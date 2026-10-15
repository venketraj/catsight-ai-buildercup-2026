"""The agent graph (catsight_agent.agent / agents, app.streaming).

The real ADK 2.11 `Workflow` runs here, offline: the model is a fake that
answers by prompt type, the embedder is the hashing one, and the vector store
holds the real clauses chunked from the generated wordings. So the graph's
order, the SSE frames, grounding, verification and the report's figure check
are all exercised without a model call or a network.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from catsight_agent.agents import (
    AgentDeps,
    GeminiReviser,
    GeminiSemanticChecker,
    check_report_figures,
    check_treaty_wording,
    write_report,
)
from catsight_agent.store import LocalStore
from catsight_agent.tools.retrieval import DeterministicEmbedder, InMemoryVectorStore, index_chunks
from ingest.chunking import chunk_pdf

WORDINGS = Path("data/synthetic/wordings")
_CLAUSE = re.compile(r"^\[(?P<id>[^\]]+)\] \(page \d+, clause [^,)]+(?:, (?P<title>[^,)]+))?", re.M)


def _vectors() -> InMemoryVectorStore:
    manifest = json.loads((WORDINGS / "manifest.json").read_text(encoding="utf-8"))
    rows = manifest if isinstance(manifest, list) else manifest["wordings"]
    store, embedder = InMemoryVectorStore(), DeterministicEmbedder()
    for row in rows:
        index_chunks(chunk_pdf(row["treaty_id"], WORDINGS / row["pdf"]),
                     store=store, embedder=embedder)
    return store


VECTORS = _vectors()


def _clause_body(prompt: str, chunk_id: str) -> str:
    start = prompt.index(f"[{chunk_id}]")
    return prompt[start:].split("\n", 1)[1].split("\n\n[")[0]


class FakeGemini:
    """Answers each agent's prompt by its kind."""

    def __init__(self, *, report_first: str | None = None, supports: bool = True,
                 revise: bool = False, wording_fails: bool = False):
        self.prompts: list[str] = []
        self.report_first = report_first
        self.supports = supports
        self.revise = revise
        self.wording_fails = wording_fails
        outer = self

        class Models:
            def generate_content(self, *, model, contents, config):
                outer.prompts.append(contents)
                return SimpleNamespace(text=outer.answer(contents))

        self.models = Models()

    def answer(self, prompt: str) -> str:
        if "reinsurance wording analyst" in prompt:
            if self.wording_fails:
                raise RuntimeError("400 INVALID_ARGUMENT")
            hours = next((m["id"] for m in _CLAUSE.finditer(prompt)
                          if m["title"] and "occurrence" in m["title"].lower()), None)
            flags = [{"issue_type": "EXCLUSION", "severity": "LOW", "explanation": "x",
                      "chunk_id": "nowhere#c1", "quote": "a quote from no clause at all"}]
            if hours:
                body = _clause_body(prompt, hours)
                flags.append({"issue_type": "HOURS", "severity": "HIGH",
                              "explanation": "The occurrence period governs aggregation.",
                              "chunk_id": hours, "quote": " ".join(body.split()[:10])})
            return json.dumps({"flags": flags})
        if "verifying a claim" in prompt:
            return json.dumps({"supports": self.supports, "reason": "checked"})
        if "failed verification" in prompt:
            return json.dumps({"keep": self.revise, "explanation": "fixed",
                               "quote": "a corrected quote" if self.revise else ""})
        if "analyst report" in prompt:
            if self.report_first is not None and "NOT IN THE FACTS" not in prompt:
                return self.report_first
            facts = prompt.split("FACTS", 1)[1]
            net = re.search(r'"our_net": "([\d.]+)"', facts).group(1)
            return f"## Summary\nOur net loss is {net}.\n## Caveats\nSynthetic data."
        raise AssertionError(f"unexpected prompt: {prompt[:80]}")


def _deps(client, frames=None) -> AgentDeps:
    sink = frames if frames is not None else []
    return AgentDeps(client=client, model_main="m", model_reason="r",
                     embedder=DeterministicEmbedder(), vectors=VECTORS, emit=sink.append)


# --------------------------------------------------------------------------- #
# AG-3
# --------------------------------------------------------------------------- #


def test_wording_checker_retrieves_flags_and_discards_ungrounded_claims():
    frames: list = []
    flags = check_treaty_wording("T-001", event={"name": "Jebi"}, booked={}, engine={},
                                 deps=_deps(FakeGemini(), frames))
    assert [f.issue_type for f in flags] == ["HOURS"]
    assert flags[0].citation.treaty_id == "T-001"
    retrievals = [f for f in frames if f["type"] == "retrieval"]
    assert {r["query"] for r in retrievals} == {"HOURS", "EXCLUSION", "TERRITORY",
                                               "REINSTATEMENT", "PERIOD"}
    assert all(h["chunk_id"].startswith("T-001#") for r in retrievals for h in r["hits"])
    assert any("discarded an ungrounded EXCLUSION flag" in f.get("message", "") for f in frames)


