"""FR-COURT - the Clause Courtroom, as an ADK graph.

    START -> brief -> (cedent_counsel, reinsurer_counsel) -> join -> price -> arbiter

  brief              picks the disputed flag (FR-COURT-1) and retrieves its
                     clauses from Firestore vector search.
  *_counsel          AG-6 / AG-7, in PARALLEL, opposing briefs. Each must quote
                     a retrieved clause; the quote is string-matched and then
                     checked for support (FR-VERIFY). A side that fails is
                     dropped, with the reason shown - never shown unsupported.
  price              each verified side's position goes through the bounded
                     scenario tool; money at stake per party is a Python
                     subtraction of the two engine results (FR-COURT-4).
  arbiter            AG-8 on MODEL_REASON summarises; it does not decide, and
                     any figure it states must come from the priced outcomes.

The analyst's position is recorded separately (FR-COURT-5).
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any, Mapping

from catsight_agent import prompts
from catsight_agent.agents import (
    AgentDeps,
    _bounded,
    _generate,
    _render,
    check_report_figures,
)
from catsight_agent.schemas import Citation, CounselArgument, SupportVerdict
from catsight_agent.tools.retrieval import STANDARD_QUERIES, search_treaty_clauses
from catsight_agent.tools.verify import match_quote

__all__ = ["pick_disputed_flag", "build_courtroom", "PARTY_KEYS", "LABEL"]

LABEL = "Issue-spotting, not legal advice. The analyst decides."
PARTY_KEYS = ("cedent_net_cost", "market_net", "our_net", "total_ceded")


def pick_disputed_flag(verified: list[Mapping[str, Any]], price_at_max) -> tuple[dict | None, str]:
    """FR-COURT-1: a verified exclusion flag whose applicability turns on an
    event fact, the one with the largest engine-priced swing (HIGH before
    MEDIUM on a tie). Returns the flag and, if none qualifies, why the
    Courtroom is skipped.

    MEDIUM qualifies as well as HIGH: severity is the wording agent's
    judgement and varies between runs on the same clause (ASSUMPTIONS M8),
    whereas a verified quote does not. LOW flags are not argued."""
    candidates = [v["flag"] for v in verified
                  if v["flag"]["issue_type"] == "EXCLUSION" and v["flag"]["severity"] in DISPUTED]
    if not candidates:
        hours = any(v["flag"]["issue_type"] in ("HOURS", "PERIOD") for v in verified)
        return None, ("No HIGH or MEDIUM exclusion flag was raised and verified for this event."
                      + (" Hours-clause questions are explored in the What-if panel." if hours else ""))
    priced = [(abs(Decimal(price_at_max(f["treaty_id"])["money_at_stake"]["our_net"])), f)
              for f in candidates]
    priced.sort(key=lambda pair: (-pair[0], DISPUTED.index(pair[1]["severity"]), pair[1]["treaty_id"]))
    return priced[0][1], ""


#: Severities the Courtroom will argue, strongest first.
DISPUTED = ("HIGH", "MEDIUM")


def build_courtroom(
    *,
    event_id: str,
    flag: Mapping[str, Any],
    deps: AgentDeps,
    price,
    emit=lambda frame: None,
) -> tuple[Any, dict[str, Any]]:
    """The graph and the dict it fills with the result."""
    from google.adk.workflow import START, JoinNode, Workflow, node

    out: dict[str, Any] = {"flag": dict(flag), "label": LABEL, "sides": {}}
    treaty_id = flag["treaty_id"]
    cause = "the excluded cause"

    @node(name="brief")
    async def brief(node_input: Any = None) -> dict:
        emit({"type": "stage", "agent": "courtroom_brief", "status": "started"})
        context = {}
        cited = flag["citation"]
        for chunk in deps.vectors.chunks_for(treaty_id):
            if chunk.clause_no == cited["clause_no"] or chunk.clause_type == "COVER":
                context[chunk.chunk_id] = chunk
        hits_cover = await asyncio.to_thread(
            search_treaty_clauses, "business covered scope of reinsurance covering clause insuring agreement",
            store=deps.vectors, embedder=deps.embedder, treaty_id=treaty_id, limit=2)
        for hit in hits_cover:
            context.setdefault(hit.chunk.chunk_id, hit.chunk)
        hits = await asyncio.to_thread(
            search_treaty_clauses, STANDARD_QUERIES["EXCLUSION"], store=deps.vectors,
            embedder=deps.embedder, treaty_id=treaty_id, limit=3)
        for hit in hits:
            context.setdefault(hit.chunk.chunk_id, hit.chunk)
        out["context"] = context
        emit({"type": "stage", "agent": "courtroom_brief", "status": "completed"})
        return {"ok": True}

    def counsel(side: str):
        async def argue(node_input: Any = None) -> dict:
            emit({"type": "stage", "agent": f"{side}_counsel", "status": "started"})
            result = await asyncio.to_thread(_argue, side)
            emit({"type": "stage", "agent": f"{side}_counsel", "status": "completed"})
            return result
        return node(argue, name=f"{side}_counsel")

    def _argue(side: str) -> dict:
        title, client, stance = prompts.COUNSEL_SIDES[side]
        context = out["context"]
        base_prompt = prompts.COUNSEL.format(
            side_title=title, client=client, stance=stance, issue_type=flag["issue_type"],
            treaty_id=treaty_id, explanation=flag["explanation"],
            observed="\n".join(f"- {o}" for o in deps.observed) or "- (none recorded)",
            clauses="\n\n".join(_render(c) for c in context.values()),
        )
        prompt = base_prompt
        last_reason = "no argument"
        last_arg: CounselArgument | None = None
        for attempt in range(2):
            stage_name = f"{side}_counsel" if attempt == 0 else f"{side}_counsel_revise"
            try:
                raw = _generate(deps, deps.model_main, prompt, CounselArgument, stage_name)
                arg = CounselArgument.model_validate(json.loads(raw or "{}"))
                last_arg = arg
            except Exception as exc:  # noqa: BLE001 - a side that cannot argue is dropped
                return _dropped(side, f"counsel could not produce an argument ({type(exc).__name__})", last_arg)
            chunk = context.get(arg.chunk_id)
            if chunk is None:
                last_reason = f"cited {arg.chunk_id}, which is not a retrieved clause"
            elif not match_quote(arg.quoted_text, chunk.text).ok:
                last_reason = "the quoted text is not in the cited clause"
            else:
                citation = Citation(treaty_id=treaty_id, page=chunk.page, clause_no=chunk.clause_no or "n/a",
                                    quote=_bounded(arg.quoted_text), source=chunk.source)
                supported, reason = _quote_is_faithful(arg, chunk)
                if supported:
                    return {"side": side, "verified": True, "reading": arg.reading,
                            "argument_md": arg.argument_md, "excluded_share": arg.excluded_share,
                            "citation": citation.model_dump(mode="json")}
                last_reason = f"the quote is misrepresented: {reason}"
                if reason.startswith("the quote check could not run"):
                    return _dropped(side, last_reason, arg)
            prompt = (
                f"{base_prompt}\n"
                f"PREVIOUS ATTEMPT FAILED VERIFICATION: {last_reason}\n"
                f"Previous chunk_id: {arg.chunk_id}\n"
                f"Previous reading: {arg.reading}\n"
                f"Previous quoted_text: {arg.quoted_text}\n"
                "Correct your response: choose a chunk_id from CLAUSES above, copy quoted_text "
                "character for character from that clause (or 2 to 3 verbatim fragments in order "
                "separated by '...'), and state in reading only what that clause itself establishes "
                "on its own terms."
            )
        return _dropped(side, last_reason, last_arg)

    def _quote_is_faithful(arg: CounselArgument, chunk: Any) -> tuple[bool, str]:
        """FR-COURT-3's meaning check: is the quote used for what it says?"""
        prompt = prompts.COUNSEL_QUOTE_CHECK.format(
            reading=arg.reading, quote=arg.quoted_text, clause_no=chunk.clause_no,
            page=chunk.page, clause=chunk.text,
            observed="\n".join(f"- {o}" for o in deps.observed) or "- (none recorded)",
        )
        try:
            raw = _generate(deps, deps.model_reason, prompt, SupportVerdict, "quote_check")
            verdict = SupportVerdict.model_validate(json.loads(raw or "{}"))
        except Exception as exc:  # noqa: BLE001 - an unchecked quote is not a verified one
            return False, f"the quote check could not run ({type(exc).__name__})"
        return verdict.supports, verdict.reason

    def _dropped(side: str, reason: str, arg: CounselArgument | None = None) -> dict:
        return {"side": side, "verified": False, "dropped_reason": reason,
                "reading": arg.reading if arg else None}

    join = JoinNode(name="join")

    @node(name="price")
    async def price_node(node_input: dict) -> dict:
        sides = {s["side"]: s for s in node_input.values()}
        for side in sides.values():
            if side["verified"]:
                side["priced"] = await asyncio.to_thread(price, treaty_id, side["excluded_share"], cause)
        out["sides"] = sides
        both = all(sides.get(s, {}).get("verified") for s in ("cedent", "reinsurer"))
        if both:
            c, r = sides["cedent"]["priced"]["scenario"], sides["reinsurer"]["priced"]["scenario"]
            # Reinsurer's reading minus cedent's, per party. Python, never a model.
            out["money_at_stake"] = {k: str(Decimal(r[k]) - Decimal(c[k])) for k in PARTY_KEYS}
        emit({"type": "courtroom_sides", "sides": sides, "money_at_stake": out.get("money_at_stake")})
        return {"both": both}

    @node(name="arbiter")
    async def arbiter(node_input: dict) -> dict:
        emit({"type": "stage", "agent": "arbiter", "status": "started"})
        sides = out["sides"]
        verified = {k: v for k, v in sides.items() if v["verified"]}
        priced = {k: {p: v["priced"]["scenario"][p] for p in PARTY_KEYS} for k, v in verified.items()}
        if verified:
            # The engine's reading with nothing excluded, for reference.
            base = next(iter(verified.values()))["priced"]["base"]
            priced["base_nothing_excluded"] = {p: base[p] for p in PARTY_KEYS}
        if out.get("money_at_stake"):
            priced["money_at_stake_reinsurer_minus_cedent"] = out["money_at_stake"]
        if not verified:
            out["arbiter_md"] = "Neither side could cite verified wording, so there is no dispute to summarise."
            out["unsupported_figures"] = []
        else:
            prompt = prompts.ARBITER.format(
                dispute=f"{flag['treaty_id']} {flag['issue_type']}: {flag['explanation']}",
                arguments=json.dumps({k: {"reading": v["reading"], "argument": v["argument_md"],
                                          "quote": v["citation"]["quote"],
                                          "excluded_share": v["excluded_share"]}
                                      for k, v in verified.items()}, indent=1),
                priced=json.dumps(priced, indent=1),
            )
            text = await asyncio.to_thread(_generate, deps, deps.model_reason, prompt, None, "arbiter")
            # A figure is supported if it appears in anything the arbiter was
            # given - the dispute, the arguments (with the facts they quote),
            # the observed facts and the priced outcomes - or is a share
            # restated as a percentage. Anything else is reported.
            shares = " ".join(f"{Decimal(str(v['excluded_share'])) * 100:f}" for v in verified.values())
            observed = " ".join(deps.observed)
            out["arbiter_md"] = text.strip()
            out["unsupported_figures"] = check_report_figures(
                text, " ".join([prompt, observed, shares]))
        emit({"type": "stage", "agent": "arbiter", "status": "completed"})
        return {"done": True}

    # The same node objects on both sides of the fan-out and the join.
    cedent, reinsurer = counsel("cedent"), counsel("reinsurer")
    graph = Workflow(
        name="clause_courtroom",
        edges=[
            (START, brief),
            (brief, (cedent, reinsurer)),
            ((cedent, reinsurer), join),
            (join, price_node),
            (price_node, arbiter),
        ],
    )
    return graph, out
