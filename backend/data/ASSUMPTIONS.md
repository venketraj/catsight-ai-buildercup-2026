# Modelling assumptions

Every assumption the engine makes, with its source and how it gets validated.
The project requires this file to be updated as part of the change that
introduces an assumption, not afterwards.

The UI's Methodology page (UI-9) renders from this file. Nothing here is a
result; results live in `benchmarks/results/RESULTS.md`.

**Status key** — `SOURCED` published figure, cited · `DERIVED` follows from a
sourced figure or from the spec's own arithmetic · `JUDGEMENT` our choice,
defensible but ours · `UNVERIFIED` placeholder pending validation.

---

## 1. Money and arithmetic

| # | Assumption | Status | Notes |
|---|---|---|---|
| M1 | Money is `Decimal`, not float, quantised to 6 dp | DERIVED | Binary float evaluates the split case's `7.85 - 0.525` as 7.324999999999999, which rounds to 7.32 rather than the correct 7.33. FR-LOSS acceptance requires exact matches, so float is unusable. Asserted by `test_float_arithmetic_loses_the_split_cases_tie`. |
| M2 | Money rounds **half away from zero** | JUDGEMENT | The financial convention. Python's built-in `round` is banker's rounding, which sends a true 7.325 down to 7.32. |
| M3 | Portfolio currency is USD; FX is fixed and configurable | JUDGEMENT | `JPY_PER_USD=150`, `PHP_PER_USD=56`, `TWD_PER_USD=32`. Fixed rather than dated, because the portfolio is synthetic and a moving rate would add noise without adding realism. |
| M4 | Figures are in USD millions throughout the worked example | DERIVED | From `DOMAIN_PRIMER.md` section 4. |

## 2. Reinstatements and reinstatement premium (FR-LOSS-3)

| # | Assumption | Status | Notes |
|---|---|---|---|
| R1 | `RIP = (limit eroded by that occurrence / limit) x premium x rate`, **per occurrence**, pro rata as to amount, while reinstatement capacity remains | DERIVED | Derived in `docs/MONEY_MOMENT.md` section 4.1 by working backwards from the one-event figures the primer already publishes (our RIP 0.622, net 6.82). It is the only basis that reproduces them. |
| R2 | Reinstatement applies to **partial** erosion, not only to exhaustion | DERIVED | L2 is eroded 81.33% in the one-event case and still attracts RIP of 1.22 in the primer. An exhaustion-only rule would give zero. |
| R3 | Erosion beyond available reinstatement capacity is **paid** (if aggregate cover allows) but attracts **no** RIP | JUDGEMENT | Nothing is restored, so no reinstatement premium is due. This is what makes the split case's L1 RIP 2.00 rather than 2.94. |
| R4 | Aggregate cover per layer is `limit x (1 + reinstatements)` | JUDGEMENT | Standard. Exceeding it is an error, not a silent overrun. |
| R5 | RIP is due in the one-event case even though L1 is never drawn on again | JUDGEMENT | The primer charges it, which is consistent with automatic reinstatement on loss. Some wordings do not. Flagged for a practitioner in `MONEY_MOMENT.md` section 4.5 — it changes no figure in the demo, because both readings there have subsequent exposure. |

**Explicitly rejected**, with reasons in `MONEY_MOMENT.md` section 4.3:
RIP on *aggregate* ceded (charges 1.47 reinstatements where one exists) and RIP
sized by what the *following* occurrence draws (sizes the reinstatement by the
wrong occurrence).

## 3. Occurrence splitting (FR-LOSS-5)

| # | Assumption | Status | Notes |
|---|---|---|---|
| O1 | A window opens at the first loss not yet assigned and runs for the clause's hours | JUDGEMENT | Standard wording lets the cedent elect the start but not before the first recorded loss. |
| O2 | A loss belongs to the window in which it **first occurs** | SOURCED | *UnipolSai v Covéa* (English Court of Appeal, 2024): "occur" means "first occur". |
| O3 | Windows may not overlap | SOURCED | Standard Cat XL wording. Falls out of O1 structurally. |
| O4 | Each occurrence carries its own retention | SOURCED | `DOMAIN_PRIMER.md` section 5a. |
| O5 | The 54.4 → 35.0 + 19.4 split is illustrative | JUDGEMENT | Taken from the primer as an example. In production the split derives from the event's loss timeline; whether a cedent would elect *this* placement is a judgement call flagged in `MONEY_MOMENT.md` section 4.5. |

## 4. Hazard — wind (DR-4)

| # | Assumption | Status | Notes |
|---|---|---|---|
| W1 | Intensity at a centroid is the **maximum** over all track points | JUDGEMENT | Per DR-4. A region brushed early and struck later takes the worse of the two. |
| W2 | Radial profile is piecewise linear through RMW, R64, R50, R34, then zero | JUDGEMENT | Per DR-4. A crude but transparent substitute for a parametric wind field. |
| W3 | Quadrant radii are averaged over **reported quadrants only** | JUDGEMENT | IBTrACS writes 0 for "not reported"; averaging those in would shrink the storm. |
| W4 | Anchors whose speed is at or above the point's `vmax`, or whose radius is inside RMW, are **discarded** | JUDGEMENT | A decaying storm can report an R64 while its vmax has fallen below 64 kt. Keeping that anchor would make wind *rise* with distance. |
| W5 | A point with no usable outer radius contributes `vmax` inside RMW and zero beyond | JUDGEMENT | Conservative: the observation simply says nothing about the outer field. |
| W6 | Knots convert at 0.514444 m/s | SOURCED | Exact definition. |
| W7 | Distances are great-circle (haversine) on a sphere of radius 6371.0088 km | JUDGEMENT | IUGG mean radius. Ellipsoidal distance is unnecessary at this resolution. |
| W8 | Region geometry is reduced to a single **centroid** | JUDGEMENT | Per DR-4. Material simplification: a large prefecture is represented by one point, so a storm clipping its edge is under- or over-counted. Listed as a limitation in the README. |

