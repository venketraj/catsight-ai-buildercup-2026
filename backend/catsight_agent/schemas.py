"""Pydantic schemas — REQUIREMENTS section 6 and REQUIREMENTS_V2 section 2.

These are the contract between the agents, the tools and the API. Two reasons
they are Pydantic rather than dataclasses:

  * `TreatyTerms` is passed to Gemini as `response_schema`, so the model
    returns structured output directly instead of JSON-in-prose that has to
    be salvaged;
  * every agent output is validated before it reaches the next stage, so a
    malformed field fails at the boundary that produced it rather than three
    stages later in the report.

Money is `Decimal` here as it is in the loss engine, for the reason given
there: the split case's `7.85 - 0.525` is 7.324999999999999 in binary float,
which rounds to the wrong cent. `model_dump(mode="json")` renders Decimals as
strings, which is what Firestore and the SSE stream should carry - a float
round-trip would reintroduce the error this avoids.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "Peril",
    "TreatyType",
    "ReinstatementBasis",
    "ClauseType",
    "IssueType",
    "Severity",
    "Citation",
    "FieldCitation",
    "CitationBatch",
    "GroundedField",
    "GroundedAnswer",
    "FlagCandidate",
    "FlagCandidates",
    "SupportVerdict",
    "RevisedFlag",
    "AskCitation",
    "SearchQueries",
    "CounselArgument",
    "AskAnswer",
    "Reinstatements",
    "LayerTerms",
    "QuotaShareTerms",
    "Territory",
    "HoursClause",
    "Endorsement",
    "TreatyTerms",
    "EventRegion",
    "EventFact",
    "Event",
    "WordingFlag",
    "VerificationResult",
    "ScenarioParams",
    "CourtroomSide",
    "PricedOutcome",
    "CourtroomVerdict",
    "gemini_response_schema",
]

Peril = Literal["WS", "EQ", "FL", "OTHER"]
TreatyType = Literal["CAT_XL", "QS"]
ReinstatementBasis = Literal[
    "pro rata as to amount",
    "pro rata as to time",
    "pro rata as to amount and time",
    "full",
]
ClauseType = Literal[
    "HOURS", "EXCLUSION", "TERRITORY", "REINSTATEMENT", "LIMIT", "PERIOD", "OTHER"
]
IssueType = Literal["HOURS", "EXCLUSION", "TERRITORY", "REINSTATEMENT", "PERIOD"]
Severity = Literal["HIGH", "MEDIUM", "LOW"]

#: Where a value was read from. `transcription` means a scanned page with no
#: text layer, which FR-ENDORSE-3 requires to be badged distinctly from a
#: text-layer read.
ValueSource = Literal["text", "transcription"]


class _Strict(BaseModel):
    """Reject unknown fields rather than silently dropping them.

    A model that invents a field name is a signal worth seeing, not one to
    swallow - particularly for `response_schema` output, where a hallucinated
    key usually means the prompt and the schema have drifted apart.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# Citations and provenance
# --------------------------------------------------------------------------- #


