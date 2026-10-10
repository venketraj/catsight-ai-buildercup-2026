# CatSight — Architecture

> Judge-facing architecture reference. Service topology, the agent graph, data flows, and the design decisions behind them.
>

---

## 1. One picture

```
                        ┌───────────────────────────────────────────────┐
  Analyst / judge       │  Firebase Hosting — React + Vite SPA          │
  (browser)      ──────►│  https://techno-crackers-catsight.web.app     │
                        └────────────────────┬──────────────────────────┘
                                             │  HTTPS · REST + SSE via fetch streaming
                                             │  CORS allow-list · NO Hosting rewrite
                                             ▼
                        ┌───────────────────────────────────────────────┐
                        │  Cloud Run — catsight-api   (us-central1)     │
                        │  FastAPI + Google ADK 2.11 graph Workflow     │
                        │  service-account auth · no API keys           │
                        │  min-instances 0 · max-instances 3 · t/o 300s │
                        └──┬─────────┬──────────┬──────────┬────────────┘
                           │         │          │          │
            ┌──────────────▼─┐ ┌─────▼─────┐ ┌──▼───────┐ ┌▼─────────────────┐
            │ Gemini on      │ │ Firestore │ │ Cloud    │ │ Google Search    │
            │ Agent Platform │ │ (native)  │ │ Storage  │ │ grounding        │
            │ (Vertex AI)    │ │ treaties  │ │ treaty   │ │ event context    │
            │ global endpoint│ │ exposures │ │ PDFs     │ │ ONLY — never a   │
            │ 3.5 Flash-Lite │ │ chunks +  │ │ exports  │ │ number or a flag │
            │ 3.8 Flash      │ │  vectors  │ └──────────┘ └──────────────────┘
            │ embedding-001  │ │ analyses  │
            └────────────────┘ └───────────┘

  Cross-cutting: Cloud Logging (structured JSON) · Cloud Trace (ADK OTel) ·
                 Secret Manager · Artifact Registry · Cloud Build · budget alerts
```

**Why the browser calls Cloud Run directly.** Firebase Hosting rewrites impose a 60-second timeout and do not stream. A full analysis runs longer than that and its value is in watching it stream. So the SPA calls the `*.run.app` URL with `fetch()` + `ReadableStream` — not `EventSource`, which is GET-only — against a CORS allow-list.

## 2. The agent graph

ADK 2.x graph `Workflow`. Not a linear chain: there is a verification **loop** and an adversarial **fan-out / fan-in**.

```
            user request (replay: event injected into state · live: query)
                                    │
  ┌─────────────────────────────────▼──────────────────────────────────┐
  │ AG-1  event_intel            MODEL_MAIN   [google_search] only     │
  │       skipped in replay mode · disallow_transfer_to_parent/peers   │
  │       → state.event                                                │
  └─────────────────────────────────┬──────────────────────────────────┘
                                    │
  ┌─────────────────────────────────▼──────────────────────────────────┐
  │ AG-2  exposure_analyst       MODEL_MAIN                             │
  │       match_treaties · estimate_layer_losses ──► LOSS ENGINE [tool] │
  │       → state.impact                                               │
  └─────────────────────────────────┬──────────────────────────────────┘
                                    │
  ┌─────────────────────────────────▼──────────────────────────────────┐
  │ AG-3  wording_checker        MODEL_REASON                           │
  │       search_treaty_clauses ──► Firestore vector search             │
  │       split_occurrence_scenario ──► LOSS ENGINE [tool]              │
  │       → state.wording_flags  (candidates)                           │
  └─────────────────────────────────┬──────────────────────────────────┘
                                    │
       ┌────────────── LOOP ────────┴──────────────┐
       │  AG-5  verifier          MODEL_REASON     │
       │  1. deterministic normalised quote-match  │  ◄── free, runs first
       │  2. checker → {supports, reason}          │
       │  fail → retry once with feedback          │
       │  fail again → ABSTAIN → withheld tray     │
       │  → state.verified_flags / withheld_flags  │
       └────────────────────┬──────────────────────┘
                            │
              ┌─ triggered only on an interpretable ambiguity ─┐
              │                                                 │
  ┌───────────▼─────────────┐      ┌──────────────────────────┐ │
  │ AG-6 cedent_counsel     │      │ AG-7 reinsurer_counsel   │ │  PARALLEL
  │ MODEL_MAIN              │      │ MODEL_MAIN               │ │  cannot see
  │ argues the cedent's     │      │ argues the reinsurer's   │ │  each other
  │ reading, cites verified │      │ reading, cites verified  │ │
  └───────────┬─────────────┘      └────────────┬─────────────┘ │
              └──────────────┬───────────────────┘               │
  ┌──────────────────────────▼─────────────────────────────────┐ │
  │ AG-8  arbiter            MODEL_REASON                       │ │
  │       price_scenario ──► LOSS ENGINE [typed bounded tool]    │ │
  │       summarises dispute risk · DOES NOT DECIDE              │ │
  │       money_at_stake computed in PYTHON, per party           │ │
  │       → state.courtroom                                      │ │
  └──────────────────────────┬─────────────────────────────────┘ │
              └──────────────┴───────────────────────────────────┘
                            │
  ┌─────────────────────────▼──────────────────────────────────────────┐
  │ AG-4  reporter               MODEL_MAIN   no tools                 │
  │       copies every number from tool output · disclaimer            │
  │       code asserts each number appears in state.impact             │
  │       → state.report                                              │
  └────────────────────────────────────────────────────────────────────┘
                            │
                      SSE → browser · analysis persisted → Firestore
                      green run → cached replay fixture written
```

