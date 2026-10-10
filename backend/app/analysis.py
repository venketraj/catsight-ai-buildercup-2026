"""The analysis pipeline â€” FR-MATCH and FR-LOSS, end to end, deterministically.

This is the spine of an analysis: an event, the treaties it touches, and what
each one pays. It is built entirely on tested modules - `hazard`,
`vulnerability`, `loss_engine`, `seed_portfolio` - and **makes no model calls
at all.**

That is a deliberate ordering choice, not a shortcut. The numbers are the part
a reinsurer would be fired for getting wrong, and they come from arithmetic
that a judge can re-derive. The agents add explanation, wording flags and the
Courtroom *on top of* this; they never produce a figure. So this layer must
work, be deployable and be demonstrable before any agent exists - and once it
does, a quota failure degrades the demo's prose rather than its answer.

## Matching is conservative (FR-MATCH)

A treaty responds when **all** of these hold:

  * the event's peril is a covered peril;
  * at least one affected region is inside the territory - by country code,
    with region-level exclusions subtracted (W3's Okinawa carve-out);
  * and **only when `as_if=False`**, the event falls inside the treaty period.

## As-if is the default, and it is not a shortcut

Replay mode defaults to `as_if=True`: a historical event applied to the book
in force today. That is standard practice - the question a reinsurer asks is
"what would Jebi cost us on this year's portfolio", not "what did it cost the
2018 portfolio", which is already settled and paid.

It also has to be the default here for the demo to say anything at all: the
replay events are 2013-2024 and the synthetic book runs 2025-2027, so a
literal period test excludes all 24 treaties. Running with `as_if=False`
exercises the period rule instead, and the book carries one deliberately
expired treaty so that path has something to exclude. The UI must show which
mode produced a figure (UI-9); an as-if number presented as a historical one
would be misleading.

Anything unmatched is reported with a reason rather than silently dropped. An
analyst's first question about a programme that did not respond is "why not",
and "it was not in the list" is not an answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from catsight_agent.tools.loss_engine import (
    CatXLResult,
    ExposureSlice,
    Layer,
    QuotaShare,
    QuotaShareResult,
    apply_cat_xl,
    apply_quota_share,
    gross_loss,
    quantise,
)
from catsight_agent.tools.vulnerability import VulnerabilityModel
from catsight_agent.store import DataStore, EventNotFound, LocalStore
from ingest.seed_portfolio import Portfolio, Treaty

__all__ = [
    "EventNotFound",
    "MatchDecision",
    "TreatyOutcome",
    "AnalysisResult",
    "available_events",
    "load_event",
    "match_treaties",
    "analyse",
    "stream_analysis",
]


# --------------------------------------------------------------------------- #
# Events - read through a DataStore. These wrappers keep the local helpers.
# --------------------------------------------------------------------------- #


def available_events(data_dir: Path | str = "data") -> list[dict[str, Any]]:
    """API-2's replay catalogue from local data. Sorted by date, newest last."""
    return LocalStore(data_dir).events()


def load_event(event_id: str, data_dir: Path | str = "data") -> dict[str, Any]:
    return LocalStore(data_dir).event(event_id)


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MatchDecision:
    """Why a treaty did or did not respond. Both cases carry a reason."""

    treaty_id: str
    cedent_id: str
    matched: bool
    reason: str
    regions: tuple[str, ...] = ()


def _event_date(event: dict[str, Any]) -> str:
    return str(event["start"])[:10]


