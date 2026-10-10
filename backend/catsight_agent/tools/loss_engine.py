"""Deterministic loss engine — FR-LOSS.

The project's hard rule: **the LLM never calculates.** Every figure that a
report, an agent or a slide quotes originates in this module. It is pure — no
I/O, no network, no Firestore, no model calls — so it is cheap to test
exhaustively and impossible to make non-deterministic. Agents reach it only
through typed tools.

Requirement coverage:
  FR-LOSS-1  gross loss from exposure x damage ratio
  FR-LOSS-2  Cat XL per-layer allocation, burn, exhaustion
  FR-LOSS-3  reinstatements and reinstatement premium (RIP)
  FR-LOSS-4  quota share
  FR-LOSS-5  multiple occurrences, split scenarios
  FR-LOSS-6  pure, typed, no I/O

Reinstatement-premium convention (FR-LOSS-3, clarified in REQUIREMENTS_V2):

    RIP = (limit eroded by THAT occurrence / limit) x premium x rate,
    charged per occurrence, pro rata as to amount, while reinstatement
    capacity remains.

Erosion beyond the available reinstatement capacity is still paid if aggregate
cover allows, but restores nothing and therefore attracts no RIP. Reinstatement
applies to partial erosion, not only to exhaustion.

This convention is not a preference: it is the only one that reproduces the
one-event figures already published in docs/DOMAIN_PRIMER.md section 4
(our RIP 0.622, net 6.82). The derivation, and the two bases it rules out, are
in docs/MONEY_MOMENT.md section 4.

Money is `decimal.Decimal`, in the portfolio's currency unit (the synthetic
portfolio uses USD millions), quantised to MONEY_DP at every boundary and
rounded half-up — the financial convention, not Python's default banker's
rounding.

Decimal rather than float is a deliberate choice, and it is load-bearing. In
binary floating point the split case's `7.85 - 0.525` evaluates to
7.324999999999999, which rounds to 7.32 and not to the correct 7.33. A cent of
drift between the engine, the report and the deck would land on exactly the
claim this project makes about its own numbers. FR-LOSS acceptance requires an
*exact* match on every reference figure, and only Decimal delivers that.

Damage ratios and intensities stay float — they are physical quantities from
published vulnerability curves, not money — and are converted on the way in.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Iterable, Mapping, Sequence, Union

__all__ = [
    "Money",
    "Numeric",
    "MONEY_DP",
    "Layer",
    "QuotaShare",
    "ExposureSlice",
    "LossIncrement",
    "Occurrence",
    "LayerResult",
    "CatXLResult",
    "QuotaShareResult",
    "ScenarioBounds",
    "gross_loss",
    "allocate_layer",
    "apply_cat_xl",
    "apply_quota_share",
    "split_occurrences",
    "quantise",
]

Money = Decimal
#: Anything the engine will accept as a money or rate input.
Numeric = Union[Decimal, float, int, str]

#: Internal money precision. Six places on USD millions is sub-dollar, far
#: finer than any figure reported, and keeps division residues from
#: accumulating across occurrences.
MONEY_DP = 6
_MONEY_Q = Decimal(1).scaleb(-MONEY_DP)


def _dec(value: Numeric) -> Decimal:
    """Convert to Decimal without inheriting a float's binary error.

    `Decimal(str(0.1))` is exactly 0.1; `Decimal(0.1)` is not.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _money(value: Numeric) -> Money:
    """Normalise to engine money precision, rounding half-up."""
    return _dec(value).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)


def quantise(value: Numeric, dp: int = 2) -> Money:
    """Round for display or assertion, half-up.

    Python's built-in `round` uses banker's rounding, which sends a true 7.325
    to 7.32. Money rounds half away from zero.
    """
    return _dec(value).quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Layer:
    """One Cat XL layer, e.g. "20 xs 10" is limit=20, retention=10.

    Money and rate fields accept float, int, str or Decimal and are normalised
    to Decimal on construction, so callers never have to think about it.
    """

    layer_no: int
    retention: Money
    limit: Money
    premium: Money = Decimal(0)
    our_share: Decimal = Decimal(0)
    reinstatements: int = 0
    reinstatement_rate: Decimal = Decimal(1)  # 1 = 100%, 0 = free reinstatement

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "retention", _money(self.retention))
        set_(self, "limit", _money(self.limit))
        set_(self, "premium", _money(self.premium))
        set_(self, "our_share", _dec(self.our_share))
        set_(self, "reinstatement_rate", _dec(self.reinstatement_rate))

        if self.limit <= 0:
            raise ValueError(f"layer {self.layer_no}: limit must be > 0, got {self.limit}")
        if self.retention < 0:
            raise ValueError(f"layer {self.layer_no}: retention must be >= 0, got {self.retention}")
        if self.premium < 0:
            raise ValueError(f"layer {self.layer_no}: premium must be >= 0, got {self.premium}")
        if not 0 <= self.our_share <= 1:
            raise ValueError(f"layer {self.layer_no}: our_share must be in [0,1], got {self.our_share}")
        if self.reinstatements < 0:
            raise ValueError(f"layer {self.layer_no}: reinstatements must be >= 0")
        if self.reinstatement_rate < 0:
            raise ValueError(f"layer {self.layer_no}: reinstatement_rate must be >= 0")

    @property
    def aggregate_cover(self) -> Money:
        """Most this layer can ever pay: the limit plus every reinstatement."""
        return _money(self.limit * (1 + self.reinstatements))

    @property
    def exhaustion_point(self) -> Money:
        """Gross loss at which this layer is fully eroded in one occurrence."""
        return _money(self.retention + self.limit)


