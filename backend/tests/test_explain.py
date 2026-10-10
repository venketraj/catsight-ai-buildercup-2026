""""How was this calculated?", the benchmark data, and run cost."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.analysis import explain_treaty
from app.config import load_settings
from app.main import create_app
from catsight_agent.agents import AgentDeps, cost_usd
from catsight_agent.store import FirestoreStore, LocalStore

STORE = LocalStore("data", today="2026-10-10")


def test_sakura_is_explained_step_by_step_in_usd():
    """The worked example's treaty, through Jebi: every step present, and
    the per-region losses add up to the engine's gross."""
    x = explain_treaty("jebi-2018", "T-001", store=STORE)
    assert x["perspective"].startswith("Lion Re (reinsurer)")
    assert x["match"]["matched"] and "affected region" in x["match"]["reason"]
    rows = x["damage"]["rows"]
    assert rows[0]["name"] == "Osaka" and rows[0]["unit"] == "m/s"
    assert [Decimal(r["loss_usd_m"]) for r in rows] == sorted(
        (Decimal(r["loss_usd_m"]) for r in rows), reverse=True)
    total = sum(Decimal(r["loss_usd_m"]) for r in rows)
    assert abs(total - Decimal(x["damage"]["gross_usd_m"])) <= Decimal("0.01") * len(rows)
    assert x["damage"]["gross_usd_m"] == "54.30"

    l1, l2, l3 = x["layers"]
    assert l1["formula"] == "min(max(54.30 - 10.00, 0), 20.00) = 20.00"
    assert l1["our_formula"] == "20.00 x 25% = 5.00"
    assert l1["rip_formula"].endswith("= 0.50")
    assert l2["ceded_usd_m"] == "24.30" and l3["ceded_usd_m"] == "0.00"
    assert x["parties"] == {"cedent_keeps_usd_m": "10.00", "reinsurers_pay_usd_m": "44.30",
                            "our_gross_usd_m": "7.43", "our_rip_usd_m": "0.62",
                            "our_net_usd_m": "6.81"}


def test_an_excluded_treaty_says_why_and_stops():
    x = explain_treaty("jebi-2018", "T-005", store=STORE)
    assert x["match"]["matched"] is False
    assert "PHL" in x["match"]["reason"]
    assert "layers" not in x and "parties" not in x


def test_a_quota_share_is_explained():
    book = STORE.portfolio()
    qs = next(t.treaty_id for t in book.treaties
              if t.type == "QS" and "JPN" in t.territory["include"] and "WS" in t.perils)
    x = explain_treaty("jebi-2018", qs, store=STORE)
    assert x["quota_share"]["ceded_usd_m"] == x["parties"]["reinsurers_pay_usd_m"]
    gross = Decimal(x["damage"]["gross_usd_m"])
    assert Decimal(x["parties"]["cedent_keeps_usd_m"]) + Decimal(
        x["parties"]["reinsurers_pay_usd_m"]) == gross


def test_citations_come_from_verified_reconciliation(tmp_path):
    import json
    import shutil

    shutil.copytree("data", tmp_path / "data", ignore=shutil.ignore_patterns("synthetic", "raw", "cache"))
    (tmp_path / "data" / "extracted" / "reconciliation.json").write_text(json.dumps({"T-001": {
        "fields": [
            {"field": "layers.1.limit", "result": "match",
             "citation": {"status": "verified", "page": 3, "clause_no": "6", "quote": "q" * 12}},
            {"field": "layers.1.retention", "result": "unverified",
             "citation": {"status": "unverified", "page": 3}},
            {"field": "currency", "result": "book_only", "citation": None},
        ]}}), encoding="utf-8")
    x = explain_treaty("jebi-2018", "T-001", store=LocalStore(tmp_path / "data"))
    assert x["citations"] == {"layers.1.limit": {"page": 3, "clause_no": "6", "quote": "q" * 12,
                                                 "status": "verified", "agrees_with_book": True}}


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


@pytest.fixture()
def api():
    return TestClient(create_app(load_settings({"GOOGLE_CLOUD_PROJECT": "p"}), store=STORE))


def test_explanation_endpoint(api):
    body = api.get("/api/analyses/replay-jebi-2018/treaties/T-001").json()
    assert body["parties"]["our_net_usd_m"] == "6.81"
    assert api.get("/api/analyses/jebi-2018/treaties/T-001").status_code == 404
    assert api.get("/api/analyses/replay-nope/treaties/T-001").status_code == 404
    assert api.get("/api/analyses/replay-jebi-2018/treaties/T-999").status_code == 404