## 5. Hazard — earthquake (DR-4)

| # | Assumption | Status | Notes |
|---|---|---|---|
| E1 | MMI at a centroid is the **nearest** ShakeMap grid cell | JUDGEMENT | Per DR-4. No interpolation between cells. |
| E2 | The MMI column is located by its `grid_field` declaration, not by position | DERIVED | ShakeMap products vary in field count and order; MMI sits behind PGA in the Noto product. Assuming column 3 would read PGA as intensity. |

## 6. Vulnerability — wind (DR-5)

| # | Assumption | Status | Notes |
|---|---|---|---|
| V1 | Emanuel (2011) sigmoid: `f = vn³/(1+vn³)`, `vn = max(V - 25.7, 0)/(V_half - 25.7)` | SOURCED | V in m/s, 1-minute sustained. |
| V2 | `V_half` = 190.5 m/s (JPN, TWN), 76.0 m/s (PHL) | SOURCED | Eberenz et al. 2021, CC BY 4.0. The single biggest driver of the PH/JP loss difference. |
| V3 | Per-country `calibration_factor`, default 1.0 | UNVERIFIED | Tuned in benchmark B5 and reported there. Until B5 runs, all factors are 1.0. |
| V4 | A damage ratio is capped at 1.0 after calibration | JUDGEMENT | A calibration factor must not produce a loss above the sum insured. |

## 7. Vulnerability — earthquake (DR-5)

| # | Assumption | Status | Notes |
|---|---|---|---|
| Q1 | MMI → mean damage ratio: 5 → 0, 6 → 0.5%, 7 → 2%, 8 → 6%, 9 → 15%, ≥10 → 30% | UNVERIFIED | **Illustrative.** Informed by Hazus damage-state repair ratios but not taken from them directly. `REQUIREMENTS.md` section 14.2 flags this. Must be labelled illustrative wherever displayed. |
| Q2 | Values are **interpolated linearly** between integer MMI anchors | JUDGEMENT | ShakeMap reports fractional MMI (6.7, not 7). At integer MMI the interpolated value equals the spec table exactly, so this refines the table rather than departing from it. Switchable via `interpolate: false`. |
| Q3 | Country factor 0.5 for JPN, 1.0 for TWN and PHL | UNVERIFIED | Reflects Japanese seismic building standards. Calibrated in B5. |

## 8. IBTrACS parsing (DR-3)

| # | Assumption | Status | Notes |
|---|---|---|---|
| I1 | Row 2 is a **units row** and is skipped | SOURCED | IBTrACS v04r01 format. Detected by content (unparseable `ISO_TIME`) rather than by position alone, so a file without one still parses. |
| I2 | Storms are selected by **SID**, never by NAME | SOURCED | Names repeat across basins and seasons. |
| I3 | `USA_WIND` (1-minute, kt) is preferred | SOURCED | Matches the 1-minute basis Emanuel's function expects. |
| I4 | Where `USA_WIND` is absent, `TOKYO_WIND` (10-minute) x **1.12** | JUDGEMENT | 10-minute → 1-minute conversion. A commonly used factor, but a choice; it affects JMA-only track segments. |
| I5 | Missing values are blanks, bare spaces, `NA`, `NaN`, `-999` or `-9999` — never 0 | SOURCED | A 0 radius means "reported as zero", which differs from "not reported". |
| I6 | Radii are nautical miles, converted at 1.852 km | SOURCED | Exact definition. |
| I7 | Track points with no wind reading at all are **dropped** | JUDGEMENT | The point cannot contribute to a wind field. |
| I8 | Track points with no position are **dropped** | JUDGEMENT | As above. |

## 9. Synthetic portfolio (DR-1)

