"""QA-2 — hazard intensity, damage ratios and the IBTrACS parser.

Pass bar: known centroid distances give the expected bands, and the IBTrACS
parser skips the units row and filters by SID.

No network and no large fixtures: the IBTrACS and ShakeMap samples below are
hand-written in the real formats, including the quirks that bite.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from catsight_agent.tools.hazard import (
    EARTH_RADIUS_KM,
    KT_TO_MS,
    Region,
    ShakeMapGrid,
    TrackPoint,
    haversine_km,
    mmi_at,
    parse_shakemap_grid,
    quadrant_mean,
    wind_at,
    wind_at_point,
)
from catsight_agent.tools.vulnerability import (
    VulnerabilityModel,
    emanuel_2011,
)
from ingest.ibtracs import (
    NM_TO_KM,
    TOKYO_TO_ONE_MINUTE,
    parse_ibtracs_csv,
    track_for_sid,
)

T0 = datetime(2018, 9, 4, 12, 0, tzinfo=timezone.utc)

# A storm centred in Osaka Bay, with the radii a strong typhoon reports.
JEBI_LIKE = TrackPoint(
    t=T0,
    lat=34.4,
    lon=135.3,
    vmax_ms=50.0,
    rmw_km=30.0,
    r64_km=60.0,
    r50_km=120.0,
    r34_km=240.0,
)


@pytest.fixture(scope="module")
def vuln() -> VulnerabilityModel:
    """The real data/vulnerability.json, not a stub -- the committed
    parameters are part of what QA-2 checks."""
    return VulnerabilityModel.load()


# --------------------------------------------------------------------------- #
# Distance
# --------------------------------------------------------------------------- #


def test_haversine_is_zero_for_the_same_point():
    assert haversine_km(34.4, 135.3, 34.4, 135.3) == 0.0


def test_haversine_one_degree_of_latitude_is_about_111_km():
    assert haversine_km(34.0, 135.0, 35.0, 135.0) == pytest.approx(111.2, abs=0.2)


def test_haversine_matches_a_known_city_pair():
    """Osaka (34.69, 135.50) to Tokyo (35.69, 139.69): about 400 km."""
    assert haversine_km(34.69, 135.50, 35.69, 139.69) == pytest.approx(403, abs=8)


def test_haversine_handles_antipodes():
    half_circumference = 3.141592653589793 * EARTH_RADIUS_KM
    assert haversine_km(0.0, 0.0, 0.0, 180.0) == pytest.approx(half_circumference, rel=1e-9)


def test_haversine_is_symmetric():
    there = haversine_km(34.4, 135.3, 24.0, 121.0)
    back = haversine_km(24.0, 121.0, 34.4, 135.3)
    assert there == pytest.approx(back)


# --------------------------------------------------------------------------- #
# DR-4 radial wind profile
# --------------------------------------------------------------------------- #


def test_wind_inside_the_radius_of_maximum_wind_is_vmax():
    assert wind_at_point(JEBI_LIKE, 0.0) == 50.0
    assert wind_at_point(JEBI_LIKE, 15.0) == 50.0
    assert wind_at_point(JEBI_LIKE, 30.0) == 50.0  # exactly at RMW


def test_wind_at_each_threshold_radius_equals_that_threshold_speed():
    """The profile must pass exactly through 64, 50 and 34 kt at their radii."""
    assert wind_at_point(JEBI_LIKE, 60.0) == pytest.approx(64 * KT_TO_MS)
    assert wind_at_point(JEBI_LIKE, 120.0) == pytest.approx(50 * KT_TO_MS)
    assert wind_at_point(JEBI_LIKE, 240.0) == pytest.approx(34 * KT_TO_MS)


def test_wind_decays_monotonically_with_distance():
    distances = [0, 15, 30, 45, 60, 90, 120, 180, 240, 300]
    winds = [wind_at_point(JEBI_LIKE, float(d)) for d in distances]
    assert winds == sorted(winds, reverse=True)


def test_wind_beyond_the_34kt_radius_is_zero():
    assert wind_at_point(JEBI_LIKE, 240.1) == 0.0
    assert wind_at_point(JEBI_LIKE, 1000.0) == 0.0


def test_wind_interpolates_linearly_between_anchors():
    """Halfway between R64 (60 km) and R50 (120 km) is halfway in speed."""
    midpoint = wind_at_point(JEBI_LIKE, 90.0)
    expected = (64 * KT_TO_MS + 50 * KT_TO_MS) / 2
    assert midpoint == pytest.approx(expected)


def test_a_point_with_no_usable_radii_contributes_only_inside_rmw():
    bare = TrackPoint(t=T0, lat=34.4, lon=135.3, vmax_ms=40.0, rmw_km=25.0)
    assert wind_at_point(bare, 20.0) == 40.0
    assert wind_at_point(bare, 25.1) == 0.0


def test_a_decayed_storm_ignores_threshold_radii_above_its_vmax():
    """vmax 30 m/s is below 64 kt (32.9 m/s), so the R64 anchor is nonsense and
    must be dropped rather than producing a profile that rises with distance.
    """
    decaying = TrackPoint(
        t=T0, lat=34.4, lon=135.3, vmax_ms=30.0,
        rmw_km=40.0, r64_km=80.0, r50_km=150.0, r34_km=300.0,
    )
    assert wind_at_point(decaying, 80.0) < decaying.vmax_ms
    # 50 kt = 25.7 m/s is still below vmax, so R50 remains the first anchor.
    assert wind_at_point(decaying, 150.0) == pytest.approx(50 * KT_TO_MS)
    distances = [0.0, 40.0, 80.0, 150.0, 300.0, 400.0]
    winds = [wind_at_point(decaying, d) for d in distances]
    assert winds == sorted(winds, reverse=True)


def test_radii_inside_rmw_are_discarded_as_inconsistent():
    odd = TrackPoint(
        t=T0, lat=34.4, lon=135.3, vmax_ms=50.0,
        rmw_km=100.0, r64_km=50.0, r50_km=150.0, r34_km=250.0,
    )
    assert wind_at_point(odd, 100.0) == 50.0
    assert wind_at_point(odd, 150.0) == pytest.approx(50 * KT_TO_MS)


def test_wind_at_point_rejects_a_negative_distance():
    with pytest.raises(ValueError, match="distance_km"):
        wind_at_point(JEBI_LIKE, -1.0)


def test_wind_over_a_track_takes_the_maximum_over_all_points():
    """A region can be brushed by a weak early point and hit hard later."""
    track = [
        TrackPoint(t=T0, lat=30.0, lon=135.3, vmax_ms=60.0, rmw_km=30.0, r34_km=200.0),
        TrackPoint(t=T0, lat=34.4, lon=135.3, vmax_ms=45.0, rmw_km=30.0, r34_km=200.0),
    ]
    # Osaka Bay: far from the first point, inside RMW of the second.
    assert wind_at(34.4, 135.3, track) == 45.0


def test_wind_over_an_empty_track_is_zero():
    assert wind_at(34.4, 135.3, []) == 0.0


def test_a_region_far_from_the_track_sees_nothing():
    """Okinawa (26.2N, 127.7E) against a storm in Osaka Bay -- this is the
    territorial-carve-out case W3 relies on."""
    assert wind_at(26.2, 127.7, [JEBI_LIKE]) == 0.0


@pytest.mark.parametrize(
    "field, value",
    [("lat", 91.0), ("lat", -91.0), ("lon", -181.0), ("vmax_ms", -1.0), ("rmw_km", -1.0)],
)
def test_track_point_validates_its_inputs(field, value):
    kwargs = {"t": T0, "lat": 34.4, "lon": 135.3, "vmax_ms": 50.0, field: value}
    with pytest.raises(ValueError):
        TrackPoint(**kwargs)


def test_quadrant_mean_ignores_unreported_quadrants():
    """IBTrACS writes 0 for "not reported". Averaging those in would shrink
    the storm."""
    assert quadrant_mean(100.0, 100.0, 0.0, 0.0) == 100.0
    assert quadrant_mean(120.0, 80.0, 100.0, 100.0) == 100.0
    assert quadrant_mean(0.0, 0.0, 0.0, 0.0) == 0.0


# --------------------------------------------------------------------------- #
# DR-4 bands
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "wind_ms, band",
    [
        (0.0, 0), (16.9, 0),
        (17.0, 1), (24.9, 1),
        (25.0, 2), (32.9, 2),
        (33.0, 3), (41.9, 3),
        (42.0, 4), (49.9, 4),
        (50.0, 5), (80.0, 5),
    ],
)
def test_wind_bands_match_the_spec_boundaries(vuln, wind_ms, band):
    assert vuln.wind_band(wind_ms) == band


@pytest.mark.parametrize(
    "mmi, band",
    [
        (0.0, 0), (4.9, 0),
        (5.0, 1), (5.9, 1),
        (6.0, 2), (6.9, 2),
        (7.0, 3), (7.9, 3),
        (8.0, 4), (8.9, 4),
        (9.0, 5), (10.0, 5),
    ],
)
def test_mmi_bands_match_the_spec_boundaries(vuln, mmi, band):
    assert vuln.mmi_band(mmi) == band


def test_a_centroid_at_a_known_distance_lands_in_the_expected_band(vuln):
    """QA-2's headline: known centroid distance -> expected band.

    At 90 km from Jebi-like centre the profile gives the midpoint of 64 and
    50 kt = 29.3 m/s, which is band 2 (25-33 m/s).
    """
    wind = wind_at_point(JEBI_LIKE, 90.0)
    assert wind == pytest.approx(29.3, abs=0.1)
    assert vuln.wind_band(wind) == 2

    # Inside RMW: 50 m/s, the top band.
    assert vuln.wind_band(wind_at_point(JEBI_LIKE, 10.0)) == 5
    # Beyond R34: nothing.
    assert vuln.wind_band(wind_at_point(JEBI_LIKE, 500.0)) == 0


# --------------------------------------------------------------------------- #
# DR-5 damage ratios
# --------------------------------------------------------------------------- #


def test_emanuel_is_zero_at_and_below_the_threshold():
    assert emanuel_2011(25.7, 190.5) == 0.0
    assert emanuel_2011(10.0, 190.5) == 0.0


def test_emanuel_reaches_one_half_at_v_half():
    """v_half is by construction the speed at which the ratio is 0.5."""
    assert emanuel_2011(190.5, 190.5) == pytest.approx(0.5)
    assert emanuel_2011(76.0, 76.0) == pytest.approx(0.5)


def test_emanuel_increases_monotonically():
    ratios = [emanuel_2011(v, 190.5) for v in (26, 30, 40, 50, 70, 100, 150)]
    assert ratios == sorted(ratios)


def test_emanuel_rejects_a_v_half_below_the_threshold():
    with pytest.raises(ValueError, match="v_half"):
        emanuel_2011(50.0, 20.0)


def test_the_philippines_is_far_more_vulnerable_than_japan_at_the_same_wind(vuln):
    """v_half 76.0 vs 190.5 -- the single biggest driver of PH vs JP loss."""
    ph = vuln.wind_damage_ratio(50.0, "PHL")
    jp = vuln.wind_damage_ratio(50.0, "JPN")
    assert ph > jp * 10


def test_wind_damage_ratio_rejects_an_unknown_country(vuln):
    with pytest.raises(KeyError, match="IDN"):
        vuln.wind_damage_ratio(50.0, "IDN")


@pytest.mark.parametrize(
    "mmi, raw_ratio",
    [(5, 0.0), (6, 0.005), (7, 0.02), (8, 0.06), (9, 0.15), (10, 0.30)],
)
def test_eq_table_reproduces_the_spec_values_at_integer_mmi(vuln, mmi, raw_ratio):
    """Interpolation must not disturb the anchors DR-5 specifies. Taiwan has a
    country factor of 1.0, so the raw table value shows through."""
    assert vuln.eq_damage_ratio(float(mmi), "TWN") == pytest.approx(raw_ratio)


def test_eq_ratio_is_zero_below_mmi_5(vuln):
    assert vuln.eq_damage_ratio(4.9, "TWN") == 0.0
    assert vuln.eq_damage_ratio(1.0, "TWN") == 0.0


def test_eq_ratio_saturates_above_the_top_anchor(vuln):
    assert vuln.eq_damage_ratio(12.0, "TWN") == pytest.approx(0.30)


def test_eq_ratio_interpolates_between_anchors(vuln):
    """ShakeMap reports fractional MMI, so 6.5 must sit between 6 and 7."""
    half = vuln.eq_damage_ratio(6.5, "TWN")
    assert half == pytest.approx((0.005 + 0.02) / 2)


def test_eq_country_factor_halves_japan(vuln):
    assert vuln.eq_damage_ratio(8.0, "JPN") == pytest.approx(0.06 * 0.5)


def test_eq_step_function_when_interpolation_is_disabled(vuln):
    stepped = VulnerabilityModel.from_dict(
        {
            "wind": {
                "v_threshold_ms": 25.7,
                "v_half_ms": {"JPN": 190.5},
                "calibration_factor": {"JPN": 1.0},
            },
            "earthquake": {
                "interpolate": False,
                "mmi_damage_ratio": {"5": 0.0, "6": 0.005, "7": 0.02},
                "country_factor": {"JPN": 1.0},
            },
            "bands": {"wind_ms": [17], "mmi": [5]},
        }
    )
    assert stepped.eq_damage_ratio(6.9, "JPN") == pytest.approx(0.005)


def test_damage_ratio_dispatches_on_peril(vuln):
    assert vuln.damage_ratio(50.0, "WS", "PHL") == vuln.wind_damage_ratio(50.0, "PHL")
    assert vuln.damage_ratio(8.0, "EQ", "JPN") == vuln.eq_damage_ratio(8.0, "JPN")
    with pytest.raises(ValueError, match="FL"):
        vuln.damage_ratio(1.0, "FL", "JPN")


def test_a_calibration_factor_cannot_push_a_ratio_above_one():
    model = VulnerabilityModel.from_dict(
        {
            "wind": {
                "v_threshold_ms": 25.7,
                "v_half_ms": {"PHL": 30.0},
                "calibration_factor": {"PHL": 100.0},
            },
            "earthquake": {
                "mmi_damage_ratio": {"10": 0.3},
                "country_factor": {"PHL": 100.0},
            },
            "bands": {"wind_ms": [17], "mmi": [5]},
        }
    )
    assert model.wind_damage_ratio(200.0, "PHL") == 1.0
    assert model.eq_damage_ratio(10.0, "PHL") == 1.0


def test_the_committed_vulnerability_file_covers_every_in_scope_country(vuln):
    for country in ("JPN", "PHL", "TWN"):
        assert country in vuln.v_half_ms
        assert country in vuln.eq_country_factor


# --------------------------------------------------------------------------- #
# DR-3 IBTrACS parsing — the quirks QA-2 names
# --------------------------------------------------------------------------- #

# Real shape: uppercase headers, a units row, two storms, missing values as
# blanks. Trimmed to the columns the parser reads.
IBTRACS_CSV = """SID,SEASON,BASIN,NAME,ISO_TIME,LAT,LON,USA_WIND,TOKYO_WIND,USA_RMW,USA_R34_NE,USA_R34_SE,USA_R34_SW,USA_R34_NW,USA_R50_NE,USA_R50_SE,USA_R50_SW,USA_R50_NW,USA_R64_NE,USA_R64_SE,USA_R64_SW,USA_R64_NW
,year,,,,degrees_north,degrees_east,kts,kts,nmile,nmile,nmile,nmile,nmile,nmile,nmile,nmile,nmile,nmile,nmile,nmile,nmile
2018239N11161,2018,WP,JEBI,2018-09-03 18:00:00,31.5,134.0,100,90,15,130,120,100,110,70,65,55,60,35,30,25,30
2018239N11161,2018,WP,JEBI,2018-09-04 06:00:00,33.5,135.0,85,75,20,120,110,90,100,60,55,45,50,30,25,20,25
2018239N11161,2018,WP,JEBI,2018-09-04 12:00:00,34.8,135.5,70,,25,100,90,80,90,50,45,40,45,25,20,20,20
2018239N11161,2018,WP,JEBI,2018-09-05 00:00:00,38.0,137.0, , ,30, , , , , , , , , , , ,
2019278N16165,2019,WP,HAGIBIS,2019-10-12 09:00:00,34.0,138.5,95,85,20,150,140,120,130,80,75,65,70,40,35,30,35
"""


def test_parse_skips_the_units_row():
    """Row 2 carries units, not data. Parsing it would yield vmax "kts"."""
    rows = list(parse_ibtracs_csv(IBTRACS_CSV))
    assert all(row["SID"].strip() for row in rows)
    assert not any(row["LAT"].strip() == "degrees_north" for row in rows)
    assert len(rows) == 5  # four Jebi rows plus one Hagibis


def test_parse_handles_a_file_with_no_units_row():
    header, _units, *data = IBTRACS_CSV.strip().splitlines()
    rows = list(parse_ibtracs_csv("\n".join([header, *data]) + "\n"))
    assert len(rows) == 5


def test_parse_of_an_empty_or_header_only_file_yields_nothing():
    assert list(parse_ibtracs_csv("")) == []
    assert list(parse_ibtracs_csv("SID,ISO_TIME,LAT,LON\n")) == []
    assert list(parse_ibtracs_csv("SID,ISO_TIME,LAT,LON\n,,,\n")) == []


def test_track_is_filtered_by_sid_not_by_name():
    """SID is unique; NAME is not. This is the filter DR-3 insists on."""
    track = track_for_sid(IBTRACS_CSV, "2018239N11161")
    assert len(track) == 3  # the fourth Jebi row has no wind at all
    assert all(point.lat < 36.0 for point in track)  # no Hagibis point leaked in


def test_an_unknown_sid_raises_rather_than_returning_an_empty_track():
    with pytest.raises(ValueError, match="no usable track points"):
        track_for_sid(IBTRACS_CSV, "9999999N99999")


def test_track_for_sid_requires_a_sid():
    with pytest.raises(ValueError, match="sid is required"):
        track_for_sid(IBTRACS_CSV, "  ")


def test_usa_wind_is_converted_from_knots_to_metres_per_second():
    track = track_for_sid(IBTRACS_CSV, "2018239N11161")
    assert track[0].vmax_ms == pytest.approx(100 * KT_TO_MS)


def test_tokyo_wind_is_used_only_when_usa_wind_is_missing():
    """Row 3 has USA_WIND 70 and a blank TOKYO_WIND, so no factor applies."""
    track = track_for_sid(IBTRACS_CSV, "2018239N11161")
    assert track[2].vmax_ms == pytest.approx(70 * KT_TO_MS)

    tokyo_only = IBTRACS_CSV.replace(
        "2018-09-03 18:00:00,31.5,134.0,100,90,", "2018-09-03 18:00:00,31.5,134.0, ,90,"
    )
    point = track_for_sid(tokyo_only, "2018239N11161")[0]
    assert point.vmax_ms == pytest.approx(90 * TOKYO_TO_ONE_MINUTE * KT_TO_MS)


def test_rows_with_no_wind_at_all_are_dropped():
    """The last Jebi row has blanks for both wind columns."""
    track = track_for_sid(IBTRACS_CSV, "2018239N11161")
    assert all(point.vmax_ms > 0 for point in track)
    assert max(point.t for point in track).day == 4  # the 5 Sep row is gone


def test_radii_are_averaged_over_quadrants_and_converted_to_km():
    track = track_for_sid(IBTRACS_CSV, "2018239N11161")
    expected = ((130 + 120 + 100 + 110) / 4) * NM_TO_KM
    assert track[0].r34_km == pytest.approx(expected)
    assert track[0].rmw_km == pytest.approx(15 * NM_TO_KM)


def test_track_points_are_sorted_by_time():
    scrambled = IBTRACS_CSV.strip().splitlines()
    reordered = [scrambled[0], scrambled[1], scrambled[4], scrambled[2], scrambled[3]]
    track = track_for_sid("\n".join(reordered) + "\n", "2018239N11161")
    assert [p.t for p in track] == sorted(p.t for p in track)


def test_a_parsed_track_produces_plausible_wind_over_osaka():
    """End to end: CSV -> track -> wind -> band. Osaka Bay is near the 4 Sep
    12:00 position, so it should land in a damaging band."""
    track = track_for_sid(IBTRACS_CSV, "2018239N11161")
    wind = wind_at(34.69, 135.50, track)
    assert 25.0 < wind < 60.0
    assert VulnerabilityModel.load().wind_band(wind) >= 2


# --------------------------------------------------------------------------- #
# DR-4 ShakeMap
# --------------------------------------------------------------------------- #

SHAKEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<shakemap_grid xmlns="http://earthquake.usgs.gov/eqcenter/shakemap"
    event_id="us6000m0xl" shakemap_version="3">
  <event event_id="us6000m0xl" magnitude="7.5" lat="37.49" lon="137.24"/>
  <grid_specification lon_min="136.0" lat_min="36.5" lon_max="138.0" lat_max="38.0"
      nlon="3" nlat="3"/>
  <grid_field index="1" name="LON" units="dd"/>
  <grid_field index="2" name="LAT" units="dd"/>
  <grid_field index="3" name="PGA" units="pctg"/>
  <grid_field index="4" name="MMI" units="intensity"/>
  <grid_data>
136.0 38.0 12.0 6.1
137.0 38.0 28.0 7.4
138.0 38.0 8.0 5.5
136.0 37.5 20.0 6.8
137.0 37.5 60.0 8.9
138.0 37.5 14.0 6.2
136.0 36.5 6.0 5.0
137.0 36.5 18.0 6.5
138.0 36.5 5.0 4.6
  </grid_data>
</shakemap_grid>
"""


