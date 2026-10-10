"""QA-1 — the loss engine reproduces the DOMAIN_PRIMER worked example exactly.

Project rule: QA-1 must pass before any agent code is written. These figures are
also asserted by QA-11 and are scripted into the deck (slide 7) and the video
(scene 4), so if a code change moves them, the slide is wrong — not the test.

Every money assertion compares Decimal to Decimal via `D("...")`. Comparing a
Decimal against a float literal would silently reintroduce the binary-floating-
point error the engine exists to avoid: `Decimal("7.33") == 7.33` is False.

Reference: docs/DOMAIN_PRIMER.md section 4-5a (one event) and
docs/MONEY_MOMENT.md section 3-4 (the two-occurrence split and the per-party
view).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from catsight_agent.tools.loss_engine import (
    CatXLResult,
    ExposureSlice,
    Layer,
    LossIncrement,
    QuotaShare,
    ScenarioBounds,
    allocate_layer,
    apply_cat_xl,
    apply_quota_share,
    gross_loss,
    quantise,
    split_occurrences,
    with_overrides,
)


def D(text: str) -> Decimal:
    """An exact decimal literal."""
    return Decimal(text)


def q(value, dp: int = 2) -> Decimal:
    """Round half-up for assertion, matching the engine's money convention."""
    return quantise(value, dp)


# --------------------------------------------------------------------------- #
# The worked-example programme: Sakura General Insurance, Japan Cat XL.
# DR-2 specifies this exact structure so the demo can show it.
# --------------------------------------------------------------------------- #

L1 = Layer(
    layer_no=1,
    retention="10",
    limit="20",
    premium="2.0",
    our_share="0.25",
    reinstatements=1,
    reinstatement_rate="1.0",
)
L2 = Layer(
    layer_no=2,
    retention="30",
    limit="30",
    premium="1.5",
    our_share="0.10",
    reinstatements=1,
    reinstatement_rate="1.0",
)
L3 = Layer(
    layer_no=3,
    retention="60",
    limit="40",
    premium="1.0",
    our_share="0",
    reinstatements=1,
    reinstatement_rate="1.0",
)
PROGRAMME = (L1, L2, L3)

GROSS = D("54.4")
SPLIT = (D("35.0"), D("19.4"))  # the two-occurrence reading; sums to 54.4


# --------------------------------------------------------------------------- #
# The money convention itself
# --------------------------------------------------------------------------- #


def test_quantise_rounds_money_half_up_not_bankers():
    """On an exact tie, money rounds half away from zero. Banker's rounding
    would send 7.325 down to 7.32 and 2.665 down to 2.66."""
    assert q(D("7.325")) == D("7.33")
    assert q(D("2.665")) == D("2.67")
    assert q(D("-7.325")) == D("-7.33")


def test_float_arithmetic_loses_the_split_cases_tie():
    """Why the engine uses Decimal, stated as an executable fact.

    The literal float 7.325 happens to sit just above the tie and rounds up
    correctly. The *computed* value does not: in binary floating point
    7.85 - 0.525 is 7.324999999999999, distinctly below the tie, so it rounds
    to 7.32 and the deck's figure would be a cent light.
    """
    assert 7.85 - 0.525 != 7.325
    assert round(7.85 - 0.525, 2) == 7.32  # wrong
    assert q(D("7.85") - D("0.525")) == D("7.33")  # right


def test_engine_inputs_do_not_inherit_float_error():
    """Decimal(str(0.1)) is exactly 0.1; Decimal(0.1) is not."""
    layer = Layer(layer_no=1, retention=0.1, limit=0.2)
    assert layer.retention == D("0.100000")
    assert layer.limit == D("0.200000")


# --------------------------------------------------------------------------- #
# FR-LOSS-1 gross loss
# --------------------------------------------------------------------------- #


