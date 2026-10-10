"""Run RAG-first ingestion + extraction over every wording and measure it.

    python -m ingest.rag_pipeline                      # in-memory vectors
    python -m ingest.rag_pipeline --store firestore    # Firestore vector search

Prints progress per treaty as it goes, then QA-3 (field accuracy), C-7
(verified citations), the retrieval hit rate and wall-clock time - the same
yardsticks as the whole-document run, so the two can be compared directly.

Retrieval hit rate: for every answer-key field, whether the clause the answer
key says governs it was among the clauses retrieved for its term group. A miss
here is a retrieval failure, distinct from the model misreading a clause it
was shown - the two need different fixes, so they are reported separately.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Sequence

from ingest.ingest_treaty import CITATION_BAR, _jsonable, _manifest_rows, build_client
from ingest.rag_extract import (
    GROUP_OF_FIELD,
    RagOutcome,
    default_model,
    extract_treaty_rag,
    ingest_wording,
)

__all__ = ["retrieval_hits", "ingestion_record", "run", "main"]


def ingestion_record(
    row: dict, result: RagOutcome, ingested: Any, *, model: str, embed_model: str,
    store: str, hits: int, total: int, bucket: str | None, when: str,
) -> dict[str, Any]:
    """Evidence of one wording's ingestion, for the Knowledge base screen.

    Everything here is a fact recorded at ingest time - counts, models, the
    PDF's location and the measured results - so the UI can show that the
    corpus was really built, and when, rather than asserting it.
    """
    prov = result.outcome.provenance
    return {
        "treaty_id": row["treaty_id"],
        "wording_id": row["wording_id"],
        "pdf": f"gs://{bucket}/wordings/{row['pdf']}" if bucket else row["pdf"],
        "clauses": len(ingested.chunks),
        "embedded": len(ingested.chunks),
        "transcribed_pages": list(ingested.transcribed_pages),
        "embed_model": embed_model,
        "embed_dim": 768,
        "vector_store": "firestore:treaty_chunks" if store == "firestore" else "memory",
        "extraction_model": model,
        "fields_extracted": len(result.outcome.fields),
        "citations_verified": prov.showable_count,
        "citations_total": prov.total,
        "retrieval_hits": hits,
        "retrieval_total": total,
        "structurally_valid": not result.outcome.quarantined,
        "seconds": round(result.seconds, 1),
        "ingested_at": when,
    }


def retrieval_hits(
    truth_rows: Sequence[dict], outcome: RagOutcome, chunk_clause: dict[str, str | None]
) -> tuple[int, int, list[str]]:
    """(hits, total, misses) for one treaty's answer-key fields."""
    hits, misses = 0, []
    for row in truth_rows:
        group = outcome.groups.get(GROUP_OF_FIELD(row["field"]) or "")
        if group is None:
            continue
        retrieved = {chunk_clause.get(cid) for cid in group.retrieved}
        if str(row["clause_no"]) in retrieved:
            hits += 1
        else:
            misses.append(f"{row['field']} (clause {row['clause_no']}, group {group.group})")
    return hits, hits + len(misses), misses


def _one(row: dict, wordings: Path, *, client: Any, model: str, embedder: Any,
         store: Any, k: int) -> tuple[str, RagOutcome, Any]:
    treaty_id = row["treaty_id"]
    ingested = ingest_wording(
        treaty_id, wordings / row["pdf"], client=client, model=model,
        embedder=embedder, store=store,
    )
    print(f"  {row['wording_id']} ({treaty_id}) ingested: {len(ingested.chunks)} clauses"
          + (f", transcribed page(s) {list(ingested.transcribed_pages)}"
             if ingested.transcribed_pages else ""), flush=True)
    result = extract_treaty_rag(ingested, client=client, model=model, embedder=embedder,
                                store=store, k=k)
    prov = result.outcome.provenance
    status = "QUARANTINED " + result.outcome.validation_error if result.outcome.quarantined else "ok"
    print(f"  {row['wording_id']} ({treaty_id}) extracted in {result.seconds:.0f}s: "
          f"{prov.showable_count}/{prov.total} citations verified, {status}", flush=True)
    for group in result.groups.values():
        if group.error:
            print(f"      {group.group}: call failed - {group.error}", flush=True)
        for name, reason in group.rejected:
            print(f"      {group.group}: rejected {name} - {reason}", flush=True)
    return treaty_id, result, ingested


