/**
 * The application shell and the Analysis screen (UI-1..8).
 *
 * One click runs the hero event through the agent graph. Panels fill in as
 * SSE frames arrive: the timeline with each live vector search, the loss
 * engine's figures, wording flags once the verifier has passed them, and the
 * report last. A judge with ninety seconds should not have to choose anything.
 */

import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";

import {
  AgentTimeline,
  ClauseViewer,
  FlagsPanel,
  KnowledgeBasePage,
  ReportPanel,
  type Retrieval,
  type ToolLine,
  type VerifiedFlag,
} from "./agents";
import { API_BASE, BUILD_LABEL, fetchEvents, fetchHealth, runAnalysis } from "./api";
import { EventPanel, ExcludedPanel, MoneyMoment, TreatyTable } from "./components";
import { BenchmarkPanel, ExplainModal, FlowSummary } from "./explain";
import { AskPanel } from "./ask";
import { CourtroomPanel } from "./courtroom";
import { analysisMarkdown, downloadMarkdown } from "./export";
import { HazardMap } from "./Map";
import { Landing } from "./landing";
import { Tour } from "./tour";
import { Logo } from "./Logo";
import { WhatIfPanel } from "./whatif";
import { MethodologyPage, TreatiesPage } from "./pages";
import { SkeletonPanel, Stepper, SummaryBar, TrustStrip, type Step, type StepId } from "./steps";
import type { EventSummary, Frame, Health, Impact, WordingFlag, Withheld } from "./types";

// The layer chart only exists after an analysis, so it loads on demand.
const LayerChart = lazy(() => import("./LayerChart"));

const HERO_EVENT = "jebi-2018";
/** Kept in the data and the API, but not offered in the demo: its Philippine
 * book is scaled like Japan's, so gross claims (~$94B) are not credible next
 * to the real ~$1.5B insured loss. See ASSUMPTIONS X11 and the README. */
const DEMO_HIDDEN = new Set(["haiyan-2013"]);
/** Sakura's programme is the worked example in DOMAIN_PRIMER section 4. */
const HERO_TREATY = "T-001";

type Page = "analysis" | "knowledge" | "treaties" | "methodology";

const PAGES: { id: Page; label: string }[] = [
  { id: "analysis", label: "Analysis" },
  { id: "knowledge", label: "Knowledge base" },
  { id: "treaties", label: "Treaties" },
  { id: "methodology", label: "Methodology" },
];

interface RunState {
  status: Record<string, "running" | "done">;
  tools: ToolLine[];
  retrievals: Retrieval[];
  warnings: string[];
  impact: Impact | null;
  verified: VerifiedFlag[];
  withheld: Withheld[];
  header: string | null;
  report: {
    markdown: string;
    unsupported: string[];
    calls: Record<string, number>;
    costUsd?: string | null;
  } | null;
  agents: boolean | null;
  analysisId: string | null;
  /** The stored run, for the Word export. */
  runId: string | null;
  /** Set when the stream is a recorded run being played back. */
  replay: { message: string; liveSeconds: number } | null;
}

const EMPTY: RunState = {
  status: {},
  tools: [],
  retrievals: [],
  warnings: [],
  impact: null,
  verified: [],
  withheld: [],
  header: null,
  report: null,
  agents: null,
  analysisId: null,
  runId: null,
  replay: null,
};

