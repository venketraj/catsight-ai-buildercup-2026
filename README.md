# CatSight

**Event-aware contract intelligence for catastrophe reinsurance.**

> When a typhoon or earthquake hits, CatSight tells a reinsurer within about a minute which treaties respond, roughly what each layer pays, which contract clauses could change that answer - and exactly where each clause says so, with every quote machine-verified.

Google Cloud AI Builder Cup 2026 · BFSI: Intelligent Risk, Fraud & Financial Experiences · Team Techno Crackers.

---

## What it does

CatSight takes the reinsurer's side - a fictional reinsurer, **Lion Re** - and replays a real catastrophe over a synthetic book of 24 treaties written for 8 fictional insurers in Japan, the Philippines and Taiwan.

1. **Which treaties respond** - peril, territory and period matching, with a reason for every treaty that does not.
2. **What each layer pays** - gross loss by region, per-layer ceded, burn, reinstatements and reinstatement premium, and where each party stands: what the insurer keeps, what all reinsurers pay, and Lion Re's net.
3. **Which clauses change that answer** - Gemini agents search the treaty wordings and flag clauses that bite on *this* event (for Jebi: T-004 excludes storm surge, and Osaka recorded a record 329 cm tide).
4. **Where each clause says so** - treaty, page and clause, with the quote string-matched against the stored clause and checked for support. Anything that fails is withheld and shown as withheld, never displayed as a finding.

Around that core:

| Feature | What it gives the analyst |
|---|---|
| **How was this calculated?** | Every treaty, step by step: the hazard, why it responded, damage by region (insured value × damage % = loss), and each layer's figure with its formula and contract citation |
| **Map** | Regions coloured by peak wind or shaking intensity; click a region for insured value by insurer; table alternative |
| **Follow-up questions** | "Show the hours clause for W1" - answered from the engine's figures and live clause retrieval, with verified citations |
| **What-if** | Apply an hours clause to the real loss timeline, or a clearly labelled hypothetical split - priced by the engine, money at stake per party |
| **Clause Courtroom** | Two AI counsel argue opposite readings of the disputed clause in parallel, each from verified wording; the engine prices both readings; an arbiter summarises without deciding; the analyst records a position |
| **Treaties, Methodology, Knowledge base** | The treaty book with each wording reconciled against it field by field; the versioned method; evidence of how the clause corpus was built |
| **Reports** | Markdown and Word (.docx) downloads, the on-screen report laid out as a paper memo; instant replay of a recorded real run |

**Built for a judge with ninety seconds.** The Analysis screen opens on the event cards and two buttons - **Instant replay** (a recorded real run, about 6 s, no model cost) and **Run live** (the agents, about a minute). The result is laid out in five steps - *Event → Who's hit → What it costs → Clauses that matter → Decide* - under a sticky summary bar (claims, reinsurers pay, our net, flags verified, time, method version). A guided **tour** walks through a recorded run in nine stops. Dark and light themes, each with its own colour-blind-checked palette; keyboard navigation throughout.

## The design decision that matters

**The language model never does arithmetic.**

Every money figure comes from deterministic, unit-tested Python (`Decimal`, half-up rounding) validated against a hand-checked worked example. Gemini reads the wordings, finds and argues clauses, and writes prose; tested code calculates. Every number in an AI-written report or answer is checked against the engine's output, and any figure that is not there is shown as unsupported.

## Architecture (as built)

```
Browser (React) ──SSE──► Cloud Run: FastAPI
                            │
     ADK 2.11 Workflow:  event_intel → exposure_analyst → wording_checker → verifier → reporter
                                          (loss engine,     (Firestore        (quote match
                                           no model)         vector search     + support check
                                                             + Gemini)          on Gemini 3.8)
     Clause Courtroom:   brief → ┌ cedent_counsel    ┐ → join → price (engine) → arbiter
                                 └ reinsurer_counsel ┘   (parallel fan-out)
                            │
     Firestore: treaty book, events, method versions, 252 clause vectors,
                ingestion evidence, completed runs · Cloud Storage: treaty PDFs
```

