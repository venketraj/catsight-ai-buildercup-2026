"""Live tests against the real system - Gemini, embeddings, Firestore.

    $env:RUN_LIVE="1"; uv run --no-sync --env-file .env pytest -m live -q

Skipped by default: they cost a few cents, need credentials, and depend on
quota. They check that the real services are wired correctly and that a full
analysis completes with its guarantees intact - every displayed flag's quote
really is in the stored clause, every report figure came from the engine. They
deliberately do NOT assert which flags appear: model output varies between
runs, and flag quality is measured by benchmark B4, not by a pass/fail test.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to call real GCP"),
]


@pytest.fixture(scope="module")
def gcp():
    from google.cloud import firestore

    from app.config import load_settings
    from catsight_agent.store import FirestoreStore
    from catsight_agent.tools.retrieval import FirestoreVectorStore, GeminiEmbedder
    from ingest.ingest_treaty import build_client

    config = load_settings()
    assert config.project, "GOOGLE_CLOUD_PROJECT must be set (use --env-file .env)"
    db = firestore.Client(project=config.project, database=config.firestore_database)
    return {
        "config": config,
        "client": build_client(config.project, config.location),
        "embedder": GeminiEmbedder(project=config.project, location=config.location,
                                   model=config.embed_model,
                                   cache_path=os.environ.get("EMBED_CACHE")),
        "vectors": FirestoreVectorStore(db),
        "store": FirestoreStore(db),
    }


def test_gemini_answers_on_the_configured_model(gcp):
    from ingest.rag_extract import generation_config

    response = gcp["client"].models.generate_content(
        model=gcp["config"].model_main, contents="Reply with the single word: ready",
        config=generation_config(),
    )
    assert "ready" in (response.text or "").lower()
    assert response.usage_metadata.prompt_token_count > 0


def test_embeddings_are_768_and_unit_length(gcp):
    vector = gcp["embedder"].embed_query("loss occurrence hours clause")
    assert len(vector) == 768
    assert abs(sum(v * v for v in vector) - 1.0) < 1e-6


def test_firestore_holds_the_seeded_book_and_method(gcp):
    store = gcp["store"]
    assert len(store.portfolio().treaties) == 24
    assert store.methodology()["version"]
    assert {e["event_id"] for e in store.events()} >= {"jebi-2018", "noto-2024"}


def test_vector_search_runs_with_the_treaty_prefilter(gcp):
    from catsight_agent.tools.retrieval import STANDARD_QUERIES, search_treaty_clauses

    hits = search_treaty_clauses(STANDARD_QUERIES["HOURS"], store=gcp["vectors"],
                                 embedder=gcp["embedder"], treaty_id="T-001", limit=3)
    assert hits and all(h.chunk.treaty_id == "T-001" for h in hits)
    assert 0 < hits[0].score <= 1


def test_a_full_live_analysis_keeps_its_guarantees(gcp):
    from app.streaming import stream_agent_analysis
    from catsight_agent.agents import AgentDeps
    from catsight_agent.tools.verify import match_quote

    config = gcp["config"]

    async def run():
        frames = []
        async for chunk in stream_agent_analysis(
            "jebi-2018", store=gcp["store"],
            make_deps=lambda emit: AgentDeps(
                client=gcp["client"], model_main=config.model_main,
                model_reason=config.model_reason, embedder=gcp["embedder"],
                vectors=gcp["vectors"], emit=emit),
        ):
            frames.append(json.loads(chunk[len("data:"):].strip()))
        return frames

    frames = asyncio.run(run())
    kinds = [f["type"] for f in frames]
    assert "error" not in kinds, [f for f in frames if f["type"] == "error"]
    assert kinds[-1] == "done" and "report" in kinds and "verification" in kinds

    stages = {(f["agent"], f["status"]) for f in frames if f["type"] == "stage"}
    for agent in ("event_intel", "exposure_analyst", "wording_checker", "verifier", "reporter"):
        assert (agent, "completed") in stages, agent

    # Every displayed flag's quote is really in the stored clause it cites.
    for frame in (f for f in frames if f["type"] == "flag" and f["status"] == "verified"):
        citation = frame["flag"]["citation"]
        clause = next(c for c in gcp["vectors"].chunks_for(citation["treaty_id"])
                      if c.clause_no == citation["clause_no"])
        assert match_quote(citation["quote"], clause.text).ok

    report = next(f for f in frames if f["type"] == "report")
    assert report["unsupported_figures"] == []
    assert report["cost_usd"] is not None and float(report["cost_usd"]) < 0.05


def test_counsel_quote_check_adversarial_and_positive_control(gcp):
    """Finding N9: Live adversarial evaluation of the relaxed quote check.

    Verifies that COUNSEL_QUOTE_CHECK on Gemini 3.8 Flash (model_reason):
    1. Negative test: Rejects an adversarial reading claiming storm surge is covered
       using a Clause 2 quote (supports=False).
    2. Positive control: Accepts an accurate reading of what Clause 2 establishes
       (supports=True).
    """
    from catsight_agent import prompts
    from catsight_agent.agents import AgentDeps, _generate
    from catsight_agent.schemas import SupportVerdict

    config = gcp["config"]
    deps = AgentDeps(
        client=gcp["client"],
        model_main=config.model_main,
        model_reason=config.model_reason,
        embedder=gcp["embedder"],
        vectors=gcp["vectors"],
        observed=[
            "Typhoon Jebi made landfall on 4 September 2018 in Kansai region.",
            "Peak storm tide observed at Osaka tidal station was 329 cm.",
            "Wind gusts up to 209 km/h recorded in Osaka prefecture.",
        ],
    )

    chunks = gcp["vectors"].chunks_for("T-004")
    clause2 = next((c for c in chunks if str(c.clause_no) == "2"), chunks[0])

    quote = "limited to loss arising from Windstorm"
    assert quote in clause2.text, f"Expected '{quote}' in Clause 2 text: {clause2.text}"

    # 1. Negative test: counsel reading falsely asserts storm surge is covered business
    neg_prompt = prompts.COUNSEL_QUOTE_CHECK.format(
        reading="Clause 2 explicitly provides that storm surge and coastal flood are covered business without exclusion.",
        quote=quote,
        clause_no=clause2.clause_no,
        page=clause2.page,
        clause=clause2.text,
        observed="\n".join(f"- {o}" for o in deps.observed),
    )
    raw_neg = _generate(deps, deps.model_reason, neg_prompt, SupportVerdict, "adv_quote_check_neg")
    verdict_neg = SupportVerdict.model_validate(json.loads(raw_neg or "{}"))
    assert verdict_neg.supports is False, f"Expected supports=False for adversarial misrepresentation, got: {verdict_neg}"

    # 2. Positive control: counsel reading accurately asserts what Clause 2 establishes
    pos_prompt = prompts.COUNSEL_QUOTE_CHECK.format(
        reading="Clause 2 establishes that Windstorm is covered business under the treaty's property account.",
        quote=quote,
        clause_no=clause2.clause_no,
        page=clause2.page,
        clause=clause2.text,
        observed="\n".join(f"- {o}" for o in deps.observed),
    )
    raw_pos = _generate(deps, deps.model_reason, pos_prompt, SupportVerdict, "adv_quote_check_pos")
    verdict_pos = SupportVerdict.model_validate(json.loads(raw_pos or "{}"))
    assert verdict_pos.supports is True, f"Expected supports=True for faithful reading, got: {verdict_pos}"