| # | Assumption | Status | Notes |
|---|---|---|---|
| X1 | Region exposure weights are **approximate resident populations**, not GIROJ sums insured or e-Stat dwelling counts | JUDGEMENT | DR-1 asks for the latter two; we do not hold those datasets. Populations are public general knowledge and give a plausible distribution. The portfolio is synthetic by rule (C-8), so nothing downstream claims these are real exposure. Replacing them is a one-table change. **Benchmark B5 must not be run on these weights** — it uses a market-level proxy, which is a separate input. |
| X2 | All **22** ISO 3166-2:TW entries are carried | DERIVED | DR-1 says "21 counties/cities"; ISO lists 22. Carrying all 22 rather than dropping one to hit a number. |
| X3 | `TSI_PER_WEIGHT_USD_M = 15,000` | JUDGEMENT | Makes the synthetic Japanese market about **US$18.7tn** of sum insured — the right order for Japan, whose real insured value is order US$20–30tn — and puts Sakura at 14% share on about US$2.6tn. A round number chosen for that realism. |
| X4 | Market shares are **explicit per cedent**, not drawn from the seed | JUDGEMENT | A cedent's size is structural. If it moved with the seed, the demo's headline figures would move with it. Sakura is pinned at 14%. |
| X5 | The modelled Jebi gross loss for Sakura lands at **54.45** against the worked example's 54.40 | DERIVED | Falls out of X3 and X4 rather than being fitted. It is what lets the live demo reproduce the documented figures, and it is asserted by `test_the_jebi_replay_reproduces_the_worked_example_gross`. If `build_events.py`'s real IBTrACS track moves it, re-derive X3 once rather than loosening the test. |
| X6 | **The model under-predicts Jebi's actual market loss by roughly 25x** | UNVERIFIED | Jebi's paid claims were about ¥1,068bn (~US$9.5bn). The curve gives a market-wide damage ratio of ~0.00024 against a reality of ~0.0003–0.0005 — so the curve is roughly right at market level, but the modelled footprint only reaches 16 regions at low ratios, while real losses were broader and driven partly by flood and surge the model does not carry. **This is a B5 finding to report honestly, not something to tune away in the portfolio.** The lever is `calibration_factor` (V3), and it stays at 1.0 until B5 derives it. |
| X7 | Programmes are sized against a **reference major-event loss**, not against sum insured | JUDGEMENT | DR-1 asks for retentions "plausible relative to TSI", but a Cat XL is bought against a return-period loss. Sakura retains 10.0 of a 54.4 event — 18.4% of the event, and 0.0004% of its TSI, which is entirely normal for a cat cover. Every filler programme attaches in the same 15–35% band, so the book is internally coherent. |
| X8 | Each cedent's reference loss scales linearly with its sum insured from Sakura's | JUDGEMENT | Ignores that a Philippine book is far more wind-vulnerable than a Japanese one at the same wind speed. It only has to make the filler book's structure sensible, and it keeps the generator free of any dependency on the vulnerability curves. |
| X9 | Philippine earthquake penetration is **25%** of wind | JUDGEMENT | Reflects thin EQ take-up. Illustrative. |
| X10 | Region **centroids** are approximate, to about a tenth of a degree | JUDGEMENT | Committed so the hazard chain is testable and the demo runs without the ~40 MB Natural Earth download. `build_regions.py` recomputes them from Natural Earth 10m admin-1 polygons; a recomputed centroid more than ~50 km away is a reconciliation failure worth investigating. |
| X11 | **Haiyan is not offered in the demo** (it stays in the data and the API) | JUDGEMENT | Traced 2026-10-10: the Philippine book is sized by population at the same rate per person as Japan (X1, X3), about US$868bn for two cedents, and the PHL Emanuel `v_half` of 76 m/s (Eberenz et al. 2021, an economic-damage calibration) gives 64% damage in Leyte. Gross claims come out at about US$94bn against Swiss Re's ~US$1.5bn insured (88% protection gap). Tuning the PHL factors to hit 1.5bn would fit the model to the answer shown, so it was not done. Fix belongs to B5: per-country insurance penetration from an independent source plus an insured-loss wind calibration. |

## 10. Treaty wordings (DR-2, FR-ENDORSE)

| # | Assumption | Status | Notes |
|---|---|---|---|
| Y1 | Wording prose is **original**, written in the register of catastrophe excess-of-loss contracts | DERIVED | RESEARCH_FINDINGS §D9 permits publicly filed wordings as a *style* reference only. Nothing is copied. Every document states on its face that it is synthetic, fictional and of no legal effect. |
| Y2 | Ground-truth **page numbers are read back out of the rendered PDF**, not predicted | DERIVED | QA-4 scores citation page accuracy at ≥ 95%, which is meaningless if the answer key's own pages were guessed. A layout change can no longer silently invalidate the key. |
| Y3 | The hours clause is phrased in **four registers** across the eight wordings | JUDGEMENT | `plain`, `spelled`, `period`, `words`. W8 carries it inside a definition with **no digits at all**. A single register would let a prompt tuned to one layout score 100%. |
| Y4 | **Ten decoy passages** mention a number of hours without being the hours clause | JUDGEMENT | Notification deadlines, cash-call windows, inspection notice, arbitration service, premium interest. They let QA-4 measure precision rather than recall alone. Each is recorded in the answer key, so a flag citing one scores as the false positive it is. |
| Y5 | **Boilerplate** clauses carry neither ground-truth fields nor decoy status | JUDGEMENT | Realistic noise — a real treaty is mostly boilerplate. Counting it either way would distort both recall and precision. It is also what brings each document honestly into DR-2's 6–15 page range rather than padding. |
| Y6 | The scanned endorsement sits on **W4** | JUDGEMENT | DR-2 does not pin W4's hours clause, so an override there adds a planted feature without contradicting the documented W1–W8 table — and it is not W1, whose terms the money moment depends on. |
| Y7 | The endorsement page has **no text layer** | DERIVED | Rendered as a raster image. Asserted by `test_the_endorsement_page_has_no_extractable_text`; the page yields under 120 characters, all of it the rendered footer. An endorsement the text extractor hands over for free exercises nothing. |
| Y8 | W4's **effective** windstorm hours window is 168, not the 72 its base clause states | DERIVED | FR-ENDORSE-3 makes the endorsement operative. The treaty record carries the effective term plus `endorsement{base_value, endorsed_value, source}` for provenance, and the answer key records both rows with distinct `source` values. |
| Y9 | **The "blind set" is a structural holdout, not a blind set** | JUDGEMENT | ⚠️ DR-2 and risk #5 in the win-readiness review ask for wordings written by someone **outside the prompt work**, so an accuracy score is not self-graded. This cannot be satisfied by the same author who writes the wordings, the answer key and the extraction prompts. What the generator produces is a holdout built from a different seed, ordering and phrasing — genuinely useful for catching a prompt tuned to one layout, and genuinely **not** a blind set. **Report it as a holdout. Never quote it as a blind-set score** until a human outside the prompt work has written one. |

