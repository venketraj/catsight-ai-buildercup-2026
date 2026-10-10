/**
 * The demo-path components (UI-1..8, UI-13).
 *
 * One file because there are eight small components and splitting them across
 * eight files would add navigation for no clarity. They split when one grows
 * past a screenful.
 */

import { formatUsd as formatMoney } from "./api";
import type { EventFact, Impact, TreatyOutcome } from "./types";

/** UI-10 / FR-JUDGE-4. Definitions from DOMAIN_PRIMER. */
const GLOSSARY: Record<string, string> = {
  cedent: "The insurer buying reinsurance. It cedes part of its risk to reinsurers.",
  layer:
    "One slice of a Cat XL programme, written as 'limit xs retention' - 20 xs 10 pays up to 20 once the loss passes 10.",
  retention:
    "The attachment point: the loss the cedent keeps before this layer pays anything.",
  limit: "The maximum this layer pays for one loss occurrence. Not the top of the layer.",
  burn: "How much of a layer's limit has been used. Above 100% means reinstatements were drawn on.",
  reinstatement:
    "Restoring a layer's limit after a loss, usually for an additional premium.",
  "hours clause":
    "Defines the window within which individual losses count as one loss occurrence - typically 72 hours for windstorm.",
  "as-if":
    "A historical event applied to the portfolio in force today, rather than the one in force when it happened. Standard practice.",
  "loss occurrence":
    "The unit a treaty pays on: all losses from one event inside the hours-clause window.",
  "quota share": "A proportional treaty: the reinsurer takes a fixed percentage of every loss.",
};

export function Term({ children }: { children: string }) {
  const definition = GLOSSARY[children.toLowerCase()];
  if (!definition) return <>{children}</>;
  return (
    <abbr title={definition} tabIndex={0}>
      {children}
    </abbr>
  );
}

/* -------------------------------------------------------------- UI-2/UI-3 -- */

export function EventPanel({ impact }: { impact: Impact }) {
  const { event, totals, as_if } = impact;
  return (
    <section className="panel">
      <h2>Event</h2>
      <div className="figures">
        <div className="figure">
          <div className="label">Event</div>
          <div className="value" style={{ fontSize: 19 }}>
            {event.name}
          </div>
        </div>
        <div className="figure">
          <div className="label">Peril</div>
          <div className="value" style={{ fontSize: 19 }}>
            {event.peril}
          </div>
        </div>
        <div className="figure">
          <div className="label">Damaging window</div>
          <div className="value" style={{ fontSize: 19 }}>
            {event.peril === "EQ" ? "single shock" : `${event.duration_h ?? "-"} h`}
          </div>
        </div>
        <div className="figure">
          <div className="label">Regions affected</div>
          <div className="value" style={{ fontSize: 19 }}>
            {event.regions}
          </div>
        </div>
      </div>

      <p className="note">
        {totals.treaties_matched} treaties responded, {totals.treaties_excluded}{" "}
        excluded.{" "}
        {as_if ? (
          <>
            <span className="pill asif">as-if</span> A historical event priced
            against the portfolio in force <strong>today</strong> — the{" "}
            <Term>as-if</Term> basis, which is what a reinsurer actually asks.
            The treaty period test is deliberately not applied.
          </>
        ) : (
          <>Priced on the portfolio in force at the time of the event.</>
        )}
      </p>

      {event.facts?.length ? <Facts facts={event.facts} /> : null}
      {event.disclaimer ? <p className="note">{event.disclaimer}</p> : null}
    </section>
  );
}