### Why this shape

| Decision | What it buys |
|---|---|
| **LLM orchestrates, Python computes** | No hallucinated money. The first question a finance judge asks is already answered. |
| **Verifier loop, not a filter** | The model gets one chance to correct itself with specific feedback, then abstains. Abstention is counted and shown, which turns a silent safety rule into a measurable feature. |
| **Counsels in parallel and blind to each other** | Two independent readings, not one model talking to itself. Also the only way the latency budget closes. |
| **Counsels on `MODEL_MAIN`, arbiter on `MODEL_REASON`** | Keeps the Courtroom path under $0.08. The reasoning model is needed to weigh the two readings, not to construct each one. |
| **Arbiter cannot decide** | Issue-spotting, not legal advice. The analyst records the position, and it persists on the analysis. |
| **`money_at_stake` in Python** | The headline number of the whole demo is a subtraction over engine output, never a token prediction. |
| **Conditional Courtroom** | A standard analysis costs $0.037, not $0.058. And when no clause is genuinely ambiguous, the UI says so rather than inventing a dispute. |
| **Typed bounded scenario tool** | The LLM picks parameters inside a schema that refuses out-of-range values. One tool serves both the Courtroom and what-if. |
| **Idempotent tools** | Failed graph nodes re-run on resume. |

## 3. Data flows

### Flow A — treaty ingestion (admin, once per document)

```
treaty_*.pdf ──► POST /api/admin/ingest (X-Admin-Token) ──► GCS gs://…-docs/treaties/
                     │
                     ├─[A1] Gemini MODEL_MAIN · Part.from_uri(gs://…)
                     │      response_schema=TreatyTerms · temperature 0
                     │      media_resolution MEDIUM · page_number on EVERY field
                     │      → cedent, type, perils[], territory{}, inception, expiry,
                     │        currency, layers[], qs{}, hours_clause{}, exclusions[]
                     │      → validate (limit>0, retention≥0, layers contiguous)
                     │        invalid → re-ask once → else extraction.confidence=low
                     │
                     ├─[A2] scanned endorsement page (no text layer)
                     │      native image understanding → transcription stored as a
                     │      chunk with source="transcription"
                     │      contradicts base wording → effective term = endorsement,
                     │      both retained with provenance
                     │
                     └─[A3] split by clause (fallback: by page)
                            gemini-embedding-001 · 768 dims · L2-normalised
                            task_type=RETRIEVAL_DOCUMENT · one input per request
                            → treaty_chunks{treaty_id, page, clause_no, clause_title,
                                            clause_type, text, embedding}
```

Vector index is created with **gcloud**, not the Firebase CLI: `treaty_chunks`, `treaty_id ASC` + `embedding` flat 768. Pre-filters are **equality only**, which is why retrieval filters on `treaty_id` and nothing else.

### Flow B — analysis (the demo path)

