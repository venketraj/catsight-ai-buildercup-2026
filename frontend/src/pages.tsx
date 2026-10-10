/**
 * The Treaties and Methodology screens (Phase 3b). Read-only views of what is
 * stored in Firestore: the treaty book, each wording reconciled against it,
 * and the method version every figure is computed under.
 */

import { useEffect, useMemo, useState } from "react";

import { ClauseViewer } from "./agents";
import { fetchMethodology, fetchTreaties, fetchTreaty, formatUsd, unlessAborted } from "./api";
import type { Citation, Methodology, TreatyDetail, TreatySummary } from "./types";

// --------------------------------------------------------------- treaties -- //

const COUNTRY = { JPN: "Japan", PHL: "Philippines", TWN: "Taiwan" } as Record<string, string>;
const PERIL = { WS: "Windstorm", EQ: "Earthquake", FL: "Flood" } as Record<string, string>;

const RESULT_LABEL: Record<string, string> = {
  match: "✓ matches the book",
  differs: "≠ differs from the book",
  unverified: "? no verified citation",
  book_only: "book only",
  wording_only: "wording only",
};

export function TreatiesPage() {
  const [treaties, setTreaties] = useState<TreatySummary[] | null>(null);
  const [country, setCountry] = useState("all");
  const [peril, setPeril] = useState("all");
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchTreaties(controller.signal)
      .then((b) => setTreaties(b.treaties))
      .catch(unlessAborted(setError));
    return () => controller.abort();
  }, []);

  const shown = useMemo(
    () =>
      (treaties ?? []).filter(
        (t) =>
          (country === "all" || t.territory.include.includes(country)) &&
          (peril === "all" || t.perils.includes(peril)),
      ),
    [treaties, country, peril],
  );

  if (error) return <p className="banner error">{error}</p>;
  if (!treaties) return <p className="note">Loading the treaty book…</p>;

  return (
    <>
      <section className="panel">
        <h2>Treaty book · {treaties.length} treaties</h2>
        <p className="note" style={{ marginTop: 0 }}>
          The record the loss engine prices from (Firestore <code>treaties</code>). Eight have a
          contract wording that Gemini read and that is reconciled against this book, field by
          field.
        </p>
        <div className="controls">
          <label>
            Country{" "}
            <select value={country} onChange={(e) => setCountry(e.target.value)}>
              <option value="all">All</option>
              {Object.entries(COUNTRY).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </label>
          <label>
            Peril{" "}
            <select value={peril} onChange={(e) => setPeril(e.target.value)}>
              <option value="all">All</option>
              {Object.entries(PERIL).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </label>
          <span className="note" style={{ margin: 0 }}>{shown.length} shown</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>Treaty</th>
              <th>Insurer (cedent)</th>
              <th>Type</th>
              <th>Covers</th>
              <th>Territory</th>
              <th>Period</th>
              <th>Wording</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((t) => (
              <tr key={t.treaty_id} className={t.treaty_id === selected ? "hero" : undefined}>
                <td>{t.treaty_id}</td>
                <td>{t.cedent}</td>
                <td><span className="pill">{t.type === "CAT_XL" ? `Cat XL · ${t.layers} layers` : "Quota share"}</span></td>
                <td>{t.perils.map((p) => PERIL[p] ?? p).join(", ")}</td>
                <td>{t.territory.include.map((c) => COUNTRY[c] ?? c).join(", ")}</td>
                <td>{t.inception} → {t.expiry}</td>
                <td>{t.has_wording ? `✓ ${t.wording_id}` : "—"}</td>
                <td><button className="cite" onClick={() => setSelected(t.treaty_id)}>Open</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {selected && <TreatyPanel treatyId={selected} onClose={() => setSelected(null)} />}
    </>
  );
}

function TreatyPanel({ treatyId, onClose }: { treatyId: string; onClose: () => void }) {
  const [t, setT] = useState<TreatyDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState<Citation | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setT(null);
    fetchTreaty(treatyId, controller.signal).then(setT).catch(unlessAborted(setError));
    return () => controller.abort();
  }, [treatyId]);

  if (error) return <p className="banner error">{error}</p>;
  if (!t) return <section className="panel"><p className="note">Loading {treatyId}…</p></section>;

  const recon = t.reconciliation;
  return (
    <section className="panel treaty-detail">
      <div className="modal-head">
        <h2 style={{ margin: 0 }}>{t.treaty_id} · {t.cedent}</h2>
        <span className="spacer" />
        <button className="cite" onClick={onClose}>Close</button>
      </div>

      <div className="figures">
        <Fig label="Type" value={t.type === "CAT_XL" ? "Catastrophe excess of loss" : "Quota share"} />
        <Fig label="Covers" value={t.perils.map((p) => PERIL[p] ?? p).join(", ")} />
        <Fig label="Territory" value={t.territory.include.map((c) => COUNTRY[c] ?? c).join(", ") +
          (t.territory.exclude.length ? ` (excl. ${t.territory.exclude.join(", ")})` : "")} />
        <Fig label="Period" value={`${t.inception} → ${t.expiry}`} />
      </div>

      <div className="grid">
        <div>
          <h3>{t.type === "CAT_XL" ? "Layers" : "Cession"}</h3>
          {t.type === "CAT_XL" ? (
            <table>
              <thead>
                <tr>
                  <th>Layer</th>
                  <th>Covers losses</th>
                  <th className="num">Premium</th>
                  <th className="num">Our share</th>
                  <th>Reinstatements</th>
                </tr>
              </thead>
              <tbody>
                {t.layers.map((l) => (
                  <tr key={l.layer_no}>
                    <td>L{l.layer_no}</td>
                    <td>{formatUsd(l.limit)} xs {formatUsd(l.retention)}</td>
                    <td className="num">{formatUsd(l.premium)}</td>
                    <td className="num">{Math.round(l.our_share * 100)}%</td>
                    <td>{l.reinstatements.count ?? 0} × {l.reinstatements.basis ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p>
              Reinsurers take {Math.round((t.qs?.cession_pct ?? 0) * 100)}% of every loss
              {t.qs?.event_limit ? `, up to ${formatUsd(t.qs.event_limit)} per event` : ""}. Our share{" "}
              {Math.round((t.qs?.our_share ?? 0) * 100)}%.
            </p>
          )}
        </div>
        <div>
          <h3>Key clauses as booked</h3>
          <ul className="note" style={{ marginTop: 0 }}>
            <li>One event = {Object.entries(t.hours_clause).filter(([, h]) => h).map(([p, h]) => `${h}h ${PERIL[p] ?? p}`).join(", ") || "no hours clause"}</li>
            <li>Excludes: {t.exclusions.length ? t.exclusions.join(", ") : "nothing stated"}</li>
            {t.endorsement && <li>Endorsement on record: {JSON.stringify(t.endorsement)}</li>}
          </ul>
        </div>
      </div>

      <h3>Book vs contract wording</h3>
      {!recon ? (
        <p className="note">No contract wording on file for this treaty - the book is the only source.</p>
      ) : (
        <>
          <p className="note" style={{ marginTop: 0 }}>
            Wording {t.wording_id}, read by Gemini, each value checked against its page.{" "}
            {Object.entries(recon.counts).map(([k, v]) => `${v} ${RESULT_LABEL[k] ?? k}`).join(" · ")}
          </p>
          <table className="recon">
            <thead>
              <tr>
                <th>Term</th>
                <th>Book</th>
                <th>Wording says</th>
                <th>Result</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {recon.fields.map((row) => (
                <tr key={row.field} className={`r-${row.result}`}>
                  <td><code>{row.field}</code></td>
                  <td>{show(row.booked)}</td>
                  <td>{show(row.wording)}</td>
                  <td>{RESULT_LABEL[row.result] ?? row.result}</td>
                  <td>
                    {row.citation?.page && row.citation.quote ? (
                      <button
                        className="cite"
                        title={row.citation.quote}
                        onClick={() => setOpened({
                          treaty_id: t.treaty_id, page: row.citation!.page!,
                          clause_no: row.citation!.clause_no ?? "", quote: row.citation!.quote!,
                          source: row.citation!.status === "transcribed" ? "transcription" : "text",
                        })}
                      >
                        {row.citation.status === "transcribed" ? "🖼" : "✓"} p.{row.citation.page} cl.{row.citation.clause_no}
                      </button>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {opened && <ClauseViewer citation={opened} onClose={() => setOpened(null)} />}
    </section>
  );
}

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "(none)";
  return String(value);
}

function Fig({ label, value }: { label: string; value: string }) {
  return (
    <div className="figure">
      <div className="label">{label}</div>
      <div className="value" style={{ fontSize: 16 }}>{value}</div>
    </div>
  );
}

// ------------------------------------------------------------ methodology -- //

export function MethodologyPage() {
  const [m, setM] = useState<Methodology | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetchMethodology(controller.signal).then(setM).catch(unlessAborted(setError));
    return () => controller.abort();
  }, []);

  if (error) return <p className="banner error">{error}</p>;
  if (!m) return <p className="note">Loading the method…</p>;
  const v = m.vulnerability;
  return (
    <>
      <section className="panel">
        <h2>Methodology · version {m.version}</h2>
        <p className="note" style={{ marginTop: 0 }}>
          Every analysis is stamped with the method version it ran under. A change in market
          practice becomes a new approved version with a later effective date - never an edit to
          this one - so any past figure can be traced to the rules in force when it was produced.
        </p>
        <div className="figures">
          <Fig label="Version" value={m.version} />
          <Fig label="Effective from" value={m.effective_from} />
          <Fig label="Status" value={m.status} />
          <Fig label="Approved by" value={m.approved_by} />
        </div>
      </section>

      <section className="panel">
        <h2>Conventions the loss engine applies</h2>
        <table>
          <tbody>
            {Object.entries(m.conventions).map(([key, c]) => (
              <tr key={key}>
                <td style={{ whiteSpace: "nowrap" }}><strong>{key.replace(/_/g, " ")}</strong></td>
                <td>{c.rule}<div className="src">Source: {c.source}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h2>Damage curves</h2>
        <div className="grid">
          <div>
            <h3>Wind - {v.wind.function.replace("_", " (")})</h3>
            <p className="note" style={{ marginTop: 0 }}>
              Damage starts above {v.wind.v_threshold_ms} m/s and reaches 50% at the v½ speed
              below. Eberenz et al. (2021) country values, CC BY 4.0.
            </p>
            <table>
              <thead><tr><th>Country</th><th className="num">v½ (m/s)</th><th className="num">Calibration</th></tr></thead>
              <tbody>
                {Object.entries(v.wind.v_half_ms).map(([c, val]) => (
                  <tr key={c}>
                    <td>{COUNTRY[c] ?? c}</td>
                    <td className="num">{val}</td>
                    <td className="num">{v.wind.calibration_factor[c] ?? 1}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <h3>Earthquake - MMI table</h3>
            <p className="note" style={{ marginTop: 0 }}>
              Illustrative, informed by Hazus repair ratios - labelled illustrative wherever shown.
            </p>
            <table>
              <thead><tr><th>MMI</th><th className="num">Mean damage</th></tr></thead>
              <tbody>
                {Object.entries(v.earthquake.mmi_damage_ratio).map(([mmi, ratio]) => (
                  <tr key={mmi}>
                    <td>{mmi}</td>
                    <td className="num">{(ratio * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>Changelog</h2>
        <ul>
          {m.changelog.map((c) => (
            <li key={c.version}><strong>{c.version}</strong> ({c.date}) - {c.change}</li>
          ))}
        </ul>
        <p className="note">
          What stays out of this file: treaty terms (they come from the treaty book and the
          wordings) and any arithmetic by a language model - the engine is deterministic Python.
        </p>
      </section>
    </>
  );
}
