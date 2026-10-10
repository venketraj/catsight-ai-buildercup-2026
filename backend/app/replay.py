"""Cached instant replay - FR-JUDGE-2, the demo safety net.

A real live agent run is recorded frame by frame, with the time each frame
arrived. Playing it back streams the same frames in a few seconds, opened by a
`notice` frame that says plainly it is a recording and when it was made. So a
judge never waits on a cold model, the daily cap never shows an error, and the
replay is never passed off as live.

Only complete runs are recorded: a run that errored or produced no report is
not a demo of anything.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

__all__ = ["fixture_path", "has_replay", "record", "play"]

#: Playback is compressed to about this long, whatever the live run took.
TARGET_SECONDS = 6.0
#: Never pause longer than this between two frames during playback.
MAX_GAP = 0.6


def fixture_path(directory: Path | str, event_id: str) -> Path:
    return Path(directory) / f"{event_id}.json"


def has_replay(directory: Path | str, event_id: str) -> bool:
    path = fixture_path(directory, event_id)
    return path.parent == Path(directory) and path.exists()


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'), default=str)}\n\n"


def _frame(chunk: str) -> dict[str, Any] | None:
    line = chunk.strip()
    if not line.startswith("data:"):
        return None
    try:
        return json.loads(line[5:])
    except json.JSONDecodeError:
        return None


async def record(
    stream: AsyncIterator[str], directory: Path | str, event_id: str
) -> AsyncIterator[str]:
    """Pass a live stream through unchanged, saving it as a replay fixture
    if - and only if - it completed with a report and no error."""
    started = time.monotonic()
    frames: list[dict[str, Any]] = []
    async for chunk in stream:
        frame = _frame(chunk)
        if frame is not None:
            frames.append({"t": round(time.monotonic() - started, 3), "frame": frame})
        yield chunk

    kinds = {f["frame"].get("type") for f in frames}
    if "report" not in kinds or "error" in kinds:
        return
    payload = {
        "event_id": event_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": frames[-1]["t"] if frames else 0,
        "frames": frames,
    }
    try:
        path = fixture_path(directory, event_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    except OSError:  # a read-only filesystem must not break a finished stream
        pass


async def play(
    directory: Path | str, event_id: str, *, reason: str = "requested"
) -> AsyncIterator[str]:
    """Stream a recorded run, compressed to about TARGET_SECONDS."""
    data = json.loads(fixture_path(directory, event_id).read_text(encoding="utf-8"))
    live_seconds = float(data.get("seconds") or 0)
    speed = max(1.0, live_seconds / TARGET_SECONDS)
    why = {
        "requested": "Instant replay",
        "cap": "The daily analysis cap has been reached - showing an instant replay",
        "cached_only": "Instant-replay mode is on",
    }.get(reason, "Instant replay")
    yield _sse({
        "type": "notice", "kind": "replay", "reason": reason,
        "recorded_at": data.get("recorded_at"), "live_seconds": round(live_seconds),
        "message": (f"{why} of a real live run recorded {str(data.get('recorded_at'))[:16].replace('T', ' ')} "
                    f"UTC (it took {round(live_seconds)}s live). Run live for a fresh analysis."),
    })
    previous = 0.0
    for row in data.get("frames", []):
        gap = (float(row["t"]) - previous) / speed
        previous = float(row["t"])
        if gap > 0:
            await asyncio.sleep(min(gap, MAX_GAP))
        frame = dict(row["frame"])
        if frame.get("type") == "done":
            frame["replay"] = True
        yield _sse(frame)
