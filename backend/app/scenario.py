"""FR-WHATIF - bounded scenarios, priced by the loss engine.

Two modes, and the difference between them is the honesty of the demo:

  * timing        apply an hours window to the event's REAL loss timeline.
                  Each region's loss is timed by when the storm track passed
                  closest to it (a quake's by the shock). For Jebi, every
                  allowed window gives one occurrence - which is the truth.
  * hypothetical  cut the timeline at 1-2 analyst-chosen moments inside the
                  event, e.g. between Jebi's two real landfalls. This is NOT
                  what the wording produces; it is labelled hypothetical
                  wherever it appears.

The model never computes money: the engine prices both the base (one
occurrence) and the scenario, and money at stake is a Python subtraction per
party. Every result carries the parameters that produced it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from catsight_agent.store import DataStore
from catsight_agent.tools.hazard import haversine_km
from catsight_agent.tools.loss_engine import (
    CatXLResult,
    LossIncrement,
    apply_cat_xl,
    quantise,
    split_occurrences,
    with_overrides,
)
from catsight_agent.tools.vulnerability import VulnerabilityModel
from ingest.regions_reference import CENTROIDS

__all__ = ["ScenarioRequest", "loss_timeline", "run_scenario", "HOURS_WINDOWS"]

HOURS_WINDOWS = (24, 48, 72, 96, 120, 168, 240)
PARTIES = ("cedent_net_cost", "market_net", "our_net", "total_ceded", "cedent_retention", "our_rip")


def _parse(moment: str) -> datetime:
    return datetime.fromisoformat(moment.replace("Z", "+00:00"))


class ScenarioRequest(BaseModel):
    """The bounded tool input (FR-WHATIF-1). Out-of-range values are refused,
    never clamped."""

    model_config = {"extra": "forbid"}

    treaty_id: str = Field(max_length=16)
    mode: Literal["timing", "hypothetical", "exclusion"]
    hours_window: int | None = None
    split_at: list[str] = Field(default_factory=list, max_length=2)
    #: Exclusion mode: the share of the loss attributed to an excluded cause
    #: (e.g. storm surge). An ASSUMPTION - our data does not separate wind
    #: from surge damage - bounded so no reading can claim more than half.
    excluded_share: float | None = Field(default=None, ge=0, le=0.5)
    excluded_cause: str | None = Field(default=None, max_length=40)
    our_share_override: float | None = Field(default=None, ge=0, le=1)
    retention_override: float | None = Field(default=None, ge=0)

    @field_validator("hours_window")
    @classmethod
    def _market_window(cls, value: int | None) -> int | None:
        if value is not None and value not in HOURS_WINDOWS:
            raise ValueError(f"hours_window must be one of {HOURS_WINDOWS}")
        return value

    @model_validator(mode="after")
    def _mode_has_its_parameter(self) -> "ScenarioRequest":
        if self.mode == "timing" and self.hours_window is None:
            raise ValueError("a timing scenario needs hours_window")
        if self.mode == "hypothetical":
            if not self.split_at:
                raise ValueError("a hypothetical scenario needs 1-2 split_at moments")
            moments = [_parse(m) for m in self.split_at]
            if moments != sorted(set(moments)):
                raise ValueError("split_at moments must be distinct and in time order")
        if self.mode == "exclusion" and self.excluded_share is None:
            raise ValueError("an exclusion scenario needs excluded_share")
        return self


def loss_timeline(event: dict[str, Any], losses_by_region: dict[str, Decimal]) -> list[LossIncrement]:
    """Date each region's loss. Wind: the time the track passed closest to
    the region's centroid. Earthquake: the time of the shock."""
    if event["peril"] == "WS" and event.get("track"):
        points = event["track"]
        increments = []
        for code, loss in losses_by_region.items():
            lat, lon = CENTROIDS[code]
            nearest = min(points, key=lambda p: haversine_km(lat, lon, p["lat"], p["lon"]))
            increments.append(LossIncrement(at=_parse(nearest["t"]), amount=loss))
        return increments
    at = _parse(event["start"])
    return [LossIncrement(at=at, amount=loss) for loss in losses_by_region.values()]


def _priced(result: CatXLResult) -> dict[str, Any]:
    return {
        "occurrence_losses": [str(quantise(x)) for x in result.occurrences],
        "total_ceded": str(quantise(result.total_ceded)),
        "cedent_retention": str(quantise(result.cedent_retention)),
        "cedent_net_cost": str(quantise(result.cedent_net_cost)),
        "market_net": str(quantise(result.market_net)),
        "our_loss": str(quantise(result.our_loss)),
        "our_rip": str(quantise(result.our_rip)),
        "our_net": str(quantise(result.our_net)),
        "layers": [{"layer_no": lr.layer_no, "ceded": str(quantise(lr.ceded)),
                    "burn": str(quantise(lr.burn, 4)), "exhausted": lr.exhausted,
                    "per_occurrence": [str(quantise(x)) for x in lr.per_occurrence]}
                   for lr in result.layers],
    }