def _affected(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Regions with a non-zero intensity. A region sampled at zero is in the
    file for completeness but is not affected."""
    out = []
    for region in event.get("regions", []):
        values = (region.get("intensity") or {}).values()
        if any(float(v) > 0 for v in values):
            out.append(region)
    return out


def match_treaties(
    portfolio: Portfolio, event: dict[str, Any], *, as_if: bool = True
) -> tuple[MatchDecision, ...]:
    """FR-MATCH. One decision per treaty, matched or not, always with a reason."""
    peril = event["peril"]
    on = _event_date(event)
    affected = _affected(event)
    countries = {r.get("country") for r in affected}

    decisions: list[MatchDecision] = []
    for treaty in portfolio.treaties:
        if peril not in treaty.perils:
            decisions.append(
                MatchDecision(
                    treaty.treaty_id,
                    treaty.cedent_id,
                    False,
                    f"{peril} is not a covered peril (covers {', '.join(treaty.perils)})",
                )
            )
            continue

        if not as_if and not (treaty.inception <= on <= treaty.expiry):
            decisions.append(
                MatchDecision(
                    treaty.treaty_id,
                    treaty.cedent_id,
                    False,
                    f"event date {on} is outside the period "
                    f"{treaty.inception} to {treaty.expiry}",
                )
            )
            continue

        include = set(treaty.territory.get("include", ()))
        exclude = set(treaty.territory.get("exclude", ()))
        if not (include & countries):
            decisions.append(
                MatchDecision(
                    treaty.treaty_id,
                    treaty.cedent_id,
                    False,
                    f"no affected region in territory ({', '.join(sorted(include))})",
                )
            )
            continue

        in_scope = tuple(
            r["code"]
            for r in affected
            if r.get("country") in include and r["code"] not in exclude
        )
        if not in_scope:
            # Every affected region in the covered country is carved out - W3's
            # Okinawa exclusion is exactly this case, and it must read as a
            # territorial exclusion rather than "no exposure".
            carved = sorted(exclude & {r["code"] for r in affected})
            decisions.append(
                MatchDecision(
                    treaty.treaty_id,
                    treaty.cedent_id,
                    False,
                    f"every affected region is territorially excluded ({', '.join(carved)})",
                    (),
                )
            )
            continue

        decisions.append(
            MatchDecision(
                treaty.treaty_id,
                treaty.cedent_id,
                True,
                f"{len(in_scope)} affected region(s) in territory",
                in_scope,
            )
        )
    return tuple(decisions)


# --------------------------------------------------------------------------- #
# Pricing
# --------------------------------------------------------------------------- #


def _damage_ratios(
    event: dict[str, Any], model: VulnerabilityModel
) -> dict[str, float]:
    """Region code to damage ratio, from the event's sampled intensities."""
    peril = event["peril"]
    key = "wind_ms" if peril == "WS" else "mmi"
    ratios: dict[str, float] = {}
    for region in event.get("regions", []):
        intensity = (region.get("intensity") or {}).get(key)
        if intensity is None:
            continue
        ratios[region["code"]] = model.damage_ratio(
            float(intensity), peril, region.get("country") or "JPN"
        )
    return ratios


def _layers_of(treaty: Treaty) -> list[Layer]:
    return [
        Layer(
            layer_no=layer.layer_no,
            retention=layer.retention,
            limit=layer.limit,
            premium=layer.premium,
            our_share=layer.our_share,
            reinstatements=int(layer.reinstatements.get("count", 0)),
            reinstatement_rate=Decimal(str(layer.reinstatements.get("rate", 1.0))),
        )
        for layer in treaty.layers
    ]


@dataclass
class TreatyOutcome:
    """One treaty's result, with the inputs that produced it."""

    treaty_id: str
    cedent_id: str
    cedent_name: str
    type: str
    gross: Decimal
    regions: tuple[str, ...]
    cat_xl: CatXLResult | None = None
    quota_share: QuotaShareResult | None = None

    @property
    def our_net(self) -> Decimal:
        if self.cat_xl is not None:
            return self.cat_xl.our_net
        if self.quota_share is not None:
            # No reinstatement premium on a proportional treaty, so net is loss.
            return self.quota_share.our_loss
        return Decimal(0)

    @property
    def ceded(self) -> Decimal:
        if self.cat_xl is not None:
            return self.cat_xl.total_ceded
        if self.quota_share is not None:
            return self.quota_share.ceded
        return Decimal(0)

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "treaty_id": self.treaty_id,
            "cedent_id": self.cedent_id,
            "cedent": self.cedent_name,
            "type": self.type,
            "gross": str(quantise(self.gross)),
            "regions": list(self.regions),
            "our_net": str(quantise(self.our_net)),
            "ceded": str(quantise(self.ceded)),
        }
        if self.cat_xl is not None:
            payload["layers"] = [
                {
                    "layer_no": lr.layer_no,
                    "ceded": str(quantise(lr.ceded)),
                    "our_loss": str(quantise(lr.our_loss)),
                    "our_rip": str(quantise(lr.our_rip)),
                    # The engine's own verdicts, not recomputed here. `burn`
                    # exceeds 1 when reinstatements are used, which is the
                    # layer chart's whole point (UI-4).
                    "burn": str(quantise(lr.burn, 4)),
                    "exhausted": lr.exhausted,
                    "reinstated": str(quantise(lr.reinstated)),
                }
                for lr in self.cat_xl.layers
            ]
            # The full per-party view (MONEY_MOMENT section 4.4). All of it,
            # because the insight is the comparison: the cedent's cost, the
            # market's receipt and ours move differently, and a caller
            # deriving one of them from the others would get RIP's direction
            # wrong - it is a cost to the cedent and a receipt to us.
            payload["cedent_retention"] = str(quantise(self.cat_xl.cedent_retention))
            payload["cedent_net_cost"] = str(quantise(self.cat_xl.cedent_net_cost))
            payload["total_rip"] = str(quantise(self.cat_xl.total_rip))
            payload["our_loss"] = str(quantise(self.cat_xl.our_loss))
            payload["our_rip"] = str(quantise(self.cat_xl.our_rip))
            payload["market_net"] = str(quantise(self.cat_xl.market_net))
        if self.quota_share is not None:
            payload["capped"] = self.quota_share.capped
        return payload


