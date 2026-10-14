"""The model-backed agents: AG-3 wording_checker, AG-5's semantic check and
revision, and AG-4 reporter. The graph that runs them is in `agent.py`.

Each agent is a plain function over injected dependencies (`AgentDeps`), so
the ADK graph, the API and the tests all drive the same code, and a fake
client exercises everything without a model call.

None of these computes money. The loss engine's output arrives as data and is
copied; `check_report_figures` then proves every number in the report came
from the facts it was given.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping, Sequence

from catsight_agent import prompts
from catsight_agent.schemas import (
    AskAnswer,
    Citation,
    SearchQueries,
    FlagCandidates,
    RevisedFlag,
    SupportVerdict,
    WordingFlag,
    gemini_response_schema,
)
from catsight_agent.tools.retrieval import STANDARD_QUERIES, search_treaty_clauses
from catsight_agent.tools.verify import match_quote
from ingest.chunking import Chunk

__all__ = [
    "AgentDeps",
    "WORDING_QUERIES",
    "check_treaty_wording",
    "GeminiSemanticChecker",
    "GeminiReviser",
    "check_report_figures",
    "write_report",
    "cost_usd",
    "ask_targets",
    "answer_question",
]

#: The retrieval queries AG-3 runs for every matched treaty (FR-WORD).
WORDING_QUERIES = ("HOURS", "EXCLUSION", "TERRITORY", "REINSTATEMENT", "PERIOD")

#: `Citation.quote` is capped; a verified quote is cut to whole words.
_QUOTE_LIMIT = 300


@dataclass
class AgentDeps:
    """Everything an agent needs, injected."""

    client: Any
    model_main: str
    model_reason: str
    embedder: Any
    #: A vector store that is also a `verify.ChunkLookup` (has `chunks_for`).
    vectors: Any
    #: Receives SSE frames as they happen. Must be thread-safe.
    emit: Callable[[dict[str, Any]], None] = lambda frame: None
    k: int = 3
    #: Calls made, for the cost line in the report.
    calls: dict[str, int] = field(default_factory=dict)
    #: Tokens by model, from each response's usage metadata (thinking counts
    #: as output, as it is billed).
    usage: dict[str, dict[str, int]] = field(default_factory=dict)
    #: The event's observed facts, so the verifier can check what a flag
    #: claims about the event - not only what it claims about the wording.
    observed: list[str] = field(default_factory=list)

    def count(self, kind: str) -> None:
        self.calls[kind] = self.calls.get(kind, 0) + 1

    def record(self, model: str, response: Any) -> None:
        meta = getattr(response, "usage_metadata", None)
        row = self.usage.setdefault(model, {"input": 0, "output": 0})
        if meta is None:
            return
        row["input"] += int(getattr(meta, "prompt_token_count", 0) or 0)
        row["output"] += int(getattr(meta, "candidates_token_count", 0) or 0) + int(
            getattr(meta, "thoughts_token_count", 0) or 0
        )


def cost_usd(usage: Mapping[str, Mapping[str, int]], pricing: Mapping[str, Any]) -> str | None:
    """Model spend for a run, from measured tokens and published prices.
    None when a model used has no price on record - never a guess."""
    prices = (pricing or {}).get("usd_per_million_tokens", {})
    total = Decimal(0)
    for model, tokens in usage.items():
        price = prices.get(model)
        if price is None:
            return None
        total += (Decimal(tokens.get("input", 0)) * Decimal(str(price["input"]))
                  + Decimal(tokens.get("output", 0)) * Decimal(str(price["output"]))) / 1_000_000
    return str(total.quantize(Decimal("0.0001")))


def _generate(deps: AgentDeps, model: str, prompt: str, schema: Any | None, kind: str) -> str:
    """One model call, retried on quota, thinking LOW."""
    from ingest.ingest_treaty import _generate_with_retry
    from ingest.rag_extract import generation_config

    deps.count(kind)
    response = _generate_with_retry(
        lambda: deps.client.models.generate_content(
            model=model, contents=prompt, config=generation_config(schema)
        )
    )
    deps.record(model, response)
    return response.text or ""


def _bounded(quote: str) -> str:
    from ingest.rag_extract import _bounded as bound

    return bound(quote, _QUOTE_LIMIT)


def _render(chunk: Chunk) -> str:
    from ingest.rag_extract import _render_clause

    return _render_clause(chunk)


def _is_endorsement(chunk: Chunk) -> bool:
    title = (chunk.clause_title or "").strip().lower()
    return chunk.source == "transcription" or title.startswith(("endorsement", "addendum"))


# --------------------------------------------------------------------------- #
# AG-3 wording_checker
# --------------------------------------------------------------------------- #


def check_treaty_wording(
    treaty_id: str,
    *,
    event: Mapping[str, Any],
    booked: Mapping[str, Any],
    engine: Mapping[str, Any],
    deps: AgentDeps,
    as_if: bool = True,
) -> list[WordingFlag]:
    """Retrieve this treaty's relevant clauses and flag what could change the
    answer. Returns candidate flags whose quotes are in the cited clause; the
    verifier then decides which are shown."""
    context: dict[str, Chunk] = {}
    for category in WORDING_QUERIES:
        query = STANDARD_QUERIES[category]
        hits = search_treaty_clauses(
            query, store=deps.vectors, embedder=deps.embedder, treaty_id=treaty_id,
            limit=deps.k, clause_type=category,
        )
        deps.emit({
            "type": "retrieval", "agent": "wording_checker", "treaty_id": treaty_id,
            "query": category,
            "hits": [
                {"chunk_id": h.chunk.chunk_id, "clause_no": h.chunk.clause_no,
                 "title": h.chunk.clause_title, "page": h.chunk.page,
                 "score": round(h.score, 3)}
                for h in hits
            ],
        })
        for hit in hits:
            context.setdefault(hit.chunk.chunk_id, hit.chunk)
    # An endorsement can amend any term (FR-ENDORSE-3): always in context.
    for chunk in deps.vectors.chunks_for(treaty_id):
        if _is_endorsement(chunk):
            context.setdefault(chunk.chunk_id, chunk)

    basis = (
        "AS-IF: this historical event is replayed against the treaty book in force "
        "TODAY, to ask what it would cost now. The event's historical date is not a "
        "reason to flag PERIOD - the period test is deliberately not applied."
        if as_if else
        "ACTUAL: the event is assessed against the treaty in force on its date, so "
        "the period of the agreement matters."
    )
    prompt = prompts.WORDING_CHECKER.format(
        event=json.dumps(event, indent=1), basis=basis, treaty_id=treaty_id,
        booked=json.dumps(booked, indent=1), engine=json.dumps(engine, indent=1),
        clauses="\n\n".join(_render(c) for c in context.values()),
    )
    try:
        raw = _generate(deps, deps.model_main, prompt, FlagCandidates, "wording_checker")
        candidates = FlagCandidates.model_validate(json.loads(raw or "{}")).flags
    except Exception as exc:  # noqa: BLE001 - one treaty's failure is not the analysis's
        deps.emit({"type": "warning", "agent": "wording_checker", "treaty_id": treaty_id,
                   "message": f"wording check failed: {type(exc).__name__}: {exc}"})
        return []

    flags: list[WordingFlag] = []
    for candidate in candidates:
        chunk = context.get(candidate.chunk_id)
        if chunk is None or not match_quote(candidate.quote, chunk.text).ok:
            deps.emit({"type": "warning", "agent": "wording_checker", "treaty_id": treaty_id,
                       "message": f"discarded an ungrounded {candidate.issue_type} flag"})
            continue
        flags.append(WordingFlag(
            treaty_id=treaty_id,
            issue_type=candidate.issue_type,
            severity=candidate.severity,
            explanation=candidate.explanation,
            citation=Citation(
                treaty_id=treaty_id, page=chunk.page, clause_no=chunk.clause_no or "n/a",
                quote=_bounded(candidate.quote), source=chunk.source,
            ),
        ))
    return flags


# --------------------------------------------------------------------------- #
# AG-5 semantic check and revision
# --------------------------------------------------------------------------- #


class GeminiSemanticChecker:
    """FR-VERIFY-2 on MODEL_REASON: does the quote SUPPORT the claim, and is
    what it says about the event backed by the observed facts?"""

    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps

    def supports(self, flag: WordingFlag, chunk: Chunk) -> tuple[bool, str | None]:
        prompt = prompts.SEMANTIC_CHECK.format(
            issue_type=flag.issue_type, severity=flag.severity, explanation=flag.explanation,
            quote=flag.citation.quote, clause_no=chunk.clause_no, page=chunk.page,
            clause=chunk.text,
            observed="\n".join(f"- {fact}" for fact in self.deps.observed) or "- (none recorded)",
        )
        try:
            raw = _generate(self.deps, self.deps.model_reason, prompt, SupportVerdict, "verifier")
            verdict = SupportVerdict.model_validate(json.loads(raw or "{}"))
        except Exception as exc:  # noqa: BLE001 - an unchecked claim is not a supported one
            return False, f"the semantic check could not run: {type(exc).__name__}"
        return verdict.supports, verdict.reason


class GeminiReviser:
    """AG-5's single retry: correct a failing flag on its own clause, or drop it."""

    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps

    def revise(self, flag: WordingFlag, reason: str) -> WordingFlag | None:
        chunk = next(
            (c for c in self.deps.vectors.chunks_for(flag.treaty_id)
             if c.clause_no == flag.citation.clause_no
             and flag.citation.page in (c.pages_spanned or (c.page,))),
            None,
        )
        if chunk is None:
            return None
        prompt = prompts.REVISE_FLAG.format(
            treaty_id=flag.treaty_id, reason=reason, issue_type=flag.issue_type,
            explanation=flag.explanation, quote=flag.citation.quote,
            chunk_id=chunk.chunk_id, page=chunk.page, clause=chunk.text,
        )
        try:
            raw = _generate(self.deps, self.deps.model_main, prompt, RevisedFlag, "reviser")
            revised = RevisedFlag.model_validate(json.loads(raw or "{}"))
        except Exception:  # noqa: BLE001 - no revision; the flag is withheld
            return None
        if not revised.keep or not revised.quote.strip():
            return None
        return flag.model_copy(update={
            "explanation": revised.explanation or flag.explanation,
            "citation": flag.citation.model_copy(update={"quote": _bounded(revised.quote)}),
        })


