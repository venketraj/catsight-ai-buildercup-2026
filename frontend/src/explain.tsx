/**
 * Making the numbers legible: whose view this is, how each figure was
 * reached, and what the run saved against a manual first view. Every figure
 * shown is served by the API; the browser formats, it never calculates.
 */

import { useEffect, useState } from "react";

import { fetchBenchmark, fetchExplanation, formatUsd, unlessAborted } from "./api";
import type { Benchmark, Explanation, Impact } from "./types";

// ---------------------------------------------------------- flow summary -- //

export function FlowSummary({ impact }: { impact: Impact }) {
  const t = impact.totals;
  return (
    <section className="panel flow" data-tour="money">
      <h2>The result, from our side</h2>
      <p className="perspective">
        <strong>We are Lion Re, a reinsurer.</strong> Insurers in Japan, the Philippines and Taiwan
        (our clients, the <em>cedents</em>) pass part of their disaster losses to reinsurers like
        us. This shows what <strong>{impact.event.name}</strong> would cost each party on today's
        book.
      </p>
      <div className="flow-steps">
        <FlowStep value={`${impact.event.regions}`} label="regions hit" sub={impact.event.name} />
        <Arrow />
        <FlowStep value={`${t.treaties_matched}`} label="treaties respond"
                  sub={`${t.treaties_excluded} do not`} />
        <Arrow />
        <FlowStep value={formatUsd(t.gross)} label="insurers' claims" sub="damage to insured property" />
        <Arrow />
        <FlowStep value={formatUsd(t.retained)} label="insurers keep" sub="their deductibles" tone="cedent" />
        <FlowStep value={formatUsd(t.ceded)} label="reinsurers pay" sub="all reinsurers together" tone="market" />
        <Arrow />
        <FlowStep value={formatUsd(t.our_net)} label="our net cost" sub="our share, after reinstatement premium" tone="ours" />
      </div>
      <MoneyBar gross={t.gross} retained={t.retained} ceded={t.ceded} ours={t.our_net} />
      <p className="note">
        Synthetic book of fictional insurers - not {impact.event.name}'s real market loss.
        Open any treaty below with <strong>How?</strong> to see every step.
      </p>
    </section>
  );
}

function FlowStep({ value, label, sub, tone }: { value: string; label: string; sub: string; tone?: string }) {
  return (
    <div className={`flow-step ${tone ?? ""}`}>
      <div className="flow-value">{value}</div>
      <div className="flow-label">{label}</div>
      <div className="flow-sub">{sub}</div>
    </div>
  );
}

/** The insurers' claims as one bar: what they keep, what reinsurers pay, and
 * our slice of the latter. Widths are engine totals over gross - nothing new
 * is computed. Our net is after reinstatement premium, so it is drawn as a
 * marked portion of the reinsurers' side, not as a third share of gross. */
function MoneyBar({ gross, retained, ceded, ours }: { gross: string; retained?: string; ceded: string; ours: string }) {
  const g = Number(gross);
  if (!(g > 0) || retained === undefined) return null;
  const keep = Number(retained) / g;
  const pay = Number(ceded) / g;
  const our = Math.min(Math.max(Number(ours), 0) / Math.max(Number(ceded), 1), 1);
  return (
    <>
    <div className="money-bar" role="img"
         aria-label={`Of ${formatUsd(gross)} in claims, insurers keep ${formatUsd(retained)} and reinsurers pay ${formatUsd(ceded)}, of which our net cost is ${formatUsd(ours)}`}>
      <div className="mb-seg mb-cedent" style={{ flexGrow: keep }} title={`Insurers keep ${formatUsd(retained)}`}>
        {keep > 0.12 && <span>Insurers keep {formatUsd(retained)}</span>}
      </div>
      <div className="mb-seg mb-market" style={{ flexGrow: pay }} title={`Reinsurers pay ${formatUsd(ceded)}`}>
        <div className="mb-ours" style={{ width: `${our * 100}%` }} title={`Our net ${formatUsd(ours)}`} />
        {pay > 0.12 && <span>Reinsurers pay {formatUsd(ceded)}</span>}
      </div>
    </div>
    <div className="split-legend">
      <span><i className="swatch" style={{ background: "var(--cedent)" }} /> insurers keep</span>
      <span><i className="swatch" style={{ background: "var(--market)" }} /> all reinsurers pay</span>
      <span><i className="swatch" style={{ background: "var(--ours)" }} /> our net (Lion Re), {formatUsd(ours)}</span>
    </div>
    </>
  );
}

const Arrow = () =><div className="flow-arrow" aria-hidden>→</div>;