def run_scenario(event_id: str, request: ScenarioRequest, *, store: DataStore) -> dict[str, Any]:
    """Price the base reading (one occurrence) and the scenario reading."""
    from app.analysis import _damage_ratios, _layers_of, match_treaties

    event = store.event(event_id)
    book = store.portfolio()
    treaty = book.treaty(request.treaty_id)  # KeyError -> 404 upstream
    if treaty.type != "CAT_XL":
        raise ValueError("occurrence scenarios apply to excess-of-loss treaties, not quota shares")
    decision = next(d for d in match_treaties(book, event) if d.treaty_id == treaty.treaty_id)
    if not decision.matched:
        raise ValueError(f"{treaty.treaty_id} does not respond to this event: {decision.reason}")

    model = VulnerabilityModel.from_dict(store.methodology()["vulnerability"])
    ratios = _damage_ratios(event, model)
    losses: dict[str, Decimal] = {}
    for exposure in book.exposures_for(treaty.cedent_id, event["peril"]):
        if exposure.region_code in decision.regions:
            ratio = Decimal(str(ratios.get(exposure.region_code, 0)))
            losses[exposure.region_code] = losses.get(exposure.region_code, Decimal(0)) + (
                Decimal(str(exposure.tsi_usd)) * ratio)
    timeline = loss_timeline(event, losses)

    layers = [with_overrides(layer, our_share=request.our_share_override,
                             retention=request.retention_override)
              for layer in _layers_of(treaty)]

    if request.mode == "timing":
        occurrences = split_occurrences(timeline, request.hours_window)
        windows = [{"index": o.index, "start": o.window_start.isoformat(),
                    "end": o.window_end.isoformat(), "loss": str(quantise(o.loss))}
                   for o in occurrences]
        scenario_losses = [o.loss for o in occurrences]
        label = (f"Timing scenario: a {request.hours_window}-hour clause applied to the real "
                 f"loss timeline gives {len(occurrences)} occurrence(s).")
    elif request.mode == "exclusion":
        share = Decimal(str(request.excluded_share))
        cause = request.excluded_cause or "the excluded cause"
        total = sum((inc.amount for inc in timeline), Decimal(0))
        scenario_losses = [total * (1 - share)]
        windows = [{"index": 1, "start": None, "end": None, "loss": str(quantise(total * (1 - share)))}]
        label = (f"ASSUMPTION: {share * 100:.0f}% of the loss is attributed to {cause} and "
                 "excluded. The event data does not separate this damage - the share is an "
                 "assumption for discussion, not a finding.")
    else:
        start = _parse(event["start"]) - timedelta(hours=24)
        end = _parse(event["end"]) + timedelta(hours=24)
        cuts = [_parse(m) for m in request.split_at]
        if any(not start < c < end for c in cuts):
            raise ValueError("split_at must fall within the event window (start-24h to end+24h)")
        edges = [datetime.min.replace(tzinfo=cuts[0].tzinfo), *cuts,
                 datetime.max.replace(tzinfo=cuts[0].tzinfo)]
        scenario_losses, windows = [], []
        for i, (lo, hi) in enumerate(zip(edges, edges[1:]), start=1):
            amount = sum((inc.amount for inc in timeline if lo <= inc.at < hi), Decimal(0))
            scenario_losses.append(amount)
            windows.append({"index": i, "start": lo.isoformat() if i > 1 else None,
                            "end": hi.isoformat() if i <= len(cuts) else None,
                            "loss": str(quantise(amount))})
        label = ("HYPOTHETICAL: the timeline is cut at the moment(s) chosen, which the hours "
                 "clause does not produce for this event. For discussion only.")

    base = apply_cat_xl([sum((inc.amount for inc in timeline), Decimal(0))], layers)
    scenario = apply_cat_xl(scenario_losses or [Decimal(0)], layers)
    base_p, scen_p = _priced(base), _priced(scenario)
    if request.mode == "exclusion":
        # The excluded loss leaves the treaty, not the insurer: it is paid in
        # full out of the insurer's own pocket. Without this the insurer would
        # appear to save money when cover is taken away.
        excluded = sum((inc.amount for inc in timeline), Decimal(0)) - scenario_losses[0]
        scen_p["excluded_loss"] = str(quantise(excluded))
        scen_p["cedent_net_cost"] = str(quantise(Decimal(scen_p["cedent_net_cost"]) + excluded))
        base_p["excluded_loss"] = "0.00"
    stake = {k: str(quantise(Decimal(scen_p[k]) - Decimal(base_p[k]))) for k in PARTIES}
    return {
        "event_id": event_id, "treaty_id": treaty.treaty_id, "mode": request.mode,
        "hypothetical": request.mode == "hypothetical", "label": label,
        "params": request.model_dump(exclude_none=True),
        "occurrences": windows, "base": base_p, "scenario": scen_p,
        # Signed, per party: scenario minus base. Computed here, never by a model.
        "money_at_stake": stake,
        "timeline": [{"at": inc.at.isoformat(), "loss": str(quantise(inc.amount))}
                     for inc in sorted(timeline, key=lambda i: i.at)],
    }
