"""Hazard intensity at region centroids — DR-4.

Pure geometry and interpolation. No network, no file access: tracks and grids
are passed in, having been built by `ingest/`.

WIND. Intensity at a centroid is the maximum over all track points of a
piecewise radial profile (DR-4):

    d <= RMW          -> vmax
    RMW < d <= R64    -> interpolate vmax  -> 64 kt
    R64 < d <= R50    -> interpolate 64 kt -> 50 kt
    R50 < d <= R34    -> interpolate 50 kt -> 34 kt
    d > R34           -> 0

Quadrant radii are averaged into a single radius per threshold. Knots convert
to m/s at 0.514444.

Real IBTrACS rows are untidy: radii are frequently missing, and a weak or
decaying storm can report a vmax below one of the threshold speeds, which
would make that anchor nonsense. So the profile is assembled from whichever
anchors are actually usable — radius present, strictly outside RMW,
monotonically increasing, and speed below vmax — rather than assuming all four
are there. A point with no usable radius contributes vmax inside RMW and
nothing beyond it.

EARTHQUAKE. MMI is sampled from a ShakeMap `grid.xml` at the nearest grid
cell.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from statistics import mean
from typing import Iterable, Sequence

__all__ = [
    "KT_TO_MS",
    "EARTH_RADIUS_KM",
    "TrackPoint",
    "Region",
    "ShakeMapGrid",
    "haversine_km",
    "wind_at_point",
    "wind_at",
    "parse_shakemap_grid",
    "mmi_at",
]

KT_TO_MS = 0.514444
EARTH_RADIUS_KM = 6371.0088

#: Threshold wind speeds whose radii IBTrACS reports, in knots.
_R64_KT, _R50_KT, _R34_KT = 64.0, 50.0, 34.0


@dataclass(frozen=True)
class TrackPoint:
    """One cyclone track observation. Radii are quadrant means, in km."""

    t: datetime
    lat: float
    lon: float
    vmax_ms: float
    rmw_km: float = 0.0
    r64_km: float = 0.0
    r50_km: float = 0.0
    r34_km: float = 0.0

    def __post_init__(self) -> None:
        if not -90.0 <= self.lat <= 90.0:
            raise ValueError(f"lat out of range: {self.lat}")
        if not -180.0 <= self.lon <= 360.0:
            raise ValueError(f"lon out of range: {self.lon}")
        if self.vmax_ms < 0:
            raise ValueError("vmax_ms must be >= 0")
        for name in ("rmw_km", "r64_km", "r50_km", "r34_km"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")


@dataclass(frozen=True)
class Region:
    """An admin-1 region reduced to its centroid (DR-4)."""

    code: str
    name: str
    country: str
    lat: float
    lon: float


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    p1, p2 = radians(lat1), radians(lat2)
    dp = p2 - p1
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(min(1.0, sqrt(a)))


def _profile_anchors(point: TrackPoint) -> list[tuple[float, float]]:
    """Usable (radius_km, wind_ms) anchors for one track point, inner to outer.

    Starts at (RMW, vmax). Adds the 64/50/34 kt radii only where each is
    present, lies strictly outside everything already accepted, and carries a
    speed below vmax — so a decaying storm whose vmax has dropped below 64 kt
    does not get a spurious 64 kt anchor.
    """
    anchors: list[tuple[float, float]] = [(point.rmw_km, point.vmax_ms)]
    for radius_km, speed_kt in (
        (point.r64_km, _R64_KT),
        (point.r50_km, _R50_KT),
        (point.r34_km, _R34_KT),
    ):
        speed_ms = speed_kt * KT_TO_MS
        if radius_km <= 0:
            continue
        if radius_km <= anchors[-1][0]:
            continue
        if speed_ms >= point.vmax_ms:
            continue
        anchors.append((radius_km, speed_ms))
    return anchors


def wind_at_point(point: TrackPoint, distance_km: float) -> float:
    """Wind in m/s at `distance_km` from one track point's centre."""
    if distance_km < 0:
        raise ValueError("distance_km must be >= 0")

    anchors = _profile_anchors(point)
    inner_radius, inner_speed = anchors[0]

    if distance_km <= inner_radius:
        return point.vmax_ms
    if len(anchors) == 1:
        # No usable outer radius: the point says nothing beyond RMW.
        return 0.0

    for (r_in, v_in), (r_out, v_out) in zip(anchors, anchors[1:]):
        if distance_km <= r_out:
            weight = (distance_km - r_in) / (r_out - r_in)
            return v_in + weight * (v_out - v_in)

    return 0.0  # beyond the outermost radius


def wind_at(lat: float, lon: float, track: Iterable[TrackPoint]) -> float:
    """Maximum wind in m/s at a location over the whole track."""
    strongest = 0.0
    for point in track:
        distance = haversine_km(lat, lon, point.lat, point.lon)
        strongest = max(strongest, wind_at_point(point, distance))
    return strongest