def test_gross_loss_from_exposure_and_injected_ratios():
    """Sum of tsi x damage ratio. Ratios are injected, per FR-LOSS acceptance."""
    exposures = [
        ExposureSlice("JP-27", "WS", "1200"),  # Osaka
        ExposureSlice("JP-28", "WS", "800"),  # Hyogo
        ExposureSlice("JP-36", "WS", "400"),  # Tokushima
    ]
    ratios = {"JP-27": "0.03", "JP-28": "0.02", "JP-36": "0.006"}
    # 36.0 + 16.0 + 2.4 = 54.4
    assert q(gross_loss(exposures, ratios)) == q(GROSS)


def test_gross_loss_accepts_a_callable():
    exposures = [ExposureSlice("JP-27", "WS", "1000")]
    assert gross_loss(exposures, lambda s: "0.05") == D("50.000000")


def test_gross_loss_accepts_float_ratios_from_a_vulnerability_curve():
    exposures = [ExposureSlice("JP-27", "WS", "1000")]
    assert gross_loss(exposures, lambda s: 0.05) == D("50.000000")


def test_gross_loss_ignores_regions_absent_from_the_mapping():
    exposures = [ExposureSlice("JP-27", "WS", "1000"), ExposureSlice("JP-01", "WS", "999")]
    assert gross_loss(exposures, {"JP-27": "0.05"}) == D("50.000000")


def test_gross_loss_is_zero_with_no_exposure():
    assert gross_loss([], {"JP-27": "0.05"}) == D("0")


@pytest.mark.parametrize("bad_ratio", ["-0.01", "1.01"])
def test_gross_loss_rejects_out_of_range_damage_ratio(bad_ratio):
    with pytest.raises(ValueError, match="damage ratio"):
        gross_loss([ExposureSlice("JP-27", "WS", "100")], {"JP-27": bad_ratio})


# --------------------------------------------------------------------------- #
# FR-LOSS-2 / FR-LOSS-3 — one event. The primer's published figures.
# --------------------------------------------------------------------------- #


@pytest.fixture
def one_event() -> CatXLResult:
    return apply_cat_xl([GROSS], PROGRAMME)


def test_one_event_layer_cessions(one_event):
    """Gross 54.4 -> L1 20.0, L2 24.4, L3 0. DOMAIN_PRIMER section 4."""
    assert q(one_event.layer(1).ceded) == D("20.00")
    assert q(one_event.layer(2).ceded) == D("24.40")
    assert q(one_event.layer(3).ceded) == D("0.00")
    assert q(one_event.total_ceded) == D("44.40")
    assert q(one_event.cedent_retention) == D("10.00")


def test_one_event_burn_and_exhaustion(one_event):
    assert one_event.layer(1).exhausted is True
    assert q(one_event.layer(1).burn, 4) == D("1.0000")
    assert one_event.layer(2).exhausted is False
    assert q(one_event.layer(2).burn, 4) == D("0.8133")
    assert one_event.layer(3).exhausted is False
    assert one_event.layer(3).burn == D("0")


def test_one_event_our_loss_is_7_44(one_event):
    """Lion Re: 20.0 x 25% + 24.4 x 10% = 5.00 + 2.44 = 7.44."""
    assert q(one_event.layer(1).our_loss) == D("5.00")
    assert q(one_event.layer(2).our_loss) == D("2.44")
    assert q(one_event.our_loss) == D("7.44")


def test_one_event_rip_is_0_622_and_net_is_6_82(one_event):
    """L1 fully eroded -> full premium. L2 eroded 81.33% -> pro rata.

    This is the test that pins the reinstatement-premium convention: L2 is NOT
    exhausted and still attracts RIP, which is what rules out an
    exhaustion-only reading. MONEY_MOMENT section 4.1.
    """
    assert q(one_event.layer(1).rip) == D("2.00")
    assert q(one_event.layer(1).our_rip) == D("0.50")
    assert q(one_event.layer(2).rip) == D("1.22")
    assert q(one_event.layer(2).our_rip, 3) == D("0.122")
    assert q(one_event.our_rip, 3) == D("0.622")
    assert q(one_event.our_net) == D("6.82")


