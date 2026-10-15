"""Treaty wording ingestion — FR-INGEST-1, the online half of S3.

Reads a wording PDF, extracts `TreatyTerms` with Gemini structured output,
chunks it, embeds the chunks, and writes both to Firestore. The offline half
(chunking, retrieval, the QA-3 harness) is already tested; this module is the
part that needs a live project, and it is deliberately thin so that most of
the logic stays in the tested modules.

## Native PDF understanding, not a text dump

The PDF goes to Gemini **as a PDF** rather than as extracted text. W4's
endorsement is a rasterised page with no text layer, so a text-only pipeline
cannot see it at all - and FR-ENDORSE-3 makes that endorsement *operative*,
overriding the 72 hours printed in the body with 168. An extractor that reads
only the text layer gets W4's hours clause confidently wrong, which is the
single most expensive error the planted set can produce.

## Two schemas, on purpose

Gemini's `Schema` has no `exclusiveMinimum`, so `TreatyTerms` cannot be sent
as `response_schema` unchanged. `gemini_response_schema()` produces a relaxed
twin for the API; `TreatyTerms.model_validate` then enforces the real
contract, including FR-INGEST-3's structural rules. See that function's
docstring - the upshot is that validation is load-bearing, because the schema
sent to the model no longer forbids a zero limit.

## Money is in millions

The answer key expresses limits, retentions and premiums in **millions of the
treaty currency** (a layer of `20.0`, not `20000000`). Left unsaid, the model
returns raw currency units and every money field scores wrong while being, in
a sense, correct. The instruction pins the unit explicitly.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from catsight_agent.schemas import CitationBatch, TreatyTerms, gemini_response_schema
from ingest.chunking import Chunk, chunk_pdf, page_texts
from ingest.provenance import (
    ProvenanceReport,
    check_field_citations,
    required_citation_fields,
)

__all__ = [
    "EXTRACTION_INSTRUCTION",
    "ExtractionOutcome",
    "build_client",
    "resolve_target",
    "extract_treaty_terms",
    "flatten_terms",
    "field_pages_of",
    "main",
]


#: FR-INGEST-1's instruction. Written against the planted features in DR-2 and
#: the decoys in `wording_clauses.DECOYS`, because the failure modes are known
#: in advance: a decoy clause that mentions a period, an endorsement that is
#: easy to miss, and an hours clause hidden under a "Definitions" heading.
EXTRACTION_INSTRUCTION = """\
You are extracting the operative terms of a reinsurance treaty wording.

Return ONLY the structured object the schema describes.

UNITS
Express `retention`, `limit`, `premium` and `event_limit` in MILLIONS of the
treaty currency. A layer written as "USD 20,000,000" is 20.0, not 20000000.
Rates and shares are decimals: 100% is 1.0.

LAYERS - READ THIS CAREFULLY
`retention` is the attachment point: the loss the reinsured keeps before the
layer pays.
`limit` is the MAXIMUM AMOUNT THE REINSURERS PAY for one loss occurrence. It
is NOT the top of the layer.

Given "the Reinsurers shall pay the amount by which the ultimate net loss
exceeds 10.0, but not more than 20.0":
    retention = 10.0
    limit     = 20.0        <- the figure as written
    (the layer is exhausted once the loss reaches 30.0)
NEVER subtract the retention from the limit. `limit = 20.0`, not 10.0.

Layers in a programme are contiguous: each layer's retention equals the
previous layer's retention plus the previous layer's limit. Check this before
you answer. If your layers are not contiguous you have misread a limit - go
back and re-read the schedule.

HOURS CLAUSE
Report, for each peril, the period the loss-occurrence definition STATES for
it - whether or not this treaty covers that peril. The hours clause is a
definition, and coverage is decided separately by the perils and exclusions.
So if the clause reads "As respects Flood, the period is 168 consecutive
hours", report FL as 168 even when Flood is not a covered peril.

Use 0 only when the wording states no period for that peril at all. A
proportional treaty with no loss-occurrence definition is 0 for every peril.

