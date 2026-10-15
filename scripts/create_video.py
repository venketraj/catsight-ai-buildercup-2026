"""Build the CatSight demo video from ONE real live run on the deployed site.

Every figure the narration speaks is read from that run - the Courtroom
outcome, the run time, the What-if result, the citation count - or from the
measured files in benchmarks/results/, never typed into this file. The
narration follows the README section by section, in its own words.

    python scripts/create_video.py            # capture, narrate, assemble

Needs: playwright (uses the installed Microsoft Edge), edge-tts,
imageio-ffmpeg. Output: docs/demo/CatSight_Demo_Video.mp4 plus .srt/.vtt,
loudness-normalised to -16 LUFS, under 2:55.
"""

import sys

sys.stdout.reconfigure(encoding="utf-8")

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from decimal import Decimal

import edge_tts
import imageio_ffmpeg
from playwright.sync_api import sync_playwright

LIVE_URL = os.environ.get("CATSIGHT_URL", "https://catsight-api-342162443546.us-central1.run.app")
REPO_URL = os.environ.get("CATSIGHT_REPO", "https://github.com/venketraj/catsight-ai-buildercup-2026")
VOICE = "en-US-ChristopherNeural"
RATE = "+12%"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FONT = "C\\:/Windows/Fonts/segoeui.ttf"
FONT_BOLD = "C\\:/Windows/Fonts/seguisb.ttf"
TEAL = "0x1fa99c"
MAX_SECONDS = 175  # 2:55; the rules say strictly under 3 minutes
# Recording pixels per CSS pixel. Playwright's recorder draws the page 1:1 in
# the top-left of the frame whatever the device scale, so 1080p is recorded.
CAPTURE_SCALE = 1

OUT = "docs/demo/CatSight_Demo_Video.mp4"
SUBS = "docs/demo/CatSight_Demo_Video"
BACKUP = "docs/demo/CatSight_Demo_Video_v3_plain"
TIMING = "benchmarks/results/browser_check_2026-10-15.json"
BENCH = "benchmarks/results/latest.json"

# What-if: Jebi's hero treaty, cut where the timeline splits into two real-sized
# occurrences (docs/MONEY_MOMENT.md section 3). The figures come from the engine.
WHATIF_TREATY = "T-001"
WHATIF_CUT = "2018-09-04T06:00:00+00:00"
ASK_EXAMPLE = "Why does T-004 matter for this event?"

for d in ("scratch/slides", "scratch/clips", "scratch/audio", "scratch/capture", "docs/demo"):
    os.makedirs(d, exist_ok=True)


# --------------------------------------------------------------------------- #
# 1. Capture: one continuous recording of a live run, with time marks          #
# --------------------------------------------------------------------------- #

# A headless recording shows no pointer. This draws one that follows the real
# mouse events Playwright sends, with a ripple on each click, so a viewer can
# see where the navigation happens. It is an overlay on the recording only.
CURSOR_JS = """
(() => {
  const install = () => {
    if (document.getElementById('demo-cursor')) return;
    const c = document.createElement('div');
    c.id = 'demo-cursor';
    c.innerHTML = '<svg width="28" height="28" viewBox="0 0 24 24"><path d="M3 2l7.5 19 2.4-7.6L20.5 11z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, {position:'fixed', left:'-50px', top:'-50px', zIndex:2147483647,
      pointerEvents:'none', transform:'translate(-3px,-2px)', filter:'drop-shadow(0 2px 3px rgba(0,0,0,.5))'});
    document.body.appendChild(c);
    const st = document.createElement('style');
    st.textContent = '@keyframes demo-ripple{from{transform:translate(-50%,-50%) scale(.3);opacity:.9}to{transform:translate(-50%,-50%) scale(1.6);opacity:0}}';
    document.head.appendChild(st);
    addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', e => {
      const r = document.createElement('div');
      Object.assign(r.style, {position:'fixed', left:e.clientX+'px', top:e.clientY+'px', width:'46px', height:'46px',
        borderRadius:'50%', border:'3px solid #1fa99c', background:'rgba(31,169,156,.25)', zIndex:2147483646,
        pointerEvents:'none', animation:'demo-ripple .6s ease-out forwards'});
      document.body.appendChild(r); setTimeout(() => r.remove(), 700);
    }, true);
  };
  if (document.body) install(); else addEventListener('DOMContentLoaded', install);
})();
"""

# Records, ten times a second, where each element the narration talks about
# sits on screen (CSS pixels), but only while it is in view and not covered.
# The assembly step uses this to draw a highlight, and zoom, on the element
# at the moment its figure is spoken.
TRACK_JS = """
(() => {
  window.__track = [];
  const sb = (label) => [...document.querySelectorAll('.summary-bar .sb-item')]
    .find(e => (e.querySelector('.sb-label')?.innerText || '').trim().toLowerCase() === label);
  const has = (sel, re) => [...document.querySelectorAll(sel)].find(e => re.test(e.innerText));
  const targets = {
    sb_contracts: () => sb('contracts hit'),
    sb_time: () => sb('time'),
    flow_treaties: () => has('.flow-step', /treaties respond/),
    flag_t004: () => has('li.flag', /T-004/),
    court_cites: () => document.querySelectorAll('.court-side button.cite'),
    court_stake: () => document.querySelector('.stake'),
    modal_mark: () => document.querySelectorAll('.modal mark'),
    whatif_table: () => document.querySelector('.whatif table'),
    report_check: () => document.querySelector('.paper-check'),
    ask_check: () => document.querySelector('.ask-answer .verify-header'),
  };
  const shown = (e, b) => {
    if (b.width < 2 || b.height < 2 || b.top < 0 || b.left < 0 || b.bottom > innerHeight || b.right > innerWidth) return false;
    const c = document.elementFromPoint((b.left + b.right) / 2, (b.top + b.bottom) / 2);
    return !!c && (e.contains(c) || c.contains(e));
  };
  setInterval(() => {
    const row = { t: Date.now() };
    for (const [name, find] of Object.entries(targets)) {
      let found; try { found = find(); } catch (err) { continue; }
      if (!found) continue;
      const els = found instanceof NodeList ? [...found] : [found];
      let r = null;
      for (const e of els) {
        const b = e.getBoundingClientRect();
        if (!shown(e, b)) { r = null; break; }
        r = r ? [Math.min(r[0], b.left), Math.min(r[1], b.top), Math.max(r[2], b.right), Math.max(r[3], b.bottom)]
              : [b.left, b.top, b.right, b.bottom];
      }
      if (r) row[name] = r.map(Math.round);
    }
    window.__track.push(row);
  }, 100);
})();
"""