# --------------------------------------------------------------------------- #
# FR-ASK follow-up questions
# --------------------------------------------------------------------------- #

_TREATY_ID = re.compile(r"\bT-\d{3}\b", re.IGNORECASE)
_WORDING_ID = re.compile(r"\bW(\d)\b", re.IGNORECASE)


def ask_targets(question: str, impact: Mapping[str, Any], wording_of: Mapping[str, str]) -> list[str]:
    """Which treaties' clauses to search: those the question names (by
    treaty or wording id), else every responding treaty that has a wording."""
    by_wording = {w.upper(): t for t, w in wording_of.items()}
    named = {m.upper() for m in _TREATY_ID.findall(question)}
    named |= {by_wording[f"W{m}"] for m in _WORDING_ID.findall(question) if f"W{m}" in by_wording}
    named &= set(wording_of)
    if named:
        return sorted(named)
    return [t["treaty_id"] for t in impact.get("treaties", []) if t["treaty_id"] in wording_of]


def rewrite_queries(question: str, deps: AgentDeps) -> list[str]:
    """Clause-style search phrases for a question; [] if the call fails, so
    retrieval falls back to the question itself rather than failing."""
    try:
        raw = _generate(deps, deps.model_main, prompts.REWRITE_QUERY.format(question=question),
                        SearchQueries, "ask_rewrite")
        phrases = SearchQueries.model_validate(json.loads(raw or "{}")).queries
    except Exception:  # noqa: BLE001 - degrade to the raw question
        return []
    return [p.strip() for p in phrases if p.strip() and p.strip() != question][:3]