def test_one_event_per_party_view(one_event):
    """MONEY_MOMENT section 4.4. RIP flows cedent -> reinsurer."""
    assert q(one_event.total_rip) == D("3.22")
    assert q(one_event.cedent_net_cost) == D("13.22")  # retention 10.0 + RIP 3.22
    assert q(one_event.market_net) == D("41.18")  # 44.4 - 3.22


# --------------------------------------------------------------------------- #
# FR-LOSS-5 — the two-occurrence split. The money moment.
# --------------------------------------------------------------------------- #


@pytest.fixture
def split_event() -> CatXLResult:
    return apply_cat_xl(list(SPLIT), PROGRAMME)


def test_split_sums_to_the_same_gross(split_event):
    assert sum(SPLIT) == GROSS
    assert q(split_event.gross) == q(GROSS)


def test_split_layer_cessions_are_29_4_and_5_0(split_event):
    """Each occurrence carries its own retention, so the burden shifts DOWN
    into L1 -- 20.0 + 9.4 -- while L2 drops to 5.0 + 0."""
    l1 = split_event.layer(1)
    l2 = split_event.layer(2)
    assert [q(c) for c in l1.per_occurrence] == [D("20.00"), D("9.40")]
    assert q(l1.ceded) == D("29.40")
    assert [q(c) for c in l2.per_occurrence] == [D("5.00"), D("0.00")]
    assert q(l2.ceded) == D("5.00")
    assert q(split_event.layer(3).ceded) == D("0.00")


def test_split_total_ceded_falls_and_retention_doubles(split_event):
    """The headline: one clause moves total ceded by -10.0, or -22.5%."""
    assert q(split_event.total_ceded) == D("34.40")
    assert q(split_event.cedent_retention) == D("20.00")


def test_split_headline_delta_is_minus_10_and_minus_22_5_percent(one_event, split_event):
    delta = split_event.total_ceded - one_event.total_ceded
    assert q(delta) == D("-10.00")
    assert q(100 * delta / one_event.total_ceded, 1) == D("-22.5")


def test_split_uses_the_reinstatement_but_stays_within_aggregate_cover(split_event):
    l1 = split_event.layer(1)
    assert q(l1.reinstated) == D("20.00")  # occurrence 1 eroded the full limit
    assert q(l1.burn, 3) == D("1.470")  # 29.4 / 20 -- over 100%, reinstatement used
    assert l1.ceded <= L1.aggregate_cover  # 29.4 <= 40
    assert L1.aggregate_cover == D("40.000000")


def test_split_rip_is_0_525_second_occurrence_attracts_none(split_event):
    """Occurrence 2 erodes 9.4 of the restored limit, but the single
    reinstatement was consumed in full by occurrence 1 -- nothing further is
    restored, so no RIP. MONEY_MOMENT section 4.2.
    """
    l1 = split_event.layer(1)
    assert q(l1.rip) == D("2.00")  # occurrence 1 only
    assert q(l1.our_rip) == D("0.50")
    l2 = split_event.layer(2)
    assert q(l2.rip) == D("0.25")  # (5/30) x 1.5
    assert q(l2.our_rip, 3) == D("0.025")
    assert q(split_event.our_rip, 3) == D("0.525")


def test_split_our_net_is_7_33(split_event):
    """7.85 - 0.525 = 7.325 exactly, which rounds half-up to 7.33.

    In binary float this expression is 7.324999999999999 and rounds to 7.32.
    This assertion is the reason the engine uses Decimal.
    """
    assert q(split_event.our_loss) == D("7.85")
    assert split_event.our_net == D("7.325000")
    assert q(split_event.our_net) == D("7.33")


def test_split_per_party_view(split_event):
    assert q(split_event.total_rip) == D("2.25")
    assert q(split_event.cedent_net_cost) == D("22.25")  # retention 20.0 + RIP 2.25
    assert q(split_event.market_net) == D("32.15")  # 34.4 - 2.25


# --------------------------------------------------------------------------- #
# The finding: three parties, not two. MONEY_MOMENT section 4.4.
# --------------------------------------------------------------------------- #


