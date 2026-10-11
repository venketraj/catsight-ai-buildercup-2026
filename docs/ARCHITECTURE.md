# CatSight — Architecture (as built)

Service topology, the agent graph, data flows, and the decisions behind them.
Everything here is what runs on the live service; planned work is in section 7
and labelled as such.

---

## 1. One picture

```
  Analyst / judge (browser)
          │  HTTPS · same origin · REST + SSE (fetch streaming)
          ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  Cloud Run — catsight-api  (us-central1)                     │
  │  FastAPI: the API, the SSE stream AND the built React UI     │
  │  Google ADK 2.11 graph Workflows · deterministic loss engine │
  │  dedicated service account · no API keys                     │
  │  max-instances 3 · timeout 300 s · per-visitor + daily caps  │
  └──────┬──────────────────┬───────────────────┬────────────────┘
         │                  │                   │
  ┌──────▼─────────┐ ┌──────▼──────────┐ ┌──────▼─────────┐
  │ Gemini on      │ │ Firestore       │ │ Cloud Storage  │
  │ Vertex AI      │ │ (native)        │ │ treaty PDFs    │
  │ global endpoint│ │ treaty book     │ └────────────────┘
  │ 3.5 Flash-Lite │ │ events, methods │
  │ 3.8 Flash      │ │ 252 clause      │
  │ embedding-001  │ │ vectors (768-d) │
  └────────────────┘ │ completed runs  │
                     └─────────────────┘

  Cross-cutting: Cloud Logging (structured JSON, one line per stage) ·
                 Cloud Trace (ADK OpenTelemetry spans) · Cloud Monitoring
                 (log-based metrics + dashboard) · Cloud Build
```

**One service, one origin.** The deploy script builds the React app into
the container, and FastAPI serves it next to the API. The browser streams
from the same origin, with no proxy timeout in between. The stream uses
`fetch()` with a `ReadableStream` rather than `EventSource`, because the
analysis is a POST.