def run(args: Any, *, client: Any, embedder: Any, store: Any) -> int:
    from qa.extraction_accuracy import format_report, load_ground_truth, score_extraction

    wordings = Path(args.wordings)
    truth = load_ground_truth(wordings / "ground_truth.json")
    truth_rows = json.loads((wordings / "ground_truth.json").read_text(encoding="utf-8"))["fields"]
    wanted = set(args.only) if args.only else None
    rows = [r for r in _manifest_rows(wordings) if wanted is None or r["treaty_id"] in wanted]
    model = args.model or default_model()

    print(f"RAG-first extraction: {len(rows)} wording(s), model {model}, "
          f"store {args.store}, k={args.k}, {args.workers} in parallel", flush=True)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(
            lambda r: _one(r, wordings, client=client, model=model, embedder=embedder,
                           store=store, k=args.k),
            rows,
        ))
    elapsed = time.monotonic() - started

    from datetime import datetime, timezone

    when = datetime.now(timezone.utc).isoformat(timespec="seconds")
    by_id = {r["treaty_id"]: r for r in rows}
    extracted, pages, provenance, retrieval, ingestions = {}, {}, {}, {}, {}
    hit_total = hit_ok = cited_total = cited_ok = 0
    quarantined = []
    for treaty_id, result, ingested in results:
        outcome = result.outcome
        extracted[treaty_id] = _jsonable(outcome.fields)
        prov = outcome.provenance
        pages[treaty_id] = {n: p.page for n, p in prov.fields.items() if p.showable}
        provenance[treaty_id] = prov.to_json()
        cited_total += prov.total
        cited_ok += prov.showable_count
        if outcome.quarantined:
            quarantined.append(f"{treaty_id}: {outcome.validation_error}")
        clause_of = {c.chunk_id: c.clause_no for c in ingested.chunks}
        hits, total, misses = retrieval_hits(
            [r for r in truth_rows if r["treaty_id"] == treaty_id], result, clause_of
        )
        hit_ok += hits
        hit_total += total
        retrieval[treaty_id] = {
            "hits": hits, "total": total, "misses": misses, "seconds": round(result.seconds, 1),
            "groups": {g.group: list(g.retrieved) for g in result.groups.values()},
        }
        ingestions[treaty_id] = ingestion_record(
            by_id[treaty_id], result, ingested, model=model,
            embed_model=getattr(embedder, "model", type(embedder).__name__),
            store=args.store, hits=hits, total=total,
            bucket=os.environ.get("GCS_BUCKET"), when=when,
        )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "extracted.json").write_text(json.dumps(
        {"extracted": extracted, "pages": pages, "provenance": provenance,
         "retrieval": retrieval, "seconds": round(elapsed, 1), "model": model},
        indent=2, sort_keys=True), encoding="utf-8")
    (out / "ingestions.json").write_text(
        json.dumps(ingestions, indent=2, sort_keys=True), encoding="utf-8")

    report = score_extraction(truth, extracted, pages=pages,
                              only_treaties=sorted(wanted) if wanted else None)
    print()
    print(format_report(report))
    print()
    print("Retrieval - was the governing clause among those retrieved?")
    print("=" * 46)
    print(f"hit rate           {hit_ok}/{hit_total}  {hit_ok / hit_total if hit_total else 0:.1%}")
    for treaty_id, info in retrieval.items():
        for miss in info["misses"]:
            print(f"  miss  {treaty_id}  {miss}")
    rate = cited_ok / cited_total if cited_total else 0.0
    print()
    print("C-7 - verified field citations")
    print("=" * 46)
    print(f"verified or transcribed  {cited_ok}/{cited_total}  {rate:.1%}")
    print()
    print(f"structural: {len(rows) - len(quarantined)}/{len(rows)} ingestable")
    for note in quarantined:
        print(f"  quarantined  {note}")
    print(f"wall clock: {elapsed:.0f}s for {len(rows)} wording(s)")
    gate = report.passed and rate >= CITATION_BAR and not quarantined
    print(f"gate: {'PASS' if gate else 'FAIL'}")
    print(f"wrote {out / 'extracted.json'}")
    return 0 if gate else 1


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - live only
    import argparse

    from catsight_agent.tools.retrieval import (
        FirestoreVectorStore,
        GeminiEmbedder,
        InMemoryVectorStore,
    )

    parser = argparse.ArgumentParser(description="RAG-first extraction (Phase 2).")
    parser.add_argument("--wordings", default="data/synthetic/wordings")
    parser.add_argument("--out", default="data/extracted")
    parser.add_argument("--store", choices=("memory", "firestore"), default="memory")
    parser.add_argument("--model", default=None)
    parser.add_argument("--only", action="append")
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("GOOGLE_CLOUD_LOCATION") or "global"
    embedder = GeminiEmbedder(project=project, location=location,
                              model=os.environ.get("EMBED_MODEL") or "gemini-embedding-001",
                              cache_path=os.environ.get("EMBED_CACHE") or "data/cache/embeddings.jsonl",
                              requests_per_minute=float(os.environ.get("EMBED_RPM") or 12))
    if args.store == "firestore":
        from google.cloud import firestore

        store: Any = FirestoreVectorStore(firestore.Client(
            project=project, database=os.environ.get("FIRESTORE_DATABASE") or "(default)"))
    else:
        store = InMemoryVectorStore()
    return run(args, client=build_client(), embedder=embedder, store=store)


if __name__ == "__main__":
    raise SystemExit(main())
