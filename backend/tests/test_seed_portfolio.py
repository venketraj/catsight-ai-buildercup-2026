"""DR-1 — the synthetic portfolio.

The headline assertion is that Sakura's programme reproduces the
DOMAIN_PRIMER worked example exactly, because the money moment is computed
from it: if the seed drifts, the demo's $10.0M headline silently changes.

Also checks DR-1's structural requirements (counts, periods, shares,
determinism) and the invariants the downstream agents rely on - contiguous
layers, keyed exposures, every treaty resolving to a real cedent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

import pytest

from catsight_agent.tools.loss_engine import Layer as EngineLayer
from catsight_agent.tools.loss_engine import apply_cat_xl, quantise
from ingest.regions_reference import ALL_REGIONS, JAPAN, PHILIPPINES, TAIWAN, by_country
from ingest.seed_portfolio import (
    CEDENTS,
    MARKET_SHARE,
    WORKED_EXAMPLE_GROSS,
    OUR_REINSURER,
    SEED,
    WORDINGS,
    Portfolio,
    build_portfolio,
    main,
    write_firestore,
    write_json,
)


def D(text: str) -> Decimal:
    return Decimal(text)


@pytest.fixture(scope="module")
def portfolio() -> Portfolio:
    return build_portfolio()


# --------------------------------------------------------------------------- #
# The worked example. This is the one that matters.
# --------------------------------------------------------------------------- #


def test_sakura_programme_matches_the_worked_example(portfolio):
    """DR-1 requires this programme exactly: 20xs10, 30xs30, 40xs60;
    premiums 2.0/1.5/1.0; Lion Re 25% and 10%."""
    treaty = portfolio.treaty("T-001")
    assert treaty.cedent_id == "C-SAKURA"
    assert treaty.wording_id == "W1"
    assert treaty.type == "CAT_XL"
    assert len(treaty.layers) == 3

    expected = [
        (1, 10.0, 20.0, 2.0, 0.25),
        (2, 30.0, 30.0, 1.5, 0.10),
        (3, 60.0, 40.0, 1.0, 0.00),
    ]
    actual = [
        (la.layer_no, la.retention, la.limit, la.premium, la.our_share)
        for la in treaty.layers
    ]
    assert actual == expected


def test_sakura_reinstatement_terms_match_the_planted_wording(portfolio):
    """W1: one reinstatement at 100%, pro rata as to amount."""
    for layer in portfolio.treaty("T-001").layers:
        assert layer.reinstatements == {
            "count": 1,
            "basis": "pro rata as to amount",
            "rate": 1.0,
        }


def test_the_seeded_programme_reproduces_the_money_moment(portfolio):
    """End to end: the committed portfolio, through the real loss engine,
    gives the figures the deck and video are scripted on.

    If this fails, either the seed drifted or the engine changed - and the
    slide is wrong, not the test.
    """
    layers = tuple(
        EngineLayer(
            layer_no=la.layer_no,
            retention=str(la.retention),
            limit=str(la.limit),
            premium=str(la.premium),
            our_share=str(la.our_share),
            reinstatements=la.reinstatements["count"],
            reinstatement_rate=str(la.reinstatements["rate"]),
        )
        for la in portfolio.treaty("T-001").layers
    )

    one_event = apply_cat_xl(["54.4"], layers)
    split = apply_cat_xl(["35.0", "19.4"], layers)

    assert quantise(one_event.total_ceded) == D("44.40")
    assert quantise(one_event.our_net) == D("6.82")
    assert quantise(split.total_ceded) == D("34.40")
    assert quantise(split.our_net) == D("7.33")
    assert quantise(split.total_ceded - one_event.total_ceded) == D("-10.00")


# --------------------------------------------------------------------------- #
# DR-1 structure
# --------------------------------------------------------------------------- #


def test_eight_cedents_split_four_two_two(portfolio):
    assert len(portfolio.cedents) == 8
    by_nation = {c.country for c in portfolio.cedents}
    assert by_nation == {"JPN", "PHL", "TWN"}
    assert sum(1 for c in portfolio.cedents if c.country == "JPN") == 4
    assert sum(1 for c in portfolio.cedents if c.country == "PHL") == 2
    assert sum(1 for c in portfolio.cedents if c.country == "TWN") == 2


def test_twenty_four_treaties_eighteen_cat_xl_and_six_quota_share(portfolio):
    assert len(portfolio.treaties) == 24
    assert sum(1 for t in portfolio.treaties if t.type == "CAT_XL") == 18
    assert sum(1 for t in portfolio.treaties if t.type == "QS") == 6


def test_every_cat_xl_has_three_or_four_layers(portfolio):
    for treaty in portfolio.treaties:
        if treaty.type == "CAT_XL":
            assert 3 <= len(treaty.layers) <= 4, treaty.treaty_id


def test_quota_shares_have_no_layers_and_cat_xl_has_no_qs_block(portfolio):
    for treaty in portfolio.treaties:
        if treaty.type == "QS":
            assert treaty.layers == ()
            assert treaty.qs is not None
            assert set(treaty.qs) == {"cession_pct", "event_limit", "our_share"}
        else:
            assert treaty.qs is None
            assert treaty.layers


def test_our_shares_sit_between_five_and_thirty_percent(portfolio):
    """DR-1: Lion Re holds 5%-30% per layer. Layer 3 of the worked example is
    deliberately 0%, which is the documented exception."""
    for treaty in portfolio.treaties:
        for layer in treaty.layers:
            if (treaty.treaty_id, layer.layer_no) == ("T-001", 3):
                assert layer.our_share == 0.0
                continue
            assert 0.05 <= layer.our_share <= 0.30, (treaty.treaty_id, layer.layer_no)
        if treaty.qs:
            assert 0.05 <= treaty.qs["our_share"] <= 0.30


def test_layers_are_contiguous(portfolio):
    """FR-INGEST-3 validates contiguity, so the generator must not leave gaps:
    each layer attaches where the one below exhausts."""
    for treaty in portfolio.treaties:
        for lower, upper in zip(treaty.layers, treaty.layers[1:]):
            assert upper.retention == pytest.approx(lower.retention + lower.limit), (
                treaty.treaty_id,
                upper.layer_no,
            )


def test_layer_numbers_ascend_from_one(portfolio):
    for treaty in portfolio.treaties:
        numbers = [la.layer_no for la in treaty.layers]
        assert numbers == list(range(1, len(numbers) + 1))


def test_every_limit_and_premium_is_positive(portfolio):
    for treaty in portfolio.treaties:
        for layer in treaty.layers:
            assert layer.limit > 0
            assert layer.premium > 0
            assert layer.retention >= 0


# --------------------------------------------------------------------------- #
# Periods — DR-1
# --------------------------------------------------------------------------- #


def test_japanese_programmes_run_april_to_april(portfolio):
    for treaty in portfolio.treaties:
        cedent = portfolio.cedent(treaty.cedent_id)
        if cedent.country == "JPN" and treaty.inception.startswith("2026"):
            assert treaty.inception == "2026-04-01"
            assert treaty.expiry == "2027-03-31"


def test_philippine_and_taiwanese_programmes_run_calendar_years(portfolio):
    for treaty in portfolio.treaties:
        cedent = portfolio.cedent(treaty.cedent_id)
        if cedent.country in {"PHL", "TWN"} and treaty.inception.startswith("2026"):
            assert treaty.inception == "2026-01-01"
            assert treaty.expiry == "2026-12-31"


def test_there_is_at_least_one_expired_treaty_for_the_period_check(portfolio):
    """DR-1 asks for expired treaties so live mode can show a period
    exclusion. W8 is the documented one."""
    expired = [t for t in portfolio.treaties if t.expiry < "2026-01-01"]
    assert expired
    assert any(t.wording_id == "W8" for t in expired)


def test_inception_always_precedes_expiry(portfolio):
    for treaty in portfolio.treaties:
        assert treaty.inception < treaty.expiry


# --------------------------------------------------------------------------- #
# The eight wordings and their planted features — DR-2
# --------------------------------------------------------------------------- #


def test_the_first_eight_treaties_carry_the_eight_wordings(portfolio):
    for index, wording in enumerate(WORDINGS, start=1):
        treaty = portfolio.treaty(f"T-{index:03d}")
        assert treaty.wording_id == wording.wording_id
        assert treaty.source_pdf is not None
        assert treaty.source_pdf.endswith(f"{wording.wording_id.lower()}.pdf")


def test_filler_treaties_have_no_wording_pdf(portfolio):
    filler = [t for t in portfolio.treaties if t.wording_id is None]
    assert len(filler) == 24 - len(WORDINGS)
    assert all(t.source_pdf is None for t in filler)


@pytest.mark.parametrize(
    "wording_id, peril, hours",
    [("W1", "WS", 72), ("W2", "WS", 96), ("W3", "WS", 120), ("W7", "WS", 168)],
)
def test_planted_hours_clauses_differ_across_wordings(portfolio, wording_id, peril, hours):
    """The whole point of FR-WORD-1: never assume 72h. Real contracts use 72,
    96, 120 or 168, and the extractor has to read each one."""
    treaty = next(t for t in portfolio.treaties if t.wording_id == wording_id)
    assert treaty.hours_clause[peril] == hours


def test_w3_excludes_okinawa(portfolio):
    """The territorial carve-out FR-WORD-3 flags."""
    treaty = next(t for t in portfolio.treaties if t.wording_id == "W3")
    assert "JP-47" in treaty.territory["exclude"]


def test_w4_excludes_storm_surge_outright(portfolio):
    treaty = next(t for t in portfolio.treaties if t.wording_id == "W4")
    assert "storm surge" in treaty.exclusions
    assert treaty.layers[0].reinstatements["count"] == 2


def test_w5_is_wind_only(portfolio):
    treaty = next(t for t in portfolio.treaties if t.wording_id == "W5")
    assert treaty.perils == ("WS",)
    assert "earthquake" in treaty.exclusions


def test_w6_is_the_quota_share(portfolio):
    treaty = next(t for t in portfolio.treaties if t.wording_id == "W6")
    assert treaty.type == "QS"
    assert treaty.qs is not None


def test_w7_has_a_free_first_reinstatement(portfolio):
    treaty = next(t for t in portfolio.treaties if t.wording_id == "W7")
    assert treaty.layers[0].reinstatements["rate"] == 0.0


def test_hours_clauses_are_a_known_market_value(portfolio):
    """RESEARCH_FINDINGS: real Cat XL contracts use 72, 96, 120 or 168."""
    for treaty in portfolio.treaties:
        if treaty.type != "CAT_XL":
            continue
        assert treaty.hours_clause["WS"] in {72, 96, 120, 168}, treaty.treaty_id


# --------------------------------------------------------------------------- #
# Exposures
# --------------------------------------------------------------------------- #


def test_every_cedent_has_exposure_in_its_own_country_only(portfolio):
    for cedent in portfolio.cedents:
        codes = {e.region_code for e in portfolio.exposures_for(cedent.cedent_id)}
        allowed = {r.code for r in by_country(cedent.country)}
        assert codes
        assert codes <= allowed


def test_exposure_ids_are_keyed_as_the_data_model_specifies(portfolio):
    """REQUIREMENTS 4.1: {cedent_id}_{region_code}_{peril}."""
    for exposure in portfolio.exposures:
        assert exposure.exposure_id == (
            f"{exposure.cedent_id}_{exposure.region_code}_{exposure.peril}"
        )


def test_exposure_ids_are_unique(portfolio):
    ids = [e.exposure_id for e in portfolio.exposures]
    assert len(ids) == len(set(ids))


def test_exposure_covers_both_perils(portfolio):
    assert {e.peril for e in portfolio.exposures} == {"WS", "EQ"}


def test_every_tsi_is_positive(portfolio):
    assert all(e.tsi_usd > 0 for e in portfolio.exposures)


def test_philippine_earthquake_penetration_is_lower_than_wind(portfolio):
    """Deliberate: EQ cover is thin in the Philippines."""
    ph = [c.cedent_id for c in portfolio.cedents if c.country == "PHL"]
    for cedent_id in ph:
        ws = sum(e.tsi_usd for e in portfolio.exposures_for(cedent_id, "WS"))
        eq = sum(e.tsi_usd for e in portfolio.exposures_for(cedent_id, "EQ"))
        assert eq < ws


def test_osaka_exposure_exists_for_the_jebi_demo(portfolio):
    """The hero demo needs Sakura to have exposure where Jebi made landfall."""
    codes = {
        e.region_code for e in portfolio.exposures_for("C-SAKURA", "WS")
    }
    for code in ("JP-27", "JP-28", "JP-36"):  # Osaka, Hyogo, Tokushima
        assert code in codes


def test_programmes_attach_at_a_plausible_share_of_a_major_event_loss(portfolio):
    """DR-1 asks for retentions "plausible relative to TSI", but a Cat XL is
    bought against a return-period loss, not against sum insured: Sakura
    retains 10.0 of a 54.4 event, which is 0.0004% of its TSI and entirely
    normal. So plausibility is checked against the reference event loss.

    Every programme should retain roughly 15-35% of a major event, matching
    Sakura's 18.4%.
    """
    anchor = sum(e.tsi_usd for e in portfolio.exposures_for("C-SAKURA"))
    for treaty in portfolio.treaties:
        if treaty.type != "CAT_XL":
            continue
        tsi = sum(e.tsi_usd for e in portfolio.exposures_for(treaty.cedent_id))
        reference = WORKED_EXAMPLE_GROSS * tsi / anchor
        share = treaty.layers[0].retention / reference
        assert 0.10 <= share <= 0.40, (treaty.treaty_id, round(share, 3))


def test_sakura_retains_eighteen_percent_of_the_worked_example(portfolio):
    treaty = portfolio.treaty("T-001")
    assert treaty.layers[0].retention / WORKED_EXAMPLE_GROSS == pytest.approx(0.184, abs=0.001)


def test_market_shares_are_explicit_not_drawn():
    """A cedent's size is structural. If it moved with the seed, the demo's
    headline figures would move with it."""
    assert MARKET_SHARE["C-SAKURA"] == 0.14
    assert set(MARKET_SHARE) == {c.cedent_id for c in CEDENTS}
    assert all(0.0 < s < 1.0 for s in MARKET_SHARE.values())


def test_the_synthetic_japanese_market_is_the_size_the_demo_requires(portfolio):
    """About US$2.5tn of sum insured across the four Japanese cedents.

    **Deliberately smaller than reality**, and the trade-off is the point.
    Japan's real insured value is order US$20-30tn, so this is roughly 10x
    light. It is set by `TSI_PER_WEIGHT_USD_M`, which was re-derived so that
    Sakura's modelled Jebi gross lands near the worked example's 54.4 and the
    programme burns partially - without that the money moment has nothing to
    show.

    Portfolio size is not the lever for absolute loss level; that is
    `calibration_factor` (V3) at B5. See the constant's own note.
    """
    jp_ws = sum(
        e.tsi_usd
        for e in portfolio.exposures
        if e.peril == "WS" and portfolio.cedent(e.cedent_id).country == "JPN"
    )
    assert 2e6 < jp_ws < 3.5e6  # USD millions, i.e. US$2-3.5tn


def test_the_jebi_replay_reproduces_the_worked_example_gross(portfolio):
    """The one that makes the demo work.

    **Reads the committed `jebi-2018.json`**, which is what the live demo
    serves. The previous version of this test built its own Jebi-like track
    and asserted against that, so when `build_events.py` landed the real
    IBTrACS track - stronger and twice as broad - the calibration drifted 4.4x
    and this test kept passing. A test that exercises an input production
    never sees is worse than no test: it reports confidence it has not earned.

    The tolerance stays tight. If this drifts again, re-derive
    TSI_PER_WEIGHT_USD_M against the event file rather than loosening it.
    """
    import json
    from pathlib import Path

    from catsight_agent.tools.loss_engine import ExposureSlice, gross_loss

    event = json.loads(
        (Path("data/events/jebi-2018.json")).read_text(encoding="utf-8")
    )
    from catsight_agent.tools.vulnerability import VulnerabilityModel

    vuln = VulnerabilityModel.load()
    ratios = {
        region["code"]: str(
            vuln.wind_damage_ratio(region["intensity"]["wind_ms"], region["country"])
        )
        for region in event["regions"]
        if "wind_ms" in region.get("intensity", {})
    }

    exposures = portfolio.exposures_for("C-SAKURA", "WS")
    gross = gross_loss(
        [ExposureSlice(e.region_code, e.peril, str(e.tsi_usd)) for e in exposures],
        ratios,
    )
    assert float(gross) == pytest.approx(54.4, abs=0.5)


def test_the_jebi_replay_pierces_layers_one_and_two_but_not_three(portfolio):
    """What the demo must show: L1 exhausted, L2 partly burnt, L3 untouched.
    Without this the hero demo renders an empty layer chart."""
    from catsight_agent.tools.loss_engine import Layer as EngineLayer
    from catsight_agent.tools.loss_engine import apply_cat_xl

    layers = tuple(
        EngineLayer(
            layer_no=la.layer_no,
            retention=str(la.retention),
            limit=str(la.limit),
            premium=str(la.premium),
            our_share=str(la.our_share),
            reinstatements=la.reinstatements["count"],
            reinstatement_rate=str(la.reinstatements["rate"]),
        )
        for la in portfolio.treaty("T-001").layers
    )
    result = apply_cat_xl(["54.4"], layers)
    assert result.layer(1).exhausted is True
    assert result.layer(2).ceded > 0
    assert result.layer(2).exhausted is False
    assert result.layer(3).ceded == 0


def _jebi_like_track():
    """Jebi's approach through the Kii Channel into Osaka Bay, 4 Sep 2018.

    Approximated from the real track positions. build_events.py replaces this
    with the IBTrACS v04r01 record for SID 2018239N11161.
    """
    from datetime import datetime, timedelta, timezone

    from catsight_agent.tools.hazard import TrackPoint

    t0 = datetime(2018, 9, 4, 0, 0, tzinfo=timezone.utc)
    return [
        TrackPoint(t0, 31.5, 134.0, 51.4, 27.8, 55.6, 115.8, 213.0),
        TrackPoint(t0 + timedelta(hours=6), 33.5, 135.0, 43.7, 37.0, 46.3, 97.2, 194.5),
        TrackPoint(t0 + timedelta(hours=12), 34.8, 135.5, 36.0, 46.3, 37.0, 83.3, 166.7),
        TrackPoint(t0 + timedelta(hours=18), 37.0, 136.5, 28.3, 55.6, 0.0, 0.0, 138.9),
    ]


# --------------------------------------------------------------------------- #
# Referential integrity
# --------------------------------------------------------------------------- #


def test_every_treaty_resolves_to_a_real_cedent(portfolio):
    ids = {c.cedent_id for c in portfolio.cedents}
    assert all(t.cedent_id in ids for t in portfolio.treaties)


def test_every_exposure_resolves_to_a_real_cedent(portfolio):
    ids = {c.cedent_id for c in portfolio.cedents}
    assert all(e.cedent_id in ids for e in portfolio.exposures)


def test_treaty_ids_are_unique_and_sequential(portfolio):
    ids = [t.treaty_id for t in portfolio.treaties]
    assert ids == [f"T-{i:03d}" for i in range(1, 25)]


def test_lookup_helpers_raise_for_unknown_keys(portfolio):
    with pytest.raises(KeyError, match="T-999"):
        portfolio.treaty("T-999")
    with pytest.raises(KeyError, match="C-NOPE"):
        portfolio.cedent("C-NOPE")


def test_all_currency_is_usd(portfolio):
    assert {t.currency for t in portfolio.treaties} == {"USD"}


# --------------------------------------------------------------------------- #
# Determinism — DR-1 requires a fixed seed and idempotence
# --------------------------------------------------------------------------- #


def test_the_same_seed_gives_an_identical_portfolio():
    assert build_portfolio(SEED) == build_portfolio(SEED)


def test_a_different_seed_changes_the_filler_but_not_the_worked_example():
    other = build_portfolio(SEED + 1)
    assert other != build_portfolio(SEED)
    # T-001 is pinned regardless of seed.
    expected = [
        (1, 10.0, 20.0, 2.0, 0.25),
        (2, 30.0, 30.0, 1.5, 0.10),
        (3, 60.0, 40.0, 1.0, 0.00),
    ]
    actual = [
        (la.layer_no, la.retention, la.limit, la.premium, la.our_share)
        for la in other.treaty("T-001").layers
    ]
    assert actual == expected


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #


def test_write_json_emits_three_readable_files(tmp_path, portfolio):
    written = write_json(portfolio, tmp_path)
    assert set(written) == {"cedents", "treaties", "exposures"}
    for name, path in written.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload, list)
        assert payload


def test_write_json_is_idempotent(tmp_path, portfolio):
    first = write_json(portfolio, tmp_path)["treaties"].read_text(encoding="utf-8")
    second = write_json(portfolio, tmp_path)["treaties"].read_text(encoding="utf-8")
    assert first == second


def test_written_treaties_round_trip_tuples_as_lists(tmp_path, portfolio):
    path = write_json(portfolio, tmp_path)["treaties"]
    treaties = {t["treaty_id"]: t for t in json.loads(path.read_text(encoding="utf-8"))}
    sakura = treaties["T-001"]
    assert sakura["perils"] == ["WS", "EQ"]
    assert sakura["territory"]["include"] == ["JPN"]
    assert len(sakura["layers"]) == 3
    assert sakura["layers"][0]["retention"] == 10.0


class _FakeDoc:
    def __init__(self, store: dict, collection: str, doc_id: str) -> None:
        self._store, self._collection, self._id = store, collection, doc_id

    def set(self, data: dict) -> None:
        self._store.setdefault(self._collection, {})[self._id] = data


class _FakeCollection:
    def __init__(self, store: dict, name: str) -> None:
        self._store, self._name = store, name

    def document(self, doc_id: str) -> _FakeDoc:
        return _FakeDoc(self._store, self._name, doc_id)


class _FakeFirestore:
    """Just enough of the Firestore surface to test the writer without GCP."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, dict]] = {}

    def collection(self, name: str) -> _FakeCollection:
        return _FakeCollection(self.store, name)


