"""CatSight API — API-1..5.

The browser calls this service directly on its `*.run.app` URL with CORS
(C-10). It is deliberately **not** behind a Firebase Hosting rewrite: that
path has a 60-second timeout and does not stream, and an analysis streams for
longer than that.

What is implemented here is the deterministic spine - the catalogue, the
treaties, and an analysis whose numbers come from the loss engine. No model
calls. The agent graph adds explanation and wording flags on top, emitting
more frames between the same SSE bookends, so the frontend contract does not
change when it lands.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.analysis import (
    EventNotFound,
    analyse,
    explain_treaty,
    stream_analysis,
)
from app.config import Settings, settings
from app.replay import has_replay, play, record
from app.report_docx import build_report_docx
from app.scenario import ScenarioRequest, run_scenario
from app.streaming import _run_with_adk
from catsight_agent.courtroom import LABEL, build_courtroom, pick_disputed_flag
from app.logs import hash_ip, log_event, observe, setup_tracing
from app.runs import MemoryRunStore, capture, new_run_id
from app.streaming import stream_agent_analysis
from catsight_agent.agents import AgentDeps, answer_question, ask_targets, cost_usd
from catsight_agent.guardrails import default_guardrail
from catsight_agent.store import BookNotSeeded, DataStore, FirestoreStore, LocalStore

__all__ = ["app", "create_app"]

API_VERSION = "0.5.0-s4-spine"


class AnalysisRequest(BaseModel):
    """API-4's body. FR-GUARD: validated, with the query length bounded."""

    mode: str = Field(default="replay", pattern="^(replay|live)$")
    event_id: str | None = Field(default=None, max_length=64)
    event_query: str | None = Field(default=None, max_length=300)
    #: FR-MATCH: replay defaults to as-if, a historical event on the current
    #: book. `False` applies the treaty period test instead.
    as_if: bool = True
    #: Run the agent graph (wording checker, verifier, reporter). Defaults to
    #: on when GCP is configured with Firestore; `False` gives the instant,
    #: deterministic numbers-only path.
    agents: bool | None = None
    #: Play the recorded real run back instantly instead of running live.
    replay: bool = False


class AskRequest(BaseModel):
    """API-6's body. FR-GUARD: bounded length; the text is data, never
    instructions (see prompts.ASK)."""

    question: str = Field(min_length=3, max_length=300)


class PositionRequest(BaseModel):
    """FR-COURT-5: the analyst's recorded position on the dispute."""

    position: Literal["cedent_reading", "reinsurer_reading", "unresolved"]
    note: str = Field(default="", max_length=500)