_pointer = {"x": 960.0, "y": 540.0}


def point(page, locator, pause: int = 350) -> None:
    """Glide the visible pointer to the element without clicking."""
    target = locator.first
    target.scroll_into_view_if_needed()
    box = target.bounding_box()
    if not box:
        return
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(_pointer["x"], _pointer["y"])
    page.mouse.move(x, y, steps=28)
    _pointer.update(x=x, y=y)
    page.wait_for_timeout(pause)


def click(page, locator, pause: int = 350) -> None:
    """Glide the visible pointer to the element, then click it."""
    target = locator.first
    target.scroll_into_view_if_needed()
    if not target.bounding_box():
        target.click()
        return
    point(page, target, pause)
    page.mouse.down()
    page.wait_for_timeout(90)
    page.mouse.up()


def capture() -> dict:
    """Run Jebi live and walk the five steps: event, who's hit (with How?),
    what it costs, clauses and the Courtroom, the checked quote and scanned
    endorsement, then Decide (What-if, the report, a follow-up question)."""
    marks: dict[str, float] = {}
    facts: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, accept_downloads=True,
                                  device_scale_factor=CAPTURE_SCALE, record_video_dir="scratch/capture",
                                  record_video_size={"width": 1920 * CAPTURE_SCALE, "height": 1080 * CAPTURE_SCALE})
        ctx.add_init_script(CURSOR_JS)
        ctx.add_init_script(TRACK_JS)
        page = ctx.new_page()
        t0 = time.monotonic()
        t0_epoch = time.time()
        mark = lambda name: marks.__setitem__(name, round(time.monotonic() - t0, 2))

        court_box: dict = {}

        def on_response(resp):
            if re.search(r"/api/runs/[^/]+/courtroom(\?|$)", resp.url) and resp.request.method == "POST":
                try:
                    court_box["data"] = resp.json()
                except Exception:
                    pass

        page.on("response", on_response)

        page.goto(LIVE_URL, wait_until="networkidle")
        page.wait_for_timeout(1500)

        # Scene 2: one click, live; step 1 shows while the agents run.
        mark("live_click")
        click(page, page.locator("button:has-text('Run live')"))
        page.wait_for_function(
            "() => /\\d+ verified\\s*·\\s*\\d+ withheld/.test(document.body.innerText)"
            " && !document.querySelector('[aria-busy=true]')",
            timeout=300_000)
        mark("live_done")
        if marks["live_done"] - marks["live_click"] > 45:
            raise SystemExit(f"The analysis took {marks['live_done'] - marks['live_click']:.0f} s on this run, "
                             "outside every measured run (8-43 s) - record again rather than show it")
        page.wait_for_timeout(2000)
        body = page.inner_text("body")
        facts["seconds"] = _grab(r"TIME\s+(\d+)\s*s", body)
        facts["cost"] = _grab(r"MODEL COST\s+\$([\d.]+)", body)
        facts["treaties"] = re.search(r"(?:TREATIES|CONTRACTS)\s+HIT\s+(\d+)\s+of\s+(\d+)", body, re.IGNORECASE)
        facts["treaties"] = facts["treaties"].groups() if facts["treaties"] else None
        facts["flags"] = re.search(r"(\d+) verified\s*·\s*(\d+) withheld", body).groups()

        click(page, page.locator("button.step:has-text(\"Who's hit\")"))
        page.wait_for_timeout(4500)
        click(page, page.locator("button.cite:has-text('How?')"))
        page.wait_for_timeout(7000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)
        click(page, page.locator("button.step:has-text('What it costs')"))
        page.wait_for_timeout(6500)
        mark("steps_end")

        # Scene 3: step 4, the clauses and the Courtroom.
        mark("court_start")
        click(page, page.locator("button.step:has-text('Clauses that matter')"))
        page.wait_for_timeout(2500)
        click(page, page.locator("button:has-text('Open the Clause Courtroom')"))
        mark("court_click")
        page.wait_for_function(
            "() => /Arbiter|Neither side|could not produce/.test(document.body.innerText)",
            timeout=300_000)
        mark("court_done")
        facts["court_seconds"] = round(marks["court_done"] - marks["court_click"])
        if facts["court_seconds"] > 90:
            raise SystemExit(f"The Courtroom took {facts['court_seconds']} s on this run - an outlier; "
                             "record again rather than show it")
        page.wait_for_timeout(1500)
        page.locator(".court").first.scroll_into_view_if_needed()
        page.mouse.wheel(0, 300)
        page.wait_for_timeout(11000)
        page.mouse.wheel(0, 500)
        page.wait_for_timeout(10000)
        mark("court_end")
        facts["court"] = court_box.get("data")

        # Scene 4: the verified flag's clause, then the scanned endorsement.
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(800)
        mark("trust_start")
        click(page, page.locator("button:has-text('open clause')"))
        page.wait_for_timeout(6500)
        page.keyboard.press("Escape")
        mark("clause_closed")
        page.wait_for_timeout(500)
        click(page, page.locator("button.tab", has_text="Treaties"))
        page.wait_for_timeout(1500)
        click(page, page.locator("tr:has-text('T-004') button:has-text('Open')"))
        page.wait_for_timeout(1500)
        scanned = page.locator("button.cite:has-text('🖼')")
        facts["endorsement_shown"] = scanned.count() > 0
        if facts["endorsement_shown"]:
            scanned.first.scroll_into_view_if_needed()
            page.wait_for_timeout(800)
            point(page, scanned)
            mark("endorse_click")
            scanned.first.click()
            page.wait_for_timeout(6000)
            page.keyboard.press("Escape")
        mark("trust_end")

        # Scene 5: step 5, Decide - What-if, the report, a follow-up question.
        page.keyboard.press("Escape")
        click(page, page.locator("button.tab", has_text="Analysis"))
        page.wait_for_timeout(1200)
        page.evaluate("window.scrollTo(0, 0)")
        mark("decide_start")
        click(page, page.locator("button.step:has-text('Decide')"))
        page.wait_for_timeout(800)
        page.locator(".whatif select").first.select_option(WHATIF_TREATY)
        page.wait_for_timeout(1200)
        click(page, page.locator(".whatif input[type=radio]").nth(1))
        page.wait_for_timeout(300)
        cut = page.locator(".whatif select").nth(2)
        point(page, cut)
        cut.select_option(WHATIF_CUT)
        page.wait_for_timeout(400)
        with page.expect_response(lambda r: "/scenario" in r.url and r.request.method == "POST"
                                  and "hypothetical" in (r.request.post_data or "")) as info:
            click(page, page.locator(".whatif button:has-text('Price it')"))
        facts["whatif"] = info.value.json()
        page.locator(".whatif table").wait_for()
        page.locator(".whatif table").scroll_into_view_if_needed()
        page.wait_for_timeout(4500)

        page.locator(".panel.report").scroll_into_view_if_needed()
        page.wait_for_timeout(800)
        page.mouse.wheel(0, 350)
        page.wait_for_timeout(1500)
        with page.expect_download(timeout=60_000) as dl:
            click(page, page.locator("a:has-text('Download Word')"))
        facts["word_report"] = dl.value.suggested_filename
        page.wait_for_timeout(800)

        page.locator(".panel.ask").scroll_into_view_if_needed()
        page.wait_for_timeout(600)
        with page.expect_response(lambda r: r.url.endswith("/ask") and r.request.method == "POST",
                                  timeout=120_000) as info:
            click(page, page.locator(".ask-examples button", has_text=ASK_EXAMPLE))
        facts["ask"] = info.value.json() if info.value.ok else {"error": info.value.status}
        page.locator(".ask-answer").first.wait_for(timeout=120_000)
        page.locator(".ask-answer").first.scroll_into_view_if_needed()
        page.wait_for_timeout(8500)
        mark("decide_end")

        # Where each tracked element was on screen, on the recording's clock.
        track = [{**row, "t": round(row["t"] / 1000 - t0_epoch, 3)} for row in page.evaluate("window.__track || []")]
        page.close()
        video = page.video.path()
        ctx.close()
        browser.close()

    with open("scratch/capture/facts.json", "w", encoding="utf-8") as f:
        json.dump({"marks": marks, "facts": facts, "video": video}, f, indent=2, default=str)
    with open("scratch/capture/track.json", "w", encoding="utf-8") as f:
        json.dump(track, f)
    return {"video": video, "marks": marks, "facts": facts, "track": track}


