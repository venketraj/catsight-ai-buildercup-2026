/**
 * The agent-facing screens: the live timeline (UI-2), wording flags with
 * verified citations (UI-6), the report (UI-7), the clause viewer, and the
 * knowledge base. Everything here renders frames and API data as received -
 * no figure is computed in the browser.
 */

import { useEffect, useMemo, useState } from "react";

import { fetchClauses, fetchKnowledgeBase, unlessAborted } from "./api";
import type {
  Citation,
  Clause,
  KnowledgeBase,
  RetrievalHit,
  WordingFlag,
  Withheld,
} from "./types";

// ------------------------------------------------------------- timeline -- //

export const AGENTS: { id: string; label: string; what: string }[] = [
  { id: "event_intel", label: "Event intel", what: "Loads the event record" },
  { id: "exposure_analyst", label: "Exposure analyst", what: "Matches treaties, runs the loss engine" },
  { id: "wording_checker", label: "Wording checker", what: "Firestore vector search + Gemini reads clauses" },
  { id: "verifier", label: "Verifier", what: "Quote check + Gemini 3.8 support check" },
  { id: "reporter", label: "Reporter", what: "Writes the report from verified facts" },
];

export interface ToolLine {
  agent: string;
  name: string;
  summary: string;
}

export interface Retrieval {
  treaty_id: string;
  query: string;
  hits: RetrievalHit[];
}

