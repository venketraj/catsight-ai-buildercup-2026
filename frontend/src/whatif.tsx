/**
 * UI-15 - bounded what-if. Controls only (no free text): pick a treaty, then
 * either apply an hours clause to the REAL loss timeline, or cut the timeline
 * at a moment taken from that timeline - which is labelled HYPOTHETICAL.
 * Every figure comes from the engine via the API; this file only formats.
 */

import { useEffect, useMemo, useState } from "react";

import { API_BASE, formatUsd } from "./api";
import type { Impact } from "./types";

const WINDOWS = [24, 48, 72, 96, 120, 168, 240];

interface Priced {
  occurrence_losses: string[];
  total_ceded: string;
  cedent_retention: string;
  cedent_net_cost: string;
  market_net: string;
  our_loss: string;
  our_rip: string;
  our_net: string;
}

interface ScenarioResult {
  mode: "timing" | "hypothetical";
  hypothetical: boolean;
  label: string;
  occurrences: { index: number; start: string | null; end: string | null; loss: string }[];
  base: Priced;
  scenario: Priced;
  money_at_stake: Record<string, string>;
  timeline: { at: string; loss: string }[];
}

const ROWS: { key: keyof Priced; label: string; party: string; worseIfUp: boolean }[] = [
  { key: "cedent_net_cost", label: "Insurer's net cost (retention + reinstatement premium)", party: "the insurer", worseIfUp: true },
  { key: "market_net", label: "All reinsurers pay, net", party: "the reinsurance market", worseIfUp: true },
  { key: "our_net", label: "Our net cost (Lion Re)", party: "us", worseIfUp: true },
];

async function post(analysisId: string, body: object): Promise<ScenarioResult> {
  const response = await fetch(`${API_BASE}/api/analyses/${encodeURIComponent(analysisId)}/scenario`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(typeof detail === "string" ? detail : `The server returned ${response.status}.`);
  }
  return payload as ScenarioResult;
}

const hhmm = (iso: string) => `${iso.slice(5, 10)} ${iso.slice(11, 16)} UTC`;

export function WhatIfPanel({ analysisId, impact }: { analysisId: string; impact: Impact }) {
  const catXl = useMemo(() => impact.treaties.filter((t) => t.type === "CAT_XL"), [impact]);
  const [treatyId, setTreatyId] = useState(catXl[0]?.treaty_id ?? "");
  const [mode, setMode] = useState<"timing" | "hypothetical">("timing");
  const [hours, setHours] = useState(72);
  const [cut, setCut] = useState("");
  const [moments, setMoments] = useState<string[]>([]);
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // The timeline's own timestamps are the only cut points offered.
  useEffect(() => {
    if (!treatyId) return;
    post(analysisId, { treaty_id: treatyId, mode: "timing", hours_window: 72 })
      .then((r) => {
        const times = [...new Set(r.timeline.map((t) => t.at))].sort();
        setMoments(times.slice(1));
        setCut(times[Math.floor(times.length / 2)] ?? "");
      })
      .catch(() => setMoments([]));
  }, [analysisId, treatyId]);

  if (!catXl.length) return null;

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = mode === "timing"
        ? { treaty_id: treatyId, mode, hours_window: hours }
        : { treaty_id: treatyId, mode, split_at: [cut] };
      setResult(await post(analysisId, body));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel whatif" data-tour="whatif">
      <h2>What-if · one event or several?</h2>
      <p className="note" style={{ marginTop: 0 }}>
        The hours clause decides whether a disaster's losses count as one occurrence or several -
        and the insurer's retention applies again to each. Explore it here. Figures come from the
        loss engine; nothing is estimated by AI.
      </p>
      <div className="controls">
        <label>
          Treaty{" "}
          <select value={treatyId} onChange={(e) => { setTreatyId(e.target.value); setResult(null); }}>
            {catXl.map((t) => (
              <option key={t.treaty_id} value={t.treaty_id}>{t.treaty_id} · {t.cedent}</option>
            ))}
          </select>
        </label>
        <label>
          <input type="radio" checked={mode === "timing"} onChange={() => setMode("timing")} /> Real timing,
          clause of{" "}
          <select value={hours} disabled={mode !== "timing"} onChange={(e) => setHours(Number(e.target.value))}>
            {WINDOWS.map((w) => <option key={w} value={w}>{w} hours</option>)}
          </select>
        </label>
        <label>
          <input type="radio" checked={mode === "hypothetical"} onChange={() => setMode("hypothetical")}
                 disabled={!moments.length} /> Hypothetical cut at{" "}
          <select value={cut} disabled={mode !== "hypothetical"} onChange={(e) => setCut(e.target.value)}>
            {moments.map((m) => <option key={m} value={m}>{hhmm(m)}</option>)}
          </select>
        </label>
        <button className="primary" onClick={run} disabled={busy || !treatyId}>
          {busy ? "Pricing…" : "Price it"}
        </button>
      </div>
      {error && <p className="banner error">{error}</p>}

      {result && (
        <>
          <p className={result.hypothetical ? "banner hypothetical" : "banner info"}>{result.label}</p>
          <p className="note">
            Occurrences:{" "}
            {result.occurrences.map((o) => `#${o.index} ${formatUsd(o.loss)}`).join("  ·  ")}
          </p>
          <table>
            <thead>
              <tr>
                <th>Party</th>
                <th className="num">As one occurrence</th>
                <th className="num">{result.hypothetical ? "Hypothetical" : "Scenario"}</th>
                <th>Money at stake</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => {
                const delta = Number(result.money_at_stake[row.key]);
                const words = delta === 0
                  ? "no change"
                  : `${row.party} ${delta > 0 ? "pays" : "saves"} ${formatUsd(Math.abs(delta))}`;
                return (
                  <tr key={row.key}>
                    <td>{row.label}</td>
                    <td className="num">{formatUsd(result.base[row.key] as string)}</td>
                    <td className="num">{formatUsd(result.scenario[row.key] as string)}</td>
                    <td className={delta === 0 ? "" : delta > 0 ? "worse" : "better"}>
                      {delta === 0 ? "—" : `${delta > 0 ? "+" : "−"}${formatUsd(Math.abs(delta))}`} · {words}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