def test_shakemap_parses_cells_and_event_id():
    grid = parse_shakemap_grid(SHAKEMAP_XML)
    assert grid.event_id == "us6000m0xl"
    assert len(grid.cells) == 9


def test_shakemap_reads_the_mmi_column_by_name_not_by_position():
    """MMI is field 4 here, behind PGA. Assuming column 3 would read PGA as
    intensity and report an MMI of 60."""
    grid = parse_shakemap_grid(SHAKEMAP_XML)
    assert mmi_at(37.5, 137.0, grid) == pytest.approx(8.9)


def test_mmi_at_samples_the_nearest_cell():
    """Inside the grid, take the nearest cell."""
    grid = parse_shakemap_grid(SHAKEMAP_XML)
    assert mmi_at(37.52, 136.98, grid) == pytest.approx(8.9)
    assert mmi_at(36.51, 137.02, grid) == pytest.approx(6.5)
    assert mmi_at(36.51, 137.98, grid) == pytest.approx(4.6)


def test_mmi_at_returns_zero_outside_the_grid():
    """Nearest-cell sampling always returns *something*, so an unbounded grid
    hands a location thousands of km away its nearest corner cell. The real
    Noto grid did exactly that: MMI 2.9 for every Taiwanese and Philippine
    region, which then appear in the event and let FR-MATCH respond a
    Philippine treaty to a Japanese earthquake.
    """
    grid = parse_shakemap_grid(SHAKEMAP_XML)
    assert mmi_at(25.0, 121.5, grid) == 0.0  # Taipei
    assert mmi_at(14.6, 121.0, grid) == 0.0  # Metro Manila
    assert mmi_at(36.49, 138.02, grid) == 0.0  # just outside the corner