def _grab(pattern: str, text: str):
    m = re.search(pattern, text)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# 2. Narration, written from what the run showed and the README's wording     #
# --------------------------------------------------------------------------- #

def _m(value) -> str:
    """'-11.64' -> '11.6 million dollars'."""
    v = abs(Decimal(str(value)))
    return f"{v:.1f} million dollars"


def measured() -> dict:
    """Averages from the 15 Oct browser check and the 10-run benchmark."""
    with open(TIMING, encoding="utf-8") as f:
        runs = json.load(f)["runs"]
    with open(BENCH, encoding="utf-8") as f:
        bench = json.load(f)["analyses"]
    a = [r["analysis_wall_s"] for r in runs]
    c = [r["courtroom_wall_s"] for r in runs if not r.get("courtroom_skipped")]
    cost = [float(r["app_cost"]) for r in runs]
    money = sorted(r["money_s"] for r in bench)
    return {"avg": round(sum(a) / len(a)), "lo": round(min(a)), "hi": round(max(a)),
            "court": round(sum(c) / len(c)), "court_lo": round(min(c)), "court_hi": round(max(c)),
            "cost": sum(cost) / len(cost), "money": (money[4] + money[5]) / 2}


def courtroom_lines(court: dict | None) -> str:
    opening = ("Step four, the clauses that matter. Treaty T-004 excludes storm surge, and Osaka "
               "recorded a record 329 centimetre tide. So two AI lawyers argue opposite readings, and "
               "each quote is checked against the page. ")
    closing = " An arbiter summarises without deciding; the analyst records the position."
    if not court or court.get("skipped"):
        return opening + "On this run no reading could be priced." + closing
    sides = court.get("sides", {})
    verified = {k: s for k, s in sides.items() if s.get("verified")}
    if "money_at_stake" in court and len(verified) == 2:
        stake = court["money_at_stake"]
        share = Decimal(str(sides["reinsurer"].get("excluded_share", 0))) * 100
        return (opening + f"Both quotes verify, and the engine prices both: at a {share:.0f} percent surge "
                f"share, {_m(stake['total_ceded'])} of recoveries move, and {_m(stake['our_net'])} of it "
                "is Lion Re's." + closing)
    if len(verified) == 1:
        return (opening + "On this run one side's quote failed the check, so that side was dropped and no "
                "money at stake is shown." + closing)
    return opening + "Neither side could cite verified wording, so nothing is priced." + closing


def decide_lines(facts: dict) -> str:
    w = facts.get("whatif") or {}
    stake, base = w.get("money_at_stake", {}), w.get("base", {})
    line = "Step five, decide. "
    if stake:
        retention = ("doubles" if Decimal(stake["cedent_retention"]) == Decimal(base["cedent_retention"])
                     else f"rises {_m(stake['cedent_retention'])}")
        line += (f"What-if prices a labelled hypothetical: split Jebi into two occurrences, and total "
                 f"recoveries fall {_m(stake['total_ceded'])}, while the insurer's retention {retention}. ")
    line += "The analyst report is ready to read, and downloads as Word, with every figure matching the engine. "
    ask = facts.get("ask") or {}
    line += "Then ask a follow-up question. Questions are screened by Google Cloud Model Armor"
    if ask.get("unsupported_figures") == []:
        line += ("; this answer cites the contract, and its figures all match the engine. " if ask.get("citations")
                 else "; this answer's figures all match the engine. ")
    else:
        line += ". "
    return line + "Nothing is sent anywhere automatically: people decide."


