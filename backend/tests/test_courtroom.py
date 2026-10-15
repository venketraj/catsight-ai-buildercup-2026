"""FR-COURT - the Clause Courtroom (catsight_agent.courtroom and its API).

The real ADK graph runs here - parallel counsel, join, pricing, arbiter - with
a fake model, the offline embedder and the real clauses of T-004.
"""

from __future__ import annotations

import asyncio
import json
import re
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.runs import MemoryRunStore
from app.scenario import ScenarioRequest, run_scenario
from app.streaming import _run_with_adk
from catsight_agent.agents import AgentDeps
from catsight_agent.courtroom import build_courtroom, pick_disputed_flag
from catsight_agent.store import LocalStore
from catsight_agent.tools.retrieval import DeterministicEmbedder
from tests.test_agents import VECTORS

STORE = LocalStore("data", today="2026-10-10")
SURGE_CLAUSE = next(c for c in VECTORS.chunks_for("T-004") if c.clause_no == "8")
FLAG = {"treaty_id": "T-004", "issue_type": "EXCLUSION", "severity": "HIGH",
        "explanation": "Storm surge is excluded and Osaka recorded a record tide.",
        "citation": {"treaty_id": "T-004", "page": SURGE_CLAUSE.page, "clause_no": "8",
                     "quote": " ".join(SURGE_CLAUSE.text.split()[:8]), "source": "text"}}
_ID = re.compile(r"^\[(?P<id>[^\]]+)\]", re.M)


class CourtModel:
    """Counsel cite the exclusion clause; the checker and arbiter behave."""

    def __init__(self, *, bad_side=None, supports=True, arbiter="Both sides have a point; our net moves by {stake}."):
        self.bad_side, self.supports, self.arbiter, self.prompts = bad_side, supports, arbiter, []
        outer = self

        class Models:
            def generate_content(self, *, model, contents, config):
                outer.prompts.append(contents)
                return SimpleNamespace(text=outer.respond(contents), usage_metadata=None)

        self.models = Models()

    def respond(self, prompt):
        if "in a dispute over one reinsurance treaty clause" in prompt:
            side = "cedent" if "counsel for the cedent" in prompt else "reinsurer"
            chunk_id = "T-004#c8"
            quote = " ".join(SURGE_CLAUSE.text.split()[:8])
            if side == self.bad_side:
                quote = "words that are not in the clause at all"
            return json.dumps({"reading": f"{side} reading of the surge exclusion",
                               "chunk_id": chunk_id, "quoted_text": quote,
                               "excluded_share": 0.0 if side == "cedent" else 0.3,
                               "argument_md": f"{side} argues."})
        if "relies on a quotation" in prompt:
            # The observed facts reach the quote check (stubbed or from the event record).
            assert "Do NOT fail it because the" in prompt and "329 cm" in prompt
            return json.dumps({"supports": self.supports, "reason": "checked"})
        if "claims arbiter" in prompt:
            stake = json.loads(prompt.split("PRICED OUTCOMES (USD millions, from the deterministic loss engine)")[1])
            our = stake.get("money_at_stake_reinsurer_minus_cedent", {}).get("our_net", "0")
            return self.arbiter.format(stake=our)
        raise AssertionError(prompt[:80])


def _price(treaty_id, share, cause):
    return run_scenario("jebi-2018", ScenarioRequest(treaty_id=treaty_id, mode="exclusion",
                                                     excluded_share=share, excluded_cause=cause), store=STORE)


def _court(model, frames=None):
    deps = AgentDeps(client=model, model_main="m", model_reason="r",
                     embedder=DeterministicEmbedder(), vectors=VECTORS,
                     emit=(frames.append if frames is not None else (lambda f: None)))
    deps.observed = ["Osaka recorded a tide of 329 cm, a record for the station."]
    graph, out = build_courtroom(event_id="jebi-2018", flag=FLAG, deps=deps, price=_price,
                                 emit=deps.emit)
    asyncio.run(_run_with_adk(graph))
    return out, deps


def test_both_verified_sides_are_priced_and_money_at_stake_is_python():
    frames = []
    out, deps = _court(CourtModel(), frames)
    sides = out["sides"]
    assert sides["cedent"]["verified"] and sides["reinsurer"]["verified"]
    c, r = sides["cedent"]["priced"]["scenario"], sides["reinsurer"]["priced"]["scenario"]
    for key, value in out["money_at_stake"].items():
        assert Decimal(value) == Decimal(r[key]) - Decimal(c[key])
    assert Decimal(out["money_at_stake"]["total_ceded"]) < 0, "excluding surge cuts recoveries"
    assert sides["reinsurer"]["priced"]["label"].startswith("ASSUMPTION: 30%")
    assert out["unsupported_figures"] == [] and "our net moves by" in out["arbiter_md"]
    assert deps.calls["cedent_counsel"] == 1 and deps.calls["reinsurer_counsel"] == 1
    stages = [(f["agent"], f["status"]) for f in frames if f["type"] == "stage"]
    assert ("arbiter", "completed") in stages and out["label"].startswith("Issue-spotting")