def test_grid_bounds_come_from_the_grid_specification():
    grid = parse_shakemap_grid(SHAKEMAP_XML)
    assert (grid.lon_min, grid.lat_min) == (136.0, 36.5)
    assert (grid.lon_max, grid.lat_max) == (138.0, 38.0)
    assert grid.contains(37.0, 137.0)
    assert not grid.contains(37.0, 150.0)


def test_grid_bounds_fall_back_to_the_cell_extent():
    """A grid file without a grid_specification must still be bounded, or the
    out-of-grid guard silently stops working."""
    without_spec = SHAKEMAP_XML.replace(
        '<grid_specification lon_min="136.0" lat_min="36.5" lon_max="138.0" lat_max="38.0"\n'
        '      nlon="3" nlat="3"/>',
        "",
    )
    grid = parse_shakemap_grid(without_spec)
    assert (grid.lon_min, grid.lon_max) == (136.0, 138.0)
    assert (grid.lat_min, grid.lat_max) == (36.5, 38.0)
    assert mmi_at(25.0, 121.5, grid) == 0.0


def test_grid_bounds_are_inclusive_at_the_edge():
    grid = parse_shakemap_grid(SHAKEMAP_XML)
    assert grid.contains(36.5, 136.0)
    assert grid.contains(38.0, 138.0)
    assert mmi_at(36.5, 136.0, grid) == pytest.approx(5.0)