The operative number lives in the loss-occurrence definition, which may sit
under a heading such as "Definitions" or "Interpretation" rather than one
that names the hours clause.

ENDORSEMENTS OVERRIDE THE BODY
If an endorsement, addendum or schedule amends a term, the ENDORSED value is
the operative one.

You must do BOTH of these, not just the first:
  1. Put the endorsed value in the field itself.
  2. Fill the `endorsement` object, which records what was replaced:
       "endorsement": {
         "overrides":      "hours_clause.WS",   <- the dotted field name
         "base_value":     "72",                <- what the BODY said
         "endorsed_value": "168",               <- the operative value
         "source":         "7"                  <- the page it came from
       }
Leaving `endorsement` empty loses the audit trail: the report would show 168
with no way to see that the body says 72 and an endorsement changed it. That
is the single most important provenance in the document.

Some endorsements are scanned images with no selectable text. Read them from
the page image. Do not skip a page because it has no text layer.

DO NOT BE MISLED
Many clauses mention hours, periods, territories or retentions without
governing them - notice provisions, inspection rights, cash-call deadlines,
business-day definitions. Extract only from the clause that actually governs
the term. A number's presence near a word is not evidence.

EXCLUSIONS
`exclusions` means PERILS AND CAUSES OF LOSS that are excluded. It does NOT
mean classes of business excluded from the cession. Facultative business,
financial guarantee business, and business written through a compulsory pool
are scope-of-business terms, not peril exclusions - leave them out.

Take them from the treaty's Exclusions clause. Return SHORT canonical tags,
not clause text. The house taxonomy is:
  war, nuclear, cyber, storm surge, earthquake, flood when written as such,
  terrorism, pollution, communicable disease
Use the tag that fits; add a short lowercase tag of your own only if none
does.

Use a "... when written as such" tag ONLY where the exclusion is CONDITIONAL
on how the original policy rates the peril. An absolute exclusion is just the
peril: "Earthquake, earthquake shock, volcanic eruption and tsunami, this
Agreement being written in respect of windstorm only" is the tag `earthquake`,
not `earthquake when written as such` - nothing about it is conditional.

A sanctions clause is NOT a peril exclusion. It limits payment where payment
would breach sanctions; it does not exclude a cause of loss. Market wordings
carry one as boilerplate - leave it out. "War, invasion, hostilities, civil war, rebellion or insurrection,
whether war be declared or not." is the tag `war`.

List EVERY exclusion the clause states, including one that also carves out
what it does not exclude. "Flood, where the original policy writes flood as a
separately rated and separately stated peril" is still an exclusion - it is
the tag `flood when written as such` - even though the same paragraph goes on
to say that flood caused by a covered windstorm is not excluded.

PROVENANCE
`field_pages` is a LIST. Add one entry per field you extract, each with:
  field      the dotted field name, exactly as the schema spells it -
             "hours_clause.WS", "layers.2.limit", "territory.include"
  page       the page number the value came from
  clause_no  the clause number, e.g. "5" or "END-1"
  source     "text" for a selectable text layer, "transcription" for a page
             you had to read as an image
  quote      the EXACT words on that page that state the value, copied
             character for character - 5 to 40 words, whole words only,
             never paraphrased, never stitched from two places. It will be
             string-matched against the page text; a quote that does not
             appear verbatim on the cited page is rejected and the value is
             shown as unverified.
Produce one entry for EVERY field in your answer, not a summary. A treaty
with four layers has twelve layer entries - layers.1.retention,
layers.1.limit, layers.1.premium, layers.2.retention, and so on. List fields
(perils, exclusions, territory.include, territory.exclude) need an entry too:
quote the sentence that enumerates them. Fields stated together in one
sentence may share the same quote. A field without an entry cannot be
checked, and an unchecked value is not usable.

If an endorsement replaced a value, also add an entry for "<field>.base"
citing where the BODY stated the superseded value, e.g. "hours_clause.WS.base".