**Health check:** `GET /health`. (`/healthz` also exists for local use, but
Cloud Run's front end reserves paths ending in `z` on `*.run.app`.)

## 2. The agent graphs

Two ADK 2.x `Workflow` graphs of function nodes. Model calls happen inside
nodes with structured output (`response_schema`) rather than as a free
tool-calling loop: the retrieval queries per clause type are fixed, so a loop
would add calls and latency without adding judgement.

### Analysis

```
  START
    │
  event_intel        loads the event record (track or ShakeMap, observed facts)
    │
  exposure_analyst   NO MODEL · match_treaties → LOSS ENGINE
    │                peril ∩ territory ∩ period; per-layer ceded, burn,
    │                reinstatements, reinstatement premium, each party's position
    │
  wording_checker    3.5 Flash-Lite · Firestore vector search per treaty
    │                (equality pre-filter on treaty_id) → candidate flags,
    │                each citing treaty, page, clause and a quote
    │
  verifier           1. deterministic normalised quote match against the stored clause
    │  ◄── loop ──┐  2. 3.8 Flash: does the quote SUPPORT the claim?
    │   reviser   │  fail → one revision (3.5 Flash-Lite) → re-verify
    │  ───────────┘  fail again → withheld, with the reason, never shown as a finding
    │
  reporter           3.5 Flash-Lite · writes the report from verified facts;
                     code checks every figure against engine output, one rewrite,
                     anything still untraceable is listed as unsupported
    │
  SSE → browser · run saved to Firestore · a complete run refreshes the replay recording
```

### Clause Courtroom (on demand, on a completed run)

```
  brief      picks the most material verified exclusion flag
    │
    ├──► cedent_counsel     3.5 Flash-Lite ┐  in PARALLEL, blind to each other;
    └──► reinsurer_counsel  3.5 Flash-Lite ┘  each cites a retrieved clause and
                                               states its excluded share (0-50%)
    │
  quote check   deterministic match + 3.8 Flash: does the quote say what
    │           counsel uses it to say? A side that fails is dropped.
    │
  price         LOSS ENGINE prices each verified reading (typed, bounded tool)
    │           money_at_stake per party = a Python subtraction
    │
  arbiter       3.8 Flash · summarises the dispute; does NOT decide;
                any figure not in the engine output is flagged
    │
  analyst records a position (insurer's reading / reinsurers' / unresolved)
```

### Why this shape

| Decision | What it buys |
|---|---|
| **Models read, Python computes** | No model-generated money. Every figure is a tested `Decimal` calculation. |
| **Verifier loop, not a filter** | One chance to correct a flag with specific feedback, then withhold. Withholding is counted and shown, so a safety rule becomes a visible feature. |
| **Counsel in parallel and blind** | Two independent readings, not one model talking to itself, at the latency of one. |
| **Counsel on Flash-Lite, judging on 3.8 Flash** | Cheap generation, stronger checking. The Courtroom costs well under a cent per run (see `RESULTS.md`). |
| **The arbiter cannot decide** | Issue-spotting, not legal advice. The analyst's position is saved on the run. |
| **Typed, bounded scenario tool** | The model picks parameters inside a schema that refuses out-of-range values. One tool serves the Courtroom and What-if. |

## 3. Data flows

### A — treaty ingestion (offline, scripts in `backend/ingest/`)

```
synthetic treaty PDFs ──► split into clauses with page numbers
                           │  scanned page with no text layer → Gemini transcribes it once,
                           │  stored as a clause with source="transcription"
                           ▼
                     gemini-embedding-001 · 768 dims · cached by text hash
                           ▼
                     Firestore treaty_chunks {treaty_id, page, clause_no, text, embedding}
                           ▼
              RAG-first extraction: per term group, top-4 clauses → Gemini reads only
              those → every answer cites a retrieved clause; quote matched before accepted
                           ▼
              reconciliation: the treaty book is the data of record; each extracted
              term is compared field by field, and a verified disagreement is flagged
```

The vector index is created with gcloud (`treaty_id` + `embedding`, flat,
768). Firestore pre-filters are equality only, which is why retrieval filters
on `treaty_id` alone.

### B — analysis

```
POST /api/analyses {event_id, as_if}
   ├─ guards: validation · per-visitor hourly limit · daily cap
   │          (over a limit → the recorded replay, labelled, if one exists)
   ├─ hazard: wind per region from the IBTrACS track, or MMI from the ShakeMap grid
   ├─ graph above → SSE frames
   └─ run saved · replay recording refreshed
```

SSE frames, in order: `stage` (each agent started/completed), `tool`
(e.g. "13 matched, 11 excluded"), `result` (`event`, `impact`), `retrieval`,
`flag`, `verification` (verified and withheld counts), `report` (markdown,
cost, unsupported figures), `done` (run id).

### C — instant replay

Every complete live run records its stream to `data/replays/{event_id}.json`.
**Instant replay** plays it back in about 6 seconds, labelled with when it
was recorded and how long the live run took. It covers cold starts, the daily
cap under public traffic, and a dead network on stage. Replays cost nothing
in model calls.

## 4. Trust architecture

1. **The model never calculates.** Every figure comes from deterministic Python (`Decimal`, half-up rounding) tested against a hand-checked worked example.
2. **Every wording claim is cited** to treaty, page and clause, with a quote.
3. **Every citation is machine-checked**: exact normalised match first, then a model check that the quote supports the claim.
4. **What fails is withheld, visibly**: "n of n displayed citations verified · k withheld", with the reason for each.
5. **Transcribed sources are badged differently** from text-layer sources.
6. **Every figure in AI-written text is checked** against engine output; anything untraceable is listed as unsupported.
7. **Retrieved text is data, not instructions.** Agents are told to ignore instructions inside documents.
8. **A human decides.** The Courtroom records the analyst's position; the arbiter only summarises.
9. **Synthetic data throughout.** Fictional insurers and wordings, public hazard data with attribution.
10. **The disclaimer is on every report, export and page footer.**

## 5. Service configuration

| Concern | Setting |
|---|---|
| Region | Cloud Run, Firestore, Cloud Storage: `us-central1`. **Gemini: `global`** (3.x is not served from us-central1). |
| Auth | Dedicated `catsight-run` service account (Vertex AI user, Firestore user, storage, logging, trace); `GOOGLE_GENAI_USE_ENTERPRISE=true`; no API keys |
| Scaling | `--min-instances 0` (1 during judging) `--max-instances 3 --timeout 300`, startup CPU boost |
| Cost guards | Daily analysis cap (300), per-visitor limit (20/hour), `CACHED_REPLAY_ONLY` kill switch |
| Firestore rules | Deny all client access; everything goes through the API |
| Retries | 429 / 500 / 503 and dropped connections retried with backoff; a 400 is never retried |
| Thinking | `thinking_level=LOW` on Gemini 3 |
| Observability | Structured JSON logs with the run id; guardrail events (`citation_withheld`, `unsupported_figures`, `counsel_dropped`, `limit_refused`); ADK spans to Cloud Trace. `scripts/setup_observability.sh` builds log-based metrics, a Cloud Monitoring dashboard and an optional budget alert from them. No raw IPs, questions or prompts logged. |

Measured latency and cost are in [`RESULTS.md`](RESULTS.md) §1.

## 6. Repository layout

```
/
├── README.md
├── LICENSE                         Apache-2.0
├── backend/
│   ├── app/                        FastAPI: main (routes), analysis (stream), scenario
│   │                               (What-if and Courtroom pricing), replay, runs,
│   │                               report_docx, config, logs
│   ├── catsight_agent/             agent.py (analysis graph), courtroom.py, agents.py
│   │   │                           (model calls), prompts.py, schemas.py, store.py
│   │   └── tools/                  loss_engine · hazard · vulnerability · retrieval · verify
│   ├── ingest/                     wordings, embedding, RAG extraction, reconciliation, seeding
│   ├── qa/                         extraction accuracy and the per-field citation audit
│   ├── data/                       book, events, replays, extracted terms, ASSUMPTIONS.md
│   ├── tests/                      869 pytest tests (+ an opt-in live suite)
│   └── Dockerfile
├── frontend/                       Vite + React + TypeScript
├── benchmarks/                     run_all.py — live latency, cost and Courtroom runs
├── docs/                           this documentation
└── scripts/                        deploy.sh · smoke_test.sh · setup_observability.sh
                                    · create_video.py · build_deck.py
```

## 7. Not built — the path to production

- **Live event intake.** Today the event comes from its stored record. Next: Pub/Sub from USGS or GDACS alerts, and grounded web search for event context in a separate panel (never touching a number or a flag).
- **Model failover.** A fallback from 3.8 Flash to 3.5 Flash-Lite on outage.
- **Vendor hazard feeds.** The hazard layer is an interface: a licensed cat-model footprint (Moody's RMS, Verisk) can replace IBTrACS / ShakeMap without touching the engine or the agents. **CatSight complements those products; it does not replace them.**
- **Ingestion at scale.** An authenticated upload API for real treaty packs and exposure schedules; BigQuery for portfolio-scale exposure.
- **Multi-tenancy.** There are no user accounts today, by design.
- **Integration.** An A2A / MCP endpoint so a broker's or modeller's agent can call CatSight as a tool.
- **Loss development.** Re-run as loss advices arrive, and track reserve drift.

## 8. Data sources and attribution

| Source | Use | Licence |
|---|---|---|
| NOAA **IBTrACS** v04r01 WP | Typhoon tracks | Cite Knapp et al. 2010, doi:10.25921/82ty-9e16 |
| **USGS** ShakeMap | Earthquake MMI | Public domain — credit U.S. Geological Survey |
| **Natural Earth** 10m admin-1 | Region geometry | Public domain |
| **JMA** | Event facts | "Source: Japan Meteorological Agency website" |
| **e-Stat** | Dwelling counts for exposure calibration | 出典：政府統計の総合窓口(e-Stat) |
| **GIROJ / GIAJ** | Calibration references | Cited only; not redistributed |
| **Eberenz et al. 2021** | Wind vulnerability V_half | CC BY 4.0 |
| SEC EDGAR contracts | Style reference only — wordings are paraphrased, never copied | — |

Portfolio, insurers and treaty wordings are **entirely synthetic**. Events are
real, and so are the referenced market losses, which are used for context
only — never as model inputs.