@dataclass
class AnalysisResult:
    event: dict[str, Any]
    outcomes: list[TreatyOutcome] = field(default_factory=list)
    decisions: tuple[MatchDecision, ...] = ()
    #: True when the period test was skipped - a historical event on the
    #: current book. Carried into the payload so the UI can label it.
    as_if: bool = True
    #: The method version the figures were produced under, so a number can
    #: always be traced to the rules in force when it was computed.
    methodology: dict[str, Any] = field(default_factory=dict)

    @property
    def matched(self) -> int:
        return sum(1 for d in self.decisions if d.matched)

    @property
    def excluded(self) -> int:
        return sum(1 for d in self.decisions if not d.matched)

    @property
    def our_net_total(self) -> Decimal:
        return sum((o.our_net for o in self.outcomes), Decimal(0))

    @property
    def gross_total(self) -> Decimal:
        return sum((o.gross for o in self.outcomes), Decimal(0))

    @property
    def ceded_total(self) -> Decimal:
        return sum((o.ceded for o in self.outcomes), Decimal(0))

    def to_json(self) -> dict[str, Any]:
        return {
            "event": {
                "event_id": self.event["event_id"],
                "name": self.event["name"],
                "peril": self.event["peril"],
                "start": self.event["start"],
                "end": self.event["end"],
                "duration_h": self.event.get("duration_h"),
                "regions": len(self.event.get("regions", [])),
                "facts": self.event.get("facts", []),
                "disclaimer": self.event.get("disclaimer"),
            },
            "totals": {
                "gross": str(quantise(self.gross_total)),
                "ceded": str(quantise(self.ceded_total)),
                # What the insurers keep - served, so the UI never subtracts.
                "retained": str(quantise(self.gross_total - self.ceded_total)),
                "our_net": str(quantise(self.our_net_total)),
                "treaties_matched": self.matched,
                "treaties_excluded": self.excluded,
            },
            "as_if": self.as_if,
            "methodology": {
                "version": self.methodology.get("version"),
                "effective_from": self.methodology.get("effective_from"),
            },
            "treaties": [o.to_json() for o in self.outcomes],
            "excluded": [
                {"treaty_id": d.treaty_id, "reason": d.reason}
                for d in self.decisions
                if not d.matched
            ],
        }


