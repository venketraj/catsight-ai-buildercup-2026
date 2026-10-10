"""regions.geojson builder (ingest.build_regions)."""

from __future__ import annotations

import json
from pathlib import Path

from ingest.build_regions import ALIASES, build_regions, main, simplify_ring


def _square(x, y, size=1.0, steps=10):
    pts = []
    for i in range(steps):
        pts.append([x + size * i / steps, y])
    for i in range(steps):
        pts.append([x + size, y + size * i / steps])
    for i in range(steps):
        pts.append([x + size - size * i / steps, y + size])
    for i in range(steps):
        pts.append([x, y + size - size * i / steps])
    pts.append([x, y])
    return pts


def _feature(code, country, rings, kind="Polygon"):
    coords = [[r] for r in rings] if kind == "MultiPolygon" else [rings[0]]
    return {"properties": {"iso_3166_2": code, "adm0_a3": country},
            "geometry": {"type": kind, "coordinates": coords}}


def test_simplification_keeps_corners_and_closes_the_ring():
    ring = simplify_ring(_square(0, 0), tolerance=0.01, digits=3)
    assert ring[0] == ring[-1]
    assert {tuple(p) for p in ring} >= {(0, 0), (1, 0), (1, 1), (0, 1)}
    assert len(ring) == 5, "collinear points along the sides are dropped"


def test_degenerate_inputs():
    from ingest.build_regions import _douglas_peucker, _perpendicular

    assert _perpendicular((3, 4), (0, 0), (0, 0)) == 5.0
    assert _douglas_peucker([(0, 0), (1, 1)], 0.1) == [(0, 0), (1, 1)]
    # An open ring is closed.
    assert simplify_ring([[0, 0], [1, 0], [1, 1], [0, 1]], 0, 2)[-1] == [0.0, 0.0]
    # Points and lines are not polygons and contribute nothing.
    from ingest.build_regions import _polygons
    assert list(_polygons({"type": "Point", "coordinates": [0, 0]})) == []


def test_a_ring_that_collapses_is_dropped():
    assert simplify_ring([[0, 0], [0.001, 0], [0, 0]], tolerance=1, digits=2) is None


def test_build_groups_aliases_and_keeps_every_region():
    tiny = [[5, 5], [5.001, 5], [5.001, 5.001], [5, 5]]
    features = [
        _feature("PH-MNL", "PHL", [_square(0, 0)]),
        _feature("PH-MNL", "PHL", [_square(2, 0)], "MultiPolygon"),
        _feature("JP-47", "JPN", [tiny]),  # collapses under simplification
        _feature("US-CA", "USA", [_square(9, 9)]),  # wrong country, ignored
    ]
    out = build_regions(features, {"PH-00": "Metro Manila", "JP-47": "Okinawa"},
                        tolerance=0.5, digits=2)
    by_code = {f["properties"]["code"]: f for f in out["features"]}
    assert set(by_code) == {"PH-00", "JP-47"}
    assert len(by_code["PH-00"]["geometry"]["coordinates"]) == 2, "both cities merged"
    assert by_code["PH-00"]["properties"] == {"code": "PH-00", "name": "Metro Manila",
                                              "country": "PHL", "in_book": True}
    assert by_code["JP-47"]["geometry"]["coordinates"], "keep-shapes: never dropped"
    assert ALIASES["TW-TPQ"] == "TW-NWT"


def test_regions_outside_the_book_are_context_only():
    out = build_regions([_feature("PH-SLU", "PHL", [_square(0, 0)])], {}, tolerance=0.1, digits=2)
    assert out["features"][0]["properties"]["in_book"] is False


def test_cli_fits_the_budget_and_reports(tmp_path, capsys):
    source = tmp_path / "ne.geojson"
    source.write_text(json.dumps({"features": [_feature("JP-13", "JPN", [_square(139, 35)])]}),
                      encoding="utf-8")
    out = tmp_path / "regions.geojson"
    assert main(["--source", str(source), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "1 regions" in printed and "JP-01" in printed  # missing book regions listed
    assert json.loads(out.read_text(encoding="utf-8"))["type"] == "FeatureCollection"


def test_cli_without_source_or_budget(tmp_path, capsys):
    assert main(["--source", str(tmp_path / "nope.geojson")]) == 2
    source = tmp_path / "ne.geojson"
    source.write_text(json.dumps({"features": [_feature("JP-13", "JPN", [_square(139, 35)])]}),
                      encoding="utf-8")
    assert main(["--source", str(source), "--out", str(tmp_path / "o.json"), "--budget", "10"]) == 1


def test_the_committed_file_is_within_budget():
    path = Path("../frontend/public/regions.geojson")
    assert path.stat().st_size <= 100_000
    codes = {f["properties"]["code"] for f in json.loads(path.read_text(encoding="utf-8"))["features"]}
    assert {"JP-27", "PH-00", "TW-NWT"} <= codes