@dataclass(frozen=True)
class QuotaShare:
    """Proportional treaty (FR-LOSS-4)."""

    cession_pct: Decimal
    our_share: Decimal = Decimal(0)
    event_limit: Money | None = None

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "cession_pct", _dec(self.cession_pct))
        set_(self, "our_share", _dec(self.our_share))
        if self.event_limit is not None:
            set_(self, "event_limit", _money(self.event_limit))

        if not 0 <= self.cession_pct <= 1:
            raise ValueError(f"cession_pct must be in [0,1], got {self.cession_pct}")
        if not 0 <= self.our_share <= 1:
            raise ValueError(f"our_share must be in [0,1], got {self.our_share}")
        if self.event_limit is not None and self.event_limit < 0:
            raise ValueError("event_limit must be >= 0 when set")


@dataclass(frozen=True)
class ExposureSlice:
    """Total sum insured for one cedent x region x peril (FR-LOSS-1)."""

    region_code: str
    peril: str
    tsi_usd: Money

    def __post_init__(self) -> None:
        object.__setattr__(self, "tsi_usd", _money(self.tsi_usd))
        if self.tsi_usd < 0:
            raise ValueError(f"{self.region_code}/{self.peril}: tsi_usd must be >= 0")


@dataclass(frozen=True)
class LossIncrement:
    """A dated slice of loss, used to split an event into occurrences."""

    at: datetime
    amount: Money

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _money(self.amount))
        if self.amount < 0:
            raise ValueError("loss increment amount must be >= 0")


@dataclass(frozen=True)
class Occurrence:
    """One loss occurrence: a non-overlapping hours-clause window."""

    index: int
    window_start: datetime
    window_end: datetime
    loss: Money


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LayerResult:
    layer_no: int
    ceded: Money
    burn: Decimal  # ceded / limit; exceeds 1 when reinstatements are used
    exhausted: bool
    our_loss: Money
    rip: Money  # reinstatement premium, 100% basis
    our_rip: Money
    reinstated: Money  # limit restored across all occurrences
    per_occurrence: tuple[Money, ...]


@dataclass(frozen=True)
class CatXLResult:
    """Per-party view. Section 4.4 of MONEY_MOMENT is the reason all of these
    are returned together rather than derived by a caller."""

    gross: Money
    occurrences: tuple[Money, ...]
    layers: tuple[LayerResult, ...]
    total_ceded: Money
    cedent_retention: Money
    total_rip: Money
    our_loss: Money
    our_rip: Money
    our_net: Money
    cedent_net_cost: Money  # retention + RIP payable
    market_net: Money  # recoveries received by all reinsurers, net of RIP

    def layer(self, layer_no: int) -> LayerResult:
        for lr in self.layers:
            if lr.layer_no == layer_no:
                return lr
        raise KeyError(f"no layer {layer_no} in result")


@dataclass(frozen=True)
class QuotaShareResult:
    gross: Money
    ceded: Money
    our_loss: Money
    capped: bool


# --------------------------------------------------------------------------- #
# FR-LOSS-1 gross loss
# --------------------------------------------------------------------------- #


