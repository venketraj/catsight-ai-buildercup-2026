# CatSight — Business Impact & Benchmarking

> **Purpose:** to quantify what CatSight saves (time and money), explain how we prove it, and give the numbers for the deck and README.
>
> Labels:
> - **[SOURCED]** = backed by RESEARCH_FINDINGS
> - **[HYPOTHESIS]** = our estimate, to be validated by practitioner interviews and benchmark B1
> - **[CALC]** = arithmetic on the above
>
> **Rule for the deck:** say "measured" only for figures produced by the benchmarks in §3. Present everything else as "estimated".

---

## 1. Where the value comes from

| Value driver | What changes | Type |
|---|---|---|
| **V1. Analyst time per event** | First-view preparation goes from days of spreadsheet work to minutes of automated work plus a human review | Direct cost saving |
| **V2. Speed to decision** | Leadership gets a portfolio-specific view **within hours**. Industry reference points: modelling firms' estimates arrive in 4–20 days, PERILS in 6 weeks, Verisk PCS Japan in up to 90 days [SOURCED] | Decision value (reserving, retro or back-up cover, communication to the board, rating agencies and investors) |
| **V3. Wording-driven error avoidance** | Hours clauses (72, 96, 120 or 168h in real contracts) and exclusions change which layers pay. Missing them can mis-state a single program's loss by tens of percent | Risk reduction |
| **V4. Access** | 48% of insurers don't license cat models, and about 60% have cat teams of five or fewer people [SOURCED, Aon 2025]. CatSight gives them a first view at near-zero marginal cost | Market reach |

**Be honest in the pitch:** V1 (labour) is real but modest per firm. **V2 and V3 are the big-ticket value.** One avoided mis-estimate can outweigh years of labour savings.

---

## 2. Baseline vs CatSight: time and cost model

### 2.1 Baseline manual "first view" per significant event [HYPOTHESIS]

Assumed reference firm: a mid-size reinsurer with about 100 APAC cat treaties, about 25 of them exposed to the event.

| Step | Manual today (person-hours) | With CatSight (person-hours) |
|---|---|---|
| 1. Gather event facts (track, intensity, affected areas) | 2–4 | ~0 (automated, cited) |
| 2. Identify exposed treaties (territory, peril, period) | 3–6 | ~0 (automated) |
| 3. Assemble cedent exposure by region | 6–12 | ~0 (already in the system)* |
| 4. Estimate gross loss and apply layers | 6–12 | ~0 (deterministic engine) |
| 5. Wording review of exposed treaties (25 × 0.4–0.8 h) | 10–20 | 1.5–4 (review only the **flagged** treaties) |
| 6. Compile report, peer review, sign-off | 3–6 | 2–4 (review and approve the draft) |
| **Total effort** | **30–60 h** | **3.5–8 h** |
| **Elapsed time** | **2–4 business days** | **Same day (< 4 h)**, with the automated run taking minutes |

\* This assumes exposure data is already loaded, as it would be in production. Data onboarding is a one-time cost and is excluded here.

**Saving per significant event [CALC]:** about **26–52 person-hours (≈ 85–87%)**, and elapsed time drops **from days to hours**.

### 2.2 Annualised [CALC]

| Input | Assumption [HYPOTHESIS] |
|---|---|
| Significant APAC events needing a full first view | 4–8 per year |
| Minor or near-miss events needing a check | 10–20 per year, at about 25% of full effort (manual 7.5–15 h vs CatSight 1–2 h) |
| Loaded cost per analyst or underwriter hour (Singapore) | **US$100**, with a range of 70–150. **Replace with your own figure.** |
| FTE hours per year | 1,700 |

| | Low | High |
|---|---|---|
| Hours saved: significant events | 4 × 26 = 104 | 8 × 52 = 416 |
| Hours saved: minor events | 10 × 6 = 60 | 20 × 13 = 260 |
| **Total hours saved per year** | **≈ 165 h (≈ 0.1 FTE)** | **≈ 675 h (≈ 0.4 FTE)** |
| **Labour value at $100/h** | **≈ $16.5k** | **≈ $67.5k** |
| CatSight running cost (Gemini about $0.03 per analysis × ~1,500 runs, plus serverless infrastructure) | ≈ $0.2–1k per year | |

Production integration, support and licensing costs are **not estimated** here.

### 2.3 Wording-risk illustration [CALC, from DOMAIN_PRIMER §5]

This uses the same $54.4M loss on Sakura's program, comparing one occurrence with an hours-clause split into two ($35.0M + $19.4M):

| Layer | One event | Two events | Difference |
|---|---|---|---|
| L1 (20 xs 10) | $20.0M | $29.4M | +47% |
| L2 (30 xs 30) | $24.4M | $5.0M | −80% |
| Cedent retention | $10M | $20M | ×2 |

For a reinsurer holding **10% of L2 only**, the first view swings between **$2.44M and $0.50M**: a $1.94M (80%) difference on **one program**, caused by one clause.

Across a portfolio with several such programs, the swing in reserving and communication can reach several million dollars per event. That is why V3 matters more than V1.

### 2.4 Market context for "impact" [SOURCED]