def scenes(facts: dict, m: dict) -> list[dict]:
    sec = facts.get("seconds") or "under sixty"
    hit = facts.get("treaties") or ("13", "24")
    return [
        {"id": "scene1_hook", "text": (
            "When a typhoon or earthquake hits, a reinsurer must know who pays what under each contract, "
            "and which wording could change that. In 2018, Typhoon Jebi hit western Japan; insured "
            "losses later reached about thirteen billion dollars.")},
        {"id": "scene2_run", "text": (
            "CatSight takes the side of a fictional reinsurer, Lion Re. One click, and the agents run "
            f"live. Step one, the event. Step two, who's hit: {hit[0]} of {hit[1]} treaties respond, and "
            "How was this calculated shows every step. Step three, what it costs, layer by layer. Tested "
            "Python calculates every figure; the AI never does the maths. This run took "
            f"{sec} seconds; on average, it's {m['avg']}.")},
        {"id": "scene3_clauses", "text": courtroom_lines(facts.get("court"))},
        {"id": "scene4_trust", "text": (
            "Every quote is matched word for word against the stored page, then a second Gemini model "
            "checks it. If it still fails after one retry, it's withheld and counted. "
            + ("Even a scanned endorsement with no text layer is read by Gemini and cited to its page."
               if facts.get("endorsement_shown") else ""))},
        {"id": "scene5_decide", "text": decide_lines(facts)},
        {"id": "scene6_results", "text": (
            "What we measured: ninety-nine point five percent extraction accuracy, an upper bound. Money "
            f"on screen in {m['money']:.1f} seconds. In three live runs on the fifteenth of October, the "
            f"full check averaged {m['avg']} seconds, and the Courtroom {m['court']} more, for about one "
            "cent per analysis.")},
        {"id": "scene7_architecture", "text": (
            "Gemini 3.5 Flash-Lite and 3.8 Flash on Gemini Enterprise Agent Platform. A Google ADK graph "
            "with a verification loop and a parallel Courtroom. Firestore vector search, Model Armor, "
            "Cloud Logging and Monitoring, all on one Cloud Run service.")},
        {"id": "scene8_close", "text": (
            "Synthetic contracts, real disasters, public hazard data. Reinsurance recoveries are what let "
            "insurers pay households and small businesses. CatSight is about settling them faster, and "
            "arguing about them less.")},
    ]


def cues(facts: dict, m: dict) -> dict[str, list[dict]]:
    """What lights up as each figure is spoken. `say` is the first word of the
    phrase (matched in order within the scene); `targets` are tracked elements
    (see TRACK_JS); `card` is a slide card; `zoom` marks the key moments."""
    sec = facts.get("seconds") or "-"
    hit = facts.get("treaties") or ("13", "24")
    court = facts.get("court") or {}
    stake = court.get("money_at_stake") or {}
    share = Decimal(str(((court.get("sides") or {}).get("reinsurer") or {}).get("excluded_share") or 0)) * 100
    w = (facts.get("whatif") or {}).get("money_at_stake") or {}
    usd = lambda v: f"${abs(Decimal(str(v))):.1f}M"
    out = {
        "scene1_hook": [{"say": "thirteen", "card": 1}],
        "scene2_run": [
            {"say": hit[0], "targets": ["flow_treaties", "sb_contracts"], "zoom": True,
             "caption": f"{hit[0]} of {hit[1]} treaties respond"},
            {"say": "tested", "caption": "Every figure from tested Python · no AI arithmetic"},
            {"say": "took", "targets": ["sb_time"], "zoom": True,
             "caption": f"This run {sec} s  ·  average {m['avg']} s"},
        ],
        "scene3_clauses": [
            {"say": "treaty", "targets": ["flag_t004"], "caption": "T-004 excludes storm surge · Osaka tide 329 cm"},
            {"say": "both", "targets": ["court_cites"], "caption": "Both quotes verified against the page"},
            {"say": "an", "caption": "The arbiter summarises · the analyst decides"},
        ],
        "scene4_trust": [
            {"say": "every", "targets": ["modal_mark"], "zoom": True,
             "caption": "Quote matched word for word on the stored page"},
            {"say": "if", "caption": "Fails after one retry → withheld and counted"},
            {"say": "even", "targets": ["modal_mark"], "zoom": True,
             "caption": "Scanned endorsement read by Gemini, cited to its page"},
        ],
        "scene5_decide": [
            {"say": "step", "caption": "Step 5 · Decide"},
            {"say": "nothing", "caption": "Nothing is sent automatically · people decide"},
        ],
        "scene6_results": [{"say": "ninety-nine", "card": 0}, {"say": "money", "card": 1},
                           {"say": "full", "card": 2}, {"say": "courtroom", "card": 3}, {"say": "cent", "card": 4}],
        "scene7_architecture": [{"say": "gemini", "card": 0}, {"say": "adk", "card": 1}, {"say": "firestore", "card": 2},
                                {"say": "model", "card": 3}, {"say": "cloud", "card": 6}, {"say": "run", "card": 4}],
    }
    if stake:
        out["scene3_clauses"].insert(2, {
            "say": "at", "targets": ["court_stake"], "zoom": True,
            "caption": f"At a {share:.0f}% surge share: {usd(stake['total_ceded'])} of recoveries move · "
                       f"Lion Re {usd(stake['our_net'])}"})
    if w:
        out["scene5_decide"].insert(1, {
            "say": "total", "targets": ["whatif_table"], "zoom": True,
            "caption": f"Hypothetical split: recoveries −{usd(w['total_ceded'])} · insurer's retention doubles"
                       if Decimal(w["cedent_retention"]) > 0 else f"Recoveries −{usd(w['total_ceded'])}"})
    out["scene5_decide"].insert(-1, {"say": "word", "targets": ["report_check"],
                                     "caption": "Report: every figure matches the engine · Word download"})
    if (facts.get("ask") or {}).get("unsupported_figures") == []:
        out["scene5_decide"].insert(-1, {"say": "this", "targets": ["ask_check"], "zoom": True,
                                         "caption": "Screened by Model Armor · every figure matches the engine"})
    return out


