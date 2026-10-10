"""Clause-aware PDF chunking — FR-INGEST-2.

Splits a treaty wording into retrievable chunks, **by clause where possible
and by page as a fallback**, recording for each chunk the page it starts on,
its clause number and title, and a classified clause type.

Why clause boundaries rather than fixed-size windows: every wording flag has
to cite a clause number and a page (C-7), and the verifier quote-matches
against the stored chunk text (FR-VERIFY-1). A chunk that straddles two
clauses can produce a quote that verifies against the chunk but cites the
wrong clause - which is worse than failing, because it looks correct.

Page attribution: a clause can span a page break, so each chunk records the
page its heading appeared on, which is the page a citation should point at.
`pages_spanned` is kept so a long clause can still be rendered in context.

No I/O beyond reading the PDF's text, and no model calls: chunking is
deterministic, so the same wording always produces the same chunk ids and
retrieval results are reproducible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

__all__ = [
    "Chunk",
    "CLAUSE_TYPE_KEYWORDS",
    "classify_clause",
    "page_texts",
    "chunk_pages",
    "chunk_pdf",
]

#: A clause heading as rendered by build_wordings: "5. Loss Occurrence",
#: "16.2. Salvage and Subrogation". Anchored to the start of a line so a
#: cross-reference mid-sentence ("subject to Clause 5") is not mistaken for a
#: heading.
_HEADING = re.compile(
    r"^(?P<number>\d{1,2}(?:\.\d{1,2})?)\.\s+(?P<title>[A-Z][^\n]{2,80})$",
    re.MULTILINE,
)

#: Keyword to clause type. Ordered: the first match wins, so the more specific
#: families are listed before the general ones.
CLAUSE_TYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("HOURS", ("loss occurrence", "hours clause", "consecutive hours")),
    ("REINSTATEMENT", ("reinstatement",)),
    ("TERRITORY", ("territorial", "territory")),
    ("PERIOD", ("period", "extended expiration")),
    ("LIMIT", ("limit and retention", "cession and event limit", "limit", "retention")),
    ("EXCLUSION", ("exclusion", "excluded", "sanctions")),
)


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage."""

    treaty_id: str
    chunk_id: str
    page: int
    clause_no: str | None
    clause_title: str | None
    clause_type: str
    text: str
    pages_spanned: tuple[int, ...] = ()
    #: `transcription` for a page with no text layer, so the verifier can
    #: badge it distinctly (FR-ENDORSE-3).
    source: str = "text"

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError(f"{self.chunk_id}: a chunk cannot be empty")
        if self.page < 1:
            raise ValueError(f"{self.chunk_id}: page must be >= 1")


#: Phrases specific enough to classify from the body when a chunk has no
#: heading. Deliberately narrow. Every decoy in `wording_clauses` says
#: "within 72 hours of", "settle within 168 hours" and so on - none says
#: "consecutive hours", which is the operative phrase in a loss-occurrence
#: definition. That makes it a safe discriminator where a bare "hours" is not.
BODY_PHRASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("HOURS", ("consecutive hours", "loss occurrence means", "loss occurrence, as respects")),
    ("REINSTATEMENT", ("automatically reinstated", "reinstatement premium")),
    ("TERRITORY", ("territorial scope",)),
)


#: Headings that describe a document's structure rather than its subject
#: matter. "Definitions" and "Endorsement" tell you nothing about what the
#: clause governs, so for these the body is the better signal - and W8's
#: operative hours clause and the scanned endorsement's override both live
#: under exactly such a heading.
_STRUCTURAL_TITLES = ("definition", "endorsement", "schedule", "interpretation")


def _is_structural(title: str) -> bool:
    flat = title.strip().lower()
    return any(flat.startswith(prefix) for prefix in _STRUCTURAL_TITLES)


def classify_clause(title: str | None, text: str) -> str:
    """Classify a clause for the `clause_type` filter.

    **Classified from the heading, not the body.** A heading is the drafter's
    own classification; body keywords are noise, and the decoys are built
    precisely to exploit that. "Inspection of Records" mentions a period,
    "Loss Advices and Cash Calls" mentions a retention, "Definition: Business
    Day" mentions territory - all would be misclassified by a body match, and
    FR-WORD's retrieval would then pull them as if they were material.

    Where a chunk has no heading - the page-fallback path - the body is used,
    but only against `BODY_PHRASES`, which is narrow enough not to fire on a
    decoy.

    `clause_type` is a **hint, not a gate.** W8 hides its hours clause inside
    a clause titled "Definitions", so it classifies as OTHER; retrieval that
    filtered hard on `clause_type == "HOURS"` would miss it entirely. That is
    why FR-WORD retrieves by vector similarity and treats this field as a
    filter of convenience.
    """
    if title and not _is_structural(title):
        haystack = title.lower()
        for clause_type, keywords in CLAUSE_TYPE_KEYWORDS:
            if any(keyword in haystack for keyword in keywords):
                return clause_type
        return "OTHER"

    haystack = text[:600].lower()
    for clause_type, phrases in BODY_PHRASES:
        if any(phrase in haystack for phrase in phrases):
            return clause_type
    return "OTHER"


def page_texts(pdf_path: Path | str) -> list[str]:
    """Extracted text per page, 0-indexed. Empty string for an image-only page."""
    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    return [(page.extract_text() or "") for page in reader.pages]


