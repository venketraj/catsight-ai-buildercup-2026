"""REQUIREMENTS section 6 and REQUIREMENTS_V2 section 2 — the Pydantic schemas.

These are the boundaries between agents, so the tests are about what each
boundary refuses. A schema that accepts a malformed value just moves the
failure three stages downstream, into a report, where it looks like a wrong
number rather than a bad parse.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from catsight_agent.schemas import (
    Citation,
    CourtroomSide,
    CourtroomVerdict,
    Event,
    EventRegion,
    FieldCitation,
    HoursClause,
    LayerTerms,
    PricedOutcome,
    QuotaShareTerms,
    Reinstatements,
    ScenarioParams,
    Territory,
    TreatyTerms,
    VerificationResult,
    WordingFlag,
)

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _layer(no: int, retention: str, limit: str, share: str = "0.25") -> LayerTerms:
    return LayerTerms(
        layer_no=no,
        retention=retention,
        limit=limit,
        premium="2.0",
        our_share=share,
        reinstatements=Reinstatements(count=1, rate="1.0"),
    )


def _terms(**overrides) -> TreatyTerms:
    base = dict(
        treaty_id="T-001",
        cedent="Sakura General Insurance",
        type="CAT_XL",
        perils=["WS", "EQ"],
        territory=Territory(include=["JPN"]),
        inception="2026-04-01",
        expiry="2027-03-31",
        currency="USD",
        hours_clause=HoursClause(WS=72, EQ=72, FL=168, OTHER=168),
        layers=[_layer(1, "10", "20"), _layer(2, "30", "30")],
    )
    base.update(overrides)
    return TreatyTerms(**base)


# --------------------------------------------------------------------------- #
# Strictness
# --------------------------------------------------------------------------- #


def test_an_unknown_field_is_rejected_not_dropped():
    """A model that invents a key usually means the prompt and the schema
    have drifted apart, which is worth seeing rather than swallowing."""
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        Citation(
            treaty_id="T-001", page=1, clause_no="5",
            quote="a quote long enough to be substantive",
            hallucinated_field="oops",
        )


def test_money_stays_decimal_rather_than_becoming_float():
    """The reason given in the loss engine: a float round-trip reintroduces
    the error Decimal exists to avoid."""
    layer = _layer(1, "10", "20")
    assert isinstance(layer.retention, Decimal)
    assert layer.retention == Decimal("10")


def test_json_mode_renders_decimals_as_strings():
    """So Firestore and the SSE stream carry an exact value."""
    payload = _layer(1, "10.5", "20.25").model_dump(mode="json")
    assert payload["retention"] == "10.5"
    assert payload["limit"] == "20.25"


# --------------------------------------------------------------------------- #
# Citations — C-7
# --------------------------------------------------------------------------- #


def test_a_citation_needs_a_substantive_quote():
    """A three-word fragment cannot be quote-matched meaningfully, and it
    cannot be shown to an analyst as evidence either."""
    with pytest.raises(ValidationError, match="substantive"):
        Citation(treaty_id="T-001", page=1, clause_no="5", quote="too short")


def test_a_citation_quote_is_capped_at_three_hundred_characters():
    with pytest.raises(ValidationError):
        Citation(treaty_id="T-001", page=1, clause_no="5", quote="x" * 301)


def test_a_citation_page_is_one_based():
    with pytest.raises(ValidationError):
        Citation(
            treaty_id="T-001", page=0, clause_no="5",
            quote="a quote long enough to be substantive",
        )


def test_a_citation_records_whether_it_came_from_a_scan():
    """FR-ENDORSE-3 badges a transcription read distinctly from a text-layer
    read, so the distinction has to survive into the citation."""
    citation = Citation(
        treaty_id="T-004", page=7, clause_no="END-1",
        quote="the period shall read 168 consecutive hours", source="transcription",
    )
    assert citation.source == "transcription"
    assert Citation(
        treaty_id="T-001", page=2, clause_no="5",
        quote="all individual losses which first occur within 72 consecutive hours",
    ).source == "text"


def test_field_provenance_records_the_page_per_field():
    """FR-INGEST-1 requires a page for every extracted field."""
    provenance = FieldCitation(field="hours_clause.WS", page=2, clause_no="5")
    assert provenance.page == 2
    assert provenance.source == "text"


# --------------------------------------------------------------------------- #
# TreatyTerms — FR-INGEST-3 validation
# --------------------------------------------------------------------------- #


def test_valid_terms_round_trip():
    terms = _terms()
    assert terms.treaty_id == "T-001"
    assert len(terms.layers) == 2


def test_non_contiguous_layers_are_rejected():
    """A gap between layers is a loss band nobody covers - almost always a
    misread rather than a real structure."""
    with pytest.raises(ValidationError, match="not contiguous"):
        _terms(layers=[_layer(1, "10", "20"), _layer(2, "40", "30")])


def test_contiguous_layers_pass_regardless_of_input_order():
    terms = _terms(layers=[_layer(2, "30", "30"), _layer(1, "10", "20")])
    assert len(terms.layers) == 2


def test_a_zero_or_negative_limit_is_rejected():
    with pytest.raises(ValidationError):
        _layer(1, "10", "0")
    with pytest.raises(ValidationError):
        _layer(1, "10", "-5")


def test_a_negative_retention_is_rejected():
    with pytest.raises(ValidationError):
        _layer(1, "-1", "20")


def test_a_share_outside_zero_to_one_is_rejected():
    with pytest.raises(ValidationError):
        _layer(1, "10", "20", share="1.5")


def test_a_cat_xl_treaty_needs_layers_and_no_quota_share_block():
    with pytest.raises(ValidationError, match="needs at least one layer"):
        _terms(layers=[])
    with pytest.raises(ValidationError, match="must not carry quota-share"):
        _terms(qs=QuotaShareTerms(cession_pct="0.3", our_share="0.2"))


def test_a_quota_share_needs_cession_terms_and_no_layers():
    with pytest.raises(ValidationError, match="must not carry layers"):
        _terms(type="QS", qs=QuotaShareTerms(cession_pct="0.3", our_share="0.2"))
    with pytest.raises(ValidationError, match="needs cession terms"):
        _terms(type="QS", layers=[])


def test_a_valid_quota_share_passes():
    terms = _terms(
        type="QS", layers=[], qs=QuotaShareTerms(cession_pct="0.3", our_share="0.2")
    )
    assert terms.qs is not None
    assert terms.layers == []


def test_an_inverted_period_is_rejected():
    with pytest.raises(ValidationError, match="not before expiry"):
        _terms(inception="2027-03-31", expiry="2026-04-01")


def test_a_currency_must_be_a_three_letter_code():
    with pytest.raises(ValidationError):
        _terms(currency="DOLLARS")


def test_at_least_one_peril_is_required():
    with pytest.raises(ValidationError):
        _terms(perils=[])


def test_a_territory_cannot_both_include_and_exclude_the_same_code():
    """A contradiction the extractor should never produce, and which would
    make FR-MATCH's answer depend on evaluation order."""
    with pytest.raises(ValidationError, match="both includes and excludes"):
        Territory(include=["JPN", "JP-47"], exclude=["JP-47"])


