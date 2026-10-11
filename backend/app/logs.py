"""Structured logs and optional Cloud Trace - observability without a UI.

Cloud Run sends anything a container writes to stdout to Cloud Logging, and a
line that is a JSON object becomes a structured entry: `severity` sets the
level, `message` the summary, and every other key is searchable as
`jsonPayload.<key>`. So one JSON line per event, with the run id on it, is all
it takes to follow a run end to end or count guardrail trips in a log-based
metric - no logging library, no extra service.

What is never logged: a raw IP (only a short salted hash, enough to see that
requests came from one client), the text of a user's question, or any prompt.

Guardrail events, for log-based metrics: `citation_withheld`,
`unsupported_figures`, `counsel_dropped`, `limit_refused`.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, TextIO

from starlette.concurrency import iterate_in_threadpool

__all__ = ["log_event", "hash_ip", "observe", "setup_tracing"]

_SALT = os.environ.get("LOG_IP_SALT", "catsight")


def hash_ip(ip: str | None) -> str:
    """A short, salted, one-way tag for a client - never the address itself."""
    return hashlib.sha256(f"{_SALT}:{ip or 'unknown'}".encode()).hexdigest()[:12]


def log_event(event: str, *, severity: str = "INFO", stream: TextIO | None = None, **fields: Any) -> None:
    """Write one structured log line. Never raises: logging must not break a
    request."""
    entry = {
        "severity": severity,
        "message": f"{event}" + (f" {fields['run_id']}" if fields.get("run_id") else ""),
        "event": event,
        "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "component": "catsight-api",
        **fields,
    }
    try:
        print(json.dumps(entry, default=str, separators=(",", ":")), file=stream or sys.stdout, flush=True)
    except Exception:  # noqa: BLE001
        pass


def _frame(chunk: str) -> dict[str, Any] | None:
    line = chunk.strip()
    if not line.startswith("data:"):
        return None
    try:
        return json.loads(line[5:])
    except json.JSONDecodeError:
        return None


async def _aiter(stream: Any) -> AsyncIterator[str]:
    """Some streams are async generators, the numbers-only one is a plain one."""
    if hasattr(stream, "__aiter__"):
        async for chunk in stream:
            yield chunk
    else:  # off the event loop, as Starlette itself would run it
        async for chunk in iterate_in_threadpool(stream):
            yield chunk


async def observe(stream: Any, *, run_id: str, event_id: str, mode: str) -> AsyncIterator[str]:
    """Pass an analysis stream through unchanged, logging what happens in it.
    `mode` is live, replay or cap_replay."""
    started = time.monotonic()
    log_event("analysis_started", run_id=run_id, event_id=event_id, mode=mode)
    outcome: dict[str, Any] = {"verified": 0, "withheld": 0, "calls": None, "cost_usd": None,
                               "error": None, "tool_calls": 0, "retrievals": 0}
    # Per-run breakdown for the dashboard's run table: seconds per agent stage
    # and to the first engine result, measured as frames pass through.
    stage_started: dict[str, float] = {}
    agent_seconds: dict[str, float] = {}
    async for chunk in _aiter(stream):
        frame = _frame(chunk)
        if frame is not None:
            now = time.monotonic()
            if frame.get("type") == "stage" and frame.get("agent"):
                agent = str(frame["agent"])
                if frame.get("status") == "started":
                    stage_started[agent] = now
                elif frame.get("status") == "completed" and agent in stage_started:
                    agent_seconds[agent] = round(now - stage_started.pop(agent), 2)
            elif (frame.get("type") == "result" and frame.get("key") == "impact"
                  and "money_seconds" not in outcome):
                outcome["money_seconds"] = round(now - started, 2)
            _log_frame(frame, run_id, outcome)
        yield chunk
    log_event(
        "analysis_done", severity="ERROR" if outcome["error"] else "INFO",
        run_id=run_id, event_id=event_id, mode=mode,
        seconds=round(time.monotonic() - started, 2),
        agent_seconds=agent_seconds or None,
        **{k: v for k, v in outcome.items() if v is not None},
    )


def _token_totals(usage: Any) -> tuple[int | None, int | None]:
    """Input and output tokens summed across models, from the report frame's
    usage map ({model: {"input": n, "output": n}}). Anything else -> None."""
    if not isinstance(usage, dict):
        return None, None
    rows = [u for u in usage.values() if isinstance(u, dict)]
    if not rows:
        return None, None
    return (sum(int(u.get("input") or 0) for u in rows),
            sum(int(u.get("output") or 0) for u in rows))


def _log_frame(frame: dict[str, Any], run_id: str, outcome: dict[str, Any]) -> None:
    kind = frame.get("type")
    if kind == "stage":
        log_event("stage", run_id=run_id, agent=frame.get("agent"), status=frame.get("status"))
    elif kind == "tool":
        outcome["tool_calls"] += 1
    elif kind == "retrieval":
        outcome["retrievals"] += 1
        log_event("retrieval", run_id=run_id, treaty_id=frame.get("treaty_id"),
                  hits=len(frame.get("hits") or []))
    elif kind == "flag" and frame.get("status") == "verified":
        outcome["verified"] += 1
        flag = frame.get("flag") or {}
        log_event("citation_verified", run_id=run_id, treaty_id=flag.get("treaty_id"),
                  issue_type=flag.get("issue_type"))
    elif kind == "verification":
        withheld = frame.get("withheld") or []
        outcome["withheld"] = len(withheld)
        for item in withheld:
            flag = item.get("flag", item) if isinstance(item, dict) else {}
            log_event("citation_withheld", severity="WARNING", run_id=run_id,
                      treaty_id=flag.get("treaty_id"), issue_type=flag.get("issue_type"),
                      reason=(item.get("reason") if isinstance(item, dict) else None))
    elif kind == "report":
        calls = frame.get("calls") or {}
        outcome["calls"] = sum(calls.values())
        outcome["calls_by_agent"] = calls or None
        outcome["cost_usd"] = frame.get("cost_usd")
        outcome["tokens"] = frame.get("usage")
        outcome["tokens_in"], outcome["tokens_out"] = _token_totals(frame.get("usage"))
        figures = frame.get("unsupported_figures") or []
        if figures:
            log_event("unsupported_figures", severity="WARNING", run_id=run_id, where="report",
                      count=len(figures), figures=figures[:10])
    elif kind == "warning":
        log_event("agent_warning", severity="WARNING", run_id=run_id,
                  treaty_id=frame.get("treaty_id"), detail=str(frame.get("message"))[:300])
    elif kind == "error":
        outcome["error"] = str(frame.get("message"))[:300]
        log_event("analysis_error", severity="ERROR", run_id=run_id, detail=outcome["error"])


def setup_tracing(enabled: bool) -> bool:  # pragma: no cover - needs GCP credentials
    """Send ADK's OpenTelemetry spans (workflow, nodes, Gemini calls) to Cloud
    Trace. Off unless asked for, so tests and local runs send nothing. Prompt
    and response text is kept out of spans: timings and token counts only."""
    if not enabled:
        return False
    os.environ.setdefault("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS", "false")
    try:
        from google.adk.telemetry.google_cloud import get_gcp_exporters
        from google.adk.telemetry.setup import maybe_set_otel_providers

        maybe_set_otel_providers([get_gcp_exporters(enable_cloud_tracing=True)])
    except Exception as exc:  # noqa: BLE001 - tracing is optional; say why and carry on
        log_event("tracing_unavailable", severity="WARNING", detail=f"{type(exc).__name__}: {exc}")
        return False
    log_event("tracing_enabled")
    return True
