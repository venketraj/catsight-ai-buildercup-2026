"""DR-3 — the event replay files.

Split deliberately in two:

  * **Logic tests** run on small hand-written fixtures and always run. They
    cover the damaging-window definition, the schema, and the out-of-grid
    guard.
  * **Integration tests** run against the real 114 MB IBTrACS CSV and the
    7.6 MB ShakeMap grid, and **skip** when those are absent. They are
    git-ignored, so a fresh clone must not fail here - it must tell you to
    fetch them.

The integration tests are worth having anyway: Jebi's real landfall record is
the only independent check that the parser reads IBTrACS correctly.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from catsight_agent.tools.hazard import Region, TrackPoint
from catsight_agent.tools.vulnerability import VulnerabilityModel
from ingest.build_events import (
    DAMAGE_THRESHOLD_MS,
    EVENTS,
    IBTRACS_FILE,
    IBTRACS_URL,
    SHAKEMAP_FILE,
    EventSpec,
    SourceMissing,
    build_all,
    build_quake_event,
    build_wind_event,
    damaging_window,
    event_spec,
    main,
)
from ingest.regions_reference import as_hazard_regions

RAW = Path("data/raw")
HAS_IBTRACS = (RAW / IBTRACS_FILE).exists()
HAS_SHAKEMAP = (RAW / SHAKEMAP_FILE).exists()

needs_ibtracs = pytest.mark.skipif(
    not HAS_IBTRACS,
    reason=f"{IBTRACS_FILE} not cached; run python -m ingest.build_events --fetch",
)
needs_shakemap = pytest.mark.skipif(
    not HAS_SHAKEMAP,
    reason=f"{SHAKEMAP_FILE} not cached; run python -m ingest.build_events --fetch",
)

T0 = datetime(2018, 9, 4, 0, 0, tzinfo=timezone.utc)
OSAKA = Region("JP-27", "Osaka", "JPN", 34.6, 135.5)


@pytest.fixture(scope="module")
def vuln() -> VulnerabilityModel:
    return VulnerabilityModel.load()


# --------------------------------------------------------------------------- #
# Event specifications
# --------------------------------------------------------------------------- #


def test_the_four_planned_events_are_specified():
    ids = [spec.event_id for spec in EVENTS]
    assert ids == ["jebi-2018", "hagibis-2019", "haiyan-2013", "noto-2024"]


def test_every_wind_event_has_a_sid_and_the_quake_has_a_usgs_id():
    """DR-3 is explicit that storms are selected by SID, never by name."""
    for spec in EVENTS:
        if spec.peril == "WS":
            assert spec.sid and spec.usgs_id is None
        else:
            assert spec.usgs_id and spec.sid is None


def test_every_event_carries_cited_facts_and_attribution():
    for spec in EVENTS:
        assert spec.facts, spec.event_id
        assert spec.attribution, spec.event_id
        for fact in spec.facts:
            assert fact["text"]
            assert fact["source"]
            assert "url" in fact  # may be None for a third-party figure


def test_reference_losses_are_dated_or_explicitly_undated():
    """They feed the B5 back-test, so an undated figure must say so rather
    than imply currency."""
    for spec in EVENTS:
        for loss in spec.reference_losses:
            assert loss["source"]
            assert loss["value"]
            assert "as_of" in loss


def test_ibtracs_attribution_cites_the_doi():
    """DR-6 requires Knapp et al. 2010 and the DOI."""
    for spec in EVENTS:
        if spec.peril == "WS":
            joined = " ".join(spec.attribution)
            assert "IBTrACS" in joined
            assert "10.25921/82ty-9e16" in joined


def test_usgs_attribution_credits_the_survey():
    noto = event_spec("noto-2024")
    assert any("Geological Survey" in line for line in noto.attribution)


def test_event_spec_rejects_an_unknown_id():
    with pytest.raises(KeyError, match="nope"):
        event_spec("nope")


# --------------------------------------------------------------------------- #
# The damaging window — the module's most consequential decision
# --------------------------------------------------------------------------- #


def _track(*offsets_and_winds) -> list[TrackPoint]:
    return [
        TrackPoint(
            T0 + timedelta(hours=h), 34.6, 135.5, wind,
            rmw_km=40.0, r64_km=80.0, r50_km=150.0, r34_km=280.0,
        )
        for h, wind in offsets_and_winds
    ]


def test_the_window_covers_only_damaging_points():
    """A storm that spends days as a weak system and one day as a damaging
    one has a one-day loss occurrence, not a multi-day one."""
    track = _track((0, 10.0), (24, 12.0), (48, 45.0), (54, 40.0), (72, 15.0), (96, 8.0))
    start, end, hours, count = damaging_window(track, [OSAKA])
    assert start == T0 + timedelta(hours=48)
    assert end == T0 + timedelta(hours=54)
    assert hours == 6.0
    assert count == 2


def test_the_window_is_not_the_track_lifetime():
    """The whole reason the function exists. Jebi's real track spans 213
    hours; using that as duration_h would breach every hours clause."""
    track = _track((0, 10.0), (200, 45.0), (206, 44.0), (400, 9.0))
    _, _, hours, _ = damaging_window(track, [OSAKA])
    span = (track[-1].t - track[0].t).total_seconds() / 3600
    assert span == 400.0
    assert hours == 6.0


def test_a_single_damaging_point_gives_a_zero_length_window():
    track = _track((0, 10.0), (24, 50.0), (48, 10.0))
    start, end, hours, count = damaging_window(track, [OSAKA])
    assert start == end
    assert hours == 0.0
    assert count == 1


def test_a_storm_that_never_reaches_a_covered_region_has_zero_duration():
    """It still describes itself - the track span is reported - but duration
    is zero so no hours clause can be triggered."""
    far_away = Region("XX-01", "Elsewhere", "JPN", -40.0, 20.0)
    track = _track((0, 60.0), (24, 55.0))
    start, end, hours, count = damaging_window(track, [far_away])
    assert (start, end) == (track[0].t, track[-1].t)
    assert hours == 0.0
    assert count == 0


def test_the_threshold_is_the_vulnerability_curves_own():
    """Below 25.7 m/s the Emanuel curve's damage ratio is zero by
    construction, so those hours cannot contribute loss."""
    assert DAMAGE_THRESHOLD_MS == 25.7
    just_under = _track((0, 25.6),)
    _, _, hours, count = damaging_window(just_under, [OSAKA])
    assert count == 0
    just_over = _track((0, 25.8),)
    _, _, _, count = damaging_window(just_over, [OSAKA])
    assert count == 1


# --------------------------------------------------------------------------- #
# Wind event schema
# --------------------------------------------------------------------------- #

SMALL_CSV = """SID,ISO_TIME,LAT,LON,USA_WIND,USA_RMW,USA_R34_NE,USA_R34_SE,USA_R34_SW,USA_R34_NW,USA_R50_NE,USA_R50_SE,USA_R50_SW,USA_R50_NW,USA_R64_NE,USA_R64_SE,USA_R64_SW,USA_R64_NW
,,degrees_north,degrees_east,kts,nmile,nmile,nmile,nmile,nmile,nmile,nmile,nmile,nmile,nmile,nmile,nmile,nmile
2018239N11161,2018-09-04 00:00:00,32.4,133.8,100,25,150,140,120,130,85,80,70,75,45,40,35,40
2018239N11161,2018-09-04 06:00:00,35.5,135.6,80,25,145,135,115,125,80,75,65,70,40,35,30,35
2018239N11161,2018-09-04 12:00:00,39.2,137.7,60,45,140,130,110,120,75,70,60,65,0,0,0,0
"""


@pytest.fixture(scope="module")
def small_wind_event(vuln) -> dict:
    return build_wind_event(
        event_spec("jebi-2018"), SMALL_CSV, as_hazard_regions(), vuln
    )


def test_a_wind_event_has_every_field_the_schema_requires(small_wind_event):
    for key in (
        "event_id", "name", "peril", "sid", "start", "end", "duration_h",
        "track", "regions", "facts", "reference_losses", "attribution",
    ):
        assert key in small_wind_event, key


def test_a_wind_event_explains_how_its_duration_was_derived(small_wind_event):
    """Anyone reading the file cold must learn that duration is the damaging
    window, not the track life, or they will misread the hours-clause flag."""
    basis = small_wind_event["duration_basis"]
    assert "not the" in basis and "track lifetime" in basis
    assert str(DAMAGE_THRESHOLD_MS) in basis


def test_a_wind_event_reports_both_the_damaging_window_and_the_track_span(small_wind_event):
    assert small_wind_event["track_start"] <= small_wind_event["start"]
    assert small_wind_event["end"] <= small_wind_event["track_end"]
    assert small_wind_event["damaging_points"] >= 1


def test_track_points_carry_the_radii_the_profile_needs(small_wind_event):
    for point in small_wind_event["track"]:
        for key in ("t", "lat", "lon", "vmax_ms", "rmw_km", "r34_km", "r50_km", "r64_km"):
            assert key in point


def test_regions_are_non_zero_banded_and_sorted_strongest_first(small_wind_event):
    rows = small_wind_event["regions"]
    assert rows
    winds = [r["intensity"]["wind_ms"] for r in rows]
    assert winds == sorted(winds, reverse=True)
    assert all(w > 0 for w in winds)
    for row in rows:
        assert 0 <= row["band"] <= 5
        assert row["intensity_source"] == "computed"


def test_a_wind_event_only_includes_regions_the_storm_reached(small_wind_event):
    """Okinawa is 900 km from this track and must not appear."""
    codes = {row["code"] for row in small_wind_event["regions"]}
    assert "JP-27" in codes  # Osaka
    assert "JP-47" not in codes  # Okinawa


def test_a_wind_event_records_its_peak(small_wind_event):
    peak = small_wind_event["peak"]
    assert peak["vmax_ms"] == pytest.approx(100 * 0.514444, abs=0.01)


def test_a_wind_event_carries_the_disclaimer(small_wind_event):
    """C-13, and the explicit statement that reference losses are not model
    inputs - which is what stops a judge reading them as our output."""
    text = small_wind_event["disclaimer"]
    assert "Not a catastrophe-model output" in text
    assert "never model inputs" in text


def test_building_a_wind_event_without_a_sid_fails():
    spec = EventSpec(event_id="x", name="X", peril="WS")
    with pytest.raises(ValueError, match="IBTrACS SID"):
        build_wind_event(spec, SMALL_CSV, as_hazard_regions(), VulnerabilityModel.load())


# --------------------------------------------------------------------------- #
# Quake event schema
# --------------------------------------------------------------------------- #

SMALL_GRID = """<?xml version="1.0" encoding="UTF-8"?>
<shakemap_grid xmlns="http://earthquake.usgs.gov/eqcenter/shakemap" event_id="us6000m0xl">
  <grid_specification lon_min="136.0" lat_min="36.5" lon_max="138.0" lat_max="38.0"
      nlon="3" nlat="2"/>
  <grid_field index="1" name="LON" units="dd"/>
  <grid_field index="2" name="LAT" units="dd"/>
  <grid_field index="3" name="MMI" units="intensity"/>
  <grid_data>