def test_write_firestore_keys_every_document(portfolio):
    client = _FakeFirestore()
    count = write_firestore(portfolio, client)
    assert count == 8 + 24 + len(portfolio.exposures)
    assert set(client.store) == {"cedents", "treaties", "exposures"}
    assert "T-001" in client.store["treaties"]
    assert "C-SAKURA" in client.store["cedents"]


def test_write_firestore_is_idempotent(portfolio):
    client = _FakeFirestore()
    write_firestore(portfolio, client)
    first = dict(client.store["treaties"])
    write_firestore(portfolio, client)
    assert client.store["treaties"] == first


def test_write_firestore_substitutes_the_bucket_placeholder(portfolio):
    """source_pdf carries a {bucket} placeholder until a real bucket is known
    - the placeholder convention from BUILD_PLAN decision 2."""
    client = _FakeFirestore()
    write_firestore(portfolio, client, bucket="my-bucket")
    assert client.store["treaties"]["T-001"]["source_pdf"] == (
        "gs://my-bucket/treaties/w1.pdf"
    )


def test_write_firestore_leaves_the_placeholder_when_no_bucket_is_given(portfolio):
    client = _FakeFirestore()
    write_firestore(portfolio, client)
    assert "{bucket}" in client.store["treaties"]["T-001"]["source_pdf"]


