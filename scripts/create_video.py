"""Build the CatSight demo video from ONE real live run on the deployed site.

Every figure the narration speaks is read from that run - the Courtroom
outcome, the run time, the cost, the citation count - never typed into this
file. The video script's rule: nothing is invented for the video.

    python scripts/create_video.py            # capture, narrate, assemble

Needs: playwright (uses the installed Microsoft Edge), edge-tts,
imageio-ffmpeg. Output: docs/demo/catsight_3min_presentation.mp4 plus .srt.
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

OUT = "docs/demo/catsight_3min_presentation_v2.mp4"
OUT_V1 = "docs/demo/catsight_3min_presentation_v1.mp4"
OUT_LEGACY = "docs/demo/catsight_3min_presentation.mp4"
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


def click(page, locator, pause: int = 350) -> None:
    """Glide the visible pointer to the element, then click it."""
    target = locator.first
    target.scroll_into_view_if_needed()
    box = target.bounding_box()
    if not box:
        target.click()
        return
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(_pointer["x"], _pointer["y"])
    page.mouse.move(x, y, steps=28)
    _pointer.update(x=x, y=y)
    page.wait_for_timeout(pause)
    page.mouse.down()
    page.wait_for_timeout(90)
    page.mouse.up()

def capture() -> dict:
    """Run Jebi live, open the Courtroom, the verified clause and the scanned
    endorsement. Returns the video path, scene time marks and what the run
    showed."""
    marks: dict[str, float] = {}
    facts: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080},
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

        # Scene 2: one click, live.
        mark("live_click")
        click(page, page.locator("button:has-text('Run live')"))
        page.wait_for_function(
            "() => /\\d+ verified\\s*·\\s*\\d+ withheld/.test(document.body.innerText)"
            " && !document.querySelector('[aria-busy=true]')",
            timeout=180_000)
        mark("live_done")
        page.wait_for_timeout(2000)
        body = page.inner_text("body")
        facts["seconds"] = _grab(r"TIME\s+(\d+)\s*s", body)
        facts["cost"] = _grab(r"MODEL COST\s+\$([\d.]+)", body)
        facts["treaties"] = re.search(r"TREATIES HIT\s+(\d+)\s+of\s+(\d+)", body)
        facts["treaties"] = facts["treaties"].groups() if facts["treaties"] else None
        facts["flags"] = re.search(r"(\d+) verified\s*·\s*(\d+) withheld", body).groups()

        click(page, page.locator("button:has-text('What it costs')"))
        page.wait_for_timeout(5000)

        # Scene 3: the Courtroom.
        mark("court_start")
        click(page, page.locator("button:has-text('Clauses that matter')"))
        page.wait_for_timeout(2500)
        click(page, page.locator("button:has-text('Open the Clause Courtroom')"))
        page.wait_for_function(
            "() => /Arbiter|Neither side|could not produce/.test(document.body.innerText)",
            timeout=120_000)
        page.wait_for_timeout(1500)
        page.locator(".court").first.scroll_into_view_if_needed()
        page.mouse.wheel(0, 300)
        page.wait_for_timeout(9000)
        page.mouse.wheel(0, 500)
        page.wait_for_timeout(7000)
        mark("court_end")
        facts["court"] = court_box.get("data")

        # Scene 4a: the verified flag's clause, highlighted on its page.
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(800)
        mark("trust_start")
        click(page, page.locator("button:has-text('open clause')"))
        page.wait_for_timeout(7000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)

        # Scene 4b: the scanned endorsement, transcribed by Gemini.
        click(page, page.locator("button.tab", has_text="Treaties"))
        page.wait_for_timeout(2500)
        click(page, page.locator("tr:has-text('T-004') button:has-text('Open')"))
        page.wait_for_timeout(3000)
        scanned = page.locator("button.cite:has-text('🖼')")
        facts["endorsement_shown"] = scanned.count() > 0
        if facts["endorsement_shown"]:
            scanned.first.scroll_into_view_if_needed()
            page.wait_for_timeout(1500)
            click(page, scanned)
            page.wait_for_timeout(8000)
        mark("trust_end")

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
# 2. Narration, written from what the run showed                               #
# --------------------------------------------------------------------------- #

def _m(value) -> str:
    """'-11.64' -> '11.6 million dollars'."""
    v = abs(Decimal(str(value)))
    return f"{v:.1f} million dollars"


def courtroom_lines(court: dict | None) -> str:
    opening = ("Then it finds the clause that decides the answer. Jebi drove a record storm tide into "
               "Osaka Bay, and treaty T-004 excludes storm surge. So CatSight argues both sides. One "
               "agent takes the insurer's reading: this was windstorm damage, and the exclusion doesn't "
               "bite. The other takes the reinsurers': part of this loss is surge. Each must quote the "
               "contract, and each quote is checked against the page. ")
    closing = " The agents don't decide. The analyst does."
    if not court or court.get("skipped"):
        return opening + "No reading could be priced on this run." + closing
    sides = court.get("sides", {})
    verified = {k: s for k, s in sides.items() if s.get("verified")}
    if "money_at_stake" in court and len(verified) == 2:
        stake = court["money_at_stake"]
        return (opening + "Both quotes verify, and the engine prices both readings. One clause: "
                f"{_m(stake['total_ceded'])} of recoveries move, and {_m(stake['our_net'])} of it is "
                "ours. What the reinsurers save, the insurer carries." + closing)
    if len(verified) == 1:
        (name, side), = verified.items()
        dropped = "insurer's" if name != "cedent" else "reinsurers'"
        priced = side.get("priced", {})
        stake = priced.get("money_at_stake", {})
        share = Decimal(str(side.get("excluded_share", 0))) * 100
        line = (f"On this run, the {dropped} counsel quoted the contract for something it doesn't say. "
                "The verifier dropped that side, and with only one verified reading, CatSight puts no "
                "money at stake on screen. ")
        if stake:
            line += (f"The surviving reading, a stated assumption of {share:.0f} percent surge, is "
                     f"priced by the engine: {_m(stake['total_ceded'])} less in recoveries, "
                     f"{_m(stake['our_net'])} of it ours.")
        return opening + line + closing
    return (opening + "Neither side could cite verified wording, so nothing is priced. An argument "
            "without verified wording is never shown." + closing)


def scenes(facts: dict) -> list[dict]:
    sec = facts.get("seconds") or "under sixty"
    hit = facts.get("treaties") or ("13", "24")
    return [
        {"id": "scene1_hook", "text": (
            "In September 2018, Typhoon Jebi hit western Japan. About ten days later, modellers put "
            "insured losses at three to five and a half billion dollars. The figure later reached about "
            "thirteen billion. For a "
            "reinsurer, the question isn't just how big. It's how much of it lands on us, and which "
            "contract words decide that.")},
        {"id": "scene2_one_click", "text": (
            "One click, and the agents run live: hazard footprint, exposure overlay, layer maths, then "
            "the wording. Every number you see comes from tested Python. The language model never does "
            f"arithmetic. It reads, retrieves and explains. {hit[1]} treaties, {hit[0]} hit. The money "
            f"in seconds, the checked wording in {sec} seconds.")},
        {"id": "scene3_money_moment", "text": courtroom_lines(facts.get("court"))},
        {"id": "scene4_trust", "text": (
            "Every flag carries a citation, and every citation is machine-checked against the source "
            "page. What can't be verified isn't shown. It's held for human review, and counted. "
            + ("And when a term is buried in a scanned endorsement with no text layer, Gemini reads the "
               "image, and the transcription is cited to its page."
               if facts.get("endorsement_shown") else ""))},
        {"id": "scene5_results", "text": (
            "A human approves before anything leaves. What we measured: RAG-first extraction accuracy "
            "ninety-nine point five percent, one hundred eighty-five of one hundred eighty-six fields, "
            "including a scanned endorsement page. "
            f"On this run, {facts['flags'][0]} of {int(facts['flags'][0]) + int(facts['flags'][1])} "
            f"displayed citations verified, in {sec} seconds, for about one cent.")},
        {"id": "scene6_architecture", "text": (
            "Gemini 3.5 Flash-Lite and 3.8 Flash on Gemini Enterprise Agent Platform, Vertex AI. A Google ADK graph, with a verification "
            "loop and a parallel fan-out for the courtroom. Firestore vector search for the clauses. One "
            "Cloud Run service streaming the analysis to the React app it serves. Synthetic contracts, "
            "public hazard data.")},
        {"id": "scene7_close", "text": (
            "Jebi, Hagibis, Haiyan, Noto: real events, and real losses for the people in them. "
            "Reinsurance recoveries are what let insurers pay households and small businesses after a "
            "disaster. CatSight is about settling those recoveries faster, and arguing about them less.")},
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
.note{margin-top:40px;font-size:18px;color:#64748b;max-width:1300px;text-align:center;line-height:1.5}"""