```
POST /api/analyses {mode:"replay", event_id:"jebi-2018", as_if:true}
   │
   ├─ guards: Pydantic validation · per-IP 20/h · DAILY_ANALYSIS_CAP · query ≤300 chars
   │
   ├─ replay: load data/events/jebi-2018.json → inject into state (NO search call)
   │  live:   AG-1 with google_search → Event + facts + source URLs
   │          intensities flagged intensity_source="llm_estimate" + warning badge
   │
   ├─ hazard: per-region wind (piecewise radial profile over track points) or MMI
   │          (nearest ShakeMap grid cell) → intensity bands
   │
   ├─ AG-2 → match_treaties (peril ∩ territory ∩ period-unless-as_if)
   │       → estimate_layer_losses → LOSS ENGINE
   │          gross = Σ tsi_usd × damage_ratio(intensity, country)
   │          Cat XL: ceded = min(max(loss−retention,0), limit)
   │          QS:     ceded = min(gross × cession_pct, event_limit)
   │          per-layer burn, exhaustion, reinstatements, RIP, our_share
   │
   ├─ AG-3 → retrieval (hours clause · exclusions · territory · reinstatement · period)
   │       → candidate flags, each with treaty_id, page, clause_no, quote ≤300 chars
   │       → hours clause vs event.duration_h → split scenario if longer
   │
   ├─ AG-5 → verify every candidate → verified_flags | withheld_flags
   │
   ├─ [if ambiguity] AG-6 ∥ AG-7 → AG-8 → courtroom{priced, money_at_stake, arbiter_md}
   │
   ├─ AG-4 → report_md + structured key_numbers + disclaimer
   │
   └─ persist analyses/{id} · write cached replay fixture · SSE "done"
```

### SSE event contract

```
{"type":"stage","agent":"…","status":"started|completed","ts":…}
{"type":"tool","agent":"…","name":"…","summary":"12 matched, 3 excluded"}
{"type":"partial","agent":"reporter","text":"…"}      ← REPLACES, never appends
{"type":"result","key":"event|impact|wording_flags|courtroom|report","data":{…}}
{"type":"error","message":"…","retryable":true}
{"type":"done","analysis_id":"…"}
```

Headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`.

### Flow C — cached instant replay

Load-bearing infrastructure, not an optimisation. Every green analysis writes its SSE stream to `data/replays/{event_id}.jsonl`. The client falls back to the fixture when the first event misses `FIRST_EVENT_TIMEOUT_MS`, the daily cap is hit, or the request errors. Anonymous visitors are served fixtures at **zero LLM cost**.

One mechanism, three risks closed: cold starts across three weeks of unattended remote judging; the daily cap being exhausted by public traffic from a launch post; a dead backend or network on stage at the finale. Cached runs are always labelled as cached, with the timestamp of the run they came from.

## 4. Trust architecture

What a regulated-industry judge is actually looking for:

1. **The LLM never calculates.** Every number originates in tested, deterministic Python with full branch coverage. The reporter is checked in code: each number it prints must appear in `state.impact`.
2. **Every wording claim is cited** to `treaty_id`, page and clause, with a quote ≤ 300 characters.
3. **Every citation is machine-verified** — normalised substring match, then a semantic check. Failures retry once, then abstain.
4. **Unverifiable claims are withheld, visibly.** `"n of n verified · k withheld"` sits in the report header, and the withheld tray shows the reason.
5. **Transcribed sources are badged differently** from text-layer sources.
6. **Grounded web search touches event context only** — never a number, never a flag — and is displayed in its own panel.
7. **Retrieved text is data, not instructions.** Agents are told to ignore instructions found inside documents; ingestion is admin-token-protected.
8. **A human approves** before anything leaves. Approve / Needs changes with a note, persisted.
9. **Synthetic data throughout.** Fictional cedents, paraphrased wordings, public hazard data with attribution.
10. **The disclaimer is on every report and in the footer.**

## 5. Service configuration

| Concern | Setting |
|---|---|
| Region | Cloud Run, Firestore, GCS: `us-central1`. **Gemini: `global`** — 3.x is not served from us-central1. |
| Auth | Cloud Run service account; `GOOGLE_GENAI_USE_ENTERPRISE=true`; no API keys anywhere |
| Scaling | `--min-instances 0 --max-instances 3 --cpu-boost --timeout 300` |
| Cost guards | Daily analysis cap, per-IP 20/h, budget alerts, `CACHED_REPLAY_ONLY` kill switch |
| Firestore rules | **Deny all** client access; everything goes through the API |
| Secrets | `ADMIN_TOKEN` in Secret Manager, never in git |
| Retries | `HttpRetryOptions(attempts=5, initial_delay=1)` — google-genai retries are off by default |
| Model failover | `FallbackModel`: 3.8 Flash → 3.5 Flash-Lite |
| Thinking | `ThinkingConfig(thinking_level=LOW)`; thinking tokens bill as output |
| Observability | Structured JSON logs (`analysis_id`, stage, latency, tokens); Cloud Trace via ADK OTel |

## 6. Performance and cost

| Path | p50 | p95 | Cost |
|---|---|---|---|
| Standard analysis (warm) | ≤ 50 s | ≤ 95 s | ≈ $0.037 |
| Courtroom path (warm) | ≤ 70 s | ≤ 120 s | ≈ $0.058 |
| What-if re-run | — | — | ≈ $0.004 |
| Cached replay | instant | instant | $0 |

Time to first SSE event ≤ 3 s; cold start to first response ≤ 15 s. The added stages sit at the **end** of the pipeline, so they do not delay the first event — the stream starts moving while the expensive work is still ahead.



## 7. Scalability path

What production would need, stated as roadmap rather than claimed as built:

- **Ingestion at scale** — real treaty packs and exposure schedules through an authenticated API; bordereaux upload; BigQuery for portfolio-scale exposure.
- **Multi-tenancy** — per-tenant Firestore collections or project-per-tenant; today there are no user accounts by design.
- **Event triggers** — Pub/Sub from public disaster alerts (GDACS, USGS feeds) via Cloud Scheduler for automatic runs on new events.
- **Vendor feeds** — the hazard layer is an interface; a licensed cat-model footprint (Moody's RMS, Verisk) can replace IBTrACS/ShakeMap without touching the engine or the wording agents. **CatSight is complementary to those products, not a replacement.**
- **Integration surface** — A2A / MCP endpoint so a broker's or modeller's agent can call CatSight as a tool.
- **Loss development** — re-run as cedent loss advices arrive over months and track reserve drift.
- **Managed runtime** — Agent Engine for the agent pipeline.

## 8. Repository layout

```
/
├── README.md                      # judge-facing · FR-DOC
├── LICENSE                        # Apache-2.0
├── backend/
│   ├── catsight_agent/            # ADK package · root_agent in agent.py
│   │   ├── agent.py               # the graph Workflow
│   │   ├── prompts.py             # every instruction, in one place
│   │   ├── schemas.py             # Pydantic models
│   │   └── tools/
│   │       ├── exposure.py        # match_treaties
│   │       ├── loss_engine.py     # deterministic maths · FR-LOSS · no I/O
│   │       ├── hazard.py          # wind / MMI at region centroids
│   │       ├── retrieval.py       # search_treaty_clauses (+ local fallback)
│   │       └── verify.py          # deterministic quote-match · FR-VERIFY-1
│   ├── app/
│   │   ├── main.py                # FastAPI routes
│   │   ├── streaming.py           # ADK events → SSE
│   │   ├── guards.py              # rate limit, daily cap, validation
│   │   └── settings.py            # env config
│   ├── ingest/                    # build_* and ingest_treaty scripts
│   ├── data/                      # committed synthetic + derived (small files only)
│   │   ├── events/ · synthetic/wordings/ · replays/ · ASSUMPTIONS.md
│   │   └── raw/                   # git-ignored: IBTrACS ~114MB, Natural Earth ~40MB
│   ├── tests/                     # pytest + ADK eval sets
│   ├── requirements.txt           # pinned · google-adk==2.11.0
│   └── Dockerfile
├── frontend/                      # Vite + React + TypeScript
├── benchmarks/                    # B2–B7 harness + human templates + results/
├── docs/                          # this pack
├── scripts/                       # setup_gcp.sh · deploy.sh · smoke_test.sh
└── firebase.json · .firebaserc · firestore.rules
```

## 9. Data sources and attribution

| Source | Use | Licence |
|---|---|---|
| NOAA **IBTrACS** v04r01 WP | Typhoon tracks | Cite Knapp et al. 2010, doi:10.25921/82ty-9e16 |
| **USGS** ShakeMap | Earthquake MMI | Public domain — credit U.S. Geological Survey |
| **Natural Earth** 10m admin-1 | Region geometry | Public domain |
| **JMA** | Event facts | "Source: Japan Meteorological Agency website" |
| **e-Stat** | Dwelling counts for exposure calibration | 出典：政府統計の総合窓口(e-Stat) |
| **GIROJ / GIAJ / JER** | Calibration and back-test references | Cited only; not redistributed |
| **Eberenz et al. 2021** | Wind vulnerability V_half | CC BY 4.0 |
| SEC EDGAR contracts | Style reference only — wordings are paraphrased, never copied | — |

Portfolio, cedents and treaty wordings are **entirely synthetic**. Events are real and so are the referenced market losses, which are used for credibility and the B5 back-test only — never as model inputs.
