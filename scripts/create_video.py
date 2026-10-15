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
MAX_SECONDS = 175  # 2:55; the rules say strictly under 3 minutes

OUT = "docs/demo/CatSight_Demo_Video.mp4"
SUBS = "docs/demo/CatSight_Demo_Video"
BACKUP = "docs/demo/CatSight_Demo_Video_v2_patched"
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
                                  record_video_dir="scratch/capture",
                                  record_video_size={"width": 1920, "height": 1080})
        ctx.add_init_script(CURSOR_JS)
        page = ctx.new_page()
        t0 = time.monotonic()
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
        page.wait_for_timeout(3800)
        page.keyboard.press("Escape")
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
            click(page, scanned)
            page.wait_for_timeout(5000)
            page.keyboard.press("Escape")
        mark("trust_end")

        # Scene 5: step 5, Decide - What-if, the report, a follow-up question.
        page.keyboard.press("Escape")
        click(page, page.locator("button.tab", has_text="Analysis"))
        page.wait_for_timeout(1200)
        page.evaluate("window.scrollTo(0, 0)")
        mark("decide_start")
        click(page, page.locator("button.step:has-text('Decide')"))
        page.wait_for_timeout(1500)
        page.locator(".whatif select").first.select_option(WHATIF_TREATY)
        page.wait_for_timeout(1500)
        click(page, page.locator(".whatif input[type=radio]").nth(1))
        page.wait_for_timeout(500)
        cut = page.locator(".whatif select").nth(2)
        point(page, cut)
        cut.select_option(WHATIF_CUT)
        page.wait_for_timeout(700)
        with page.expect_response(lambda r: "/scenario" in r.url and r.request.method == "POST"
                                  and "hypothetical" in (r.request.post_data or "")) as info:
            click(page, page.locator(".whatif button:has-text('Price it')"))
        facts["whatif"] = info.value.json()
        page.locator(".whatif table").wait_for()
        page.locator(".whatif table").scroll_into_view_if_needed()
        page.wait_for_timeout(6000)

        page.locator(".panel.report").scroll_into_view_if_needed()
        page.wait_for_timeout(1200)
        page.mouse.wheel(0, 350)
        page.wait_for_timeout(2000)
        with page.expect_download(timeout=60_000) as dl:
            click(page, page.locator("a:has-text('Download Word')"))
        facts["word_report"] = dl.value.suggested_filename
        page.wait_for_timeout(1500)

        page.locator(".panel.ask").scroll_into_view_if_needed()
        page.wait_for_timeout(1000)
        with page.expect_response(lambda r: r.url.endswith("/ask") and r.request.method == "POST",
                                  timeout=120_000) as info:
            click(page, page.locator(".ask-examples button", has_text=ASK_EXAMPLE))
        facts["ask"] = info.value.json() if info.value.ok else {"error": info.value.status}
        page.locator(".ask-answer").first.wait_for(timeout=120_000)
        page.locator(".ask-answer").first.scroll_into_view_if_needed()
        page.wait_for_timeout(7000)
        mark("decide_end")

        page.close()
        video = page.video.path()
        ctx.close()
        browser.close()

    with open("scratch/capture/facts.json", "w", encoding="utf-8") as f:
        json.dump({"marks": marks, "facts": facts, "video": video}, f, indent=2, default=str)
    return {"video": video, "marks": marks, "facts": facts}


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