def test_mmi_sampled_near_the_epicentre_lands_in_the_top_bands():
    grid = parse_shakemap_grid(SHAKEMAP_XML)
    vuln = VulnerabilityModel.load()
    assert vuln.mmi_band(mmi_at(37.49, 137.24, grid)) == 4  # 8.9 -> band 4
    assert vuln.mmi_band(mmi_at(36.5, 138.0, grid)) == 0  # 4.6 -> below 5


def test_shakemap_ignores_ragged_lines():
    broken = SHAKEMAP_XML.replace("138.0 36.5 5.0 4.6", "138.0 36.5")
    grid = parse_shakemap_grid(broken)
    assert len(grid.cells) == 8


def test_shakemap_requires_the_mmi_field():
    without_mmi = SHAKEMAP_XML.replace('<grid_field index="4" name="MMI" units="intensity"/>', "")
    with pytest.raises(ValueError, match="MMI"):
        parse_shakemap_grid(without_mmi)


def test_shakemap_requires_grid_data():
    empty = SHAKEMAP_XML.replace(
        SHAKEMAP_XML[SHAKEMAP_XML.index("<grid_data>") : SHAKEMAP_XML.index("</grid_data>")],
        "<grid_data>\n",
    )
    with pytest.raises(ValueError, match="grid_data"):
        parse_shakemap_grid(empty)