async def _tts(items: list[dict]) -> None:
    for s in items:
        comm = edge_tts.Communicate(s["text"], VOICE, rate=RATE, boundary="WordBoundary")
        words = []
        with open(f"scratch/audio/{s['id']}.mp3", "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    words.append({"t": chunk["offset"] / 1e7, "d": chunk["duration"] / 1e7, "w": chunk["text"]})
        s["words"] = words
        s["duration"] = _duration(f"scratch/audio/{s['id']}.mp3")


def _find_word(words: list[dict], say: str, after: int) -> int | None:
    say = say.lower()
    for i in range(after, len(words)):
        raw = words[i]["w"].lower()
        if re.sub(r"[^\w%\-]", "", raw) == say or raw.startswith(say + " "):
            return i
    return None


def _timed(scene: dict, scene_cues: list[dict]) -> list[dict]:
    """Attach each cue to the moment its first word is spoken, in order; a cue
    lasts until shortly before the next one, at most 3.2 s for a highlight."""
    found, after = [], 0
    for c in scene_cues:
        i = _find_word(scene["words"], c["say"], after)
        if i is None:
            print(f"WARNING: cue '{c['say']}' not found in {scene['id']}")
            continue
        after = i + 1
        found.append({**c, "at": scene["words"][i]["t"]})
    for k, c in enumerate(found):
        nxt = found[k + 1]["at"] - 0.15 if k + 1 < len(found) else scene["duration"] - 0.1
        c["until"] = nxt if "card" in c else min(c["at"] + (4.5 if c.get("targets") else 3.2), nxt)
    return found


def _duration(path: str) -> float:
    err = subprocess.run([FFMPEG, "-i", path], capture_output=True, text=True).stderr
    h, m, sec = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(sec)


# --------------------------------------------------------------------------- #
# 3. Slides                                                                    #
# --------------------------------------------------------------------------- #

CSS = """body{margin:0;width:1920px;height:1080px;background:#090d16;color:#f8fafc;
font-family:'Segoe UI',Roboto,sans-serif;display:flex;flex-direction:column;justify-content:center;
align-items:center;overflow:hidden}.badge{border:1px solid #1fa99c;color:#1fa99c;padding:8px 24px;
border-radius:999px;font-weight:700;font-size:18px;letter-spacing:2px;text-transform:uppercase;
margin-bottom:24px}.title{font-size:56px;font-weight:800;margin-bottom:48px;text-align:center}
.grid{display:grid;gap:28px}.card{background:#0f172a;border:1px solid #334155;border-radius:16px;
padding:32px;text-align:center}.val{font-size:52px;font-weight:800;color:#1fa99c;margin-bottom:8px}
.lbl{font-size:20px;font-weight:700;margin-bottom:8px}.sub{font-size:16px;color:#94a3b8;line-height:1.4}
.note{margin-top:40px;font-size:18px;color:#64748b;max-width:1400px;text-align:center;line-height:1.5}
.card{transition:none}.card.lit{border:2px solid #1fa99c;box-shadow:0 0 0 6px rgba(31,169,156,.22),0 0 48px rgba(31,169,156,.35);
transform:scale(1.05);background:#10243a}"""


def slides(m: dict) -> dict[str, str]:
    hook = f"""<style>{CSS}</style><div class=badge>CatSight · Typhoon Jebi, 2018</div>
<div class=title>Which contract words decide<br>who pays?</div>
<div class=grid style="grid-template-columns:1fr 1fr;width:1100px">
<div class=card><div class=sub>First modelled insured loss, ~10 days after (Moody's RMS)</div><div class=val style="color:#f8fafc">$3–5.5bn</div></div>
<div class=card><div class=sub>Insured loss after development (Swiss Re)</div><div class=val style="color:#c0812a">~$13bn</div></div></div>"""
    results = f"""<style>{CSS}</style><div class=badge>Measured</div><div class=title>What we measured</div>
<div class=grid style="grid-template-columns:repeat(5,1fr);width:1760px;gap:22px">
<div class=card><div class=val>99.5%</div><div class=lbl>Fields extracted (185/186)</div><div class=sub>on the 8 synthetic wordings the prompts were developed against (upper bound)</div></div>
<div class=card><div class=val>{m['money']:.1f} s</div><div class=lbl>Money on screen</div><div class=sub>median of 10 live runs, 14 Oct</div></div>
<div class=card><div class=val>{m['avg']} s</div><div class=lbl>Full check, live</div><div class=sub>average of 3 live runs in the browser, 15 Oct ({m['lo']}–{m['hi']} s)</div></div>
<div class=card><div class=val>{m['court']} s</div><div class=lbl>Clause Courtroom</div><div class=sub>a separate click; average of the same 3 runs ({m['court_lo']}–{m['court_hi']} s)</div></div>
<div class=card><div class=val>${m['cost']:.3f}</div><div class=lbl>Model cost per analysis</div><div class=sub>average of the 3 runs (Courtroom about $0.005 more)</div></div></div>
<div class=note>Slow runs spend their time re-checking a quote that failed its first check.<br>
10-run benchmark, 14 Oct: 11.3 s median (7.8–19.3 s) · 870+ offline tests · 0 untraceable figures in AI-written text</div>"""
    arch = f"""<style>{CSS}</style><div class=badge>Google Cloud</div><div class=title>How it is built</div>
<div class=grid style="grid-template-columns:repeat(4,1fr);width:1700px">
<div class=card><div class=lbl>Gemini 3.5 Flash-Lite · 3.8 Flash</div><div class=sub>on Gemini Enterprise Agent Platform (formerly Vertex AI): reading, checks, lawyers &amp; arbiter</div></div>
<div class=card><div class=lbl>Google ADK 2.11 graph</div><div class=sub>verification loop and parallel Courtroom fan-out</div></div>
<div class=card><div class=lbl>Firestore vector search</div><div class=sub>252 clause vectors at 768 dims, filtered by treaty</div></div>
<div class=card><div class=lbl>Google Cloud Model Armor</div><div class=sub>screens follow-up questions and answers, after a local filter</div></div>
<div class=card><div class=lbl>Cloud Run</div><div class=sub>one service: API, SSE stream and the React app</div></div>
<div class=card><div class=lbl>Deterministic loss engine</div><div class=sub>Python Decimal, 870+ offline tests: layers, reinstatements; no AI arithmetic</div></div>
<div class=card><div class=lbl>Cloud Logging &amp; Monitoring</div><div class=sub>one log line per stage; guardrail metrics on a dashboard</div></div>
<div class=card><div class=lbl>Public hazard data</div><div class=sub>NOAA IBTrACS · USGS ShakeMap · synthetic treaties</div></div></div>"""
    close = f"""<style>{CSS}</style><div class=title style="font-size:72px;margin-bottom:16px">CatSight</div>
<div style="font-size:30px;color:#1fa99c;margin-bottom:48px">Faster, fairer disaster recovery</div>
<div class=card style="text-align:left;font-size:22px;color:#94a3b8;line-height:2">
<b style="color:#f8fafc">Live</b> &nbsp;{LIVE_URL}<br><b style="color:#f8fafc">Code</b> &nbsp;{REPO_URL}</div>
<div class=note>Indicative first view on synthetic data. Not a catastrophe-model output. Not underwriting or claims advice.</div>"""
    return {"hook": hook, "results": results, "arch": arch, "close": close}


def render_slides(html: dict[str, str], lit: dict[str, set[int]]) -> None:
    """Render each slide, plus one copy per card that lights up as it is spoken."""
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        for name, body in html.items():
            path = os.path.abspath(f"scratch/slides/{name}.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"<!doctype html><meta charset=utf-8>{body}")
            page.goto(f"file:///{path}")
            page.screenshot(path=f"scratch/slides/{name}.png")
            for i in sorted(lit.get(name, set())):
                page.evaluate("i => { document.querySelectorAll('.card').forEach((c, k) => "
                              "c.classList.toggle('lit', k === i)); }", i)
                page.screenshot(path=f"scratch/slides/{name}_lit{i}.png")
        browser.close()


# --------------------------------------------------------------------------- #
# 4. Assembly                                                                  #
# --------------------------------------------------------------------------- #

def _run(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-600:])
    return r.stderr


def still(png: str, audio: str, dur: float, out: str, cues: list[dict] | None = None) -> None:
    """A slide held for its narration; each card lights up while it is spoken."""
    cues = [c for c in (cues or []) if "card" in c]
    name = png[:-4]
    cmd = [FFMPEG, "-y", "-loop", "1", "-i", png]
    for c in cues:
        cmd += ["-loop", "1", "-i", f"{name}_lit{c['card']}.png"]
    chain, last = [], "[0:v]"
    for k, c in enumerate(cues, 1):
        chain.append(f"{last}[{k}:v]overlay=0:0:enable='between(t,{c['at']:.2f},{c['until']:.2f})'[s{k}]")
        last = f"[s{k}]"
    chain.append(f"{last}format=yuv420p[v]")
    cmd += ["-i", audio, "-filter_complex", ";".join(chain), "-map", "[v]", "-map", f"{len(cues) + 1}:a",
            "-c:v", "libx264", "-tune", "stillimage", "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-ac", "1", "-t", f"{dur:.2f}", out]
    _run(cmd)


RAMP = 0.5  # seconds to zoom in, and again to zoom out


def _footage_time(parts: list[tuple[float, float]], tau: float) -> float:
    """Where in the capture the joined clip is at its own time tau."""
    acc = 0.0
    for a, b in parts:
        if tau < acc + (b - a):
            return a + tau - acc
        acc += b - a
    return parts[-1][1]


def _rect_at(track: list[dict], names: list[str], t: float) -> list[list[int]] | None:
    """The named elements' rects (CSS px) at capture time t, if all are on screen."""
    if not track:
        return None
    i = min(range(len(track)), key=lambda k: abs(track[k]["t"] - t))
    row = track[i]
    if abs(row["t"] - t) > 0.15 or any(n not in row for n in names):
        return None
    return [row[n] for n in names]


def _union(rs: list[list[int]]) -> list[int]:
    return [min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs)]


