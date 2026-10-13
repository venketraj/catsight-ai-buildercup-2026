"""The analysis pipeline as an ADK 2.x graph `Workflow` (REQUIREMENTS 3.1).

    START -> event_intel -> exposure_analyst -> wording_checker -> verifier -> reporter

  event_intel       AG-1. Replay mode: loads the event record. No model call.
  exposure_analyst  AG-2. Treaty matching and the loss engine - deterministic
                    tools; no model touches a number (C-6).
  wording_checker   AG-3. Per matched treaty with a wording, in parallel:
                    Firestore vector retrieval, then Gemini reads only the
                    retrieved clauses and raises cited flags.
  verifier          AG-5. Quote-in-clause check (code), then "does it support
                    the claim" on MODEL_REASON; one revision; else withheld.
  reporter          AG-4. Markdown report from verified facts; every figure
                    in it is checked against those facts.

Each node emits SSE frames through `deps.emit` as it works, so the UI shows
retrieval hits and verification results while the graph is still running.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from catsight_agent.agents import (
    AgentDeps,
    GeminiReviser,
    GeminiSemanticChecker,
    check_treaty_wording,
    cost_usd,
    write_report,
)
from catsight_agent.store import DataStore
from catsight_agent.tools.verify import _flag_id, verify_flags

__all__ = ["AnalysisContext", "build_workflow", "booked_terms"]

DISCLAIMER = (
    "Indicative first view on synthetic data. Not a catastrophe-model output and "
    "not advice; figures are deterministic estimates and wording flags are "
    "machine-verified citations for an analyst to review."
)


@dataclass
class AnalysisContext:
    event_id: str
    store: DataStore
    deps: AgentDeps
    as_if: bool = True
    max_retries: int = 1


def booked_terms(treaty: Any) -> dict[str, Any]:
    """The book's terms for one treaty, as the wording checker sees them."""
    return {
        "type": treaty.type,
        "perils": list(treaty.perils),
        "territory": {k: list(v) for k, v in treaty.territory.items()},
        "inception": treaty.inception,
        "expiry": treaty.expiry,
        "hours_clause": dict(treaty.hours_clause),
        "exclusions": list(treaty.exclusions),
        "layers": [
            {"layer_no": la.layer_no, "retention": la.retention, "limit": la.limit,
             "reinstatements": dict(la.reinstatements)}
            for la in treaty.layers
        ],
        "qs": dict(treaty.qs) if treaty.qs else None,
    }


def _pct(value: str) -> str:
    """Burn as a percentage string, computed here in Python so the reporter
    can quote it rather than derive it."""
    return f"{(Decimal(value) * 100).quantize(Decimal('0.1'))}%"