## 11. Event replay files (DR-3)

| # | Assumption | Status | Notes |
|---|---|---|---|
| Z1 | **`duration_h` is the damaging window, not the track lifetime** | JUDGEMENT | The most consequential decision in `build_events.py`. Jebi's IBTrACS track spans **213 hours** from genesis to dissipation; using that as the duration would breach every hours clause and make the FR-WORD-1 flag fire on every replay, meaninglessly. The duration is the span of track points at which at least one in-scope region sees wind ≥ 25.7 m/s. |
| Z2 | The threshold is the **vulnerability curve's own** 25.7 m/s | DERIVED | Below it the Emanuel damage ratio is zero by construction, so those hours cannot contribute loss and therefore cannot lengthen a loss occurrence. Not an independently chosen number. |
| Z3 | Resulting durations: Jebi **9 h**, Haiyan **12 h**, Hagibis **27 h** | DERIVED | All comfortably inside a 72-hour clause, consistent with the DOMAIN_PRIMER's statement that Jebi's damage was "well inside 72". The primer says "about 24 hours"; the computed 9 h reflects 6-hourly track resolution over the covered regions. Both readings agree on what matters — no split. |
| Z4 | An earthquake's `duration_h` is **0** | JUDGEMENT | A mainshock is instantaneous, so no hours clause can split it. A real aftershock sequence would extend it; **not modelled.** Noto's 1 Jan 2024 sequence included substantial aftershocks, so a production system would need to decide whether they form one occurrence. |
| Z5 | MMI is **0 outside the ShakeMap grid extent** | DERIVED | Nearest-cell sampling always returns *something*. Unbounded, the Noto grid assigned MMI 2.9 to every Taiwanese and Philippine region — all band 0, so harmless to the loss, but they then appear in `event.regions`, and **FR-MATCH uses an event's regions to decide which treaties respond**. A Philippine treaty would have matched a Japanese earthquake. Bounds come from `grid_specification`, falling back **per key** to the cells' own extent. |
| Z6 | The ShakeMap grid URL is **resolved through the USGS event API**, not hardcoded | DERIVED | The download URL carries a product-version timestamp. Noto's ShakeMap is at version 10, so a pinned URL goes stale on the next revision. |
| Z7 | RESEARCH_FINDINGS records Noto's max MMI as 8.9; ShakeMap v10 gives **8.793** | SOURCED | The product has been revised since that note was written. The build takes the figure from the data, not the note. |
| Z8 | Facts and reference losses are **never model inputs** | DERIVED | Quoted from RESEARCH_FINDINGS §D8 for credibility and the B5 back-test only. Every event file carries that statement in its own `disclaimer` field, so the file cannot be read as claiming them as output. |
| Z9 | Source data is **cache-first, never fetched implicitly** | JUDGEMENT | The 114 MB CSV and 7.6 MB grid live in git-ignored `data/raw/`. A missing source fails with the exact URL and target path rather than producing a half-event; `--fetch` downloads explicitly. A zero-byte file counts as missing, because a truncated download is worse than an absent one. |

## 12. Ingestion and retrieval (FR-INGEST, S3 local half)