136.0 38.0 6.1
137.0 38.0 8.8
138.0 38.0 5.5
136.0 36.5 5.0
137.0 36.5 6.5
138.0 36.5 4.6
  </grid_data>
</shakemap_grid>
"""


@pytest.fixture(scope="module")
def small_quake_event(vuln) -> dict:
    return build_quake_event(
        event_spec("noto-2024"), SMALL_GRID, as_hazard_regions(), vuln
    )


def test_a_quake_event_has_zero_duration_so_no_hours_clause_can_split_it(small_quake_event):
    assert small_quake_event["duration_h"] == 0.0
    assert "mainshock" in small_quake_event["duration_basis"]
    assert small_quake_event["start"] == small_quake_event["end"]


def test_a_quake_event_has_no_track(small_quake_event):
    assert small_quake_event["track"] == []


def test_a_quake_event_reports_its_grid(small_quake_event):
    assert small_quake_event["grid_cells"] == 6
    assert small_quake_event["max_grid_mmi"] == pytest.approx(8.8)
    assert small_quake_event["shakemap_event_id"] == "us6000m0xl"


def test_a_quake_event_excludes_regions_outside_the_grid(small_quake_event):
    """The out-of-grid bug. Without bounds every Taiwanese and Philippine
    region is handed the nearest corner cell, and FR-MATCH would then respond
    a Philippine treaty to a Japanese earthquake."""
    countries = {row["country"] for row in small_quake_event["regions"]}
    assert countries == {"JPN"}
    codes = {row["code"] for row in small_quake_event["regions"]}
    assert "TW-TPE" not in codes
    assert "PH-00" not in codes


def test_quake_regions_are_sorted_by_intensity(small_quake_event):
    values = [row["intensity"]["mmi"] for row in small_quake_event["regions"]]
    assert values == sorted(values, reverse=True)
    assert all(v > 0 for v in values)


def test_the_quake_origin_time_comes_from_the_cited_facts(small_quake_event):
    """So the file and its own citation cannot drift apart."""
    assert small_quake_event["start"] == "2024-01-01T07:10:09Z"
    noto = event_spec("noto-2024")
    assert any("07:10:09" in fact["text"] for fact in noto.facts)


def test_a_quake_spec_without_a_usgs_origin_fact_fails(vuln):
    spec = EventSpec(
        event_id="x", name="X", peril="EQ", usgs_id="us1",
        facts=({"text": "no time here", "source": "JMA", "url": None},),
    )
    with pytest.raises(ValueError, match="origin time"):
        build_quake_event(spec, SMALL_GRID, as_hazard_regions(), vuln)


# --------------------------------------------------------------------------- #
# Cache-first behaviour
# --------------------------------------------------------------------------- #


def test_a_missing_source_fails_with_the_url_and_the_target_path(tmp_path):
    """No silent half-events, and no implicit 114 MB download."""
    with pytest.raises(SourceMissing) as caught:
        build_all(raw_dir=tmp_path / "empty", out_dir=tmp_path / "out")
    message = str(caught.value)
    assert IBTRACS_FILE in message
    assert IBTRACS_URL in message
    assert "--fetch" in message
    assert "114 MB" in message


def test_an_empty_source_file_counts_as_missing(tmp_path):
    """A truncated or zero-byte download is worse than an absent one."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / IBTRACS_FILE).write_text("", encoding="utf-8")
    with pytest.raises(SourceMissing):
        build_all(raw_dir=raw, out_dir=tmp_path / "out", only=["jebi-2018"])