def build_workflow(ctx: AnalysisContext) -> Any:
    """A fresh graph bound to one analysis request."""
    from google.adk.workflow import START, Workflow, node

    deps = ctx.deps
    emit = deps.emit

    def stage(agent: str, status: str) -> None:
        emit({"type": "stage", "agent": agent, "status": status})

    @node(name="event_intel")
    async def event_intel(node_input: Any = None) -> dict:
        stage("event_intel", "started")
        event = await asyncio.to_thread(ctx.store.event, ctx.event_id)
        emit({"type": "result", "key": "event", "data": {
            "event_id": event["event_id"], "name": event["name"], "peril": event["peril"],
            "duration_h": event.get("duration_h"), "regions": len(event.get("regions", [])),
            "facts": event.get("facts", []),
        }})
        stage("event_intel", "completed")
        return {"event_id": event["event_id"]}

    @node(name="exposure_analyst")
    async def exposure_analyst(node_input: dict) -> dict:
        from app.analysis import analyse

        stage("exposure_analyst", "started")
        result = await asyncio.to_thread(
            analyse, ctx.event_id, store=ctx.store, as_if=ctx.as_if
        )
        emit({"type": "tool", "agent": "exposure_analyst", "name": "match_treaties",
              "summary": f"{result.matched} matched, {result.excluded} excluded"})
        emit({"type": "tool", "agent": "exposure_analyst", "name": "loss_engine",
              "summary": f"{len(result.outcomes)} treaties priced, deterministic"})
        impact = result.to_json()
        emit({"type": "result", "key": "impact", "data": impact})
        stage("exposure_analyst", "completed")
        return {"impact": impact}

    @node(name="wording_checker")
    async def wording_checker(node_input: dict) -> dict:
        stage("wording_checker", "started")
        impact = node_input["impact"]
        book = ctx.store.portfolio()
        event = impact["event"]
        # The event's observed facts (surge, gusts, landfalls) are what make a
        # clause bite: a storm-surge exclusion only matters if there was surge.
        brief = {"name": event["name"], "peril": event["peril"], "start": event["start"],
                 "end": event["end"], "duration_h": event["duration_h"],
                 "regions_hit": event["regions"],
                 "observed": [f["text"] for f in event.get("facts", [])]}
        # Include the event window and duration so the verifier can check HOURS flags.
        deps.observed = [
            f"Event window: {event.get('start')} to {event.get('end')} (duration {event.get('duration_h')} hours).",
            *brief["observed"],
        ]
        targets = [t for t in impact["treaties"] if book.treaty(t["treaty_id"]).wording_id]
        emit({"type": "tool", "agent": "wording_checker", "name": "search_treaty_clauses",
              "summary": f"{len(targets)} matched treaties have wordings"})

        async def one(row: dict) -> list:
            return await asyncio.to_thread(
                check_treaty_wording, row["treaty_id"], event=brief,
                booked=booked_terms(book.treaty(row["treaty_id"])),
                engine={k: row[k] for k in ("gross", "ceded", "our_net", "layers") if k in row},
                deps=deps, as_if=ctx.as_if,
            )

        flags = [f for batch in await asyncio.gather(*(one(t) for t in targets)) for f in batch]
        for flag in flags:
            emit({"type": "flag", "status": "candidate", "flag": flag.model_dump(mode="json")})
        stage("wording_checker", "completed")
        return {"impact": impact, "flags": [f.model_dump(mode="json") for f in flags]}

    @node(name="verifier")
    async def verifier(node_input: dict) -> dict:
        from catsight_agent.schemas import WordingFlag

        stage("verifier", "started")
        flags = [WordingFlag.model_validate(f) for f in node_input["flags"]]
        outcome = await asyncio.to_thread(
            verify_flags, flags, deps.vectors, checker=GeminiSemanticChecker(deps),
            reviser=GeminiReviser(deps), max_retries=ctx.max_retries,
        )
        for flag in outcome.verified:
            emit({"type": "flag", "status": "verified", "badge": outcome.badge(flag),
                  "flag": flag.model_dump(mode="json")})
        withheld = [
            {"treaty_id": f.treaty_id, "issue_type": f.issue_type,
             "reason": outcome.results[_flag_id(f)].reason
             if _flag_id(f) in outcome.results else None}
            for f in outcome.withheld
        ]
        emit({"type": "verification", "header": outcome.header(),
              "verified": outcome.verified_count, "withheld": withheld})
        stage("verifier", "completed")
        return {
            "impact": node_input["impact"],
            "verified": [f.model_dump(mode="json") for f in outcome.verified],
            "withheld": withheld,
            "header": outcome.header(),
        }

    @node(name="reporter")
    async def reporter(node_input: dict) -> dict:
        stage("reporter", "started")
        impact = node_input["impact"]
        facts = {
            "event": impact["event"]["name"],
            "event_dates": [
                str(d).replace("T", " ").replace("Z", " UTC")
                for d in (impact["event"]["start"], impact["event"]["end"])
            ],
            "totals_usd_m": impact["totals"],
            "as_if_on_current_book": impact["as_if"],
            "methodology_version": impact["methodology"]["version"],
            "treaties": [
                {"treaty_id": t["treaty_id"], "cedent": t["cedent"], "type": t["type"],
                 "gross": t["gross"], "ceded": t["ceded"], "our_net": t["our_net"],
                 "layers": [{"layer_no": la["layer_no"], "burn": _pct(la["burn"]),
                             "exhausted": la["exhausted"], "ceded": la["ceded"]}
                            for la in t.get("layers", [])]}
                for t in impact["treaties"][:6]
            ],
            "verified_flags": [
                {"treaty_id": f["treaty_id"], "issue": f["issue_type"],
                 "severity": f["severity"], "explanation": f["explanation"],
                 "page": f["citation"]["page"], "clause": f["citation"]["clause_no"]}
                for f in node_input["verified"]
            ],
            "verification": node_input["header"],
            "withheld_flags": len(node_input["withheld"]),
            "disclaimer": DISCLAIMER,
        }
        report, unsupported = await asyncio.to_thread(write_report, facts, deps)
        pricing = (ctx.store.benchmark() or {}).get("pricing", {})
        emit({"type": "report", "markdown": report, "unsupported_figures": unsupported,
              "calls": dict(deps.calls), "usage": dict(deps.usage),
              "cost_usd": cost_usd(deps.usage, pricing)})
        stage("reporter", "completed")
        return {"report": report}

    return Workflow(
        name="catsight_analysis",
        edges=[
            (START, event_intel),
            (event_intel, exposure_analyst),
            (exposure_analyst, wording_checker),
            (wording_checker, verifier),
            (verifier, reporter),
        ],
    )
