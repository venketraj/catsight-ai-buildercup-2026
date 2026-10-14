# CatSight — Business impact

Who CatSight is for, what it changes, and how much of that is measured.
Figures are labelled: **measured** (from our runs, `RESULTS.md`), **sourced**
(a named public source) or **estimate** (our model, with its assumptions shown).

---

## 1. The problem

After a typhoon or earthquake, a reinsurer's leadership needs a first view of
*its own* exposure: which treaties respond, what each layer pays, and which
contract wording could change that. Industry numbers arrive slowly and are
not portfolio-specific:

| Source | Example | First figure | Time after the event |
|---|---|---|---|
| Moody's RMS | Jebi 2018 | $3–5.5bn | ~10 days |
| Moody's RMS | Hagibis 2019 | $7–11bn | ~19 days |
| Moody's RMS | Noto 2024 | $3–6bn | 11 days |
| PERILS (Japan typhoon and flood) | — | first report | 6 weeks |
| Verisk PCS Japan (events ≥ $2bn) | — | first estimate | within 90 days |

*Sourced: published event-response releases of each provider.* Early views can
also be far off: Jebi's insured loss grew from $3–5bn to about $13bn (Swiss Re).

Meanwhile the in-house work is manual. Moody's itself describes outward
reinsurance structures that "might only exist in their capital model, a
homegrown tool, or even in a spreadsheet". In Aon's 2025 survey, **48% of
insurers do not license catastrophe models** and **nearly 60% run cat teams of
five or fewer people**.

## 2. Where CatSight fits

CatSight is **not a catastrophe model**. Cat models (Moody's RMS, Verisk and
others) estimate the size of the loss; they price treaties whose terms have
already been coded as data. CatSight is the step after: it joins an event
footprint to the reinsurer's treaties **and reads their wording**, so the
analyst sees who pays what and which clause could change it, with the page it
is on. Today the footprint comes from public data; a licensed cat-model
footprint could be plugged in behind the same interface.

| Player | What it does | The gap CatSight addresses |
|---|---|---|
| Moody's RMS, Verisk | Footprints; layer loss on structured treaty terms | Terms must be pre-coded; no reasoning over wording text with citations |
| Broker event-response tools | Event footprints and modelled loss for clients | Tied to the broker relationship |
| Real-time alerting engines | Alerts plus a financial engine for coded treaty terms | No wording retrieval |
| Document-AI platforms | Contract extraction at underwriting time | No post-event, per-layer money flow |

## 3. What changes

| Value | What changes |
|---|---|
| **Speed** | A portfolio-specific first view in seconds to minutes, days before industry figures |
| **Wording risk** | Hours clauses (72, 96, 120 or 168 hours in real contracts) and exclusions decide which layers pay; CatSight surfaces the clause that bites on *this* event, with a verified quote |
| **Effort** | Analysts review flagged treaties instead of re-reading every contract |
| **Access** | A first view for teams without licensed cat models, at a model cost of about a cent per analysis |

## 4. Measured on our test portfolio

24 synthetic treaties, 8 fictional insurers, Typhoon Jebi replayed live on the
deployed service (10-run live benchmark; see `RESULTS.md` §1):

| | Measured |
|---|---|
| Money on screen (treaties hit, layer losses, each party's position) | about **0.7 s** after the request (p50 0.7 s; 0.5–1.1 s) |
| Complete analysis, with wording flags verified against the page | **11.3 s p50** (7.8–19.3 s) |
| Model cost per analysis | **$0.0097** p50 ($0.0081–$0.0140) |
| Report figures not traceable to the engine | **0** |
| Treaty-term extraction from the wordings | 99.5% (upper bound — see `RESULTS.md`) |

## 5. Effort model (estimate)

A mid-size reinsurer with about 100 APAC cat treaties, 25 exposed to the event.
These are our estimates; **no manual baseline has been timed yet**.

| Step | Manual today (person-hours) | With CatSight (person-hours) |
|---|---|---|
| Gather event facts | 2–4 | ~0 |
| Identify exposed treaties | 3–6 | ~0 |
| Assemble insurer exposure by region | 6–12 | ~0 (already loaded)* |
| Estimate gross loss and apply layers | 6–12 | ~0 |
| Wording review of exposed treaties (25 × 0.4–0.8 h) | 10–20 | 1.5–4 (flagged treaties only) |
| Compile, peer review, sign off | 3–6 | 2–4 |
| **Total** | **30–60 h** | **3.5–8 h** |
| **Elapsed** | **2–4 business days** | **same day** |

\* Exposure data loaded once, as in production; onboarding is excluded.

At 4–8 significant events and 10–20 smaller checks a year, that is roughly
**165–675 analyst-hours a year** (≈ 0.1–0.4 FTE). At an assumed loaded cost of
US$70–150 an hour, about **$12k–100k a year** in labour. Running cost at the
measured ~$0.01 per analysis is negligible next to that.

**The labour saving is the smaller part.** The larger value is acting days
earlier, and not missing the clause that changes the number.

## 6. Why wording matters: an illustration

On the worked example in `DOMAIN_PRIMER.md` (a $54.4M loss on one programme),
reading the loss as one event or as two ($35.0M + $19.4M) under the hours
clause moves:

| | One event | Two events | Change |
|---|---|---|---|
| Layer 1 (20 xs 10) | $20.0M | $29.4M | +47% |
| Layer 2 (30 xs 30) | $24.4M | $5.0M | −80% |
| Insurer's retention | $10M | $20M | ×2 |

A reinsurer holding only Layer 2 would see its first view swing between $2.44M
and $0.50M on one programme, because of one clause. Real disputes show the
stakes: *Tokio Marine Europe v Novae* (2014, Thai floods, a 72-hour clause)
and *UnipolSai v Covéa* (English Court of Appeal, 2024, a 168-hour clause).

## 7. Market context (sourced)

- **Singapore** wrote S$27.6bn of reinsurance premium in 2023, about 21% of
  Asia's market, and is the regional hub for 16 of the top 25 global
  reinsurers (MAS).
- **Protection gap:** 91% of Asia-Pacific's 2023 economic losses from
  natural catastrophes (US$65bn) were uninsured (MAS).
- **Jebi** produced 857,284 claims and ¥1,067.8bn paid, the largest ever for a
  Japanese typhoon (General Insurance Association of Japan).

## 8. Not yet measured

- A **timed manual baseline** on the same portfolio, which would replace the
  effort estimate in section 5.
- **Usability** with practitioners.
- A **back-test** of modelled market-level loss against paid claims.