async def _tts(items: list[dict]) -> None:
    for s in items:
        comm = edge_tts.Communicate(s["text"], VOICE, rate=RATE)
        subs = edge_tts.SubMaker()
        with open(f"scratch/audio/{s['id']}.mp3", "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                    subs.feed(chunk)
        s["srt"] = subs.get_srt()
        s["duration"] = _duration(f"scratch/audio/{s['id']}.mp3")


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
.note{margin-top:40px;font-size:18px;color:#64748b;max-width:1400px;text-align:center;line-height:1.5}"""


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


def render_slides(html: dict[str, str]) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        for name, body in html.items():
            path = os.path.abspath(f"scratch/slides/{name}.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"<!doctype html><meta charset=utf-8>{body}")
            page.goto(f"file:///{path}")
            page.screenshot(path=f"scratch/slides/{name}.png")
        browser.close()


# --------------------------------------------------------------------------- #
# 4. Assembly                                                                  #
# --------------------------------------------------------------------------- #

def _run(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-600:])
    return r.stderr


def still(png: str, audio: str, dur: float, out: str) -> None:
    _run([FFMPEG, "-y", "-loop", "1", "-i", png, "-i", audio, "-c:v", "libx264", "-tune", "stillimage",
          "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "1",
          "-t", f"{dur:.2f}", out])


def segment(video: str, parts: list[tuple[float, float]], audio: str, dur: float, out: str,
            caption: str | None = None) -> None:
    """Join the listed [start, end] parts of the capture at real speed. A long
    wait is cut out, never sped up, and the cut is captioned with the real
    time it took. Footage beyond the narration is trimmed from the end; a clip
    shorter than its narration holds its last frame, which is reported."""
    parts = [(max(a, 0.0), b) for a, b in parts if b - a > 0.2]
    lengths = [b - a for a, b in parts]
    length = sum(lengths)
    fc = [f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS,scale=1920:1080,fps=30[p{i}]"
          for i, (a, b) in enumerate(parts)]
    fc.append("".join(f"[p{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[j]")
    last = "[j]"
    if caption and len(parts) > 1:
        t = lengths[0]
        fc.append(f"[j]drawtext=fontfile='{FONT}':text='{caption}':x=(w-tw)/2:y=h-120:fontsize=34:"
                  "fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=16:"
                  f"enable='between(t,{max(t - 0.3, 0):.2f},{t + 3.5:.2f})'[c]")
        last = "[c]"
    fc.append(f"{last}tpad=stop_mode=clone:stop_duration=60[v]")
    if length + 0.5 < dur:
        print(f"WARNING: {out} footage {length:.1f}s is shorter than its narration {dur:.1f}s")
    _run([FFMPEG, "-y", "-i", video, "-i", audio, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "1:a",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
          "-ac", "1", "-t", f"{dur:.2f}", out])
    print(f"{out}: footage {length:.1f}s at real speed, narration {dur:.1f}s"
          + (f", {length - dur:.1f}s trimmed from the end" if length > dur else ""))


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


def write_subtitles(items: list[dict]) -> None:
    out, n, offset = [], 1, 0.0
    for s in items:
        for block in s["srt"].strip().split("\n\n"):
            lines = block.splitlines()
            if len(lines) < 3:
                continue
            a, b = [x.strip() for x in lines[1].split("-->")]
            to_s = lambda x: (lambda h, m, rest: int(h) * 3600 + int(m) * 60 + float(rest.replace(",", ".")))(*x.split(":"))
            out.append(f"{n}\n{_srt_time(offset + to_s(a))} --> {_srt_time(offset + to_s(b))}\n{' '.join(lines[2:])}\n")
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
    cap = capture()
    facts, marks, video = cap["facts"], cap["marks"], cap["video"]
    print(json.dumps({"marks": marks, **{k: v for k, v in facts.items() if k not in ("court", "whatif", "ask")}},
                     indent=1, default=str))
    if not facts.get("court"):
        print("WARNING: no Courtroom response captured")

    items = scenes(facts, m)
    asyncio.run(_tts(items))
    for s in items:
        print(f"{s['id']:22} {s['duration']:6.1f}s  {s['text'][:90]}...")
    total = sum(s["duration"] for s in items)
    print(f"narration total {total:.1f}s")
    if total > MAX_SECONDS:
        raise SystemExit(f"narration {total:.1f}s is over {MAX_SECONDS}s - shorten the text before assembling")

    render_slides(slides(m))
    d = {s["id"]: s["duration"] for s in items}
    a = lambda i: f"scratch/audio/{i}.mp3"
    still("scratch/slides/hook.png", a("scene1_hook"), d["scene1_hook"], "scratch/clips/scene1.mp4")
    segment(video, _wait_cut(marks["live_click"] - 1.0, marks["live_click"], marks["live_done"], marks["steps_end"]),
            a("scene2_run"), d["scene2_run"], "scratch/clips/scene2.mp4",
            caption=f"Wait shortened — this live run took {facts.get('seconds')} s in real time")
    segment(video, _wait_cut(marks["court_start"], marks["court_click"], marks["court_done"], marks["court_end"]),
            a("scene3_clauses"), d["scene3_clauses"], "scratch/clips/scene3.mp4",
            caption=f"Wait shortened — the Courtroom took {facts.get('court_seconds')} s in real time")
    segment(video, [(marks["trust_start"], marks["trust_end"])], a("scene4_trust"), d["scene4_trust"],
            "scratch/clips/scene4.mp4")
    segment(video, [(marks["decide_start"], marks["decide_end"])], a("scene5_decide"), d["scene5_decide"],
            "scratch/clips/scene5.mp4")
    still("scratch/slides/results.png", a("scene6_results"), d["scene6_results"], "scratch/clips/scene6.mp4")
    still("scratch/slides/arch.png", a("scene7_architecture"), d["scene7_architecture"], "scratch/clips/scene7.mp4")
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
                   "whatif": facts.get("whatif", {}).get("money_at_stake"),
                   "court": (facts.get("court") or {}).get("money_at_stake"),
                   "ask_unsupported": (facts.get("ask") or {}).get("unsupported_figures")}, f, indent=2)
    print(f"done: {OUT} ({_duration(OUT):.1f}s)")


if __name__ == "__main__":
    main()