def answer_question(
    question: str,
    *,
    facts: Mapping[str, Any],
    targets: Sequence[str],
    deps: AgentDeps,
    per_treaty: int = 3,
) -> dict[str, Any]:
    """Answer one question with cited clauses. Returns the answer, the
    citations whose quotes are in their clause, the ones withheld, and any
    figure the answer states that the facts do not contain."""
    queries = [question, *rewrite_queries(question, deps)] if targets else [question]
    context: dict[str, Chunk] = {}
    # Retrieval needs a live embedding per question. If that call fails (quota,
    # network), answer from the engine's facts alone and say so, rather than
    # failing the request: the figures never depended on retrieval anyway.
    retrieval_skipped = False
    try:
        for treaty_id in targets:
            for query in queries:
                for hit in search_treaty_clauses(query, store=deps.vectors, embedder=deps.embedder,
                                                 treaty_id=treaty_id, limit=per_treaty):
                    context.setdefault(hit.chunk.chunk_id, hit.chunk)
    except Exception:  # noqa: BLE001 - degrade to a facts-only answer
        retrieval_skipped = True

    facts_text = json.dumps(facts, indent=1, default=str)
    if context:
        clauses = "\n\n".join(_render(c) for c in context.values())
    elif retrieval_skipped:
        clauses = "(clause retrieval was unavailable for this question; answer from the facts only and cite no clauses)"
    else:
        clauses = "(none retrieved)"
    prompt = prompts.ASK.format(question=question, facts=facts_text, clauses=clauses)
    raw = _generate(deps, deps.model_main, prompt, AskAnswer, "ask")
    answer = AskAnswer.model_validate(json.loads(raw or "{}"))

    citations, withheld, verified_text = [], [], []
    for item in answer.citations:
        chunk = context.get(item.chunk_id)
        if chunk is not None and match_quote(item.quote, chunk.text).ok:
            citations.append({"treaty_id": chunk.treaty_id, "page": chunk.page,
                              "clause_no": chunk.clause_no, "quote": _bounded(item.quote),
                              "source": chunk.source})
            verified_text.append(f"{chunk.page} {chunk.clause_no} {chunk.text}")
        else:
            withheld.append({"chunk_id": item.chunk_id,
                             "reason": "not a retrieved clause" if chunk is None
                             else "quote not found in the clause"})
    # A figure is supported if the engine produced it, or if it appears in a
    # VERIFIED clause the answer cites (a contract term such as "72 hours" or
    # a 19.8 event limit), along with that clause's page and number. Numbers
    # from withheld citations do not count.
    allowed = " ".join([facts_text, *verified_text])
    return {
        "answer_md": answer.answer_md.strip(),
        "citations": citations,
        "withheld": withheld,
        "unsupported_figures": check_report_figures(answer.answer_md, allowed),
        "searched": sorted({c.treaty_id for c in context.values()}),
        "retrieval_skipped": retrieval_skipped,
    }


