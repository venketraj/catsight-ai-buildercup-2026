"""Suite-wide safety settings."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def pytest_configure(config):
    """Ensure working directory is backend/ and derived wording PDFs exist on a
    fresh clone before modules that read them at import time are collected."""
    backend_dir = Path(__file__).resolve().parent.parent
    os.chdir(backend_dir)
    wordings = backend_dir / "data" / "synthetic" / "wordings"
    if not (wordings / "manifest.json").is_file() or not (wordings / "w1.pdf").is_file():
        from ingest.build_wordings import build_all

        build_all(out_dir=wordings)


@pytest.fixture(autouse=True)
def _no_real_firestore(monkeypatch):
    """The ordinary suite must never touch the real database. Any code path
    that constructs a real Firestore client fails loudly instead - except in
    the opt-in live suite (RUN_LIVE=1), which exists to do exactly that."""
    if os.environ.get("RUN_LIVE") == "1":
        return
    from google.cloud import firestore

    def refuse(*args, **kwargs):
        raise RuntimeError("a test tried to open a real Firestore client")

    monkeypatch.setattr(firestore, "Client", refuse)


@pytest.fixture(autouse=True)
def _isolated_replays(tmp_path, monkeypatch):
    """Recorded runs are demo evidence. A test drives the graph with a fake
    model, so its recording must land in a temporary folder - never in
    data/replays, where it could be played back as a real live run."""
    import app.config

    monkeypatch.setattr(app.config, "DEFAULT_REPLAY_DIR", str(tmp_path / "replays"))