def test_a_territory_carve_out_is_allowed():
    territory = Territory(include=["JPN"], exclude=["JP-47"])
    assert territory.exclude == ["JP-47"]


def test_an_hours_clause_of_zero_is_valid_for_a_proportional_treaty():
    """Zero means "no hours clause applies", which is correct for a quota
    share rather than a missing value."""
    clause = HoursClause(WS=0, EQ=0, FL=0, OTHER=0)
    assert clause.WS == 0


def test_an_implausible_hours_clause_is_rejected():
    with pytest.raises(ValidationError):
        HoursClause(WS=5000, EQ=72, FL=168, OTHER=168)


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #


def test_an_event_window_must_be_ordered():
    with pytest.raises(ValidationError, match="end precedes"):
        Event(
            event_id="jebi-2018", name="Typhoon Jebi", peril="WS",
            start=NOW, end=datetime(2018, 1, 1, tzinfo=timezone.utc), duration_h=9,
        )


def test_a_zero_duration_event_is_valid():
    """An earthquake mainshock is instantaneous."""
    event = Event(
        event_id="noto-2024", name="Noto", peril="EQ",
        start=NOW, end=NOW, duration_h=0,
    )
    assert event.duration_h == 0


def test_a_region_band_is_within_the_six_band_scale():
    EventRegion(code="JP-27", intensity={"wind_ms": 36.0}, band=3)
    with pytest.raises(ValidationError):
        EventRegion(code="JP-27", intensity={"wind_ms": 36.0}, band=9)


def test_an_llm_estimated_intensity_is_distinguishable():
    """FR-EVENT: live-mode estimates are shown with a warning badge, so the
    provenance has to reach the UI."""
    region = EventRegion(
        code="JP-27", intensity={"wind_ms": 30.0}, band=2,
        intensity_source="llm_estimate",
    )
    assert region.intensity_source == "llm_estimate"


# --------------------------------------------------------------------------- #
# Flags and verification — FR-VERIFY
# --------------------------------------------------------------------------- #


def _citation(treaty_id: str = "T-001") -> Citation:
    return Citation(
        treaty_id=treaty_id, page=2, clause_no="5",
        quote="all individual losses which first occur within 72 consecutive hours",
    )


def test_a_flag_cannot_cite_a_different_treaty():
    """The failure mode this prevents is a flag on one treaty quoting
    another's wording - which reads as correct and is not."""
    with pytest.raises(ValidationError, match="cites"):
        WordingFlag(
            treaty_id="T-001", issue_type="HOURS", severity="HIGH",
            explanation="duration exceeds the window",
            citation=_citation("T-002"),
        )