If a value genuinely is not stated, omit the field rather than inventing one.
"""


#: The follow-up request for fields whose citation was missing or failed the
#: check. Narrow on purpose: the values are already extracted, so the model is
#: asked only to locate them, which it does far more reliably than it cites
#: thirty fields in one pass.
CITATION_REPAIR_INSTRUCTION = """\
You previously extracted terms from this reinsurance treaty wording. Some of
the citations were missing or could not be found on the page given. For each
field below, find where the wording states that value and return one citation.

Each citation needs:
  field      exactly as given below
  page       the page number where the value is stated
  clause_no  the clause number, e.g. "5" or "END-1"
  source     "text", or "transcription" if you read the page as an image
  quote      the EXACT words from that page that state the value: 5 to 40
             whole words, copied character for character, not paraphrased,
             not joined across separate passages. It will be string-matched
             against the page text.

Quote the clause that GOVERNS the value, not a clause that merely mentions a
similar number. Where an endorsement replaced a value, cite the endorsement;
a field ending in ".base" is the value the BODY stated before the endorsement.

Return ONLY the structured object the schema describes.

FIELDS TO CITE
"""


@dataclass
class ExtractionOutcome:
    """One wording's extraction, in the shape QA-3 scores.

    `terms` is None when the payload failed FR-INGEST-3, but `fields` is still
    populated from the raw payload. The two failures are different and must be
    counted differently:

      * **A wrong field** is a measurement result. It belongs in QA-3's
        accuracy figure.
      * **An FR-INGEST-3 rejection** is a refusal to ingest. In production the
        treaty is quarantined for a human, so none of its fields reach a
        report at all.

    Collapsing the second into the first by scoring every field as wrong turns
    one misread limit into 28 wrong fields and makes the accuracy number
    meaningless. Reporting only accuracy and hiding the rejection is worse: a
    97% field score with three of eight treaties quarantined is not a 97%
    system. So both numbers are produced, side by side.
    """

    treaty_id: str
    terms: TreatyTerms | None
    fields: dict[str, Any]
    pages: dict[str, int]
    chunks: tuple[Chunk, ...] = ()
    error: str | None = None
    #: Set when the payload parsed but failed FR-INGEST-3's structural rules.
    validation_error: str | None = None
    #: Per-field citation check against the PDF text (QA-4, C-7). None only
    #: when the PDF text itself could not be read.
    provenance: ProvenanceReport | None = None
    #: Set when the citation-repair request failed. Recorded, never fatal: the
    #: affected fields are already labelled unverified.
    repair_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.terms is not None

    @property
    def quarantined(self) -> bool:
        return self.validation_error is not None


def build_client(
    project: str | None = None,
    location: str | None = None,
    *,
    timeout_ms: int | None = None,
    attempts: int = 3,
) -> Any:
    """A Vertex-backed genai client, configured from the environment.

    Reads `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` so nothing here
    hardcodes a project - the rule stated in `.env.example`. Location
    defaults to `global` because Gemini 3.x is not served from us-central1.

    The defaults suit ingestion (a long timeout, transport retries). The live
    service passes a short timeout and one attempt: a visitor is waiting.
    """
    from google import genai
    from google.genai import types

    resolved_project, resolved_location = resolve_target(project, location)
    return genai.Client(  # pragma: no cover - needs a live project
        enterprise=True,
        project=resolved_project,
        location=resolved_location,
        # A hung request must fail and be retried, not wait forever (ms).
        # Transport-level retries are off by default in google-genai (C-5).
        http_options=types.HttpOptions(
            timeout=timeout_ms or REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=attempts, initial_delay=2.0),
        ),
    )


def resolve_target(
    project: str | None = None, location: str | None = None
) -> tuple[str, str]:
    """`(project, location)` from arguments then environment.

    Separate from `build_client` so it can be tested without constructing a
    real client: the resolution is the part with rules in it, and the client
    is the part that needs credentials.
    """
    resolved_project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not resolved_project:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT is not set. Copy backend/.env.example to "
            "backend/.env and fill it in."
        )
    # `global` rather than us-central1: Gemini 3.x is not served from the
    # region Cloud Run, Firestore and GCS live in.
    resolved_location = location or os.environ.get("GOOGLE_CLOUD_LOCATION") or "global"
    return resolved_project, resolved_location


#: Share of extracted fields that must carry a citation verified against the
#: PDF text. The rest are shown labelled as unverified, never as fact.
CITATION_BAR = 0.95

#: Per-request timeout for model calls. A whole-document extraction ran about
#: three minutes; a grounded group call should finish well inside this.
REQUEST_TIMEOUT_MS = 180_000


#: Retried status codes. 429 is quota, 503 is a transient backend. Both are
#: worth waiting for; a 400 is a bug in the request and must not be retried,
#: or a schema error turns into a slow schema error.
_RETRY_MARKERS = (
    "429",
    "RESOURCE_EXHAUSTED",
    "503",
    "UNAVAILABLE",
    "500",
    "INTERNAL",
    # Transport-level, seen live: the server closes the connection mid-request
    # on a large PDF. Not an answer, so it must not be scored as one.
    "Server disconnected",
    "RemoteProtocolError",
    "ConnectError",
    "ReadTimeout",
    "ConnectionReset",
)


def _is_retryable(exc: Exception) -> bool:
    text = str(exc)
    return any(marker in text for marker in _RETRY_MARKERS)


def _generate_with_retry(
    call: Any, *, attempts: int = 6, base_delay: float = 4.0
) -> Any:
    """Call Gemini, backing off on quota.

    The project's Vertex quota throttles well below eight back-to-back PDF
    requests, and an unretried 429 is indistinguishable in the QA report from
    a wrong answer - which is the worst possible confusion, because it makes a
    quota problem look like an accuracy problem. Exponential backoff with
    jitter, so a retry storm does not synchronise.
    """
    import random
    import time

    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - re-raised below
            last = exc
            if not _is_retryable(exc) or attempt == attempts - 1:
                raise
            delay = base_delay * (2**attempt) + random.uniform(0, 1.5)
            print(
                f"    quota/transient ({type(exc).__name__}); "
                f"retrying in {delay:.1f}s [{attempt + 1}/{attempts - 1}]",
                flush=True,
            )
            time.sleep(delay)
    raise last  # pragma: no cover - unreachable: the loop re-raises


def extract_treaty_terms(
    pdf_path: Path | str,
    treaty_id: str,
    *,
    client: Any,
    model: str | None = None,
    repair: bool = True,
) -> ExtractionOutcome:
    """Extract one wording. Never raises; a failure is recorded, not thrown.

    A wording that fails extraction must still appear in the QA-3 report as
    wrong rather than vanishing from the denominator - silently dropping the
    hard ones is the easiest way to a flattering score.
    """
    from google.genai import types

    model = model or os.environ.get("MODEL_MAIN") or "gemini-3.5-flash-lite"
    path = Path(pdf_path)

    try:
        response = _generate_with_retry(
            lambda: client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(
                        data=path.read_bytes(), mime_type="application/pdf"
                    ),
                    f"{EXTRACTION_INSTRUCTION}\nThe treaty_id is {treaty_id}.",
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=gemini_response_schema(TreatyTerms),
                    temperature=0,
                ),
            )
        )
        payload = json.loads(response.text or "{}")
        payload["treaty_id"] = treaty_id
    except Exception as exc:  # noqa: BLE001 - recorded, see docstring
        return ExtractionOutcome(
            treaty_id=treaty_id,
            terms=None,
            fields={},
            pages={},
            error=f"{type(exc).__name__}: {exc}",
        )

    provenance, repair_error = _check_and_repair_citations(
        payload, path, treaty_id, client=client, model=model, repair=repair
    )

    try:
        terms = TreatyTerms.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - FR-INGEST-3 rejection
        # Quarantined, not discarded. The fields are still scored so one
        # misread limit does not read as 28 wrong fields.
        return ExtractionOutcome(
            treaty_id=treaty_id,
            terms=None,
            fields=flatten_payload(payload),
            pages=_pages_from_payload(payload),
            validation_error=_first_error_line(exc),
            provenance=provenance,
            repair_error=repair_error,
        )

    return ExtractionOutcome(
        treaty_id=treaty_id,
        terms=terms,
        fields=flatten_terms(terms),
        pages=field_pages_of(terms),
        provenance=provenance,
        repair_error=repair_error,
    )


def _check_and_repair_citations(
    payload: dict,
    path: Path,
    treaty_id: str,
    *,
    client: Any,
    model: str,
    repair: bool,
) -> tuple[ProvenanceReport | None, str | None]:
    """Check every field's citation; ask once for the ones that fail.

    Mutates `payload["field_pages"]` with any repaired citations, so the
    validated `TreatyTerms` carries the corrected provenance. One repair round
    only: a field that still cannot be cited after a targeted request is
    labelled unverified rather than retried until the model says something
    that happens to match.
    """
    try:
        texts = page_texts(path)
        chunks = chunk_pdf(treaty_id, path)
    except Exception:  # noqa: BLE001 - no text, nothing to check against
        return None, None

    flattened = flatten_payload(payload)
    required = required_citation_fields(flattened)
    entries = list(payload.get("field_pages") or [])
    report = check_field_citations(treaty_id, entries, required, texts, chunks)

    if not repair or not report.failing:
        return report, None

    try:
        repaired = _request_citations(
            path, report, flattened, client=client, model=model
        )
    except Exception as exc:  # noqa: BLE001 - recorded, see ExtractionOutcome
        return report, f"{type(exc).__name__}: {exc}"

    wanted = set(report.failing)
    entries.extend(c for c in repaired if c.get("field") in wanted)
    payload["field_pages"] = entries
    return check_field_citations(treaty_id, entries, required, texts, chunks), None


def _request_citations(
    path: Path,
    report: ProvenanceReport,
    flattened: dict[str, Any],
    *,
    client: Any,
    model: str,
) -> list[dict]:
    """The targeted follow-up: values are known, only their location is asked."""
    from google.genai import types

    lines = []
    for name in report.failing:
        value = flattened.get(name)
        problem = report.fields[name].reason or "missing"
        lines.append(f"- {name} = {json.dumps(_jsonable(value))}   (previous problem: {problem})")

    response = _generate_with_retry(
        lambda: client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=path.read_bytes(), mime_type="application/pdf"),
                CITATION_REPAIR_INSTRUCTION + "\n".join(lines),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=gemini_response_schema(CitationBatch),
                temperature=0,
            ),
        )
    )
    batch = CitationBatch.model_validate(json.loads(response.text or "{}"))
    return [c.model_dump() for c in batch.citations]


def _first_error_line(exc: Exception) -> str:
    """The one line of a Pydantic error that says what is actually wrong."""
    for line in str(exc).splitlines():
        stripped = line.strip()
        if stripped.startswith("Value error,"):
            return stripped.removeprefix("Value error,").strip()
    return f"{type(exc).__name__}: {str(exc).splitlines()[0]}"


def flatten_terms(terms: TreatyTerms) -> dict[str, Any]:
    """Flatten validated terms. See `flatten_payload` for the field mapping."""
    return flatten_payload(terms.model_dump(mode="json"))


def _pages_from_payload(payload: dict) -> dict[str, int]:
    pages: dict[str, int] = {}
    for entry in payload.get("field_pages") or []:
        if isinstance(entry, dict) and entry.get("field") and entry.get("page"):
            pages[str(entry["field"])] = int(entry["page"])
    return pages


def flatten_payload(payload: dict) -> dict[str, Any]:
    """Flatten `TreatyTerms` to the dotted field names the answer key uses.

    Two shape mismatches are handled here rather than in the schema, because
    the schema's shape is the one the model and the loss engine want:

      * `reinstatements` is **per layer** in the schema and **per treaty** in
        the answer key, since every layer of a programme shares its terms.
        Layer 1's values are reported.
      * An endorsed field carries the *operative* value in its own name and
        the superseded one under `.base` - matching W4, where
        `hours_clause.WS` is 168 from the endorsement and
        `hours_clause.WS.base` is the 72 printed in the body.

    Takes the raw payload rather than a validated model, so a treaty
    quarantined by FR-INGEST-3 can still be scored field by field.
    """
    territory = payload.get("territory") or {}
    hours = payload.get("hours_clause") or {}

    out: dict[str, Any] = {}

    def put(name: str, value: Any) -> None:
        # A field the model omitted stays absent, so QA-3 counts it as missing
        # rather than as a wrong value of None.
        if value is not None:
            out[name] = value

    put("type", payload.get("type"))
    put("perils", payload.get("perils"))
    put("territory.include", territory.get("include"))
    put("territory.exclude", territory.get("exclude"))
    put("inception", payload.get("inception"))
    put("expiry", payload.get("expiry"))
    put("currency", payload.get("currency"))
    put("exclusions", payload.get("exclusions"))
    put("hours_clause.WS", hours.get("WS"))
    put("hours_clause.EQ", hours.get("EQ"))
    put("hours_clause.FL", hours.get("FL"))

    layers = [la for la in (payload.get("layers") or []) if isinstance(la, dict)]
    for layer in layers:
        number = layer.get("layer_no")
        if number is None:
            continue
        put(f"layers.{number}.retention", layer.get("retention"))
        put(f"layers.{number}.limit", layer.get("limit"))
        put(f"layers.{number}.premium", layer.get("premium"))

    numbered = [la for la in layers if la.get("layer_no") is not None]
    if numbered:
        first = min(numbered, key=lambda la: la["layer_no"])
        reinstatements = first.get("reinstatements") or {}
        put("reinstatements.count", reinstatements.get("count"))
        put("reinstatements.rate", reinstatements.get("rate"))
        put("reinstatements.basis", reinstatements.get("basis"))

    qs = payload.get("qs") or {}
    put("qs.cession_pct", qs.get("cession_pct"))
    put("qs.event_limit", qs.get("event_limit"))

    endorsement = payload.get("endorsement") or {}
    overrides = endorsement.get("overrides")
    if overrides:
        out["endorsement.overrides"] = overrides
        base = endorsement.get("base_value")
        if base is not None:
            out[f"{overrides}.base"] = base

    return out


def field_pages_of(terms: TreatyTerms) -> dict[str, int]:
    """The pages the extractor cited, for QA-4's separate page score."""
    return terms.pages_by_field()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _manifest_rows(wordings_dir: Path) -> list[dict]:
    manifest = json.loads((wordings_dir / "manifest.json").read_text(encoding="utf-8"))
    return manifest if isinstance(manifest, list) else manifest.get("wordings", [])


