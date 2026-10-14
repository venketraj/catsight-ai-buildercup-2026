/**
 * The Analysis screen's frame (Phase 5): the five-step story, the sticky
 * summary bar, the trust strip and loading placeholders. Every figure shown
 * is one the API served; nothing here computes money.
 */

import { formatUsd } from "./api";
import type { Impact } from "./types";

export type StepId = "event" | "hit" | "cost" | "clauses" | "decide";

export interface Step {
  id: StepId;
  label: string;
  hint: string;
  ready: boolean;
}

export function Stepper({ steps, current, onPick }: {
  steps: Step[]; current: StepId; onPick: (id: StepId) => void;
}) {
  return (
    <nav className="stepper" aria-label="Analysis steps (use the left and right arrow keys)">
      <ol>
        {steps.map((s, i) => (
          <li key={s.id}>
            <button
              className={s.id === current ? "step active" : s.ready ? "step ready" : "step"}
              aria-current={s.id === current ? "step" : undefined}
              disabled={!s.ready}
              onClick={() => onPick(s.id)}
              data-tour={`step-${s.id}`}
            >
              <span className="step-no">{i + 1}</span>
              <span className="step-text">
                <span className="step-label">{s.label}</span>
                <span className="step-hint">{s.hint}</span>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function SummaryBar({ impact, verified, withheld, checked, seconds, running, costUsd }: {
  impact: Impact;
  verified: number;
  withheld: number;
  checked: boolean;
  seconds: number;
  running: boolean;
  costUsd?: string | null;
}) {
  const t = impact.totals;
  return (
    <div className="summary-bar" role="status" aria-label="Analysis summary" data-tour="summary">
      <Item label="Event" value={impact.event.name} />
      <Item label="Insurers' claims" value={formatUsd(t.gross)} tone="cedent" />
      <Item label="Reinsurers pay" value={formatUsd(t.ceded)} tone="market" />
      <Item label="Our net (Lion Re)" value={formatUsd(t.our_net)} tone="ours" strong />
      <Item label="Contracts hit" value={`${t.treaties_matched} of ${t.treaties_matched + t.treaties_excluded}`} />
      <Item
        label="Clause flags"
        value={checked ? `${verified} verified · ${withheld} withheld` : running ? "checking…" : "-"}
      />
      <Item label="Time" value={running ? `${seconds}s…` : `${seconds}s`} />
      {costUsd ? <Item label="Model cost" value={`$${costUsd}`} /> : null}
      {impact.methodology?.version ? <Item label="Method" value={impact.methodology.version} /> : null}
    </div>
  );
}

function Item({ label, value, tone, strong }: { label: string; value: string; tone?: string; strong?: boolean }) {
  return (
    <div className={`sb-item ${strong ? "strong" : ""}`}>
      <span className="sb-label">
        {tone && <i className={`sb-dot ${tone}`} aria-hidden />}
        {label}
      </span>
      <span className="sb-value">{value}</span>
    </div>
  );
}

/** Why the findings can be trusted, stated next to them (UI-13). */
export function TrustStrip({ verified, withheld, checked, running, agents, method }: {
  verified: number;
  withheld: number;
  checked: boolean;
  running: boolean;
  agents: boolean | null;
  method: string | null;
}) {
  return (
    <div className="trust-strip" data-tour="trust">
      <span className="ok">
        ✓ {checked ? `${verified} clause citation${verified === 1 ? "" : "s"} verified against the wording`
          : running ? "citations being verified…" : agents === false ? "numbers-only run - no clause claims made" : "no clause claims yet"}
      </span>
      {checked && withheld > 0 && <span>⚠ {withheld} withheld - failed verification, never shown as findings</span>}
      <span>∑ every figure from the deterministic loss engine</span>
      {method && <span>method {method}</span>}
    </div>
  );
}

export function SkeletonPanel({ title }: { title: string }) {
  return (
    <section className="panel" aria-busy="true">
      <h2>{title}</h2>
      <div className="skeleton" style={{ width: "62%" }} />
      <div className="skeleton" style={{ width: "88%" }} />
      <div className="skeleton" style={{ width: "45%" }} />
      <span className="visually-hidden">Loading</span>
    </section>
  );
}