class _RateLimiter:
    """FR-GUARD's per-IP hourly limit and the global daily cap.

    In-process and therefore per-instance, which is honest about what it is: a
    cost guard against a popular link, not a security control. Cloud Run runs
    at most 3 instances (C-12), so the effective ceiling is 3x the configured
    limit - stated here rather than discovered from a bill.
    """

    def __init__(self, per_hour: int, daily_cap: int) -> None:
        self.per_hour = per_hour
        self.daily_cap = daily_cap
        self._by_ip: dict[str, deque[float]] = {}
        self._day: deque[float] = deque()

    def check(self, ip: str, *, now: float | None = None) -> tuple[bool, str]:
        now = now if now is not None else time.time()

        while self._day and now - self._day[0] > 86_400:
            self._day.popleft()
        if len(self._day) >= self.daily_cap:
            return False, (
                "The daily analysis cap has been reached. Cached replays are "
                "still available, and the cap resets 24 hours after the first "
                "run of the day."
            )

        seen = self._by_ip.setdefault(ip, deque())
        while seen and now - seen[0] > 3_600:
            seen.popleft()
        if len(seen) >= self.per_hour:
            if not seen:  # a limit of 0 means live runs are switched off
                return False, "Live analyses are switched off here. Open an instant replay instead."
            wait = int((3_600 - (now - seen[0])) // 60) + 1
            return False, (
                f"You have run {self.per_hour} analyses in the last hour. "
                f"Try again in about {wait} minute(s), or open a cached replay."
            )

        seen.append(now)
        self._day.append(now)
        return True, ""


def _refused(message: str, ip: str, endpoint: str) -> None:
    """A guardrail trip: the rate limit or the daily cap turned a request away."""
    kind = "daily_cap" if "daily" in message else "switched_off" if "switched off" in message else "hourly"
    log_event("limit_refused", severity="WARNING", kind=kind, endpoint=endpoint, client=hash_ip(ip))


def _log_courtroom(run_id: str, result: dict[str, Any]) -> None:
    if result.get("skipped"):
        log_event("courtroom_skipped", run_id=run_id, reason=str(result.get("reason"))[:200])
        return
    sides = result.get("sides") or {}
    for name, side in sides.items():
        if not side.get("verified"):
            log_event("counsel_dropped", severity="WARNING", run_id=run_id, side=name,
                      reason=str(side.get("dropped_reason"))[:200])
    flag = result.get("flag") or {}
    log_event("courtroom_done", run_id=run_id, treaty_id=flag.get("treaty_id"),
              sides_verified=sum(1 for s in sides.values() if s.get("verified")),
              money_at_stake=result.get("money_at_stake"),
              unsupported=len(result.get("unsupported_figures") or []), cost_usd=result.get("cost_usd"))


def open_store(config: Settings) -> DataStore:
    """The data source configuration selects. Never the generator."""
    if config.data_backend == "firestore":  # pragma: no cover - needs a live project
        from google.cloud import firestore

        return FirestoreStore(
            firestore.Client(project=config.project, database=config.firestore_database)
        )
    return LocalStore(config.data_dir)


#: The standard retrieval queries, embedded once (`ingest/build_query_embeddings.py`).
QUERY_EMBEDDINGS = "query_embeddings.jsonl"

#: Seconds of silence before the stream sends an SSE comment. Keeps proxies
#: and networks from dropping a connection while a slow stage works.
HEARTBEAT_SECONDS = 15.0


async def with_heartbeat(stream: Any, every: float = HEARTBEAT_SECONDS):
    """Pass the stream through, adding `: keepalive` comment lines whenever it
    is silent for `every` seconds. Browsers and the frontend parser ignore
    comment lines. The pending read is never cancelled - cancelling it would
    abort the generator underneath."""
    iterator = stream.__aiter__()
    pending: asyncio.Future | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=every)
            if not done:
                yield ": keepalive\n\n"
                continue
            try:
                chunk = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            yield chunk
    finally:
        if pending is not None and not pending.done():
            pending.cancel()