def main(argv: Sequence[str] | None = None) -> int:
    """python -m ingest.ingest_treaty --out data/extracted

    Extracts every wording, writes the result, and prints the QA-3 report.
    Exits non-zero when accuracy is below the bar, so it can gate S3.
    """
    import argparse

    from qa.extraction_accuracy import (
        format_report,
        load_ground_truth,
        score_extraction,
    )

    parser = argparse.ArgumentParser(description="Extract treaty terms (FR-INGEST-1).")
    parser.add_argument("--wordings", default="data/synthetic/wordings")
    parser.add_argument("--out", default="data/extracted")
    parser.add_argument("--model", default=None, help="defaults to $MODEL_MAIN")
    parser.add_argument("--only", action="append", help="treaty_id; repeatable")
    parser.add_argument(
        "--chunk", action="store_true", help="also chunk each PDF and report the count"
    )
    args = parser.parse_args(argv)

    wordings = Path(args.wordings)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = build_client()
    wanted = set(args.only) if args.only else None

    extracted: dict[str, dict] = {}
    pages: dict[str, dict] = {}
    hard_failures: list[str] = []
    quarantined: list[str] = []
    provenance: dict[str, dict] = {}
    cited_total = cited_ok = 0
    attempted = 0

    for row in _manifest_rows(wordings):
        treaty_id = row["treaty_id"]
        if wanted is not None and treaty_id not in wanted:
            continue
        attempted += 1
        print(f"  extracting {row['wording_id']} ({treaty_id}) ...", flush=True)
        outcome = extract_treaty_terms(
            wordings / row["pdf"], treaty_id, client=client, model=args.model
        )
        if outcome.error:
            hard_failures.append(f"{treaty_id}: {outcome.error}")
            print(f"    FAILED  {outcome.error}", flush=True)
        elif outcome.quarantined:
            quarantined.append(f"{treaty_id}: {outcome.validation_error}")
            print(f"    QUARANTINED  {outcome.validation_error}", flush=True)
        extracted[treaty_id] = _jsonable(outcome.fields)
        if outcome.provenance is not None:
            # QA-4 scores only citations that survived the text check. An
            # unverified page is not a citation, so it must not earn credit.
            pages[treaty_id] = {
                name: p.page
                for name, p in outcome.provenance.fields.items()
                if p.showable and p.page is not None
            }
            provenance[treaty_id] = outcome.provenance.to_json()
            prov = outcome.provenance
            print(
                f"    citations {prov.showable_count}/{prov.total} verified"
                f" ({len(prov.by_status('transcribed'))} transcribed)",
                flush=True,
            )
            for name in prov.failing:
                print(f"      unverified  {name}: {prov.fields[name].reason}", flush=True)
            cited_total += prov.total
            cited_ok += prov.showable_count
        else:
            pages[treaty_id] = outcome.pages
        if outcome.repair_error:
            print(f"    citation repair failed: {outcome.repair_error}", flush=True)
        if args.chunk:
            chunks = chunk_pdf(treaty_id, wordings / row["pdf"])
            print(f"    {len(chunks)} chunks", flush=True)

    (out_dir / "extracted.json").write_text(
        json.dumps(
            {"extracted": extracted, "pages": pages, "provenance": provenance},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    truth = load_ground_truth(wordings / "ground_truth.json")
    report = score_extraction(
        truth, extracted, pages=pages, only_treaties=sorted(wanted) if wanted else None
    )
    print()
    print(format_report(report))

    # FR-INGEST-3 rejections are reported next to the accuracy figure, never
    # folded into it. A high field score with treaties quarantined is not a
    # high score, and quoting one without the other would mislead.
    ingestable = attempted - len(quarantined) - len(hard_failures)
    print()
    print("FR-INGEST-3 - structural validation")
    print("=" * 46)
    print(f"treaties attempted {attempted}")
    print(f"ingestable         {ingestable}")
    print(f"quarantined        {len(quarantined)}")
    print(f"hard failures      {len(hard_failures)}")
    for note in quarantined:
        print(f"  quarantined  {note}")
    for note in hard_failures:
        print(f"  failed       {note}")

    # C-7: a value is only usable with a reference a human can check. Every
    # extracted field's citation was string-matched against its page above.
    citation_rate = cited_ok / cited_total if cited_total else 0.0
    citations_ok = citation_rate >= CITATION_BAR
    print()
    print("C-7 - verified field citations")
    print("=" * 46)
    print(f"verified or transcribed  {cited_ok}/{cited_total}  {citation_rate:.1%}")
    print(f"bar                      {CITATION_BAR:.0%}  {'PASS' if citations_ok else 'FAIL'}")

    gate = report.passed and citations_ok and not quarantined and not hard_failures
    print()
    print(f"S3 gate: {'PASS' if gate else 'FAIL'}")
    return 0 if gate else 1


def _jsonable(value: Any) -> Any:
    """Decimals to strings, not floats - the reason given in `schemas.py`."""
    from decimal import Decimal

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