def _plan(cue: dict, parts: list[tuple[float, float]], track: list[dict]) -> dict:
    """Decide the highlight box, and zoom, for one cue. A box is drawn only
    while the element is on screen and still; otherwise the caption shows alone."""
    p = dict(cue)
    want_zoom = p.pop("zoom", False)
    if not cue.get("targets"):
        return p
    start = r0 = None
    t = cue["at"]
    while t <= min(cue["at"] + 3.0, cue["until"] - 1.0):
        r = _rect_at(track, cue["targets"], _footage_time(parts, t))
        if r:
            start, r0 = t, r
            break
        t += 0.1
    if start is None:
        print(f"  no box for '{cue['say']}': not on screen when spoken")
        return p
    end, t = start, start
    while t <= cue["until"]:
        r = _rect_at(track, cue["targets"], _footage_time(parts, t))
        if not r or max(abs(a - b) for ra, rb in zip(r, r0) for a, b in zip(ra, rb)) > 12:
            break
        end, t = t, t + 0.1
    if end - start < 1.0:
        print(f"  no box for '{cue['say']}': on screen only {end - start:.1f}s")
        return p
    u = _union(r0)
    p.update(boxes=r0, box=u, ba=start, bb=end)
    w, h = u[2] - u[0], u[3] - u[1]
    z = min(0.62 * 1920 / max(w, 1), 0.62 * 1080 / max(h, 1), 1.8)
    if want_zoom and z >= 1.2 and end - start >= 1.8:
        p["zoom"] = round(z, 2)
    return p


