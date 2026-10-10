"""Admin-1 region reference table — DR-1 / DR-4.

ISO 3166-2 codes, names and a relative exposure weight per region, for Japan,
Taiwan and the Philippines.

Two things live here and nothing else:

  * the **code and name** list, which is stable reference data rather than
    anything derived, so it is committed rather than downloaded; and
  * a **relative exposure weight**, used only to distribute a synthetic
    portfolio across regions in a plausible shape.

`build_regions.py` reconciles these codes against Natural Earth 10m admin-1
and adds the centroids and geometry. A code here that Natural Earth does not
carry is a reconciliation failure, not something to paper over.

## On the weights

`REQUIREMENTS.md` DR-1 asks for calibration against GIROJ earthquake sums
insured by prefecture and e-Stat dwelling counts. **We do not have those
datasets, so these weights are not them.** They are approximate resident
populations (in hundreds of thousands), which are public general knowledge and
give a defensibly plausible distribution of insured value.

That is sufficient and honest, because the portfolio is synthetic by rule
(C-8): nothing downstream claims these weights are real exposure. They exist
to make the demo's geography sensible, not to model a market.

Replacing them with GIROJ and e-Stat figures is a drop-in change — one table,
no code — and is tracked as assumption V3/X1 in `data/ASSUMPTIONS.md`.
Benchmark B5's market-level back-test is where real weights start to matter,
and it should not be run on these.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "RegionRef", "JAPAN", "TAIWAN", "PHILIPPINES", "ALL_REGIONS",
    "by_country", "CENTROIDS", "centroid", "as_hazard_regions",
]


@dataclass(frozen=True)
class RegionRef:
    code: str
    name: str
    country: str
    weight: float  # relative exposure weight; see the module docstring


# --------------------------------------------------------------------------- #
# Japan — all 47 prefectures (ISO 3166-2:JP)
# --------------------------------------------------------------------------- #

JAPAN: tuple[RegionRef, ...] = tuple(
    RegionRef(code, name, "JPN", weight)
    for code, name, weight in [
        ("JP-01", "Hokkaido", 51.0),
        ("JP-02", "Aomori", 12.0),
        ("JP-03", "Iwate", 12.0),
        ("JP-04", "Miyagi", 23.0),
        ("JP-05", "Akita", 9.0),
        ("JP-06", "Yamagata", 10.0),
        ("JP-07", "Fukushima", 18.0),
        ("JP-08", "Ibaraki", 28.0),
        ("JP-09", "Tochigi", 19.0),
        ("JP-10", "Gunma", 19.0),
        ("JP-11", "Saitama", 73.0),
        ("JP-12", "Chiba", 63.0),
        ("JP-13", "Tokyo", 140.0),
        ("JP-14", "Kanagawa", 92.0),
        ("JP-15", "Niigata", 22.0),
        ("JP-16", "Toyama", 10.0),
        ("JP-17", "Ishikawa", 11.0),
        ("JP-18", "Fukui", 7.5),
        ("JP-19", "Yamanashi", 8.0),
        ("JP-20", "Nagano", 20.0),
        ("JP-21", "Gifu", 19.0),
        ("JP-22", "Shizuoka", 36.0),
        ("JP-23", "Aichi", 75.0),
        ("JP-24", "Mie", 17.0),
        ("JP-25", "Shiga", 14.0),
        ("JP-26", "Kyoto", 25.0),
        ("JP-27", "Osaka", 88.0),
        ("JP-28", "Hyogo", 54.0),
        ("JP-29", "Nara", 13.0),
        ("JP-30", "Wakayama", 9.0),
        ("JP-31", "Tottori", 5.5),
        ("JP-32", "Shimane", 6.6),
        ("JP-33", "Okayama", 19.0),
        ("JP-34", "Hiroshima", 28.0),
        ("JP-35", "Yamaguchi", 13.0),
        ("JP-36", "Tokushima", 7.0),
        ("JP-37", "Kagawa", 9.0),
        ("JP-38", "Ehime", 13.0),
        ("JP-39", "Kochi", 6.8),
        ("JP-40", "Fukuoka", 51.0),
        ("JP-41", "Saga", 8.0),
        ("JP-42", "Nagasaki", 13.0),
        ("JP-43", "Kumamoto", 17.0),
        ("JP-44", "Oita", 11.0),
        ("JP-45", "Miyazaki", 11.0),
        ("JP-46", "Kagoshima", 16.0),
        ("JP-47", "Okinawa", 15.0),
    ]
)

# --------------------------------------------------------------------------- #
# Taiwan — all 22 counties and cities (ISO 3166-2:TW)
#
# DR-1 says "21 counties/cities". ISO lists 22, so all 22 are carried and the
# count deviation is logged as assumption X2 rather than one being dropped to
# hit a number.
# --------------------------------------------------------------------------- #

TAIWAN: tuple[RegionRef, ...] = tuple(
    RegionRef(code, name, "TWN", weight)
    for code, name, weight in [
        ("TW-NWT", "New Taipei", 40.0),
        ("TW-TXG", "Taichung", 28.0),
        ("TW-KHH", "Kaohsiung", 27.0),
        ("TW-TPE", "Taipei", 25.0),
        ("TW-TAO", "Taoyuan", 23.0),
        ("TW-TNN", "Tainan", 18.5),
        ("TW-CHA", "Changhua", 12.5),
        ("TW-PIF", "Pingtung", 8.0),
        ("TW-YUN", "Yunlin", 6.6),
        ("TW-HSQ", "Hsinchu County", 5.8),
        ("TW-MIA", "Miaoli", 5.4),
        ("TW-CYQ", "Chiayi County", 4.8),
        ("TW-NAN", "Nantou", 4.8),
        ("TW-ILA", "Yilan", 4.5),
        ("TW-HSZ", "Hsinchu City", 4.5),
        ("TW-KEE", "Keelung", 3.6),
        ("TW-HUA", "Hualien", 3.2),
        ("TW-CYI", "Chiayi City", 2.6),
        ("TW-TTT", "Taitung", 2.1),
        ("TW-KIN", "Kinmen", 1.4),
        ("TW-PEN", "Penghu", 1.1),
        ("TW-LIE", "Lienchiang", 0.13),
    ]
)

# --------------------------------------------------------------------------- #
# Philippines — a 30-province subset (ISO 3166-2:PH)
#
# DR-1 permits "a subset of about 30 provinces". The subset is chosen for
# population and for typhoon exposure, and deliberately includes the provinces
# Haiyan struck in 2013 (Leyte, Samar, Eastern Samar, Northern Samar, Cebu,
# Iloilo, Capiz, Antique, Aklan) so the haiyan-2013 replay has exposure to
# land on.
# --------------------------------------------------------------------------- #

PHILIPPINES: tuple[RegionRef, ...] = tuple(
    RegionRef(code, name, "PHL", weight)
    for code, name, weight in [
        ("PH-00", "Metro Manila", 135.0),
        ("PH-CAV", "Cavite", 43.0),
        ("PH-BUL", "Bulacan", 37.0),
        ("PH-LAG", "Laguna", 34.0),
        ("PH-CEB", "Cebu", 33.0),
        ("PH-RIZ", "Rizal", 33.0),
        ("PH-PAN", "Pangasinan", 32.0),
        ("PH-BTG", "Batangas", 29.0),
        ("PH-NEC", "Negros Occidental", 26.0),
        ("PH-PAM", "Pampanga", 24.0),
        ("PH-NUE", "Nueva Ecija", 23.0),
        ("PH-ILI", "Iloilo", 21.0),
        ("PH-CAS", "Camarines Sur", 20.0),
        ("PH-QUE", "Quezon", 20.0),
        ("PH-LEY", "Leyte", 18.0),
        ("PH-ISA", "Isabela", 17.0),
        ("PH-BUK", "Bukidnon", 15.0),
        ("PH-TAR", "Tarlac", 15.0),
        ("PH-ALB", "Albay", 14.0),
        ("PH-BOH", "Bohol", 14.0),
        ("PH-NER", "Negros Oriental", 14.0),
        ("PH-CAG", "Cagayan", 13.0),
        ("PH-ZSI", "Zamboanga del Sur", 11.0),
        ("PH-PLW", "Palawan", 11.0),
        ("PH-MSR", "Misamis Oriental", 10.0),
        ("PH-WSA", "Samar", 8.0),
        ("PH-SOR", "Sorsogon", 8.0),
        ("PH-CAP", "Capiz", 8.0),
        ("PH-NSA", "Northern Samar", 6.0),
        ("PH-EAS", "Eastern Samar", 5.0),
        ("PH-AKL", "Aklan", 6.0),
        ("PH-ANT", "Antique", 6.0),
    ]
)

ALL_REGIONS: tuple[RegionRef, ...] = JAPAN + TAIWAN + PHILIPPINES

_BY_COUNTRY = {"JPN": JAPAN, "TWN": TAIWAN, "PHL": PHILIPPINES}


def by_country(country: str) -> tuple[RegionRef, ...]:
    if country not in _BY_COUNTRY:
        raise KeyError(f"no regions for country {country!r}; have {sorted(_BY_COUNTRY)}")
    return _BY_COUNTRY[country]


# --------------------------------------------------------------------------- #
# Approximate centroids
#
# Separate from the weights above because their provenance differs: the
# weights are synthetic, these are real geography, approximated.
#
# Accurate to roughly a tenth of a degree, which is well inside the error
# already introduced by representing a whole prefecture or province by one
# point (assumption W8). They exist so the hazard chain is testable and the
# demo runs without the ~40 MB Natural Earth download.
#
# `build_regions.py` recomputes these from Natural Earth 10m admin-1 polygons
# and overwrites `data/regions.json`. A code whose recomputed centroid sits
# more than ~50 km from the value here is a reconciliation failure worth
# looking at, not a rounding difference.
# --------------------------------------------------------------------------- #

CENTROIDS: dict[str, tuple[float, float]] = {
    # Japan
    "JP-01": (43.3, 142.8), "JP-02": (40.8, 140.8), "JP-03": (39.6, 141.3),
    "JP-04": (38.5, 140.9), "JP-05": (39.8, 140.4), "JP-06": (38.4, 140.1),
    "JP-07": (37.4, 140.3), "JP-08": (36.3, 140.3), "JP-09": (36.7, 139.8),
    "JP-10": (36.5, 138.9), "JP-11": (36.0, 139.4), "JP-12": (35.5, 140.2),
    "JP-13": (35.7, 139.4), "JP-14": (35.4, 139.3), "JP-15": (37.5, 138.9),
    "JP-16": (36.6, 137.2), "JP-17": (36.7, 136.7), "JP-18": (35.8, 136.2),
    "JP-19": (35.6, 138.6), "JP-20": (36.1, 138.1), "JP-21": (35.8, 137.0),
    "JP-22": (34.9, 138.4), "JP-23": (35.0, 137.1), "JP-24": (34.5, 136.3),
    "JP-25": (35.2, 136.1), "JP-26": (35.3, 135.5), "JP-27": (34.6, 135.5),
    "JP-28": (35.0, 134.8), "JP-29": (34.3, 135.9), "JP-30": (33.9, 135.4),
    "JP-31": (35.4, 133.9), "JP-32": (35.0, 132.6), "JP-33": (34.9, 133.8),
    "JP-34": (34.6, 132.8), "JP-35": (34.2, 131.6), "JP-36": (33.9, 134.3),
    "JP-37": (34.2, 134.0), "JP-38": (33.7, 132.9), "JP-39": (33.5, 133.4),
    "JP-40": (33.6, 130.6), "JP-41": (33.3, 130.1), "JP-42": (33.0, 129.6),
    "JP-43": (32.6, 130.8), "JP-44": (33.2, 131.4), "JP-45": (32.1, 131.3),
    "JP-46": (31.4, 130.6), "JP-47": (26.3, 127.8),
    # Taiwan
    "TW-TPE": (25.07, 121.55), "TW-NWT": (25.00, 121.55), "TW-KEE": (25.13, 121.74),
    "TW-TAO": (24.95, 121.25), "TW-HSZ": (24.81, 120.97), "TW-HSQ": (24.70, 121.10),
    "TW-MIA": (24.49, 120.90), "TW-TXG": (24.18, 120.90), "TW-CHA": (23.99, 120.50),
    "TW-NAN": (23.90, 120.95), "TW-YUN": (23.70, 120.30), "TW-CYI": (23.48, 120.45),
    "TW-CYQ": (23.45, 120.55), "TW-TNN": (23.10, 120.25), "TW-KHH": (22.80, 120.50),
    "TW-PIF": (22.40, 120.60), "TW-ILA": (24.70, 121.70), "TW-HUA": (23.80, 121.40),
    "TW-TTT": (22.90, 121.05), "TW-PEN": (23.57, 119.58), "TW-KIN": (24.43, 118.33),
    "TW-LIE": (26.15, 119.95),
    # Philippines
    "PH-00": (14.60, 121.00), "PH-CAV": (14.30, 120.90), "PH-BUL": (14.85, 120.95),
    "PH-LAG": (14.20, 121.35), "PH-CEB": (10.40, 123.80), "PH-RIZ": (14.60, 121.25),
    "PH-PAN": (15.95, 120.45), "PH-BTG": (13.90, 121.05), "PH-NEC": (10.40, 123.00),
    "PH-PAM": (15.05, 120.65), "PH-NUE": (15.55, 121.00), "PH-ILI": (10.90, 122.55),
    "PH-CAS": (13.60, 123.30), "PH-QUE": (14.00, 122.10), "PH-LEY": (10.80, 124.90),
    "PH-ISA": (16.90, 121.70), "PH-BUK": (8.05, 125.05), "PH-TAR": (15.50, 120.55),
    "PH-ALB": (13.25, 123.60), "PH-BOH": (9.85, 124.15), "PH-NER": (9.65, 123.05),
    "PH-CAG": (18.00, 121.75), "PH-ZSI": (7.85, 123.30), "PH-PLW": (9.80, 118.75),
    "PH-MSR": (8.60, 124.85), "PH-WSA": (11.80, 124.90), "PH-SOR": (12.90, 124.00),
    "PH-CAP": (11.45, 122.70), "PH-NSA": (12.35, 124.65), "PH-EAS": (11.65, 125.45),
    "PH-AKL": (11.70, 122.35), "PH-ANT": (11.10, 122.05),
}


def centroid(code: str) -> tuple[float, float]:
    """(lat, lon) for a region code."""
    if code not in CENTROIDS:
        raise KeyError(f"no centroid for region {code!r}")
    return CENTROIDS[code]


def as_hazard_regions() -> tuple:
    """The reference table as `hazard.Region` objects, ready for `wind_at`."""
    from catsight_agent.tools.hazard import Region

    return tuple(
        Region(r.code, r.name, r.country, *centroid(r.code)) for r in ALL_REGIONS
    )