def test_a_side_without_a_verified_quote_is_dropped_and_no_stake_is_shown():
    out, _ = _court(CourtModel(bad_side="reinsurer"))
    assert out["sides"]["reinsurer"]["verified"] is False
    assert "not in the cited clause" in out["sides"]["reinsurer"]["dropped_reason"]
    assert "money_at_stake" not in out


def test_an_unsupported_reading_is_dropped():
    out, _ = _court(CourtModel(supports=False))
    assert not any(s["verified"] for s in out["sides"].values())
    assert "the quote is misrepresented" in out["sides"]["cedent"]["dropped_reason"]
    assert out["arbiter_md"].startswith("Neither side could cite verified wording")


def test_an_arbiter_that_invents_a_figure_is_caught():
    out, _ = _court(CourtModel(arbiter="Probably about 123.45 is at stake."))
    assert out["unsupported_figures"] == ["123.45"]


def test_counsel_that_fails_or_cites_an_unknown_clause_is_dropped():
    class Broken(CourtModel):
        def respond(self, prompt):
            if "counsel for the cedent" in prompt:
                raise RuntimeError("400")
            if "counsel for the reinsurers" in prompt:
                return json.dumps({"reading": "r", "chunk_id": "T-004#c999", "quoted_text": "x y z",
                                   "excluded_share": 0.2, "argument_md": "a"})
            return super().respond(prompt)

    out, _ = _court(Broken())
    assert "could not produce an argument" in out["sides"]["cedent"]["dropped_reason"]
    assert "not a retrieved clause" in out["sides"]["reinsurer"]["dropped_reason"]


def test_flag_selection_follows_fr_court_1():
    verified = [{"flag": FLAG}, {"flag": {**FLAG, "treaty_id": "T-002"}}]
    flag, why = pick_disputed_flag(verified, lambda tid: _price(tid, 0.5, "x"))
    assert flag["treaty_id"] in ("T-002", "T-004") and why == ""
    none, why = pick_disputed_flag([{"flag": {**FLAG, "issue_type": "HOURS"}}], lambda t: None)
    assert none is None and "What-if" in why
    none, why = pick_disputed_flag([], lambda t: None)
    assert none is None and "What-if" not in why


def test_a_medium_exclusion_is_argued_and_a_low_one_is_not():
    """Live Jebi runs rated the same verified T-004 surge exclusion HIGH in
    some runs and MEDIUM in others; the Courtroom must not depend on that."""
    medium = {**FLAG, "severity": "MEDIUM"}
    flag, why = pick_disputed_flag([{"flag": medium}], lambda tid: _price(tid, 0.5, "x"))
    assert flag["treaty_id"] == "T-004" and why == ""
    none, why = pick_disputed_flag([{"flag": {**FLAG, "severity": "LOW"}}], lambda t: None)
    assert none is None and "HIGH or MEDIUM" in why
    # Same swing: HIGH is preferred over MEDIUM.
    high = {**FLAG, "severity": "HIGH"}
    flag, _ = pick_disputed_flag([{"flag": medium}, {"flag": high}], lambda tid: _price(tid, 0.5, "x"))
    assert flag["severity"] == "HIGH"


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


def _api(model, verified=None, **env):
    config = load_settings({"GOOGLE_CLOUD_PROJECT": "p", "DATA_BACKEND": "firestore", **env})
    api = create_app(config, store=STORE)
    api.state.runs = MemoryRunStore()
    api.state.make_deps = lambda emit: AgentDeps(client=model, model_main="m", model_reason="r",
                                                 embedder=DeterministicEmbedder(), vectors=VECTORS)
    api.state.runs.save("run-1", {"run_id": "run-1", "event_id": "jebi-2018",
                                  "verified": [{"flag": FLAG}] if verified is None else verified})
    return api, TestClient(api)


