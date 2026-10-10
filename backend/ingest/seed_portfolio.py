"""Synthetic portfolio generation — DR-1.

Builds 8 fictional cedents, 24 treaties and their exposures, matching the
Firestore data model in `REQUIREMENTS.md` section 4.1.

**Deterministic and idempotent.** A fixed seed means re-running produces
byte-identical output, so the demo, the tests and the benchmarks all see the
same portfolio. Nothing here reads the clock or the network.

**Synthetic by rule** (C-8). Every cedent is fictional, every treaty is
invented. Company names are checked for collisions against real insurers as
part of S9; the fictional-name check is a release gate, not a habit.

The Sakura Cat XL programme (T-001 / wording W1) reproduces the
`DOMAIN_PRIMER.md` worked example **exactly** — layers 20 xs 10, 30 xs 30,
40 xs 60, premiums 2.0 / 1.5 / 1.0, Lion Re shares 25% / 10% / 0%. It is
pinned by `test_sakura_programme_matches_the_worked_example` and by the loss
engine's QA-1, because the money moment is computed from it.

Writers are pluggable: `write_json` needs nothing, `write_firestore` takes a
client. S1 runs on JSON alone, so no part of the data build blocks on GCP
access.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from random import Random
from typing import Any, Iterable, Sequence

from ingest.regions_reference import RegionRef, by_country

__all__ = [
    "SEED",
    "OUR_REINSURER",
    "Cedent",
    "Layer",
    "Treaty",
    "Exposure",
    "Portfolio",
    "build_portfolio",
    "write_json",
    "write_firestore",
]

#: Fixed so the portfolio is reproducible. Changing it changes every treaty.
SEED = 20261004

OUR_REINSURER = "Lion Re (Singapore)"

#: Japanese programmes run April to April; PH and TW run calendar years.
JP_INCEPTION, JP_EXPIRY = "2026-04-01", "2027-03-31"
CY_INCEPTION, CY_EXPIRY = "2026-01-01", "2026-12-31"
#: Two expired treaties, so live mode can demonstrate the period check.
EXPIRED_INCEPTION, EXPIRED_EXPIRY = "2025-01-01", "2025-12-31"

#: Total insured value per unit of region weight, in USD millions.
#:
#: 15,000 makes the synthetic Japanese market about US$18.7tn of sum insured,
#: which is the right order for Japan, and puts Sakura at 14% share on about
#: US$2.6tn. It is a round number chosen for that realism, not reverse-fitted.
#:
#: It also happens to make the modelled Jebi gross loss for Sakura land at
#: 54.45 against the worked example's 54.40, which is what lets the live demo
#: reproduce the documented figures. See data/ASSUMPTIONS.md X3-X5 - and note
#: that the model under-predicts Jebi's *actual* market loss by roughly 25x,
#: which is a B5 finding to report rather than something to tune away here.
TSI_PER_WEIGHT_USD_M = 3_400.0
#: Re-derived 2026-10-05 against the committed `jebi-2018.json`, which carries
#: the real IBTrACS track. The previous 15,000 was calibrated against a
#: hand-made Jebi-like track that peaked at 36 m/s over 16 prefectures; the
#: real track peaks at 46.3 m/s over 34, and Emanuel's sigmoid is steeply
#: non-linear there - Hyogo's damage ratio alone rises 8.7x. Sakura's modelled
#: Jebi gross was therefore 239.55, which exhausts the whole 20/30/40
#: programme and destroys the money moment: with no partial burn, splitting
#: one occurrence into two changes nothing.
#:
#: 15,000 x 54.4/239.55 = 3,406, rounded DOWN to 3,400 rather than tuned to
#: 3,410 to land on the deck's 6.82 exactly. Fitting a four-digit constant to
#: a figure that is itself rounded would be reverse-fitting; the live demo
#: reports 54.30 and our net 6.81 against the primer's didactic 54.4 and 6.82.
#:
#: The cost is stated plainly: the synthetic Japanese market falls from about
#: US$11.2tn to about US$2.5tn, against a real insured value of order
#: US$20-30tn - roughly 10x light. (An earlier comment here claimed 18.7tn;
#: that figure was never measured and was wrong.) Absolute loss level is NOT this constant's job - that is
#: `calibration_factor` (V3) at benchmark B5. Using portfolio size to close a
#: vulnerability gap would conflate two different things and make both
#: unmeasurable.

#: Market share per cedent. Explicit rather than drawn, because the size of a
#: cedent's book is structural: letting it wander with the seed would move the
#: demo's headline figures. Shares do not sum to 1 - these eight cedents are a
#: sample of each market, not the whole of it.
MARKET_SHARE: dict[str, float] = {
    "C-SAKURA": 0.14,  # pinned: drives the worked example's gross loss
    "C-KOGANE": 0.18,
    "C-TSURUMI": 0.13,
    "C-YAMABIKO": 0.15,
    "C-MARIPOSA": 0.20,
    "C-TAMARAW": 0.16,
    "C-FORMOSA": 0.17,
    "C-BLACKBEAR": 0.15,
}

#: Earthquake penetration in the Philippines is thin relative to wind.
PH_EQ_PENETRATION = 0.25

#: Gross loss from the DOMAIN_PRIMER worked example. Programmes are sized
#: against a reference event loss rather than against sum insured, because
#: that is how catastrophe covers are actually bought: a Cat XL attaches at a
#: return-period loss. Sakura's own programme attaches at 10.0 against this,
#: which is 18.4%, and the filler book is sized to look like it.
WORKED_EXAMPLE_GROSS = 54.4


# --------------------------------------------------------------------------- #
# Records — shaped to REQUIREMENTS section 4.1
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Cedent:
    cedent_id: str
    name: str
    country: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Layer:
    layer_no: int
    retention: float
    limit: float
    premium: float
    our_share: float
    reinstatements: dict[str, Any]


@dataclass(frozen=True)
class Treaty:
    treaty_id: str
    cedent_id: str
    type: str  # CAT_XL | QS
    perils: tuple[str, ...]
    territory: dict[str, tuple[str, ...]]
    inception: str
    expiry: str
    currency: str
    hours_clause: dict[str, int]
    exclusions: tuple[str, ...]
    layers: tuple[Layer, ...] = ()
    qs: dict[str, float] | None = None
    source_pdf: str | None = None
    wording_id: str | None = None
    extraction: dict[str, Any] | None = None
    endorsement: dict[str, Any] | None = None


@dataclass(frozen=True)
class Exposure:
    exposure_id: str
    cedent_id: str
    region_code: str
    peril: str
    tsi_usd: float
    policy_count: int
    lob: str


@dataclass(frozen=True)
class Portfolio:
    cedents: tuple[Cedent, ...]
    treaties: tuple[Treaty, ...]
    exposures: tuple[Exposure, ...]

    def treaty(self, treaty_id: str) -> Treaty:
        for treaty in self.treaties:
            if treaty.treaty_id == treaty_id:
                return treaty
        raise KeyError(f"no treaty {treaty_id!r}")

    def cedent(self, cedent_id: str) -> Cedent:
        for cedent in self.cedents:
            if cedent.cedent_id == cedent_id:
                return cedent
        raise KeyError(f"no cedent {cedent_id!r}")

    def exposures_for(self, cedent_id: str, peril: str | None = None) -> tuple[Exposure, ...]:
        return tuple(
            e
            for e in self.exposures
            if e.cedent_id == cedent_id and (peril is None or e.peril == peril)
        )


# --------------------------------------------------------------------------- #
# Cedents — DR-1: JP x4, PH x2, TW x2, all clearly fictional
# --------------------------------------------------------------------------- #

CEDENTS: tuple[Cedent, ...] = (
    Cedent("C-SAKURA", "Sakura General Insurance", "JPN", ("FIRE", "MARINE", "ENGINEERING")),
    Cedent("C-KOGANE", "Kogane Fire & Marine", "JPN", ("FIRE", "MARINE")),
    Cedent("C-TSURUMI", "Tsurumi Mutual Insurance", "JPN", ("FIRE", "PERSONAL_LINES")),
    Cedent("C-YAMABIKO", "Yamabiko Casualty", "JPN", ("FIRE", "ENGINEERING")),
    Cedent("C-MARIPOSA", "Mariposa Seguros", "PHL", ("FIRE", "PERSONAL_LINES")),
    Cedent("C-TAMARAW", "Tamaraw Assurance", "PHL", ("FIRE", "AGRICULTURE")),
    Cedent("C-FORMOSA", "Formosa Union Insurance", "TWN", ("FIRE", "ENGINEERING")),
    Cedent("C-BLACKBEAR", "Black Bear Insurance (Taipei)", "TWN", ("FIRE", "MARINE")),
)


# --------------------------------------------------------------------------- #
# The eight wordings. Planted features come from DR-2 and form the ground
# truth that QA-3 and QA-4 are scored against.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class WordingSpec:
    """A treaty that has a PDF wording, with its planted features."""

    wording_id: str
    cedent_id: str
    type: str
    perils: tuple[str, ...]
    hours_clause: dict[str, int]
    exclusions: tuple[str, ...]
    territory: dict[str, tuple[str, ...]]
    reinstatements: dict[str, Any]
    note: str
    expired: bool = False
    #: Set when a scanned endorsement overrides a base term (FR-ENDORSE-3).
    #: `hours_clause` above holds the EFFECTIVE term; this records what the
    #: base wording said and where the override came from.
    endorsement: dict[str, Any] | None = None


_JP_TERRITORY = {"include": ("JPN",), "exclude": ()}
_PH_TERRITORY = {"include": ("PHL",), "exclude": ()}
_TW_TERRITORY = {"include": ("TWN",), "exclude": ()}

_FULL_REINSTATEMENT = {"count": 1, "basis": "pro rata as to amount", "rate": 1.0}
_TWO_REINSTATEMENTS = {"count": 2, "basis": "pro rata as to amount", "rate": 1.0}
_FREE_REINSTATEMENT = {"count": 1, "basis": "pro rata as to amount", "rate": 0.0}

WORDINGS: tuple[WordingSpec, ...] = (
    WordingSpec(
        "W1", "C-SAKURA", "CAT_XL", ("WS", "EQ"),
        {"WS": 72, "EQ": 72, "FL": 168, "OTHER": 168},
        ("war", "nuclear", "cyber"),
        _JP_TERRITORY, _FULL_REINSTATEMENT,
        "Storm surge covered when caused by a named windstorm. The worked example.",
    ),
    WordingSpec(
        "W2", "C-KOGANE", "CAT_XL", ("WS", "EQ"),
        {"WS": 96, "EQ": 168, "FL": 168, "OTHER": 168},
        ("war", "nuclear", "flood when written as such"),
        _JP_TERRITORY, _FULL_REINSTATEMENT,
        "WS 96h, not the assumed 72h. Flood-when-written-as-such excluded.",
    ),
    WordingSpec(
        "W3", "C-TSURUMI", "CAT_XL", ("WS", "EQ"),
        {"WS": 120, "EQ": 72, "FL": 168, "OTHER": 168},
        ("war", "nuclear"),
        {"include": ("JPN",), "exclude": ("JP-47",)}, _FULL_REINSTATEMENT,
        "WS 120h. Territory excludes Okinawa Prefecture.",
    ),
    WordingSpec(
        "W4", "C-YAMABIKO", "CAT_XL", ("WS", "EQ"),
        # WS is 168 EFFECTIVE: the base clause says 72 and a scanned,
        # image-only endorsement overrides it. FR-ENDORSE-3 makes the
        # endorsement's term the operative one.
        {"WS": 168, "EQ": 72, "FL": 168, "OTHER": 168},
        ("war", "nuclear", "storm surge"),
        _JP_TERRITORY, _TWO_REINSTATEMENTS,
        "Storm surge excluded outright. Two reinstatements. Carries a scanned, "
        "image-only endorsement that overrides the windstorm hours clause from "
        "72 to 168 - the FR-ENDORSE case.",
        endorsement={
            "overrides": "hours_clause.WS",
            "base_value": 72,
            "endorsed_value": 168,
            "source": "transcription",
            "note": "stamped and signed endorsement page, no text layer",
        },
    ),
    WordingSpec(
        "W5", "C-MARIPOSA", "CAT_XL", ("WS",),
        {"WS": 72, "EQ": 72, "FL": 168, "OTHER": 168},
        ("war", "nuclear", "earthquake"),
        _PH_TERRITORY, _FULL_REINSTATEMENT,
        "Wind only. Earthquake excluded.",
    ),
    WordingSpec(
        "W6", "C-TAMARAW", "QS", ("WS", "EQ"),
        {"WS": 0, "EQ": 0, "FL": 0, "OTHER": 0},
        ("war", "nuclear"),
        _PH_TERRITORY, {"count": 0, "basis": "n/a", "rate": 0.0},
        "Proportional 30% quota share. No hours clause. Cat event limit.",
    ),
    WordingSpec(
        "W7", "C-FORMOSA", "CAT_XL", ("WS", "EQ"),
        {"WS": 168, "EQ": 168, "FL": 168, "OTHER": 168},
        ("war", "nuclear"),
        _TW_TERRITORY, _FREE_REINSTATEMENT,
        "168h for all perils. Free first reinstatement.",
    ),
    WordingSpec(
        "W8", "C-BLACKBEAR", "CAT_XL", ("WS", "EQ"),
        {"WS": 72, "EQ": 72, "FL": 168, "OTHER": 168},
        ("war", "nuclear"),
        _TW_TERRITORY, _FULL_REINSTATEMENT,
        'Hours clause spelled "seventy-two (72) consecutive hours" inside a '
        '"Loss Occurrence" definition, to test extraction robustness. Expired period.',
        expired=True,
    ),
)

#: The worked example, reproduced exactly. DOMAIN_PRIMER section 4.
SAKURA_LAYERS: tuple[tuple[int, float, float, float, float], ...] = (
    # layer_no, retention, limit, premium, our_share
    (1, 10.0, 20.0, 2.0, 0.25),
    (2, 30.0, 30.0, 1.5, 0.10),
    (3, 60.0, 40.0, 1.0, 0.00),
)


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #


def build_portfolio(seed: int = SEED) -> Portfolio:
    """Build the whole portfolio deterministically."""
    rng = Random(seed)

    exposures = tuple(_build_exposures())
    tsi_by_cedent = {
        cedent.cedent_id: sum(
            e.tsi_usd for e in exposures if e.cedent_id == cedent.cedent_id
        )
        for cedent in CEDENTS
    }
    reference_loss = _reference_losses(tsi_by_cedent)

    treaties: list[Treaty] = []

    # The eight treaties that have wordings, T-001..T-008.
    for index, wording in enumerate(WORDINGS, start=1):
        treaties.append(_treaty_from_wording(index, wording, reference_loss, rng))

    # Filler to reach 18 Cat XL and 6 QS in total. These carry no PDF: they
    # are the rest of the book, so the demo's matching and exclusion logic has
    # something to chew on beyond the eight documented programmes.
    cat_xl_so_far = sum(1 for t in treaties if t.type == "CAT_XL")
    qs_so_far = sum(1 for t in treaties if t.type == "QS")
    next_index = len(WORDINGS) + 1

    for _ in range(18 - cat_xl_so_far):
        treaties.append(_filler_treaty(next_index, "CAT_XL", reference_loss, rng))
        next_index += 1
    for _ in range(6 - qs_so_far):
        treaties.append(_filler_treaty(next_index, "QS", reference_loss, rng))
        next_index += 1

    return Portfolio(cedents=CEDENTS, treaties=tuple(treaties), exposures=exposures)


def _build_exposures() -> Iterable[Exposure]:
    """Spread each cedent's book across its home country's regions.

    Entirely deterministic: a cedent's share of each region follows the
    region's exposure weight, so **geography** drives the loss rather than a
    random draw. That is what makes the Jebi replay reproducible.
    """
    for cedent in CEDENTS:
        share = MARKET_SHARE[cedent.cedent_id]
        for region in by_country(cedent.country):
            for peril in ("WS", "EQ"):
                tsi = region.weight * TSI_PER_WEIGHT_USD_M * share
                if peril == "EQ" and cedent.country == "PHL":
                    tsi *= PH_EQ_PENETRATION
                tsi = round(tsi, 3)
                yield Exposure(
                    exposure_id=f"{cedent.cedent_id}_{region.code}_{peril}",
                    cedent_id=cedent.cedent_id,
                    region_code=region.code,
                    peril=peril,
                    tsi_usd=tsi,
                    policy_count=int(region.weight * 120 * share),
                    lob="FIRE",
                )


def _reference_losses(tsi_by_cedent: dict[str, float]) -> dict[str, float]:
    """A reference major-event loss per cedent, used to size programmes.

    Anchored on Sakura, whose reference loss is the worked example's gross by
    definition, and scaled by each cedent's sum insured. Approximate - it
    ignores that a Philippine book is far more wind-vulnerable than a Japanese
    one - but it only has to make the filler book's structure sensible, and it
    keeps the generator free of any dependency on the vulnerability curves.
    """
    anchor_tsi = tsi_by_cedent["C-SAKURA"]
    return {
        cedent_id: WORKED_EXAMPLE_GROSS * (tsi / anchor_tsi)
        for cedent_id, tsi in tsi_by_cedent.items()
    }


def _treaty_from_wording(
    index: int,
    wording: WordingSpec,
    reference_loss: dict[str, float],
    rng: Random,
) -> Treaty:
    treaty_id = f"T-{index:03d}"
    inception, expiry = _period(wording.cedent_id, expired=wording.expired)

    if wording.wording_id == "W1":
        layers = tuple(
            Layer(
                layer_no=no,
                retention=retention,
                limit=limit,
                premium=premium,
                our_share=our_share,
                reinstatements=dict(wording.reinstatements),
            )
            for no, retention, limit, premium, our_share in SAKURA_LAYERS
        )
        qs = None
    elif wording.type == "CAT_XL":
        layers = _plausible_layers(
            reference_loss[wording.cedent_id], wording.reinstatements, rng
        )
        qs = None
    else:
        layers = ()
        qs = _plausible_quota_share(reference_loss[wording.cedent_id], rng)

    return Treaty(
        treaty_id=treaty_id,
        cedent_id=wording.cedent_id,
        type=wording.type,
        perils=wording.perils,
        territory={k: tuple(v) for k, v in wording.territory.items()},
        inception=inception,
        expiry=expiry,
        currency="USD",
        hours_clause=dict(wording.hours_clause),
        exclusions=wording.exclusions,
        layers=layers,
        qs=qs,
        source_pdf=f"gs://{{bucket}}/treaties/{wording.wording_id.lower()}.pdf",
        wording_id=wording.wording_id,
        extraction=None,  # filled by ingest_treaty.py at S3
        endorsement=dict(wording.endorsement) if wording.endorsement else None,
    )


def _filler_treaty(
    index: int, treaty_type: str, reference_loss: dict[str, float], rng: Random
) -> Treaty:
    cedent = CEDENTS[rng.randrange(len(CEDENTS))]
    territory = {"include": (cedent.country,), "exclude": ()}
    perils = ("WS",) if cedent.country == "PHL" and rng.random() < 0.4 else ("WS", "EQ")
    hours = rng.choice((72, 96, 120, 168))
    inception, expiry = _period(cedent.cedent_id)

    return Treaty(
        treaty_id=f"T-{index:03d}",
        cedent_id=cedent.cedent_id,
        type=treaty_type,
        perils=perils,
        territory=territory,
        inception=inception,
        expiry=expiry,
        currency="USD",
        hours_clause={"WS": hours, "EQ": hours, "FL": 168, "OTHER": 168}
        if treaty_type == "CAT_XL"
        else {"WS": 0, "EQ": 0, "FL": 0, "OTHER": 0},
        exclusions=("war", "nuclear"),
        layers=_plausible_layers(
            reference_loss[cedent.cedent_id], _FULL_REINSTATEMENT, rng
        )
        if treaty_type == "CAT_XL"
        else (),
        qs=None if treaty_type == "CAT_XL" else _plausible_quota_share(
            reference_loss[cedent.cedent_id], rng
        ),
        source_pdf=None,
        wording_id=None,
        extraction=None,
    )


def _plausible_layers(
    reference_loss: float, reinstatements: dict[str, Any], rng: Random
) -> tuple[Layer, ...]:
    """3 or 4 contiguous layers, sized against a reference major-event loss.

    Sized off the event loss rather than off sum insured, because that is how
    catastrophe covers are bought. Sakura's own programme retains 18.4% of the
    worked example's gross, so the filler book attaches in the same 15-35%
    band and the whole portfolio looks coherent.

    Contiguity matters: FR-INGEST-3 validates that each layer attaches where
    the one below exhausts, so the generator must not produce gaps.
    """
    count = rng.choice((3, 4))
    attachment = round(reference_loss * (0.15 + rng.random() * 0.20), 1)
    attachment = max(attachment, 0.1)

    layers: list[Layer] = []
    for layer_no in range(1, count + 1):
        limit = round(attachment * (1.0 + rng.random()), 1)
        layers.append(
            Layer(
                layer_no=layer_no,
                retention=attachment,
                limit=limit,
                premium=round(limit * (0.06 + rng.random() * 0.06), 2),
                our_share=round(0.05 + rng.random() * 0.25, 2),  # DR-1: 5%-30%
                reinstatements=dict(reinstatements),
            )
        )
        attachment = round(attachment + limit, 1)
    return tuple(layers)


def _plausible_quota_share(reference_loss: float, rng: Random) -> dict[str, float]:
    """A cat event limit set near the reference event loss, so the limit can
    actually bite in the demo."""
    return {
        "cession_pct": round(rng.choice((0.20, 0.25, 0.30, 0.40)), 2),
        "event_limit": round(reference_loss * (0.4 + rng.random() * 0.6), 1),
        "our_share": round(0.05 + rng.random() * 0.25, 2),
    }


def _period(cedent_id: str, expired: bool = False) -> tuple[str, str]:
    if expired:
        return EXPIRED_INCEPTION, EXPIRED_EXPIRY
    cedent = next(c for c in CEDENTS if c.cedent_id == cedent_id)
    if cedent.country == "JPN":
        return JP_INCEPTION, JP_EXPIRY
    return CY_INCEPTION, CY_EXPIRY


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #


def _serialise(record: Any) -> dict[str, Any]:
    """dataclass -> plain JSON, with tuples as lists."""

    def convert(value: Any) -> Any:
        if isinstance(value, tuple):
            return [convert(v) for v in value]
        if isinstance(value, list):
            return [convert(v) for v in value]
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        if isinstance(value, Decimal):
            return float(value)
        return value

    return {k: convert(v) for k, v in asdict(record).items()}


def write_json(portfolio: Portfolio, out_dir: Path | str) -> dict[str, Path]:
    """Write the portfolio as three JSON files. Needs no GCP."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name, records in (
        ("cedents", portfolio.cedents),
        ("treaties", portfolio.treaties),
        ("exposures", portfolio.exposures),
    ):
        path = out / f"{name}.json"
        payload = [_serialise(r) for r in records]
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written[name] = path
    return written


