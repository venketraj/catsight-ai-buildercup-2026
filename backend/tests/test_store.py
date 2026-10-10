"""The runtime data store (catsight_agent.store): local JSON and Firestore
behind one interface, plus method-version selection."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from catsight_agent.store import (
    BookNotSeeded,
    DataStore,
    EventNotFound,
    FirestoreStore,
    LocalStore,
    current_methodology,
)


# --------------------------------------------------------------------------- #
# A minimal Firestore fake: collection(name).stream() / .document(id).get()
# --------------------------------------------------------------------------- #


class _Doc:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _Collection:
    def __init__(self, docs):
        self.docs = docs

    def stream(self):
        return [_Doc(d) for d in self.docs.values()]

    def document(self, key):
        outer = self

        class Ref:
            def get(self):
                return _Doc(outer.docs.get(key))

        return Ref()


class _FakeFirestore:
    def __init__(self, collections):
        self.collections = collections

    def collection(self, name):
        return _Collection(self.collections.get(name, {}))


def _seeded_fake():
    """A Firestore holding exactly what the seed writes from local data."""
    def load(name):
        return json.loads(Path("data/book", f"{name}.json").read_text(encoding="utf-8"))

    events = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in Path("data/events").glob("*.json")
    }
    method = json.loads(Path("data/methodology.json").read_text(encoding="utf-8"))
    method["vulnerability"] = json.loads(Path("data/vulnerability.json").read_text(encoding="utf-8"))
    draft = {**method, "version": "2027.1", "effective_from": "2027-01-01"}
    return _FakeFirestore({
        "cedents": {c["cedent_id"]: c for c in load("cedents")},
        "treaties": {t["treaty_id"]: t for t in load("treaties")},
        "exposures": {e["exposure_id"]: e for e in load("exposures")},
        "events": events,
        "methodology": {"2026.1": method, "2027.1": draft},
        "reconciliations": {"T-001": {"treaty_id": "T-001", "status": "reconciled"}},
    })


# --------------------------------------------------------------------------- #
# Both stores answer identically
# --------------------------------------------------------------------------- #


def test_both_stores_satisfy_the_protocol():
    assert isinstance(LocalStore("data"), DataStore)
    assert isinstance(FirestoreStore(_seeded_fake()), DataStore)


def test_firestore_and_local_return_the_same_book_and_events():
    local, cloud = LocalStore("data"), FirestoreStore(_seeded_fake(), today="2026-10-10")
    assert cloud.portfolio() == local.portfolio()
    assert cloud.events() == local.events()
    assert cloud.event("jebi-2018") == local.event("jebi-2018")


def test_the_same_analysis_from_either_store():
    from app.analysis import analyse

    local = analyse("jebi-2018", store=LocalStore("data", today="2026-10-10"))
    cloud = analyse("jebi-2018", store=FirestoreStore(_seeded_fake(), today="2026-10-10"))
    assert cloud.to_json() == local.to_json()


def test_firestore_caches_the_book():
    store = FirestoreStore(_seeded_fake())
    assert store.portfolio() is store.portfolio()


def test_an_empty_firestore_is_not_seeded():
    with pytest.raises(BookNotSeeded, match="seed_cloud"):
        FirestoreStore(_FakeFirestore({})).portfolio()


def test_unknown_events_raise_in_both_stores():
    for store in (LocalStore("data"), FirestoreStore(_seeded_fake())):
        with pytest.raises(EventNotFound):
            store.event("no-such-event")


@pytest.mark.parametrize("hostile", ["../methodology", "a/b", "..\\x"])
def test_event_ids_cannot_escape_the_events_collection(hostile):
    with pytest.raises(EventNotFound):
        LocalStore("data").event(hostile)
    with pytest.raises(EventNotFound):
        FirestoreStore(_seeded_fake()).event(hostile)


def test_reconciliations_from_both_stores(tmp_path):
    cloud = FirestoreStore(_seeded_fake())
    assert cloud.reconciliation("T-001")["status"] == "reconciled"
    assert cloud.reconciliation("T-999") is None

    assert LocalStore(tmp_path).reconciliation("T-001") is None
    (tmp_path / "extracted").mkdir()
    (tmp_path / "extracted" / "reconciliation.json").write_text(
        json.dumps({"T-001": {"status": "discrepancies"}}), encoding="utf-8"
    )
    assert LocalStore(tmp_path).reconciliation("T-001") == {"status": "discrepancies"}


def test_a_missing_local_book_says_how_to_seed_it(tmp_path):
    with pytest.raises(BookNotSeeded, match="seed_portfolio"):
        LocalStore(tmp_path).portfolio()


# --------------------------------------------------------------------------- #
# Method versions
# --------------------------------------------------------------------------- #


def test_the_method_in_force_is_the_latest_approved_effective_version():
    versions = [
        {"version": "2026.1", "effective_from": "2026-10-01", "status": "approved"},
        {"version": "2027.1", "effective_from": "2027-01-01", "status": "approved"},
        {"version": "2026.2", "effective_from": "2026-11-01", "status": "draft"},
    ]
    assert current_methodology(versions, "2026-12-01")["version"] == "2026.1"
    assert current_methodology(versions, "2027-02-01")["version"] == "2027.1"


def test_no_method_in_force_is_an_error():
    with pytest.raises(BookNotSeeded):
        current_methodology([{"version": "x", "effective_from": "2030-01-01",
                              "status": "approved"}], "2026-10-10")


def test_a_future_cloud_version_takes_over_on_its_date():
    store = FirestoreStore(_seeded_fake(), today="2027-02-01")
    assert store.methodology()["version"] == "2027.1"


def test_local_methodology_embeds_its_vulnerability_curve():
    method = LocalStore("data").methodology()
    assert method["version"] == "2026.1"
    assert method["vulnerability"]["earthquake"]["function"] == "mmi_table"


def test_a_new_method_version_changes_the_stamp_not_the_code(tmp_path):
    """The governance story: market practice changes -> a new version file,
    and analyses produced after its date carry the new stamp."""
    from app.analysis import analyse

    shutil.copytree("data", tmp_path / "data", ignore=shutil.ignore_patterns("synthetic", "raw"))
    path = tmp_path / "data" / "methodology.json"
    method = json.loads(path.read_text(encoding="utf-8"))
    method.update(version="2026.2", effective_from="2026-10-05")
    path.write_text(json.dumps(method), encoding="utf-8")

    result = analyse("jebi-2018", store=LocalStore(tmp_path / "data", today="2026-10-10"))
    assert result.to_json()["methodology"] == {"version": "2026.2", "effective_from": "2026-10-05"}


# --------------------------------------------------------------------------- #
# Configuration selects the store
# --------------------------------------------------------------------------- #


def test_data_backend_defaults_to_local():
    from app.config import load_settings
    from app.main import open_store

    config = load_settings({"GOOGLE_CLOUD_PROJECT": "p"})
    assert config.data_backend == "local"
    assert isinstance(open_store(config), LocalStore)


def test_an_unknown_data_backend_falls_back_with_a_warning():
    from app.config import load_settings

    config = load_settings({"GOOGLE_CLOUD_PROJECT": "p", "DATA_BACKEND": "postgres"})
    assert config.data_backend == "local"
    assert any("DATA_BACKEND" in w for w in config.warnings)


def test_firestore_without_a_project_falls_back_with_a_warning():
    from app.config import load_settings

    config = load_settings({"DATA_BACKEND": "Firestore"})
    assert config.data_backend == "local"
    assert any("needs GOOGLE_CLOUD_PROJECT" in w for w in config.warnings)


def test_firestore_backend_is_selected_with_a_project():
    from app.config import load_settings

    config = load_settings({"GOOGLE_CLOUD_PROJECT": "p", "DATA_BACKEND": "firestore"})
    assert config.data_backend == "firestore"


def test_ingestions_from_both_stores(tmp_path):
    assert LocalStore(tmp_path).ingestions() == []
    (tmp_path / "extracted").mkdir()
    (tmp_path / "extracted" / "ingestions.json").write_text(
        json.dumps({"T-002": {"treaty_id": "T-002"}, "T-001": {"treaty_id": "T-001"}}),
        encoding="utf-8",
    )
    assert [r["treaty_id"] for r in LocalStore(tmp_path).ingestions()] == ["T-001", "T-002"]
    cloud = FirestoreStore(_FakeFirestore({"ingestions": {
        "T-2": {"treaty_id": "T-2"}, "T-1": {"treaty_id": "T-1"}}}))
    assert [r["treaty_id"] for r in cloud.ingestions()] == ["T-1", "T-2"]
