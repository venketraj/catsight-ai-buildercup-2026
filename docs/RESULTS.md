# CatSight — measured results

Every number here came from a run against the live project. Nothing is
estimated, and nothing that has not been measured is quoted.

- **Project** `techno-crackers-catsight` · Firestore `(default)` Native, us-central1
- **Models** `gemini-3.5-flash-lite` (MODEL_MAIN), `gemini-3.8-flash` (MODEL_REASON),
  `gemini-embedding-001` @ 768 dims — all three confirmed to resolve at `location=global`
- **Run date** 2026-10-05
- **Reproduce** `python -m ingest.ingest_treaty --out data/extracted`

---

## Read this before quoting the headline number

> **QA-3 is 100% on a set the prompt was tuned against.** The extraction
> instruction went through six revisions, each driven by a failure in the
> previous run against *this* answer key. That is legitimate engineering — the
> defects it fixed were real, and they are listed below — but a score on the
> data you tuned on is an upper bound, not an expectation.
>
> The honest claim is: **"100% on the eight planted wordings, after six prompt
> revisions against them."** The number that would support a general claim is
> the blind set (**Y9**), which does not exist yet and must be authored by
> someone outside the prompt work.

---

## 1. QA-3 · field extraction accuracy

**100.0% — 186/186 fields. Bar: ≥95%. PASS.**

| Treaty | | Planted feature |
|---|---|---|
| T-001 (W1) | 23/23 · 100% | the worked example |
| T-002 (W2) | 23/23 · 100% | WS 96h, not the assumed 72h; conditional flood exclusion |
| T-003 (W3) | 23/23 · 100% | Okinawa territorial carve-out |
| T-004 (W4) | 28/28 · 100% | **scanned endorsement: 168h overrides the body's 72h** |
| T-005 (W5) | 26/26 · 100% | absolute earthquake exclusion, PHL |
| T-006 (W6) | 11/11 · 100% | quota share, no hours clause |
| T-007 (W7) | 26/26 · 100% | two reinstatements |
| T-008 (W8) | 26/26 · 100% | **hours clause hidden under a "Definitions" heading** |

**By source:** text-layer 184/184 (100%) · **transcription 2/2 (100%)**

The transcription figure is the one worth noting. W4's endorsement is a
rasterised page with no text layer, and FR-ENDORSE-3 makes it *operative* — it
replaces the 72 hours printed in the body with 168. A text-only pipeline
cannot see it at all and gets W4's hours clause confidently wrong, which is
the most expensive single error the planted set can produce. Sending the PDF
to Gemini as a PDF rather than as extracted text is what makes this work.

## 2. QA-4 · citation provenance — **below bar**

| Measure | Result | Bar | |
|---|---|---|---|
| Page accuracy, where a citation was offered | 135/144 · **93.8%** | ≥95% | ❌ |
| **Citation coverage** — fields carrying any citation at all | 144/186 · **77.4%** | — | ❌ |

Both are reported because accuracy alone flatters an extractor that cites only
the easy fields. C-7 requires every wording claim to carry a citation, and at
77.4% coverage roughly one field in four has no audit trail — a larger problem
than the 6.2% of offered pages that are wrong. **This is the main open gap.**

## 3. FR-INGEST-3 · structural validation

**8/8 ingestable · 0 quarantined · 0 hard failures.**

Reported beside accuracy, never folded into it: a perfect field score with
treaties quarantined is not a perfect system, since a quarantined treaty's
fields never reach a report at all.

This check earned its place. In run 2 it caught a real misread on three
treaties — the model computed `limit = stated_limit − retention`, producing a
non-contiguous programme — and refused all three rather than emitting wrong
money. See §5.

## 4. Retrieval — real embeddings, first measurement

`gemini-embedding-001` returns 768 dimensions, L2-normalised to 1.0, matching
`EMBED_DIM` and the vector index. Cosine margins against a planted decoy:

| Query | Operative clause | Decoy ("Inspection of Records") | Margin |
|---|---|---|---|
| `"loss occurrence"` | **0.778** | 0.633 | 0.145 |
| `"hours clause"` | **0.641** | 0.624 | **0.018** |

Both rank correctly, but the margins differ by 8×. The legal term of art
discriminates; the colloquial phrase barely separates the decoy. `STANDARD_QUERIES`
should prefer terms of art. This supersedes **R11** only in part: the embedder
is now real, but no recall or precision figure over the full corpus exists yet.

## 5. What the prompt revisions actually fixed

Listed because the headline number is only meaningful alongside them.

| Run | QA-3 | Cause |
|---|---|---|
| 1 | 87.0% *(W1 only)* | `limit` never defined; flood-hours instruction self-contradictory; `basis` free text; exclusions returned as full clause sentences |
| 2 | 58.1% | **`limit = stated − retention`** on 3 of 8 → quarantined by FR-INGEST-3 |
| 3 | 33.9% | quota 429s on 5 of 8 — **not** an accuracy result; retries added |
| 4 | 98.4% | `endorsement` returned `null` every time |
| 5 | 99.5% | `earthquake when written as such` — taxonomy example over-applied |
| 6 | **100.0%** | — |

Four findings generalise beyond this project:

1. **An open-ended map is the one shape the model will not populate.**
   `field_pages: dict[str, FieldProvenance]` came back `{}` and
   `endorsement: dict[str, str | int | None]` came back `null`, every run —
   while the model was *correctly applying* the endorsement it would not
   describe. Changed to a list of records and a typed object: both populated
   immediately. Lists and named fields work; free-form maps do not.
2. **`response_schema` cannot express exclusive bounds.** `Field(gt=0)` emits
   `exclusiveMinimum`, which Gemini's `Schema` rejects outright. The bound
   stays in Pydantic and the API gets a relaxed twin, so the schema no longer
   forbids a zero limit — making FR-INGEST-3's validation load-bearing rather
   than defensive.
3. **Quota looks exactly like inaccuracy.** An unretried 429 is indistinguishable
   from a wrong answer in the QA report. Run 3's 33.9% was entirely throttling.
   Retries now cover 429/503/500 and transport-level drops; a 400 is never
   retried, or a schema bug becomes a slow schema bug.
4. **`temperature=0` is not determinism.** Runs 2 and the diagnostic disagreed
   on the same PDFs with identical settings.

## 6. Access verification

`scripts/check_access.ps1` — **21 PASS · 1 WARN · 0 FAIL**. Billing linked;
all 8 required APIs enabled; Firestore Native mode (not changeable in place);
`response_schema` honoured; embeddings 768-dim.

The WARN is benign: Vertex's publisher-model *list* endpoint is not served at
`location=global`. Per-model `generateContent` is the real test and passed.

## 7. Not yet measured

Stated so no figure here is read as covering them.

- **The blind set (Y9).** The eight wordings are a structural holdout, not a
  blind set. Six prompt revisions ran against them.
- **FR-VERIFY-2 (VF7).** QA-10 passes 40/40 corruptions withheld and 0 false
  withholds, but every `semantic_pass` in the suite comes from a stub. The
  deterministic half only.
- **Retrieval recall/precision**, end-to-end latency (NFR-1), cost per
  analysis (NFR-4), QA-11 Courtroom determinism, QA-13 replay fidelity.
- **Vertex quota**, which throttled 8 sequential PDF requests. Relevant to
  NFR-1's p95 and to demo reliability.
- **B1 manual baseline** and **B8 usability** — both need humans.