def test_the_cli_writes_the_portfolio(tmp_path, capsys):
    assert main(["--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "8 cedents, 24 treaties" in out
    assert (tmp_path / "treaties.json").exists()


def test_the_cli_accepts_a_seed(tmp_path, capsys):
    assert main(["--out", str(tmp_path), "--seed", "99"]) == 0
    assert "seed 99" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Region reference table
# --------------------------------------------------------------------------- #


def test_japan_has_all_forty_seven_prefectures():
    assert len(JAPAN) == 47
    assert {r.code for r in JAPAN} == {f"JP-{n:02d}" for n in range(1, 48)}


def test_taiwan_has_all_twenty_two_iso_entries():
    """DR-1 says 21; ISO lists 22. All 22 are carried - see assumption X2."""
    assert len(TAIWAN) == 22


def test_the_philippine_subset_is_about_thirty_provinces():
    assert 28 <= len(PHILIPPINES) <= 34


def test_region_codes_are_unique_and_well_formed():
    import re

    codes = [r.code for r in ALL_REGIONS]
    assert len(codes) == len(set(codes))
    pattern = re.compile(r"^[A-Z]{2}-[A-Z0-9]{2,3}$")
    assert all(pattern.match(code) for code in codes)


def test_region_codes_prefix_matches_their_country():
    prefixes = {"JPN": "JP", "TWN": "TW", "PHL": "PH"}
    for region in ALL_REGIONS:
        assert region.code.startswith(prefixes[region.country] + "-")


def test_every_region_has_a_positive_weight():
    assert all(r.weight > 0 for r in ALL_REGIONS)


def test_tokyo_and_osaka_are_the_heaviest_japanese_regions():
    """A sanity check on the weights: if these are not at the top, the table
    has been scrambled."""
    heaviest = sorted(JAPAN, key=lambda r: r.weight, reverse=True)[:3]
    assert {r.code for r in heaviest} >= {"JP-13", "JP-27"}


def test_haiyan_provinces_are_present_so_the_replay_has_exposure():
    codes = {r.code for r in PHILIPPINES}
    for code in ("PH-LEY", "PH-WSA", "PH-EAS", "PH-CEB", "PH-ILI"):
        assert code in codes


def test_by_country_rejects_an_unknown_country():
    with pytest.raises(KeyError, match="IDN"):
        by_country("IDN")


def test_our_reinsurer_is_named_as_the_spec_requires():
    assert OUR_REINSURER == "Lion Re (Singapore)"


def test_cedent_names_are_clearly_fictional():
    """C-8 forbids real company data. The S9 release gate web-checks these;
    this test only catches an accidental edit to a real insurer's name."""
    real_insurers = {
        "tokio marine", "sompo", "ms&ad", "aioi", "nipponkoa", "mitsui",
        "zurich", "allianz", "axa", "chubb", "aig", "munich re", "swiss re",
        "hannover", "scor", "lloyd's", "fubon", "cathay", "shin kong",
        "malayan", "pioneer", "prudential",
    }
    for cedent in CEDENTS:
        assert cedent.name.lower() not in real_insurers
        assert not any(brand in cedent.name.lower() for brand in real_insurers)


# --------------------------------------------------------------------------- #
# Centroids and serialisation edge cases
# --------------------------------------------------------------------------- #


def test_centroid_rejects_an_unknown_region():
    from ingest.regions_reference import centroid

    with pytest.raises(KeyError, match="JP-99"):
        centroid("JP-99")


def test_every_region_has_a_centroid_and_none_is_orphaned():
    from ingest.regions_reference import CENTROIDS

    codes = {r.code for r in ALL_REGIONS}
    assert codes == set(CENTROIDS)


def test_centroids_sit_inside_each_countrys_plausible_bounding_box():
    """A transposed lat/lon or a stray sign would put a prefecture in the
    ocean, and the hazard chain would silently report zero wind."""
    from ingest.regions_reference import centroid

    boxes = {
        "JPN": (24.0, 46.0, 122.0, 146.0),
        "TWN": (21.5, 26.5, 118.0, 122.5),
        "PHL": (4.5, 21.0, 116.0, 127.0),
    }
    for region in ALL_REGIONS:
        lat, lon = centroid(region.code)
        lat_min, lat_max, lon_min, lon_max = boxes[region.country]
        assert lat_min <= lat <= lat_max, region.code
        assert lon_min <= lon <= lon_max, region.code


def test_as_hazard_regions_builds_usable_region_objects():
    from ingest.regions_reference import as_hazard_regions

    regions = as_hazard_regions()
    assert len(regions) == len(ALL_REGIONS)
    osaka = next(r for r in regions if r.code == "JP-27")
    assert osaka.name == "Osaka"
    assert osaka.country == "JPN"
    assert (osaka.lat, osaka.lon) == (34.6, 135.5)


def test_serialisation_converts_nested_lists_and_decimals(tmp_path):
    """Firestore and JSON both need plain types; a Decimal or a nested tuple
    would otherwise fail to serialise at write time rather than at build."""
    from decimal import Decimal

    from ingest.seed_portfolio import Cedent, Portfolio, _serialise

    record = Cedent("C-X", "X", "JPN", ("FIRE", "MARINE"))
    assert _serialise(record)["lines"] == ["FIRE", "MARINE"]

    @dataclass(frozen=True)
    class WithOddTypes:
        nested: list
        amount: Decimal

    payload = _serialise(WithOddTypes(nested=[("a", "b"), ["c"]], amount=Decimal("1.50")))
    assert payload["nested"] == [["a", "b"], ["c"]]
    assert payload["amount"] == 1.5