export default function App() {
  const [page, setPage] = useState<Page>("analysis");
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [selected, setSelected] = useState(HERO_EVENT);
  const [health, setHealth] = useState<Health | null>(null);

  const [running, setRunning] = useState(false);
  const [run, setRun] = useState<RunState>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  /** The server refused a live run (rate limit or daily cap): offer the replay. */
  const [limited, setLimited] = useState(false);
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  const [opened, setOpened] = useState<WordingFlag | null>(null);
  const [explaining, setExplaining] = useState<string | null>(null);
  const [ranEvent, setRanEvent] = useState(HERO_EVENT);
  const [elapsed, setElapsed] = useState(0);
  const abort = useRef<AbortController | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">(
    () => (localStorage.getItem("catsight-theme") === "light" ? "light" : "dark"),
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("catsight-theme", theme);
  }, [theme]);
  const [step, setStep] = useState<StepId>("event");
  /** Once the analyst picks a step, the screen stops following the run. */
  const picked = useRef(false);
  const [touring, setTouring] = useState(false);
  /** The tour was asked for before a run existed: start it when the replay ends. */
  const [tourPending, setTourPending] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchEvents(controller.signal)
      .then((payload) => setEvents(payload.events))
      .catch(() => {
        /* the catalogue is a convenience; the hero button works without it */
      });
    fetchHealth(controller.signal)
      .then(setHealth)
      .catch(() => setHealth(null));
    return () => controller.abort();
  }, []);

  useEffect(() => () => abort.current?.abort(), []);

  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500);
    return () => clearInterval(timer);
  }, [running]);

  const start = useCallback(async (eventId: string, replay = false) => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setRunning(true);
    setError(null);
    setLimited(false);
    setRun(EMPTY);
    setElapsed(0);
    setRanEvent(eventId);
    setStep("event");
    picked.current = false;
    try {
      for await (const frame of runAnalysis({ event_id: eventId, replay }, controller.signal)) {
        if (frame.type === "error") {
          setError(frame.message);
          setLimited(frame.retryable === false);
        }
        else setRun((current) => reduce(current, frame));
      }
    } catch (caught) {
      if ((caught as Error)?.name !== "AbortError") {
        setError(
          caught instanceof Error
            ? `The analysis could not reach the server (${caught.message}). Instant replay still works if a recording exists - or try again in a moment.`
            : "The analysis could not be started. Try Instant replay, or again in a moment.",
        );
      }
    } finally {
      setRunning(false);
      // A completed live run records a replay; refresh so the button enables.
      if (!replay) fetchEvents().then((p) => setEvents(p.events)).catch(() => {});
    }
  }, []);

  const impact = run.impact;
  const hero =
    impact?.treaties.find((t) => t.treaty_id === HERO_TREATY) ?? impact?.treaties[0];
  const started = Object.keys(run.status).length > 0 || run.impact !== null;

  const steps: Step[] = [
    { id: "event", label: "Event", hint: "what happened, agents at work", ready: started },
    { id: "hit", label: "Who's hit", hint: "treaties that respond", ready: impact !== null },
    { id: "cost", label: "What it costs", hint: "layers and each party", ready: impact !== null },
    { id: "clauses", label: "Clauses that matter", hint: "verified flags, Courtroom", ready: impact !== null },
    { id: "decide", label: "Decide", hint: "what-if, report, questions", ready: impact !== null },
  ];

  const pickStep = useCallback((id: StepId) => {
    picked.current = true;
    setStep(id);
  }, []);

  // Follow the run until the analyst takes over: the money is the first
  // answer, so move to "who's hit" as soon as the engine has it.
  useEffect(() => {
    if (impact && !picked.current && step === "event" && !running) setStep("hit");
  }, [impact, running, step]);

  useEffect(() => {
    if (tourPending && run.report && !running) {
      setTourPending(false);
      setTouring(true);
    }
  }, [tourPending, run.report, running]);

  const startTour = () => {
    setPage("analysis");
    if (run.report && !running) setTouring(true);
    else if (!running) {
      setTourPending(true);
      setSelected(HERO_EVENT);
      start(HERO_EVENT, true);
    } else setTourPending(true);
  };
  const endTour = useCallback(() => setTouring(false), []);

  // Left/right arrows move between steps, except while typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (touring || page !== "analysis" || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const ready = steps.filter((s) => s.ready).map((s) => s.id);
      const at = ready.indexOf(step);
      const next = ready[at + (e.key === "ArrowRight" ? 1 : -1)];
      if (next) pickStep(next);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="wrap">
      <header className="top">
        <h1 className="brand"><Logo /> CatSight</h1>
        <span className="tag">Treaty-level catastrophe impact for reinsurers</span>
        <span className="spacer" />
        <button className="tour-button" onClick={startTour}
                title="A short guided walk through a recorded real run of Typhoon Jebi">
          <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden>
            <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
            <path d="M10.6 5.4 9 9 5.4 10.6 7 7z" fill="currentColor" />
          </svg>
          Take the tour
        </button>
        <button
          className="theme-switch"
          role="switch"
          aria-checked={theme === "light"}
          aria-label="Light mode"
          onClick={() => setTheme(theme === "light" ? "dark" : "light")}
        >
          <span aria-hidden>{theme === "light" ? "☀" : "☾"}</span>
          <span className="track" aria-hidden><span className="knob" /></span>
          Light mode
        </button>
        <span className="build">
          build {BUILD_LABEL}
          {health ? ` · api ${health.version}` : ""}
          {health ? ` · ${health.models.main}` : ""}
        </span>
      </header>

      <nav className="tabs" aria-label="Sections">
        {PAGES.map((p) => (
          <button
            key={p.id}
            className={page === p.id ? "tab active" : "tab"}
            aria-current={page === p.id ? "page" : undefined}
            onClick={() => setPage(p.id)}
          >
            {p.label}
          </button>
        ))}
      </nav>

      {page === "knowledge" && <KnowledgeBasePage />}
      {page === "treaties" && <TreatiesPage />}
      {page === "methodology" && <MethodologyPage />}

      {page === "analysis" && (
        <>
          <Landing
            events={events.length ? events.filter((e) => !DEMO_HIDDEN.has(e.event_id)) : [fallbackEvent()]}
            selected={selected}
            onSelect={setSelected}
            running={running}
            compact={started || running}
            liveLabel={running && !run.replay ? `Running live… ${elapsed}s` : `Run live: ${labelFor(events, selected)}`}
            replayReady={hasReplay(events, selected)}
            onLive={() => start(selected)}
            onReplay={() => start(selected, true)}
            status={!running && run.agents !== null && !run.replay
              ? (run.agents ? `agents ran live in ${elapsed}s` : "numbers-only run") : null}
          />
          {run.replay && (
            <div className="banner replay" role="status">
              ▶ {run.replay.message}
            </div>
          )}

          {!online && (
            <div className="banner info" role="status">
              You appear to be offline. Recorded runs still play if the page has loaded; live runs
              need a connection.
            </div>
          )}

          {error && (
            <div className={limited ? "banner info" : "banner error"} role="alert">
              <span>{error}</span>
              {hasReplay(events, selected) && !running && (
                <button className="secondary" style={{ marginLeft: 12 }} onClick={() => start(selected, true)}>
                  ▶ Show the instant replay
                </button>
              )}
            </div>
          )}

          {health && !health.configured && (
            <div className="banner info">
              The API has no Google Cloud project configured: figures still work, but the
              wording agents will not run.
            </div>
          )}

          {impact && (
            <SummaryBar
              impact={impact}
              verified={run.verified.length}
              withheld={run.withheld.length}
              checked={run.header !== null}
              seconds={run.replay ? run.replay.liveSeconds : elapsed}
              running={running}
              costUsd={run.report?.costUsd}
            />
          )}

          {started && (
            <Stepper steps={steps} current={step} onPick={pickStep} />
          )}

          {started && step === "event" && (
            <>
              <AgentTimeline
                status={run.status}
                tools={run.tools}
                retrievals={run.retrievals}
                warnings={run.warnings}
                verificationHeader={run.header}
              />
              {impact && <HazardMap eventId={impact.event.event_id} peril={impact.event.peril} />}
              {impact && <EventPanel impact={impact} />}
            </>
          )}

          {impact && hero && step === "hit" && (
            <>
              <FlowSummary impact={impact} />
              <TreatyTable impact={impact} heroId={hero.treaty_id} onExplain={setExplaining} />
              <ExcludedPanel impact={impact} />
            </>
          )}

          {impact && hero && step === "cost" && (
            <>
              <MoneyMoment hero={hero} />
              <Suspense fallback={<SkeletonPanel title="How the loss is split" />}>
                <LayerChart treaties={impact.treaties} initial={hero.treaty_id} />
              </Suspense>
            </>
          )}

          {impact && step === "clauses" && (
            <>
              <TrustStrip
                verified={run.verified.length}
                withheld={run.withheld.length}
                checked={run.header !== null}
                running={running}
                agents={run.agents}
                method={impact.methodology?.version ?? null}
              />
              <FlagsPanel
                verified={run.verified}
                withheld={run.withheld}
                header={run.header}
                running={running}
                onOpen={setOpened}
              />
              {run.runId && !running && run.agents && health?.features?.courtroom !== false && (
                <CourtroomPanel key={run.runId} runId={run.runId} />
              )}
            </>
          )}

          {impact && step === "decide" && (
            <>
              <WhatIfPanel analysisId={run.analysisId ?? `replay-${ranEvent}`} impact={impact} />
              {run.report ? (
                <ReportPanel
                  markdown={run.report.markdown}
                  unsupported={run.report.unsupported}
                  calls={run.report.calls}
                  wordUrl={run.runId ? `${API_BASE}/api/runs/${run.runId}/report.docx` : null}
                  onDownload={() =>
                    downloadMarkdown(
                      `catsight-${impact.event.event_id}.md`,
                      analysisMarkdown({
                        impact,
                        report: run.report!.markdown,
                        verified: run.verified,
                        withheld: run.withheld,
                        header: run.header,
                        replay: run.replay,
                        costUsd: run.report!.costUsd,
                      }),
                    )
                  }
                />
              ) : running ? (
                <SkeletonPanel title="Report" />
              ) : null}
              {run.report && !running && run.agents && (
                <AskPanel analysisId={run.analysisId ?? `replay-${ranEvent}`} />
              )}
              {run.report && !running && (
                <BenchmarkPanel
                  eventId={ranEvent}
                  metrics={{
                    // A replay reports the original live run's time, not playback time.
                    seconds: run.replay ? run.replay.liveSeconds : elapsed,
                    calls: Object.values(run.report.calls).reduce((a, b) => a + b, 0),
                    costUsd: run.report.costUsd,
                    verified: run.verified.length,
                    withheld: run.withheld.length,
                    wordingsChecked: new Set(run.retrievals.map((r) => r.treaty_id)).size,
                    treatiesMatched: impact.totals.treaties_matched,
                  }}
                />
              )}
            </>
          )}

          {started && !impact && step !== "event" && <SkeletonPanel title="Waiting for the loss engine" />}


        </>
      )}

      {touring && <Tour onStep={pickStep} onClose={endTour} />}
      {opened && <ClauseViewer citation={opened.citation} onClose={() => setOpened(null)} />}
      {explaining && (
        <ExplainModal
          analysisId={run.analysisId ?? `replay-${ranEvent}`}
          treatyId={explaining}
          onClose={() => setExplaining(null)}
        />
      )}

      <footer className="foot">
        <strong>Indicative first view on synthetic data. Not a catastrophe-model output. Not
        underwriting or claims advice.</strong> Synthetic portfolio and treaty wordings; cedent
        names are fictional. Hazard from NOAA IBTrACS and USGS ShakeMap; damage ratios from
        published vulnerability curves.
      </footer>
    </div>
  );
}