def test_courtroom_endpoint_runs_saves_and_reuses():
    model = CourtModel()
    api, client = _api(model)
    first = client.post("/api/runs/run-1/courtroom").json()
    assert first["skipped"] is False and first["money_at_stake"] and "context" not in first
    calls = len(model.prompts)
    again = client.post("/api/runs/run-1/courtroom").json()
    assert again == first and len(model.prompts) == calls, "a saved Courtroom is not re-run"
    client.post("/api/runs/run-1/courtroom", params={"rerun": True})
    assert len(model.prompts) > calls

    position = client.post("/api/runs/run-1/courtroom/position",
                           json={"position": "unresolved", "note": "need adjuster split"}).json()
    assert position["position"] == "unresolved" and position["decided_at"].endswith("+00:00")
    assert api.state.runs.get("run-1")["courtroom"]["position"]["note"] == "need adjuster split"


def test_courtroom_endpoint_skips_and_guards():
    _, client = _api(CourtModel(), verified=[])
    skipped = client.post("/api/runs/run-1/courtroom").json()
    assert skipped["skipped"] is True and skipped["reason"]
    assert client.post("/api/runs/run-1/courtroom/position",
                       json={"position": "unresolved"}).status_code == 404
    assert client.post("/api/runs/run-x/courtroom").status_code == 404
    assert client.post("/api/runs/run-x/courtroom/position", json={"position": "unresolved"}).status_code == 404
    assert client.post("/api/runs/run-1/courtroom/position", json={"position": "maybe"}).status_code == 422

    _, limited = _api(CourtModel(), RATE_LIMIT_PER_HOUR="1")
    assert limited.post("/api/runs/run-1/courtroom").status_code == 200
    assert limited.post("/api/runs/run-1/courtroom", params={"rerun": True}).status_code == 429

    local = TestClient(create_app(load_settings({"GOOGLE_CLOUD_PROJECT": "p"}), store=STORE))
    assert local.post("/api/runs/run-1/courtroom").status_code == 400


def test_a_quote_check_that_cannot_run_drops_the_side():
    class CheckFails(CourtModel):
        def respond(self, prompt):
            if "relies on a quotation" in prompt:
                raise RuntimeError("400 INVALID_ARGUMENT")  # not retried, so the test stays fast
            return super().respond(prompt)

    out, _ = _court(CheckFails())
    assert "the quote check could not run" in out["sides"]["cedent"]["dropped_reason"]


def test_the_arbiter_may_use_facts_and_figures_it_was_given():
    model = CourtModel(arbiter="T-004: the 329 cm tide matters; base ceded {stake}; shares 0 and 30 percent.")
    out, _ = _court(model)
    assert out["unsupported_figures"] == [], out["unsupported_figures"]
    prompt = next(p for p in model.prompts if "claims arbiter" in p)
    assert "base_nothing_excluded" in prompt


def test_a_dropped_counsel_gets_one_revision_with_the_checkers_reason():
    """FR-COURT-3: a counsel whose first quote fails gets one retry carrying
    the failure reason, so a recoverable quote error does not drop the side."""
    class RecoversOnRetry(CourtModel):
        def respond(self, prompt):
            if "counsel for the cedent" in prompt and "PREVIOUS ATTEMPT FAILED VERIFICATION" not in prompt:
                return json.dumps({"reading": "bad first try", "chunk_id": "T-004#c8",
                                   "quoted_text": "not in the clause at all",
                                   "excluded_share": 0.0, "argument_md": "first try"})
            return super().respond(prompt)

    out, deps = _court(RecoversOnRetry())
    assert out["sides"]["cedent"]["verified"] is True
    assert out["sides"]["reinsurer"]["verified"] is True
    assert "money_at_stake" in out
    assert deps.calls["cedent_counsel"] == 1
    assert deps.calls["cedent_counsel_revise"] == 1


def test_courtroom_kill_switch_skips_cleanly():
    _, disabled = _api(CourtModel(), COURTROOM_ENABLED="false")
    resp = disabled.post("/api/runs/run-1/courtroom").json()
    assert resp["skipped"] is True
    assert "switched off" in resp["reason"]


def test_adversarial_counsel_denying_exclusion_without_support_is_dropped():
    """FR-COURT-3 / N9: A counsel who accurately quotes text but asserts an
    unfaithful reading that the checker rejects (supports=False) must fail
    verification and be dropped, preventing unverified money at stake from pricing."""
    class UnsupportedReading(CourtModel):
        def __init__(self):
            super().__init__(supports=False)

    out, _ = _court(UnsupportedReading())
    assert out["sides"]["cedent"]["verified"] is False
    assert out["sides"]["reinsurer"]["verified"] is False
    assert "money_at_stake" not in out


class _QuotaEmbedder:
    """An embedder whose every call fails the way a live quota spike does."""

    def embed_query(self, text):
        raise RuntimeError("429 RESOURCE_EXHAUSTED: embed quota")

    def embed_documents(self, texts):  # pragma: no cover - not reached by the brief
        raise RuntimeError("429 RESOURCE_EXHAUSTED: embed quota")