| # | Assumption | Status | Notes |
|---|---|---|---|
| R1 | Chunking is **by clause**, falling back to **by page** | DERIVED | FR-INGEST-2. Every flag cites a clause number and a page, and the verifier quote-matches against the stored chunk, so a chunk straddling two clauses can produce a quote that verifies against the chunk while citing the wrong clause — worse than failing, because it looks correct. |
| R2 | A clause is classified from its **heading**, not its body | JUDGEMENT | The heading is the drafter's own classification; body keywords are noise, and the decoys exploit exactly that. "Inspection of Records" mentions a period, "Loss Advices and Cash Calls" mentions a retention, "Definition: Business Day" mentions territory — a body-keyword classifier mistypes all three, and FR-WORD's retrieval would then pull them as material. |
| R3 | Structural headings (`Definitions`, `Endorsement`, `Schedule`, `Interpretation`) **defer to the body** | JUDGEMENT | They describe structure, not subject matter. This is what lets W8's operative hours clause — hidden inside a clause titled "Definitions" — and the scanned endorsement's override both classify correctly. |
| R4 | Body classification uses a **narrow phrase set**, not keywords | DERIVED | `consecutive hours` rather than `hours`. Every decoy says "within 72 hours of", "settle within 168 hours" and so on; **none** says "consecutive hours", which is the operative phrase in a loss-occurrence definition. That makes it a safe discriminator where a bare "hours" is not. |
| R5 | `clause_type` is a **filter of convenience, never a gate** | DERIVED | Retrieval ranks by vector similarity and uses `clause_type` only to reorder. Filtering hard on it would lose any clause whose heading does not advertise its subject. |
| R6 | A chunk **retains its own heading** in its text | JUDGEMENT | The heading is semantically informative, so it helps retrieval, and it is harmless to quote-matching. It also means a chunk body is never empty, which is why there is no empty-body guard. |
| R7 | An image-only page **without** a transcription is **skipped, not emitted empty** | JUDGEMENT | The caller is responsible for noticing: a silently dropped endorsement is how an override gets missed. A page yielding under 120 characters after furniture-stripping is treated as image-only; the scanned endorsement yields 45. |
| R8 | Local vectors are **768-dimensional**, matching production | DERIVED | C-2. Same shape locally and in production, so an index built on one is not silently incompatible with the other. |
| R9 | Vector pre-filters are **equality only** | SOURCED | C-11, a Firestore constraint. The interface therefore offers only `treaty_id`, so a query written against the in-memory store behaves identically against Firestore. |
| R10 | Ranking ties break on `chunk_id` | JUDGEMENT | Without it, equal scores reorder between runs and QA-5's ADK tool-trajectory check becomes flaky. |
| R11 | **`DeterministicEmbedder` has no semantics. Never quote a retrieval metric measured against it.** | JUDGEMENT | ⚠️ It is a hashing bag-of-words, so it matches on shared vocabulary and nothing else — "hours clause" and "loss occurrence" are the same concept and it scores them at zero (asserted by a test). It exists so chunking, retrieval, the tool contract and the QA harness can be built and tested without a model call. **Recall and precision figures for the deck come from `GeminiEmbedder` against a live Firestore index and from nowhere else.** |
| R12 | QA-3 comparison is **typed, not textual** | JUDGEMENT | `"72"`, `72` and `72.0` are the same hours clause; `["WS","EQ"]` and `["EQ","WS"]` are the same peril list. A string compare fails all of these and reports an accuracy far below the truth — the sort of error that gets a threshold loosened when the extractor was right. Coercion is narrow: a scalar never matches a list, and booleans never compare as numbers. |
| R13 | A field **absent** from an extraction counts as **wrong**, not skipped | JUDGEMENT | Otherwise omitting the hard fields is the easiest route to a high score. |
| R14 | Citation pages are scored **separately** from field values | DERIVED | QA-4 scores page accuracy at ≥ 95% on its own line. A field extracted correctly but cited to the wrong page is a different failure: the number is right and the audit trail is wrong, which in a regulated setting is arguably worse. Averaging the two would hide both. |
| R15 | Transcription reads are reported **separately** from text-layer reads | DERIVED | At two transcription fields out of 186, a uniform average would hide a total failure to read the scan. A model that reads clean text well and scans badly has a very different weakness from one that is uniformly mediocre. |
| R16 | Each field is claimed on **exactly one page** in the answer key | DERIVED | A field claimed on two pages cannot be cited correctly, which makes QA-4's page accuracy unscoreable for it. W8 originally did this — its hours clause appeared in both Clause 5 and the Definitions clause — so Clause 5 now cross-references rather than restating. Asserted by a test. |

## 13. Citation verification (FR-VERIFY, QA-10)

| # | Assumption | Status | Note |
|---|---|---|---|
| VF1 | Verification is scoped to the **cited location**: treaty, then clause, then page | JUDGEMENT | A quote that exists somewhere in the corpus is not verified; it must exist where the citation says. This is what makes the badge `verified - {treaty}, p.{page}, cl.{clause}` something an analyst can check by turning to the page. |
| VF2 | A clause spanning a page break verifies on **any** page it spans | JUDGEMENT | Via `pages_spanned`. Refusing a citation to page 4 of a clause that starts on page 3 would be a false withhold. |
| VF3 | **Boilerplate text cannot detect a wrong-treaty citation** | DERIVED | All eight wordings share 11 boilerplate clauses, so a quote from W1's Schedule clause genuinely appears in W2 - citing it to W2 is not an error to catch, because it is not an error. QA-10's wrong-treaty corruption is therefore built only from treaty-unique text, which is also what a real flag cites: the operative clause, never the furniture. Found while writing QA-10, not predicted. |
| VF4 | Mid-word truncation fails deterministically; a **clean** partial quote does not | JUDGEMENT | A cut quote cannot be checked against the page, so word-boundary alignment is enforced. But a clean, genuinely present, misleadingly partial quote **is** a substring and must pass FR-VERIFY-1 - catching the misleading omission is FR-VERIFY-2's job. Cheap checks first, the model only on what survives. |
| VF5 | The chunk's own `source` is authoritative for the badge, not the citation's claim | JUDGEMENT | QA-12 needs `verified against transcription` to be true of the stored chunk. What the model asserts about provenance is not load-bearing. |
| VF6 | Normalisation undoes what `pypdf` mangles and nothing more | JUDGEMENT | NFKC (ligatures), curly quotes, en/em dashes, soft hyphens, zero-width characters, hyphenated line breaks, whitespace collapse, casefold. Punctuation is **not** stripped wholesale: "not, covered" must not match "not covered", and "shall not apply" must not match "shall apply". |
| VF7 | No FR-VERIFY-2 number exists yet | UNVERIFIED | The semantic check needs `MODEL_REASON`. Every `semantic_pass` in the local suite comes from a stub (`AlwaysSupports`), so **QA-10's result covers the deterministic half only**. The semantic half cannot be measured until the models resolve on a real project. Same class of gap as R11. |

## 13b. Live extraction (FR-INGEST-1, S3 online half)

