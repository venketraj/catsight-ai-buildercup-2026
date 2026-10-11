"""A fresh Cloud Run instance must not stall, and a slow stream must not go silent.

Both were seen live (2026-10-11): the first analysis on a new instance took
112-145 s because every standard query was re-embedded under the paced embed
quota, and a browser lost the stream during that silence.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.main import QUERY_EMBEDDINGS, with_heartbeat
from catsight_agent.tools.retrieval import STANDARD_QUERIES, EMBED_DIM, _EmbeddingCache

DATA = Path(__file__).resolve().parents[1] / "data"


def test_every_standard_query_ships_with_a_vector():
    """If STANDARD_QUERIES changes, re-run ingest.build_query_embeddings."""
    cache = _EmbeddingCache(None, seed=str(DATA / QUERY_EMBEDDINGS))
    for query in STANDARD_QUERIES.values():
        vector = cache.get(f"gemini-embedding-001|{EMBED_DIM}|RETRIEVAL_QUERY|{query}")
        assert vector is not None, f"no shipped vector for: {query[:50]}"
        assert len(vector) == EMBED_DIM


def test_the_seed_is_read_only(tmp_path):
    seed = tmp_path / "seed.jsonl"
    seed.write_text(json.dumps({"k": "a", "v": [1.0]}) + "\n", encoding="utf-8")
    before = seed.read_text(encoding="utf-8")
    cache = _EmbeddingCache(str(tmp_path / "cache.jsonl"), seed=str(seed))
    cache.put("new query", [0.5])
    assert seed.read_text(encoding="utf-8") == before
    assert (tmp_path / "cache.jsonl").exists() and len(cache) == 2


async def _slow():
    yield "data: 1\n\n"
    await asyncio.sleep(0.25)
    yield "data: 2\n\n"


def _collect(stream) -> list[str]:
    async def run():
        return [chunk async for chunk in stream]
    return asyncio.run(run())


def test_a_silent_stream_gets_keepalive_comments_and_loses_nothing():
    chunks = _collect(with_heartbeat(_slow(), every=0.05))
    assert [c for c in chunks if c.startswith("data:")] == ["data: 1\n\n", "data: 2\n\n"]
    assert ": keepalive\n\n" in chunks


def test_a_busy_stream_is_passed_through_unchanged():
    async def fast():
        for i in range(3):
            yield f"data: {i}\n\n"
    assert _collect(with_heartbeat(fast(), every=5)) == [f"data: {i}\n\n" for i in range(3)]