def analyse(
    event_id: str,
    *,
    portfolio: Portfolio | None = None,
    model: VulnerabilityModel | None = None,
    data_dir: Path | str = "data",
    as_if: bool = True,
    store: DataStore | None = None,
) -> AnalysisResult:
    """Run the deterministic half of an analysis for one replay event.

    Everything is read through `store` - the book, the event and the method -
    so the same code prices from local JSON or from Firestore. `portfolio`
    and `model` remain as overrides for tests and what-if scenarios.
    """
    store = store if store is not None else LocalStore(data_dir)
    event = store.event(event_id)
    portfolio = portfolio if portfolio is not None else store.portfolio()
    method = store.methodology()
    model = model if model is not None else VulnerabilityModel.from_dict(method["vulnerability"])

    decisions = match_treaties(portfolio, event, as_if=as_if)
    ratios = _damage_ratios(event, model)
    result = AnalysisResult(event=event, decisions=decisions, as_if=as_if, methodology=method)

    for decision in decisions:
        if not decision.matched:
            continue
        treaty = portfolio.treaty(decision.treaty_id)
        slices = [
            ExposureSlice(e.region_code, e.peril, e.tsi_usd)
            for e in portfolio.exposures_for(treaty.cedent_id, event["peril"])
            if e.region_code in decision.regions
        ]
        gross = gross_loss(slices, ratios)

        outcome = TreatyOutcome(
            treaty_id=treaty.treaty_id,
            cedent_id=treaty.cedent_id,
            cedent_name=portfolio.cedent(treaty.cedent_id).name,
            type=treaty.type,
            gross=gross,
            regions=decision.regions,
        )
        if treaty.type == "CAT_XL" and treaty.layers:
            outcome.cat_xl = apply_cat_xl([gross], _layers_of(treaty))
        elif treaty.qs:
            outcome.quota_share = apply_quota_share(
                gross,
                QuotaShare(
                    cession_pct=Decimal(str(treaty.qs["cession_pct"])),
                    our_share=Decimal(str(treaty.qs.get("our_share", 0))),
                    event_limit=(
                        Decimal(str(treaty.qs["event_limit"]))
                        if treaty.qs.get("event_limit")
                        else None
                    ),
                ),
            )
        result.outcomes.append(outcome)

    # Largest net exposure first: the first question is always "where are we
    # most on the hook", not "which treaty id sorts first".
    result.outcomes.sort(key=lambda o: o.our_net, reverse=True)
    return result


# --------------------------------------------------------------------------- #
# "How was this calculated?" - one treaty, step by step
# --------------------------------------------------------------------------- #

#: Reconciliation fields that back a layer's terms with a contract citation.
_CITED_TERMS = ("retention", "limit", "premium")


def _m(value: Decimal | float | str) -> str:
    """Display a money figure in USD millions with two decimals."""
    return f"{quantise(Decimal(str(value)))}"


def _citations_for(store: DataStore, treaty_id: str) -> dict[str, dict[str, Any]]:
    """Field -> verified citation, from the wording reconciliation, if any."""
    recon = store.reconciliation(treaty_id) or {}
    out: dict[str, dict[str, Any]] = {}
    for row in recon.get("fields", []):
        citation = row.get("citation") or {}
        if citation.get("status") in ("verified", "transcribed"):
            out[row["field"]] = {
                "page": citation.get("page"),
                "clause_no": citation.get("clause_no"),
                "quote": citation.get("quote"),
                "status": citation.get("status"),
                "agrees_with_book": row.get("result") == "match",
            }
    return out