def test_an_empty_shakemap_grid_is_rejected():
    with pytest.raises(ValueError, match="no cells"):
        ShakeMapGrid(cells=())


# --------------------------------------------------------------------------- #
# The join: hazard -> damage ratio -> the loss engine's input
# --------------------------------------------------------------------------- #


def test_hazard_and_vulnerability_feed_the_loss_engine(vuln):
    """The loss engine takes injected ratios (FR-LOSS-1). This is the real
    production path that produces them."""
    from catsight_agent.tools.loss_engine import ExposureSlice, gross_loss

    regions = [
        Region("JP-27", "Osaka", "JPN", 34.69, 135.50),
        Region("JP-47", "Okinawa", "JPN", 26.21, 127.68),
    ]
    track = track_for_sid(IBTRACS_CSV, "2018239N11161")

    ratios = {
        region.code: vuln.wind_damage_ratio(wind_at(region.lat, region.lon, track), region.country)
        for region in regions
    }
    assert ratios["JP-27"] > 0.0
    assert ratios["JP-47"] == 0.0  # the storm never reached Okinawa

    exposures = [
        ExposureSlice("JP-27", "WS", "1000"),
        ExposureSlice("JP-47", "WS", "1000"),
    ]
    assert gross_loss(exposures, ratios) > 0


