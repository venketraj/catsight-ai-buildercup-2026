# CatSight Domain Primer: Reinsurance & Catastrophe Terms

> For team members new to reinsurance. One worked example runs through the whole document. **All company names and numbers are made up; damage ratios are illustrative.** The event (Typhoon Jebi, Sep 2018) is real.

---

## 1. The basic idea: insurance for insurance companies

```
 Homeowners / businesses
        │  pay premium, get claims paid
        ▼
 Insurance company  ("cedent")  e.g. Sakura General Insurance
        │  passes ("cedes") part of its risk + part of premium
        ▼
 Reinsurer  (CatSight's user)  e.g. "Lion Re", Singapore
```

| Term | Meaning |
|---|---|
| **Cedent** | The insurance company that buys reinsurance. It "cedes" (hands over) some of its risk. |
| **Reinsurer** | The company that takes on that risk in return for a share of premium. |
| **Treaty** | A contract that covers a whole portfolio of the cedent's policies (e.g. all Japanese property policies for one year). CatSight works with these. |
| **Facultative** | Reinsurance for one specific risk, such as a single factory. Not used in CatSight. |
| **Peril** | The cause of loss: windstorm or typhoon, earthquake, flood, fire. |
| **Territory** | Where the treaty applies, e.g. "Japan". |
| **Period** | The dates the treaty covers. Many Japanese treaties renew on **1 April**, so a typical period runs 1 Apr 2018 to 31 Mar 2019. |

---

## 2. Why catastrophes are the hard part

One house fire is easy to absorb. A **typhoon damages thousands of insured buildings at once**, and they are all claims for the same insurer. This build-up of risk in one place is called **accumulation**.

