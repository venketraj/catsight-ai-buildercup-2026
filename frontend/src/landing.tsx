/**
 * The Analysis screen's opening (Phase 5): one question in a display serif,
 * the events as cards, the two ways to run, the five-step story and what makes
 * the answer trustworthy. Once a run has started it folds into a compact bar,
 * so the controls stay in reach without pushing the result down the page.
 */

import type { EventSummary } from "./types";

const PERIL: Record<string, { icon: string; word: string }> = {
  WS: { icon: "🌀", word: "Typhoon" },
  EQ: { icon: "〰", word: "Earthquake" },
};

const COUNTRY: Record<string, string> = { JPN: "Japan", PHL: "Philippines", TWN: "Taiwan" };

const STORY = [
  ["1", "Event", "where it hit, how hard"],
  ["2", "Who's hit", "treaties that respond"],
  ["3", "What it costs", "every layer, every party"],
  ["4", "Clauses", "verified, with the quote"],
  ["5", "Decide", "what-if, report, questions"],
];

export function Landing({
  events, selected, onSelect, running, compact, liveLabel, replayReady, onLive, onReplay, status,
}: {
  events: EventSummary[];
  selected: string;
  onSelect: (id: string) => void;
  running: boolean;
  compact: boolean;
  liveLabel: string;
  replayReady: boolean;
  onLive: () => void;
  onReplay: () => void;
  status?: string | null;
}) {
  const current = events.find((e) => e.event_id === selected);
  const buttons = (
    <div className="run-buttons">
      <button className="primary big" data-tour="replay" onClick={onReplay} disabled={running || !replayReady}
              title={replayReady ? "Plays back a recorded real run in a few seconds"
                : "No recording yet - run this event live once to record one"}>
        ▶ Instant replay <small>about 6 s · recorded real run</small>
      </button>
      <button className="secondary big" onClick={onLive} disabled={running} aria-busy={running}
              title="Runs the agents live: Gemini, Firestore vector search, about a minute">
        ⚡ {liveLabel} <small>Gemini agents · about a minute</small>
      </button>
      {status && <span className="note" style={{ margin: 0 }}>{status}</span>}
    </div>
  );

  if (compact) {
    return (
      <div className="landing compact">
        <label htmlFor="event" className="visually-hidden">Event</label>
        <select id="event" value={selected} disabled={running} onChange={(e) => onSelect(e.target.value)}>
          {events.map((e) => (
            <option key={e.event_id} value={e.event_id}>{e.name} ({e.date.slice(0, 4)})</option>
          ))}
        </select>
        {buttons}
      </div>
    );
  }

  return (
    <div className="landing">
      <p className="kicker">Lion Re · catastrophe desk</p>
      <h2 className="display">
        {current ? `${current.name}, ${current.date.slice(0, 4)}` : "A catastrophe has hit"}: what does it
        cost us - and which clauses change the answer?
      </h2>
      <p className="lede-line">
        CatSight replays a real typhoon or earthquake over our treaty book: which treaties respond,
        what each layer pays, and which wording clauses could move the money - each quote verified
        against the contract.
      </p>

      <div className="event-cards" role="radiogroup" aria-label="Choose an event">
        {events.map((e) => {
          const peril = PERIL[e.peril] ?? { icon: "•", word: e.peril };
          const on = e.event_id === selected;
          return (
            <button key={e.event_id} role="radio" aria-checked={on} disabled={running}
                    className={on ? "event-card on" : "event-card"} onClick={() => onSelect(e.event_id)}>
              <span className="ec-icon" aria-hidden>{peril.icon}</span>
              <span className="ec-name">{e.name}</span>
              <span className="ec-meta">
                {peril.word} · {e.date} · {e.countries.map((c) => COUNTRY[c] ?? c).join(", ")}
              </span>
              <span className="ec-meta">
                {e.regions} regions ·{" "}
                {e.peril === "EQ" ? "single shock" : `${e.duration_h ?? "-"} h damaging window`}
              </span>
              <span className={e.replay_available ? "ec-tag ready" : "ec-tag"}>
                {e.replay_available ? "recording available" : "live run only"}
              </span>
            </button>
          );
        })}
      </div>

      {buttons}

      <ol className="story-strip" aria-label="What you will see">
        {STORY.map(([n, label, hint]) => (
          <li key={n}><span className="ss-no">{n}</span><strong>{label}</strong><span>{hint}</span></li>
        ))}
      </ol>

      <ul className="proof-badges">
        <li>∑ every figure from a deterministic loss engine - the model does no arithmetic</li>
        <li>✓ every clause quote matched against the stored wording, or withheld</li>
        <li>≈ $0.01 in model cost per analysis, measured</li>
      </ul>
    </div>
  );
}
