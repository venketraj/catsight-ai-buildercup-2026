/**
 * The API contract, mirrored from `backend/app/analysis.py`.
 *
 * Money arrives as **strings**, not numbers, and stays that way until it is
 * formatted. The backend computes in Decimal precisely because binary float
 * gets the split case wrong - `7.85 - 0.525` is 7.324999999999999 - so
 * parsing it into a JS number here would reintroduce the error the whole
 * pipeline exists to avoid. Nothing in this app does arithmetic on money.
 */

export type Peril = "WS" | "EQ" | "FL" | "OTHER";

export interface EventSummary {
  event_id: string;
  name: string;
  peril: Peril;
  date: string;
  countries: string[];
  duration_h: number | null;
  regions: number;
  /** A recorded real run exists and can be played back instantly. */
  replay_available?: boolean;
}

export interface EventFact {
  text: string;
  source: string;
  url?: string | null;
}

export interface LayerResult {
  layer_no: number;
  ceded: string;
  our_loss: string;
  our_rip: string;
  /** Exceeds 1 when reinstatements are used - the layer chart's whole point. */
  burn: string;
  exhausted: boolean;
  reinstated: string;
}

export interface TreatyOutcome {
  treaty_id: string;
  cedent_id: string;
  cedent: string;
  type: "CAT_XL" | "QS";
  gross: string;
  regions: string[];
  our_net: string;
  ceded: string;
  layers?: LayerResult[];
  /** The full per-party view (MONEY_MOMENT 4.4), Cat XL only. */
  cedent_retention?: string;
  cedent_net_cost?: string;
  total_rip?: string;
  our_loss?: string;
  our_rip?: string;
  market_net?: string;
  capped?: boolean;
}

export interface Impact {
  event: {
    event_id: string;
    name: string;
    peril: Peril;
    start: string;
    end: string;
    duration_h: number | null;
    regions: number;
    facts: EventFact[];
    disclaimer?: string | null;
  };
  totals: {
    gross: string;
    ceded: string;
    /** What the insurers keep (gross - ceded), computed by the engine. */
    retained?: string;
    our_net: string;
    treaties_matched: number;
    treaties_excluded: number;
  };
  as_if: boolean;
  /** The method version the figures were produced under. */
  methodology?: { version: string | null; effective_from: string | null };
  treaties: TreatyOutcome[];
  excluded: { treaty_id: string; reason: string }[];
}

export interface Citation {
  treaty_id: string;
  page: number;
  clause_no: string;
  quote: string;
  source: "text" | "transcription";
}

export interface WordingFlag {
  treaty_id: string;
  issue_type: "HOURS" | "EXCLUSION" | "TERRITORY" | "REINSTATEMENT" | "PERIOD";
  severity: "HIGH" | "MEDIUM" | "LOW";
  explanation: string;
  citation: Citation;
}

export interface RetrievalHit {
  chunk_id: string;
  clause_no: string | null;
  title: string | null;
  page: number;
  score: number;
}

export interface Withheld {
  treaty_id: string;
  issue_type: string;
  reason: string | null;
}

export interface Clause {
  chunk_id: string;
  clause_no: string | null;
  title: string | null;
  page: number;
  pages: number[];
  source: "text" | "transcription";
  text: string;
}

/** SSE frames (API-4). */
export type Frame =
  | { type: "stage"; agent: string; status: "started" | "completed" }
  | { type: "tool"; agent: string; name: string; summary: string }
  | { type: "partial"; agent: string; text: string }
  | {
      type: "retrieval";
      agent: string;
      treaty_id: string;
      query: string;
      hits: RetrievalHit[];
    }
  | { type: "flag"; status: "candidate" | "verified"; badge?: string; flag: WordingFlag }
  | { type: "verification"; header: string; verified: number; withheld: Withheld[] }
  | {
      type: "report";
      markdown: string;
      unsupported_figures: string[];
      calls: Record<string, number>;
      usage?: Record<string, { input: number; output: number }>;
      cost_usd?: string | null;
    }
  | { type: "warning"; agent: string; treaty_id?: string; message: string }
  | {
      type: "notice";
      kind: "replay";
      reason: string;
      recorded_at: string;
      live_seconds: number;
      message: string;
    }
  | { type: "result"; key: "event"; data: Impact["event"] }
  | { type: "result"; key: "impact"; data: Impact }
  | { type: "result"; key: string; data: unknown }
  | { type: "error"; message: string; retryable: boolean }
  | { type: "done"; analysis_id: string; agents?: boolean; replay?: boolean; run_id?: string };

export interface IngestionRecord {
  treaty_id: string;
  wording_id: string;
  pdf: string;
  clauses: number;
  embedded: number;
  transcribed_pages: number[];
  embed_model: string;
  embed_dim: number;
  vector_store: string;
  extraction_model: string;
  fields_extracted: number;
  citations_verified: number;
  citations_total: number;
  retrieval_hits: number;
  retrieval_total: number;
  structurally_valid: boolean;
  seconds: number;
  ingested_at: string;
}