def test_a_failed_wording_call_is_a_warning_not_a_crash():
    frames: list = []
    flags = check_treaty_wording("T-001", event={}, booked={}, engine={},
                                 deps=_deps(FakeGemini(wording_fails=True), frames))
    assert flags == []
    assert any("wording check failed" in f.get("message", "") for f in frames)


# --------------------------------------------------------------------------- #
# AG-5
# --------------------------------------------------------------------------- #


def _a_flag():
    return check_treaty_wording("T-001", event={}, booked={}, engine={},
                                deps=_deps(FakeGemini()))[0]


def test_semantic_checker_passes_and_fails_on_the_model_verdict():
    flag = _a_flag()
    chunk = next(c for c in VECTORS.chunks_for("T-001") if c.clause_no == flag.citation.clause_no)
    assert GeminiSemanticChecker(_deps(FakeGemini())).supports(flag, chunk) == (True, "checked")
    ok, reason = GeminiSemanticChecker(_deps(FakeGemini(supports=False))).supports(flag, chunk)
    assert ok is False and reason == "checked"


def test_semantic_checker_failing_to_run_does_not_pass_the_claim():
    class Broken(FakeGemini):
        def answer(self, prompt):
            raise RuntimeError("boom")

    flag = _a_flag()
    chunk = VECTORS.chunks_for("T-001")[0]
    ok, reason = GeminiSemanticChecker(_deps(Broken())).supports(flag, chunk)
    assert ok is False and "could not run" in reason


def test_reviser_drops_or_corrects_a_flag():
    flag = _a_flag()
    assert GeminiReviser(_deps(FakeGemini(revise=False))).revise(flag, "weak") is None
    revised = GeminiReviser(_deps(FakeGemini(revise=True))).revise(flag, "weak")
    assert revised is not None and revised.explanation == "fixed"
    assert revised.citation.clause_no == flag.citation.clause_no


def test_reviser_without_the_cited_clause_returns_none():
    flag = _a_flag()
    moved = flag.model_copy(update={"citation": flag.citation.model_copy(update={"page": 99})})
    assert GeminiReviser(_deps(FakeGemini(revise=True))).revise(moved, "x") is None


def test_reviser_survives_a_model_error():
    class Broken(FakeGemini):
        def answer(self, prompt):
            raise RuntimeError("boom")

    assert GeminiReviser(_deps(Broken())).revise(_a_flag(), "x") is None


# --------------------------------------------------------------------------- #
# AG-4
# --------------------------------------------------------------------------- #


def test_report_figures_must_come_from_the_facts():
    facts = '{"our_net": "70.36", "page": 2, "year": "2018-09-04"}'
    assert check_report_figures("Net 70.36 on p.2 in 2018.", facts) == []
    assert check_report_figures("Net 70.4, about 1,200 claims.", facts) == ["1,200", "70.4"]


def test_report_with_invented_figures_is_regenerated_once():
    client = FakeGemini(report_first="Our net loss is roughly 999.99.")
    report, unsupported = write_report({"totals": {"our_net": "70.36"}}, _deps(client))
    assert unsupported == []
    assert "70.36" in report
    assert sum("analyst report" in p for p in client.prompts) == 2


def test_report_still_unsupported_after_regeneration_is_reported():
    class Stubborn(FakeGemini):
        def answer(self, prompt):
            return "Net is 12345."

    report, unsupported = write_report({"x": "1"}, _deps(Stubborn()))
    assert unsupported == ["12345"]


# --------------------------------------------------------------------------- #
# The whole graph through ADK, streamed
# --------------------------------------------------------------------------- #


def _stream(client, event_id="jebi-2018", **kw) -> list[dict]:
    from app.streaming import stream_agent_analysis

    async def collect():
        frames = []
        async for chunk in stream_agent_analysis(
            event_id, store=LocalStore("data", today="2026-10-10"),
            make_deps=lambda emit: _deps(client, None) if False else AgentDeps(
                client=client, model_main="m", model_reason="r",
                embedder=DeterministicEmbedder(), vectors=VECTORS, emit=emit),
            **kw,
        ):
            frames.append(json.loads(chunk.removeprefix("data: ").strip()))
        return frames

    return asyncio.run(collect())


def test_the_adk_workflow_streams_every_agent_in_order():
    frames = _stream(FakeGemini())
    stages = [(f["agent"], f["status"]) for f in frames if f["type"] == "stage"]
    assert stages == [
        ("event_intel", "started"), ("event_intel", "completed"),
        ("exposure_analyst", "started"), ("exposure_analyst", "completed"),
        ("wording_checker", "started"), ("wording_checker", "completed"),
        ("verifier", "started"), ("verifier", "completed"),
        ("reporter", "started"), ("reporter", "completed"),
    ]
    kinds = {f["type"] for f in frames}
    assert {"result", "tool", "retrieval", "flag", "verification", "report", "done"} <= kinds
    verified = [f for f in frames if f["type"] == "flag" and f["status"] == "verified"]
    assert verified and all(f["badge"].startswith("verified") for f in verified)
    report = next(f for f in frames if f["type"] == "report")
    assert report["unsupported_figures"] == []
    assert report["calls"]["wording_checker"] >= 1
    assert frames[-1] == {"type": "done", "analysis_id": "replay-jebi-2018", "agents": True}