def test_three_parties_disagree_about_which_reading_they_want(one_event, split_event):
    """The cedent and the market are exact mirrors -- 9.03 either way. Lion Re
    is NOT: holding 25% of L1 against 10% of L2, we are overweight in the layer
    the split loads, so we side with the cedent against the rest of the market.
    """
    # Cedent prefers one event: 13.22 < 22.25
    assert q(split_event.cedent_net_cost - one_event.cedent_net_cost) == D("9.03")
    # The market prefers two events, by exactly the same amount
    assert q(one_event.market_net - split_event.market_net) == D("9.03")
    # But we prefer ONE event -- the split costs us more
    assert q(split_event.our_net - one_event.our_net) == D("0.51")
    assert split_event.our_net > one_event.our_net


def test_our_share_of_recoveries_rises_while_the_market_bill_falls(one_event, split_event):
    """16.8% -> 22.8% of total recoveries, on a bill that fell 10.0."""
    assert q(100 * one_event.our_loss / one_event.total_ceded, 1) == D("16.8")
    assert q(100 * split_event.our_loss / split_event.total_ceded, 1) == D("22.8")
    assert split_event.total_ceded < one_event.total_ceded


def test_split_is_worse_for_us_by_about_7_4_percent(one_event, split_event):
    pct = 100 * (split_event.our_net - one_event.our_net) / one_event.our_net
    assert q(pct, 1) == D("7.4")


# --------------------------------------------------------------------------- #
# FR-LOSS-3 — the two conventions MONEY_MOMENT section 4.3 rules out
# --------------------------------------------------------------------------- #


def test_rip_is_not_charged_on_aggregate_ceded(split_event):
    """The literal reading of v1's FR-LOSS-3 would give (29.4/20) x 2.0 = 2.94,
    charging for 1.47 reinstatements where the treaty provides one."""
    assert q(split_event.layer(1).rip) != D("2.94")
    assert q(split_event.layer(1).rip) == D("2.00")


def test_rip_is_not_sized_by_the_following_occurrence(split_event):
    """The other rejected basis sizes the reinstatement by what occurrence 2
    draws -- (9.4/20) x 2.0 = 0.94 -- rather than by occurrence 1's erosion."""
    assert q(split_event.layer(1).rip) != D("0.94")


def test_reinstatement_capacity_caps_total_recovery():
    """A layer can never pay more than limit x (1 + reinstatements)."""
    layer = Layer(layer_no=1, retention="0", limit="10", premium="1", our_share="1", reinstatements=1)
    result = allocate_layer(layer, ["10", "10", "10"])  # three full-limit hits
    assert q(result.ceded) == D("20.00")  # not 30.00
    assert result.ceded == layer.aggregate_cover


def test_free_reinstatement_restores_limit_without_premium():
    layer = Layer(
        layer_no=1,
        retention="0",
        limit="10",
        premium="2",
        our_share="1",
        reinstatements=1,
        reinstatement_rate="0",  # free
    )
    result = allocate_layer(layer, ["10", "10"])
    assert q(result.ceded) == D("20.00")
    assert result.rip == D("0")


def test_no_reinstatement_means_no_restoration_and_no_rip():
    layer = Layer(layer_no=1, retention="0", limit="10", premium="2", our_share="1", reinstatements=0)
    result = allocate_layer(layer, ["10", "10"])
    assert q(result.ceded) == D("10.00")
    assert result.rip == D("0")
    assert result.reinstated == D("0")


def test_loss_below_attachment_cedes_nothing():
    result = allocate_layer(L1, ["5"])
    assert result.ceded == D("0")
    assert result.rip == D("0")
    assert result.exhausted is False


# --------------------------------------------------------------------------- #
# FR-LOSS-4 quota share
# --------------------------------------------------------------------------- #


def test_quota_share_cedes_the_cession_percentage():
    result = apply_quota_share("100", QuotaShare(cession_pct="0.30", our_share="0.20"))
    assert q(result.ceded) == D("30.00")
    assert q(result.our_loss) == D("6.00")
    assert result.capped is False