def test_benchmark_endpoint(api):
    jebi = api.get("/api/benchmark", params={"event_id": "jebi-2018"}).json()
    assert jebi["manual_baseline"]["status"] == "simulated"
    assert jebi["manual_baseline"]["total_hours"] == [30, 60]
    assert jebi["manual_baseline"]["manual_cost_usd"] == [3000, 6000]
    assert jebi["manual_baseline"]["catsight_review_cost_usd"] == [350.0, 800]
    assert "13bn" in jebi["real_world"]["facts"][0]["text"]
    assert "not_like_for_like" in jebi["real_world"]
    assert "gemini-3.5-flash-lite" in jebi["pricing"]["usd_per_million_tokens"]
    assert api.get("/api/benchmark", params={"event_id": "noto-2024"}).json()["real_world"] is None
    assert api.get("/api/benchmark").json()["real_world"] is None


# --------------------------------------------------------------------------- #
# Cost and usage
# --------------------------------------------------------------------------- #

PRICING = {"usd_per_million_tokens": {"m": {"input": 0.30, "output": 2.50},
                                       "r": {"input": 0.75, "output": 3.75}}}


def test_run_cost_from_measured_tokens():
    usage = {"m": {"input": 100_000, "output": 10_000}, "r": {"input": 20_000, "output": 2_000}}
    # 0.03 + 0.025 + 0.015 + 0.0075
    assert cost_usd(usage, PRICING) == "0.0775"
    assert cost_usd({"unknown-model": {"input": 1, "output": 1}}, PRICING) is None
    assert cost_usd({}, {}) == "0.0000"


def test_usage_is_recorded_from_response_metadata():
    deps = AgentDeps(client=None, model_main="m", model_reason="r", embedder=None, vectors=None)
    meta = SimpleNamespace(prompt_token_count=1000, candidates_token_count=50, thoughts_token_count=200)
    deps.record("m", SimpleNamespace(usage_metadata=meta))
    deps.record("m", SimpleNamespace(usage_metadata=SimpleNamespace(prompt_token_count=None)))
    deps.record("r", SimpleNamespace())
    assert deps.usage == {"m": {"input": 1000, "output": 250}, "r": {"input": 0, "output": 0}}


def test_benchmark_from_both_stores(tmp_path):
    assert LocalStore(tmp_path).benchmark() == {}
    assert "_comment" not in STORE.benchmark()

    class Snap:
        def __init__(self, data):
            self.exists, self._d = data is not None, data

        def to_dict(self):
            return self._d

    client = SimpleNamespace(collection=lambda name: SimpleNamespace(
        document=lambda key: SimpleNamespace(get=lambda: Snap({"pricing": {}} if key == "current" else None))))
    assert FirestoreStore(client).benchmark() == {"pricing": {}}
    empty = SimpleNamespace(collection=lambda name: SimpleNamespace(
        document=lambda key: SimpleNamespace(get=lambda: Snap(None))))
    assert FirestoreStore(empty).benchmark() == {}


def test_seed_carries_the_benchmark():
    from ingest.seed_cloud import plan_seed

    plan = plan_seed("data", bucket="b")
    assert "_comment" not in plan.documents["benchmark"]["current"]
    assert plan.documents["benchmark"]["current"]["manual_baseline"]["status"] == "simulated"


def test_map_endpoints(api):
    regions = api.get("/api/events/jebi-2018/regions").json()
    assert regions["unit"] == "m/s" and len(regions["regions"]) == 34
    osaka = next(r for r in regions["regions"] if r["code"] == "JP-27")
    assert osaka["intensity"] == 39.13 and osaka["band"] is not None
    assert api.get("/api/events/nope/regions").status_code == 404

    exposure = api.get("/api/regions/JP-27/exposure", params={"peril": "WS"}).json()
    assert exposure["cedents"][0]["tsi_usd_m"] >= exposure["cedents"][-1]["tsi_usd_m"]
    assert any(c["cedent"] == "Sakura General Insurance" for c in exposure["cedents"])
    assert api.get("/api/regions/XX-99/exposure").json()["cedents"] == []
    assert api.get("/api/events/noto-2024/regions").json()["unit"] == "MMI"


def test_benchmark_without_a_baseline_is_returned_as_is(tmp_path):
    empty = TestClient(create_app(load_settings({"GOOGLE_CLOUD_PROJECT": "p"}), store=LocalStore(tmp_path)))
    assert empty.get("/api/benchmark").json() == {"real_world": None}
