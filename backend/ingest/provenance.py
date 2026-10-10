"""Field-level provenance checks for extracted treaty terms - QA-4, C-7.

The extractor cites a page, a clause and a verbatim quote for every field it
returns. A citation is only as good as the check behind it, so each one is
tested here, deterministically, against the PDF's own text layer:

  * **verified**     the quote appears, word-aligned, on the cited page.
  * **transcribed**  the cited page has no text layer (a scanned endorsement)
                     and the extractor said it read the page as an image. The
                     quote cannot be string-matched, so it is labelled as a
                     transcription rather than passed off as verified.
  * **unverified**   a citation exists but fails the check - the reason says
                     which part was wrong.
  * **missing**      no citation at all.

Only the first two may be shown as fact. The other two drive the targeted
follow-up request in `ingest_treaty`, and anything still failing after that is
labelled in the output rather than silently trusted.

The clause number is checked too, but softly: when the quote is on the cited
page under a different clause heading, the citation is kept and the clause
corrected from the chunk that actually contains it. A wrong clause number on
the right page is a labelling slip; a quote that is not on the page is not a
citation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal, Mapping, Sequence

from catsight_agent.tools.verify import match_quote
from ingest.chunking import Chunk

__all__ = [
    "Status",
    "FieldProvenance",
    "ProvenanceReport",
    "SHOWABLE",
    "required_citation_fields",
    "check_field_citations",
]

Status = Literal["verified", "transcribed", "unverified", "missing"]

#: Statuses a report may present as a sourced fact.
SHOWABLE: frozenset[str] = frozenset({"verified", "transcribed"})

#: Below this many characters a page is treated as having no text layer.
#: Matches `chunking.chunk_pdf`'s default so the two agree on which pages are
#: images.
IMAGE_PAGE_THRESHOLD = 120

#: Bookkeeping keys produced by `flatten_payload` that are not treaty terms
#: and so carry no citation of their own.
_NOT_CITED = frozenset({"endorsement.overrides"})


@dataclass(frozen=True)
class FieldProvenance:
    """The outcome of checking one field's citation."""

    field: str
    status: Status
    page: int | None = None
    clause_no: str | None = None
    quote: str | None = None
    reason: str | None = None

    @property
    def showable(self) -> bool:
        return self.status in SHOWABLE


@dataclass
class ProvenanceReport:
    """Every required field's provenance for one treaty."""

    treaty_id: str
    fields: dict[str, FieldProvenance] = field(default_factory=dict)

    def by_status(self, status: Status) -> list[str]:
        return sorted(name for name, p in self.fields.items() if p.status == status)

    @property
    def failing(self) -> list[str]:
        """Fields needing a follow-up: unverified or missing."""
        return sorted(name for name, p in self.fields.items() if not p.showable)

    @property
    def total(self) -> int:
        return len(self.fields)

    @property
    def showable_count(self) -> int:
        return sum(1 for p in self.fields.values() if p.showable)

    @property
    def coverage(self) -> float:
        return self.showable_count / self.total if self.total else 1.0

    def to_json(self) -> dict:
        return {
            name: {
                "status": p.status,
                "page": p.page,
                "clause_no": p.clause_no,
                "quote": p.quote,
                "reason": p.reason,
            }
            for name, p in sorted(self.fields.items())
        }


def required_citation_fields(flattened: Mapping[str, object]) -> list[str]:
    """The fields that must carry a citation: every extracted term."""
    return sorted(name for name in flattened if name not in _NOT_CITED)


def _last_citation_per_field(entries: Iterable[Mapping]) -> dict[str, Mapping]:
    """Last entry wins, matching `TreatyTerms.pages_by_field`: an endorsed
    field restated later resolves to the endorsement's citation."""
    out: dict[str, Mapping] = {}
    for entry in entries:
        if isinstance(entry, Mapping) and entry.get("field"):
            out[str(entry["field"])] = entry
    return out


def _clause_on_page(chunks: Sequence[Chunk], page: int, quote: str) -> str | None:
    """The clause whose chunk on `page` contains `quote`, if any."""
    for chunk in chunks:
        pages = chunk.pages_spanned or (chunk.page,)
        if page in pages and match_quote(quote, chunk.text).ok:
            return chunk.clause_no
    return None


def _check_one(
    name: str,
    entry: Mapping | None,
    page_texts: Sequence[str],
    chunks: Sequence[Chunk],
) -> FieldProvenance:
    if entry is None:
        return FieldProvenance(name, "missing", reason="no citation was returned")

    page = entry.get("page")
    clause_no = entry.get("clause_no")
    quote = (entry.get("quote") or "").strip() or None
    source = entry.get("source") or "text"

    if not isinstance(page, int) or not 1 <= page <= len(page_texts):
        return FieldProvenance(
            name, "unverified", page if isinstance(page, int) else None, clause_no, quote,
            reason=f"page {page!r} is outside the document (1-{len(page_texts)})",
        )

    text = page_texts[page - 1]
    if len(text.strip()) < IMAGE_PAGE_THRESHOLD:
        # An image-only page: nothing to string-match, so the honest label is
        # "transcribed" - and only when the extractor said it read the image.
        if source == "transcription" and quote:
            return FieldProvenance(name, "transcribed", page, clause_no, quote)
        return FieldProvenance(
            name, "unverified", page, clause_no, quote,
            reason=f"page {page} has no text layer and the citation is not marked "
            "as a transcription with a quote",
        )

    if not quote:
        return FieldProvenance(
            name, "unverified", page, clause_no, None,
            reason="the citation has no quote, so it cannot be checked",
        )

    outcome = match_quote(quote, text)
    if not outcome.ok:
        return FieldProvenance(
            name, "unverified", page, clause_no, quote,
            reason=f"not found on page {page}: {outcome.reason}",
        )

    actual_clause = _clause_on_page(chunks, page, quote)
    return FieldProvenance(name, "verified", page, actual_clause or clause_no, quote)


def check_field_citations(
    treaty_id: str,
    field_pages: Iterable[Mapping],
    required: Iterable[str],
    page_texts: Sequence[str],
    chunks: Sequence[Chunk] = (),
) -> ProvenanceReport:
    """Check every required field's citation against the PDF text."""
    cited = _last_citation_per_field(field_pages)
    report = ProvenanceReport(treaty_id)
    for name in required:
        report.fields[name] = _check_one(name, cited.get(name), page_texts, chunks)
    return report