# --------------------------------------------------------------------------- #
# DR-3 parser robustness. Real IBTrACS extracts are untidy, so every one of
# these degradations has to drop a row rather than crash a run.
# --------------------------------------------------------------------------- #


def test_a_column_missing_from_the_header_entirely_is_treated_as_absent():
    """A trimmed extract without USA_WIND must fall back to TOKYO_WIND."""
    csv_text = (
        "SID,ISO_TIME,LAT,LON,TOKYO_WIND,USA_RMW\n"
        ",,degrees_north,degrees_east,kts,nmile\n"
        "2018239N11161,2018-09-04 06:00:00,33.5,135.0,75,20\n"
    )
    point = track_for_sid(csv_text, "2018239N11161")[0]
    assert point.vmax_ms == pytest.approx(75 * TOKYO_TO_ONE_MINUTE * KT_TO_MS)
    assert point.r34_km == 0.0  # no quadrant columns at all


def test_non_numeric_junk_in_a_numeric_column_is_treated_as_missing():
    """Occasional extracts carry stray text. float() must not propagate."""
    csv_text = (
        "SID,ISO_TIME,LAT,LON,USA_WIND,USA_RMW\n"
        ",,degrees_north,degrees_east,kts,nmile\n"
        "2018239N11161,2018-09-04 06:00:00,33.5,135.0,100,n/a\n"
        "2018239N11161,2018-09-04 12:00:00,34.0,135.5,bogus,20\n"
    )
    track = track_for_sid(csv_text, "2018239N11161")
    assert len(track) == 1  # the row with an unparseable wind is dropped
    assert track[0].rmw_km == 0.0  # "n/a" radius becomes absent, not an error