function Facts({ facts }: { facts: EventFact[] }) {
  return (
    <ul className="note" style={{ paddingLeft: 18, marginTop: 12 }}>
      {facts.map((fact, index) => (
        <li key={index} style={{ marginBottom: 4 }}>
          {fact.text}{" "}
          {fact.url ? (
            <a href={fact.url} target="_blank" rel="noreferrer noopener">
              {fact.source}
            </a>
          ) : (
            <span style={{ color: "var(--ink-faint)" }}>{fact.source}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

/* -------------------------------------------------------------- the money -- */

/**
 * UI-7. The three-party view.
 *
 * The point of the product in one panel: a portfolio-level total tells you
 * nothing about whether your interest sits with the cedent or with the rest of
 * the market. Three numbers, side by side, do.
 */
export function MoneyMoment({ hero }: { hero: TreatyOutcome }) {
  return (
    <section className="panel">
      <h2>Where each party stands &middot; {hero.treaty_id}</h2>
      <div className="figures">
        <div className="figure">
          <div className="label">Cedent net cost</div>
          <div className="value cedent">{formatMoney(hero.cedent_net_cost)}</div>
          <div className="label" style={{ textTransform: "none" }}>
            {formatMoney(hero.cedent_retention)} retained +{" "}
            {formatMoney(hero.total_rip)} reinstatement premium
          </div>
        </div>
        <div className="figure">
          <div className="label">Market net</div>
          <div className="value market">{formatMoney(hero.market_net)}</div>
          <div className="label" style={{ textTransform: "none" }}>
            all reinsurers, net of RIP
          </div>
        </div>
        <div className="figure">
          <div className="label">Our net (Lion Re)</div>
          <div className="value ours">{formatMoney(hero.our_net)}</div>
          <div className="label" style={{ textTransform: "none" }}>
            {formatMoney(hero.our_loss)} recovered &minus; {formatMoney(hero.our_rip)}{" "}
            <Term>reinstatement</Term> premium
          </div>
        </div>
      </div>
      <p className="note">
        Our share differs by <Term>layer</Term>, so our position is not the
        market&rsquo;s in miniature. A portfolio-level total cannot show this —
        it is why the per-layer view below matters more than the headline.
      </p>
    </section>
  );
}

/* ------------------------------------------------------------------ UI-5 -- */

export function TreatyTable({
  impact,
  heroId,
  onExplain,
}: {
  impact: Impact;
  heroId: string;
  onExplain?: (treatyId: string) => void;
}) {
  return (
    <section className="panel" data-tour="treaties">
      <h2>Treaties that responded</h2>
      <table>
        <caption className="note" style={{ captionSide: "bottom", textAlign: "left" }}>
          Ordered by our net exposure - the first question is where we are most
          on the hook. Gross is the insurer's claims; ceded is what all
          reinsurers pay; our net is Lion Re's share.
        </caption>
        <thead>
          <tr>
            <th>Treaty</th>
            <th>
              <Term>cedent</Term>
            </th>
            <th>Type</th>
            <th className="num">Gross</th>
            <th className="num">Ceded</th>
            <th className="num">Our net</th>
            <th className="num">Regions</th>
            {onExplain && <th aria-label="Explanation" />}
          </tr>
        </thead>
        <tbody>
          {impact.treaties.map((row) => (
            <tr key={row.treaty_id} className={row.treaty_id === heroId ? "hero" : undefined}>
              <td>{row.treaty_id}</td>
              <td>{row.cedent}</td>
              <td>
                <span className="pill">{row.type}</span>
              </td>
              <td className="num">{formatMoney(row.gross)}</td>
              <td className="num">{formatMoney(row.ceded)}</td>
              <td className="num">{formatMoney(row.our_net)}</td>
              <td className="num">{row.regions.length}</td>
              {onExplain && (
                <td>
                  <button className="cite" onClick={() => onExplain(row.treaty_id)}>
                    How?
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/* ------------------------------------------------------------------ UI-6 -- */

/** Excluded treaties, each with the reason. "It was not in the list" is not
 * an answer to "why did this programme not respond". */
export function ExcludedPanel({ impact }: { impact: Impact }) {
  if (!impact.excluded.length) return null;
  return (
    <section className="panel">
      <h2>Did not respond &middot; {impact.excluded.length}</h2>
      <table>
        <thead>
          <tr>
            <th>Treaty</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {impact.excluded.map((row) => (
            <tr key={row.treaty_id}>
              <td>{row.treaty_id}</td>
              <td style={{ color: "var(--ink-dim)" }}>{row.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