def test_a_consistent_flag_passes():
    flag = WordingFlag(
        treaty_id="T-001", issue_type="HOURS", severity="HIGH",
        explanation="duration exceeds the window", citation=_citation(),
    )
    assert flag.citation.treaty_id == flag.treaty_id


def test_a_failed_verification_must_carry_a_reason():
    """It goes into the review tray, where the analyst needs to know why."""
    with pytest.raises(ValidationError, match="must carry a reason"):
        VerificationResult(flag_id="f1", deterministic_pass=False, semantic_pass=True)


def test_a_passed_verification_needs_no_reason():
    result = VerificationResult(flag_id="f1", deterministic_pass=True, semantic_pass=True)
    assert result.verified


@pytest.mark.parametrize(
    "deterministic, semantic", [(True, False), (False, True), (False, False)]
)
def test_verification_requires_both_checks(deterministic, semantic):
    result = VerificationResult(
        flag_id="f1", deterministic_pass=deterministic, semantic_pass=semantic,
        reason="quote not found in the stored chunk",
    )
    assert not result.verified


# --------------------------------------------------------------------------- #
# Courtroom — FR-COURT and FR-WHATIF
# --------------------------------------------------------------------------- #


def _scenario(**overrides) -> ScenarioParams:
    base = dict(hours_window=168, occurrences=2)
    base.update(overrides)
    return ScenarioParams(**base)


def test_an_unlisted_hours_window_is_refused_not_clamped():
    """FR-WHATIF-1: the model picks parameters and the schema is what stops a
    bad pick. Clamping would silently price a scenario nobody asked for."""
    with pytest.raises(ValidationError, match="hours_window must be one of"):
        _scenario(hours_window=100)


@pytest.mark.parametrize("hours", [24, 48, 72, 96, 120, 168, 240])
def test_every_market_hours_window_is_accepted(hours):
    assert _scenario(hours_window=hours).hours_window == hours


def test_the_occurrence_count_is_bounded():
    with pytest.raises(ValidationError):
        _scenario(occurrences=4)
    with pytest.raises(ValidationError):
        _scenario(occurrences=0)


def test_window_starts_must_match_the_occurrence_count():
    with pytest.raises(ValidationError, match="window starts"):
        _scenario(occurrences=2, window_starts=[NOW])


def test_window_starts_must_be_distinct():
    """Two occurrences cannot open at the same moment, and overlapping
    windows are forbidden by the clause itself."""
    with pytest.raises(ValidationError, match="distinct"):
        _scenario(occurrences=2, window_starts=[NOW, NOW])


def test_a_track_offset_is_bounded():
    assert _scenario(track_offset_km=30.0).track_offset_km == 30.0
    with pytest.raises(ValidationError):
        _scenario(track_offset_km=250.0)


def test_an_unverified_side_must_say_why_it_was_dropped():
    """FR-COURT-3. Silence would look like an argument nobody made."""
    with pytest.raises(ValidationError, match="why it was dropped"):
        CourtroomSide(
            party="cedent", reading="one event", quoted_text="...",
            citation=_citation(), scenario=_scenario(), argument_md="...",
            verified=False,
        )


def test_a_dropped_side_records_its_reason():
    side = CourtroomSide(
        party="reinsurer", reading="two events", quoted_text="...",
        citation=_citation(), scenario=_scenario(), argument_md="...",
        verified=False, dropped_reason="quote could not be verified against the page",
    )
    assert side.dropped_reason


def test_a_recorded_position_needs_a_timestamp_for_the_audit_trail():
    verdict_kwargs = dict(
        flag_ref="T-001#c5", sides=[], arbiter_md="the dispute turns on window placement"
    )
    with pytest.raises(ValidationError, match="needs a timestamp"):
        CourtroomVerdict(**verdict_kwargs, position="cedent_reading")
    settled = CourtroomVerdict(
        **verdict_kwargs, position="cedent_reading", decided_at=NOW
    )
    assert settled.decided_at == NOW


def test_an_undecided_verdict_is_valid():
    verdict = CourtroomVerdict(
        flag_ref="T-001#c5", sides=[], arbiter_md="unresolved pending review"
    )
    assert verdict.position is None


def test_a_priced_outcome_carries_every_party_the_money_moment_needs():
    """MONEY_MOMENT section 4.4 is the reason all of these travel together."""
    outcome = PricedOutcome(
        total_ceded="34.4", cedent_retention="20.0", our_loss="7.85",
        our_rip="0.525", our_net="7.325", cedent_net_cost="22.25", market_net="32.15",
    )
    assert outcome.our_net == Decimal("7.325")
    assert outcome.cedent_net_cost == Decimal("22.25")
