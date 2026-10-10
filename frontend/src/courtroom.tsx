/**
 * UI-14 - the Clause Courtroom. Two counsel, each shown only with a verified
 * quote (or shown as dropped, with the reason); the engine's price of each
 * reading; money at stake per party, computed by the API; the arbiter's
 * summary; and the analyst's recorded position. Labelled issue-spotting,
 * not legal advice. Every figure is served by the API; nothing is computed
 * here.
 */

import { useState } from "react";

import { ClauseViewer, Markdown } from "./agents";
import { API_BASE, formatUsd } from "./api";
import type { Citation } from "./types";

interface Side {
  side: "cedent" | "reinsurer";
  verified: boolean;
  dropped_reason?: string;
  reading: string | null;
  argument_md?: string;
  excluded_share?: number;
  citation?: Citation;
  priced?: { label: string; scenario: Record<string, string> };
}

interface Court {
  skipped: boolean;
  reason?: string;
  label: string;
  flag?: { treaty_id: string; issue_type: string; explanation: string };
  sides?: Record<string, Side>;
  money_at_stake?: Record<string, string>;
  arbiter_md?: string;
  unsupported_figures?: string[];
  cost_usd?: string | null;
  position?: { position: string; note: string; decided_at: string };
}

const PARTIES: { key: string; label: string }[] = [
  { key: "cedent_net_cost", label: "Insurer's net cost" },
  { key: "market_net", label: "All reinsurers pay" },
  { key: "our_net", label: "Our net (Lion Re)" },
];

const TITLES = { cedent: "Counsel for the insurer (cedent)", reinsurer: "Counsel for the reinsurers" };

async function call(path: string, init?: RequestInit) {
  const response = await fetch(`${API_BASE}${path}`, init);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    throw new Error(typeof detail === "string" ? detail : detail?.message ?? `The server returned ${response.status}.`);
  }
  return body;
}

export function CourtroomPanel({ runId }: { runId: string }) {
  const [court, setCourt] = useState<Court | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState<Citation | null>(null);
  const [position, setPosition] = useState("unresolved");
  const [note, setNote] = useState("");

  const open = async (rerun = false) => {
    setBusy(true);
    setError(null);
    try {
      const result = (await call(`/api/runs/${runId}/courtroom${rerun ? "?rerun=true" : ""}`,
                                 { method: "POST" })) as Court;
      setCourt(result);
      if (result.position) {
        setPosition(result.position.position);
        setNote(result.position.note);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    try {
      const saved = await call(`/api/runs/${runId}/courtroom/position`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ position, note }),
      });
      setCourt((c) => (c ? { ...c, position: saved } : c));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section className="panel court" data-tour="court">
      <h2>Clause Courtroom</h2>
      <p className="banner court-label">⚖ Issue-spotting, not legal advice. Two AI counsel argue; the analyst decides.</p>
      {!court && (
        <>
          <p className="note">
            Takes the most material disputed exclusion flag from this analysis, has two counsel argue
            opposite readings in parallel, verifies every quote, and prices each reading with the loss
            engine (about 15 seconds).
          </p>
          <button className="primary" onClick={() => open()} disabled={busy}>
            {busy ? "Counsel are arguing…" : "Open the Clause Courtroom"}
          </button>
        </>
      )}
      {error && <p className="banner error">{error}</p>}

      {court?.skipped && <p className="note">Courtroom skipped: {court.reason}</p>}

      {court && !court.skipped && court.sides && (
        <>
          <p>
            <strong>In dispute:</strong> {court.flag?.treaty_id} {court.flag?.issue_type} -{" "}
            {court.flag?.explanation}
          </p>
          <div className="court-grid">
            {(["cedent", "reinsurer"] as const).map((key) => {
              const s = court.sides?.[key];
              return (
                <div key={key} className={`court-side ${key}`}>
                  <h3>{TITLES[key]}</h3>
                  {!s || !s.verified ? (
                    <p className="dropped">
                      Dropped - {s?.dropped_reason ?? "no argument"}. An argument without verified wording is never shown.
                    </p>
                  ) : (
                    <>
                      <p className="reading">{s.reading}</p>
                      {s.citation && (
                        <>
                          <blockquote>“{s.citation.quote}”</blockquote>
                          <button className="cite" onClick={() => setOpened(s.citation!)}>
                            ✓ verified · {s.citation.treaty_id} p.{s.citation.page} cl.{s.citation.clause_no}
                          </button>
                        </>
                      )}
                      <Markdown text={s.argument_md ?? ""} />
                      <p className="assumption">
                        Position for pricing: {Math.round((s.excluded_share ?? 0) * 100)}% of the loss treated as excluded
                        (an assumption - the data does not separate this damage).
                      </p>
                      {s.priced && (
                        <table>
                          <tbody>
                            {PARTIES.map((p) => (
                              <tr key={p.key}>
                                <td>{p.label}</td>
                                <td className="num">{formatUsd(s.priced!.scenario[p.key])}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </>
                  )}
                </div>
              );
            })}
          </div>

          {court.money_at_stake ? (
            <div className="stake">
              <strong>Money at stake</strong> - the reinsurers' reading compared with the insurer's:
              {PARTIES.map((p) => {
                const v = Number(court.money_at_stake![p.key]);
                return (
                  <span key={p.key} className={v === 0 ? "" : v > 0 ? "worse" : "better"}>
                    {p.label}: {v === 0 ? "no change" : `${v > 0 ? "+" : "−"}${formatUsd(Math.abs(v))}`}
                  </span>
                );
              })}
            </div>
          ) : (
            <p className="note">Money at stake is shown only when both sides cite verified wording.</p>
          )}

          <h3>Arbiter's summary</h3>
          <Markdown text={court.arbiter_md ?? ""} />
          {court.unsupported_figures && court.unsupported_figures.length > 0 ? (
            <p className="banner error">Figures not in the inputs: {court.unsupported_figures.join(", ")}</p>
          ) : (
            <p className="verify-header">✓ Every figure in the summary came from the engine or the evidence.</p>
          )}

          <h3>Analyst's position</h3>
          <div className="position">
            {([["cedent_reading", "Insurer's reading"], ["reinsurer_reading", "Reinsurers' reading"],
              ["unresolved", "Unresolved"]] as const).map(([value, label]) => (
              <label key={value}>
                <input type="radio" name="position" checked={position === value}
                       onChange={() => setPosition(value)} /> {label}
              </label>
            ))}
            <input type="text" maxLength={500} placeholder="Note (optional), e.g. need adjuster's wind/surge split"
                   value={note} onChange={(e) => setNote(e.target.value)} />
            <button className="primary" onClick={save}>Record position</button>
          </div>
          {court.position && (
            <p className="note">
              Recorded: {court.position.position.replace("_", " ")} at {court.position.decided_at.replace("T", " ").slice(0, 16)} UTC
              {court.position.note ? ` - "${court.position.note}"` : ""}
            </p>
          )}
          <p className="note">
            {court.cost_usd ? `Model cost $${court.cost_usd} · ` : ""}
            <button className="linkish" onClick={() => open(true)} disabled={busy}>
              {busy ? "Re-running…" : "Run the Courtroom again"}
            </button>
          </p>
        </>
      )}
      {opened && <ClauseViewer citation={opened} onClose={() => setOpened(null)} />}
    </section>
  );
}