def test_a_file_with_only_a_header_and_units_row_yields_nothing():
    csv_text = "SID,ISO_TIME,LAT,LON,USA_WIND\n,,degrees_north,degrees_east,kts\n"
    assert list(parse_ibtracs_csv(csv_text)) == []


def test_a_row_with_an_unparseable_timestamp_is_not_mistaken_for_data():
    """This is how the units row is detected, so it must hold for any row
    whose ISO_TIME does not parse."""
    csv_text = (
        "SID,ISO_TIME,LAT,LON,USA_WIND\n"
        "2018239N11161,not-a-date,33.5,135.0,100\n"
        "2018239N11161,2018-09-04 06:00:00,33.5,135.0,100\n"
    )
    rows = list(parse_ibtracs_csv(csv_text))
    assert len(rows) == 1
    assert rows[0]["ISO_TIME"] == "2018-09-04 06:00:00"


def test_rows_with_a_missing_position_are_dropped():
    csv_text = (
        "SID,ISO_TIME,LAT,LON,USA_WIND\n"
        ",,degrees_north,degrees_east,kts\n"
        "2018239N11161,2018-09-04 06:00:00, ,135.0,100\n"
        "2018239N11161,2018-09-04 12:00:00,34.0, ,100\n"
        "2018239N11161,2018-09-04 18:00:00,34.5,135.5,100\n"
    )
    track = track_for_sid(csv_text, "2018239N11161")
    assert len(track) == 1
    assert track[0].lat == 34.5


def test_sentinel_missing_values_are_honoured():
    """IBTrACS also uses -999 style sentinels in some columns."""
    csv_text = (
        "SID,ISO_TIME,LAT,LON,USA_WIND,TOKYO_WIND\n"
        ",,degrees_north,degrees_east,kts,kts\n"
        "2018239N11161,2018-09-04 06:00:00,33.5,135.0,-999,75\n"
    )
    point = track_for_sid(csv_text, "2018239N11161")[0]
    assert point.vmax_ms == pytest.approx(75 * TOKYO_TO_ONE_MINUTE * KT_TO_MS)


def test_blank_rows_between_or_after_data_are_skipped():
    """CSV exports routinely end with a row of bare commas."""
    csv_text = (
        "SID,ISO_TIME,LAT,LON,USA_WIND\n"
        ",,degrees_north,degrees_east,kts\n"
        "2018239N11161,2018-09-04 06:00:00,33.5,135.0,100\n"
        ",,,,\n"
        "2018239N11161,2018-09-04 12:00:00,34.0,135.5,90\n"
        ",,,,\n"
    )
    rows = list(parse_ibtracs_csv(csv_text))
    assert len(rows) == 2
    assert len(track_for_sid(csv_text, "2018239N11161")) == 2
