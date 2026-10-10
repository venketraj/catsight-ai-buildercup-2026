/**
 * FR-JUDGE - the guided tour. A few short stops over the real screen, each
 * pointing at one thing a judge would otherwise have to find: the headline,
 * who pays what, the step-by-step calculation, the verified clause, the
 * Courtroom, the what-if and the report. It runs on an instant replay, so it
 * costs nothing and never waits on a model. Esc closes; arrows or Enter move.
 */

import { useCallback, useEffect, useLayoutEffect, useState } from "react";

import type { StepId } from "./steps";

interface Stop {
  target: string;
  step: StepId;
  title: string;
  body: string;
}

const STOPS: Stop[] = [
  { target: "summary", step: "hit", title: "The answer in one line",
    body: "What the disaster cost the insurers, what all reinsurers pay, and our net as Lion Re - plus how many clause findings passed verification. It stays at the top while you scroll." },
  { target: "money", step: "hit", title: "Who pays what",
    body: "The insurers' claims, split into what they keep and what reinsurers pay. Teal is our slice. Every width is a figure from the loss engine - the model does no arithmetic." },
  { target: "treaties", step: "hit", title: "Every treaty, and how",
    body: "Each treaty that responded, ordered by our exposure. Press How? on any row to see every step: hazard, damage by region, each layer's formula and its contract citation." },
  { target: "waterfall", step: "cost", title: "Layer by layer",
    body: "Pick any treaty: the insurer's retention, then each layer up to its limit, with exhausted layers hatched. The table below carries the same numbers." },
  { target: "trust", step: "clauses", title: "Why you can trust the findings",
    body: "Gemini reads the wordings through vector search. Each quote it cites is matched word for word against the stored contract and checked for support - anything that fails is withheld, never shown." },
  { target: "flags", step: "clauses", title: "The clause that changes the answer",
    body: "A verified finding, with treaty, page and clause. Open the citation to see the exact wording highlighted on its page." },
  { target: "court", step: "clauses", title: "The Clause Courtroom",
    body: "Two AI counsel argue opposite readings of the disputed clause, each from verified wording. The engine prices both readings, the arbiter summarises without deciding, and the analyst records a position." },
  { target: "whatif", step: "decide", title: "What if?",
    body: "Change an assumption - an hours clause window, a split into two events, an excluded share - and the engine re-prices it, showing the money at stake for each party. Hypotheticals are labelled as such." },
  { target: "report", step: "decide", title: "The report",
    body: "A first-view memo written from verified facts only, with every figure checked against the engine. Download it as Word or Markdown, or ask a follow-up question below it." },
];

export function Tour({ onStep, onClose }: { onStep: (step: StepId) => void; onClose: () => void }) {
  const [at, setAt] = useState(0);
  const [box, setBox] = useState<DOMRect | null>(null);
  const stop = STOPS[at]!;

  const go = useCallback((delta: number) => {
    setAt((i) => {
      const next = i + delta;
      if (next >= STOPS.length) {
        onClose();
        return i;
      }
      return Math.max(0, next);
    });
  }, [onClose]);

  // Show the stop's step, then find its element. A stop whose element is not
  // on screen (no Courtroom on a numbers-only run, say) is skipped.
  useLayoutEffect(() => {
    onStep(stop.step);
    let tries = 0;
    let timer = 0;
    const find = () => {
      const el = document.querySelector(`[data-tour="${stop.target}"]`);
      if (el) {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        window.setTimeout(() => setBox(el.getBoundingClientRect()), 350);
      } else if (tries++ < 8) {
        timer = window.setTimeout(find, 100);
      } else {
        go(1);
      }
    };
    setBox(null);
    find();
    return () => window.clearTimeout(timer);
  }, [at, stop, onStep, go]);

  useEffect(() => {
    const measure = () => {
      const el = document.querySelector(`[data-tour="${stop.target}"]`);
      if (el) setBox(el.getBoundingClientRect());
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); go(1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
    };
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [stop, go, onClose]);

  // The card sits below the highlighted element, or above it near the bottom.
  const below = box ? box.bottom + 230 < window.innerHeight : true;
  const cardStyle = box
    ? {
        top: below ? box.bottom + 12 : Math.max(12, box.top - 12),
        left: Math.min(Math.max(12, box.left), window.innerWidth - 392),
        transform: below ? undefined : "translateY(-100%)",
      }
    : { top: "40%", left: "50%", transform: "translate(-50%, -50%)" };

  return (
    <div className="tour" role="dialog" aria-modal="false" aria-labelledby="tour-title">
      {box && (
        <div className="tour-ring" style={{
          top: box.top - 6, left: box.left - 6, width: box.width + 12, height: Math.min(box.height + 12, window.innerHeight),
        }} />
      )}
      <div className="tour-card" style={cardStyle}>
        <p className="tour-count">Tour · {at + 1} of {STOPS.length}</p>
        <h3 id="tour-title">{stop.title}</h3>
        <p>{stop.body}</p>
        <div className="tour-actions">
          <button className="linkish" onClick={onClose}>Skip tour</button>
          <span className="spacer" />
          {at > 0 && <button className="secondary" onClick={() => go(-1)}>Back</button>}
          <button className="primary" onClick={() => go(1)} autoFocus>
            {at === STOPS.length - 1 ? "Finish" : "Next"}
          </button>
        </div>
      </div>
    </div>
  );
}
