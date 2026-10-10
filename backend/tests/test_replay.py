"""Cached instant replay (app.replay) and its use by API-4."""

from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from app import replay as replay_module
from app.config import load_settings
from app.main import create_app
from app.replay import fixture_path, has_replay, play, record
from catsight_agent.store import LocalStore


def _sse(frame):
    return f"data: {json.dumps(frame)}\n\n"


def _frames(chunks):
    return [json.loads(c.strip()[5:]) for c in chunks if c.strip().startswith("data:")]


async def _gen(frames, extra=()):
    for frame in frames:
        yield _sse(frame)
    for raw in extra:
        yield raw


GOOD = [{"type": "stage", "agent": "event_intel", "status": "started"},
        {"type": "report", "markdown": "## Summary", "unsupported_figures": [], "calls": {}},
        {"type": "done", "analysis_id": "replay-x", "agents": True}]


def _collect(agen):
    async def go():
        return [chunk async for chunk in agen]

    return asyncio.run(go())


def test_a_complete_live_run_is_recorded_and_passed_through(tmp_path):
    out = _collect(record(_gen(GOOD, extra=["not a frame\n\n", "data: {broken\n\n"]), tmp_path, "x"))
    assert len(out) == 5, "the live stream passes through untouched"
    saved = json.loads(fixture_path(tmp_path, "x").read_text(encoding="utf-8"))
    assert [f["frame"]["type"] for f in saved["frames"]] == ["stage", "report", "done"]
    assert saved["event_id"] == "x" and saved["recorded_at"].endswith("+00:00")
    assert has_replay(tmp_path, "x")


def test_failed_or_incomplete_runs_are_not_recorded(tmp_path):
    _collect(record(_gen(GOOD[:1] + [{"type": "error", "message": "x"}] + GOOD[1:]), tmp_path, "a"))
    _collect(record(_gen([GOOD[0], GOOD[2]]), tmp_path, "b"))
    _collect(record(_gen([]), tmp_path, "c"))
    assert not any(has_replay(tmp_path, e) for e in ("a", "b", "c"))


def test_recording_survives_a_read_only_filesystem(tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise OSError("read-only")

    monkeypatch.setattr(replay_module.Path, "write_text", refuse)
    out = _collect(record(_gen(GOOD), tmp_path, "x"))
    assert len(out) == 3


def test_playback_is_labelled_compressed_and_marked(tmp_path, monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(replay_module.asyncio, "sleep", fake_sleep)
    fixture_path(tmp_path, "x").write_text(json.dumps({
        "event_id": "x", "recorded_at": "2026-10-10T07:00:00+00:00", "seconds": 60,
        "frames": [{"t": 0, "frame": GOOD[0]}, {"t": 30, "frame": GOOD[1]},
                   {"t": 60, "frame": GOOD[2]}],
    }), encoding="utf-8")

    frames = _frames(_collect(play(tmp_path, "x", reason="cap")))
    notice = frames[0]
    assert notice["type"] == "notice" and notice["kind"] == "replay"
    assert "daily analysis cap" in notice["message"] and "took 60s live" in notice["message"]
    assert frames[-1]["replay"] is True
    assert sleeps and max(sleeps) <= replay_module.MAX_GAP
    assert "Instant-replay mode" in _frames(_collect(play(tmp_path, "x", reason="cached_only")))[0]["message"]
    assert _frames(_collect(play(tmp_path, "x", reason="other")))[0]["message"].startswith("Instant replay")


def test_event_ids_cannot_escape_the_replay_folder(tmp_path):
    assert not has_replay(tmp_path, "../x")


# --------------------------------------------------------------------------- #
# API-4
# --------------------------------------------------------------------------- #


def _api(tmp_path, **env):
    fixture_path(tmp_path, "jebi-2018").write_text(json.dumps({
        "event_id": "jebi-2018", "recorded_at": "2026-10-10T07:00:00+00:00", "seconds": 0.1,
        "frames": [{"t": 0, "frame": g} for g in GOOD],
    }), encoding="utf-8")
    settings = {"GOOGLE_CLOUD_PROJECT": "p", "REPLAY_FIXTURE_DIR": str(tmp_path), **env}
    return TestClient(create_app(load_settings(settings), store=LocalStore("data")))


def test_replay_on_request(tmp_path):
    client = _api(tmp_path)
    response = client.post("/api/analyses", json={"event_id": "jebi-2018", "replay": True})
    frames = _frames(response.text.split("\n\n"))
    assert frames[0]["type"] == "notice" and frames[-1]["replay"] is True
    missing = client.post("/api/analyses", json={"event_id": "noto-2024", "replay": True})
    assert missing.status_code == 404 and "Run it live once" in missing.json()["detail"]


def test_replay_only_mode(tmp_path):
    client = _api(tmp_path, CACHED_REPLAY_ONLY="true")
    frames = _frames(client.post("/api/analyses", json={"event_id": "jebi-2018"}).text.split("\n\n"))
    assert "Instant-replay mode" in frames[0]["message"]


def test_the_cap_hit_path_serves_the_replay_not_an_error(tmp_path):
    client = _api(tmp_path, RATE_LIMIT_PER_HOUR="1")
    first = client.post("/api/analyses", json={"event_id": "jebi-2018", "agents": False})
    assert first.status_code == 200
    capped = client.post("/api/analyses", json={"event_id": "jebi-2018", "agents": False})
    assert capped.status_code == 200
    assert "daily analysis cap" in _frames(capped.text.split("\n\n"))[0]["message"]


def test_events_say_which_have_a_replay(tmp_path):
    events = {e["event_id"]: e for e in _api(tmp_path).get("/api/events").json()["events"]}
    assert events["jebi-2018"]["replay_available"] is True
    assert events["noto-2024"]["replay_available"] is False


def test_live_agent_runs_are_recorded(tmp_path):
    from catsight_agent.agents import AgentDeps
    from catsight_agent.tools.retrieval import DeterministicEmbedder
    from tests.test_agents import VECTORS, FakeGemini

    config = load_settings({"GOOGLE_CLOUD_PROJECT": "p", "DATA_BACKEND": "firestore",
                            "REPLAY_FIXTURE_DIR": str(tmp_path)})
    api = create_app(config, store=LocalStore("data", today="2026-10-10"))
    from app.runs import MemoryRunStore

    api.state.runs = MemoryRunStore()
    api.state.make_deps = lambda emit: AgentDeps(
        client=FakeGemini(), model_main="m", model_reason="r",
        embedder=DeterministicEmbedder(), vectors=VECTORS, emit=emit)
    TestClient(api).post("/api/analyses", json={"event_id": "jebi-2018"})
    assert has_replay(tmp_path, "jebi-2018")