| Term | Meaning |
|---|---|
| **Cat (catastrophe) event** | One natural disaster causing a large number of losses at the same time. |
| **Exposure / TSI (Total Sum Insured)** | The total value the cedent insures in an area. 10,000 Osaka buildings worth $2B in total = $2B Osaka TSI. |
| **Ground-up / gross loss** | The total loss to the cedent before any reinsurance pays. |
| **Intensity** | How severe the event was in each place (wind speed, quake shaking). |
| **Damage ratio (MDR, mean damage ratio)** | The share of insured value expected to be destroyed at a given intensity. 2% MDR on $2B = $40M loss. |
| **Cat model** | Expensive specialist software (vendors such as Verisk and Moody's RMS) that estimates these losses properly. **CatSight is not a cat model.** It gives a fast, transparent *first view* within hours. |

---

## 3. Excess of loss and layers (the core idea)

A **Cat XL (Catastrophe Excess of Loss)** treaty works like an insurance deductible stacked into floors.

Notation: **"20M xs 10M"** reads "20 million in excess of 10 million". The reinsurer pays losses **above $10M**, up to a further **$20M**. So this layer starts paying at $10M and is used up at $30M.

| Term | Meaning |
|---|---|
| **Retention / attachment point** | What the cedent pays itself before the layer pays anything ($10M here). |
| **Limit** | The maximum the layer pays ($20M here). |
| **Layer** | One "floor" of cover. Large programs stack several layers on top of each other. |
| **Program** | The full stack of layers. |
| **Share / line** | A reinsurer usually takes only a **percentage** of a layer. Other reinsurers take the rest. |
| **Burn / erosion** | How much of a layer's limit an event has used up. |
| **Exhausted** | The layer has paid its full limit. |
| **Rate on Line (ROL)** | Premium ÷ limit. A $2M premium for a $20M limit = 10% ROL. A quick read on how risky the market thinks the layer is. |

### Sakura's Cat XL program

```
        $100M ┌──────────────────────────┐
              │ Layer 3: 40M xs 60M      │  premium $1.0M
         $60M ├──────────────────────────┤
              │ Layer 2: 30M xs 30M      │  premium $1.5M   ← Lion Re takes 10%
         $30M ├──────────────────────────┤
              │ Layer 1: 20M xs 10M      │  premium $2.0M   ← Lion Re takes 25%
         $10M ├──────────────────────────┤
              │ Retention (Sakura pays)  │
           $0 └──────────────────────────┘
```

---

## 4. Worked example: Typhoon Jebi hits Kansai

### Step 1: Event facts (`event_intel` agent)

Using Google Search grounding, it finds and cites sources:
- Typhoon Jebi made landfall on 4 Sep 2018.
- The worst damage lasted about 24 hours.
- Osaka was hit hardest, then Hyogo, then Kyoto.
- Storm surge flooded Kansai Airport.

### Step 2: Match treaties (`match_treaties` tool)

Is Sakura's treaty in scope?
- Peril "windstorm" is covered ✔
- Territory "Japan" ✔
- The date (4 Sep 2018) falls inside the 1 Apr 2018 – 31 Mar 2019 period ✔

### Step 3: Gross loss (`loss_engine`, plain Python with no AI arithmetic)

| Region | Sakura's TSI | Intensity band | Damage ratio | Gross loss |
|---|---|---|---|---|
| Osaka | $2,000M | 4 (severe) | 2.0% | $40.0M |
| Hyogo | $1,200M | 3 (strong) | 1.0% | $12.0M |
| Kyoto | $800M | 2 (moderate) | 0.3% | $2.4M |
| **Total** | | | | **$54.4M** |

> **Calibration note (research 2026-10-02):** these damage ratios are for teaching only. Published wind-damage curves (Eberenz et al. 2021) show Japanese buildings are **much less vulnerable** than Philippine ones. At 50 m/s the curves give about 0.3% for Japan vs about 10% for the Philippines. Jebi's real insured loss was about ¥1.07 trillion (GIAJ). The prototype uses separate curves per country, and its exposure is scaled to GIROJ prefecture sums insured.

### Step 4: Apply the layers

Formula for each layer: **pays = min(max(loss − retention, 0), limit)**

| Layer | Calculation | Layer pays | Burn | Our share | **Our loss** |
|---|---|---|---|---|---|
| L1: 20 xs 10 | min(54.4 − 10, 20) | $20.0M | **100% (exhausted)** | 25% | **$5.00M** |
| L2: 30 xs 30 | min(54.4 − 30, 30) | $24.4M | 81% | 10% | **$2.44M** |
| L3: 40 xs 60 | 54.4 < 60, so nothing | $0 | 0% | 0% | $0 |
| | | | | **Total to Lion Re** | **$7.44M** |

Sakura itself pays the first $10M (its retention).

### Step 5: Reinstatements

Once Layer 1 is exhausted, Sakura has no protection left for the next typhoon that season. Treaties therefore usually allow the limit to be **reinstated** (restored) a set number of times. The cedent pays an extra **reinstatement premium** to restore it.

- A common basis is **"pro rata as to amount"**: pay in proportion to how much of the limit was used.
- Layer 1: (20 ÷ 20) × $2.0M = $2.0M. At our 25% share, **we receive $0.5M**.
- Layer 2: (24.4 ÷ 30) × $1.5M = $1.22M. At our 10% share, **we receive about $0.12M**.

Net cost to Lion Re ≈ $7.44M − $0.62M ≈ **$6.8M**. Real wordings can add details, such as a time-based "pro rata as to time" element. The prototype uses the simple version.

---

## 5. Why the treaty wording matters (where CatSight stands out)

The figures above assume a simple reading of the contract. Specific clauses in the treaty wording can change the answer. The `wording_checker` agent uses RAG (searching the treaty documents) to find these clauses and cite the page.

### a) Hours clause (the definition of "one event")
A treaty pays **per loss occurrence**, meaning per event. The **hours clause** sets a time window: all losses within, e.g., **72 hours** for windstorm (often **168 hours** for flood) count as **one** event.

> **Verified in research (2026-10-02):**
> - Real public Cat XL contracts (filed with the US SEC) use **72, 96, 120 or 168 hours**. CatSight must read the clause from each treaty, never assume 72h.
> - Standard wording lets the **cedent choose when each window starts**, but not before the first recorded loss.
> - **Windows may not overlap.**
> - UK case law (UnipolSai v Covéa, 2024): "occur" means "first occur", so losses that *first* occur inside the window count toward that event.

- **Jebi:** the main damage lasted about 24 hours, well inside 72, so it is one event and the calculation above stands. ✔
- **A long flood instead:** suppose flooding lasts 10 days (240 hours) under a 168-hour clause. The same $54.4M could be split into **two** events, e.g. $35M + $19.4M. Each event has its own retention.

| | One event ($54.4M) | Two events ($35M + $19.4M) |
|---|---|---|
| Sakura's retention | $10M | $10M + $10M = **$20M** |
| Layer 1 pays | $20M | $20M + $9.4M = **$29.4M** (uses a reinstatement) |
| Layer 2 pays | $24.4M | $5M + $0 = **$5M** |

The same total loss leads to very different payments per layer, and to different reinsurers being hit. **CatSight flags this automatically and cites the clause.** This is the main moment in the demo.

### b) Exclusions
Suppose the wording says *"flood and storm surge excluded unless directly caused by a named windstorm."* Jebi was a named typhoon, so surge damage at the airport is **covered**. If the wording excluded storm surge outright, those losses would be removed before applying the layers. Example flag: *"Treaty T-07, p.12, Clause 9: storm surge exclusion. Review airport-area losses."*

### c) Territorial scope
A treaty covering "Japan excluding Okinawa" would not respond to a typhoon that only hit Okinawa.

---

## 6. Other terms you'll hear

| Term | Meaning |
|---|---|
| **Bordereau / bordereaux** (pronounced "bor-de-ROH") | A spreadsheet report from the cedent listing policies, premiums or claims. In CatSight they are the source of exposure (TSI) data. |
| **Quota Share (QS)** | A *proportional* treaty: the reinsurer takes a fixed % of every policy and every loss (e.g. 30% of everything). No layers; much simpler maths. |
| **Surplus** | Proportional reinsurance where the reinsurer covers the amount of each risk above a set level the cedent keeps. |
| **Proportional vs non-proportional** | QS and Surplus share losses by percentage. XL layers pay only above a retention. |
| **PML (Probable Maximum Loss)** | The worst realistic loss, e.g. a 1-in-200-year typhoon. Used to decide how many layers to buy. |
| **Flash / first-view loss estimate** | A quick early estimate after an event. CatSight's report is this. |
| **CRESTA zones** | Standard geographic zones the industry uses to report exposure. CatSight uses administrative regions (prefectures) as a simpler stand-in. |
| **Industry loss estimate** | A market-wide loss figure published by modelling firms days or weeks after an event. |

---

## 7. How each CatSight step uses these terms

| CatSight step | Question it answers | Terms involved |
|---|---|---|
| `event_intel` agent | "What happened, where, how bad, for how long?" | peril, intensity, event duration |
| `match_treaties` tool | "Which contracts respond?" | treaty, territory, period, peril |
| `loss_engine` tool | "How much does each layer pay?" | TSI, damage ratio, gross loss, retention, limit, share, burn, reinstatement |
| `wording_checker` agent | "Does the fine print change it?" | hours clause, loss occurrence, exclusions, territorial scope |
| `reporter` agent | "Summary for the leadership team, with sources" | flash report, citations |

---

## 8. Using this example in the build

- **Unit tests:** the step 3–5 numbers above (gross $54.4M, L1 $20M, L2 $24.4M, Lion Re $7.44M, reinstatement receipts $0.62M) and the two-event split in section 5a are ready-made, hand-checked test cases for `tests/test_loss_engine.py`.
- **Synthetic data:** Sakura's 3-layer program is a good first entry in `seed_portfolio.py`.
- **Video framing (about 20 seconds):** *"When a typhoon hits, CatSight tells a reinsurer within minutes which contracts are affected, roughly how much each layer pays, and which contract clauses might change that answer, with sources for every claim."*
