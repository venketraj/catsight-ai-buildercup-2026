"""Build the 12-slide submission deck (PDF) from HTML.

    python scripts/build_deck.py      # -> docs/CatSight_deck.pdf

Every figure is either measured (docs/RESULTS.md), sourced (named on the
slide) or labelled an estimate. Screenshots are frames of the live service
recorded by scripts/create_video.py (scratch/frames/, git-ignored).
Needs playwright and the installed Microsoft Edge.
"""

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "scratch" / "frames"
OUT = ROOT / "docs" / "CatSight_deck.pdf"
LIVE = "https://catsight-api-tzvix6sejq-uc.a.run.app"
REPO = os.environ.get("CATSIGHT_REPO", "https://github.com/venketraj/catsight-ai-buildercup-2026")
DISCLAIMER = "Indicative first view on synthetic data. Not a catastrophe-model output. Not underwriting or claims advice."


def img(name: str) -> str:
    return (FRAMES / name).as_uri()


CSS = """
@page { size: 1920px 1080px; margin: 0 }
* { box-sizing: border-box }
body { margin: 0; font-family: 'Segoe UI', Roboto, sans-serif; color: #e8edf5; background: #0b1120 }
.s { width: 1920px; height: 1080px; padding: 80px 110px; position: relative; page-break-after: always;
     background: radial-gradient(1200px 600px at 85% -10%, rgba(31,169,156,.10), transparent), #0b1120 }
.kicker { color: #1fa99c; font-weight: 700; letter-spacing: 3px; text-transform: uppercase; font-size: 20px }
h1 { font-size: 62px; margin: 14px 0 34px; line-height: 1.1 }
h2 { font-size: 30px; color: #94a3b8; font-weight: 500; margin: -18px 0 34px }
p, li { font-size: 27px; line-height: 1.5; color: #cbd5e1 }
li { margin-bottom: 10px }
b, strong { color: #f8fafc }
table { border-collapse: collapse; width: 100%; font-size: 24px }
th { text-align: left; color: #94a3b8; font-weight: 600; border-bottom: 2px solid #334155; padding: 12px 14px }
td { border-bottom: 1px solid #1e293b; padding: 12px 14px; color: #cbd5e1; vertical-align: top }
td b { color: #f8fafc }
.foot { position: absolute; bottom: 34px; left: 110px; right: 110px; font-size: 17px; color: #64748b;
        display: flex; justify-content: space-between }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 50px; align-items: start }
.shot { width: 100%; border-radius: 12px; border: 1px solid #334155; box-shadow: 0 20px 50px rgba(0,0,0,.5) }
.card { background: #111a2e; border: 1px solid #263248; border-radius: 16px; padding: 26px 30px }
.big { font-size: 64px; font-weight: 800; color: #1fa99c; line-height: 1.1 }
.lbl { font-size: 22px; color: #94a3b8; margin-top: 6px }
.tag { display: inline-block; font-size: 17px; padding: 3px 12px; border-radius: 999px; border: 1px solid #475569; color: #94a3b8; margin-left: 8px; vertical-align: middle }
.pos { color: #e0a458 } .neg { color: #1fa99c }
.box { border: 2px solid #334155; border-radius: 14px; padding: 18px 22px; background: #111a2e; font-size: 23px; color: #cbd5e1 }
.box b { display: block; font-size: 25px; margin-bottom: 4px }
.arrow { text-align: center; color: #475569; font-size: 30px; line-height: 1 }
"""


def foot(n: int) -> str:
    return f'<div class="foot"><span>CatSight · Team Techno Crackers · Google Cloud AI Builder Cup 2026</span><span>{n} / 12</span></div>'