# --------------------------------------------------------------------------- #
# Earthquake — ShakeMap grid.xml
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ShakeMapGrid:
    """MMI samples from a USGS ShakeMap `grid.xml`, with its extent.

    The extent is load-bearing, not decoration. Nearest-cell sampling always
    returns *something*, so without bounds a location thousands of kilometres
    away is handed the nearest corner cell's intensity: the Noto grid assigns
    MMI 2.9 to every Taiwanese and Philippine region. Those regions then
    appear in the event, and FR-MATCH uses an event's regions to decide which
    treaties respond - so a Philippine treaty would match a Japanese
    earthquake.
    """

    cells: tuple[tuple[float, float, float], ...]  # (lon, lat, mmi)
    event_id: str | None = None
    lon_min: float | None = None
    lat_min: float | None = None
    lon_max: float | None = None
    lat_max: float | None = None

    def __post_init__(self) -> None:
        if not self.cells:
            raise ValueError("ShakeMap grid has no cells")
        # Fall back to the cells' own extent, per bound. Real ShakeMap
        # products vary in what their grid_specification carries, and filling
        # only when *all* bounds are absent would leave a partially specified
        # grid half-bounded - which re-admits out-of-grid regions on the
        # unbounded axis and makes `contains` raise on a None comparison.
        lons = [c[0] for c in self.cells]
        lats = [c[1] for c in self.cells]
        for name, value in (
            ("lon_min", min(lons)),
            ("lon_max", max(lons)),
            ("lat_min", min(lats)),
            ("lat_max", max(lats)),
        ):
            if getattr(self, name) is None:
                object.__setattr__(self, name, value)

    def contains(self, lat: float, lon: float) -> bool:
        """Whether a location falls inside the grid's extent."""
        return (
            self.lat_min <= lat <= self.lat_max  # type: ignore[operator]
            and self.lon_min <= lon <= self.lon_max  # type: ignore[operator]
        )


def parse_shakemap_grid(xml_text: str) -> ShakeMapGrid:
    """Parse a ShakeMap `grid.xml` into (lon, lat, MMI) cells.

    Column order is read from the `grid_field` declarations rather than
    assumed, because ShakeMap products vary in how many fields they carry and
    in what order.
    """
    root = ET.fromstring(xml_text)

    def strip_ns(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    fields: dict[str, int] = {}
    data_text: str | None = None
    event_id = root.attrib.get("event_id")
    bounds: dict[str, float] = {}

    for element in root.iter():
        tag = strip_ns(element.tag)
        if tag == "grid_field":
            name = element.attrib["name"].upper()
            fields[name] = int(element.attrib["index"]) - 1  # 1-based in the file
        elif tag == "grid_data":
            data_text = element.text
        elif tag == "grid_specification":
            for key in ("lon_min", "lat_min", "lon_max", "lat_max"):
                if key in element.attrib:
                    bounds[key] = float(element.attrib[key])

    for required in ("LON", "LAT", "MMI"):
        if required not in fields:
            raise ValueError(f"ShakeMap grid is missing the {required} field")
    if not data_text or not data_text.strip():
        raise ValueError("ShakeMap grid has no grid_data")

    lon_i, lat_i, mmi_i = fields["LON"], fields["LAT"], fields["MMI"]
    needed = max(lon_i, lat_i, mmi_i)
    cells: list[tuple[float, float, float]] = []
    for line in data_text.strip().splitlines():
        parts = line.split()
        if len(parts) <= needed:
            continue  # ragged or blank line
        cells.append((float(parts[lon_i]), float(parts[lat_i]), float(parts[mmi_i])))

    return ShakeMapGrid(cells=tuple(cells), event_id=event_id, **bounds)


def mmi_at(lat: float, lon: float, grid: ShakeMapGrid) -> float:
    """MMI at the grid cell nearest to a location, or 0.0 outside the grid.

    Returning 0.0 rather than the nearest edge cell is the point: see
    `ShakeMapGrid`.
    """
    if not grid.contains(lat, lon):
        return 0.0
    nearest_mmi = 0.0
    nearest_distance = float("inf")
    for cell_lon, cell_lat, mmi in grid.cells:
        distance = haversine_km(lat, lon, cell_lat, cell_lon)
        if distance < nearest_distance:
            nearest_distance = distance
            nearest_mmi = mmi
    return nearest_mmi


def quadrant_mean(*radii: float) -> float:
    """Mean of the quadrant radii, ignoring missing (<= 0) quadrants.

    DR-4 says to use the mean of the quadrant radii. Averaging in the zeros
    that IBTrACS uses for "not reported" would shrink the storm, so only
    reported quadrants count.
    """
    reported = [r for r in radii if r > 0]
    return mean(reported) if reported else 0.0