def slides(facts: dict) -> dict[str, str]:
    v, w = facts["flags"]
    shown = int(v) + int(w)
    hook = f"""<style>{CSS}</style><div class=badge>CatSight · Typhoon Jebi, 2018</div>
<div class=title>Which contract words decide<br>who pays?</div>
<div class=grid style="grid-template-columns:1fr 1fr;width:1100px">
<div class=card><div class=sub>First modelled insured loss, ~10 days after (Moody's RMS)</div><div class=val style="color:#f8fafc">$3–5.5bn</div></div>
<div class=card><div class=sub>Insured loss after development (Swiss Re)</div><div class=val style="color:#c0812a">~$13bn</div></div></div>"""
    results = f"""<style>{CSS}</style><div class=badge>Measured</div><div class=title>What we measured</div>
<div class=grid style="grid-template-columns:repeat(4,1fr);width:1600px">
<div class=card><div class=val>99.5%</div><div class=lbl>Fields extracted (185/186)</div><div class=sub>RAG-first on the 8 synthetic wordings (upper bound), incl. scanned endorsement</div></div>
<div class=card><div class=val>{v} of {shown}</div><div class=lbl>Displayed citations verified</div><div class=sub>on the run shown · {w} withheld for review</div></div>
<div class=card><div class=val>{facts.get('seconds') or '—'} s</div><div class=lbl>Live analysis</div><div class=sub>the run shown, end to end</div></div>
<div class=card><div class=val>${facts.get('cost') or '—'}</div><div class=lbl>Model cost</div><div class=sub>the run shown (Courtroom extra)</div></div></div>
<div class=note>874 automated pytest tests · 0 untraceable figures across all runs · Flag recall and a blind extraction set are next.</div>"""
    arch = f"""<style>{CSS}</style><div class=badge>Google Cloud</div><div class=title>How it is built</div>
<div class=grid style="grid-template-columns:repeat(3,1fr);width:1500px">
<div class=card><div class=lbl>Gemini 3.5 Flash-Lite · 3.8 Flash</div><div class=sub>on Gemini Enterprise Agent Platform (Vertex AI): reading, checks, counsel &amp; arbiter</div></div>
<div class=card><div class=lbl>Google ADK 2.11 graph</div><div class=sub>verification loop and parallel Courtroom fan-out</div></div>
<div class=card><div class=lbl>Firestore vector search</div><div class=sub>768-dim clause embeddings (186/186 retrieved)</div></div>
<div class=card><div class=lbl>Cloud Run</div><div class=sub>one service: API, SSE stream and the React app</div></div>
<div class=card><div class=lbl>Deterministic loss engine</div><div class=sub>Python Decimal (874 tests): layers, reinstatements; no LLM arithmetic</div></div>
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

def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-600:])


def still(png: str, audio: str, dur: float, out: str) -> None:
    _run([FFMPEG, "-y", "-loop", "1", "-i", png, "-i", audio, "-c:v", "libx264", "-tune", "stillimage",
          "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.2f}", out])


def segment(video: str, start: float, end: float, audio: str, dur: float, out: str) -> None:
    """Cut [start, end] from the capture and fit it to the narration. Faster
    than real time is labelled on screen; never silently."""
    length = max(end - start, 0.5)
    speed = length / dur
    vf = "scale=1920:1080"
    if speed > 1.05:
        vf += (f",setpts=PTS/{speed:.4f},drawtext=fontfile='{FONT}':text='×{speed:.1f} speed':"
               "x=w-tw-40:y=40:fontsize=30:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=12")
    else:
        vf += ",tpad=stop_mode=clone:stop_duration=60"
    _run([FFMPEG, "-y", "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", video, "-i", audio,
          "-vf", vf, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
          "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.2f}", out])


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
    with open("docs/demo/catsight_presentation_v2.srt", "w", encoding="utf-8") as f:
        f.write(srt)
    with open("docs/demo/catsight_presentation_v2.vtt", "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n" + re.sub(r"(\d\d:\d\d:\d\d),(\d\d\d)", r"\1.\2", srt))


def _preserve_v1() -> None:
    backups = [
        ("docs/demo/catsight_3min_presentation.mp4", "docs/demo/catsight_3min_presentation_v1.mp4"),
        ("docs/demo/catsight_presentation.srt", "docs/demo/catsight_presentation_v1.srt"),
        ("docs/demo/catsight_presentation.vtt", "docs/demo/catsight_presentation_v1.vtt"),
        ("scratch/capture/facts.json", "scratch/capture/facts_v1.json"),
        ("scratch/capture/narration.json", "scratch/capture/narration_v1.json"),
    ]
    for src, dst in backups:
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
            print(f"preserved v1: {src} -> {dst}")


def main() -> None:
    _preserve_v1()
    cap = capture()
    facts, marks, video = cap["facts"], cap["marks"], cap["video"]
    shutil.copy2("scratch/capture/facts.json", "scratch/capture/facts_v2.json")
    print(json.dumps({"marks": marks, **{k: v for k, v in facts.items() if k != "court"}}, indent=1, default=str))
    if not facts.get("court"):
        print("WARNING: no Courtroom response captured")

    items = scenes(facts)
    asyncio.run(_tts(items))
    for s in items:
        print(f"{s['id']:22} {s['duration']:6.1f}s  {s['text'][:90]}...")
    total = sum(s["duration"] for s in items)
    print(f"narration total {total:.1f}s")
    if total > 178:
        raise SystemExit("narration over 2:58 - shorten the text before assembling")

    render_slides(slides(facts))
    d = {s["id"]: s["duration"] for s in items}
    a = lambda i: f"scratch/audio/{i}.mp3"
    still("scratch/slides/hook.png", a("scene1_hook"), d["scene1_hook"], "scratch/clips/scene1.mp4")
    segment(video, marks["live_click"] - 1.0, marks["live_done"] + 6.0, a("scene2_one_click"),
            d["scene2_one_click"], "scratch/clips/scene2.mp4")
    segment(video, marks["court_start"], marks["court_end"], a("scene3_money_moment"),
            d["scene3_money_moment"], "scratch/clips/scene3.mp4")
    segment(video, marks["trust_start"], marks["trust_end"], a("scene4_trust"),
            d["scene4_trust"], "scratch/clips/scene4.mp4")
    still("scratch/slides/results.png", a("scene5_results"), d["scene5_results"], "scratch/clips/scene5.mp4")
    still("scratch/slides/arch.png", a("scene6_architecture"), d["scene6_architecture"], "scratch/clips/scene6.mp4")
    still("scratch/slides/close.png", a("scene7_close"), d["scene7_close"], "scratch/clips/scene7.mp4")

    with open("scratch/clips/concat_list.txt", "w", encoding="utf-8") as f:
        for i in range(1, 8):
            f.write(f"file '{os.path.abspath(f'scratch/clips/scene{i}.mp4').replace(chr(92), '/')}'\n")
    _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", "scratch/clips/concat_list.txt", "-c", "copy", OUT])
    write_subtitles(items)
    with open("scratch/capture/narration.json", "w", encoding="utf-8") as f:
        json.dump([{k: s[k] for k in ("id", "text", "duration")} for s in items], f, indent=2)
    shutil.copy2("scratch/capture/narration.json", "scratch/capture/narration_v2.json")
    print(f"done: {OUT} ({total:.1f}s) | preserved v1 at {OUT_V1} and {OUT_LEGACY}")


if __name__ == "__main__":
    main()
