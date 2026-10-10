"""The one-time cloud seed (ingest.seed_cloud), against fakes."""

from __future__ import annotations

import json
import shutil

import pytest

from catsight_agent.store import FirestoreStore, LocalStore
from ingest.seed_cloud import apply_seed, main, plan_seed


class _Collection:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def document(self, key):
        return (self.name, key)

    def stream(self):
        class Doc:
            def __init__(self, data):
                self._data = data

            def to_dict(self):
                return self._data

        return [Doc(d) for d in self.store.data.get(self.name, {}).values()]


class _Batch:
    def __init__(self, store):
        self.store, self.ops = store, []

    def set(self, ref, data):
        self.ops.append((ref, data))

    def commit(self):
        self.store.commits += 1
        for (name, key), data in self.ops:
            self.store.data.setdefault(name, {})[key] = json.loads(json.dumps(data))


class _FakeFirestore:
    def __init__(self):
        self.data, self.commits = {}, 0

    def collection(self, name):
        return _Collection(self, name)

    def batch(self):
        return _Batch(self)


class _FakeBucket:
    def __init__(self):
        self.uploaded = {}

    def blob(self, name):
        outer = self

        class Blob:
            def upload_from_filename(self, path, content_type=None):
                outer.uploaded[name] = (path, content_type)

        return Blob()


def test_the_plan_covers_every_collection_and_the_wordings():
    plan = plan_seed("data", bucket="my-bucket")
    assert len(plan.documents["treaties"]) == 24
    assert len(plan.documents["exposures"]) == 592
    assert len(plan.documents["cedents"]) == 8
    assert set(plan.documents["events"]) >= {"jebi-2018", "noto-2024"}
    method = plan.documents["methodology"]["2026.1"]
    assert method["vulnerability"]["wind"]["function"] == "emanuel_2011"
    assert "_comment" not in method and "_comment" not in method["vulnerability"]
    assert len(plan.documents["extractions"]) == 8
    assert len(plan.uploads) == 8
    assert all(name.startswith("wordings/") for _, name in plan.uploads)
    assert any("Firestore" not in line for line in plan.summary())


def test_the_bucket_placeholder_is_filled_in_source_pdf():
    plan = plan_seed("data", bucket="my-bucket")
    pdfs = [t["source_pdf"] for t in plan.documents["treaties"].values() if t.get("source_pdf")]
    assert pdfs and all("{bucket}" not in p for p in pdfs)


def test_applying_the_seed_yields_a_store_identical_to_local():
    """The point of the seed: Firestore then answers exactly as local does."""
    plan = plan_seed("data", bucket="b")
    fake, bucket = _FakeFirestore(), _FakeBucket()
    written = apply_seed(plan, firestore_client=fake, bucket=bucket)

    assert written == sum(len(d) for d in plan.documents.values()) + len(plan.uploads)
    assert fake.commits >= 2, "592 exposures need more than one batch of 400"
    assert len(bucket.uploaded) == 8

    cloud = FirestoreStore(fake, today="2026-10-10")
    local = LocalStore("data", today="2026-10-10")
    assert cloud.events() == local.events()
    assert cloud.methodology()["version"] == local.methodology()["version"]
    # source_pdf differs by design (bucket filled in); compare the rest.
    strip = lambda p: [t.__class__(**{**t.__dict__, "source_pdf": None}) for t in p.treaties]
    assert strip(cloud.portfolio()) == strip(local.portfolio())


def test_reconciliations_are_seeded_when_present(tmp_path):
    shutil.copytree("data", tmp_path / "data", ignore=shutil.ignore_patterns("raw"))
    (tmp_path / "data" / "extracted" / "reconciliation.json").write_text(
        json.dumps({"T-001": {"status": "reconciled"}}), encoding="utf-8"
    )
    (tmp_path / "data" / "extracted" / "ingestions.json").write_text(
        json.dumps({"T-001": {"treaty_id": "T-001", "clauses": 31}}), encoding="utf-8"
    )
    plan = plan_seed(tmp_path / "data", bucket="b")
    assert plan.documents["reconciliations"] == {"T-001": {"status": "reconciled"}}
    assert plan.documents["ingestions"]["T-001"]["clauses"] == 31


def test_optional_artifacts_may_be_absent(tmp_path):
    shutil.copytree(
        "data", tmp_path / "data", ignore=shutil.ignore_patterns("raw", "extracted", "synthetic")
    )
    plan = plan_seed(tmp_path / "data", bucket="b")
    assert "extractions" not in plan.documents
    assert "reconciliations" not in plan.documents
    assert plan.uploads == []


def test_a_missing_book_says_how_to_build_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="seed_portfolio"):
        plan_seed(tmp_path, bucket="b")


def test_cli_dry_run_writes_nothing(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setenv("GCS_BUCKET", "proj-docs")
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "gs://proj-docs" in out


@pytest.mark.parametrize("env", [{}, {"GOOGLE_CLOUD_PROJECT": "p", "GCS_BUCKET": "<GCP_PROJECT_ID>-docs"}])
def test_cli_refuses_without_real_configuration(monkeypatch, capsys, env):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCS_BUCKET", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert main([]) == 2