def test_quota_share_respects_the_event_limit():
    result = apply_quota_share(
        "1000", QuotaShare(cession_pct="0.30", our_share="0.20", event_limit="50")
    )
    assert q(result.ceded) == D("50.00")
    assert q(result.our_loss) == D("10.00")
    assert result.capped is True


def test_quota_share_at_the_event_limit_exactly_is_not_capped():
    result = apply_quota_share("100", QuotaShare(cession_pct="0.50", event_limit="50"))
    assert q(result.ceded) == D("50.00")
    assert result.capped is False


def test_quota_share_rejects_negative_gross():
    with pytest.raises(ValueError, match="gross"):
        apply_quota_share("-1", QuotaShare(cession_pct="0.3"))


# --------------------------------------------------------------------------- #
# FR-LOSS-5 split_occurrences — hours clause windows
# --------------------------------------------------------------------------- #

T0 = datetime(2018, 9, 4, 0, 0, tzinfo=timezone.utc)


def test_jebi_duration_sits_inside_72_hours_so_it_is_one_event():
    """The primer: Jebi's main damage lasted about 24 hours, well inside 72."""
    timeline = [
        LossIncrement(T0, "30.0"),
        LossIncrement(T0 + timedelta(hours=12), "20.0"),
        LossIncrement(T0 + timedelta(hours=23), "4.4"),
    ]
    occurrences = split_occurrences(timeline, hours_window=72)
    assert len(occurrences) == 1
    assert q(occurrences[0].loss) == q(GROSS)


def test_a_240_hour_loss_under_a_168_hour_clause_splits_into_two():
    """The split case: same total, two occurrences of 35.0 and 19.4."""
    timeline = [
        LossIncrement(T0, "35.0"),
        LossIncrement(T0 + timedelta(hours=180), "19.4"),
    ]
    occurrences = split_occurrences(timeline, hours_window=168)
    assert len(occurrences) == 2
    assert [q(o.loss) for o in occurrences] == [q(s) for s in SPLIT]


def test_windows_do_not_overlap():
    timeline = [LossIncrement(T0 + timedelta(hours=h), "1") for h in (0, 100, 200, 300)]
    occurrences = split_occurrences(timeline, hours_window=72)
    for earlier, later in zip(occurrences, occurrences[1:]):
        assert earlier.window_end <= later.window_start


def test_a_window_opens_at_the_first_loss_not_before():
    """Standard wording lets the cedent choose when a window starts, but not
    before the first recorded loss -- and UnipolSai v Covea (2024) reads
    "occur" as "first occur"."""
    timeline = [LossIncrement(T0 + timedelta(hours=5), "10")]
    (occurrence,) = split_occurrences(timeline, hours_window=72)
    assert occurrence.window_start == T0 + timedelta(hours=5)
    assert occurrence.window_end == T0 + timedelta(hours=77)


def test_a_loss_exactly_on_the_window_boundary_starts_a_new_occurrence():
    timeline = [LossIncrement(T0, "10"), LossIncrement(T0 + timedelta(hours=72), "5")]
    occurrences = split_occurrences(timeline, hours_window=72)
    assert len(occurrences) == 2


def test_split_occurrences_sorts_an_unordered_timeline():
    timeline = [
        LossIncrement(T0 + timedelta(hours=180), "19.4"),
        LossIncrement(T0, "35.0"),
    ]
    occurrences = split_occurrences(timeline, hours_window=168)
    assert [q(o.loss) for o in occurrences] == [q(s) for s in SPLIT]


def test_split_occurrences_indexes_from_one():
    timeline = [LossIncrement(T0 + timedelta(hours=h), "1") for h in (0, 200)]
    occurrences = split_occurrences(timeline, hours_window=72)
    assert [o.index for o in occurrences] == [1, 2]


def test_split_occurrences_rejects_an_empty_timeline():
    with pytest.raises(ValueError, match="timeline"):
        split_occurrences([], hours_window=72)


