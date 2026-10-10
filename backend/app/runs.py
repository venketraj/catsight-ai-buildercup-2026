"""Completed analysis runs - kept so they can be exported (FR-EXPORT) and,
later, reviewed (FR-REVIEW).

A run is what one stream produced that the engine cannot recompute: the
verified flags with their citations, what was withheld, the report text, the
model cost, and whether it was live or a replay. The engine's figures are NOT
stored - they are deterministic, so an export recomputes them and the document
cannot drift from the engine.

Two stores behind one interface: in memory for local runs, Firestore
(`analyses` collection) in the cloud - Cloud Run may serve the download from a
different instance than the one that ran the analysis.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Protocol, runtime_checkable

__all__ = ["RunStore", "MemoryRunStore", "FirestoreRunStore", "capture", "new_run_id"]


@runtime_checkable
class RunStore(Protocol):
    def save(self, run_id: str, run: dict[str, Any]) -> None: ...

    def get(self, run_id: str) -> dict[str, Any] | None: ...


class MemoryRunStore:
    """Local runs. Bounded, so a long session cannot grow without limit."""

    def __init__(self, limit: int = 50) -> None:
        self.limit = limit
        self._runs: dict[str, dict[str, Any]] = {}

    def save(self, run_id: str, run: dict[str, Any]) -> None:
        self._runs[run_id] = run
        while len(self._runs) > self.limit:
            self._runs.pop(next(iter(self._runs)))

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self._runs.get(run_id)


class FirestoreRunStore:
    """Cloud runs, one document per run in `analyses`."""

    def __init__(self, client: Any, collection: str = "analyses") -> None:
        self.client, self.collection = client, collection

    def save(self, run_id: str, run: dict[str, Any]) -> None:
        self.client.collection(self.collection).document(run_id).set(run)

    def get(self, run_id: str) -> dict[str, Any] | None:
        snapshot = self.client.collection(self.collection).document(run_id).get()
        return snapshot.to_dict() if snapshot.exists else None


def new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


def _frame(chunk: str) -> dict[str, Any] | None:
    line = chunk.strip()
    if not line.startswith("data:"):
        return None
    try:
        return json.loads(line[5:])
    except json.JSONDecodeError:
        return None


async def capture(
    stream: AsyncIterator[str], store: RunStore, run_id: str, event_id: str
) -> AsyncIterator[str]:
    """Pass a stream through; when it finishes with a report, save the run.
    The `done` frame gains the run id, so the UI can ask for its export."""
    verified: list[dict] = []
    run: dict[str, Any] = {"run_id": run_id, "event_id": event_id, "replay": None,
                           "verified": verified, "withheld": [], "header": None,
                           "report": None, "cost_usd": None}
    async for chunk in stream:
        frame = _frame(chunk)
        if frame is None:
            yield chunk
            continue
        kind = frame.get("type")
        if kind == "notice" and frame.get("kind") == "replay":
            run["replay"] = {"message": frame.get("message"), "recorded_at": frame.get("recorded_at")}
        elif kind == "flag" and frame.get("status") == "verified":
            verified.append({"flag": frame["flag"], "badge": frame.get("badge")})
        elif kind == "verification":
            run["header"], run["withheld"] = frame.get("header"), frame.get("withheld", [])
        elif kind == "report":
            run["report"], run["cost_usd"] = frame.get("markdown"), frame.get("cost_usd")
        elif kind == "done":
            if run["report"] is not None:
                run["completed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                try:
                    store.save(run_id, run)
                    frame = {**frame, "run_id": run_id}
                except Exception:  # noqa: BLE001 - a failed save must not break the stream
                    pass
            chunk = f"data: {json.dumps(frame, separators=(',', ':'), default=str)}\n\n"
        yield chunk
