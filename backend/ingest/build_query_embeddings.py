"""Embed the standard retrieval queries once and ship the vectors.

    uv run --no-sync --env-file .env python -m ingest.build_query_embeddings   # from backend/

Writes data/query_embeddings.jsonl, which the live service loads as a
read-only seed for its embedding cache. Without it each fresh Cloud Run
instance re-embeds every query under the paced embed quota (12/min), and its
first analysis takes two minutes instead of seconds. Re-run only when
STANDARD_QUERIES, the embedding model or its dimensions change.
"""

from __future__ import annotations

from pathlib import Path

from app.config import load_settings
from catsight_agent.tools.retrieval import STANDARD_QUERIES, GeminiEmbedder

OUT = Path(__file__).resolve().parents[1] / "data" / "query_embeddings.jsonl"


def main() -> None:
    config = load_settings()
    if not config.project:
        raise SystemExit("GOOGLE_CLOUD_PROJECT is not set (use --env-file .env)")
    OUT.unlink(missing_ok=True)
    embedder = GeminiEmbedder(project=config.project, location=config.location,
                              model=config.embed_model, cache_path=str(OUT))
    for category, query in STANDARD_QUERIES.items():
        vector = embedder.embed_query(query)
        print(f"{category:14} {len(vector)} dims")
    print(f"wrote {OUT} ({len(STANDARD_QUERIES)} queries, model {config.embed_model})")


if __name__ == "__main__":
    main()