def explain_treaty(
    event_id: str,
    treaty_id: str,
    *,
    store: DataStore | None = None,
    data_dir: Path | str = "data",
    as_if: bool = True,
) -> dict[str, Any]:
    """Every step from the event to this treaty's figures, for the UI.

    All figures are the engine's: the per-region losses use the same damage
    ratios and multiplication as `gross_loss`, the layer figures are read from
    the engine's result, and the formula strings only display those inputs
    and outputs. Nothing here is a second calculation that could disagree.
    """
    store = store if store is not None else LocalStore(data_dir)
    event = store.event(event_id)
    book = store.portfolio()
    treaty = book.treaty(treaty_id)  # KeyError for an unknown treaty
    method = store.methodology()
    model = VulnerabilityModel.from_dict(method["vulnerability"])

    decision = next(d for d in match_treaties(book, event, as_if=as_if) if d.treaty_id == treaty_id)
    key, unit = ("wind_ms", "m/s") if event["peril"] == "WS" else ("mmi", "MMI")
    regions = {r["code"]: r for r in event.get("regions", [])}
    ratios = _damage_ratios(event, model)

    rows = []
    for exposure in book.exposures_for(treaty.cedent_id, event["peril"]):
        if exposure.region_code not in decision.regions:
            continue
        region = regions[exposure.region_code]
        ratio = Decimal(str(ratios.get(exposure.region_code, 0)))
        rows.append({
            "region": exposure.region_code,
            "name": region.get("name"),
            "intensity": (region.get("intensity") or {}).get(key),
            "unit": unit,
            "insured_usd_m": _m(exposure.tsi_usd),
            "damage_ratio": str(ratio.quantize(Decimal("0.000001"))),
            "loss_usd_m": _m(Decimal(str(exposure.tsi_usd)) * ratio),
        })
    rows.sort(key=lambda r: Decimal(r["loss_usd_m"]), reverse=True)

    explanation: dict[str, Any] = {
        "treaty_id": treaty_id,
        "cedent": book.cedent(treaty.cedent_id).name,
        "type": treaty.type,
        "perspective": "Lion Re (reinsurer) - our share of what this treaty pays",
        "event": {"name": event["name"], "peril": event["peril"], "start": event["start"],
                  "end": event["end"], "source": "NOAA IBTrACS" if event["peril"] == "WS"
                  else "USGS ShakeMap"},
        "match": {"matched": decision.matched, "reason": decision.reason,
                  "territory": {k: list(v) for k, v in treaty.territory.items()},
                  "perils": list(treaty.perils)},
        "damage": {"rows": rows, "regions": len(rows),
                   "curve": "Emanuel (2011)" if event["peril"] == "WS" else "MMI table",
                   "method_version": method["version"]},
        "citations": _citations_for(store, treaty_id),
    }
    if not decision.matched:
        return explanation

    result = analyse(event_id, store=store, as_if=as_if)
    outcome = next(o for o in result.outcomes if o.treaty_id == treaty_id)
    gross = quantise(outcome.gross)
    explanation["damage"]["gross_usd_m"] = str(gross)

    if outcome.cat_xl is not None:
        layers = []
        for spec, lr in zip(treaty.layers, outcome.cat_xl.layers):
            share = Decimal(str(spec.our_share))
            layers.append({
                "layer_no": lr.layer_no,
                "attaches_usd_m": _m(spec.retention),
                "limit_usd_m": _m(spec.limit),
                "ceded_usd_m": _m(lr.ceded),
                "our_share": f"{(share * 100).normalize()}%",
                "our_loss_usd_m": _m(lr.our_loss),
                "our_rip_usd_m": _m(lr.our_rip),
                "formula": (
                    f"min(max({gross} - {_m(spec.retention)}, 0), {_m(spec.limit)}) "
                    f"= {_m(lr.ceded)}"
                ),
                "our_formula": f"{_m(lr.ceded)} x {(share * 100).normalize()}% = {_m(lr.our_loss)}",
                "rip_formula": (
                    f"{_m(lr.reinstated)} / {_m(spec.limit)} x premium {_m(spec.premium)} x "
                    f"rate {Decimal(str(spec.reinstatements.get('rate', 1))).normalize()} x "
                    f"{(share * 100).normalize()}% = {_m(lr.our_rip)}"
                ),
            })
        cat = outcome.cat_xl
        explanation["layers"] = layers
        explanation["parties"] = {
            "cedent_keeps_usd_m": _m(cat.cedent_retention),
            "reinsurers_pay_usd_m": _m(cat.total_ceded),
            "our_gross_usd_m": _m(cat.our_loss),
            "our_rip_usd_m": _m(cat.our_rip),
            "our_net_usd_m": _m(cat.our_net),
        }
    elif outcome.quota_share is not None:
        qs = outcome.quota_share
        explanation["quota_share"] = {
            "cession_pct": str(treaty.qs.get("cession_pct")),
            "event_limit_usd_m": treaty.qs.get("event_limit"),
            "ceded_usd_m": _m(qs.ceded),
            "capped": qs.capped,
            "our_net_usd_m": _m(qs.our_loss),
        }
        explanation["parties"] = {
            "cedent_keeps_usd_m": _m(outcome.gross - qs.ceded),
            "reinsurers_pay_usd_m": _m(qs.ceded),
            "our_net_usd_m": _m(qs.our_loss),
        }
    return explanation