def _sse_response(stream: Any) -> StreamingResponse:
    return StreamingResponse(
        with_heartbeat(stream),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Cloud Run buffers responses without this, which turns a stream
            # into one block at the end and defeats the point.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _client_ip(request: Request) -> str:
    """Right-most hop of X-Forwarded-For (appended by Google's front end on
    Cloud Run, which the client cannot spoof), falling back to client.host."""
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [part.strip() for part in forwarded.split(",") if part.strip()]
    if hops:
        return hops[-1]
    return request.client.host if request.client else "unknown"


def create_app(config: Settings | None = None, store: DataStore | None = None) -> FastAPI:
    from contextlib import asynccontextmanager
    import threading

    config = config if config is not None else settings

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI):
        """Read the book once at start-up, in the background, so the first
        analysis does not wait on ~600 Firestore reads."""
        def load() -> None:
            try:
                app_instance.state.store.portfolio()
            except Exception:  # noqa: BLE001 - surfaced on first request instead
                pass

        threading.Thread(target=load, daemon=True).start()
        yield

    hide_docs = config.data_backend == "firestore"
    api = FastAPI(
        title="CatSight API",
        version=API_VERSION,
        description=(
            "Treaty-level catastrophe impact with a machine-verified citation "
            "for every wording claim."
        ),
        lifespan=lifespan,
        docs_url=None if hide_docs else "/docs",
        redoc_url=None,
        openapi_url=None if hide_docs else "/openapi.json",
    )

    api.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    setup_tracing(config.enable_cloud_trace)
    limiter = _RateLimiter(config.rate_limit_per_hour, config.daily_analysis_cap)
    api.state.config = config
    api.state.limiter = limiter
    # The book, events and method are read from the seeded store - local JSON
    # or Firestore - and cached by the store. The runtime never generates data.
    api.state.store = store if store is not None else open_store(config)

    def portfolio():
        try:
            return api.state.store.portfolio()
        except BookNotSeeded as exc:
            raise HTTPException(status_code=503, detail=str(exc))

    api.state.agent_resources = None

    def agents_available() -> bool:
        return config.configured and config.data_backend == "firestore"

    def make_deps(emit):  # pragma: no cover - builds live GCP clients
        """Shared clients (built once), a fresh AgentDeps per request."""
        if api.state.agent_resources is None:
            from google.cloud import firestore

            from catsight_agent.tools.retrieval import FirestoreVectorStore, GeminiEmbedder
            from ingest.ingest_treaty import build_client

            api.state.agent_resources = {
                "client": build_client(config.project, config.location),
                "embedder": GeminiEmbedder(
                    project=config.project, location=config.location,
                    model=config.embed_model,
                    cache_path=os.environ.get("EMBED_CACHE") or None,
                    seed_path=str(Path(config.data_dir) / QUERY_EMBEDDINGS),
                ),
                "vectors": FirestoreVectorStore(firestore.Client(
                    project=config.project, database=config.firestore_database)),
            }
        shared = api.state.agent_resources
        return AgentDeps(client=shared["client"], model_main=config.model_main,
                         model_reason=config.model_reason, embedder=shared["embedder"],
                         vectors=shared["vectors"], emit=emit)

    api.state.make_deps = make_deps
    # How an ADK graph is executed; tests run the same graphs through ADK too.
    api.state.run_graph = _run_with_adk
    api.state.clauses = None
    # Completed runs, for export: Firestore in the cloud (any instance can
    # serve the download), memory locally.
    api.state.runs = None

    def run_store():
        if api.state.runs is None:
            if agents_available():  # pragma: no cover - live Firestore
                from google.cloud import firestore

                from app.runs import FirestoreRunStore

                api.state.runs = FirestoreRunStore(firestore.Client(
                    project=config.project, database=config.firestore_database))
            else:
                api.state.runs = MemoryRunStore()
        return api.state.runs

    def clause_store():
        """The stored clause corpus (Firestore `treaty_chunks`)."""
        if api.state.clauses is None:
            if not agents_available():
                raise HTTPException(
                    status_code=503,
                    detail="Clause text lives in Firestore; set DATA_BACKEND=firestore.",
                )
            from google.cloud import firestore  # pragma: no cover - live only

            from catsight_agent.tools.retrieval import FirestoreVectorStore  # pragma: no cover

            api.state.clauses = FirestoreVectorStore(firestore.Client(  # pragma: no cover
                project=config.project, database=config.firestore_database))
        return api.state.clauses

    @api.get("/api/treaties/{treaty_id}/clauses")
    def treaty_clauses(treaty_id: str) -> dict[str, Any]:
        """Every stored clause of one treaty - what the clause viewer shows
        when a citation is opened, and what the verifier checked against."""
        chunks = clause_store().chunks_for(treaty_id)
        if not chunks:
            raise HTTPException(status_code=404, detail=f"no stored clauses for {treaty_id}")
        return {"treaty_id": treaty_id, "clauses": [
            {"chunk_id": c.chunk_id, "clause_no": c.clause_no, "title": c.clause_title,
             "page": c.page, "pages": list(c.pages_spanned or (c.page,)),
             "source": c.source, "text": c.text}
            for c in chunks
        ]}

    # ----------------------------------------------------------------- API-1 #

    # `/health` is the one to call on Cloud Run: Google's front end reserves
    # paths ending in "z" on *.run.app, so `/healthz` 404s before reaching us.
    @api.get("/healthz")
    @api.get("/health")
    def healthz() -> dict[str, Any]:
        """Liveness plus enough configuration to diagnose a bad deploy.

        Answers even when the project is unset: "up but unconfigured" is a
        far more useful signal than a service that refuses to boot.
        """
        return {
            "status": "ok",
            "version": API_VERSION,
            "build": config.build_label,
            "configured": config.configured,
            "models": {
                "main": config.model_main,
                "reason": config.model_reason,
                "embed": config.embed_model,
                "embed_dim": config.embed_dim,
            },
            "location": config.location,
            "features": {
                "courtroom": config.courtroom_enabled,
                "cached_replay_only": config.cached_replay_only,
            },
            "warnings": list(config.warnings),
            "frontend": api.state.static_dir is not None,
        }

    # ----------------------------------------------------------------- API-2 #

    @api.get("/api/events")
    def events() -> dict[str, Any]:
        return {"events": [
            {**e, "replay_available": has_replay(config.replay_fixture_dir, e["event_id"])}
            for e in api.state.store.events()
        ]}

    @api.get("/api/events/{event_id}/regions")
    def event_regions(event_id: str) -> dict[str, Any]:
        """UI-3: each region's sampled intensity and band for the map."""
        try:
            event = api.state.store.event(event_id)
        except EventNotFound:
            raise HTTPException(status_code=404, detail=f"no event {event_id}")
        key, unit = ("wind_ms", "m/s") if event["peril"] == "WS" else ("mmi", "MMI")
        return {
            "event_id": event_id, "peril": event["peril"], "unit": unit,
            "regions": [
                {"code": r["code"], "name": r.get("name"), "country": r.get("country"),
                 "intensity": (r.get("intensity") or {}).get(key), "band": r.get("band")}
                for r in event.get("regions", [])
            ],
        }

    @api.get("/api/regions/{code}/exposure")
    def region_exposure(code: str, peril: str | None = None) -> dict[str, Any]:
        """UI-3: insured value (TSI) in one region, by cedent, from the book."""
        book = portfolio()
        rows: dict[str, float] = {}
        for exposure in book.exposures:
            if exposure.region_code == code and (peril is None or exposure.peril == peril):
                rows[exposure.cedent_id] = rows.get(exposure.cedent_id, 0.0) + exposure.tsi_usd
        return {
            "code": code, "peril": peril,
            "cedents": [
                {"cedent_id": cid, "cedent": book.cedent(cid).name, "tsi_usd_m": round(tsi, 2)}
                for cid, tsi in sorted(rows.items(), key=lambda kv: -kv[1])
            ],
        }

    @api.get("/api/knowledge-base")
    def knowledge_base() -> dict[str, Any]:
        """Evidence that the clause corpus was built: one ingestion record per
        wording, recorded at ingest time, plus corpus totals."""
        rows = api.state.store.ingestions()
        return {
            "wordings": rows,
            "totals": {
                "wordings": len(rows),
                "clauses": sum(r.get("clauses", 0) for r in rows),
                "citations_verified": sum(r.get("citations_verified", 0) for r in rows),
                "citations_total": sum(r.get("citations_total", 0) for r in rows),
                "retrieval_hits": sum(r.get("retrieval_hits", 0) for r in rows),
                "retrieval_total": sum(r.get("retrieval_total", 0) for r in rows),
            },
        }

    @api.get("/api/benchmark")
    def benchmark(event_id: str | None = None) -> dict[str, Any]:
        """Reference data for the Business impact panel: the simulated manual
        baseline, model prices, and - where published - what the market saw
        for this event. CatSight's own figures come from each run."""
        data = dict(api.state.store.benchmark())
        real = data.pop("real_world", {}) or {}
        data["real_world"] = real.get(event_id) if event_id else None
        manual = dict(data.get("manual_baseline") or {})
        if manual.get("total_hours") and manual.get("loaded_rate_usd_per_hour"):
            rate = manual["loaded_rate_usd_per_hour"]
            manual["manual_cost_usd"] = [h * rate for h in manual["total_hours"]]
            manual["catsight_review_cost_usd"] = [
                h * rate for h in manual.get("catsight_review_hours", [])
            ]
            data["manual_baseline"] = manual
        return data

    @api.get("/api/analyses/{analysis_id}/treaties/{treaty_id}")
    def treaty_explanation(analysis_id: str, treaty_id: str) -> dict[str, Any]:
        """"How was this calculated?" for one treaty in one analysis: the
        event data, why the treaty responded, the damage by region, and each
        layer's figures with the formula and the contract citation."""
        prefix = "replay-"
        if not analysis_id.startswith(prefix):
            raise HTTPException(status_code=404, detail="analyses are addressed as replay-{event_id}")
        portfolio()
        try:
            return explain_treaty(analysis_id[len(prefix):], treaty_id, store=api.state.store)
        except EventNotFound:
            raise HTTPException(status_code=404, detail=f"no event {analysis_id[len(prefix):]}")
        except KeyError:
            raise HTTPException(status_code=404, detail=f"no treaty {treaty_id}")

    @api.get("/api/methodology")
    def methodology() -> dict[str, Any]:
        """The method version in force, with its conventions and sources."""
        method = dict(api.state.store.methodology())
        method.pop("_comment", None)
        return method

    # ----------------------------------------------------------------- API-3 #

    @api.get("/api/treaties")
    def treaties() -> dict[str, Any]:
        book = portfolio()
        names = {c.cedent_id: c.name for c in book.cedents}
        return {
            "treaties": [
                {
                    "treaty_id": t.treaty_id,
                    "cedent_id": t.cedent_id,
                    "cedent": names.get(t.cedent_id, t.cedent_id),
                    "type": t.type,
                    "perils": list(t.perils),
                    "territory": {
                        "include": list(t.territory.get("include", ())),
                        "exclude": list(t.territory.get("exclude", ())),
                    },
                    "inception": t.inception,
                    "expiry": t.expiry,
                    "currency": t.currency,
                    "hours_clause": dict(t.hours_clause),
                    "layers": len(t.layers),
                    "has_wording": bool(t.wording_id),
                    "wording_id": t.wording_id,
                }
                for t in book.treaties
            ]
        }

    @api.get("/api/treaties/{treaty_id}")
    def treaty_detail(treaty_id: str) -> dict[str, Any]:
        book = portfolio()
        try:
            found = book.treaty(treaty_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"no treaty {treaty_id}")
        return {
            "treaty_id": found.treaty_id,
            "cedent": book.cedent(found.cedent_id).name,
            "type": found.type,
            "perils": list(found.perils),
            "territory": {
                "include": list(found.territory.get("include", ())),
                "exclude": list(found.territory.get("exclude", ())),
            },
            "inception": found.inception,
            "expiry": found.expiry,
            "currency": found.currency,
            "hours_clause": dict(found.hours_clause),
            "exclusions": list(found.exclusions),
            "layers": [
                {
                    "layer_no": layer.layer_no,
                    "retention": layer.retention,
                    "limit": layer.limit,
                    "premium": layer.premium,
                    "our_share": layer.our_share,
                    "reinstatements": dict(layer.reinstatements),
                }
                for layer in found.layers
            ],
            "qs": dict(found.qs) if found.qs else None,
            "wording_id": found.wording_id,
            "endorsement": found.endorsement,
            "extraction": found.extraction,
            # Booked terms vs what the wording states, field by field, each
            # wording value with its verified citation. None until reconciled.
            "reconciliation": api.state.store.reconciliation(found.treaty_id),
        }

    # ----------------------------------------------------------------- API-4 #

    @api.post("/api/analyses")
    def create_analysis(body: AnalysisRequest, request: Request) -> StreamingResponse:
        """SSE stream. The client uses `fetch()` with a ReadableStream, not
        `EventSource`, because EventSource cannot POST."""
        if body.event_query and len(body.event_query) > config.max_query_chars:
            raise HTTPException(
                status_code=422,
                detail=f"event_query exceeds {config.max_query_chars} characters.",
            )
        if body.mode == "live":
            raise HTTPException(
                status_code=501,
                detail=(
                    "Live web-feed ingestion is outside v1 scope. Pick a replay event "
                    "from GET /api/events."
                ),
            )
        event_id = body.event_id or "jebi-2018"
        replays = config.replay_fixture_dir
        cached = has_replay(replays, event_id)

        # FR-JUDGE-2: a recorded real run, played back instantly and labelled.
        if body.replay or config.cached_replay_only:
            if not cached:
                raise HTTPException(
                    status_code=404,
                    detail=f"No recorded replay for {event_id} yet. Run it live once to record one.",
                )
            reason = "requested" if body.replay else "cached_only"
            run_id = new_run_id()
            return _sse_response(observe(capture(play(replays, event_id, reason=reason),
                                                 run_store(), run_id, event_id),
                                         run_id=run_id, event_id=event_id, mode="replay"))

        client_ip = _client_ip(request)
        allowed, message = api.state.limiter.check(client_ip)
        if not allowed:
            _refused(message, client_ip, "analysis")
            # FR-GUARD-5: never a bare error. With a recording available, the
            # cap-hit path serves it, labelled; without one, explain what to do.
            if cached:
                run_id = new_run_id()
                return _sse_response(observe(capture(play(replays, event_id, reason="cap"),
                                                     run_store(), run_id, event_id),
                                             run_id=run_id, event_id=event_id, mode="cap_replay"))
            raise HTTPException(
                status_code=429,
                detail={"message": message, "cached_available": False},
            )

        use_agents = agents_available() if body.agents is None else body.agents
        if use_agents and not agents_available():
            raise HTTPException(
                status_code=400,
                detail="Agent analysis needs GOOGLE_CLOUD_PROJECT and DATA_BACKEND=firestore.",
            )
        portfolio()  # a clear 503 now if the book is not seeded
        run_id = new_run_id()
        if use_agents:
            # Every complete live run refreshes the event's replay recording,
            # and is kept as a run so it can be exported.
            stream = capture(
                record(
                    stream_agent_analysis(
                        event_id, store=api.state.store, make_deps=api.state.make_deps,
                        as_if=body.as_if, max_retries=config.verifier_max_retries,
                    ),
                    replays, event_id,
                ),
                run_store(), run_id, event_id,
            )
        else:
            stream = stream_analysis(
                event_id, portfolio=portfolio(), as_if=body.as_if, store=api.state.store,
            )
        return _sse_response(observe(stream, run_id=run_id, event_id=event_id,
                                     mode="live" if use_agents else "numbers"))

    # -------------------------------------------------------------- FR-WHATIF #

    @api.post("/api/analyses/{analysis_id}/scenario")
    def scenario(analysis_id: str, body: ScenarioRequest) -> dict[str, Any]:
        """A bounded what-if, priced by the engine: the base reading (one
        occurrence) against the scenario, with money at stake per party.
        Deterministic - no model call - so it is not rate-limited."""
        prefix = "replay-"
        if not analysis_id.startswith(prefix):
            raise HTTPException(status_code=404, detail="analyses are addressed as replay-{event_id}")
        portfolio()
        try:
            return run_scenario(analysis_id[len(prefix):], body, store=api.state.store)
        except EventNotFound:
            raise HTTPException(status_code=404, detail=f"no event {analysis_id[len(prefix):]}")
        except KeyError:
            raise HTTPException(status_code=404, detail=f"no treaty {body.treaty_id}")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    # --------------------------------------------------------------- FR-COURT #

    def _price_exclusion(event_id: str):
        def price(treaty_id: str, share: float, cause: str) -> dict[str, Any]:
            return run_scenario(event_id, ScenarioRequest(
                treaty_id=treaty_id, mode="exclusion", excluded_share=share, excluded_cause=cause),
                store=api.state.store)
        return price

    @api.post("/api/runs/{run_id}/courtroom")
    async def courtroom(run_id: str, request: Request, rerun: bool = False) -> dict[str, Any]:
        """FR-COURT on a completed run: picks the disputed flag, runs the two
        counsel in parallel and the arbiter, prices both readings. Saved on
        the run, so re-opening it does not pay for the agents again."""
        if not config.courtroom_enabled:
            return {"skipped": True, "reason": "The Clause Courtroom is switched off on this instance.",
                    "label": LABEL}
        if not agents_available():
            raise HTTPException(status_code=400,
                                detail="The Courtroom needs GOOGLE_CLOUD_PROJECT and DATA_BACKEND=firestore.")
        store = run_store()
        run = await asyncio.to_thread(store.get, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"no completed run {run_id}")
        if run.get("courtroom") and not rerun:
            return run["courtroom"]
        client_ip = _client_ip(request)
        allowed, message = api.state.limiter.check(client_ip)
        if not allowed:
            _refused(message, client_ip, "courtroom")
            raise HTTPException(status_code=429, detail={"message": message})

        event = await asyncio.to_thread(api.state.store.event, run["event_id"])
        price = _price_exclusion(run["event_id"])
        flag, skipped = pick_disputed_flag(run.get("verified", []),
                                           lambda tid: price(tid, 0.5, "the excluded cause"))
        if flag is None:
            result: dict[str, Any] = {"skipped": True, "reason": skipped, "label": LABEL}
        else:
            deps = api.state.make_deps(lambda frame: None)
            deps.observed = [
                f"Event window: {event.get('start')} to {event.get('end')} (duration {event.get('duration_h')} hours).",
                *[f["text"] for f in event.get("facts", [])],
            ]
            graph, out = build_courtroom(event_id=run["event_id"], flag=flag, deps=deps, price=price)
            await api.state.run_graph(graph)
            out.pop("context", None)
            pricing = (api.state.store.benchmark() or {}).get("pricing", {})
            result = {"skipped": False, **out, "calls": dict(deps.calls),
                      "cost_usd": cost_usd(deps.usage, pricing)}
        _log_courtroom(run_id, result)
        run["courtroom"] = result
        await asyncio.to_thread(store.save, run_id, run)
        return result

    @api.post("/api/runs/{run_id}/courtroom/position")
    def courtroom_position(run_id: str, body: PositionRequest) -> dict[str, Any]:
        """FR-COURT-5: the human decides. Timestamped for the audit trail."""
        store = run_store()
        run = store.get(run_id)
        if run is None or not run.get("courtroom") or run["courtroom"].get("skipped"):
            raise HTTPException(status_code=404, detail="no Courtroom to record a position on")
        from datetime import datetime, timezone

        run["courtroom"]["position"] = {
            "position": body.position, "note": body.note,
            "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        store.save(run_id, run)
        return run["courtroom"]["position"]

    # ------------------------------------------------------------- FR-EXPORT #

    @api.get("/api/runs/{run_id}/report.docx")
    def report_docx(run_id: str) -> Response:
        """The analyst report as Word: the stored run's flags and text, with
        the engine's figures recomputed (deterministic, so identical)."""
        run = run_store().get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"no completed run {run_id}")
        impact = analyse(run["event_id"], store=api.state.store).to_json()
        body = build_report_docx(run, impact)
        name = f"catsight-{run['event_id']}-{run_id}.docx"
        return Response(
            content=body,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    # ----------------------------------------------------------------- API-6 #

    @api.post("/api/analyses/{analysis_id}/ask")
    def ask(analysis_id: str, body: AskRequest, request: Request) -> dict[str, Any]:
        """FR-ASK: a follow-up question, answered from the engine's figures
        and live clause retrieval, with checked citations. Stateless: the
        replay analysis is recomputed (deterministic, so identical)."""
        if len(body.question) > config.max_query_chars:
            raise HTTPException(
                status_code=422,
                detail=f"question exceeds {config.max_query_chars} characters.",
            )
        screen = default_guardrail.screen_prompt(body.question, context="ask")
        if not screen.allowed:
            log_event("guardrail_blocked", where="ask", reason=screen.reason, filter=screen.filter_type)
            raise HTTPException(status_code=400, detail=screen.reason)
        prefix = "replay-"
        if not analysis_id.startswith(prefix):
            raise HTTPException(status_code=404, detail="analyses are addressed as replay-{event_id}")
        if not agents_available():
            raise HTTPException(status_code=400,
                                detail="Questions need GOOGLE_CLOUD_PROJECT and DATA_BACKEND=firestore.")
        client_ip = _client_ip(request)
        allowed, message = api.state.limiter.check(client_ip)
        if not allowed:
            _refused(message, client_ip, "ask")
            raise HTTPException(status_code=429, detail={"message": message})

        book = portfolio()
        try:
            result = analyse(analysis_id[len(prefix):], store=api.state.store)
        except EventNotFound:
            raise HTTPException(status_code=404, detail=f"no event {analysis_id[len(prefix):]}")
        impact = result.to_json()
        for row in impact["treaties"]:
            row.pop("regions", None)  # long code lists add tokens, not answers
        wording_of = {t.treaty_id: t.wording_id for t in book.treaties if t.wording_id}
        deps = api.state.make_deps(lambda frame: None)
        answer = answer_question(
            body.question, facts=impact,
            targets=ask_targets(body.question, impact, wording_of), deps=deps,
        )
        pricing = (api.state.store.benchmark() or {}).get("pricing", {})
        spent = cost_usd(deps.usage, pricing)
        # The question text is not logged - only what happened to the answer.
        log_event("ask_answered", analysis_id=analysis_id,
                  citations=len(answer.get("citations") or []),
                  withheld=len(answer.get("withheld") or []),
                  unsupported=len(answer.get("unsupported_figures") or []), cost_usd=spent)
        if answer.get("unsupported_figures"):
            log_event("unsupported_figures", severity="WARNING", where="ask",
                      analysis_id=analysis_id, count=len(answer["unsupported_figures"]))
        resp_screen = default_guardrail.screen_response(answer.get("answer_md", ""), context="ask")
        if not resp_screen.allowed:
            log_event("guardrail_blocked", where="ask_response", reason=resp_screen.reason)
            answer["answer_md"] = "Response withheld by security guardrails."
        return {"analysis_id": analysis_id, "question": body.question, **answer, "cost_usd": spent}

    # ----------------------------------------------------------------- API-5 #

    @api.get("/api/analyses/{analysis_id}")
    def get_analysis(analysis_id: str) -> dict[str, Any]:
        """The full analysis document.

        A replay analysis is addressable as `replay-{event_id}` and is
        **recomputed rather than stored**: the deterministic pipeline returns
        the same figures every time, so persistence would add a cache to
        invalidate for no gain. That stops being true once the agents add
        prose and an analyst can record a Courtroom position, which is when
        this reads from Firestore instead.
        """
        prefix = "replay-"
        if not analysis_id.startswith(prefix):
            raise HTTPException(
                status_code=404,
                detail="only replay analyses exist so far, as replay-{event_id}",
            )
        event_id = analysis_id[len(prefix) :]
        try:
            result = analyse(event_id, portfolio=portfolio(), store=api.state.store)
        except EventNotFound:
            raise HTTPException(status_code=404, detail=f"no event {event_id}")
        return {"analysis_id": analysis_id, **result.to_json()}

    _mount_frontend(api)
    return api


#: Where the built frontend might be. The container copies it to /app/static;
#: a developer running uvicorn from `backend/` has it one level up.
_STATIC_CANDIDATES = ("static", "../frontend/dist")


def _mount_frontend(api: FastAPI) -> None:
    """Serve the built SPA from this same service, if it is present.

    One service rather than two, which is a deliberate simplification over
    Firebase Hosting: the frontend and the API share an origin, so CORS stops
    being a thing that can be configured wrongly - and a silent CORS failure,
    with nothing in the server logs, is a classic way to lose a demo.

    This does **not** reintroduce what C-10 forbids. C-10 rules out a Hosting
    *rewrite* to the API, because that path imposes a 60-second timeout and
    will not stream SSE. Here the API is not behind a proxy at all; it is the
    same process, and the routes above were registered first.

    Unknown paths serve `index.html` rather than 404, matching the rewrite in
    `firebase.json` so behaviour does not depend on where this is hosted.
    `StaticFiles(html=True)` alone does not do that - it falls back only for
    directory paths, so refreshing on a client-side route would 404.

    If no build is present the API still serves normally, which is what the
    tests and a bare `uvicorn app.main:app` do.
    """
    configured = os.environ.get("STATIC_DIR")
    candidates = (configured,) if configured else _STATIC_CANDIDATES

    directory: Path | None = None
    for candidate in candidates:
        if candidate and (Path(candidate) / "index.html").is_file():
            directory = Path(candidate)
            break

    if directory is None:
        api.state.static_dir = None
        return

    index = directory / "index.html"
    api.state.static_dir = str(directory.resolve())

    assets = directory / "assets"
    if assets.is_dir():
        api.mount("/assets", StaticFiles(directory=assets), name="assets")

    @api.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        # A real file at that path wins; anything else is a client-side route.
        # `resolve()` and the prefix check stop `../` escaping the build
        # directory - without it this would serve any file on the container.
        if path:
            candidate = (directory / path).resolve()
            root = directory.resolve()
            if candidate.is_file() and str(candidate).startswith(str(root)):
                return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
