"""FR-WHATIF scenarios (app.scenario) and their endpoint."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import load_settings
from app.main import create_app
from app.scenario import ScenarioRequest, loss_timeline, run_scenario
from catsight_agent.store import LocalStore

STORE = LocalStore("data", today="2026-10-10")


def _run(**kw):
    return run_scenario("jebi-2018", ScenarioRequest(treaty_id="T-001", **kw), store=STORE)


def test_the_real_72_hour_clause_gives_one_occurrence_and_no_money_at_stake():
    r = _run(mode="timing", hours_window=72)
    assert len(r["occurrences"]) == 1 and r["hypothetical"] is False
    assert r["base"] == r["scenario"]
    assert set(r["money_at_stake"].values()) == {"0.00"}
    assert r["base"]["our_net"] == "6.81" and r["base"]["total_ceded"] == "44.30"


def test_the_base_matches_the_main_analysis():
    from app.analysis import analyse

    main = next(t for t in analyse("jebi-2018", store=STORE).to_json()["treaties"]
                if t["treaty_id"] == "T-001")
    base = _run(mode="timing", hours_window=72)["base"]
    assert (base["our_net"], base["total_ceded"]) == (main["our_net"], main["ceded"])


def test_a_hypothetical_cut_is_priced_per_party_and_labelled():
    r = _run(mode="hypothetical", split_at=["2018-09-04T04:00:00Z"])
    assert r["hypothetical"] is True and r["label"].startswith("HYPOTHETICAL")
    losses = [Decimal(o["loss"]) for o in r["occurrences"]]
    assert len(losses) == 2 and sum(losses) == Decimal(r["base"]["occurrence_losses"][0])
    stake = r["money_at_stake"]
    # Signed scenario-minus-base, consistent with the two priced results.
    for key, value in stake.items():
        assert Decimal(value) == Decimal(r["scenario"][key]) - Decimal(r["base"][key])
    assert Decimal(stake["cedent_retention"]) > 0, "a second retention falls on the cedent"
    assert r["params"] == {"treaty_id": "T-001", "mode": "hypothetical",
                           "split_at": ["2018-09-04T04:00:00Z"]}


def test_two_cuts_give_three_occurrences():
    r = _run(mode="hypothetical", split_at=["2018-09-04T03:00:00Z", "2018-09-04T06:00:00Z"])
    assert len(r["occurrences"]) == 3
    assert r["occurrences"][0]["start"] is None and r["occurrences"][-1]["end"] is None


def test_the_timeline_is_dated_and_ordered():
    r = _run(mode="timing", hours_window=24)
    times = [row["at"] for row in r["timeline"]]
    assert times == sorted(times) and len(times) == 34


def test_overrides_are_bounded_and_applied():
    shared = _run(mode="timing", hours_window=72, our_share_override=0.5)
    assert Decimal(shared["base"]["our_net"]) > Decimal("6.81")
    with pytest.raises(ValueError, match="exceeds"):
        _run(mode="timing", hours_window=72, retention_override=1000)


@pytest.mark.parametrize("bad", [
    {"mode": "timing"},
    {"mode": "timing", "hours_window": 60},
    {"mode": "hypothetical"},
    {"mode": "hypothetical", "split_at": ["2018-09-04T06:00:00Z", "2018-09-04T03:00:00Z"]},
    {"mode": "hypothetical", "split_at": ["a", "b", "c"]},
    {"mode": "timing", "hours_window": 72, "our_share_override": 1.5},
    {"mode": "timing", "hours_window": 72, "surprise": 1},
])
def test_out_of_bounds_parameters_are_refused_not_clamped(bad):
    with pytest.raises(ValidationError):
        ScenarioRequest(treaty_id="T-001", **bad)


def test_cuts_outside_the_event_window_are_refused():
    with pytest.raises(ValueError, match="within the event window"):
        _run(mode="hypothetical", split_at=["2018-08-01T00:00:00Z"])


def test_quota_shares_and_non_responding_treaties_are_refused():
    with pytest.raises(ValueError, match="quota shares"):
        run_scenario("jebi-2018", ScenarioRequest(treaty_id="T-023", mode="timing", hours_window=72),
                     store=STORE)
    with pytest.raises(ValueError, match="does not respond"):
        run_scenario("jebi-2018", ScenarioRequest(treaty_id="T-005", mode="timing", hours_window=72),
                     store=STORE)


def test_an_earthquake_timeline_is_the_shock_time():
    event = STORE.event("noto-2024")
    increments = loss_timeline(event, {"JP-17": Decimal("1.5")})
    assert increments[0].at.isoformat().startswith(event["start"][:16])


def test_scenario_endpoint():
    client = TestClient(create_app(load_settings({"GOOGLE_CLOUD_PROJECT": "p"}), store=STORE))
    ok = client.post("/api/analyses/replay-jebi-2018/scenario",
                     json={"treaty_id": "T-001", "mode": "timing", "hours_window": 72})
    assert ok.status_code == 200 and ok.json()["base"]["our_net"] == "6.81"
    assert client.post("/api/analyses/jebi-2018/scenario",
                       json={"treaty_id": "T-001", "mode": "timing", "hours_window": 72}).status_code == 404
    assert client.post("/api/analyses/replay-nope/scenario",
                       json={"treaty_id": "T-001", "mode": "timing", "hours_window": 72}).status_code == 404
    assert client.post("/api/analyses/replay-jebi-2018/scenario",
                       json={"treaty_id": "T-999", "mode": "timing", "hours_window": 72}).status_code == 404
    refused = client.post("/api/analyses/replay-jebi-2018/scenario",
                          json={"treaty_id": "T-023", "mode": "timing", "hours_window": 72})
    assert refused.status_code == 422 and "quota shares" in refused.json()["detail"]
    assert client.post("/api/analyses/replay-jebi-2018/scenario",
                       json={"treaty_id": "T-001", "mode": "timing", "hours_window": 61}).status_code == 422


def test_an_exclusion_share_reduces_the_loss_and_is_labelled_an_assumption():
    r = run_scenario("jebi-2018", ScenarioRequest(treaty_id="T-004", mode="exclusion",
                                                  excluded_share=0.3, excluded_cause="storm surge"),
                     store=STORE)
    gross = Decimal(r["base"]["occurrence_losses"][0])
    # The engine applies the share to the unrounded gross; the displayed gross
    # is rounded, so allow one cent of rounding between the two.
    assert abs(Decimal(r["scenario"]["occurrence_losses"][0]) - gross * Decimal("0.7")) <= Decimal("0.01")
    assert r["label"].startswith("ASSUMPTION: 30% of the loss is attributed to storm surge")
    assert Decimal(r["money_at_stake"]["total_ceded"]) < 0
    # The excluded loss is the insurer's own: excluding cover never makes the
    # insurer better off. Its cost rises by the excluded loss less the
    # reinstatement premium it no longer pays.
    excluded = Decimal(r["scenario"]["excluded_loss"])
    assert abs(excluded - gross * Decimal("0.3")) <= Decimal("0.01")
    assert Decimal(r["money_at_stake"]["cedent_net_cost"]) > 0
    rip_saved = (Decimal(r["base"]["cedent_net_cost"]) - Decimal(r["base"]["cedent_retention"])) - (
        Decimal(r["scenario"]["cedent_net_cost"]) - excluded - Decimal(r["scenario"]["cedent_retention"]))
    assert Decimal(r["money_at_stake"]["cedent_net_cost"]) == excluded - rip_saved
    none = run_scenario("jebi-2018", ScenarioRequest(treaty_id="T-004", mode="exclusion",
                                                     excluded_share=0), store=STORE)
    assert set(none["money_at_stake"].values()) == {"0.00"} and "the excluded cause" in none["label"]


@pytest.mark.parametrize("share", [-0.1, 0.51, None])
def test_the_excluded_share_is_bounded(share):
    with pytest.raises(ValidationError):
        ScenarioRequest(treaty_id="T-004", mode="exclusion", excluded_share=share)