Measured 2026-10-05 against `techno-crackers-catsight`. Full report in
`docs/RESULTS.md`.

| # | Assumption | Status | Note |
|---|---|---|---|
| G1 | `response_schema` cannot express exclusive bounds | SOURCED | Verified live: `Field(gt=0)` emits `exclusiveMinimum`, which Gemini's `Schema` rejects before a request is sent. `gemini_response_schema()` relaxes it to `minimum`. **Consequence: the schema no longer forbids a zero limit** - FR-INGEST-3's validator is what rejects it, so that validation is load-bearing, not defensive. |
| G2 | An open-ended map is the one shape the model will not populate | DERIVED | `field_pages: dict[str, FieldProvenance]` returned `{}` and `endorsement: dict[...]` returned `null` on every run - while the model was correctly *applying* the endorsement it refused to describe. A list of records and a typed object both populated immediately. Design rule: lists and named fields, never free-form maps, in any `response_schema`. |
| G3 | Money in the answer key is in **millions** | JUDGEMENT | Unstated, the model returns raw currency units and every money field scores wrong while being arguably correct. The instruction pins the unit. |
| G4 | `limit` is the maximum payment, not the top of the layer | SOURCED | The model computed `limit = stated_limit - retention` on 3 of 8 treaties, producing non-contiguous programmes. Caught by FR-INGEST-3, fixed by defining the term and asking the model to check contiguity before answering. |
| G5 | The hours clause is a definition, independent of coverage | JUDGEMENT | The answer key records the period the clause *states* for each peril even where that peril is not covered. The first instruction said "0 where none applies", and the model correctly reasoned Flood was uncovered and returned 0. The convention is right - an hours clause is a definition - but it has to be said. |
| G6 | `exclusions` means perils, not classes of business, and not sanctions | JUDGEMENT | A sanctions clause limits payment; it does not exclude a cause of loss. Facultative/financial-guarantee/compulsory-pool terms are scope-of-business. Both were extracted as exclusions until the instruction scoped the field. Defensible domain reasoning, but it is a **scoping decision matching this answer key** and the blind set must test whether it generalises. |
| G7 | `temperature=0` does not give determinism | SOURCED | Two runs over the same PDFs with identical settings disagreed on T-005 and T-008. Any claim of reproducibility must be measured over repeats, not assumed. QA-11 requires 5 identical runs; that has not been done. |
| G8 | Quota is indistinguishable from inaccuracy | SOURCED | An unretried 429 scores as a wrong answer. One whole run (33.9%) was pure throttling. Retries cover 429/503/500 and transport drops; 400 is never retried. Vertex quota throttles 8 sequential PDF requests on this project. |
| G9 | **QA-3's 100% is an upper bound, not an expectation** | UNVERIFIED | Six prompt revisions ran against this answer key. The defects fixed were real, but the score is on tuned data. Quote it as "100% on the eight planted wordings after six revisions against them". The general number requires Y9. |
| G10 | Citation coverage is the real provenance gap | SOURCED | Page accuracy is 93.8% where a citation was offered, but only 77.4% of fields carry one at all. C-7 wants every claim cited. Reported as two numbers because accuracy alone flatters an extractor that cites only easy fields. |
| G11 | A citation counts only if its quote is on the cited page | JUDGEMENT | Response to G10 (2026-10-10). Every field now carries a verbatim quote, string-matched against the cited page's text layer (`ingest/provenance.py`). Failures get one targeted repair request; whatever still fails is labelled unverified and earns no QA-4 credit. A wrong clause number on the right page is corrected from the chunk, not failed. Gate: ≥ 95% of fields verified. |
| G12 | A scanned page can only be *transcribed*, never *verified* | JUDGEMENT | With no text layer there is nothing to match a quote against. Such citations are labelled `transcribed` and shown as such - honest, but weaker than a string match. A human spot-check of W4 page 7 is the only real check. |

## 13c. Data of record and method governance (2026-10-10)