- **Models:** `gemini-3.5-flash-lite` (agents), `gemini-3.8-flash` (verification, arbiter), `gemini-embedding-001` at 768 dims - on Vertex AI (global endpoint), service-account auth, no API keys.
- **RAG:** each wording is split into clauses with page numbers (the scanned endorsement page is transcribed by Gemini once), embedded and stored in **Firestore vector search**; agents retrieve with an equality pre-filter on the treaty.
- **Serving:** the frontend is served by the same Cloud Run service, so the browser streams from one origin.
- **Observability:** structured JSON logs (one line per stage, retrieval, verification and limit hit, each with the run id) go to **Cloud Logging**; ADK's OpenTelemetry spans go to **Cloud Trace** (`ENABLE_CLOUD_TRACE=true` on Cloud Run). Guardrail trips are named events - `citation_withheld`, `unsupported_figures`, `counsel_dropped`, `limit_refused` - ready for log-based metrics. No raw IPs, question text or prompts are logged.
- **Guards:** per-visitor hourly limit and a daily cap (a refused live run falls back to the recorded replay); Cloud Run `--min-instances 0 --max-instances 3`; a dedicated least-privilege service account.

Detail in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Measured results

| Measure | Result | Notes |
|---|---|---|
| Loss engine vs the hand-checked worked example | exact | QA-1 |
| Treaty-term extraction (RAG-first) | **99.5%** (185/186 fields) | on the 8 wordings the prompts were developed against; not measured on a held-out set |
| Governing clause retrieved | **186/186** | Firestore vector search |
| Citations verified against the page | **185/187** | 1 scanned page labelled "transcribed" |
| Extraction time, 8 wordings | **57 s** | vs ~25 min for whole-document extraction |
| Live analysis (Jebi) | **20-50 s**, about **$0.01** in model cost | from measured token counts |
| Follow-up question | about **$0.003** | |
| Clause Courtroom | about **15 s**, about **$0.004** | |
| Automated tests | **864 passing** | plus an opt-in live suite against real GCP |

## Run it yourself

Prerequisites: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node LTS, and for the AI features the Google Cloud CLI signed in with `gcloud auth application-default login` to a project that has Vertex AI and Firestore enabled.

**1. Backend (first time)** - in `backend/`:

```powershell
uv venv --python 3.12
uv pip install -r requirements.txt -r requirements-dev.txt
copy .env.example .env          # then set GOOGLE_CLOUD_PROJECT and GCS_BUCKET
uv run --no-sync python -m ingest.build_wordings   # generates the treaty PDFs (git-ignored)
```

**2. Start the API** - in `backend/`:

```powershell
# Numbers only, no cloud needed (reads local JSON):
uv run --no-sync uvicorn app.main:app --port 8080

# Full system - agents, Firestore, vector search (needs the GCP sign-in):
$env:DATA_BACKEND="firestore"; $env:EMBED_CACHE="data/cache/embeddings.jsonl"
uv run --no-sync --env-file .env uvicorn app.main:app --port 8080
```

**3. Start the UI** - in `frontend/`, in a second terminal:

```powershell
npm install
npm run dev        # open http://localhost:5173
```

**4. Tests** - in `backend/`:

```powershell
uv run --no-sync pytest -q                                   # 864 tests, no cloud calls
$env:RUN_LIVE="1"; uv run --no-sync --env-file .env pytest -m live -q   # real Gemini + Firestore, a few cents
```

**One-time data jobs** (already done for this project; re-run only if the data changes) - in `backend/`:

```powershell
uv run --no-sync --env-file .env python -m ingest.rag_pipeline --store firestore   # embed + extract wordings
uv run --no-sync python -m ingest.reconcile                                        # book vs wording
uv run --no-sync --env-file .env python -m ingest.seed_cloud --apply               # seed Firestore + Storage
```

