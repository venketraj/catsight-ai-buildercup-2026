"""RAG-first treaty ingestion and extraction - FR-INGEST-1/2, Phase 2.

Two stages, replacing "send the whole PDF to Gemini and ask for every term":

**Ingest** (once per wording)
  1. Split the PDF into clause chunks with page numbers (`ingest.chunking`).
  2. Pages with no text layer - the scanned endorsement - are transcribed by
     Gemini once and stored as chunks marked `source="transcription"`.
  3. Embed every chunk (`gemini-embedding-001`, 768 dims, RETRIEVAL_DOCUMENT)
     and store it in the vector store (Firestore vector search in GCP).

**Extract** (per term group, in parallel)
  For each group of related terms - layers, hours clause, perils, territory,
  period, currency, reinstatements, exclusions - retrieve the top clauses for
  that treaty (equality pre-filter on `treaty_id`, C-11) and ask Gemini to
  read ONLY those clauses. Every answer names the `chunk_id` it came from and
  quotes it; the quote is checked against that chunk before it is accepted.
  A citation is therefore verifiable by construction, not located afterwards.

Endorsement chunks are added to every group's context regardless of rank:
an endorsement can amend any term, and FR-ENDORSE-3 makes it operative, so a
retrieval miss on it would silently keep a superseded value.

Small calls with `thinking_level=LOW` and a request timeout, run in parallel,
instead of one long whole-document call per treaty.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from catsight_agent.schemas import GroundedAnswer, TreatyTerms, gemini_response_schema
from catsight_agent.tools.retrieval import (
    Embedder,
    VectorStore,
    index_chunks,
    search_treaty_clauses,
)
from catsight_agent.tools.verify import match_quote
from ingest.chunking import Chunk, chunk_pdf, page_texts
from ingest.ingest_treaty import (
    ExtractionOutcome,
    _first_error_line,
    _generate_with_retry,
    flatten_payload,
)
from ingest.provenance import check_field_citations, required_citation_fields

__all__ = [
    "TermGroup",
    "TERM_GROUPS",
    "GROUP_OF_FIELD",
    "IngestResult",
    "GroupResult",
    "RagOutcome",
    "generation_config",
    "transcribe_image_pages",
    "ingest_wording",
    "extract_group",
    "assemble_payload",
    "extract_treaty_rag",
]


# --------------------------------------------------------------------------- #
# Model call configuration
# --------------------------------------------------------------------------- #


def generation_config(schema: Any | None = None) -> Any:
    """JSON output, temperature 0, thinking LOW (RESEARCH_FINDINGS C9:
    thinking cannot be turned off on Flash, and it bills as output)."""
    from google.genai import types

    kwargs: dict[str, Any] = {
        "temperature": 0,
        "thinking_config": types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        # No tools are passed, so automatic function calling has nothing to
        # do; disabling it explicitly also silences the SDK's AFC warning.
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
    }
    if schema is not None:
        kwargs["response_mime_type"] = "application/json"
        kwargs["response_schema"] = gemini_response_schema(schema)
    return types.GenerateContentConfig(**kwargs)


# --------------------------------------------------------------------------- #
# Term groups
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TermGroup:
    name: str
    #: Phrased as the clause would read - the embedder is semantic.
    query: str
    #: A ranking preference, never a filter (see `search_treaty_clauses`).
    clause_type: str | None
    #: The fields to return and how to express them.
    instruction: str
    #: Dotted field prefixes this group is responsible for.
    prefixes: tuple[str, ...]


TERM_GROUPS: tuple[TermGroup, ...] = (
    TermGroup(
        "scope",
        "business covered by this agreement, excess of loss or quota share reinsurance, "
        "the perils covered such as windstorm, earthquake and flood",
        None,
        """\
  type     "CAT_XL" for excess of loss, "QS" for quota share
  perils   the COVERED perils as codes, comma-separated: WS (windstorm/typhoon),
           EQ (earthquake), FL (flood), OTHER. Only perils the agreement covers -
           not perils that are merely mentioned, defined or excluded.""",
        ("type", "perils"),
    ),
    TermGroup(
        "territory",
        "territorial scope, which territories and regions are covered or carved out",
        "TERRITORY",
        """\
  territory.include  covered countries as ISO-3166 alpha-3 codes, comma-separated
  territory.exclude  carved-out areas, comma-separated: a whole country as its
                     alpha-3 code, a region or prefecture as its ISO 3166-2
                     subdivision code (e.g. Okinawa Prefecture is JP-47). If the
                     wording states that nothing is carved out, return an empty
                     value "" and quote that statement.""",
        ("territory.",),
    ),
    TermGroup(
        "period",
        "period of the agreement, inception and expiry dates",
        "PERIOD",
        """\
  inception  start date as YYYY-MM-DD
  expiry     end date as YYYY-MM-DD""",
        ("inception", "expiry"),
    ),
    TermGroup(
        "currency",
        "currency of the agreement, the currency in which amounts are expressed and settled",
        None,
        """\
  currency   ISO-4217 code, e.g. USD""",
        ("currency",),
    ),
    TermGroup(
        "limits",
        "limit and retention per loss occurrence for each layer, schedule of layers "
        "and premium; quota share cession percentage and event limit",
        "LIMIT",
        """\
  For an excess of loss agreement, per layer N (1, 2, 3...):
    layers.N.retention   the attachment point, in MILLIONS of currency
    layers.N.limit       the maximum the reinsurers pay per loss occurrence, in
                         MILLIONS, exactly as written. NOT the top of the layer:
                         "exceeds 10.0 but not more than 20.0" is limit 20.0.
    layers.N.premium     the layer premium in MILLIONS
  Layers are contiguous: each retention equals the previous retention plus the
  previous limit. Check this before answering.
  For a quota share agreement instead:
    qs.cession_pct       the ceded share as a decimal (30% is 0.3)
    qs.event_limit       the per-event limit in MILLIONS""",
        ("layers.", "qs."),
    ),
    TermGroup(
        "reinstatements",
        "reinstatement of the limit, number of reinstatements, reinstatement premium and its basis",
        "REINSTATEMENT",
        """\
  reinstatements.count  number of reinstatements as an integer
  reinstatements.rate   reinstatement premium rate as a decimal (100% is 1.0,
                        free reinstatement is 0)
  reinstatements.basis  exactly one of: "pro rata as to amount", "pro rata as to
                        time", "pro rata as to amount and time", "full\"""",
        ("reinstatements.",),
    ),
    TermGroup(
        "hours",
        "loss occurrence definition, the number of consecutive hours within which "
        "individual losses are treated as one event, for windstorm, earthquake and flood",
        "HOURS",
        """\
  hours_clause.WS  hours for windstorm, integer
  hours_clause.EQ  hours for earthquake, integer
  hours_clause.FL  hours for flood, integer
  Report the period the loss occurrence definition STATES for each peril,
  whether or not that peril is covered. Use 0 only where the wording states no
  period for that peril, and quote the clause that shows it. Ignore notice
  periods and other clauses that mention hours without defining an occurrence.
  If an ENDORSEMENT changes a period, the endorsed value is operative. Then
  also return:
    endorsement.overrides   the field it changes, e.g. hours_clause.WS
    <that field>.base       the value the BODY stated, citing the body clause""",
        ("hours_clause.", "endorsement."),
    ),
    TermGroup(
        "exclusions",
        "excluded perils and causes of loss, war, nuclear, cyber, storm surge, flood written as such",
        "EXCLUSION",
        """\
  exclusions  the excluded PERILS and causes of loss as short tags,
              comma-separated, from: war, nuclear, cyber, storm surge,
              earthquake, flood when written as such, terrorism, pollution,
              communicable disease. Use "<peril> when written as such" only for
              a conditional exclusion. Not classes of business, not sanctions.
              A sentence confirming that a peril IS covered ("for the avoidance
              of doubt, X is covered") is a carve-back, not an exclusion - leave
              that peril out.""",
        ("exclusions",),
    ),
)


def _group_of_field(name: str) -> str | None:
    base = name.removesuffix(".base")
    for group in TERM_GROUPS:
        if any(base == p or base.startswith(p) for p in group.prefixes):
            return group.name
    return None


#: Truth field -> group, for the retrieval hit-rate metric.
GROUP_OF_FIELD = _group_of_field

_PREAMBLE = """\
You are reading clauses retrieved from reinsurance treaty {treaty_id}. Use ONLY
the clauses below. Each starts with its chunk_id in square brackets.

For each field below that the clauses state, return:
  field     the field name exactly as listed
  value     the value as a string, formatted as described
  chunk_id  the chunk_id of the clause that states it
  quote     the EXACT words from that clause that state the value - 5 to 40
            whole words, copied character for character, never paraphrased,
            never joined from two places. It is string-matched against the
            clause; a quote that does not match is discarded.

Omit a field the clauses do not state rather than guessing. Many clauses
mention numbers, hours or places without governing the term - extract only
from the clause that governs it. An endorsement overrides the body.

FIELDS
{fields}

CLAUSES
{clauses}
"""


def _render_clause(chunk: Chunk) -> str:
    label = f"page {chunk.page}, clause {chunk.clause_no or '-'}"
    if chunk.clause_title:
        label += f", {chunk.clause_title}"
    if chunk.source == "transcription":
        label += ", transcribed from a scanned page"
    return f"[{chunk.chunk_id}] ({label})\n{chunk.text}"


# --------------------------------------------------------------------------- #
# Ingest
# --------------------------------------------------------------------------- #

TRANSCRIBE_INSTRUCTION = """\
Page {page} of this PDF is a scanned image with no text layer. Transcribe the
text on page {page} exactly as printed, word for word, preserving numbers and
clause headings. Return only the transcription, no commentary."""


def transcribe_image_pages(
    pdf_path: Path | str,
    pages: Iterable[int],
    *,
    client: Any,
    model: str,
) -> dict[int, str]:
    """Transcribe image-only pages once, so they can be chunked and searched."""
    from google.genai import types

    path = Path(pdf_path)
    out: dict[int, str] = {}
    for page in pages:
        response = _generate_with_retry(
            lambda page=page: client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(data=path.read_bytes(), mime_type="application/pdf"),
                    TRANSCRIBE_INSTRUCTION.format(page=page),
                ],
                config=generation_config(),
            )
        )
        text = (response.text or "").strip()
        if text:
            out[page] = text
    return out


@dataclass
class IngestResult:
    treaty_id: str
    chunks: tuple[Chunk, ...]
    texts: list[str]
    transcribed_pages: tuple[int, ...]

    @property
    def endorsements(self) -> tuple[Chunk, ...]:
        return tuple(
            c for c in self.chunks
            if c.source == "transcription"
            or (c.clause_title or "").strip().lower().startswith(("endorsement", "addendum"))
        )


def _image_pages(texts: Sequence[str], threshold: int = 120) -> list[int]:
    from ingest.chunking import _strip_running_furniture

    return [
        index for index, text in enumerate(texts, start=1)
        if len(_strip_running_furniture(text).strip()) < threshold
    ]


def ingest_wording(
    treaty_id: str,
    pdf_path: Path | str,
    *,
    client: Any,
    model: str,
    embedder: Embedder,
    store: VectorStore,
) -> IngestResult:
    """Chunk, transcribe image pages, embed and store one wording."""
    texts = page_texts(pdf_path)
    image_pages = _image_pages(texts)
    transcriptions = (
        transcribe_image_pages(pdf_path, image_pages, client=client, model=model)
        if image_pages
        else {}
    )
    chunks = chunk_pdf(treaty_id, pdf_path, transcriptions=transcriptions)
    index_chunks(chunks, store=store, embedder=embedder)
    return IngestResult(treaty_id, chunks, texts, tuple(sorted(transcriptions)))


# --------------------------------------------------------------------------- #
# Extract
# --------------------------------------------------------------------------- #


@dataclass
class GroupResult:
    group: str
    retrieved: tuple[str, ...]
    #: Accepted answers: field, value, chunk_id, quote, page, clause_no, source.
    accepted: list[dict[str, Any]] = field(default_factory=list)
    #: (field, reason) for answers discarded by the grounding check.
    rejected: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None


#: Stored citations are capped (`FieldCitation.quote`).
QUOTE_LIMIT = 300


def _bounded(quote: str, limit: int = QUOTE_LIMIT) -> str:
    """A verified quote, cut to whole words within `limit`. A word-aligned
    prefix of a matching quote still matches, so verification survives."""
    words, kept = quote.split(), []
    for word in words:
        if len(" ".join(kept + [word])) > limit:
            break
        kept.append(word)
    return " ".join(kept) if kept else quote[:limit]


def _quote_page(chunk: Chunk, quote: str, texts: Sequence[str]) -> int:
    """The page a quote is on. A clause can span pages; the citation names
    the page the quoted words actually appear on."""
    for page in chunk.pages_spanned or (chunk.page,):
        if 1 <= page <= len(texts) and match_quote(quote, texts[page - 1]).ok:
            return page
    return chunk.page


def extract_group(
    treaty_id: str,
    group: TermGroup,
    *,
    client: Any,
    model: str,
    embedder: Embedder,
    store: VectorStore,
    texts: Sequence[str],
    endorsements: Sequence[Chunk] = (),
    k: int = 4,
) -> GroupResult:
    """Retrieve clauses for one term group and read the terms from them."""
    from google.genai import types  # noqa: F401 - ensures the SDK is present

    hits = search_treaty_clauses(
        group.query,
        store=store,
        embedder=embedder,
        treaty_id=treaty_id,
        limit=k,
        clause_type=group.clause_type,
    )
    context: dict[str, Chunk] = {h.chunk.chunk_id: h.chunk for h in hits}
    for chunk in endorsements:
        context.setdefault(chunk.chunk_id, chunk)
    result = GroupResult(group.name, tuple(context))

    prompt = _PREAMBLE.format(
        treaty_id=treaty_id,
        fields=group.instruction,
        clauses="\n\n".join(_render_clause(c) for c in context.values()),
    )

    def ask(text: str) -> GroundedAnswer:
        response = _generate_with_retry(
            lambda: client.models.generate_content(
                model=model, contents=text, config=generation_config(GroundedAnswer)
            )
        )
        return GroundedAnswer.model_validate(json.loads(response.text or "{}"))

    try:
        answer = ask(prompt)
    except Exception as exc:  # noqa: BLE001 - recorded; the fields stay missing
        result.error = f"{type(exc).__name__}: {exc}"
        return result
    rejected = _ground(answer, group, context, texts, result)

    # One retry for answers that failed the grounding check, told exactly what
    # failed. Never more: a value that cannot be quoted after a targeted second
    # attempt stays missing rather than being retried until something matches.
    if rejected:
        notes = "\n".join(f"  {name}: {reason}" for name, reason in rejected)
        retry = (
            f"{prompt}\nYOUR PREVIOUS ANSWER FOR THESE FIELDS WAS REJECTED:\n{notes}\n"
            "Answer ONLY these fields again. Copy the quote character for character "
            "from the clause you cite, as one continuous passage."
        )
        try:
            wanted = {name for name, _ in rejected}
            again = ask(retry)
            again.fields = [f for f in again.fields if f.field in wanted]
            _ground(again, group, context, texts, result, retry=True)
        except Exception as exc:  # noqa: BLE001 - the first answer stands
            result.error = f"retry failed: {type(exc).__name__}: {exc}"
    return result


def _ground(
    answer: GroundedAnswer,
    group: TermGroup,
    context: Mapping[str, Chunk],
    texts: Sequence[str],
    result: GroupResult,
    *,
    retry: bool = False,
) -> list[tuple[str, str]]:
    """Apply the grounding check; accepted answers go into `result`. Returns
    the answers rejected in this pass (field, reason)."""
    rejected: list[tuple[str, str]] = []
    for item in answer.fields:
        if _group_of_field(item.field) != group.name:
            reason = f"not a {group.name} field"
        elif item.chunk_id not in context:
            reason = f"cites {item.chunk_id}, which was not retrieved"
        else:
            chunk = context[item.chunk_id]
            outcome = match_quote(item.quote, chunk.text)
            if outcome.ok:
                quote = _bounded(item.quote)
                result.accepted.append({
                    "field": item.field,
                    "value": item.value,
                    "chunk_id": chunk.chunk_id,
                    "quote": quote,
                    "page": _quote_page(chunk, quote, texts),
                    "clause_no": chunk.clause_no,
                    "source": chunk.source,
                    "retried": retry,
                })
                continue
            reason = f"quote not in {item.chunk_id}: {outcome.reason}"
        rejected.append((item.field, reason))
        result.rejected.append((item.field, ("after retry: " if retry else "") + reason))
    return rejected


# --------------------------------------------------------------------------- #
# Assembly - typed, deterministic, no model involved
# --------------------------------------------------------------------------- #

_INT_FIELDS = ("hours_clause.", "reinstatements.count")
_LIST_FIELDS = ("perils", "territory.include", "territory.exclude", "exclusions")


def _as_list(value: str) -> list[str]:
    text = value.strip()
    if text.startswith("["):
        try:
            return [str(v).strip() for v in json.loads(text) if str(v).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip().strip("\"'") for part in text.split(",") if part.strip()]


def _typed(name: str, value: str) -> Any:
    base = name.removesuffix(".base")
    if base in _LIST_FIELDS:
        items = _as_list(value)
        return [i.upper() for i in items] if base != "exclusions" else [i.lower() for i in items]
    if name == "endorsement.overrides":
        return value.strip()
    if any(base.startswith(p) for p in _INT_FIELDS):
        return int(float(value))
    if base.startswith(("layers.", "qs.")) or base == "reinstatements.rate":
        return value.strip()
    if base in ("type", "currency"):
        return value.strip().upper()
    return value.strip()


def assemble_payload(treaty_id: str, accepted: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a `TreatyTerms`-shaped payload from grounded answers.

    The signed line (`our_share`) is a booking fact, not a wording term - the
    book holds it - so it is set to 0 here rather than invented.
    """
    values: dict[str, Any] = {}
    field_pages: list[dict[str, Any]] = []
    for item in accepted:
        try:
            values[item["field"]] = _typed(item["field"], item["value"])
        except (TypeError, ValueError):
            continue
        field_pages.append({
            "field": item["field"],
            "page": item["page"],
            "clause_no": item.get("clause_no"),
            "source": item.get("source") or "text",
            "quote": item["quote"],
        })

    payload: dict[str, Any] = {
        "treaty_id": treaty_id,
        "cedent": "unknown",
        "field_pages": field_pages,
    }
    for key in ("type", "perils", "inception", "expiry", "currency", "exclusions"):
        if key in values:
            payload[key] = values[key]
    territory = {
        side: values[f"territory.{side}"]
        for side in ("include", "exclude")
        if f"territory.{side}" in values
    }
    if territory:
        payload["territory"] = territory

    hours = {p: values[f"hours_clause.{p}"] for p in ("WS", "EQ", "FL") if f"hours_clause.{p}" in values}
    if hours:
        payload["hours_clause"] = {"WS": 0, "EQ": 0, "FL": 0, "OTHER": 0, **hours}

    reinstatements = {
        "count": values.get("reinstatements.count", 0),
        "rate": values.get("reinstatements.rate", "0"),
    }
    if "reinstatements.basis" in values:
        reinstatements["basis"] = values["reinstatements.basis"]

    numbers = sorted({
        int(name.split(".")[1]) for name in values
        if name.startswith("layers.") and name.split(".")[1].isdigit()
    })
    layers = []
    for n in numbers:
        layer = {
            "layer_no": n,
            "retention": values.get(f"layers.{n}.retention"),
            "limit": values.get(f"layers.{n}.limit"),
            "premium": values.get(f"layers.{n}.premium", "0"),
            "our_share": "0",
            "reinstatements": dict(reinstatements),
        }
        layers.append({k: v for k, v in layer.items() if v is not None})
    if layers:
        payload["layers"] = layers

    if "qs.cession_pct" in values:
        payload["qs"] = {
            "cession_pct": values["qs.cession_pct"],
            "event_limit": values.get("qs.event_limit"),
            "our_share": "0",
        }

    overrides = values.get("endorsement.overrides")
    if overrides:
        endorsed_page = next(
            (fp["page"] for fp in field_pages if fp["field"] == overrides), None
        )
        payload["endorsement"] = {
            "overrides": overrides,
            "base_value": _str(values.get(f"{overrides}.base")),
            "endorsed_value": _str(values.get(overrides)),
            "source": _str(endorsed_page),
        }
    return payload


def _str(value: Any) -> str | None:
    return None if value is None else str(value)


@dataclass
class RagOutcome:
    """An `ExtractionOutcome` plus what retrieval did, for measurement."""

    outcome: ExtractionOutcome
    groups: dict[str, GroupResult]
    seconds: float


def extract_treaty_rag(
    ingested: IngestResult,
    *,
    client: Any,
    model: str,
    embedder: Embedder,
    store: VectorStore,
    k: int = 4,
    workers: int = len(TERM_GROUPS),
) -> RagOutcome:
    """Extract every term group for one ingested wording, in parallel."""
    started = time.monotonic()
    treaty_id = ingested.treaty_id

    def run(group: TermGroup) -> GroupResult:
        return extract_group(
            treaty_id, group, client=client, model=model, embedder=embedder,
            store=store, texts=ingested.texts, endorsements=ingested.endorsements, k=k,
        )

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        groups = {g.group: g for g in pool.map(run, TERM_GROUPS)}

    accepted = [item for g in groups.values() for item in g.accepted]
    payload = assemble_payload(treaty_id, accepted)
    flattened = flatten_payload(payload)
    provenance = check_field_citations(
        treaty_id,
        payload["field_pages"],
        required_citation_fields(flattened),
        ingested.texts,
        ingested.chunks,
    )

    try:
        terms = TreatyTerms.model_validate(payload)
        outcome = ExtractionOutcome(
            treaty_id=treaty_id, terms=terms, fields=flattened,
            pages=terms.pages_by_field(), chunks=ingested.chunks, provenance=provenance,
        )
    except Exception as exc:  # noqa: BLE001 - FR-INGEST-3 quarantine
        outcome = ExtractionOutcome(
            treaty_id=treaty_id, terms=None, fields=flattened,
            pages={fp["field"]: fp["page"] for fp in payload["field_pages"]},
            chunks=ingested.chunks, validation_error=_first_error_line(exc),
            provenance=provenance,
        )
    return RagOutcome(outcome, groups, time.monotonic() - started)


def default_model() -> str:
    return os.environ.get("MODEL_MAIN") or "gemini-3.5-flash-lite"