# --------------------------------------------------------------------------- #
# SSE (API-4)
# --------------------------------------------------------------------------- #


def _sse(payload: dict[str, Any]) -> str:
    """One SSE frame. `data: {json}\\n\\n`, per API-4."""
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def stream_analysis(
    event_id: str,
    *,
    portfolio: Portfolio | None = None,
    model: VulnerabilityModel | None = None,
    data_dir: Path | str = "data",
    as_if: bool = True,
    store: DataStore | None = None,
) -> Iterator[str]:
    """API-4's event stream for the deterministic pipeline.

    The frame types are the ones the final agent graph will emit, so the
    frontend is written against the real contract now and does not change when
    the agents land - only more frames arrive between the same bookends.
    """
    stages = ("event_intel", "exposure_analyst")
    store = store if store is not None else LocalStore(data_dir)
    try:
        yield _sse({"type": "stage", "agent": stages[0], "status": "started"})
        event = store.event(event_id)
        yield _sse(
            {
                "type": "result",
                "key": "event",
                "data": {
                    "event_id": event["event_id"],
                    "name": event["name"],
                    "peril": event["peril"],
                    "duration_h": event.get("duration_h"),
                    "regions": len(event.get("regions", [])),
                    "facts": event.get("facts", []),
                },
            }
        )
        yield _sse({"type": "stage", "agent": stages[0], "status": "completed"})

        yield _sse({"type": "stage", "agent": stages[1], "status": "started"})
        result = analyse(
            event_id,
            portfolio=portfolio,
            model=model,
            as_if=as_if,
            store=store,
        )
        yield _sse(
            {
                "type": "tool",
                "agent": stages[1],
                "name": "match_treaties",
                "summary": f"{result.matched} matched, {result.excluded} excluded",
            }
        )
        yield _sse(
            {"type": "result", "key": "impact", "data": result.to_json()}
        )
        yield _sse({"type": "stage", "agent": stages[1], "status": "completed"})
        yield _sse({"type": "done", "analysis_id": f"replay-{event_id}"})
    except EventNotFound:
        yield _sse(
            {
                "type": "error",
                "message": f"No replay fixture for {event_id!r}.",
                "retryable": False,
            }
        )
    except Exception as exc:  # noqa: BLE001 - the stream must end cleanly
        # A half-finished SSE stream looks like a hung browser. An error frame
        # followed by `done` lets the UI say what went wrong.
        yield _sse(
            {"type": "error", "message": f"{type(exc).__name__}: {exc}", "retryable": True}
        )