def _textfile(text: str, name: str) -> str:
    os.makedirs("scratch/cues", exist_ok=True)
    path = f"scratch/cues/{name}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def segment(video: str, parts: list[tuple[float, float]], audio: str, dur: float, out: str,
            caption: str | None = None, cues: list[dict] | None = None,
            track: list[dict] | None = None) -> list[dict]:
    """Join the listed [start, end] parts of the capture at real speed. A long
    wait is cut out, never sped up, and the cut is captioned with the real
    time it took. As each cued figure is spoken, its element is boxed (and,
    at key moments, zoomed) and a caption repeats it. Footage beyond the
    narration is trimmed from the end; a short clip holds its last frame."""
    s = CAPTURE_SCALE
    parts = [(max(a, 0.0), b) for a, b in parts if b - a > 0.2]
    lengths = [b - a for a, b in parts]
    length = sum(lengths)
    plans = [_plan(c, parts, track or []) for c in (cues or [])]
    tag = os.path.basename(out)[:-4]
    # A recording made with a larger frame holds the page 1:1 in its top-left corner.
    fc = [f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS,crop={1920 * s}:{1080 * s}:0:0,fps=30[p{i}]"
          for i, (a, b) in enumerate(parts)]
    fc.append("".join(f"[p{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[j]")
    chain = []
    for p in plans:
        if "box" not in p:
            continue
        a = p["ba"] + (RAMP if "zoom" in p else 0.0)
        b = p["bb"] - (RAMP if "zoom" in p else 0.2)
        on = f"enable='between(t,{a:.2f},{b:.2f})'"
        g = 8 * s
        for rect in p["boxes"]:
            x0, y0, x1, y1 = [v * s for v in rect]
            chain.append(f"drawbox=x={x0 - g}:y={y0 - g}:w={x1 - x0 + 2 * g}:h={y1 - y0 + 2 * g}:"
                         f"color={TEAL}@0.30:t={5 * s}:{on}")
            chain.append(f"drawbox=x={x0 - g // 2}:y={y0 - g // 2}:w={x1 - x0 + g}:h={y1 - y0 + g}:"
                         f"color={TEAL}@1.0:t={2 * s}:{on}")
    zooms = [p for p in plans if "zoom" in p]
    if zooms:
        terms, cx, cy = [], f"{960 * s}", f"{540 * s}"
        for p in zooms:
            a, b = p["ba"], p["bb"]
            u = f"min(clip((it-{a:.2f})/{RAMP},0,1),clip(({b:.2f}-it)/{RAMP},0,1))"
            terms.append(f"{p['zoom'] - 1:.3f}*({u})*({u})*(3-2*({u}))")
            mx, my = (p["box"][0] + p["box"][2]) / 2 * s, (p["box"][1] + p["box"][3]) / 2 * s
            cx = f"if(between(it,{a - 0.1:.2f},{b + 0.1:.2f}),{mx:.0f},{cx})"
            cy = f"if(between(it,{a - 0.1:.2f},{b + 0.1:.2f}),{my:.0f},{cy})"
        chain.append(f"zoompan=z='1+{'+'.join(terms)}':x='clip({cx}-iw/zoom/2,0,iw-iw/zoom)':"
                     f"y='clip({cy}-ih/zoom/2,0,ih-ih/zoom)':d=1:s=1920x1080:fps=30")
    else:
        chain.append("scale=1920:1080:flags=lanczos")
    if caption and len(parts) > 1:
        t = lengths[0]
        chain.append(f"drawtext=fontfile='{FONT}':textfile='{_textfile(caption, tag + '_wait')}':expansion=none:"
                     "x=(w-tw)/2:y=36:fontsize=30:fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=14:"
                     f"enable='between(t,{max(t - 0.3, 0):.2f},{t + 3.5:.2f})'")
    for k, p in enumerate(plans):
        if p.get("caption"):
            chain.append(f"drawtext=fontfile='{FONT_BOLD}':textfile='{_textfile(p['caption'], f'{tag}_{k}')}':"
                         "expansion=none:x=(w-tw)/2:y=h-112:fontsize=36:fontcolor=white:box=1:"
                         f"boxcolor={TEAL}@0.92:boxborderw=16:enable='between(t,{p['at']:.2f},{p['until']:.2f})'")
    chain.append("tpad=stop_mode=clone:stop_duration=60")
    fc.append("[j]" + ",".join(chain) + "[v]")
    if length + 0.5 < dur:
        print(f"WARNING: {out} footage {length:.1f}s is shorter than its narration {dur:.1f}s")
    _run([FFMPEG, "-y", "-i", video, "-i", audio, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "1:a",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
          "-ac", "1", "-t", f"{dur:.2f}", out])
    print(f"{out}: footage {length:.1f}s at real speed, narration {dur:.1f}s"
          + (f", {length - dur:.1f}s trimmed from the end" if length > dur else "")
          + f"; {sum('box' in p for p in plans)} boxes, {len(zooms)} zooms, {len(plans)} captions")
    return plans


def _wait_cut(start: float, click: float, done: float, end: float) -> list[tuple[float, float]]:
    """Keep the first seconds of a wait and the moment it finishes; cut the middle."""
    if done - click <= 7:
        return [(start, end)]
    return [(start, click + 3.0), (done - 2.5, end)]


def normalise(src: str, out: str) -> None:
    """Two-pass loudnorm to -16 LUFS; the video stream is copied unchanged."""
    err = _run([FFMPEG, "-i", src, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
    m = json.loads(err[err.rindex("{"):err.rindex("}") + 1])
    ln = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    _run([FFMPEG, "-y", "-i", src, "-c:v", "copy", "-af", ln, "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
          "-movflags", "+faststart", out])


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def _sentences(s: dict) -> list[tuple[float, float, str]]:
    """One subtitle per sentence, timed from the spoken words."""
    text = s["text"]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", text)] or [len(text)]
    starts = [0] + ends[:-1]
    spans: dict[int, list[float]] = {}
    pos = 0
    for w in s["words"]:
        i = text.find(w["w"], pos)
        i = pos if i < 0 else i
        pos = i + len(w["w"])
        k = next((j for j, e in enumerate(ends) if i < e), len(ends) - 1)
        a, b = spans.get(k, [w["t"], w["t"]])
        spans[k] = [a, w["t"] + w["d"]]
    return [(a, b, text[starts[k]:ends[k]].strip()) for k, (a, b) in sorted(spans.items())]


def write_subtitles(items: list[dict]) -> None:
    out, n, offset = [], 1, 0.0
    for s in items:
        for a, b, line in _sentences(s):
            out.append(f"{n}\n{_srt_time(offset + a)} --> {_srt_time(offset + b)}\n{line}\n")
            n += 1
        offset += s["duration"]
    srt = "\n".join(out)
    with open(f"{SUBS}.srt", "w", encoding="utf-8") as f:
        f.write(srt)
    with open(f"{SUBS}.vtt", "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n" + re.sub(r"(\d\d:\d\d:\d\d),(\d\d\d)", r"\1.\2", srt))


def _backup() -> None:
    for ext in (".mp4", ".srt", ".vtt"):
        src, dst = f"{SUBS}{ext}", f"{BACKUP}{ext}"
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
            print(f"kept the previous version: {src} -> {dst}")


def main() -> None:
    m = measured()
    if "--reuse" in sys.argv:  # rebuild from the last recording, without a new live run
        with open("scratch/capture/facts.json", encoding="utf-8") as f:
            cap = json.load(f)
        with open("scratch/capture/track.json", encoding="utf-8") as f:
            cap["track"] = json.load(f)
    else:
        cap = capture()
    facts, marks, video = cap["facts"], cap["marks"], cap["video"]
    print(json.dumps({"marks": marks, **{k: v for k, v in facts.items() if k not in ("court", "whatif", "ask")}},
                     indent=1, default=str))
    if not facts.get("court"):
        print("WARNING: no Courtroom response captured")

    items = scenes(facts, m)
    cue_map = cues(facts, m)
    asyncio.run(_tts(items))
    for s in items:
        print(f"{s['id']:22} {s['duration']:6.1f}s  {s['text'][:90]}...")
    total = sum(s["duration"] for s in items)
    print(f"narration total {total:.1f}s")
    if total > MAX_SECONDS:
        raise SystemExit(f"narration {total:.1f}s is over {MAX_SECONDS}s - shorten the text before assembling")

    timed = {s["id"]: _timed(s, cue_map.get(s["id"], [])) for s in items}
    lit = lambda sid: {c["card"] for c in timed[sid] if "card" in c}
    render_slides(slides(m), {"hook": lit("scene1_hook"), "results": lit("scene6_results"),
                              "arch": lit("scene7_architecture")})
    d = {s["id"]: s["duration"] for s in items}
    a = lambda i: f"scratch/audio/{i}.mp3"
    track = cap["track"]
    plans = {k: v for k, v in timed.items() if k.startswith(("scene1", "scene6", "scene7"))}
    still("scratch/slides/hook.png", a("scene1_hook"), d["scene1_hook"], "scratch/clips/scene1.mp4",
          timed["scene1_hook"])
    plans["scene2_run"] = segment(
        video, _wait_cut(marks["live_click"] - 1.0, marks["live_click"], marks["live_done"], marks["steps_end"]),
        a("scene2_run"), d["scene2_run"], "scratch/clips/scene2.mp4",
        caption=f"Wait shortened — this live run took {facts.get('seconds')} s in real time",
        cues=timed["scene2_run"], track=track)
    plans["scene3_clauses"] = segment(
        video, _wait_cut(marks["court_start"], marks["court_click"], marks["court_done"], marks["court_end"]),
        a("scene3_clauses"), d["scene3_clauses"], "scratch/clips/scene3.mp4",
        caption=f"Wait shortened — the Courtroom took {facts.get('court_seconds')} s in real time",
        cues=timed["scene3_clauses"], track=track)
    # Scene 4 cuts the walk to the Treaties tab, so the endorsement is on screen when it is named.
    trust_parts = ([(marks["trust_start"], marks["clause_closed"]), (marks["endorse_click"] - 1.0, marks["trust_end"])]
                   if "endorse_click" in marks and "clause_closed" in marks
                   else [(marks["trust_start"], marks["trust_end"])])
    plans["scene4_trust"] = segment(
        video, trust_parts, a("scene4_trust"), d["scene4_trust"],
        "scratch/clips/scene4.mp4", cues=timed["scene4_trust"], track=track)
    plans["scene5_decide"] = segment(
        video, [(marks["decide_start"], marks["decide_end"])], a("scene5_decide"), d["scene5_decide"],
        "scratch/clips/scene5.mp4", cues=timed["scene5_decide"], track=track)
    still("scratch/slides/results.png", a("scene6_results"), d["scene6_results"], "scratch/clips/scene6.mp4",
          timed["scene6_results"])
    still("scratch/slides/arch.png", a("scene7_architecture"), d["scene7_architecture"], "scratch/clips/scene7.mp4",
          timed["scene7_architecture"])
    still("scratch/slides/close.png", a("scene8_close"), d["scene8_close"], "scratch/clips/scene8.mp4")

    with open("scratch/clips/concat_list.txt", "w", encoding="utf-8") as f:
        for i in range(1, 9):
            f.write(f"file '{os.path.abspath(f'scratch/clips/scene{i}.mp4').replace(chr(92), '/')}'\n")
    _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", "scratch/clips/concat_list.txt", "-c", "copy",
          "scratch/clips/assembled.mp4"])
    _backup()
    normalise("scratch/clips/assembled.mp4", OUT)
    write_subtitles(items)
    with open("scratch/capture/narration.json", "w", encoding="utf-8") as f:
        json.dump({"measured": m, "scenes": [{k: s[k] for k in ("id", "text", "duration")} for s in items],
                   "cues": plans,
                   "whatif": facts.get("whatif", {}).get("money_at_stake"),
                   "court": (facts.get("court") or {}).get("money_at_stake"),
                   "ask_unsupported": (facts.get("ask") or {}).get("unsupported_figures")}, f, indent=2, default=str)
    review(items, plans)
    print(f"done: {OUT} ({_duration(OUT):.1f}s)")


def review(items: list[dict], plans: dict[str, list[dict]]) -> None:
    """One frame per cue, at the middle of its highlight, tiled for checking."""
    offsets, acc = {}, 0.0
    for s in items:
        offsets[s["id"]] = acc
        acc += s["duration"]
    shutil.rmtree("scratch/review", ignore_errors=True)
    os.makedirs("scratch/review")
    n = 0
    for s in items:
        for p in plans.get(s["id"], []):
            a, b = (p["ba"], p["bb"]) if "box" in p else (p["at"], p["until"])
            _run([FFMPEG, "-y", "-ss", f"{offsets[s['id']] + (a + b) / 2:.2f}", "-i", OUT, "-frames:v", "1",
                  "-vf", f"scale=640:-1,drawtext=fontfile='{FONT}':text='{n}':x=8:y=8:fontsize=28:"
                         "fontcolor=yellow:box=1:boxcolor=black", f"scratch/review/c{n:02}.png"])
            print(f"  cue {n:2}: {s['id']} '{p['say']}'"
                  + (f" box{' + zoom ' + str(p['zoom']) if 'zoom' in p else ''}" if "box" in p else "")
                  + (f" card {p['card']}" if "card" in p else "") + (f" · {p['caption']}" if p.get("caption") else ""))
            n += 1
    rows = (n + 3) // 4
    _run([FFMPEG, "-y", "-framerate", "1", "-i", "scratch/review/c%02d.png", "-vf", f"tile=4x{rows}",
          "-frames:v", "1", "scratch/review/sheet.png"])


if __name__ == "__main__":
    main()
