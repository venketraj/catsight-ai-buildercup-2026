"""Benchmarks against the live service: latency, cost and Courtroom repeatability.

    python benchmarks/run_all.py --api-url https://<service>.run.app --runs 5

Measures, per live Jebi analysis (B2 latency, B6 cost):
  - time to the money (first `impact` result frame) and end-to-end time;
  - model cost from the report frame (the service's own token accounting);
  - flags verified / withheld.
Then runs the Courtroom on each completed run (QA-11 repeatability): which
sides verified, the share each side claimed, and the engine's money at stake.

Every figure written comes from these runs. Standard library only.
Each run costs about $0.01 (analysis) + $0.005 (Courtroom) in model calls and
counts against the service's per-visitor hourly limit (default 20).
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
DOC = Path(__file__).resolve().parents[1] / "docs" / "RESULTS.md"
START, END = "<!-- benchmarks:start -->", "<!-- benchmarks:end -->"


def _post(url: str, body: dict, timeout: float = 300):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def analysis(api: str, event_id: str) -> dict:
    """One live analysis, read frame by frame from the SSE stream."""
    t0 = time.monotonic()
    out: dict = {"event_id": event_id, "money_s": None, "flags_verified": 0, "flags_withheld": 0}
    flags: dict[tuple, dict] = {}
    with _post(f"{api}/api/analyses", {"event_id": event_id, "mode": "replay", "replay": False}) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            frame = json.loads(line[5:])
            kind = frame.get("type")
            if kind == "result" and frame.get("key") == "impact" and out["money_s"] is None:
                out["money_s"] = round(time.monotonic() - t0, 2)
            elif kind == "flag":
                f = frame.get("flag") or {}
                key = (f.get("treaty_id"), f.get("issue_type"))
                flags[key] = {"treaty_id": key[0], "issue_type": key[1], "severity": f.get("severity"),
                              "status": frame.get("status")}
            elif kind == "verification":
                count = lambda v: v if isinstance(v, int) else len(v or [])
                out["flags_verified"] = count(frame.get("verified"))
                out["flags_withheld"] = count(frame.get("withheld"))
            elif kind == "report":
                out["cost_usd"] = frame.get("cost_usd")
                out["unsupported_figures"] = len(frame.get("unsupported_figures") or [])
            elif kind == "notice":
                out["notice"] = frame.get("message")
            elif kind == "error":
                out["error"] = frame.get("message") or frame
            elif kind == "done":
                out.update(run_id=frame.get("run_id"), agents=frame.get("agents"),
                           replay=bool(frame.get("replay")))
    out["total_s"] = round(time.monotonic() - t0, 2)
    out["flags"] = list(flags.values())
    return out


def courtroom(api: str, run_id: str) -> dict:
    t0 = time.monotonic()
    with _post(f"{api}/api/runs/{run_id}/courtroom", {}) as resp:
        court = json.loads(resp.read())
    flag = court.get("flag") or {}
    treaty_id = flag.get("treaty_id")
    out = {"seconds": round(time.monotonic() - t0, 2), "skipped": court.get("skipped"),
           "reason": court.get("reason"), "treaty_id": treaty_id,
           "cost_usd": court.get("cost_usd"), "unsupported_figures": len(court.get("unsupported_figures") or [])}
    for name, side in (court.get("sides") or {}).items():
        out[f"{name}_verified"] = bool(side.get("verified"))
        out[f"{name}_share"] = side.get("excluded_share")
        stake = (side.get("priced") or {}).get("money_at_stake") or {}
        out[f"{name}_our_net_move"] = stake.get("our_net")
    out["money_at_stake"] = court.get("money_at_stake")
    return out


def _stats(values: list[float]) -> str:
    values = [v for v in values if v is not None]
    if not values:
        return "-"
    p50 = statistics.median(values)
    return f"p50 {p50:.1f} \u00b7 min {min(values):.1f} \u00b7 max {max(values):.1f} (n={len(values)})"


def _usd(values: list[float]) -> str:
    if not values:
        return "-"
    return (f"p50 ${statistics.median(values):.4f} \u00b7 min ${min(values):.4f} \u00b7 "
            f"max ${max(values):.4f} (n={len(values)})")


def write(results: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "latest.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    runs = [r for r in results["analyses"] if not r.get("error") and not r.get("replay")]
    courts = results["courtrooms"]
    costs = [float(r["cost_usd"]) for r in runs if r.get("cost_usd")]
    court_costs = [float(c["cost_usd"]) for c in courts if c.get("cost_usd")]
    ran_courts = [c for c in courts if c and not c.get("skipped") and not c.get("error")]
    both = sum(1 for c in ran_courts if c.get("money_at_stake"))
    unrun_courts = [c for c in courts if not c or c.get("skipped") or c.get("error")]
    lines = [
        "## 1. Live service benchmarks",
        "",
        f"Measured {results['measured_at']} against `{results['api_url']}` (build `{results['build']}`), "
        f"event `{results['event_id']}`, {len(runs)} live analyses. Generated by "
        "`benchmarks/run_all.py`; raw data in `latest.json`.",
        "",
        "### Live analysis - latency and cost",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Time to the money (first engine result) | {_stats([r['money_s'] for r in runs])} s |",
        f"| End to end, all agents and verification | {_stats([r['total_s'] for r in runs])} s |",
        f"| Model cost per analysis | {_usd(costs)} |",
        f"| Report figures not traceable to the engine | {sum(r.get('unsupported_figures', 0) for r in runs)} across all runs |",
        "",
        "Times are measured from this client and include network and any cold start.",
        "",
        "### Per run - flags and the Clause Courtroom",
        "",
        f"Both sides verified in **{both} of {len(ran_courts)}** Courtrooms that ran.",
    ]
    if unrun_courts:
        reasons = "; ".join(f"Run {i}: {(c or {}).get('error') or (c or {}).get('reason') or 'not run'}"
                            for i, c in enumerate(courts, 1) if not c or c.get("skipped") or c.get("error"))
        lines.append(f"*Courtrooms not run ({len(unrun_courts)}):* {reasons}")
    lines += [
        "",
        "| Run | Total (s) | Cost ($) | Wording flags | Treaty argued | Insurer side | Reinsurer side | Reinsurer share | Our net move ($M) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, (r, c) in enumerate(zip(runs, courts + [{}] * len(runs)), 1):
        flags = "; ".join(f"{f['treaty_id']} {f['issue_type']} {f.get('severity') or ''} {f.get('status') or ''}".strip()
                          for f in r.get("flags", [])) or f"{r.get('flags_verified', 0)} verified, {r.get('flags_withheld', 0)} withheld"
        treaty = (c.get("treaty_id") if c else None) or "-"
        head = f"| {i} | {r['total_s']} | {r.get('cost_usd')} | {flags} | {treaty} |"
        if not c or c.get("error") or c.get("skipped"):
            lines.append(f"{head} not run: {(c or {}).get('error') or (c or {}).get('reason') or '-'} | | | |")
            continue
        move = (c.get("money_at_stake") or {}).get("our_net") or c.get("reinsurer_our_net_move") or "-"
        lines.append(f"{head} {'verified' if c.get('cedent_verified') else 'dropped'} | "
                     f"{'verified' if c.get('reinsurer_verified') else 'dropped'} | "
                     f"{c.get('reinsurer_share')} | {move} |")
    lines += [
        "",
        f"Courtroom cost per run: {_usd(court_costs)}.",
        "",
        "The counsel agents choose their surge share each run (bounded 0-50%), so money at stake "
        "varies with the share. For a given share the engine's figure is deterministic (unit-tested). "
        "A side whose quote does not support its argument is dropped, and no money at stake is shown.",
        "",
        "### Not measured here",
        "",
        "- **B1** manual analyst baseline and **B8** usability - both need people.",
        "- Flag recall/precision over a labelled corpus, and a blind-set extraction score.",
    ]
    section = "\n".join(lines).replace("raw data in `latest.json`", "raw data in `benchmarks/results/latest.json`")
    doc = DOC.read_text(encoding="utf-8")
    head, _, rest = doc.partition(START)
    _, _, tail = rest.partition(END)
    DOC.write_text(f"{head}{START}\n{section}\n{END}{tail}", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-url", required=True)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--event", default="jebi-2018")
    ap.add_argument("--no-courtroom", action="store_true")
    ap.add_argument("--rewrite-only", action="store_true", help="re-render docs/RESULTS.md from latest.json")
    args = ap.parse_args()
    if args.rewrite_only:
        write(json.loads((RESULTS / "latest.json").read_text(encoding="utf-8")))
        return
    api = args.api_url.rstrip("/")
    with urllib.request.urlopen(f"{api}/health", timeout=60) as r:
        health = json.loads(r.read())
    results = {"api_url": api, "build": health.get("build"), "event_id": args.event,
               "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
               "analyses": [], "courtrooms": []}
    for i in range(args.runs):
        try:
            r = analysis(api, args.event)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"Aborting benchmark: analysis {i + 1} HTTP error {e.code}: {e.read()[:200]!r}")
        except Exception as e:
            raise SystemExit(f"Aborting benchmark: analysis {i + 1} failed: {e}")

        print(f"analysis {i + 1}: {r}")

        if r.get("error"):
            raise SystemExit(f"Aborting benchmark: analysis {i + 1} returned error: {r['error']}")
        if r.get("replay"):
            raise SystemExit(f"Aborting benchmark: analysis {i + 1} served as replay (daily cap or fallback reached)")
        if r.get("notice") and ("cap" in r["notice"].lower() or "limit" in r["notice"].lower()):
            raise SystemExit(f"Aborting benchmark: analysis {i + 1} returned notice/limit: {r['notice']}")

        results["analyses"].append(r)
        if not args.no_courtroom:
            if not r.get("run_id"):
                raise SystemExit(f"Aborting benchmark: analysis {i + 1} did not return a run_id")
            try:
                c = courtroom(api, r["run_id"])
            except urllib.error.HTTPError as e:
                raise SystemExit(f"Aborting benchmark: courtroom {i + 1} HTTP error {e.code}")
            except Exception as e:
                raise SystemExit(f"Aborting benchmark: courtroom {i + 1} failed: {e}")

            print(f"courtroom {i + 1}: {c}")

            if c.get("error"):
                raise SystemExit(f"Aborting benchmark: courtroom {i + 1} returned error: {c['error']}")

            results["courtrooms"].append(c)
    write(results)
    print(f"wrote {DOC} and {RESULTS / 'latest.json'}")


if __name__ == "__main__":
    main()