## Deploy (Cloud Run)

Run in **Google Cloud Shell** (bash), from the repo root:

```bash
PROJECT_ID=techno-crackers-catsight ./scripts/deploy.sh                    # scale to zero (default)
PROJECT_ID=techno-crackers-catsight MIN_INSTANCES=1 ./scripts/deploy.sh    # judging window: one warm instance
./scripts/smoke_test.sh <service-url>
```

The script builds the UI into the image, so one Cloud Run service serves both the UI and the API. It runs as the dedicated `catsight-run` service account, turns on Cloud Trace, and applies the cost guards. Logs and traces then appear in the Cloud Run, Cloud Logging and Cloud Trace consoles - no extra dashboard is built into the app.

## Limitations

- No real event in the data makes an hours clause move money (Jebi's damage lasted 9 hours; Noto's real aftershock causes no loss in our model). The hours-clause what-if is therefore shown as labelled *hypothetical*; the Courtroom argues the real storm-surge exclusion instead.
- Courtroom surge shares are bounded assumptions (0-50%) - the data does not separate wind from surge damage.
- Typhoon Haiyan (Philippines) is in the data but not offered in the demo. The synthetic Philippine book is sized like Japan's and the wind curve is an economic-damage calibration, so modelled claims (~$94B) are far above the real ~$1.5B insured loss. A per-country insurance-penetration and insured-loss calibration is future work ([`ASSUMPTIONS.md`](backend/data/ASSUMPTIONS.md) X11).
- Agent output varies between runs; it is measured, not tuned to known answers.
- Every modelling assumption is recorded in [`backend/data/ASSUMPTIONS.md`](backend/data/ASSUMPTIONS.md).
- Manual-effort comparisons in the app are labelled *simulated*: an estimate of the analyst workflow, not a timed study.

## Future work

Designed or investigated, not built:

- **More events and countries from data alone.** The 2024 Hualien earthquake (Taiwan) has been investigated: its real aftershock cluster about 20 days later is a genuine second occurrence worth about $11-15M per treaty under the hours clause - the dispute the Courtroom is built for.
- **Per-treaty hours clauses and multi-shock earthquakes** applied in the base analysis, not only in What-if.
- **Calibrated vulnerability per country** - insurance penetration and insured-loss wind curves - which would bring Haiyan back into the demo.
- **Upload your own wordings.** The RAG pipeline already ingests any PDF; public upload is held back for cost and safety.
- **Live event feeds** - a USGS or JTWC alert starts an analysis automatically.

## Documentation

| | |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Agent graph, data flows and service topology |
| [`docs/DOMAIN_PRIMER.md`](docs/DOMAIN_PRIMER.md) | Reinsurance terms and the worked example |
| [`docs/MONEY_MOMENT.md`](docs/MONEY_MOMENT.md) | The per-party money story, derived number by number |
| [`backend/data/ASSUMPTIONS.md`](backend/data/ASSUMPTIONS.md) | Every modelling assumption and decision, with its status |
| [`docs/README.md`](docs/README.md) | Full documentation index |

## Data

Portfolio, cedents and treaty wordings are **entirely synthetic** - fictional companies and wordings written in the style of public contracts. Hazard data is public: NOAA IBTrACS v04r01 (Knapp et al. 2010, doi:10.25921/82ty-9e16), USGS ShakeMap (public domain), Natural Earth (public domain). No real employer, client or broker data is used anywhere.

## Licence

Apache-2.0 - see [`LICENSE`](LICENSE).

---

*Indicative first view on synthetic data. Not a catastrophe-model output. Not underwriting or claims advice. Issue-spotting only - not legal advice.*

*Jebi, Hagibis, Haiyan and Noto were real events in which people died. This project treats them as such.*