export interface ExplainedLayer {
  layer_no: number;
  attaches_usd_m: string;
  limit_usd_m: string;
  ceded_usd_m: string;
  our_share: string;
  our_loss_usd_m: string;
  our_rip_usd_m: string;
  formula: string;
  our_formula: string;
  rip_formula: string;
}

export interface Explanation {
  treaty_id: string;
  cedent: string;
  type: "CAT_XL" | "QS";
  perspective: string;
  event: { name: string; peril: Peril; start: string; end: string; source: string };
  match: {
    matched: boolean;
    reason: string;
    territory: { include: string[]; exclude: string[] };
    perils: string[];
  };
  damage: {
    rows: {
      region: string;
      name: string | null;
      intensity: number | null;
      unit: string;
      insured_usd_m: string;
      damage_ratio: string;
      loss_usd_m: string;
    }[];
    regions: number;
    curve: string;
    method_version: string;
    gross_usd_m?: string;
  };
  citations: Record<
    string,
    { page: number; clause_no: string; quote: string; status: string; agrees_with_book: boolean }
  >;
  layers?: ExplainedLayer[];
  quota_share?: {
    cession_pct: string;
    event_limit_usd_m: number | null;
    ceded_usd_m: string;
    capped: boolean;
    our_net_usd_m: string;
  };
  parties?: {
    cedent_keeps_usd_m: string;
    reinsurers_pay_usd_m: string;
    our_gross_usd_m?: string;
    our_rip_usd_m?: string;
    our_net_usd_m: string;
  };
}

export interface Benchmark {
  manual_baseline: {
    status: string;
    label: string;
    reference_firm: string;
    steps: { step: string; manual_hours: [number, number]; catsight: string }[];
    total_hours: [number, number];
    catsight_review_hours: [number, number];
    elapsed: string;
    catsight_elapsed: string;
    loaded_rate_usd_per_hour: number;
    rate_note: string;
    manual_cost_usd?: [number, number];
    catsight_review_cost_usd?: [number, number];
  };
  pricing: { source: string };
  real_world: {
    headline: string;
    facts: { text: string; source: string }[];
    not_like_for_like: string;
  } | null;
}

export interface AskResult {
  analysis_id: string;
  question: string;
  answer_md: string;
  citations: Citation[];
  withheld: { chunk_id: string; reason: string }[];
  unsupported_figures: string[];
  searched: string[];
  /** True when clause search failed (quota, network) and the answer uses the engine's figures only. */
  retrieval_skipped?: boolean;
  cost_usd: string | null;
}

export interface TreatySummary {
  treaty_id: string;
  cedent_id: string;
  cedent: string;
  type: "CAT_XL" | "QS";
  perils: string[];
  territory: { include: string[]; exclude: string[] };
  inception: string;
  expiry: string;
  currency: string;
  hours_clause: Record<string, number>;
  layers: number;
  has_wording: boolean;
  wording_id: string | null;
}

export interface ReconciliationRow {
  field: string;
  booked: unknown;
  wording: unknown;
  result: "match" | "differs" | "unverified" | "book_only" | "wording_only";
  citation: { status: string; page: number | null; clause_no: string | null; quote: string | null } | null;
}

export interface TreatyDetail {
  treaty_id: string;
  cedent: string;
  type: "CAT_XL" | "QS";
  perils: string[];
  territory: { include: string[]; exclude: string[] };
  inception: string;
  expiry: string;
  currency: string;
  hours_clause: Record<string, number>;
  exclusions: string[];
  layers: {
    layer_no: number;
    retention: number;
    limit: number;
    premium: number;
    our_share: number;
    reinstatements: { count?: number; rate?: number; basis?: string };
  }[];
  qs: { cession_pct?: number; event_limit?: number; our_share?: number } | null;
  wording_id: string | null;
  endorsement: Record<string, unknown> | null;
  reconciliation: {
    status: string;
    counts: Record<string, number>;
    fields: ReconciliationRow[];
  } | null;
}

export interface Methodology {
  version: string;
  effective_from: string;
  status: string;
  approved_by: string;
  conventions: Record<string, { rule: string; source: string }>;
  changelog: { version: string; date: string; change: string }[];
  vulnerability: {
    wind: { function: string; v_threshold_ms: number; v_half_ms: Record<string, number>;
            calibration_factor: Record<string, number> };
    earthquake: { function: string; mmi_damage_ratio: Record<string, number>;
                  country_factor: Record<string, number> };
    bands: { wind_ms: number[]; mmi: number[] };
  };
}

export interface KnowledgeBase {
  wordings: IngestionRecord[];
  totals: {
    wordings: number;
    clauses: number;
    citations_verified: number;
    citations_total: number;
    retrieval_hits: number;
    retrieval_total: number;
  };
}

export interface Health {
  status: string;
  version: string;
  build: string;
  configured: boolean;
  models: { main: string; reason: string; embed: string; embed_dim: number };
  location: string;
  features: { courtroom: boolean; cached_replay_only: boolean };
  warnings: string[];
}