@pytest.mark.parametrize("bad_window", [0, -72])
def test_split_occurrences_rejects_a_non_positive_window(bad_window):
    with pytest.raises(ValueError, match="hours_window"):
        split_occurrences([LossIncrement(T0, "1")], hours_window=bad_window)


def test_the_end_to_end_path_from_timeline_to_money_at_stake():
    """What FR-COURT does: split under each reading, price both, compare."""
    timeline = [
        LossIncrement(T0, "35.0"),
        LossIncrement(T0 + timedelta(hours=180), "19.4"),
    ]
    as_one = apply_cat_xl([sum((i.amount for i in timeline), Decimal(0))], PROGRAMME)
    as_two = apply_cat_xl(
        [o.loss for o in split_occurrences(timeline, hours_window=168)], PROGRAMME
    )
    assert q(as_one.total_ceded - as_two.total_ceded) == D("10.00")
    assert q(as_two.our_net - as_one.our_net) == D("0.51")


# --------------------------------------------------------------------------- #
# Input validation (FR-LOSS-6: typed, total)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"limit": "0"}, "limit"),
        ({"limit": "-1"}, "limit"),
        ({"retention": "-1"}, "retention"),
        ({"premium": "-1"}, "premium"),
        ({"our_share": "1.5"}, "our_share"),
        ({"our_share": "-0.1"}, "our_share"),
        ({"reinstatements": -1}, "reinstatements"),
        ({"reinstatement_rate": "-0.5"}, "reinstatement_rate"),
    ],
)
def test_layer_rejects_invalid_structure(kwargs, match):
    base = {"layer_no": 1, "retention": "10", "limit": "20"}
    with pytest.raises(ValueError, match=match):
        Layer(**{**base, **kwargs})


def test_layer_exhaustion_point():
    assert L1.exhaustion_point == D("30.000000")
    assert L2.exhaustion_point == D("60.000000")


@pytest.mark.parametrize("bad", [{"cession_pct": "1.5"}, {"cession_pct": "-0.1"}])
def test_quota_share_rejects_invalid_cession(bad):
    with pytest.raises(ValueError, match="cession_pct"):
        QuotaShare(**bad)


def test_quota_share_rejects_invalid_our_share():
    with pytest.raises(ValueError, match="our_share"):
        QuotaShare(cession_pct="0.3", our_share="1.5")


def test_quota_share_rejects_negative_event_limit():
    with pytest.raises(ValueError, match="event_limit"):
        QuotaShare(cession_pct="0.3", event_limit="-1")


def test_exposure_slice_rejects_negative_tsi():
    with pytest.raises(ValueError, match="tsi_usd"):
        ExposureSlice("JP-27", "WS", "-1")


def test_loss_increment_rejects_a_negative_amount():
    with pytest.raises(ValueError, match="amount"):
        LossIncrement(T0, "-1")


def test_apply_cat_xl_requires_layers():
    with pytest.raises(ValueError, match="layer"):
        apply_cat_xl([GROSS], [])


def test_apply_cat_xl_rejects_duplicate_layer_numbers():
    with pytest.raises(ValueError, match="duplicate layer_no"):
        apply_cat_xl([GROSS], [L1, L1])


def test_apply_cat_xl_orders_layers_by_attachment():
    result = apply_cat_xl([GROSS], (L3, L1, L2))
    assert [lr.layer_no for lr in result.layers] == [1, 2, 3]


def test_allocate_layer_requires_an_occurrence():
    with pytest.raises(ValueError, match="occurrence"):
        allocate_layer(L1, [])


def test_allocate_layer_rejects_a_negative_occurrence_loss():
    with pytest.raises(ValueError, match="occurrence loss"):
        allocate_layer(L1, ["-1"])


def test_result_layer_lookup_raises_for_an_unknown_layer(one_event):
    with pytest.raises(KeyError, match="no layer 9"):
        one_event.layer(9)


# --------------------------------------------------------------------------- #
# FR-WHATIF-1 scenario bounds
# --------------------------------------------------------------------------- #