def slides() -> list[str]:
    s = []
    s.append(f"""
<div class=kicker>BFSI · Intelligent Risk, Fraud &amp; Financial Experiences</div>
<h1 style="font-size:110px;margin-top:150px">CatSight</h1>
<h2 style="font-size:40px;margin:0 0 50px">Event-aware contract intelligence for catastrophe reinsurance</h2>
<p style="font-size:32px;max-width:1500px">When a typhoon or earthquake hits, CatSight tells a reinsurer <b>which treaties respond, what each layer pays,
and which contract clause could change that answer</b> — with every quote machine-verified against the page.</p>
<p style="font-size:24px;margin-top:60px">Live: <b>{LIVE}</b><br>Code: <b>{REPO}</b></p>
<p style="font-size:18px;color:#64748b">{DISCLAIMER}</p>""")
    s.append("""
<div class=kicker>The problem</div><h1>The morning after a typhoon</h1>
<div class=grid2><div>
<p>A catastrophe analyst at a reinsurer needs a <b>defensible first view of their own exposure</b> — by treaty, by layer — before industry figures exist.</p>
<p>The first number matters, it is hard, and it moves. <b>Typhoon Jebi, 2018:</b></p>
<ul><li>857,284 claims, ¥1,067.8bn paid — the largest ever for a Japanese typhoon <span class=tag>GIAJ</span></li>
<li>First modelled range $3–5.5bn, about 10 days after landfall <span class=tag>Moody's RMS</span></li>
<li>Insured loss later about $13bn — roughly 3× the early figure <span class=tag>Swiss Re</span></li></ul>
</div><div class=card>
<table><tr><th>Industry figure</th><th>Arrives</th></tr>
<tr><td>Modeller event response</td><td><b>4–20 days</b></td></tr>
<tr><td>PERILS (Japan typhoon)</td><td><b>6 weeks</b></td></tr>
<tr><td>Verisk PCS Japan</td><td><b>up to 90 days</b></td></tr>
<tr><td><b>CatSight, on the reinsurer's own book</b></td><td><b class=neg>seconds</b></td></tr></table>
<p style="font-size:18px;color:#64748b;margin-top:16px">Sources: providers' published event-response releases. Industry figures describe the market, not one reinsurer's treaties.</p>
</div></div>""")
    s.append("""
<div class=kicker>Why it is hard today</div><h1>The work is manual, and the wording is where it breaks</h1>
<table><tr><th>Step</th><th>Today</th><th>Pain</th></tr>
<tr><td>Event intelligence</td><td>Licensed modeller feeds</td><td>Expensive; describes the market, not your contracts</td></tr>
<tr><td>Exposure overlay</td><td>Cat-modelling and exposure tools</td><td>Specialist time, batch runs under pressure</td></tr>
<tr><td>Contract application</td><td>Spreadsheets</td><td>Error-prone when rushed</td></tr>
<tr><td><b>Wording check</b></td><td>Underwriting, claims and legal re-read PDFs</td><td><b>Slow; endorsements get missed; disputes surface months later</b></td></tr>
<tr><td>Reporting</td><td>Flash estimates to the board</td><td>Must be fast and defensible</td></tr></table>
<p style="margin-top:34px"><b>48%</b> of insurers do not license catastrophe models, and <b>nearly 60%</b> run cat teams of five or fewer <span class=tag>Aon 2025</span>.
Treaty structures "might only exist in their capital model, a homegrown tool, or even in a spreadsheet" <span class=tag>Moody's</span>.</p>""")
    s.append("""
<div class=kicker>What exists vs what is new</div><h1>CatSight is the join</h1>
<table><tr><th>Category</th><th>Examples</th><th>Does well</th><th>Stops at</th></tr>
<tr><td>Cat-model event response</td><td>Moody's RMS, Verisk</td><td>Hazard footprints, modelled loss, coded treaty terms</td><td>Your treaty <b>wording</b></td></tr>
<tr><td>AI contract review</td><td>Document-AI platforms</td><td>Clause extraction, citations</td><td>The <b>event</b> and the layer maths</td></tr>
<tr><td>Generic LLM over PDFs</td><td>Chat with a contract</td><td>Fast answers</td><td><b>Verifiable numbers</b>, audit trail</td></tr>
<tr><td><b>CatSight</b></td><td></td><td colspan=2><b class=neg>event × exposure × layers × wording — with verified citations and tested maths</b></td></tr></table>
<p style="margin-top:34px"><b>Complementary, not a replacement.</b> CatSight is not a cat model: a licensed footprint can replace the public hazard data behind the same interface. To our knowledge, event-response products stop at the modelled loss and AI wording tools stop at the document.</p>""")
    s.append("""
<div class=kicker>Architecture</div><h1>One Cloud Run service, two ADK graphs</h1>
<div style="display:grid;grid-template-columns:1.05fr 1fr;gap:50px">
<div>
<div class=box><b>Browser</b>React UI, served by the same service · SSE stream</div><div class=arrow>▼</div>
<div class=box style="border-color:#1fa99c"><b>Cloud Run — FastAPI</b>ADK 2.11 analysis graph · Courtroom graph · deterministic loss engine · guards</div><div class=arrow>▼</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px">
<div class=box><b>Vertex AI</b>Gemini 3.5 Flash-Lite · 3.8 Flash · embedding-001</div>
<div class=box><b>Firestore</b>treaty book · 252 clause vectors · runs</div>
<div class=box><b>Cloud Storage</b>treaty PDFs</div></div>
<p style="font-size:21px;margin-top:20px">Cloud Logging · Trace · Monitoring · Cloud Build · dedicated service account, no API keys</p>
</div><div class=card style="font-size:22px">
<p style="font-size:23px"><b>Analysis</b><br>event_intel → exposure_analyst <span class=tag>no model</span> → wording_checker <span class=tag>vector search</span> → verifier <span class=tag>loop</span> → reporter</p>
<p style="font-size:23px"><b>Clause Courtroom</b><br>brief → cedent_counsel ∥ reinsurer_counsel <span class=tag>parallel, blind</span> → quote check → price <span class=tag>engine</span> → arbiter <span class=tag>does not decide</span></p>
<p style="font-size:23px"><b>Gemini reads. Tested code calculates.</b> Every figure is deterministic Python; every figure in AI-written text is checked against it.</p>
</div></div>""")
    s.append(f"""
<div class=kicker>The product — live</div><h1>Agents stream, the money lands first</h1>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:36px">
<div><img class=shot src="{img('cap_6.png')}"><p style="font-size:21px">Agents working live: retrieval per treaty, then verification</p></div>
<div><img class=shot src="{img('cap_12.png')}"><p style="font-size:21px">Who pays what: 13 of 24 treaties respond; insurers, reinsurers and our net</p></div>
</div>""")
    s.append(f"""
<div class=kicker>The money moment — one clause, one number</div><h1>Jebi, treaty T-004: the storm-surge exclusion</h1>
<div style="display:grid;grid-template-columns:1fr 1.1fr;gap:44px">
<div><p>Jebi drove a <b>record 329 cm tide</b> into Osaka Bay. T-004 (p. 2, cl. 8, verified) excludes storm surge.</p>
<p>Two AI counsel argue in parallel. Each quote is checked; each reading is <b>priced by the engine</b>. The surge share is a stated assumption — no data separates wind from water.</p>
<table><tr><th>Recorded live run</th><th>Move</th></tr>
<tr><td>Total ceded (20% surge share)</td><td><b class=neg>−$11.64M</b></td></tr>
<tr><td>Insurer's net cost</td><td><b class=pos>+$10.31M</b></td></tr>
<tr><td>All reinsurers pay</td><td><b class=neg>−$10.31M</b></td></tr>
<tr><td><b>Our net (Lion Re)</b></td><td><b class=neg>−$1.34M</b></td></tr></table>
<p style="font-size:21px;margin-top:14px">What the reinsurers save, the insurer carries. Counsel choose their share each run, so figures vary by run. Issue-spotting, not legal advice — the analyst decides.</p></div>
<div><img class=shot src="{img('cap_45.png')}"></div></div>""")
    s.append(f"""
<div class=kicker>Trust architecture</div><h1>Why a finance team can let an LLM near a loss report</h1>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:44px"><ul>
<li><b>The model never calculates.</b> Every figure from tested <code>Decimal</code> Python — 869 tests.</li>
<li><b>Every wording claim is cited</b> to treaty, page and clause.</li>
<li><b>Every citation is machine-checked</b>: exact quote match, then a model support check; one revision, then withheld.</li>
<li><b>Withheld, visibly</b>: "n of n verified · k withheld", with reasons.</li>
<li><b>Scanned pages</b> are transcribed by Gemini and badged differently.</li>
<li><b>A human decides.</b> The arbiter summarises; the analyst records a position.</li></ul>
<div><img class=shot src="{img('cap_72.png')}"><p style="font-size:21px">The endorsement detective: Gemini reads a scanned page with no text layer — 168 hours replaces the body's 72</p></div></div>""")
    s.append("""
<div class=kicker>Results — measured</div><h1>What we measured, and what we did not</h1>
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:24px;margin-bottom:34px">
<div class=card><div class=big>0.7 s</div><div class=lbl>money on screen (p50, 5 live runs)</div></div>
<div class=card><div class=big>9.8 s</div><div class=lbl>complete with verified flags (p50; 8–18 s)</div></div>
<div class=card><div class=big>$0.010</div><div class=lbl>model cost per analysis (p50)</div></div>
<div class=card><div class=big>0</div><div class=lbl>report figures not traceable to the engine</div></div></div>
<table><tr><th>Measure</th><th>Result</th><th>Honest caveat</th></tr>
<tr><td>Loss engine vs hand-checked worked example</td><td><b>exact</b></td><td>unit-tested on every figure</td></tr>
<tr><td>Treaty-term extraction</td><td><b>99.5%</b> (185/186)</td><td>upper bound: prompts developed on these 8 wordings; no blind set yet</td></tr>
<tr><td>Citations</td><td><b>186/188</b> cited · <b>185/186</b> check out</td><td>per-field audit published</td></tr>
<tr><td>Storm-surge flag on Jebi</td><td>raised 8/8 · verified 7/8</td><td>severity varies (HIGH 4/8); the Courtroom now argues HIGH or MEDIUM</td></tr>
<tr><td>Not measured</td><td colspan=2>timed manual baseline · usability · flag recall over a labelled corpus · blind extraction set</td></tr></table>""")
    s.append("""
<div class=kicker>Built on Google Cloud</div><h1>Every service, and why</h1>
<table><tr><th>Service</th><th>Role</th></tr>
<tr><td><b>Gemini 3.5 Flash-Lite</b> on Vertex AI (global)</td><td>Wording checks, counsel, reports — cheap generation</td></tr>
<tr><td><b>Gemini 3.8 Flash</b></td><td>Verification and the arbiter — stronger judging</td></tr>
<tr><td><b>Google ADK 2.11</b> graph <code>Workflow</code></td><td>A verification loop and a parallel Courtroom fan-out — not a linear chain</td></tr>
<tr><td><b>Firestore</b> + vector search, <code>gemini-embedding-001</code> 768-d</td><td>Treaty book, 252 clause vectors with a treaty pre-filter, completed runs</td></tr>
<tr><td><b>Cloud Run</b></td><td>One service: API, SSE stream and UI; max 3 instances, per-visitor and daily caps</td></tr>
<tr><td><b>Cloud Logging · Trace · Monitoring</b></td><td>Structured guardrail events; per-agent ADK spans; a dashboard of latency, cost, citations and Courtroom outcomes</td></tr>
<tr><td><b>Cloud Storage · Cloud Build</b></td><td>Treaty PDFs; source deploys</td></tr></table>""")
    s.append("""
<div class=kicker>Impact and scale</div><h1>Faster, less-disputed recoveries</h1>
<div class=grid2><div>
<p>Reinsurance recoveries are what let insurers pay households and small businesses after a disaster.</p>
<ul><li><b>Effort (estimate):</b> 30–60 analyst-hours per event → 3.5–8 hours of review; about 165–675 hours a year for a mid-size reinsurer. A timed baseline is next.</li>
<li><b>Wording risk:</b> on the worked example, one hours clause moves a layer by up to 80%.</li>
<li><b>Market:</b> Singapore writes S$27.6bn of reinsurance premium and hosts 16 of the top 25 reinsurers' regional hubs; 91% of APAC's 2023 economic catastrophe losses were uninsured <span class=tag>MAS</span>.</li></ul>
</div><div class=card><p><b>Path to production</b></p><ul style="font-size:24px">
<li>Licensed cat-model footprints behind the hazard interface</li>
<li>Live event intake from USGS / GDACS alerts</li>
<li>Authenticated upload of real treaty packs; BigQuery exposure</li>
<li>Multi-tenancy; A2A / MCP so a broker's agent can call CatSight</li>
<li>Loss development as advices arrive</li></ul></div></div>
<p style="font-size:21px;color:#94a3b8">Decision support, not a payout engine.</p>""")
    s.append(f"""
<div class=kicker>Team, ask, next steps</div><h1>Techno Crackers</h1>
<p>A two-person team: reinsurance domain knowledge and engineering, building with Gemini and Google ADK.</p>
<p><b>Next:</b> pilot on an anonymised treaty pack · a timed manual baseline · a blind extraction set · pre-landfall mode on forecast tracks.</p>
<p style="margin-top:50px;font-size:26px">Live: <b>{LIVE}</b><br>Code: <b>{REPO}</b></p>
<p style="font-size:20px;color:#94a3b8;margin-top:50px">{DISCLAIMER} Issue-spotting only — not legal advice.<br>
Jebi, Hagibis, Haiyan and Noto were real events in which people died. Synthetic insurers and treaties; public hazard data: NOAA IBTrACS, USGS ShakeMap, Natural Earth.</p>""")
    return s


def main() -> None:
    missing = [n for n in ("cap_6.png", "cap_12.png", "cap_45.png", "cap_72.png") if not (FRAMES / n).exists()]
    if missing:
        raise SystemExit(f"missing screenshots in {FRAMES}: {missing} - run scripts/create_video.py first")
    body = "".join(f'<section class="s">{html}{foot(i)}</section>' for i, html in enumerate(slides(), 1))
    html_path = ROOT / "scratch" / "deck.html"
    html_path.write_text(f"<!doctype html><meta charset=utf-8><style>{CSS}</style>{body}", encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(html_path.as_uri(), wait_until="networkidle")
        page.pdf(path=str(OUT), width="1920px", height="1080px", print_background=True,
                 margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
        for i in (1, 7, 9):
            page.set_viewport_size({"width": 1920, "height": 1080})
            page.evaluate(f"window.scrollTo(0, {(i - 1) * 1080})")
            page.screenshot(path=str(ROOT / "scratch" / f"deck_{i}.png"))
        browser.close()
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