| # | Assumption | Status | Note |
|---|---|---|---|
| D1 | **The treaty book is the data of record; wordings are reconciled against it** | JUDGEMENT | Decided with the team. The engine prices from the book (as a reinsurer's treaty system would). Gemini-extracted wording terms are compared field by field (`ingest/reconcile.py`); a *verified* disagreement is flagged with its page and quote, never applied automatically. Keeps a misread number out of the money. |
| D2 | The runtime never runs a generator | JUDGEMENT | The book is seeded once (`data/book/`, Firestore via `ingest/seed_cloud.py`) and read through a `DataStore`. A test fails if the committed book drifts from the generator, so re-seeding is enforced rather than remembered. |
| D3 | An unverified disagreement is not a discrepancy | JUDGEMENT | Reconciliation reports `unverified`, not `differs`, when the wording's value has no checkable citation. |
| D4 | Method changes are new versions, never edits | JUDGEMENT | `data/methodology.json` carries version, effective date, approval status and sourced conventions; the damage curve is embedded per version in Firestore. Each analysis is stamped with the version in force. A market-practice change is a new approved version with a later effective date. |
| R12 | **RAG-first extraction replaces whole-document extraction** | SOURCED | 2026-10-10, Firestore vector search live: 99.5% field accuracy (185/186), governing clause retrieved for 186/186 fields, 185/187 citations verified, 8/8 structurally valid, 57 s for 8 wordings (whole-document: ~25 min). Per term group: top-4 clauses by `treaty_id` pre-filter, endorsement chunks always added, Gemini reads only those clauses with `thinking_level=LOW`, every answer cites a retrieved chunk and its quote is matched before acceptance, one retry for a rejected quote. |
| R13 | The scanned page is transcribed once at ingest | JUDGEMENT | Gemini transcribes image-only pages into a `source="transcription"` chunk, which is then embedded and retrieved like any clause. Citations to it remain `transcribed`, never `verified` (G12). |
| R14 | The 100% retrieval hit rate is on 8 tuned wordings | UNVERIFIED | Same caveat as G9: prompts were adjusted after seeing failures on this answer key (territory sub-national codes; "avoidance of doubt" carve-backs are not exclusions). Both rules are general market practice, but the blind set (Y9) is what would support a general claim. |
| R15 | Embedding quota, not the model, bounds first ingestion | SOURCED | `gemini-embedding-001` per-minute quota on this project sustains ~12-14 requests/min; 32 parallel requests failed with 429. Embeddings are paced (EMBED_RPM) and cached by text hash, so identical boilerplate is embedded once (124 vectors for 252 clauses) and re-runs cost nothing. |
| R16 | Run-to-run variation persists at temperature 0 | SOURCED | Consecutive RAG runs differed on one field each (T-001/T-003/T-004 exclusions and territory, then T-002 exclusions). Consistent with G7; QA-11's repeat-run measure is still owed. |
| A1 | **The agent graph is an ADK 2.11 `Workflow` of function nodes** | JUDGEMENT | 2026-10-10. Verified live: START -> event_intel -> exposure_analyst -> wording_checker -> verifier -> reporter, one ADK event per node. Model calls happen inside nodes with structured output, not as an LlmAgent tool-calling loop: the retrieval queries are fixed per FR-WORD, so a tool loop would add calls and latency without adding judgement. An LlmAgent tool loop is the natural upgrade for free-form follow-up questions (FR-ASK). |
| A2 | AG-2 exposure_analyst is deterministic | JUDGEMENT | Matching and the loss engine run as tools with no model in the loop - C-6 taken literally. The agent label is kept because it is a graph node with its own stage and tool frames. |
| A3 | First live run, Jebi (2026-10-10) | SOURCED | 52 s, 13 model calls (4 wording, 5 support checks, 3 revisions, 1 report). Verified: T-004 storm-surge exclusion (HIGH, p.2 cl.8) against Jebi's record 329 cm Osaka tide; T-001 reinstatement terms. Report figures 100% traceable to the engine (0 unsupported). |
| A4 | The support check judges the wording, not the event | JUDGEMENT | The first live run withheld a correct hours flag because it mentioned Jebi's 9-hour duration, "not in the clause". Event facts come from the event record and are given; the check now judges only what a claim says about the wording. |
| A5 | The wording checker is told the as-if basis | JUDGEMENT | A live run flagged T-004's PERIOD as HIGH because Jebi's 2018 date is outside the 2026 period - but replays are deliberately as-if on today's book. The agent now receives the basis explicitly. |
| A6 | Observed event facts are checked against exclusions explicitly | SOURCED | Without an explicit step, one run missed the storm-surge exclusion entirely. With "check each observed fact against exclusions" in the prompt: 3/3 consecutive live runs raised exactly T-004 EXCLUSION HIGH, verified, no false flags, $0.0081-0.0083 each. Tuned on Jebi - other events still need checking. |
| A7 | Cached replay is a recording of a real run, labelled as such | JUDGEMENT | Every complete live agent run overwrites `data/replays/{event}.json`; playback compresses it to ~6 s and opens with a notice naming the recording time and live duration. Served on request, in CACHED_REPLAY_ONLY mode, and on the cap-hit path instead of an error. Tests write recordings to a temporary folder only (conftest), so a fake-model run can never become demo evidence. |
| A8 | Measured cost per live analysis is about $0.01 | SOURCED | From response token counts x EXECUTION_PLAN 4.1 prices: $0.0069-0.0114 across five Jebi runs (5-8 model calls). Below the NFR-4 budget of $0.05. |
| M1 | **No real event in the data produces a material hours-clause split** | SOURCED | 2026-10-10. Jebi's damaging window is 9 h and Hagibis's 27 h - below every allowed window (24-240 h). Noto's real M5.9 aftershock (USGS us6000m2ny, +193.8 h, a genuine second occurrence under every clause in the book) peaks at MMI 4.0 at our centroids, below the MMI-5 damage threshold: $0.00 at stake on all 10 Japanese treaties. Step 4c closed on that evidence. |
| M2 | The loss timeline dates each region by the track's closest approach | JUDGEMENT | Wind: time of the nearest IBTrACS point to the region centroid (Jebi spans 18:00Z 3 Sep - 18:00Z 4 Sep). Quake: the shock time. Coarse (3-6 h track steps) but real; it is what the timing what-if splits. |
| M3 | Hypothetical cuts are labelled HYPOTHETICAL everywhere | JUDGEMENT | The what-if may cut the real timeline at an analyst-chosen moment (offered only from the timeline's own timestamps, e.g. between Jebi's two real landfalls). It is never presented as what the wording produces. |
| M4 | **The Courtroom argues the storm-surge exclusion, not the hours clause** | JUDGEMENT | Decided with the team: it is triggered by a real verified HIGH flag (T-004 clause 8) on a real fact (Osaka's 329 cm record tide) - FR-COURT-1's "exclusion flag whose applicability depends on an event fact". The hours clause stays in the What-if panel. |
| M5 | The surge share is a bounded ASSUMPTION (0-50%) | JUDGEMENT | Our data does not separate wind from surge damage. Each counsel chooses a share as a pricing position; the engine prices it; the label says it is an assumption, not a finding. A loss adjuster's split would replace it. |
| M7 | **An excluded loss counts in the insurer's net cost** | DERIVED | 2026-10-11. The excluded share leaves the treaty, not the insurer, which pays it in full. The engine's `cedent_net_cost` (retention + RIP) covers the programme only, so the exclusion scenario adds `excluded_loss` to it. Before this, a 30% surge exclusion on T-004 showed the insurer *saving* 1.94m; it actually costs it +15.51m, the mirror of the reinsurers' −15.51m. Asserted in `test_scenario.py`. Worked-example figures (QA-1, QA-11) are unchanged: they have no exclusion. |
| M8 | **The Courtroom argues a verified HIGH or MEDIUM exclusion flag** | SOURCED | 2026-10-11. Five live Jebi runs raised the same T-004 storm-surge exclusion, verified it in 4, and rated it HIGH once and MEDIUM three times. The HIGH-only gate therefore opened the Courtroom in 1 of 5 runs on an identical, verified clause. Severity is the agent's judgement; the verified quote is not. HIGH is still preferred on an equal swing, and LOW is not argued. Asserted in `test_courtroom.py`. |
| M6 | Counsel quotes are verified for faithful use, not for merits | JUDGEMENT | Reusing the flag verifier dropped both sides in the first live run (it demanded one clause prove a whole argument). FR-COURT-3 now: exact quote match in code, plus a check that the quote says what counsel uses it to say; merits go to the arbiter. Live: 2 of 3 runs had both sides verified; in the others one side was correctly dropped for misusing a quote. |
| D5 | As built, book and wordings agree on every field | SOURCED | The existing extraction reconciles with zero differences once cited. The reconciliation therefore has nothing to show in the demo unless a realistic discrepancy is planted (open decision). |

## 14. Data sources and licences (DR-6)

| Source | Use | Licence |
|---|---|---|
| NOAA **IBTrACS** v04r01 WP | Typhoon tracks | Cite Knapp et al. 2010, doi:10.25921/82ty-9e16 |
| **USGS** ShakeMap | Earthquake MMI | Public domain — credit U.S. Geological Survey |
| **Natural Earth** 10m admin-1 | Region geometry and centroids | Public domain |
| **JMA** | Event facts | "Source: Japan Meteorological Agency website" |
| **e-Stat** | Dwelling counts for exposure calibration | 出典：政府統計の総合窓口(e-Stat) |
| **GIROJ / GIAJ / JER** | Calibration and B5 back-test references | Cited only, not redistributed |
| **Eberenz et al. 2021** | Wind `V_half` by country | CC BY 4.0 |
| SEC EDGAR contracts | Style reference for wordings only — paraphrased, never copied | — |

Portfolio, cedents and treaty wordings are **entirely synthetic**. Events are
real, and the referenced market losses are real; those are used for
credibility and the B5 back-test only, **never as model inputs**.

## 15. Outstanding — to validate, not blocking

1. `calibration_factor` (V3) and the EQ country factors (Q3) are 1.0 / 0.5 placeholders until B5 runs. Calibrate on one event, test on the other, and report misses honestly.
2. The EQ MMI table (Q1) should be checked against published Hazus repair ratios before it is cited as anything but illustrative.
3. The 10-minute to 1-minute wind factor (I4) deserves a source rather than convention.
4. Centroid representation (W8) is the largest structural simplification in the hazard chain. Quantify its effect on at least one event before claiming regional accuracy.
5. Baseline manual-effort figures are hypotheses until the B1 run.
6. The portfolio exposure weights (X1) should be rebuilt on GIROJ and e-Stat figures before any claim about regional accuracy is made.
7. X6 is the single most important honest disclosure in the proof pack: report the under-prediction and the calibration separately.
8. **R11, partly closed.** `GeminiEmbedder` now runs live: 768 dims, correct ranking against a planted decoy, but margins differing 8x by query phrasing (`RESULTS.md` section 4). Still outstanding: no recall or precision figure over the full corpus. Original note: Chunking, ranking and the QA harness are tested; the embedder they are tested against is not semantic. Nothing about recall, precision or extraction accuracy can be reported until `GeminiEmbedder` runs against a live index.
9. Z4: decide whether Noto's aftershock sequence should form one occurrence or several before the earthquake path is presented as complete.
10. **Y9 is the second: the holdout set is not a blind set.** A human outside the prompt work needs to write three wordings with planted issues the prompt author never sees. Until then, the holdout score is reported as a holdout score.
11. **VF7: QA-10's result is the deterministic half only.** Every `semantic_pass` in the suite comes from a stub, so the FR-VERIFY-2 check is unmeasured. Report QA-10 as "100% of mechanically corrupted citations withheld, 0 false withholds" - which is what was tested - and not as citation accuracy in general.
12. **G9 is now the most important disclosure of all: QA-3's 100% is on data the prompt was tuned against.** Six revisions, each driven by the previous run's failures on this same answer key. Report it with that sentence attached, and treat the blind set (Y9) as the number that would support a general claim.