# --------------------------------------------------------------------------- #
# AG-4 reporter
# --------------------------------------------------------------------------- #

#: A figure: digits not glued to a word or decimal point, and not the numeric
#: tail of an identifier such as T-004 or JP-27 (letters, hyphen, digits). A
#: minus sign or dash before a number is still read as a figure.
_NUMBER = re.compile(r"(?<![\w.])(?<![A-Za-z]-)\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[Decimal]:
    out: set[Decimal] = set()
    for token in _NUMBER.findall(text):
        try:
            out.add(Decimal(token.replace(",", "")).normalize())
        except InvalidOperation:  # pragma: no cover - the regex admits only digits
            continue
    return out


def check_report_figures(report: str, facts: str) -> list[str]:
    """Numbers in the report that do not appear in the facts - C-6's guard
    against the reporter doing arithmetic. Returns them as written."""
    allowed = _numbers(facts)
    return sorted({
        token for token in _NUMBER.findall(report)
        if Decimal(token.replace(",", "")).normalize() not in allowed
    })


def write_report(facts: Mapping[str, Any], deps: AgentDeps) -> tuple[str, list[str]]:
    """The report, and any figures in it that the facts do not contain. One
    regeneration if the first draft has unsupported figures."""
    facts_text = json.dumps(facts, indent=1, default=str)
    prompt = prompts.REPORTER.format(facts=facts_text)
    report = _generate(deps, deps.model_main, prompt, None, "reporter")
    unsupported = check_report_figures(report, facts_text)
    if unsupported:
        retry = (f"{prompt}\nYOUR DRAFT STATED FIGURES NOT IN THE FACTS: "
                 f"{', '.join(unsupported)}. Remove or replace them with figures "
                 "copied from the facts.")
        report = _generate(deps, deps.model_main, retry, None, "reporter")
        unsupported = check_report_figures(report, facts_text)
    return report.strip(), unsupported
