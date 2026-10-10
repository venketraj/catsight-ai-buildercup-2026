"""Natural Earth admin-1 -> a small regions.geojson for the map (DR-6, UI-3).

    python -m ingest.build_regions            # writes frontend/public/regions.geojson

Source: Natural Earth 10m admin-1 states and provinces (public domain),
downloaded once to data/raw/ (git-ignored). Filtered to Japan, the Philippines
and Taiwan, simplified with Douglas-Peucker and rounded so the committed file
stays under REQUIREMENTS' 100 KB budget.

Region codes are ISO 3166-2, which is what the portfolio and the event files
already use, so the map joins on `code` with no lookup table - apart from the
aliases below, where Natural Earth's coding differs from ours. A region with
no shape (Lienchiang, the Matsu islands, is absent from Natural Earth) is
drawn by the frontend as a marker at its centroid.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable, Sequence

__all__ = ["ALIASES", "simplify_ring", "build_regions", "main"]

COUNTRIES = ("JPN", "PHL", "TWN")
SOURCE = "data/raw/ne_10m_admin_1_states_provinces.geojson"
TARGET = "../frontend/public/regions.geojson"
BUDGET_BYTES = 100_000

#: Natural Earth code -> our code. NE splits Metro Manila into its 17 cities
#: (all PH-MNL), which we treat as one region; New Taipei kept its old code.
ALIASES = {"PH-MNL": "PH-00", "TW-TPQ": "TW-NWT"}

Point = tuple[float, float]


def _perpendicular(p: Point, a: Point, b: Point) -> float:
    if a == b:
        return math.dist(p, a)
    (x, y), (x1, y1), (x2, y2) = p, a, b
    return abs((y2 - y1) * x - (x2 - x1) * y + x2 * y1 - y2 * x1) / math.dist(a, b)


def _douglas_peucker(points: Sequence[Point], tolerance: float) -> list[Point]:
    """Iterative Douglas-Peucker, so a long coastline cannot hit recursion limits."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        best, index = 0.0, -1
        for i in range(start + 1, end):
            d = _perpendicular(points[i], points[start], points[end])
            if d > best:
                best, index = d, i
        if index != -1 and best > tolerance:
            keep[index] = True
            stack.extend(((start, index), (index, end)))
    return [p for p, k in zip(points, keep) if k]


def _area(ring: Sequence[Point]) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))) / 2


def simplify_ring(ring: Sequence[Sequence[float]], tolerance: float, digits: int) -> list[list[float]] | None:
    """A simplified, rounded, closed ring - or None if nothing is left of it."""
    points = [(round(x, digits), round(y, digits)) for x, y in ring]
    deduped = [p for i, p in enumerate(points) if i == 0 or p != points[i - 1]]
    simple = _douglas_peucker(deduped, tolerance)
    if simple[0] != simple[-1]:
        simple.append(simple[0])
    if len(simple) < 4:
        return None
    return [list(p) for p in simple]


def _polygons(geometry: dict) -> Iterable[list]:
    if geometry["type"] == "Polygon":
        yield geometry["coordinates"]
    elif geometry["type"] == "MultiPolygon":
        yield from geometry["coordinates"]


def build_regions(
    features: Iterable[dict], names: dict[str, str], *, tolerance: float, digits: int
) -> dict:
    """Group, alias, simplify. Every region keeps at least its largest ring
    (keep-shapes), so a small island prefecture never disappears."""
    grouped: dict[str, dict] = {}
    for feature in features:
        props = feature["properties"]
        if props.get("adm0_a3") not in COUNTRIES:
            continue
        code = ALIASES.get(props.get("iso_3166_2"), props.get("iso_3166_2"))
        entry = grouped.setdefault(code, {"country": props["adm0_a3"], "polygons": []})
        entry["polygons"].extend(_polygons(feature["geometry"]))

    out = []
    for code in sorted(grouped):
        entry = grouped[code]
        kept, largest = [], None
        for polygon in entry["polygons"]:
            outer = polygon[0]
            simple = simplify_ring(outer, tolerance, digits)
            if largest is None or _area([tuple(p) for p in outer]) > largest[0]:
                largest = (_area([tuple(p) for p in outer]), outer)
            if simple is not None:
                kept.append([simple])  # outer ring only: holes add bytes, not meaning
        if not kept and largest is not None:
            fallback = simplify_ring(largest[1], 0, digits) or [list(map(float, p)) for p in largest[1]]
            kept = [[fallback]]
        out.append({
            "type": "Feature",
            "properties": {"code": code, "name": names.get(code, code),
                           "country": entry["country"], "in_book": code in names},
            "geometry": {"type": "MultiPolygon", "coordinates": kept},
        })
    return {"type": "FeatureCollection", "features": out}


def _encode(collection: dict) -> str:
    return json.dumps(collection, separators=(",", ":"))


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from ingest.regions_reference import ALL_REGIONS

    parser = argparse.ArgumentParser(description="Build regions.geojson (UI-3).")
    parser.add_argument("--source", default=SOURCE)
    parser.add_argument("--out", default=TARGET)
    parser.add_argument("--budget", type=int, default=BUDGET_BYTES)
    args = parser.parse_args(argv)

    source = Path(args.source)
    if not source.exists():
        print(f"missing {source}: download Natural Earth 10m admin-1 GeoJSON there first")
        return 2
    features = json.loads(source.read_text(encoding="utf-8"))["features"]
    names = {r.code: r.name for r in ALL_REGIONS}

    # Coarsen until the file fits the budget - the finest result that fits wins.
    for tolerance, digits in ((0.01, 3), (0.02, 3), (0.03, 2), (0.05, 2), (0.08, 2), (0.12, 2)):
        text = _encode(build_regions(features, names, tolerance=tolerance, digits=digits))
        if len(text.encode("utf-8")) <= args.budget:
            break
    else:
        print(f"could not fit {args.budget} bytes even at the coarsest setting")
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    collection = json.loads(text)
    shaped = {f["properties"]["code"] for f in collection["features"]}
    missing = sorted(set(names) - shaped)
    print(f"wrote {out}: {len(text.encode('utf-8')) / 1024:.1f} KB, "
          f"{len(collection['features'])} regions, tolerance {tolerance}, {digits} dp")
    print(f"book regions without a shape (drawn as markers): {missing or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
