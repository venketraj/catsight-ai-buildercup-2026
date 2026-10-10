"""Suite-wide safety settings."""

from __future__ import annotations

import os

import pytest


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
