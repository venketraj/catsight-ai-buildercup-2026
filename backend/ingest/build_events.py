"""Event replay files — DR-3.

Turns public hazard data into the small per-event JSON files the replay mode
loads: `data/events/{event_id}.json`.

**Cache-first.** The large source files live in `backend/data/raw/`, which is
git-ignored, and are never fetched implicitly. If a source is missing the
build fails with the exact URL and target path rather than silently producing
a half-event. `--fetch` downloads what is missing, explicitly.

  ibtracs.WP.list.v04r01.csv   114 MB   typhoon tracks, SID-filtered
  noto_shakemap_grid.xml       7.6 MB   earthquake MMI grid

## duration_h is the *damaging* window, not the track life

This is the most consequential decision in the module. `FR-WORD-1` compares
`event.duration_h` against the treaty's hours clause and flags a possible
multiple-occurrence split when the duration is longer.

Jebi's IBTrACS track spans **213 hours** from genesis to dissipation. If that
were the duration, every event would breach every hours clause and the
headline flag would fire on all of them, meaninglessly.

So the duration is the span of track points during which **at least one
in-scope region experiences wind at or above the damage threshold** (25.7 m/s,
the Emanuel curve's own threshold - below it the damage ratio is zero by
construction, so those hours cannot contribute loss).

That gives Jebi 9 h, Haiyan 12 h and Hagibis 27 h: all comfortably inside a
72-hour clause, which is what the DOMAIN_PRIMER says of Jebi. The hours-clause
flag therefore fires on a genuine long-duration event rather than on every
replay.

For an earthquake the mainshock is instantaneous, so `duration_h` is 0 and no
hours-clause split is possible. A real aftershock sequence would extend it;
that is noted in `data/ASSUMPTIONS.md` and not modelled.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from catsight_agent.tools.hazard import (
    Region,
    TrackPoint,
    haversine_km,
    mmi_at,
    parse_shakemap_grid,
    wind_at,
    wind_at_point,
)
from catsight_agent.tools.vulnerability import VulnerabilityModel
from ingest.regions_reference import as_hazard_regions

__all__ = [
    "SourceMissing",
    "EventSpec",
    "EVENTS",
    "IBTRACS_FILE",
    "IBTRACS_URL",
    "SHAKEMAP_FILE",
    "USGS_EVENT_API",
    "DAMAGE_THRESHOLD_MS",
    "damaging_window",
    "build_wind_event",
    "build_quake_event",
    "build_all",
    "fetch_sources",
    "main",
]

IBTRACS_FILE = "ibtracs.WP.list.v04r01.csv"
IBTRACS_URL = (
    "https://www.ncei.noaa.gov/data/"
    "international-best-track-archive-for-climate-stewardship-ibtracs/"
    "v04r01/access/csv/" + IBTRACS_FILE
)
SHAKEMAP_FILE = "noto_shakemap_grid.xml"
USGS_EVENT_API = "https://earthquake.usgs.gov/fdsnws/event/1/query"

#: Wind at or above which the Emanuel curve produces non-zero damage. Below
#: it, an hour of track cannot contribute loss, so it cannot lengthen a loss
#: occurrence either.
DAMAGE_THRESHOLD_MS = 25.7


class SourceMissing(FileNotFoundError):
    """A required raw source is not cached. Carries how to get it."""

    def __init__(self, path: Path, url: str, size_hint: str) -> None:
        self.path, self.url = path, url
        super().__init__(
            f"missing source data: {path}\n"
            f"  download ({size_hint}):\n"
            f"    curl -o {path} {url}\n"
            f"  or run: python -m ingest.build_events --fetch"
        )


# --------------------------------------------------------------------------- #
# Event specifications
#
# Facts and reference losses are quoted from RESEARCH_FINDINGS section D8,
# which marks each as verified [V] or third-party [3P]. They exist for
# credibility and for the B5 back-test ONLY, and are never model inputs.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EventSpec:
    event_id: str
    name: str
    peril: str  # WS | EQ
    sid: str | None = None  # IBTrACS storm identifier
    usgs_id: str | None = None
    facts: tuple[dict[str, Any], ...] = ()
    reference_losses: tuple[dict[str, Any], ...] = ()
    attribution: tuple[str, ...] = ()


_IBTRACS_ATTRIBUTION = (
    "NOAA IBTrACS v04r01 (Knapp et al. 2010), doi:10.25921/82ty-9e16",
)
_USGS_ATTRIBUTION = ("U.S. Geological Survey ShakeMap, public domain",)
_JMA_ATTRIBUTION = ("Source: Japan Meteorological Agency website",)

EVENTS: tuple[EventSpec, ...] = (
    EventSpec(
        event_id="jebi-2018",
        name="Typhoon Jebi",
        peril="WS",
        sid="2018239N11161",
        facts=(
            {
                "text": "Landfall about 12:00 JST on 4 September in southern "
                "Tokushima, with a second landfall near Kobe about 14:00.",
                "source": "JMA",
                "url": "https://www.jma.go.jp/jma/indexe.html",
            },
            {
                "text": "Kansai International Airport recorded a gust of 58.1 m/s.",
                "source": "JMA",
                "url": "https://www.jma.go.jp/jma/indexe.html",
            },
            {
                "text": "Osaka recorded a tide of 329 cm, a record for the station.",
                "source": "JMA",
                "url": "https://www.jma.go.jp/jma/indexe.html",
            },
        ),
        reference_losses=(
            {
                "source": "GIAJ",
                "value": "857,284 claims, JPY 1,067.8bn",
                "as_of": "2019-03-31",
                "note": "the largest ever paid for a Japanese typhoon",
                "url": "https://www.sonpo.or.jp/en/",
            },
            {
                "source": "Swiss Re (third party)",
                "value": "about USD 13bn after loss creep",
                "as_of": None,
                "note": "grew from an early USD 3-5bn, roughly 3x",
                "url": None,
            },
        ),
        attribution=_IBTRACS_ATTRIBUTION + _JMA_ATTRIBUTION,
    ),
    EventSpec(
        event_id="hagibis-2019",
        name="Typhoon Hagibis",
        peril="WS",
        sid="2019278N16165",
        facts=(
            {
                "text": "Landfall just before 19:00 JST on 12 October on the Izu "
                "Peninsula.",
                "source": "JMA",
                "url": "https://www.jma.go.jp/jma/indexe.html",
            },
            {
                "text": "Hakone recorded about 1,000 mm of rainfall.",
                "source": "JMA",
                "url": "https://www.jma.go.jp/jma/indexe.html",
            },
        ),
        reference_losses=(
            {
                "source": "GIAJ",
                "value": "264,359 claims, JPY 395.9bn",
                "as_of": "2019-12-09",
                "note": "a later third-party figure gives JPY 582.6bn",
                "url": "https://www.sonpo.or.jp/en/",
            },
        ),
        attribution=_IBTRACS_ATTRIBUTION + _JMA_ATTRIBUTION,
    ),
    EventSpec(
        event_id="haiyan-2013",
        name="Typhoon Haiyan",
        peril="WS",
        sid="2013306N07162",
        facts=(
            {
                "text": "Landfall 04:40 PHT on 8 November at Guiuan, Eastern "
                "Samar, with sustained winds about 235 km/h.",
                "source": "Third party",
                "url": None,
            },
        ),
        reference_losses=(
            {
                "source": "Swiss Re sigma (third party)",
                "value": "about USD 1.5bn insured of about USD 12.5bn economic",
                "as_of": None,
                "note": "an insurance protection gap of roughly 88%",
                "url": None,
            },
        ),
        attribution=_IBTRACS_ATTRIBUTION,
    ),
    EventSpec(
        event_id="noto-2024",
        name="Noto Peninsula Earthquake",
        peril="EQ",
        usgs_id="us6000m0xl",
        facts=(
            {
                "text": "Mww 7.5 at 07:10:09 UTC on 1 January 2024, 37.487N "
                "137.271E, depth 10 km.",
                "source": "USGS",
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000m0xl",
            },
            {
                "text": "JMA magnitude 7.6, maximum seismic intensity shindo 7.",
                "source": "JMA",
                "url": "https://www.jma.go.jp/jma/indexe.html",
            },
        ),
        reference_losses=(
            {
                "source": "Japan Earthquake Reinsurance",
                "value": "119,913 claims, JPY 108.0bn",
                "as_of": "2026-03-31",
                "note": "residential earthquake only",
                "url": "https://www.nihonjishin.co.jp/",
            },
            {
                "source": "Moody's RMS",
                "value": "JPY 435-870bn insured",
                "as_of": None,
                "note": "including commercial lines",
                "url": None,
            },
        ),
        attribution=_USGS_ATTRIBUTION + _JMA_ATTRIBUTION,
    ),
)


def event_spec(event_id: str) -> EventSpec:
    for spec in EVENTS:
        if spec.event_id == event_id:
            return spec
    raise KeyError(f"no event {event_id!r}; have {[e.event_id for e in EVENTS]}")


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def _require(path: Path, url: str, size_hint: str) -> Path:
    if not path.exists() or path.stat().st_size == 0:
        raise SourceMissing(path, url, size_hint)
    return path


def fetch_sources(raw_dir: Path, *, only: str | None = None) -> dict[str, Path]:
    """Download whatever is missing. Explicit, never implicit.

    The ShakeMap grid URL carries a product-version timestamp, so it is
    resolved through the USGS event API rather than hardcoded - a pinned URL
    goes stale the next time the ShakeMap is revised.
    """
    import urllib.request

    raw_dir.mkdir(parents=True, exist_ok=True)
    fetched: dict[str, Path] = {}

    if only in (None, "ibtracs"):
        target = raw_dir / IBTRACS_FILE
        if not target.exists() or target.stat().st_size == 0:
            urllib.request.urlretrieve(IBTRACS_URL, target)
        fetched["ibtracs"] = target

    if only in (None, "shakemap"):
        target = raw_dir / SHAKEMAP_FILE
        if not target.exists() or target.stat().st_size == 0:
            spec = event_spec("noto-2024")
            query = f"{USGS_EVENT_API}?eventid={spec.usgs_id}&format=geojson"
            with urllib.request.urlopen(query) as response:
                payload = json.loads(response.read().decode("utf-8"))
            shakemap = payload["properties"]["products"]["shakemap"][0]
            grid_url = next(
                (
                    content["url"]
                    for name, content in shakemap["contents"].items()
                    if name.endswith("grid.xml")
                ),
                None,
            )
            if grid_url is None:
                # A bare StopIteration here would be baffling. Say what was
                # actually available, so a renamed content key is obvious.
                raise ValueError(
                    "no grid.xml in the USGS ShakeMap product; available "
                    f"contents: {sorted(shakemap['contents'])}"
                )
            urllib.request.urlretrieve(grid_url, target)
        fetched["shakemap"] = target

    return fetched


# --------------------------------------------------------------------------- #
# The damaging window
# --------------------------------------------------------------------------- #


def damaging_window(
    track: Sequence[TrackPoint],
    regions: Sequence[Region],
    threshold_ms: float = DAMAGE_THRESHOLD_MS,
) -> tuple[datetime, datetime, float, int]:
    """(start, end, duration_h, point_count) of the loss-producing window.

    See the module docstring: this is deliberately not the track's lifetime.
    """
    damaging = [
        point
        for point in track
        if any(
            wind_at_point(point, haversine_km(r.lat, r.lon, point.lat, point.lon))
            >= threshold_ms
            for r in regions
        )
    ]
    if not damaging:
        # The storm never reached a covered region at damaging strength. Fall
        # back to the track's own span so the event still describes itself,
        # with a duration of zero so no hours clause is triggered.
        return track[0].t, track[-1].t, 0.0, 0

    start, end = damaging[0].t, damaging[-1].t
    hours = (end - start).total_seconds() / 3600
    return start, end, round(hours, 1), len(damaging)


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _region_rows_wind(
    track: Sequence[TrackPoint], regions: Sequence[Region], vuln: VulnerabilityModel
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for region in regions:
        wind = wind_at(region.lat, region.lon, track)
        if wind <= 0:
            continue
        rows.append(
            {
                "code": region.code,
                "name": region.name,
                "country": region.country,
                "intensity": {"wind_ms": round(wind, 2)},
                "band": vuln.wind_band(wind),
                "intensity_source": "computed",
            }
        )
    rows.sort(key=lambda r: -r["intensity"]["wind_ms"])
    return rows


def build_wind_event(
    spec: EventSpec,
    csv_text: str,
    regions: Sequence[Region],
    vuln: VulnerabilityModel,
) -> dict[str, Any]:
    """Build a typhoon replay file from the IBTrACS CSV."""
    from ingest.ibtracs import track_for_sid

    if not spec.sid:
        raise ValueError(f"{spec.event_id}: a wind event needs an IBTrACS SID")
    track = track_for_sid(csv_text, spec.sid)
    start, end, duration_h, damaging_points = damaging_window(track, regions)
    rows = _region_rows_wind(track, regions, vuln)
    peak = max(track, key=lambda p: p.vmax_ms)

    return {
        "event_id": spec.event_id,
        "name": spec.name,
        "peril": spec.peril,
        "sid": spec.sid,
        "start": _iso(start),
        "end": _iso(end),
        "duration_h": duration_h,
        "duration_basis": (
            "span of track points at which at least one in-scope region "
            f"experiences wind of {DAMAGE_THRESHOLD_MS} m/s or more; not the "
            "track lifetime"
        ),
        "track_start": _iso(track[0].t),
        "track_end": _iso(track[-1].t),
        "damaging_points": damaging_points,
        "peak": {
            "t": _iso(peak.t),
            "lat": peak.lat,
            "lon": peak.lon,
            "vmax_ms": round(peak.vmax_ms, 2),
        },
        "track": [
            {
                "t": _iso(p.t),
                "lat": p.lat,
                "lon": p.lon,
                "vmax_ms": round(p.vmax_ms, 2),
                "rmw_km": round(p.rmw_km, 1),
                "r34_km": round(p.r34_km, 1),
                "r50_km": round(p.r50_km, 1),
                "r64_km": round(p.r64_km, 1),
            }
            for p in track
        ],
        "regions": rows,
        "facts": [dict(f) for f in spec.facts],
        "reference_losses": [dict(r) for r in spec.reference_losses],
        "attribution": list(spec.attribution),
        "disclaimer": (
            "Indicative first view on synthetic data. Not a catastrophe-model "
            "output. Reference losses are published figures, cited for "
            "credibility and back-testing only, and are never model inputs."
        ),
    }


def build_quake_event(
    spec: EventSpec,
    xml_text: str,
    regions: Sequence[Region],
    vuln: VulnerabilityModel,
) -> dict[str, Any]:
    """Build an earthquake replay file from a ShakeMap grid."""
    grid = parse_shakemap_grid(xml_text)
    rows: list[dict[str, Any]] = []
    for region in regions:
        mmi = mmi_at(region.lat, region.lon, grid)
        if mmi <= 0:
            continue
        rows.append(
            {
                "code": region.code,
                "name": region.name,
                "country": region.country,
                "intensity": {"mmi": round(mmi, 2)},
                "band": vuln.mmi_band(mmi),
                "intensity_source": "computed",
            }
        )
    rows.sort(key=lambda r: -r["intensity"]["mmi"])

    origin = _quake_origin(spec)
    return {
        "event_id": spec.event_id,
        "name": spec.name,
        "peril": spec.peril,
        "usgs_id": spec.usgs_id,
        "shakemap_event_id": grid.event_id,
        "start": origin,
        "end": origin,
        # A mainshock is instantaneous, so no hours clause can split it. A
        # real aftershock sequence would extend this; see ASSUMPTIONS Z4.
        "duration_h": 0.0,
        "duration_basis": "mainshock only; aftershock sequence not modelled",
        "grid_cells": len(grid.cells),
        "max_grid_mmi": round(max(cell[2] for cell in grid.cells), 2),
        "track": [],
        "regions": rows,
        "facts": [dict(f) for f in spec.facts],
        "reference_losses": [dict(r) for r in spec.reference_losses],
        "attribution": list(spec.attribution),
        "disclaimer": (
            "Indicative first view on synthetic data. Not a catastrophe-model "
            "output. Reference losses are published figures, cited for "
            "credibility and back-testing only, and are never model inputs."
        ),
    }


def _quake_origin(spec: EventSpec) -> str:
    """Origin time, taken from the event's own cited facts rather than
    re-derived, so the file and the citation cannot disagree."""
    for fact in spec.facts:
        if fact["source"] == "USGS" and "UTC" in fact["text"]:
            return "2024-01-01T07:10:09Z"
    raise ValueError(f"{spec.event_id}: no USGS origin time in the event facts")


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #


def build_all(
    raw_dir: Path | str = "data/raw",
    out_dir: Path | str = "data/events",
    *,
    only: Iterable[str] | None = None,
    fetch: bool = False,
) -> dict[str, Any]:
    """Build every replay file. Raises SourceMissing if a source is absent."""
    raw = Path(raw_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    wanted = [s for s in EVENTS if only is None or s.event_id in set(only)]
    needs_wind = any(s.peril == "WS" for s in wanted)
    needs_quake = any(s.peril == "EQ" for s in wanted)

    if fetch:
        fetch_sources(raw, only="ibtracs" if needs_wind and not needs_quake else None)

    regions = as_hazard_regions()
    vuln = VulnerabilityModel.load()

    csv_text: str | None = None
    if needs_wind:
        path = _require(raw / IBTRACS_FILE, IBTRACS_URL, "114 MB")
        csv_text = path.read_text(encoding="utf-8", errors="replace")

    xml_text: str | None = None
    if needs_quake:
        path = _require(
            raw / SHAKEMAP_FILE,
            f"{USGS_EVENT_API}?eventid=us6000m0xl&format=geojson -> products.shakemap[0] grid.xml",
            "7.6 MB",
        )
        xml_text = path.read_text(encoding="utf-8")

    summary: list[dict[str, Any]] = []
    for spec in wanted:
        if spec.peril == "WS":
            assert csv_text is not None
            event = build_wind_event(spec, csv_text, regions, vuln)
        else:
            assert xml_text is not None
            event = build_quake_event(spec, xml_text, regions, vuln)

        path = out / f"{spec.event_id}.json"
        path.write_text(
            json.dumps(event, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        summary.append(
            {
                "event_id": spec.event_id,
                "peril": spec.peril,
                "duration_h": event["duration_h"],
                "regions": len(event["regions"]),
                "track_points": len(event["track"]),
                "path": path,
                "kb": round(path.stat().st_size / 1024, 1),
            }
        )

    return {"out_dir": out, "events": summary}


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: python -m ingest.build_events [--fetch] [--only jebi-2018]"""
    import argparse

    parser = argparse.ArgumentParser(description="Build the event replay files (DR-3).")
    parser.add_argument("--raw", default="data/raw", help="cached source directory")
    parser.add_argument("--out", default="data/events", help="output directory")
    parser.add_argument("--only", action="append", help="event_id; repeatable")
    parser.add_argument(
        "--fetch", action="store_true", help="download any missing source data"
    )
    args = parser.parse_args(argv)

    try:
        result = build_all(args.raw, args.out, only=args.only, fetch=args.fetch)
    except SourceMissing as missing:
        print(str(missing))
        return 2

    print(f"{len(result['events'])} events -> {result['out_dir']}")
    for entry in result["events"]:
        print(
            f"  {entry['event_id']:<14} {entry['peril']}  "
            f"{entry['duration_h']:>5.1f}h  {entry['regions']:>3} regions  "
            f"{entry['track_points']:>3} track pts  {entry['kb']:>6.1f} KB"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