def test_the_brief_survives_a_failed_embedding_call():
    """V5: the brief's vector searches are a bonus. If they fail, the Courtroom
    still argues from the cited clause and the stored COVER clauses instead of
    returning a 500."""
    deps = AgentDeps(client=CourtModel(), model_main="m", model_reason="r",
                     embedder=_QuotaEmbedder(), vectors=VECTORS, emit=lambda f: None)
    deps.observed = ["Osaka recorded a tide of 329 cm, a record for the station."]
    graph, out = build_courtroom(event_id="jebi-2018", flag=FLAG, deps=deps, price=_price)
    asyncio.run(_run_with_adk(graph))
    assert out["retrieval_skipped"] == ["COVER", "EXCLUSION"]
    assert "T-004#c8" in out["context"]
    assert out["sides"]["cedent"]["verified"] and out["sides"]["reinsurer"]["verified"]
    assert "money_at_stake" in out


def test_the_brief_uses_the_pre_embedded_cover_query():
    """The cover search must use a STANDARD_QUERIES phrase, which ships with a
    vector in data/query_embeddings.jsonl, so a fresh instance makes no live call."""
    from catsight_agent.tools.retrieval import STANDARD_QUERIES

    seen = []

    class Recording(DeterministicEmbedder):
        def embed_query(self, text):
            seen.append(text)
            return super().embed_query(text)

    deps = AgentDeps(client=CourtModel(), model_main="m", model_reason="r",
                     embedder=Recording(), vectors=VECTORS, emit=lambda f: None)
    deps.observed = ["Osaka recorded a tide of 329 cm, a record for the station."]
    graph, out = build_courtroom(event_id="jebi-2018", flag=FLAG, deps=deps, price=_price)
    asyncio.run(_run_with_adk(graph))
    assert seen and set(seen) <= set(STANDARD_QUERIES.values())
    assert out["retrieval_skipped"] == []


def test_t004_surge_exclusion_pricing_ladder_traces_to_engine():
    """Traces the T-004 Osaka storm surge exclusion pricing ladder:
    - 0% surge share (cedent reading): baseline total_ceded = $39.58M, cedent_net_cost = $22.79M, our_net = $7.61M.
    - 20% surge share (recorded reinsurer reading):
        total_ceded drops by -$11.64M ($39.58M -> $27.94M)
        cedent_net_cost increases by +$10.31M ($22.79M -> $33.10M)
        market_net decreases by -$10.31M
        our_net (Lion Re) decreases by -$1.34M ($7.61M -> $6.27M)
    - 30% surge share:
        total_ceded drops by -$17.46M
        cedent_net_cost increases by +$15.51M
        our_net (Lion Re) decreases by -$2.44M
    - 50% surge share:
        total_ceded drops by -$29.09M (-$29.1M total reinsurer payout reduction)
        cedent_net_cost increases by +$25.97M (+26.0M insurer net cost)
        market_net decreases by -$25.97M
        our_net (Lion Re) decreases by -$5.16M
    """
    res_20 = run_scenario("jebi-2018", ScenarioRequest(
        treaty_id="T-004", mode="exclusion", excluded_share=0.20, excluded_cause="storm surge"),
        store=STORE)
    stake_20 = res_20["money_at_stake"]
    assert stake_20["total_ceded"] == "-11.64"
    assert stake_20["cedent_net_cost"] == "10.31"
    assert stake_20["market_net"] == "-10.31"
    assert stake_20["our_net"] == "-1.34"

    res_50 = run_scenario("jebi-2018", ScenarioRequest(
        treaty_id="T-004", mode="exclusion", excluded_share=0.50, excluded_cause="storm surge"),
        store=STORE)
    stake_50 = res_50["money_at_stake"]
    assert stake_50["total_ceded"] == "-29.09"
    assert stake_50["cedent_net_cost"] == "25.97"
    assert stake_50["market_net"] == "-25.97"
    assert stake_50["our_net"] == "-5.16"



def test_a_courtroom_past_its_deadline_says_so_and_can_be_retried():
    """A slow model must not hold a visitor near Cloud Run's 300 s limit: past
    the deadline the request ends with a plain message, and nothing is saved,
    so trying again runs the Courtroom afresh."""
    api, client = _api(CourtModel(), COURTROOM_DEADLINE_S="1")

    async def slow(graph):
        await asyncio.sleep(5)

    api.state.run_graph = slow
    resp = client.post("/api/runs/run-1/courtroom").json()
    assert resp["skipped"] is True and resp["timed_out"] is True
    assert "try again" in resp["reason"].lower()
    assert "courtroom" not in api.state.runs.get("run-1")