def test_bounds_accept_the_permitted_hours_windows():
    bounds = ScenarioBounds()
    for hours in (24, 48, 72, 96, 120, 168, 240):
        bounds.validate_hours_window(hours)


@pytest.mark.parametrize("bad", [71, 0, 169, 1000])
def test_bounds_refuse_an_unlisted_hours_window(bad):
    """Out-of-range values are refused, never silently clamped -- the LLM picks
    parameters and the schema is what stops a bad pick."""
    with pytest.raises(ValueError, match="hours_window"):
        ScenarioBounds().validate_hours_window(bad)


def test_bounds_limit_the_occurrence_count():
    ScenarioBounds().validate_occurrences(3)
    with pytest.raises(ValueError, match="occurrences"):
        ScenarioBounds().validate_occurrences(4)
    with pytest.raises(ValueError, match="occurrences"):
        ScenarioBounds().validate_occurrences(0)


def test_bounds_limit_the_track_offset():
    ScenarioBounds().validate_track_offset(30.0)
    ScenarioBounds().validate_track_offset(-200.0)
    with pytest.raises(ValueError, match="track_offset_km"):
        ScenarioBounds().validate_track_offset(201.0)


def test_bounds_limit_a_retention_override():
    ScenarioBounds().validate_retention_override("100", "10")
    with pytest.raises(ValueError, match="retention_override"):
        ScenarioBounds().validate_retention_override("101", "10")
    with pytest.raises(ValueError, match="retention_override"):
        ScenarioBounds().validate_retention_override("-1", "10")


def test_bounds_allow_any_override_when_base_retention_is_zero():
    ScenarioBounds().validate_retention_override("500", "0")


def test_with_overrides_applies_bounded_changes():
    adjusted = with_overrides(L1, our_share="0.5", retention="15")
    assert adjusted.our_share == D("0.5")
    assert adjusted.retention == D("15.000000")
    assert adjusted.limit == L1.limit  # untouched
    assert L1.our_share == D("0.25")  # the original is frozen and unchanged


def test_with_overrides_is_a_no_op_without_arguments():
    assert with_overrides(L1) == L1


def test_with_overrides_refuses_an_out_of_range_share():
    with pytest.raises(ValueError, match="our_share_override"):
        with_overrides(L1, our_share="1.5")


def test_with_overrides_refuses_an_out_of_bounds_retention():
    with pytest.raises(ValueError, match="retention_override"):
        with_overrides(L1, retention="500")


def test_a_what_if_on_the_hours_clause_reproduces_the_money_moment():
    """FR-WHATIF: 'What if the hours clause were 168 hours?'"""
    timeline = [
        LossIncrement(T0, "35.0"),
        LossIncrement(T0 + timedelta(hours=180), "19.4"),
    ]
    bounds = ScenarioBounds()
    results = {}
    for hours in (72, 168):
        bounds.validate_hours_window(hours)
        occurrences = split_occurrences(timeline, hours_window=hours)
        bounds.validate_occurrences(len(occurrences))
        results[hours] = apply_cat_xl([o.loss for o in occurrences], PROGRAMME)
    # A 72-hour clause splits it too -- the losses are 180 hours apart.
    assert len(results[72].occurrences) == 2
    assert q(results[72].total_ceded) == D("34.40")
    assert q(results[168].total_ceded) == D("34.40")


# --------------------------------------------------------------------------- #
# Purity (FR-LOSS-6)
# --------------------------------------------------------------------------- #


def test_the_engine_is_deterministic():
    first = apply_cat_xl(list(SPLIT), PROGRAMME)
    second = apply_cat_xl(list(SPLIT), PROGRAMME)
    assert first == second


def test_the_engine_does_no_io():
    """FR-LOSS-6 requires no I/O. Guard it structurally rather than by habit."""
    import ast
    import pathlib

    source = pathlib.Path("catsight_agent/tools/loss_engine.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {
        "os", "io", "pathlib", "socket", "requests", "httpx", "urllib",
        "google", "firebase_admin", "sqlite3",
    }
    assert not (imported & forbidden), f"loss_engine imported I/O modules: {imported & forbidden}"
