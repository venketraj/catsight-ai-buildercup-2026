"""ADK workflow -> SSE (REQUIREMENTS 3.1, API-4).

The graph runs as a background task; its nodes emit frames into a queue from
worker threads, and this generator yields them to the client the moment they
arrive. So the browser shows each retrieval and each verification while the
analysis is still running, not a block at the end.

The stream always ends with `done`, after an `error` frame if something
failed: a half-finished SSE stream looks like a hung page.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Callable

from catsight_agent.agent import AnalysisContext, build_workflow
from catsight_agent.agents import AgentDeps
from catsight_agent.store import DataStore, EventNotFound

__all__ = ["sse", "stream_agent_analysis"]

_END = object()


def sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'), default=str)}\n\n"


async def stream_agent_analysis(
    event_id: str,
    *,
    store: DataStore,
    make_deps: Callable[[Callable[[dict], None]], AgentDeps],
    as_if: bool = True,
    max_retries: int = 1,
    run_graph: Callable[[Any], Any] | None = None,
) -> AsyncIterator[str]:
    """Run the agent graph for one replay event and stream its frames."""
    # An unknown event is the caller's mistake, not a transient failure: say
    # so before spending a model call, and do not invite a retry.
    try:
        await asyncio.to_thread(store.event, event_id)
    except EventNotFound:
        yield sse({"type": "error", "message": f"No replay fixture for {event_id!r}.",
                   "retryable": False})
        yield sse({"type": "done", "analysis_id": f"replay-{event_id}", "agents": True})
        return

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(frame: dict) -> None:  # called from worker threads
        loop.call_soon_threadsafe(queue.put_nowait, frame)

    deps = make_deps(emit)
    ctx = AnalysisContext(event_id=event_id, store=store, deps=deps, as_if=as_if,
                          max_retries=max_retries)
    runner = run_graph or _run_with_adk

    async def drive() -> None:
        try:
            await runner(build_workflow(ctx))
        except Exception as exc:  # noqa: BLE001 - reported to the client, then done
            emit({"type": "error", "message": f"{type(exc).__name__}: {exc}",
                  "retryable": True})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _END)

    task = asyncio.create_task(drive())
    try:
        while True:
            frame = await queue.get()
            if frame is _END:
                break
            yield sse(frame)
        yield sse({"type": "done", "analysis_id": f"replay-{event_id}", "agents": True})
    finally:
        if not task.done():  # client went away mid-stream
            task.cancel()


async def _run_with_adk(workflow: Any) -> None:  # pragma: no cover - exercised live
    """Run a Workflow through ADK's Runner with an in-memory session. Node
    errors surface as exceptions so the stream can report them."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    runner = Runner(app_name="catsight", node=workflow,
                    session_service=InMemorySessionService(), auto_create_session=True)
    message = types.Content(role="user", parts=[types.Part(text="analyse")])
    async for event in runner.run_async(user_id="api", session_id="analysis",
                                        new_message=message):
        error = getattr(event, "error_message", None)
        if error:
            raise RuntimeError(error)
