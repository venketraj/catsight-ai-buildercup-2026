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