def _strip_running_furniture(text: str) -> str:
    """Drop the header and footer build_wordings stamps on every page.

    Left in, they appear in every chunk and pollute both the embeddings and
    any quote the verifier tries to match.
    """
    lines = []
    for line in text.splitlines():
        flat = line.strip()
        if not flat:
            continue
        if flat.startswith("Page ") and len(flat) < 40:
            continue
        if "Synthetic - no legal effect" in flat or "Synthetic — no legal effect" in flat:
            continue
        lines.append(line)
    return "\n".join(lines)


def chunk_pages(
    treaty_id: str,
    pages: Sequence[str],
    *,
    image_only_pages: Iterable[int] = (),
    transcriptions: dict[int, str] | None = None,
    min_text_chars: int = 120,
) -> tuple[Chunk, ...]:
    """Split extracted page texts into clause chunks.

    `image_only_pages` are 1-based page numbers with no usable text layer. If
    a transcription is supplied for one it becomes a chunk marked
    `source="transcription"`; without one the page is skipped rather than
    yielding an empty chunk, and the caller is responsible for noticing - a
    silently dropped endorsement is how an override gets missed.
    """
    transcriptions = transcriptions or {}
    image_only = set(image_only_pages)

    # Locate every clause heading, with the page it appeared on.
    headings: list[tuple[int, int, str, str]] = []  # (page, offset, number, title)
    cleaned: dict[int, str] = {}
    for index, raw in enumerate(pages, start=1):
        if index in image_only:
            continue
        text = _strip_running_furniture(raw)
        cleaned[index] = text
        for match in _HEADING.finditer(text):
            headings.append(
                (index, match.start(), match.group("number"), match.group("title").strip())
            )

    chunks: list[Chunk] = []

    if headings:
        for position, (page, offset, number, title) in enumerate(headings):
            # The body starts at the heading, so it is never empty.
            body = _clause_body(cleaned, headings, position, page, offset)
            spanned = _pages_spanned(page, headings, position, cleaned)
            chunks.append(
                Chunk(
                    treaty_id=treaty_id,
                    chunk_id=f"{treaty_id}#c{number}",
                    page=page,
                    clause_no=number,
                    clause_title=title,
                    clause_type=classify_clause(title, body),
                    text=body.strip(),
                    pages_spanned=spanned,
                )
            )
    else:
        # Fallback: no headings found, so chunk by page (FR-INGEST-2).
        for page, text in cleaned.items():
            if len(text.strip()) < min_text_chars:
                continue
            chunks.append(
                Chunk(
                    treaty_id=treaty_id,
                    chunk_id=f"{treaty_id}#p{page}",
                    page=page,
                    clause_no=None,
                    clause_title=None,
                    clause_type=classify_clause(None, text),
                    text=text.strip(),
                    pages_spanned=(page,),
                )
            )

    # Image-only pages with a transcription.
    for page in sorted(image_only):
        transcribed = transcriptions.get(page, "").strip()
        if not transcribed:
            continue
        chunks.append(
            Chunk(
                treaty_id=treaty_id,
                chunk_id=f"{treaty_id}#t{page}",
                page=page,
                clause_no="END-1",
                clause_title="Endorsement",
                clause_type=classify_clause("Endorsement", transcribed),
                text=transcribed,
                pages_spanned=(page,),
                source="transcription",
            )
        )

    return tuple(chunks)


def _clause_body(
    cleaned: dict[int, str],
    headings: Sequence[tuple[int, int, str, str]],
    position: int,
    page: int,
    offset: int,
) -> str:
    """Text from this heading to the next, across page boundaries."""
    if position + 1 < len(headings):
        next_page, next_offset, _, _ = headings[position + 1]
    else:
        next_page, next_offset = max(cleaned), len(cleaned[max(cleaned)])

    if next_page == page:
        return cleaned[page][offset:next_offset]

    parts = [cleaned[page][offset:]]
    for between in range(page + 1, next_page):
        if between in cleaned:  # skip an image-only page mid-clause
            parts.append(cleaned[between])
    # `next_page` is either the next heading's page or the last text page, so
    # it is always present in `cleaned`.
    parts.append(cleaned[next_page][:next_offset])
    return "\n".join(parts)


def _pages_spanned(
    page: int,
    headings: Sequence[tuple[int, int, str, str]],
    position: int,
    cleaned: dict[int, str],
) -> tuple[int, ...]:
    last = headings[position + 1][0] if position + 1 < len(headings) else max(cleaned)
    return tuple(p for p in range(page, last + 1) if p in cleaned)


def chunk_pdf(
    treaty_id: str,
    pdf_path: Path | str,
    *,
    transcriptions: dict[int, str] | None = None,
    image_text_threshold: int = 120,
) -> tuple[Chunk, ...]:
    """Chunk a wording PDF, detecting image-only pages automatically.

    A page yielding less than `image_text_threshold` characters is treated as
    image-only. The scanned endorsement produces 45 characters of footer, so
    the threshold separates it from a genuinely short text page.
    """
    pages = page_texts(pdf_path)
    image_only = [
        index
        for index, text in enumerate(pages, start=1)
        if len(_strip_running_furniture(text).strip()) < image_text_threshold
    ]
    return chunk_pages(
        treaty_id,
        pages,
        image_only_pages=image_only,
        transcriptions=transcriptions,
    )