def gross_loss(
    exposures: Iterable[ExposureSlice],
    damage_ratio: Callable[[ExposureSlice], Numeric] | Mapping[str, Numeric],
) -> Money:
    """Sum of tsi_usd x damage_ratio over the exposure slices in scope.

    `damage_ratio` is injected — either a callable or a mapping keyed by region
    code — so the engine stays pure and the acceptance tests can use the
    worked example's ratios without pulling in the vulnerability curves.
    """
    if callable(damage_ratio):
        ratio_of = damage_ratio
    else:
        mapping = damage_ratio

        def ratio_of(slice_: ExposureSlice) -> Numeric:
            return mapping.get(slice_.region_code, 0)

    total = Decimal(0)
    for slice_ in exposures:
        ratio = _dec(ratio_of(slice_))
        if not 0 <= ratio <= 1:
            raise ValueError(
                f"{slice_.region_code}/{slice_.peril}: damage ratio must be in [0,1], got {ratio}"
            )
        total += slice_.tsi_usd * ratio
    return _money(total)


# --------------------------------------------------------------------------- #
# FR-LOSS-2 / FR-LOSS-3 Cat XL
# --------------------------------------------------------------------------- #


def allocate_layer(layer: Layer, occurrence_losses: Sequence[Numeric]) -> LayerResult:
    """Allocate a sequence of occurrence losses to one layer.

    Walks the occurrences in chronological order, maintaining the available
    limit and the remaining reinstatement capacity. See the module docstring
    for the RIP convention.
    """
    if not occurrence_losses:
        raise ValueError("at least one occurrence loss is required")
    losses = [_money(loss) for loss in occurrence_losses]
    for loss in losses:
        if loss < 0:
            raise ValueError("occurrence loss must be >= 0")

    zero = Decimal(0)
    available = layer.limit
    capacity = layer.limit * layer.reinstatements
    ceded_total = zero
    rip_total = zero
    reinstated_total = zero
    per_occurrence: list[Money] = []

    for loss in losses:
        ceded = min(max(loss - layer.retention, zero), available)
        available -= ceded
        ceded_total += ceded
        per_occurrence.append(_money(ceded))

        # Reinstatement: restore what this occurrence eroded, while capacity
        # remains. Erosion past capacity is paid but restores nothing, so it
        # attracts no RIP.
        if ceded > zero and capacity > zero:
            restore = min(ceded, capacity)
            available += restore
            capacity -= restore
            reinstated_total += restore
            rip_total += (restore / layer.limit) * layer.premium * layer.reinstatement_rate

    return LayerResult(
        layer_no=layer.layer_no,
        ceded=_money(ceded_total),
        burn=_money(ceded_total / layer.limit),
        exhausted=ceded_total >= layer.limit,
        our_loss=_money(ceded_total * layer.our_share),
        rip=_money(rip_total),
        our_rip=_money(rip_total * layer.our_share),
        reinstated=_money(reinstated_total),
        per_occurrence=tuple(per_occurrence),
    )


def apply_cat_xl(
    occurrence_losses: Sequence[Numeric],
    layers: Sequence[Layer],
) -> CatXLResult:
    """Allocate occurrence losses across a Cat XL programme.

    Returns the full per-party view: the cedent's position, the market's, and
    ours. RIP flows from cedent to reinsurer, so it is a cost to the cedent and
    a receipt to the reinsurer — which is why `our_net` subtracts it.
    """
    if not layers:
        raise ValueError("at least one layer is required")
    seen: set[int] = set()
    for layer in layers:
        if layer.layer_no in seen:
            raise ValueError(f"duplicate layer_no {layer.layer_no}")
        seen.add(layer.layer_no)

    losses = [_money(loss) for loss in occurrence_losses]
    ordered = sorted(layers, key=lambda la: la.retention)
    results = tuple(allocate_layer(layer, losses) for layer in ordered)

    gross = _money(sum(losses, Decimal(0)))
    total_ceded = _money(sum((r.ceded for r in results), Decimal(0)))
    total_rip = _money(sum((r.rip for r in results), Decimal(0)))
    our_loss = _money(sum((r.our_loss for r in results), Decimal(0)))
    our_rip = _money(sum((r.our_rip for r in results), Decimal(0)))
    retention = _money(gross - total_ceded)

    return CatXLResult(
        gross=gross,
        occurrences=tuple(losses),
        layers=results,
        total_ceded=total_ceded,
        cedent_retention=retention,
        total_rip=total_rip,
        our_loss=our_loss,
        our_rip=our_rip,
        our_net=_money(our_loss - our_rip),
        cedent_net_cost=_money(retention + total_rip),
        market_net=_money(total_ceded - total_rip),
    )


# --------------------------------------------------------------------------- #
# FR-LOSS-4 quota share
# --------------------------------------------------------------------------- #