export function AgentTimeline({
  status,
  tools,
  retrievals,
  warnings,
  verificationHeader,
}: {
  status: Record<string, "running" | "done">;
  tools: ToolLine[];
  retrievals: Retrieval[];
  warnings: string[];
  verificationHeader: string | null;
}) {
  const byTreaty = useMemo(() => {
    const groups: Record<string, Retrieval[]> = {};
    for (const r of retrievals) (groups[r.treaty_id] ??= []).push(r);
    return groups;
  }, [retrievals]);

  return (
    <section className="panel timeline" aria-live="polite">
      <h2>Agent timeline</h2>
      <ol className="agents">
        {AGENTS.map((agent) => {
          const state = status[agent.id];
          return (
            <li key={agent.id} className={state ?? "waiting"}>
              <div className="agent-head">
                <span className="dot" aria-hidden />
                <strong>{agent.label}</strong>
                <span className="agent-what">{agent.what}</span>
                <span className="agent-state">
                  {state === "done" ? "done" : state === "running" ? "running…" : "waiting"}
                </span>
              </div>
              {tools
                .filter((t) => t.agent === agent.id)
                .map((t, i) => (
                  <div key={i} className="tool-line">
                    <code>{t.name}</code> {t.summary}
                  </div>
                ))}
              {agent.id === "wording_checker" &&
                Object.entries(byTreaty).map(([treaty, rows]) => (
                  <details key={treaty} className="retrieval">
                    <summary>
                      {treaty} · {rows.length} vector searches
                    </summary>
                    {rows.map((r) => (
                      <div key={r.query} className="retrieval-row">
                        <span className="query">{r.query}</span>
                        {r.hits.map((h) => (
                          <span key={h.chunk_id} className="hit" title={h.title ?? ""}>
                            cl.{h.clause_no ?? "-"} p.{h.page}{" "}
                            <span className="score">{h.score.toFixed(2)}</span>
                          </span>
                        ))}
                      </div>
                    ))}
                  </details>
                ))}
              {agent.id === "verifier" && verificationHeader && (
                <div className="tool-line">{verificationHeader}</div>
              )}
            </li>
          );
        })}
      </ol>
      {warnings.length > 0 && (
        <details className="warnings">
          <summary>{warnings.length} note(s) from the agents</summary>
          <ul>
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- flags -- //

export interface VerifiedFlag {
  flag: WordingFlag;
  badge: string;
}

export function FlagsPanel({
  verified,
  withheld,
  header,
  running,
  onOpen,
}: {
  verified: VerifiedFlag[];
  withheld: Withheld[];
  header: string | null;
  running: boolean;
  onOpen: (flag: WordingFlag) => void;
}) {
  const order = { HIGH: 0, MEDIUM: 1, LOW: 2 } as const;
  const sorted = [...verified].sort(
    (a, b) => order[a.flag.severity] - order[b.flag.severity],
  );
  return (
    <section className="panel" data-tour="flags">
      <h2>Wording that could change the answer</h2>
      {header && <p className="verify-header">✓ {header}</p>}
      {!header && running && <p className="note">The wording checker is reading the clauses…</p>}
      {header && sorted.length === 0 && (
        <p className="note">No clause in the matched wordings changes the answer for this event.</p>
      )}
      <ul className="flags">
        {sorted.map(({ flag, badge }) => (
          <li key={`${flag.treaty_id}-${flag.issue_type}-${flag.citation.clause_no}`}
              className={`flag sev-${flag.severity.toLowerCase()}`}>
            <div className="flag-head">
              <span className={`sev sev-${flag.severity.toLowerCase()}`}>{flag.severity}</span>
              <strong>{flag.treaty_id}</strong>
              <span className="issue">{flag.issue_type}</span>
            </div>
            <p>{flag.explanation}</p>
            <blockquote>“{flag.citation.quote}”</blockquote>
            <button className="cite" onClick={() => onOpen(flag)}>
              {badge.replace(/^verified/, "✓ verified")} — open clause
            </button>
          </li>
        ))}
      </ul>
      {withheld.length > 0 && (
        <details className="withheld">
          <summary>{withheld.length} flag(s) withheld — failed verification</summary>
          <ul>
            {withheld.map((w, i) => (
              <li key={i}>
                <strong>{w.treaty_id}</strong> {w.issue_type}: {w.reason ?? "no reason recorded"}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

// -------------------------------------------------------- clause viewer -- //

export function ClauseViewer({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const [clauses, setClauses] = useState<Clause[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchClauses(citation.treaty_id, controller.signal)
      .then((body) => setClauses(body.clauses))
      .catch(unlessAborted(setError));
    return () => controller.abort();
  }, [citation.treaty_id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const clause = clauses?.find(
    (c) => c.clause_no === citation.clause_no && c.pages.includes(citation.page),
  );

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>
            {citation.treaty_id} · page {citation.page} · clause {citation.clause_no}
            {clause?.title ? ` — ${clause.title}` : ""}
          </strong>
          <span className="spacer" />
          <button onClick={onClose} aria-label="Close">✕</button>
        </div>
        {clause?.source === "transcription" && (
          <p className="note">Transcribed from a scanned page with no text layer.</p>
        )}
        {error && <p className="banner error">{error}</p>}
        {!clauses && !error && <p className="note">Loading the stored clause from Firestore…</p>}
        {clauses && !clause && <p className="note">That clause is not in the stored corpus.</p>}
        {clause && <Highlighted text={clause.text} quote={citation.quote} />}
        <p className="note">
          Source: Firestore <code>treaty_chunks/{clause?.chunk_id ?? "…"}</code>. The highlighted
          words are the quote the verifier matched.
        </p>
      </div>
    </div>
  );
}

/** Highlight the quote in the clause, tolerant of whitespace differences. */
function Highlighted({ text, quote }: { text: string; quote: string }) {
  const pattern = quote
    .trim()
    .split(/\s+/)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("\\s+");
  const match = pattern ? new RegExp(pattern, "i").exec(text) : null;
  if (!match) return <pre className="clause">{text}</pre>;
  return (
    <pre className="clause">
      {text.slice(0, match.index)}
      <mark>{match[0]}</mark>
      {text.slice(match.index + match[0].length)}
    </pre>
  );
}

// --------------------------------------------------------------- report -- //

export function ReportPanel({
  markdown,
  unsupported,
  calls,
  onDownload,
  wordUrl,
}: {
  markdown: string;
  unsupported: string[];
  calls: Record<string, number>;
  onDownload?: () => void;
  wordUrl?: string | null;
}) {
  const total = Object.values(calls).reduce((a, b) => a + b, 0);
  return (
    <section className="panel report" data-tour="report">
      <div className="modal-head">
        <h2 style={{ margin: 0 }}>Analyst report</h2>
        <span className="spacer" />
        {onDownload && (
          <button className="secondary" onClick={onDownload}>
            Download report (.md)
          </button>
        )}
        {wordUrl && (
          <a className="button-link primary" href={wordUrl} download>
            Download Word (.docx)
          </a>
        )}
      </div>
      <article className="paper">
        <p className="paper-kicker">Lion Re · catastrophe desk · first view</p>
        {unsupported.length === 0 ? (
          <p className="paper-check">✓ Every figure in this report matches the loss engine.</p>
        ) : (
          <p className="paper-check bad">
            Figures not found in the engine output: {unsupported.join(", ")}
          </p>
        )}
        <Markdown text={markdown} />
        <p className="paper-foot">
          Indicative first view on synthetic data. Not a catastrophe-model output. Not underwriting
          or claims advice.
        </p>
      </article>
      <p className="note">
        Written by Gemini from verified facts · {total} model calls (
        {Object.entries(calls)
          .map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`)
          .join(", ")}
        )
      </p>
    </section>
  );
}

/** A deliberately small Markdown renderer: headings, bullets, bold. */
export function Markdown({ text }: { text: string }) {
  const blocks: JSX.Element[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      blocks.push(
        <ul key={blocks.length}>
          {list.map((item, i) => (
            <li key={i}>{inline(item)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const bullet = /^\s*[*-]\s+(.*)$/.exec(line);
    if (bullet) {
      list.push(bullet[1] ?? "");
      continue;
    }
    flush();
    if (line.startsWith("## ")) blocks.push(<h3 key={blocks.length}>{line.slice(3)}</h3>);
    else if (line.startsWith("# ")) blocks.push(<h3 key={blocks.length}>{line.slice(2)}</h3>);
    else if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line)}</p>);
  }
  flush();
  return <div className="md">{blocks}</div>;
}

function inline(text: string): (string | JSX.Element)[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part,
  );
}

// ------------------------------------------------------- knowledge base -- //

export function KnowledgeBasePage() {
  const [kb, setKb] = useState<KnowledgeBase | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetchKnowledgeBase(controller.signal)
      .then(setKb)
      .catch(unlessAborted(setError));
    return () => controller.abort();
  }, []);

  if (error) return <p className="banner error">{error}</p>;
  if (!kb) return <p className="note">Loading ingestion records…</p>;
  const t = kb.totals;
  const first = kb.wordings[0];
  return (
    <>
      <section className="panel">
        <h2>Knowledge base</h2>
        <p className="note" style={{ marginTop: 0 }}>
          Treaty wordings were ingested ahead of time — as a reinsurer would when contracts
          arrive — and each analysis searches this corpus live. Every row below is read from
          Firestore <code>ingestions</code>, recorded at ingest time.
        </p>
        <div className="figures">
          <Figure label="Wordings" value={String(t.wordings)} />
          <Figure label="Clauses embedded" value={String(t.clauses)} />
          <Figure label="Citations verified" value={`${t.citations_verified}/${t.citations_total}`} />
          <Figure label="Governing clause retrieved" value={`${t.retrieval_hits}/${t.retrieval_total}`} />
        </div>
        {first && (
          <p className="note">
            {first.embed_model} · {first.embed_dim} dims · {first.vector_store} · extraction by{" "}
            {first.extraction_model}
          </p>
        )}
      </section>
      <section className="panel">
        <table>
          <thead>
            <tr>
              <th>Treaty</th>
              <th>PDF (Cloud Storage)</th>
              <th className="num">Clauses</th>
              <th>Scanned pages</th>
              <th className="num">Citations</th>
              <th className="num">Retrieval</th>
              <th>Valid</th>
              <th>Ingested</th>
            </tr>
          </thead>
          <tbody>
            {kb.wordings.map((w) => (
              <tr key={w.treaty_id}>
                <td>{w.treaty_id}</td>
                <td><code>{w.pdf.replace(/^gs:\/\/[^/]+\//, "")}</code></td>
                <td className="num">{w.clauses}</td>
                <td>{w.transcribed_pages.length ? `p.${w.transcribed_pages.join(", ")} transcribed` : "—"}</td>
                <td className="num">{w.citations_verified}/{w.citations_total}</td>
                <td className="num">{w.retrieval_hits}/{w.retrieval_total}</td>
                <td>{w.structurally_valid ? "✓" : "✕"}</td>
                <td>{w.ingested_at.replace("T", " ").slice(0, 16)} UTC</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="figure">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}

export function ComingSoon({ title, phase, items }: { title: string; phase: string; items: string[] }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      <p className="note" style={{ marginTop: 0 }}>Planned for {phase}:</p>
      <ul className="note">
        {items.map((i) => (
          <li key={i}>{i}</li>
        ))}
      </ul>
    </section>
  );
}