def test_the_cli_reports_a_missing_source_without_crashing(tmp_path, capsys):
    code = main(["--raw", str(tmp_path / "nothing"), "--out", str(tmp_path / "out")])
    assert code == 2
    assert IBTRACS_URL in capsys.readouterr().out


def test_only_a_quake_build_does_not_require_the_track_csv(tmp_path):
    """Building just Noto must not demand the 114 MB typhoon file."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / SHAKEMAP_FILE).write_text(SMALL_GRID, encoding="utf-8")
    result = build_all(raw_dir=raw, out_dir=tmp_path / "out", only=["noto-2024"])
    assert len(result["events"]) == 1
    assert result["events"][0]["event_id"] == "noto-2024"


# --------------------------------------------------------------------------- #
# Integration — real source data, skipped when not cached
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def real_events(tmp_path_factory) -> dict:
    if not (HAS_IBTRACS and HAS_SHAKEMAP):
        pytest.skip("real source data not cached")
    return build_all(raw_dir=RAW, out_dir=tmp_path_factory.mktemp("events"))


@needs_ibtracs
@needs_shakemap
def test_all_four_events_build_from_real_data(real_events):
    assert len(real_events["events"]) == 4


@needs_ibtracs
@needs_shakemap
def test_every_replay_file_is_small_enough_to_commit(real_events):
    """Project rule: commit only small derived files."""
    for entry in real_events["events"]:
        assert entry["kb"] < 100, entry


@needs_ibtracs
@needs_shakemap
def test_real_durations_sit_inside_a_seventy_two_hour_clause(real_events):
    """The DOMAIN_PRIMER says Jebi's damage was well inside 72 hours. If the
    duration were the track lifetime these would all be over 200.
    """
    by_id = {e["event_id"]: e["duration_h"] for e in real_events["events"]}
    assert by_id["jebi-2018"] < 72
    assert by_id["haiyan-2013"] < 72
    assert by_id["hagibis-2019"] < 72
    assert by_id["noto-2024"] == 0.0


@needs_ibtracs
def test_jebi_matches_its_published_landfall_record(real_events):
    """The only independent check that the IBTrACS parser is right.

    RESEARCH_FINDINGS D1 records Jebi's landfall as 2018-09-04 03Z at
    33.8N 134.6E.
    """
    path = real_events["out_dir"] / "jebi-2018.json"
    event = json.loads(path.read_text(encoding="utf-8"))
    at_03z = next(p for p in event["track"] if p["t"] == "2018-09-04T03:00:00Z")
    assert at_03z["lat"] == pytest.approx(33.8, abs=0.05)
    assert at_03z["lon"] == pytest.approx(134.6, abs=0.05)


@needs_ibtracs
def test_jebi_affects_kansai_and_not_okinawa(real_events):
    """What the hero demo depends on: exposure in the regions that were hit."""
    event = json.loads(
        (real_events["out_dir"] / "jebi-2018.json").read_text(encoding="utf-8")
    )
    bands = {r["code"]: r["band"] for r in event["regions"]}
    assert bands.get("JP-27", 0) >= 2  # Osaka
    assert bands.get("JP-28", 0) >= 1  # Hyogo
    assert bands.get("JP-47", 0) == 0  # Okinawa untouched, if present at all


@needs_shakemap
def test_noto_concentrates_on_ishikawa(real_events):
    """Ishikawa contains the Noto Peninsula. Its centroid sits south of the
    rupture, so it reads well below the grid maximum - assumption W8 showing
    up in real output rather than in a comment.
    """
    event = json.loads(
        (real_events["out_dir"] / "noto-2024.json").read_text(encoding="utf-8")
    )
    top = event["regions"][0]
    assert top["code"] == "JP-17"
    assert top["intensity"]["mmi"] > 6.0
    assert event["max_grid_mmi"] > top["intensity"]["mmi"]


@needs_shakemap
def test_noto_only_lists_japanese_regions(real_events):
    event = json.loads(
        (real_events["out_dir"] / "noto-2024.json").read_text(encoding="utf-8")
    )
    assert {r["country"] for r in event["regions"]} == {"JPN"}


@needs_ibtracs
@needs_shakemap
def test_the_cli_builds_from_real_data(tmp_path, capsys):
    assert main(["--raw", str(RAW), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "4 events" in out
    assert "jebi-2018" in out


# --------------------------------------------------------------------------- #
# Fetching — exercised with a stubbed urllib, so no network in the test suite
# --------------------------------------------------------------------------- #


def test_fetch_resolves_the_shakemap_url_through_the_event_api(tmp_path, monkeypatch):
    """The grid.xml URL carries a product-version timestamp, so it is looked
    up rather than hardcoded. A pinned URL goes stale the next time USGS
    revises the ShakeMap - which it has, ten times for Noto.
    """
    import io
    import json as _json

    import ingest.build_events as mod

    payload = {
        "properties": {
            "products": {
                "shakemap": [
                    {
                        "contents": {
                            "download/cont_mmi.json": {"url": "https://x/cont_mmi.json"},
                            "download/grid.xml": {"url": "https://x/v99/grid.xml"},
                        }
                    }
                ]
            }
        }
    }
    opened: list[str] = []
    retrieved: list[tuple[str, object]] = []

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(url):
        opened.append(url)
        return _Response(_json.dumps(payload).encode("utf-8"))

    def fake_urlretrieve(url, target):
        retrieved.append((url, target))
        Path(target).write_text("grid", encoding="utf-8")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("urllib.request.urlretrieve", fake_urlretrieve)

    fetched = mod.fetch_sources(tmp_path, only="shakemap")

    assert "eventid=us6000m0xl" in opened[0]
    assert retrieved[0][0] == "https://x/v99/grid.xml"
    assert fetched["shakemap"].exists()


def test_fetch_downloads_the_track_csv_when_absent(tmp_path, monkeypatch):
    import ingest.build_events as mod

    retrieved: list[str] = []

    def fake_urlretrieve(url, target):
        retrieved.append(url)
        Path(target).write_text("SID,ISO_TIME\n", encoding="utf-8")

    monkeypatch.setattr("urllib.request.urlretrieve", fake_urlretrieve)
    fetched = mod.fetch_sources(tmp_path, only="ibtracs")

    assert retrieved == [mod.IBTRACS_URL]
    assert fetched["ibtracs"].exists()


def test_fetch_skips_a_source_that_is_already_cached(tmp_path, monkeypatch):
    """Re-running must not re-download 114 MB."""
    import ingest.build_events as mod

    (tmp_path / mod.IBTRACS_FILE).write_text("already here", encoding="utf-8")

    def explode(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("should not re-download a cached source")

    monkeypatch.setattr("urllib.request.urlretrieve", explode)
    fetched = mod.fetch_sources(tmp_path, only="ibtracs")
    assert fetched["ibtracs"].read_text(encoding="utf-8") == "already here"


def test_build_with_fetch_pulls_only_what_the_selection_needs(tmp_path, monkeypatch):
    """A wind-only build must not fetch the ShakeMap, and vice versa."""
    import ingest.build_events as mod

    calls: list[str | None] = []
    real = mod.fetch_sources

    def spy(raw_dir, *, only=None):
        calls.append(only)
        return real(raw_dir, only=only)

    monkeypatch.setattr(mod, "fetch_sources", spy)
    monkeypatch.setattr(
        "urllib.request.urlretrieve",
        lambda url, target: Path(target).write_text(SMALL_CSV, encoding="utf-8"),
    )

    mod.build_all(
        raw_dir=tmp_path, out_dir=tmp_path / "out", only=["jebi-2018"], fetch=True
    )
    assert calls == ["ibtracs"]


def test_a_wind_only_build_does_not_require_the_shakemap(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / IBTRACS_FILE).write_text(SMALL_CSV, encoding="utf-8")
    result = build_all(raw_dir=raw, out_dir=tmp_path / "out", only=["jebi-2018"])
    assert [e["event_id"] for e in result["events"]] == ["jebi-2018"]
    assert not (raw / SHAKEMAP_FILE).exists()


def test_a_grid_specification_missing_some_bounds_falls_back_per_key(tmp_path):
    """Real ShakeMap products vary. A partial grid_specification must not
    leave the grid half-bounded, which would silently re-admit out-of-grid
    regions on one axis.
    """
    from catsight_agent.tools.hazard import parse_shakemap_grid

    partial = SMALL_GRID.replace(
        '<grid_specification lon_min="136.0" lat_min="36.5" lon_max="138.0" lat_max="38.0"\n'
        '      nlon="3" nlat="2"/>',
        '<grid_specification lon_min="136.0" nlon="3" nlat="2"/>',
    )
    grid = parse_shakemap_grid(partial)
    assert grid.lon_min == 136.0
    # The rest come from the cells' own extent rather than being left None.
    assert grid.lat_min == 36.5
    assert grid.lat_max == 38.0
    assert grid.lon_max == 138.0
    assert grid.contains(37.0, 137.0)
    assert not grid.contains(25.0, 121.5)


def test_fetch_reports_clearly_when_the_api_has_no_grid_file(tmp_path, monkeypatch):
    """If USGS renames a content key, a bare StopIteration from next() tells
    you nothing. The error names what was actually available."""
    import io
    import json as _json

    import ingest.build_events as mod

    payload = {
        "properties": {
            "products": {
                "shakemap": [
                    {"contents": {"download/cont_mmi.json": {"url": "https://x/c.json"}}}
                ]
            }
        }
    }

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda url: _Response(_json.dumps(payload).encode("utf-8")),
    )
    with pytest.raises(ValueError, match="no grid.xml"):
        mod.fetch_sources(tmp_path, only="shakemap")


def test_fetch_skips_a_cached_shakemap_without_calling_the_api(tmp_path, monkeypatch):
    """Re-running must not re-query USGS or re-download the grid."""
    import ingest.build_events as mod

    (tmp_path / mod.SHAKEMAP_FILE).write_text("cached grid", encoding="utf-8")

    def explode(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("should not touch the network for a cached grid")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    monkeypatch.setattr("urllib.request.urlretrieve", explode)

    fetched = mod.fetch_sources(tmp_path, only="shakemap")
    assert fetched["shakemap"].read_text(encoding="utf-8") == "cached grid"


def test_fetch_with_no_selection_handles_both_sources(tmp_path, monkeypatch):
    """only=None is the default path the CLI takes."""
    import ingest.build_events as mod

    (tmp_path / mod.IBTRACS_FILE).write_text("cached csv", encoding="utf-8")
    (tmp_path / mod.SHAKEMAP_FILE).write_text("cached grid", encoding="utf-8")

    def explode(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("both sources were cached")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    monkeypatch.setattr("urllib.request.urlretrieve", explode)

    fetched = mod.fetch_sources(tmp_path)
    assert set(fetched) == {"ibtracs", "shakemap"}