def apply_quota_share(gross: Numeric, qs: QuotaShare) -> QuotaShareResult:
    """ceded = min(gross x cession_pct, event_limit); our_loss = ceded x our_share."""
    gross_m = _money(gross)
    if gross_m < 0:
        raise ValueError("gross must be >= 0")
    uncapped = gross_m * qs.cession_pct
    if qs.event_limit is not None and uncapped > qs.event_limit:
        ceded = qs.event_limit
        capped = True
    else:
        ceded = uncapped
        capped = False
    return QuotaShareResult(
        gross=gross_m,
        ceded=_money(ceded),
        our_loss=_money(ceded * qs.our_share),
        capped=capped,
    )


# --------------------------------------------------------------------------- #
# FR-LOSS-5 multiple occurrences
# --------------------------------------------------------------------------- #


def split_occurrences(
    timeline: Sequence[LossIncrement],
    hours_window: int,
) -> tuple[Occurrence, ...]:
    """Split a dated loss timeline into non-overlapping hours-clause windows.

    Each window opens at the first loss not yet assigned and runs for
    `hours_window` hours. A loss belongs to the window in which it *first*
    occurs — the reading the English Court of Appeal took in UnipolSai v Covea
    (2024), where "occur" means "first occur". Windows cannot overlap, which
    falls out of opening each one at the first unassigned loss.

    A single returned occurrence means the hours clause does not split the
    event.
    """
    if hours_window <= 0:
        raise ValueError("hours_window must be > 0")
    if not timeline:
        raise ValueError("timeline must not be empty")

    ordered = sorted(timeline, key=lambda inc: inc.at)
    occurrences: list[Occurrence] = []
    window_start: datetime | None = None
    window_end: datetime | None = None
    running = Decimal(0)

    for inc in ordered:
        if window_start is None:
            window_start = inc.at
            window_end = window_start + timedelta(hours=hours_window)
            running = Decimal(0)
        elif inc.at >= window_end:  # type: ignore[operator]
            occurrences.append(
                Occurrence(
                    index=len(occurrences) + 1,
                    window_start=window_start,
                    window_end=window_end,  # type: ignore[arg-type]
                    loss=_money(running),
                )
            )
            window_start = inc.at
            window_end = window_start + timedelta(hours=hours_window)
            running = Decimal(0)
        running += inc.amount

    occurrences.append(
        Occurrence(
            index=len(occurrences) + 1,
            window_start=window_start,  # type: ignore[arg-type]
            window_end=window_end,  # type: ignore[arg-type]
            loss=_money(running),
        )
    )
    return tuple(occurrences)


# --------------------------------------------------------------------------- #
# Scenario bounds — the schema the typed agent tool enforces (FR-WHATIF-1)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ScenarioBounds:
    """Bounds the LLM-facing tool must enforce. The model selects parameters;
    out-of-range values are refused, never silently clamped."""

    hours_windows: tuple[int, ...] = (24, 48, 72, 96, 120, 168, 240)
    max_occurrences: int = 3
    track_offset_km: tuple[float, float] = (-200.0, 200.0)
    retention_multiple: Numeric = 10

    def validate_hours_window(self, hours: int) -> None:
        if hours not in self.hours_windows:
            raise ValueError(
                f"hours_window must be one of {self.hours_windows}, got {hours}"
            )

    def validate_occurrences(self, count: int) -> None:
        if not 1 <= count <= self.max_occurrences:
            raise ValueError(
                f"occurrences must be between 1 and {self.max_occurrences}, got {count}"
            )

    def validate_track_offset(self, km: Numeric) -> None:
        lo, hi = (_dec(v) for v in self.track_offset_km)
        km = _dec(km)
        if not lo <= km <= hi:
            raise ValueError(f"track_offset_km must be in [{lo},{hi}], got {km}")

    def validate_retention_override(self, override: Numeric, base_retention: Numeric) -> None:
        override = _dec(override)
        base_retention = _dec(base_retention)
        if override < 0:
            raise ValueError("retention_override must be >= 0")
        ceiling = base_retention * _dec(self.retention_multiple)
        if base_retention > 0 and override > ceiling:
            raise ValueError(
                f"retention_override {override} exceeds {self.retention_multiple}x "
                f"base retention ({ceiling})"
            )


def with_overrides(
    layer: Layer,
    *,
    our_share: Numeric | None = None,
    retention: Numeric | None = None,
    bounds: ScenarioBounds | None = None,
) -> Layer:
    """Return a copy of `layer` with bounded overrides applied (FR-WHATIF-1)."""
    bounds = bounds or ScenarioBounds()
    if retention is not None:
        bounds.validate_retention_override(retention, layer.retention)
    if our_share is not None and not 0 <= _dec(our_share) <= 1:
        raise ValueError("our_share_override must be in [0,1]")
    return replace(
        layer,
        retention=layer.retention if retention is None else retention,
        our_share=layer.our_share if our_share is None else our_share,
    )
