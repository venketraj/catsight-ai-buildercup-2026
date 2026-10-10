"""IBTrACS v04r01 parsing — DR-3.

Pure parsing, separated from the ~114 MB download in `build_events.py` so the
quirks below are testable without touching the network.

Quirks verified in RESEARCH_FINDINGS and asserted by QA-2:

  * headers are uppercase;
  * **row 2 is a units row** and must be skipped - parsing it as data yields
    garbage like vmax "kts";
  * filter by **SID**, not by NAME. Storm names repeat across basins and
    seasons; SID is unique. "JEBI" alone matches several storms;
  * missing values appear as empty strings or a bare space, not as 0;
  * `USA_WIND` is 1-minute sustained in knots and is preferred. Where it is
    absent, `TOKYO_WIND` is 10-minute sustained and is converted with a
    x1.12 factor - an assumption, documented in data/ASSUMPTIONS.md;
  * radii come from `USA_R34/R50/R64_*` quadrants plus `USA_RMW`, in nautical
    miles, and are averaged over the reported quadrants only.

Source: NOAA IBTrACS v04r01, Knapp et al. 2010, doi:10.25921/82ty-9e16.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO
from typing import Iterator, Sequence

from catsight_agent.tools.hazard import KT_TO_MS, TrackPoint, quadrant_mean

__all__ = [
    "NM_TO_KM",
    "TOKYO_TO_ONE_MINUTE",
    "parse_ibtracs_csv",
    "track_for_sid",
]

NM_TO_KM = 1.852
#: 10-minute sustained -> 1-minute sustained. An assumption; see the module
#: docstring and data/ASSUMPTIONS.md.
TOKYO_TO_ONE_MINUTE = 1.12

_MISSING = {"", " ", "NA", "NaN", "-999", "-9999"}


def _number(raw: str | None) -> float | None:
    """IBTrACS missing values are blanks or sentinels, never 0."""
    if raw is None:
        return None
    text = raw.strip()
    if text in _MISSING:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _timestamp(raw: str) -> datetime:
    return datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def parse_ibtracs_csv(text: str) -> Iterator[dict[str, str]]:
    """Yield data rows from an IBTrACS CSV, skipping the units row.

    The units row is identified positionally - it is always the first row after
    the header - and confirmed by its content, so a file that happens not to
    carry one still parses.
    """
    reader = csv.reader(StringIO(text))
    try:
        header = [column.strip().upper() for column in next(reader)]
    except StopIteration:
        return

    rows = iter(reader)
    first = next(rows, None)
    if first is None:
        return

    # Row 2 is the units row. It is recognisable because SID is blank or
    # non-numeric junk and ISO_TIME does not parse as a timestamp.
    if not _looks_like_data(header, first):
        first = next(rows, None)
        if first is None:
            return

    for row in (first, *rows):
        if not row or all(not cell.strip() for cell in row):
            continue
        yield dict(zip(header, row))


def _looks_like_data(header: Sequence[str], row: Sequence[str]) -> bool:
    record = dict(zip(header, row))
    iso_time = record.get("ISO_TIME", "").strip()
    if not iso_time:
        return False
    try:
        _timestamp(iso_time)
    except ValueError:
        return False
    return True


def track_for_sid(text: str, sid: str) -> tuple[TrackPoint, ...]:
    """Build a track for one storm, selected by SID.

    Filtering by SID rather than NAME is a hard requirement: names repeat
    across basins and seasons.
    """
    if not sid or not sid.strip():
        raise ValueError("sid is required")
    wanted = sid.strip().upper()

    points: list[TrackPoint] = []
    for record in parse_ibtracs_csv(text):
        if record.get("SID", "").strip().upper() != wanted:
            continue

        iso_time = record.get("ISO_TIME", "").strip()
        lat = _number(record.get("LAT"))
        lon = _number(record.get("LON"))
        if not iso_time or lat is None or lon is None:
            continue

        vmax_ms = _vmax_ms(record)
        if vmax_ms is None:
            continue

        points.append(
            TrackPoint(
                t=_timestamp(iso_time),
                lat=lat,
                lon=lon,
                vmax_ms=vmax_ms,
                rmw_km=_radius_km(record, "USA_RMW"),
                r64_km=_quadrant_radius_km(record, "USA_R64"),
                r50_km=_quadrant_radius_km(record, "USA_R50"),
                r34_km=_quadrant_radius_km(record, "USA_R34"),
            )
        )

    if not points:
        raise ValueError(f"no usable track points for SID {sid!r}")
    points.sort(key=lambda p: p.t)
    return tuple(points)


def _vmax_ms(record: dict[str, str]) -> float | None:
    """Prefer USA_WIND (1-minute, kt). Fall back to TOKYO_WIND (10-minute)."""
    usa = _number(record.get("USA_WIND"))
    if usa is not None:
        return usa * KT_TO_MS
    tokyo = _number(record.get("TOKYO_WIND"))
    if tokyo is not None:
        return tokyo * TOKYO_TO_ONE_MINUTE * KT_TO_MS
    return None


def _radius_km(record: dict[str, str], column: str) -> float:
    value = _number(record.get(column))
    return value * NM_TO_KM if value is not None else 0.0


def _quadrant_radius_km(record: dict[str, str], prefix: str) -> float:
    """Mean of the NE/SE/SW/NW quadrant radii, reported quadrants only."""
    quadrants = [
        _number(record.get(f"{prefix}_{quadrant}")) or 0.0
        for quadrant in ("NE", "SE", "SW", "NW")
    ]
    return quadrant_mean(*quadrants) * NM_TO_KM
