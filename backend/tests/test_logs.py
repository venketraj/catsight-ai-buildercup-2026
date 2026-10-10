"""Structured logs (app/logs.py): one JSON line per event, the run id on it,
guardrail trips named for log-based metrics, and nothing private in them."""

from __future__ import annotations

import asyncio
import io
import json

from app.logs import hash_ip, log_event, observe, setup_tracing


def _lines(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]


def _sse(frame: dict) -> str:
    return f"data: {json.dumps(frame)}\n\n"


def test_a_log_line_is_one_json_object_cloud_logging_can_parse():
    out = io.StringIO()
    log_event("stage", stream=out, run_id="run-1", agent="verifier")
    entry = json.loads(out.getvalue())
    assert entry["severity"] == "INFO"
    assert entry["event"] == "stage"
    assert entry["run_id"] == "run-1"
    assert entry["message"] == "stage run-1"
    assert "time" in entry


def test_a_client_is_tagged_by_a_hash_never_by_its_address():
    tag = hash_ip("203.0.113.7")
    assert "203.0.113.7" not in tag
    assert len(tag) == 12
    assert tag == hash_ip("203.0.113.7")
    assert tag != hash_ip("203.0.113.8")


def test_observe_passes_the_stream_through_and_logs_the_guardrail_trips(capsys):
    frames = [
        {"type": "stage", "agent": "verifier", "status": "started"},
        {"type": "flag", "status": "verified", "flag": {"treaty_id": "T-004", "issue_type": "EXCLUSION"}},
        {"type": "verification", "header": "1 of 1", "withheld": [
            {"flag": {"treaty_id": "T-002", "issue_type": "HOURS"}, "reason": "quote not found"}]},
        {"type": "report", "calls": {"reporter": 1, "verifier": 2}, "cost_usd": "0.0081",
         "unsupported_figures": ["12.3"]},
        {"type": "done"},
    ]

    async def stream():
        for f in frames:
            yield _sse(f)

    async def drain():
        return [c async for c in observe(stream(), run_id="run-9", event_id="jebi-2018", mode="live")]

    passed = asyncio.run(drain())
    assert passed == [_sse(f) for f in frames]

    logged = _lines(capsys)
    events = [e["event"] for e in logged]
    assert events[0] == "analysis_started"
    assert "citation_verified" in events
    withheld = next(e for e in logged if e["event"] == "citation_withheld")
    assert (withheld["treaty_id"], withheld["reason"], withheld["severity"]) == ("T-002", "quote not found", "WARNING")
    assert next(e for e in logged if e["event"] == "unsupported_figures")["count"] == 1
    done = logged[-1]
    assert done["event"] == "analysis_done"
    assert (done["verified"], done["withheld"], done["calls"], done["cost_usd"]) == (1, 1, 3, "0.0081")
    assert all(e.get("run_id") == "run-9" for e in logged)


def test_observe_accepts_a_plain_generator_too(capsys):
    def stream():
        yield _sse({"type": "done"})

    async def drain():
        return [c async for c in observe(stream(), run_id="r", event_id="e", mode="numbers")]

    assert len(asyncio.run(drain())) == 1
    assert _lines(capsys)[-1]["mode"] == "numbers"


def test_a_refused_request_is_logged_with_a_hashed_client(capsys):
    from app.main import _refused

    _refused("The daily analysis cap has been reached.", "198.51.100.4", "analysis")
    entry = _lines(capsys)[-1]
    assert (entry["event"], entry["kind"], entry["endpoint"]) == ("limit_refused", "daily_cap", "analysis")
    assert entry["client"] == hash_ip("198.51.100.4")
    assert "198.51.100.4" not in json.dumps(entry)


def test_a_dropped_counsel_is_a_guardrail_event(capsys):
    from app.main import _log_courtroom

    _log_courtroom("run-2", {"skipped": False, "flag": {"treaty_id": "T-004"},
                             "sides": {"cedent": {"verified": True},
                                       "reinsurer": {"verified": False, "dropped_reason": "quote not in clause"}}})
    logged = _lines(capsys)
    dropped = next(e for e in logged if e["event"] == "counsel_dropped")
    assert (dropped["side"], dropped["reason"]) == ("reinsurer", "quote not in clause")
    assert next(e for e in logged if e["event"] == "courtroom_done")["sides_verified"] == 1


def test_tracing_stays_off_unless_asked_for():
    assert setup_tracing(False) is False