- Singapore: reinsurance premiums of S$27.6bn (2023, about 21% of Asia's market). **16 of the top 25 global reinsurers** have their regional hub there. About 30 or more MAS-licensed reinsurers.
- Asia-Pacific protection gap: **91% of 2023 economic losses (US$65bn) were uninsured** (MAS). Faster, cheaper analytics support capacity growth.
- Jebi's insured loss grew from early estimates of **$3–5bn to about $13bn** (≈3×). Early views are uncertain, so a tool must be transparent about its assumptions and show its drivers. CatSight does this.

**Suggested deck line (once B1/B2 are measured):** "On our test portfolio, CatSight produced a cited first view in **X minutes vs Y hours manually (−Z% effort)**. That is roughly 165–675 analyst-hours a year for a mid-size reinsurer, and it catches the wording that can swing a layer's loss by up to 80%."

---

## 3. Benchmarking: how we prove it

There is **no formal industry standard** for a "first-view" exposure report. We therefore benchmark three ways:

- **(a)** against a **measured manual baseline** on the *same* data;
- **(b)** against **ground truth we planted** in the synthetic data;
- **(c)** against **real-world reference points**: published claims figures and industry estimate timelines.

### 3.1 Benchmark suite

| ID | Benchmark | Compared against | Metric | Target | Who and how |
|---|---|---|---|---|---|
| **B1** | Manual control run (time and motion) | Manual process on the same synthetic portfolio and wordings, using spreadsheets and PDFs | Person-minutes per step; elapsed time | Show ≥ 80% effort reduction | **Human.** One person runs Jebi manually with a stopwatch per step (§2.1 steps). Ideally the domain expert does the wording step. Record it in `benchmarks/b1_manual_log.csv`. |
| **B2** | CatSight timing | B1 | p50/p95 end-to-end latency, per-stage latency, analyst review time | p95 ≤ 90 s automated; review ≤ 4 h | Automated from `analyses.metrics` (≥ 5 runs × 4 events), plus timed human review |
| **B3** | Extraction accuracy | `ground_truth.json` (planted) | Field-level accuracy | ≥ 95% | Automated (QA-3) |
| **B4** | Wording-flag quality | Planted features + decoys | Recall, precision, citation page accuracy | ≥ 90% / ≥ 80% / ≥ 95% | Automated (QA-4) |
| **B5** | Back-test for realism | **Real paid claims:** Jebi GIAJ ¥1,067.8bn (fire ¥920.2bn); Noto JER ¥108.0bn (residential earthquake) [SOURCED] | Ratio of the modelled market-level loss to actual | Within ±50% (an order-of-magnitude first view). **Calibrate on one event, test on the other** | Automated script: run the hazard and damage method on a **market-level** exposure proxy (GIROJ EQ sums insured; e-Stat dwellings × average sum insured). Report results honestly, including misses. |
| **B6** | Cost per analysis | Labour cost of B1 | Tokens → $ per analysis | ≤ $0.05 | Automated from token logs |
| **B7** | Timeliness vs industry | Modeller ranges 4–20 days; PERILS 6 weeks; PCS ≤ 90 days [SOURCED] | Elapsed time to first view | Hours vs days or weeks | Presented as a comparison of **purpose** (portfolio first view vs industry index). **It is not like-for-like**; say so on the slide |
| B8 (SHOULD) | Usability | 2–3 testers | Task success; 1–5 ease rating; time to first insight | ≥ 4/5 | Human, with notes in `benchmarks/b8_usability.md` |

### 3.2 B1 protocol (manual control run)

1. Give the tester the same inputs CatSight has: the treaty PDFs, an exposure CSV export, the event facts sheet and the damage-ratio table.
2. Task: "Produce a first-view report: impacted treaties, layer losses, our net, and wording issues."
3. Time each of the six steps in §2.1. Record errors found later, such as a missed hours clause or a wrong layer.
4. The **domain expert** separately times the wording review for all 8 treaties (step 5).
5. Compare with B2 plus the human review time of the CatSight output.
6. **Limitations to state:** small sample, a tester who knows the data, synthetic portfolio. Triangulate with the practitioner interviews (§4).

### 3.3 Results table (fill in after running; use in the deck and README)

| Metric | Manual (B1) | CatSight (B2–B6) | Δ |
|---|---|---|---|
| Effort per event (person-h) | _ | _ | _% |
| Elapsed time to first view | _ | _ | _ |
| Extraction accuracy | n/a | _% | |
| Wording-flag recall / precision | _ (issues found manually) | _% / _% | |
| Citation accuracy | n/a | _% | |
| Back-test Jebi / Noto (model ÷ actual) | n/a | _ / _ | |
| Cost per analysis | $_ (labour) | $_ (compute) | |

---

## 4. Practitioner validation (replaces the [HYPOTHESIS] tags)

Ask 1–2 practitioners (about 20 minutes each). Use their answers to update §2.1 and §2.2:

1. After a significant APAC cat event, how long until leadership gets a first portfolio view? How many people work on it?
2. Which steps take longest: event data, exposure, layers, or wording?
3. How often has wording (hours clause, exclusions, territory) changed the estimate materially? Can you give an example?
4. How many events per year trigger this work, both full and quick checks?
5. Which tools do you use today: vendor models, spreadsheets, or in-house?
6. What would you need to trust an AI-generated first view?

Record the answers as anonymised quotes in `benchmarks/interviews.md` and get permission to quote. **Never include employer-confidential details.**

---

## 5. Impact slide (deck draft)

**Headline:** "From days to minutes — with the clause that changes the number."

Body:
- **Before:** 30–60 analyst-hours and 2–4 days per event. *(Replace with B1 and interview figures.)*
- **After:** a cited first view in **_ minutes**, plus a few hours of review (**−_% effort**).
- **Wording risk:** one hours clause can swing a layer's loss by **up to 80%**, and CatSight flags it with the source page.
- **For whom:** small and mid-size APAC reinsurers. 48% of insurers lack cat models; Singapore hosts 16 of the top 25 reinsurers' regional hubs.
- **Cost:** about $0.03 per analysis in AI compute.
