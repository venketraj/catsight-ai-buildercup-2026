/**
 * UI-4 - the layer waterfall.
 *
 * For any responding treaty: the gross loss split into what the insurer keeps
 * and what each layer pays, then each layer's burn against its limit. Every
 * width is an engine figure divided by the treaty's gross - no money is
 * computed here. Exhaustion is marked by a hatch and a label, never by colour
 * alone, and the table underneath is the accessible alternative (UI-12).
 */

import { useState } from "react";

import { formatMoney, formatPercent } from "./api";
import { Term } from "./components";
import type { TreatyOutcome } from "./types";

/** Layer fills: one indigo ramp per theme (styles.css --layer-1..4), with
 * label text that reaches 4.5:1 on every step. */
const LAYER_FILL = [1, 2, 3, 4].map((n) => `var(--layer-${n})`);

export default function LayerChart({ treaties, initial }: { treaties: TreatyOutcome[]; initial: string }) {
  const [chosen, setChosen] = useState(initial);
  const hero = treaties.find((t) => t.treaty_id === chosen) ?? treaties[0];
  const layers = hero?.layers ?? [];
  const gross = Number(hero?.gross ?? 0);

  return (
    <section className="panel waterfall" data-tour="waterfall">
      <div className="panel-head">
        <h2>How the loss is split &middot; {hero?.treaty_id}</h2>
        <label className="picker">
          Treaty{" "}
          <select value={hero?.treaty_id} onChange={(e) => setChosen(e.target.value)}>
            {treaties.map((t) => (
              <option key={t.treaty_id} value={t.treaty_id}>
                {t.treaty_id} · {t.cedent} · {t.type === "QS" ? "quota share" : "Cat XL"}
              </option>
            ))}
          </select>
        </label>
      </div>

      {!hero || !layers.length || gross <= 0 ? (
        <p className="note">
          {hero?.treaty_id} is a <Term>quota share</Term>, so it has no layers - it cedes a fixed
          percentage of the loss: {formatMoney(hero?.ceded ?? "0")} of {formatMoney(hero?.gross ?? "0")}
          {hero?.capped ? " (capped by the treaty's event limit)" : ""}.
        </p>
      ) : (
        <>
          <p className="note" style={{ marginTop: 0 }}>
            {hero.cedent}'s {formatMoney(hero.gross)} of claims, from the first dollar to the last:
          </p>
          <div className="split-bar" role="img"
               aria-label={`Insurer keeps ${formatMoney(hero.cedent_retention ?? "0")}; ` +
                 layers.map((l) => `layer ${l.layer_no} pays ${formatMoney(l.ceded)}`).join("; ")}>
            <Segment value={Number(hero.cedent_retention ?? 0)} total={gross}
                     className="seg-cedent" label="Insurer keeps" amount={hero.cedent_retention ?? "0"} />
            {layers.map((l, i) => (
              <Segment key={l.layer_no} value={Number(l.ceded)} total={gross}
                       className={l.exhausted ? "seg-layer exhausted" : "seg-layer"}
                       fill={LAYER_FILL[Math.min(i, LAYER_FILL.length - 1)]}
                       label={`L${l.layer_no}`} amount={l.ceded} />
            ))}
          </div>
          <div className="split-legend">
            <span><i className="swatch" style={{ background: "var(--cedent)" }} /> insurer keeps (retention)</span>
            <span><i className="swatch" style={{ background: LAYER_FILL[1] }} /> layers - all reinsurers pay</span>
            <span><i className="swatch hatch" /> exhausted</span>
          </div>

          <h3 className="sub">Burn per layer</h3>
          <ul className="burn-list">
            {layers.map((l) => {
              const burn = Number(l.burn);
              return (
                <li key={l.layer_no}>
                  <span className="burn-name">L{l.layer_no}</span>
                  <span className="burn-track" aria-hidden>
                    <span className={l.exhausted ? "burn-fill exhausted" : "burn-fill"}
                          style={{ width: `${Math.min(burn, 1) * 100}%` }} />
                    <span className="burn-limit" />
                  </span>
                  <span className="burn-value">
                    {formatPercent(l.burn)}
                    {l.exhausted ? " · exhausted" : burn > 0 ? "" : " · untouched"}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}

      {layers.length > 0 && (
        <table style={{ marginTop: 14 }}>
          <caption className="note" style={{ captionSide: "bottom", textAlign: "left" }}>
            USD millions. <Term>burn</Term> is the share of the layer's limit used; above 100% means a
            reinstatement was drawn. Our loss and RIP are Lion Re's share.
          </caption>
          <thead>
            <tr>
              <th>Layer</th>
              <th className="num">Ceded</th>
              <th className="num">Burn</th>
              <th className="num">Our loss</th>
              <th className="num">Our RIP</th>
              <th>State</th>
            </tr>
          </thead>
          <tbody>
            {layers.map((layer) => (
              <tr key={layer.layer_no}>
                <td>L{layer.layer_no}</td>
                <td className="num">{formatMoney(layer.ceded)}</td>
                <td className="num">{formatPercent(layer.burn)}</td>
                <td className="num">{formatMoney(layer.our_loss)}</td>
                <td className="num">{formatMoney(layer.our_rip)}</td>
                <td>
                  {layer.exhausted ? (
                    <span className="pill exhausted">exhausted</span>
                  ) : Number(layer.ceded) > 0 ? (
                    <span className="pill">part-burnt</span>
                  ) : (
                    <span className="pill">untouched</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Segment({ value, total, className, label, amount, fill }: {
  value: number; total: number; className: string; label: string; amount: string; fill?: string;
}) {
  if (value <= 0) return null;
  const share = value / total;
  return (
    <div className={`seg ${className}`} style={{ flexGrow: share, background: fill }}
         title={`${label}: ${formatMoney(amount)}`}>
      {share > 0.09 && (
        <>
          <span className="seg-label">{label}</span>
          <span className="seg-amount">{formatMoney(amount)}</span>
        </>
      )}
    </div>
  );
}