/** Fold one SSE frame into the run state. Pure, so it is easy to reason about. */
function reduce(state: RunState, frame: Frame): RunState {
  switch (frame.type) {
    case "stage":
      return {
        ...state,
        status: { ...state.status, [frame.agent]: frame.status === "completed" ? "done" : "running" },
      };
    case "tool":
      return { ...state, tools: [...state.tools, { agent: frame.agent, name: frame.name, summary: frame.summary }] };
    case "retrieval":
      return {
        ...state,
        retrievals: [...state.retrievals, { treaty_id: frame.treaty_id, query: frame.query, hits: frame.hits }],
      };
    case "warning":
      return { ...state, warnings: [...state.warnings, `${frame.treaty_id ?? ""} ${frame.message}`.trim()] };
    case "result":
      return frame.key === "impact" ? { ...state, impact: frame.data as Impact } : state;
    case "flag":
      return frame.status === "verified"
        ? { ...state, verified: [...state.verified, { flag: frame.flag, badge: frame.badge ?? "verified" }] }
        : state;
    case "verification":
      return { ...state, header: frame.header, withheld: frame.withheld };
    case "report":
      return {
        ...state,
        report: {
          markdown: frame.markdown,
          unsupported: frame.unsupported_figures,
          calls: frame.calls,
          costUsd: frame.cost_usd,
        },
      };
    case "notice":
      return { ...state, replay: { message: frame.message, liveSeconds: frame.live_seconds } };
    case "done":
      return { ...state, agents: frame.agents ?? false, analysisId: frame.analysis_id, runId: frame.run_id ?? null };
    default:
      return state;
  }
}

function hasReplay(events: EventSummary[], id: string): boolean {
  return Boolean(events.find((e) => e.event_id === id)?.replay_available);
}

function labelFor(events: EventSummary[], id: string): string {
  const found = events.find((e) => e.event_id === id);
  return found ? `${found.name} ${found.date.slice(0, 4)}` : "Typhoon Jebi 2018";
}

function fallbackEvent(): EventSummary {
  return {
    event_id: HERO_EVENT,
    name: "Typhoon Jebi",
    peril: "WS",
    date: "2018-09-04",
    countries: ["JPN"],
    duration_h: 9,
    regions: 34,
  };
}