class Citation(_Strict):
    """Where a claim came from. C-7: every wording claim carries one."""

    treaty_id: str
    page: int = Field(ge=1)
    clause_no: str
    quote: str = Field(max_length=300)
    source: ValueSource = "text"

    @field_validator("quote")
    @classmethod
    def _quote_is_substantive(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError("a citation quote must be substantive, not a fragment")
        return value


class FieldCitation(_Strict):
    """Where one extracted field came from (FR-INGEST-1's `field_pages`).

    Carries its own field name because `field_pages` is a **list**, not a
    mapping. That is a shape chosen from live behaviour, not taste: with
    `dict[str, FieldProvenance]` the model returned an empty object every
    time - it will not invent the keys of an open-ended map. Given an array
    of records with `field` as a property, it populates them.
    """

    field: str
    page: int = Field(ge=1)
    clause_no: str | None = None
    source: ValueSource = "text"
    #: Verbatim words from the cited page that state the value. Checked
    #: against the PDF text by `ingest.provenance` - a citation without one
    #: cannot be verified, so it is never shown as fact.
    quote: str | None = Field(default=None, max_length=300)


class CitationBatch(_Strict):
    """Response shape for the follow-up request that repairs citations."""

    citations: list[FieldCitation] = Field(default_factory=list)


class GroundedField(_Strict):
    """One term read from retrieved clauses (RAG-first extraction).

    `chunk_id` must name one of the clauses the model was shown, and `quote`
    must appear in that clause - so the citation is verifiable by
    construction rather than located after the fact. `value` is a string for
    every field; lists are comma-separated, and assembly types it.
    """

    field: str
    value: str
    chunk_id: str
    #: No length cap here: an over-long quote must not fail the whole group's
    #: answer. The grounding check matches it against the clause regardless,
    #: and the citation stored downstream is bounded by `FieldCitation`.
    quote: str


class GroundedAnswer(_Strict):
    """Response shape for one term group."""

    fields: list[GroundedField] = Field(default_factory=list)


class FlagCandidate(_Strict):
    """AG-3's raw output: a flag citing a retrieved clause by chunk_id. Turned
    into a `WordingFlag` only after its quote is found in that clause."""

    issue_type: IssueType
    severity: Severity
    explanation: str
    chunk_id: str
    quote: str


class FlagCandidates(_Strict):
    flags: list[FlagCandidate] = Field(default_factory=list)


class SupportVerdict(_Strict):
    """FR-VERIFY-2's answer from MODEL_REASON."""

    supports: bool
    reason: str


class AskCitation(_Strict):
    chunk_id: str
    quote: str


class SearchQueries(_Strict):
    """FR-ASK's rewritten search phrases."""

    queries: list[str] = Field(default_factory=list, max_length=3)


class AskAnswer(_Strict):
    """FR-ASK's model output, before its citations and figures are checked."""

    answer_md: str
    citations: list[AskCitation] = Field(default_factory=list)


class CounselArgument(_Strict):
    """AG-6 / AG-7 output, before verification and pricing."""

    reading: str
    chunk_id: str
    quoted_text: str
    excluded_share: float = Field(ge=0, le=0.5)
    argument_md: str


class RevisedFlag(_Strict):
    """AG-5's retry: a corrected flag on the same clause, or keep=false."""

    keep: bool
    explanation: str = ""
    quote: str = ""


# --------------------------------------------------------------------------- #
# Treaty terms — the `response_schema` for FR-INGEST-1
# --------------------------------------------------------------------------- #


class Reinstatements(_Strict):
    count: int = Field(ge=0)
    #: An enum rather than free text. Asked for a string, the model returned
    #: the whole clause - "pro rata as to amount, being the proportion that
    #: the amount of limit reinstated bears to..." - which is a correct
    #: reading and an unusable field. These four are the bases that actually
    #: occur in treaty practice.
    basis: ReinstatementBasis = "pro rata as to amount"
    rate: Decimal = Field(ge=0)


class LayerTerms(_Strict):
    layer_no: int = Field(ge=1)
    retention: Decimal = Field(ge=0)
    limit: Decimal = Field(gt=0)
    premium: Decimal = Field(ge=0)
    our_share: Decimal = Field(ge=0, le=1)
    reinstatements: Reinstatements


class QuotaShareTerms(_Strict):
    cession_pct: Decimal = Field(gt=0, le=1)
    event_limit: Decimal | None = Field(default=None, ge=0)
    our_share: Decimal = Field(ge=0, le=1)


class Territory(_Strict):
    include: list[str] = Field(min_length=1)
    exclude: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_overlap(self) -> "Territory":
        overlap = set(self.include) & set(self.exclude)
        if overlap:
            raise ValueError(f"territory both includes and excludes {sorted(overlap)}")
        return self


class Endorsement(_Strict):
    """An amendment that supersedes the body of the wording (FR-ENDORSE-3).

    A typed object rather than a free-form mapping, for the reason given on
    `FieldCitation`: asked for `dict[str, str | int | None]` the model applied
    the endorsement correctly - W4's operative 168 hours, read off a scanned
    page with no text layer - and then returned `endorsement: null` every
    time. Given named fields it fills them.

    The lesson generalises, and it is the opposite of what the schema's
    flexibility suggests: **an open-ended map is the one shape a model will
    not populate.** Lists of records and typed objects both work.

    Without this the report shows 168 with no way to see that the body says 72
    and an endorsement changed it - the most important provenance in the
    document, and the planted trap in W4.
    """

    #: The dotted field this endorsement replaces, e.g. `hours_clause.WS`.
    overrides: str
    base_value: str | int | None = None
    endorsed_value: str | int | None = None
    #: The page the endorsement appears on, as written by the model.
    source: str | None = None


class HoursClause(_Strict):
    """Hours by peril. 0 means no hours clause applies, which is correct for a
    proportional treaty rather than a missing value."""

    WS: int = Field(ge=0, le=720)
    EQ: int = Field(ge=0, le=720)
    FL: int = Field(ge=0, le=720)
    OTHER: int = Field(ge=0, le=720)


class TreatyTerms(_Strict):
    """What the extractor must produce for one wording (FR-INGEST-1).

    Validation here is FR-INGEST-3: a limit of zero, a negative retention or
    non-contiguous layers fail at extraction rather than surfacing as a wrong
    number in a report.
    """

    treaty_id: str
    cedent: str
    type: TreatyType
    perils: list[Peril] = Field(min_length=1)
    territory: Territory
    inception: str
    expiry: str
    currency: str = Field(min_length=3, max_length=3)
    hours_clause: HoursClause
    exclusions: list[str] = Field(default_factory=list)
    layers: list[LayerTerms] = Field(default_factory=list)
    qs: QuotaShareTerms | None = None
    field_pages: list[FieldCitation] = Field(default_factory=list)
    endorsement: Endorsement | None = None

    @model_validator(mode="after")
    def _structure_matches_type(self) -> "TreatyTerms":
        if self.type == "CAT_XL":
            if not self.layers:
                raise ValueError("a CAT_XL treaty needs at least one layer")
            if self.qs is not None:
                raise ValueError("a CAT_XL treaty must not carry quota-share terms")
        else:
            if self.layers:
                raise ValueError("a quota share must not carry layers")
            if self.qs is None:
                raise ValueError("a quota share needs cession terms")
        return self

    @model_validator(mode="after")
    def _layers_are_contiguous(self) -> "TreatyTerms":
        """FR-INGEST-3. A gap between layers means a loss band nobody covers,
        which is almost always a misread rather than a real structure."""
        ordered = sorted(self.layers, key=lambda la: la.retention)
        for lower, upper in zip(ordered, ordered[1:]):
            if upper.retention != lower.retention + lower.limit:
                raise ValueError(
                    f"layers are not contiguous: layer {upper.layer_no} attaches at "
                    f"{upper.retention} but layer {lower.layer_no} exhausts at "
                    f"{lower.retention + lower.limit}"
                )
        return self

    @model_validator(mode="after")
    def _period_is_ordered(self) -> "TreatyTerms":
        if self.inception >= self.expiry:
            raise ValueError(f"inception {self.inception} is not before expiry {self.expiry}")
        return self

    def pages_by_field(self) -> dict[str, int]:
        """`{field: page}` for QA-4's citation-page score.

        Last entry wins on a duplicate, which is the right default: a field
        restated by an endorsement should resolve to the endorsement's page,
        and that is the page the operative value actually came from.
        """
        return {entry.field: entry.page for entry in self.field_pages}

    def provenance_of(self, field: str) -> FieldCitation | None:
        for entry in reversed(self.field_pages):
            if entry.field == field:
                return entry
        return None


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #


class EventRegion(_Strict):
    code: str
    name: str | None = None
    country: str | None = None
    intensity: dict[str, float]
    band: int = Field(ge=0, le=5)
    #: `computed` from hazard data, or `llm_estimate` in live mode - which the
    #: UI must show with a warning badge (FR-EVENT).
    intensity_source: Literal["computed", "llm_estimate"] = "computed"


class EventFact(_Strict):
    text: str
    source: str
    url: str | None = None


class Event(_Strict):
    event_id: str
    name: str
    peril: Peril
    start: datetime
    end: datetime
    duration_h: float = Field(ge=0)
    regions: list[EventRegion] = Field(default_factory=list)
    facts: list[EventFact] = Field(default_factory=list)

    @model_validator(mode="after")
    def _window_is_ordered(self) -> "Event":
        if self.end < self.start:
            raise ValueError("event end precedes its start")
        return self


# --------------------------------------------------------------------------- #
# Wording flags and verification
# --------------------------------------------------------------------------- #


class WordingFlag(_Strict):
    treaty_id: str
    issue_type: IssueType
    severity: Severity
    explanation: str
    citation: Citation
    scenario_delta: Decimal | None = None

    @model_validator(mode="after")
    def _citation_matches_treaty(self) -> "WordingFlag":
        if self.citation.treaty_id != self.treaty_id:
            raise ValueError(
                f"flag on {self.treaty_id} cites {self.citation.treaty_id}"
            )
        return self


class VerificationResult(_Strict):
    """FR-VERIFY. An unverified flag is withheld, counted and shown in a
    review tray - never dropped silently."""

    flag_id: str
    deterministic_pass: bool
    semantic_pass: bool
    reason: str | None = None
    attempts: int = Field(default=1, ge=1)
    source: ValueSource = "text"

    @property
    def verified(self) -> bool:
        return self.deterministic_pass and self.semantic_pass

    @model_validator(mode="after")
    def _failure_has_a_reason(self) -> "VerificationResult":
        if not (self.deterministic_pass and self.semantic_pass) and not self.reason:
            raise ValueError("a failed verification must carry a reason to show the analyst")
        return self


# --------------------------------------------------------------------------- #
# Courtroom — FR-COURT
# --------------------------------------------------------------------------- #


class ScenarioParams(_Strict):
    """Bounded scenario parameters (FR-WHATIF-1).

    The bounds live here as well as in `loss_engine.ScenarioBounds` on
    purpose: this is the schema the model fills, so an out-of-range choice is
    refused at the tool boundary rather than clamped silently.
    """

    hours_window: int
    occurrences: int = Field(ge=1, le=3)
    window_starts: list[datetime] = Field(default_factory=list)
    our_share_override: Decimal | None = Field(default=None, ge=0, le=1)
    retention_override: Decimal | None = Field(default=None, ge=0)
    track_offset_km: float | None = Field(default=None, ge=-200, le=200)

    @field_validator("hours_window")
    @classmethod
    def _is_a_market_window(cls, value: int) -> int:
        allowed = (24, 48, 72, 96, 120, 168, 240)
        if value not in allowed:
            raise ValueError(f"hours_window must be one of {allowed}, got {value}")
        return value

    @model_validator(mode="after")
    def _starts_match_occurrences(self) -> "ScenarioParams":
        if self.window_starts and len(self.window_starts) != self.occurrences:
            raise ValueError(
                f"{self.occurrences} occurrences but {len(self.window_starts)} window starts"
            )
        if len(set(self.window_starts)) != len(self.window_starts):
            raise ValueError("window starts must be distinct")
        return self


class PricedOutcome(_Strict):
    """One reading, priced by the engine. Every figure here originates in
    deterministic Python; none is a model output."""

    total_ceded: Decimal
    cedent_retention: Decimal
    our_loss: Decimal
    our_rip: Decimal
    our_net: Decimal
    cedent_net_cost: Decimal
    market_net: Decimal


class CourtroomSide(_Strict):
    party: Literal["cedent", "reinsurer"]
    reading: str
    quoted_text: str
    citation: Citation
    scenario: ScenarioParams
    argument_md: str
    verified: bool = False
    dropped_reason: str | None = None

    @model_validator(mode="after")
    def _unverified_sides_say_why(self) -> "CourtroomSide":
        """FR-COURT-3: a side that cannot cite verified text is dropped, and
        the UI states why. Silence would look like an argument nobody made."""
        if not self.verified and not self.dropped_reason:
            raise ValueError("an unverified side must record why it was dropped")
        return self


class CourtroomVerdict(_Strict):
    flag_ref: str
    sides: list[CourtroomSide]
    priced: dict[str, PricedOutcome] = Field(default_factory=dict)
    #: Signed, per party. Computed in Python from `priced`, never by the LLM.
    money_at_stake: dict[str, Decimal] = Field(default_factory=dict)
    arbiter_md: str
    position: Literal["cedent_reading", "reinsurer_reading", "unresolved"] | None = None
    decided_at: datetime | None = None

    @model_validator(mode="after")
    def _a_recorded_position_is_dated(self) -> "CourtroomVerdict":
        if self.position and self.decided_at is None:
            raise ValueError("a recorded analyst position needs a timestamp for the audit trail")
        return self

# --------------------------------------------------------------------------- #
# The Gemini boundary
# --------------------------------------------------------------------------- #

#: JSON Schema keywords Gemini's `types.Schema` does not model. Dropped rather
#: than translated: there is no equivalent, and sending them is a hard 400.
_UNSUPPORTED_KEYWORDS = frozenset(
    {"additionalProperties", "$schema", "discriminator", "const", "examples"}
)


def gemini_response_schema(model: type[BaseModel]) -> dict:
    """A Gemini-compatible twin of a strict model's JSON schema.

    **Verified against the live API on 2026-10-05.** Passing `TreatyTerms`
    straight to `response_schema` is rejected: Gemini's `Schema` has no
    `exclusiveMinimum`, so `Field(gt=0)` on `LayerTerms.limit` and
    `QuotaShareTerms.cession_pct` fails validation before a request is even
    sent.

    The fix is **not** to relax those bounds. FR-INGEST-3 requires a limit of
    zero to fail at extraction, so the strict bound stays on the Pydantic
    model and the API gets a relaxed twin: `exclusiveMinimum` becomes
    `minimum`, which is the closest thing Gemini models.

    The consequence is worth stating plainly, because it is a guarantee people
    assume they have and do not: **the schema no longer prevents a zero
    limit.** The model can return one. `TreatyTerms.model_validate` is what
    rejects it, which makes FR-INGEST-3's validation load-bearing rather than
    belt-and-braces.

    `$defs` and `$ref` are left alone - the live API resolves them, so
    inlining would be work that buys nothing.
    """
    return _sanitise(model.model_json_schema())


def _sanitise(node: object) -> object:
    if isinstance(node, list):
        return [_sanitise(item) for item in node]
    if not isinstance(node, dict):
        return node

    out: dict = {}
    for key, value in node.items():
        if key == "exclusiveMinimum":
            # Deliberately widening: `> 0` becomes `>= 0`. See the docstring.
            out["minimum"] = value
        elif key == "exclusiveMaximum":
            out["maximum"] = value
        elif key in _UNSUPPORTED_KEYWORDS:
            continue
        else:
            out[key] = _sanitise(value)
    return out
