/**
 * FR-ASK - follow-up questions about the analysis on screen. The answer is
 * Gemini's, but every figure in it is checked against the engine and every
 * citation against the stored clause; the panel says so for each answer.
 */

import { useState } from "react";

import { ClauseViewer, Markdown } from "./agents";
import { askQuestion } from "./api";
import type { AskResult, Citation } from "./types";

const EXAMPLES = [
  "Which layers are exhausted, and on which treaties?",
  "Show the hours clause for W1.",
  "Why does T-004 matter for this event?",
];

export function AskPanel({ analysisId }: { analysisId: string }) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<AskResult[]>([]);
  const [opened, setOpened] = useState<Citation | null>(null);

  const submit = async (text: string) => {
    const q = text.trim();
    if (q.length < 3 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await askQuestion(analysisId, q);
      setAnswers((current) => [result, ...current]);
      setQuestion("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel ask">
      <h2>Ask a follow-up question</h2>
      <form
        className="ask-form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit(question);
        }}
      >
        <input
          type="text"
          value={question}
          maxLength={300}
          placeholder="e.g. Which layers are exhausted?"
          aria-label="Your question about this analysis"
          onChange={(e) => setQuestion(e.target.value)}
          disabled={busy}
        />
        <button className="primary" type="submit" disabled={busy || question.trim().length < 3}>
          {busy ? "Thinking…" : "Ask"}
        </button>
      </form>
      <div className="ask-examples">
        {EXAMPLES.map((ex) => (
          <button key={ex} className="cite" disabled={busy} onClick={() => void submit(ex)}>
            {ex}
          </button>
        ))}
      </div>
      {error && <p className="banner error">{error}</p>}

      {answers.map((a, i) => (
        <article key={`${a.question}-${i}`} className="ask-answer">
          <div className="ask-q">Q: {a.question}</div>
          <Markdown text={a.answer_md} />
          {a.unsupported_figures.length === 0 ? (
            <p className="verify-header">✓ Every figure in this answer matches the loss engine.</p>
          ) : (
            <p className="banner error">
              Figures not found in the engine output: {a.unsupported_figures.join(", ")} - treat
              this answer with caution.
            </p>
          )}
          {a.citations.length > 0 && (
            <div className="ask-cites">
              {a.citations.map((c, j) => (
                <button key={j} className="cite" title={c.quote} onClick={() => setOpened(c)}>
                  ✓ {c.treaty_id} p.{c.page} cl.{c.clause_no}
                </button>
              ))}
            </div>
          )}
          <p className="note">
            Searched {a.searched.length ? a.searched.join(", ") : "no wordings"}
            {a.withheld.length ? ` · ${a.withheld.length} citation(s) withheld - not verifiable` : ""}
            {a.cost_usd ? ` · model cost $${a.cost_usd}` : ""}
          </p>
        </article>
      ))}
      {opened && <ClauseViewer citation={opened} onClose={() => setOpened(null)} />}
    </section>
  );
}