// ------------------------------------------------- how was this calculated -- //

export function ExplainModal({
  analysisId,
  treatyId,
  onClose,
}: {
  analysisId: string;
  treatyId: string;
  onClose: () => void;
}) {
  const [x, setX] = useState<Explanation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [allRows, setAllRows] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchExplanation(analysisId, treatyId, controller.signal)
      .then(setX)
      .catch(unlessAborted(setError));
    return () => controller.abort();
  }, [analysisId, treatyId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows = x ? (allRows ? x.damage.rows : x.damage.rows.slice(0, 8)) : [];

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>How was this calculated? · {treatyId}{x ? ` · ${x.cedent}` : ""}</strong>
          <span className="spacer" />
          <button onClick={onClose} aria-label="Close">✕</button>
        </div>
        {error && <p className="banner error">{error}</p>}
        {!x && !error && <p className="note">Loading the calculation…</p>}
        {x && (
          <ol className="steps">
            <li>
              <h3>1 · The disaster data</h3>
              <p>
                {x.event.name}, {x.event.start.slice(0, 10)}. Peak{" "}
                {x.event.peril === "WS" ? "wind speed" : "shaking intensity"} for each region,
                from {x.event.source}'s recorded {x.event.peril === "WS" ? "track" : "ShakeMap"}.
              </p>
            </li>
            <li>
              <h3>2 · Does this treaty respond?</h3>
              <p className={x.match.matched ? "ok" : "bad"}>
                {x.match.matched ? "✓ Yes" : "✕ No"} — {x.match.reason}.{" "}
                <span className="note">
                  Covers {x.match.perils.join(", ")} in {x.match.territory.include.join(", ")}
                  {x.match.territory.exclude.length ? `, excluding ${x.match.territory.exclude.join(", ")}` : ""}.
                </span>
              </p>
            </li>
            {x.match.matched && (
              <li>
                <h3>3 · Damage to {x.cedent}'s insured property (the gross loss)</h3>
                <p className="note">
                  Insured value in each region × damage % for that intensity ({x.damage.curve},
                  method {x.damage.method_version}).
                </p>
                <table>
                  <thead>
                    <tr>
                      <th>Region</th>
                      <th className="num">Intensity</th>
                      <th className="num">Insured value</th>
                      <th className="num">Damage %</th>
                      <th className="num">Loss</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.region}>
                        <td>{r.name ?? r.region}</td>
                        <td className="num">{r.intensity} {r.unit}</td>
                        <td className="num">{formatUsd(r.insured_usd_m)}</td>
                        <td className="num">{(Number(r.damage_ratio) * 100).toFixed(3)}%</td>
                        <td className="num">{formatUsd(r.loss_usd_m)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td colSpan={4}>
                        Total across {x.damage.regions} regions
                        {!allRows && x.damage.rows.length > 8 && (
                          <button className="linkish" onClick={() => setAllRows(true)}>
                            show all {x.damage.rows.length}
                          </button>
                        )}
                      </td>
                      <td className="num"><strong>{formatUsd(x.damage.gross_usd_m)}</strong></td>
                    </tr>
                  </tfoot>
                </table>
              </li>
            )}
            {x.layers && x.parties && (
              <li>
                <h3>4 · How the treaty splits {formatUsd(x.damage.gross_usd_m)}</h3>
                <table>
                  <thead>
                    <tr>
                      <th>Layer</th>
                      <th>Reinsurers pay</th>
                      <th className="num">Our share</th>
                      <th>We pay</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Below {formatUsd(x.layers[0]?.attaches_usd_m)}</td>
                      <td colSpan={3}>{x.cedent} keeps {formatUsd(x.parties.cedent_keeps_usd_m)}</td>
                    </tr>
                    {x.layers.map((l) => {
                      const cite = x.citations[`layers.${l.layer_no}.limit`];
                      return (
                        <tr key={l.layer_no}>
                          <td>
                            L{l.layer_no}: {formatUsd(l.limit_usd_m)} xs {formatUsd(l.attaches_usd_m)}
                            {cite && (
                              <div className="cite-small" title={cite.quote}>
                                ✓ p.{cite.page} cl.{cite.clause_no}
                              </div>
                            )}
                          </td>
                          <td>
                            <strong>{formatUsd(l.ceded_usd_m)}</strong>
                            <div className="formula">{l.formula}</div>
                          </td>
                          <td className="num">{l.our_share}</td>
                          <td>
                            <strong>{formatUsd(l.our_loss_usd_m)}</strong>
                            <div className="formula">{l.our_formula}</div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <div className="net-line">
                  We pay {formatUsd(x.parties.our_gross_usd_m)} − reinstatement premium received{" "}
                  {formatUsd(x.parties.our_rip_usd_m)} ={" "}
                  <strong className="ours">our net {formatUsd(x.parties.our_net_usd_m)}</strong>
                </div>
                <details className="formula-details">
                  <summary>Reinstatement premium formulas</summary>
                  {x.layers.map((l) => (
                    <div key={l.layer_no} className="formula">L{l.layer_no}: {l.rip_formula}</div>
                  ))}
                </details>
              </li>
            )}
            {x.quota_share && x.parties && (
              <li>
                <h3>4 · How the quota share splits {formatUsd(x.damage.gross_usd_m)}</h3>
                <p>
                  Reinsurers take a fixed {(Number(x.quota_share.cession_pct) * 100).toFixed(0)}% of
                  every loss{x.quota_share.capped ? ", capped at the event limit" : ""}:{" "}
                  <strong>{formatUsd(x.quota_share.ceded_usd_m)}</strong>. {x.cedent} keeps{" "}
                  {formatUsd(x.parties.cedent_keeps_usd_m)}.
                </p>
                <div className="net-line">
                  <strong className="ours">Our net {formatUsd(x.parties.our_net_usd_m)}</strong>
                </div>
              </li>
            )}
          </ol>
        )}
        <p className="note">
          All figures from the deterministic loss engine; no language model calculates any number.
          {x ? ` ${x.perspective}.` : ""}
        </p>
      </div>
    </div>
  );
}

// -------------------------------------------------------------- benchmark -- //

export interface RunMetrics {
  seconds: number;
  calls: number;
  costUsd: string | null | undefined;
  verified: number;
  withheld: number;
  wordingsChecked: number;
  treatiesMatched: number;
}

export function BenchmarkPanel({ eventId, metrics }: { eventId: string; metrics: RunMetrics }) {
  const [b, setB] = useState<Benchmark | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetchBenchmark(eventId, controller.signal).then(setB).catch(() => setB(null));
    return () => controller.abort();
  }, [eventId]);
  if (!b) return null;
  const m = b.manual_baseline;
  const usd = (n: number) => `$${n.toLocaleString("en-US")}`;
  return (
    <section className="panel bench">
      <h2>Business impact · this run vs a manual first view</h2>
      <div className="bench-grid">
        <div className="bench-col real">
          <div className="bench-tag">Real world · published</div>
          {b.real_world ? (
            <>
              <h3>{b.real_world.headline}</h3>
              <ul>
                {b.real_world.facts.map((f) => (
                  <li key={f.text}>
                    {f.text} <span className="src">— {f.source}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="note">No published market figures on record for this event.</p>
          )}
        </div>
        <div className="bench-col manual">
          <div className="bench-tag">Manual analyst · simulated</div>
          <h3>{m.total_hours[0]}–{m.total_hours[1]} person-hours · {m.elapsed}</h3>
          <ul>
            {m.steps.map((s) => (
              <li key={s.step}>
                {s.step}: <strong>{s.manual_hours[0]}–{s.manual_hours[1]} h</strong>
              </li>
            ))}
          </ul>
          {m.manual_cost_usd && (
            <p>≈ {usd(m.manual_cost_usd[0])}–{usd(m.manual_cost_usd[1])} at ${m.loaded_rate_usd_per_hour}/h</p>
          )}
          <p className="src">{m.label}</p>
        </div>
        <div className="bench-col ours">
          <div className="bench-tag">CatSight · measured on this run</div>
          <h3>{metrics.seconds}s automated + {m.catsight_review_hours[0]}–{m.catsight_review_hours[1]} h review</h3>
          <ul>
            <li>{metrics.treatiesMatched} responding treaties found and priced</li>
            <li>{metrics.wordingsChecked} wordings searched live in Firestore</li>
            <li>{metrics.verified} clause flag(s) verified · {metrics.withheld} withheld</li>
            <li>{metrics.calls} Gemini calls · model cost {metrics.costUsd ? `$${metrics.costUsd}` : "n/a"}</li>
          </ul>
          {m.catsight_review_cost_usd && (
            <p>≈ {usd(m.catsight_review_cost_usd[0])}–{usd(m.catsight_review_cost_usd[1])} of review time</p>
          )}
          <p className="src">Timing, calls and cost measured live; review hours from BUSINESS_IMPACT 2.1.</p>
        </div>
      </div>
      {b.real_world && <p className="note">{b.real_world.not_like_for_like}</p>}
      <p className="note">
        The manual column is a hypothesis until benchmark B1 — a person timing the manual process
        on the same data — replaces it.
      </p>
    </section>
  );
}