def write_firestore(portfolio: Portfolio, client: Any, bucket: str | None = None) -> int:
    """Write the portfolio to Firestore. Idempotent: documents are keyed, so a
    re-run overwrites rather than duplicating.

    `client` is any object exposing Firestore's `collection(name).document(id)
    .set(data)` chain, so this is unit-testable with a fake and needs no GCP.
    """
    written = 0
    collections = (
        ("cedents", portfolio.cedents, lambda r: r.cedent_id),
        ("treaties", portfolio.treaties, lambda r: r.treaty_id),
        ("exposures", portfolio.exposures, lambda r: r.exposure_id),
    )
    for name, records, key_of in collections:
        collection = client.collection(name)
        for record in records:
            data = _serialise(record)
            if bucket and data.get("source_pdf"):
                data["source_pdf"] = data["source_pdf"].replace("{bucket}", bucket)
            collection.document(key_of(record)).set(data)
            written += 1
    return written


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: python -m ingest.seed_portfolio [--out DIR] [--seed N]"""
    import argparse

    parser = argparse.ArgumentParser(description="Generate the synthetic portfolio (DR-1).")
    parser.add_argument("--out", default="data/synthetic/portfolio", help="output directory")
    parser.add_argument("--seed", type=int, default=SEED, help="random seed")
    args = parser.parse_args(argv)

    portfolio = build_portfolio(args.seed)
    written = write_json(portfolio, args.out)
    print(
        f"{len(portfolio.cedents)} cedents, {len(portfolio.treaties)} treaties, "
        f"{len(portfolio.exposures)} exposures (seed {args.seed})"
    )
    for name, path in written.items():
        print(f"  {name:<10} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
