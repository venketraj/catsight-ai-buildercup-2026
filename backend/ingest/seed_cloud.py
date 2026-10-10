"""One-time seed of the GCP data services from the local build artifacts.

    python -m ingest.seed_cloud            # dry run: says what it would write
    python -m ingest.seed_cloud --apply    # writes

Writes, idempotently (every document and object is keyed, so a re-run
overwrites rather than duplicating):

  Cloud Storage  gs://$GCS_BUCKET/wordings/<file>.pdf     the treaty wordings
  Firestore      cedents, treaties, exposures             the treaty book
                 events                                   replay events
                 methodology                              method versions, each
                                                          with its damage curve
                 extractions                              Gemini-extracted terms
                                                          and per-field citations
                 reconciliations                          book vs wording

After this the API runs with DATA_BACKEND=firestore and reads only from these
services. The generators are never part of the runtime.

Clients are injected so the whole module is testable with fakes; only `main`
constructs real ones.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

__all__ = ["SeedPlan", "plan_seed", "apply_seed", "main"]


@dataclass
class SeedPlan:
    """Everything the seed will write, built from local files."""

    documents: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    #: (local path, object name in the bucket)
    uploads: list[tuple[Path, str]] = field(default_factory=list)

    def summary(self) -> list[str]:
        lines = [f"  firestore {name:<16} {len(docs):>4} documents"
                 for name, docs in sorted(self.documents.items())]
        lines.append(f"  storage   wordings/        {len(self.uploads):>4} PDFs")
        return lines


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def plan_seed(data_dir: Path | str = "data", *, bucket: str) -> SeedPlan:
    """Assemble the seed from the local build artifacts. Reads, never writes."""
    data = Path(data_dir)
    plan = SeedPlan()

    book = data / "book"
    if not (book / "treaties.json").exists():
        raise FileNotFoundError(
            f"no treaty book at {book}. Run: python -m ingest.seed_portfolio --out {book}"
        )
    plan.documents["cedents"] = {c["cedent_id"]: c for c in _read(book / "cedents.json")}
    plan.documents["exposures"] = {e["exposure_id"]: e for e in _read(book / "exposures.json")}

    treaties = {}
    for treaty in _read(book / "treaties.json"):
        if treaty.get("source_pdf"):
            treaty = {**treaty, "source_pdf": treaty["source_pdf"].replace("{bucket}", bucket)}
        treaties[treaty["treaty_id"]] = treaty
    plan.documents["treaties"] = treaties

    plan.documents["events"] = {
        p.stem: _read(p) for p in sorted((data / "events").glob("*.json"))
    }

    # Each method version is stored self-contained, with its damage curve
    # embedded, so a version can never drift from the parameters it names.
    method = _read(data / "methodology.json")
    method.pop("_comment", None)
    method["vulnerability"] = _read(data / method["vulnerability_file"])
    method["vulnerability"].pop("_comment", None)
    plan.documents["methodology"] = {method["version"]: method}

    extracted_path = data / "extracted" / "extracted.json"
    if extracted_path.exists():
        extracted = _read(extracted_path)
        provenance = extracted.get("provenance") or {}
        plan.documents["extractions"] = {
            treaty_id: {
                "treaty_id": treaty_id,
                "fields": fields,
                "provenance": provenance.get(treaty_id),
            }
            for treaty_id, fields in (extracted.get("extracted") or {}).items()
        }

    reconciliation_path = data / "extracted" / "reconciliation.json"
    if reconciliation_path.exists():
        plan.documents["reconciliations"] = _read(reconciliation_path)

    benchmark_path = data / "benchmark.json"
    if benchmark_path.exists():
        benchmark = _read(benchmark_path)
        benchmark.pop("_comment", None)
        plan.documents["benchmark"] = {"current": benchmark}

    ingestions_path = data / "extracted" / "ingestions.json"
    if ingestions_path.exists():
        plan.documents["ingestions"] = _read(ingestions_path)

    wordings = data / "synthetic" / "wordings"
    for pdf in sorted(wordings.glob("*.pdf")):
        plan.uploads.append((pdf, f"wordings/{pdf.name}"))
    return plan


def apply_seed(plan: SeedPlan, *, firestore_client: Any, bucket: Any) -> int:
    """Write the plan. Firestore writes go in batches of up to 400 (the API
    limit is 500 operations per batch). Returns the number of writes."""
    written = 0
    for name, docs in plan.documents.items():
        collection = firestore_client.collection(name)
        items = list(docs.items())
        for start in range(0, len(items), 400):
            batch = firestore_client.batch()
            for key, data in items[start:start + 400]:
                batch.set(collection.document(key), data)
            batch.commit()
            written += len(items[start:start + 400])
    for path, object_name in plan.uploads:
        bucket.blob(object_name).upload_from_filename(str(path), content_type="application/pdf")
        written += 1
    return written


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Seed Firestore and Cloud Storage once.")
    parser.add_argument("--data", default="data")
    parser.add_argument("--apply", action="store_true", help="write; without it, a dry run")
    args = parser.parse_args(argv)

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    bucket_name = os.environ.get("GCS_BUCKET")
    if not project or not bucket_name or "<" in project + bucket_name:
        print("GOOGLE_CLOUD_PROJECT and GCS_BUCKET must be set (see backend/.env.example).")
        return 2

    plan = plan_seed(args.data, bucket=bucket_name)
    print(f"seed for project {project}, bucket gs://{bucket_name}")
    for line in plan.summary():
        print(line)
    if not args.apply:
        print("dry run - nothing written. Re-run with --apply to write.")
        return 0

    from google.cloud import firestore, storage  # pragma: no cover - live only

    database = os.environ.get("FIRESTORE_DATABASE") or "(default)"  # pragma: no cover
    written = apply_seed(  # pragma: no cover
        plan,
        firestore_client=firestore.Client(project=project, database=database),
        bucket=storage.Client(project=project).bucket(bucket_name),
    )
    print(f"wrote {written} documents and objects")  # pragma: no cover
    return 0  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