def test_unsupported_flags_are_withheld_with_a_reason():
    frames = _stream(FakeGemini(supports=False))
    verification = next(f for f in frames if f["type"] == "verification")
    assert verification["verified"] == 0
    assert verification["withheld"] and all(w["reason"] for w in verification["withheld"])
    assert verification["header"].startswith("0 of 0 displayed citations verified")


def test_an_unknown_event_streams_an_error_then_done():
    frames = _stream(FakeGemini(), event_id="no-such-event")
    assert frames[-2]["type"] == "error" and frames[-2]["retryable"] is False
    assert frames[-1]["type"] == "done"


def test_a_crashing_graph_streams_a_retryable_error():
    async def explode(workflow):
        raise RuntimeError("graph failed")

    frames = _stream(FakeGemini(), run_graph=explode)
    assert frames[0] == {"type": "error", "message": "RuntimeError: graph failed",
                         "retryable": True}
    assert frames[-1]["type"] == "done"


def test_a_client_leaving_mid_stream_cancels_the_graph():
    from app.streaming import stream_agent_analysis

    started = asyncio.Event()

    async def slow(workflow):
        started.set()
        await asyncio.sleep(30)

    async def go():
        gen = stream_agent_analysis(
            "jebi-2018", store=LocalStore("data", today="2026-10-10"),
            make_deps=lambda emit: AgentDeps(client=None, model_main="m", model_reason="r",
                                             embedder=None, vectors=VECTORS, emit=emit),
            run_graph=slow,
        )
        pending = asyncio.ensure_future(gen.__anext__())
        await started.wait()
        pending.cancel()
        try:
            await pending
        except asyncio.CancelledError:
            pass
        await gen.aclose()

    asyncio.run(asyncio.wait_for(go(), timeout=5))


def test_the_wording_checker_is_told_the_as_if_basis():
    client = FakeGemini()
    check_treaty_wording("T-001", event={}, booked={}, engine={}, deps=_deps(client))
    assert "AS-IF" in client.prompts[-1] and "not a reason to flag PERIOD" in client.prompts[-1]
    check_treaty_wording("T-001", event={}, booked={}, engine={}, deps=_deps(client), as_if=False)
    assert "ACTUAL" in client.prompts[-1]


def test_the_verifier_sees_the_observed_event_facts():
    client = FakeGemini()
    deps = _deps(client)
    deps.observed = ["Osaka recorded a tide of 329 cm"]
    flag = _a_flag()
    chunk = next(c for c in VECTORS.chunks_for("T-001") if c.clause_no == flag.citation.clause_no)
    GeminiSemanticChecker(deps).supports(flag, chunk)
    assert "- Osaka recorded a tide of 329 cm" in client.prompts[-1]
    GeminiSemanticChecker(_deps(client)).supports(flag, chunk)
    assert "(none recorded)" in client.prompts[-1]



def test_identifiers_are_not_figures_but_signed_numbers_are():
    from catsight_agent.agents import check_report_figures

    facts = '{"our_net": "6.81"}'
    assert check_report_figures("T-004 and JP-27 on 2018-09-04", facts + " 2018 09 04") == []
    assert check_report_figures("a change of -1.34 overall", facts) == ["1.34"]


def test_a_live_model_call_is_retried_once_and_reported(monkeypatch):
    """A visitor is waiting: a transient error is retried once, briefly, and
    every call - failed or not - is reported with its time, never its prompt."""
    from catsight_agent.agents import LIVE_ATTEMPTS, _generate

    monkeypatch.setattr("time.sleep", lambda seconds: None)
    tries: list[str] = []

    class Flaky:
        class models:
            @staticmethod
            def generate_content(*, model, contents, config):
                tries.append(model)
                if model == "down":
                    raise RuntimeError("503 UNAVAILABLE")
                return SimpleNamespace(text="ok")

    seen: list[dict] = []
    deps = AgentDeps(client=Flaky(), model_main="m", model_reason="r", embedder=None, vectors=None,
                     on_call=seen.append)
    with pytest.raises(RuntimeError):
        _generate(deps, "down", "secret prompt text", None, "verifier")
    assert len(tries) == LIVE_ATTEMPTS == 2
    assert _generate(deps, "up", "secret prompt text", None, "reporter") == "ok"
    assert [(s["kind"], s["model"], s["ok"]) for s in seen] == [("verifier", "down", False), ("reporter", "up", True)]
    assert seen[0]["error"] == "RuntimeError" and all(isinstance(s["seconds"], float) for s in seen)
    assert "secret prompt text" not in json.dumps(seen)
