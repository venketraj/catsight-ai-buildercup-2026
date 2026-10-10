/**
 * API client.
 *
 * The analysis stream uses `fetch()` with a ReadableStream rather than
 * `EventSource`, for a reason worth stating: EventSource cannot POST, cannot
 * set headers, and cannot be cancelled cleanly. The analysis needs a request
 * body, so EventSource is not an option even though this is server-sent
 * events.
 */

import type {
  AskResult,
  Benchmark,
  Clause,
  EventSummary,
  Explanation,
  Frame,
  Health,
  KnowledgeBase,
  Methodology,
  TreatyDetail,
  TreatySummary,
} from "./types";

/**
 * Empty string means same-origin, which is what we get when the API serves
 * the built frontend. A full URL points at Cloud Run during local
 * development. Reading it from the environment keeps the host out of the
 * source - the same rule the backend follows.
 */
export const API_BASE: string = (
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8080"
).replace(/\/$/, "");

export const BUILD_LABEL: string = import.meta.env.VITE_BUILD_LABEL ?? "dev";

async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { signal });
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return (await response.json()) as T;
}

/**
 * An error handler that ignores cancellation. A request aborted because the
 * component unmounted - which React's StrictMode does deliberately once in
 * development - is not a failure and must not be shown as one.
 */
export function unlessAborted(show: (message: string) => void) {
  return (error: unknown) => {
    if ((error as Error)?.name === "AbortError") return;
    show(String((error as Error)?.message ?? error));
  };
}

export function fetchHealth(signal?: AbortSignal): Promise<Health> {
  return getJSON<Health>("/healthz", signal);
}

export function fetchEvents(signal?: AbortSignal): Promise<{ events: EventSummary[] }> {
  return getJSON<{ events: EventSummary[] }>("/api/events", signal);
}

export async function askQuestion(analysisId: string, question: string): Promise<AskResult> {
  const response = await fetch(`${API_BASE}/api/analyses/${encodeURIComponent(analysisId)}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    throw new Error(typeof detail === "string" ? detail : detail?.message ?? `The server returned ${response.status}.`);
  }
  return (await response.json()) as AskResult;
}

export function fetchTreaties(signal?: AbortSignal): Promise<{ treaties: TreatySummary[] }> {
  return getJSON("/api/treaties", signal);
}

export function fetchTreaty(treatyId: string, signal?: AbortSignal): Promise<TreatyDetail> {
  return getJSON(`/api/treaties/${encodeURIComponent(treatyId)}`, signal);
}

export function fetchMethodology(signal?: AbortSignal): Promise<Methodology> {
  return getJSON("/api/methodology", signal);
}

export function fetchKnowledgeBase(signal?: AbortSignal): Promise<KnowledgeBase> {
  return getJSON<KnowledgeBase>("/api/knowledge-base", signal);
}

export function fetchClauses(
  treatyId: string,
  signal?: AbortSignal,
): Promise<{ treaty_id: string; clauses: Clause[] }> {
  return getJSON(`/api/treaties/${encodeURIComponent(treatyId)}/clauses`, signal);
}

export interface AnalysisRequest {
  mode?: "replay" | "live";
  event_id?: string;
  as_if?: boolean;
  /** Undefined lets the server decide: agents when GCP is configured. */
  agents?: boolean;
  /** Play back the recorded real run instead of running live. */
  replay?: boolean;
}

/**
 * Run an analysis, yielding each SSE frame as it arrives.
 *
 * An async generator rather than a callback so the caller can `for await` and
 * stop simply by breaking - which also aborts the request.
 */
export async function* runAnalysis(
  body: AnalysisRequest,
  signal?: AbortSignal,
): AsyncGenerator<Frame, void, void> {
  const response = await fetch(`${API_BASE}/api/analyses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "replay", ...body }),
    signal,
  });

  if (response.status === 429) {
    // FR-GUARD-5: the server explains itself, so show its message rather than
    // inventing "too many requests".
    const detail = await response.json().catch(() => null);
    const message =
      detail?.detail?.message ??
      "The analysis limit has been reached. A cached result is still available.";
    yield { type: "error", message, retryable: false };
    return;
  }

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => "");
    yield {
      type: "error",
      message: text || `The server returned ${response.status}.`,
      retryable: response.status >= 500,
    };
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Frames are separated by a blank line. Anything after the last
      // separator is a partial frame and stays in the buffer - splitting on
      // every newline would try to parse half a JSON object.
      let separator = buffer.indexOf("\n\n");
      while (separator !== -1) {
        const raw = buffer.slice(0, separator);
        buffer = buffer.slice(separator + 2);
        const frame = parseFrame(raw);
        if (frame) yield frame;
        separator = buffer.indexOf("\n\n");
      }
    }
    const tail = parseFrame(buffer);
    if (tail) yield tail;
  } finally {
    reader.releaseLock();
  }
}

function parseFrame(raw: string): Frame | null {
  const line = raw.trim();
  if (!line.startsWith("data:")) return null;
  try {
    return JSON.parse(line.slice("data:".length).trim()) as Frame;
  } catch {
    // A malformed frame is dropped rather than killing the stream: losing one
    // progress update is survivable, losing the whole analysis is not.
    return null;
  }
}

/** Money arrives as a string and is never parsed for arithmetic - only to display. */
export function formatMoney(value: string | undefined, dp = 2): string {
  if (value === undefined) return "-";
  const asNumber = Number(value);
  if (!Number.isFinite(asNumber)) return value;
  return asNumber.toLocaleString("en-US", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });
}

/**
 * USD millions (as served) to "$54.30M" or "$41.89B". Display only: the
 * value is scaled for reading, never used in a calculation.
 */
export function formatUsd(valueInMillions: string | number | undefined | null): string {
  if (valueInMillions === undefined || valueInMillions === null) return "-";
  const n = Number(valueInMillions);
  if (!Number.isFinite(n)) return String(valueInMillions);
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(2)}B`;
  return `$${n.toFixed(2)}M`;
}

export function fetchExplanation(
  analysisId: string,
  treatyId: string,
  signal?: AbortSignal,
): Promise<Explanation> {
  return getJSON(
    `/api/analyses/${encodeURIComponent(analysisId)}/treaties/${encodeURIComponent(treatyId)}`,
    signal,
  );
}

export function fetchBenchmark(eventId: string, signal?: AbortSignal): Promise<Benchmark> {
  return getJSON(`/api/benchmark?event_id=${encodeURIComponent(eventId)}`, signal);
}

export function formatPercent(value: string | undefined): string {
  if (value === undefined) return "-";
  const asNumber = Number(value);
  if (!Number.isFinite(asNumber)) return value;
  return `${(asNumber * 100).toFixed(1)}%`;
}
