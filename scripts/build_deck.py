"""Build the 14-slide submission deck (PDF) strictly using the official
Google Cloud AI Builder Cup Submission Template artwork, colors, typography,
and slide structure.

    python scripts/build_deck.py      # -> docs/CatSight_deck.pdf

Template assets (extracted directly from the official template PDF) live in
docs/template_assets/:
  - Image5.jpg  : Slide 1 top half banner (Google Cloud | H2S | AI Builder Cup + trophy)
  - Image9.jpg  : Content slides top header bar (Google Cloud | AI Builder Cup | H2S)
  - Image11.jpg : Final slide full-bleed "Thank you" artwork
"""

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "scratch" / "frames"
ASSETS = ROOT / "docs" / "template_assets"
OUT = ROOT / "docs" / "CatSight_deck.pdf"
LIVE = "https://catsight-api-342162443546.us-central1.run.app"
REPO = os.environ.get("CATSIGHT_REPO", "https://github.com/venketraj/catsight-ai-buildercup-2026")
VIDEO = os.environ.get(
    "CATSIGHT_VIDEO",
    "https://drive.google.com/file/d/14Yv-A-KtVksOgRxOxafZcEKFBUvFumQi/view?usp=sharing",
)
FOLDER = os.environ.get(
    "CATSIGHT_FOLDER",
    "https://drive.google.com/drive/folders/1X5cNQh4aMP-B1JIvIXyyxCL-4anxJhl4?usp=sharing",
)
DISCLAIMER = "Indicative first view on synthetic data. Not a catastrophe-model output. Not underwriting or claims advice. Issue-spotting only — not legal advice."


def img(name: str) -> str:
    return (FRAMES / name).as_uri()


def asset(name: str) -> str:
    return (ASSETS / name).as_uri()


def docimg(name: str) -> str:
    return (ROOT / "docs" / "images" / name).as_uri()


CSS = """
@page { size: 1920px 1080px; margin: 0 }
* { box-sizing: border-box }
body {
  margin: 0;
  font-family: 'Google Sans', 'Segoe UI', Roboto, Arial, sans-serif;
  color: #000000;
  background: #ffffff;
  -webkit-print-color-adjust: exact;
}
.s {
  width: 1920px;
  height: 1080px;
  position: relative;
  page-break-after: always;
  background: #ffffff;
  color: #000000;
  overflow: hidden;
}
.s-content {
  padding: 138px 98px 40px 98px;
  height: 1080px;
}
.hdr-bar {
  position: absolute;
  top: 0;
  left: 0;
  width: 1920px;
  height: 106.5px;
  object-fit: fill;
  display: block;
}
.btm-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 1920px;
  height: 15px;
  background: #000000;
}
.cover-banner {
  position: absolute;
  top: 0;
  left: 0;
  width: 1920px;
  height: 570px;
  object-fit: fill;
  display: block;
}
.cover-body {
  position: absolute;
  top: 570px;
  left: 0;
  right: 0;
  bottom: 15px;
  background: #ffffff;
  padding: 46px 65px 30px 65px;
}
.thankyou-full {
  position: absolute;
  top: 0;
  left: 0;
  width: 1920px;
  height: 1080px;
  object-fit: fill;
  display: block;
}
h1.tpl-title {
  font-size: 54px;
  font-weight: 500;
  color: #000000;
  margin: 0 0 24px 0;
  line-height: 1.15;
  letter-spacing: -0.3px;
}
h1.tpl-title-bold {
  font-size: 54px;
  font-weight: 600;
  color: #000000;
  margin: 0 0 24px 0;
  line-height: 1.15;
  letter-spacing: -0.3px;
}
p, li {
  font-size: 22px;
  line-height: 1.42;
  color: #000000;
  margin: 8px 0;
}
ul {
  margin: 8px 0 14px 0;
  padding-left: 34px;
}
li {
  margin-bottom: 6px;
}
b, strong {
  color: #000000;
  font-weight: 600;
}
code {
  background: #f1f3f4;
  border: 1px solid #dadce0;
  padding: 1px 7px;
  border-radius: 4px;
  font-family: Consolas, monospace;
  font-size: 19px;
  color: #000000;
}
table {
  border-collapse: collapse;
  width: 100%;
  font-size: 20px;
  color: #000000;
}
th {
  text-align: left;
  color: #000000;
  font-weight: 600;
  background: #f1f3f4;
  border-top: 2px solid #000000;
  border-bottom: 2px solid #000000;
  padding: 9px 12px;
}
td {
  border-bottom: 1px solid #dadce0;
  padding: 8px 12px;
  color: #000000;
  vertical-align: top;
}
.grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 36px;
  align-items: start;
}
.grid3 {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 26px;
  align-items: stretch;
}
.card {
  background: #f8f9fa;
  border: 1.5px solid #dadce0;
  border-radius: 10px;
  padding: 18px 22px;
}
.card-strong {
  background: #ffffff;
  border: 2px solid #000000;
  border-radius: 10px;
  padding: 18px 22px;
}
.big {
  font-size: 48px;
  font-weight: 700;
  color: #000000;
  line-height: 1.05;
}
.lbl {
  font-size: 18px;
  color: #3c4043;
  margin-top: 6px;
}
.tag {
  display: inline-block;
  font-size: 15px;
  padding: 1px 9px;
  border-radius: 999px;
  border: 1px solid #5f6368;
  color: #202124;
  background: #f1f3f4;
  margin-left: 6px;
  vertical-align: middle;
}
.box {
  border: 1.5px solid #000000;
  border-radius: 8px;
  padding: 11px 16px;
  background: #f8f9fa;
  font-size: 19px;
  color: #000000;
}
.box b {
  display: block;
  font-size: 20px;
  margin-bottom: 3px;
  color: #000000;
}
.arrow {
  text-align: center;
  color: #000000;
  font-size: 20px;
  line-height: 1;
  margin: 3px 0;
  font-weight: 700;
}
.shot {
  width: 100%;
  border-radius: 6px;
  border: 1.5px solid #000000;
  display: block;
}
.placeholder {
  background: #f8f9fa;
  border: 2px dashed #000000;
  color: #000000;
  padding: 8px 14px;
  border-radius: 6px;
  font-family: Consolas, monospace;
  font-size: 22px;
  font-weight: 600;
  display: inline-block;
}
.muted {
  color: #3c4043;
  font-size: 18px;
}
"""


def content_slide(title: str, body_html: str, bold_title: bool = False) -> str:
    h_cls = "tpl-title-bold" if bold_title else "tpl-title"
    return (
        f'<section class="s">'
        f'<img class="hdr-bar" src="{asset("Image9.jpg")}" alt="">'
        f'<div class="s-content"><h1 class="{h_cls}">{title}</h1>{body_html}</div>'
        f'<div class="btm-bar"></div>'
        f'</section>'
    )


def build_slides() -> list[str]:
    s: list[str] = []

    # Slide 1 — Template Page 1: Cover & Team Details
    s.append(f"""<section class="s">
  <img class="cover-banner" src="{asset('Image5.jpg')}" alt="">
  <div class="cover-body">
    <div style="font-size:66px;font-weight:600;color:#000000;margin-bottom:28px;line-height:1.1">Team Details</div>
    <div style="margin-left:98px;font-size:38px;line-height:1.65;color:#000000">
      <div><span style="display:inline-block;width:68px">a.</span>Team name: <b>Techno Crackers</b></div>
      <div><span style="display:inline-block;width:68px">b.</span>Team leader name: <b>Venket Raj S</b> <span style="font-size:24px;color:#3c4043">(Team: Venket Raj S · Malik Chandra Pandian · Arun Veerappan · Nagaraj — 4 working professionals in JAPAC, no students)</span></div>
      <div><span style="display:inline-block;width:68px">c.</span>Problem Statement: <b>BFSI: Intelligent Risk, Fraud &amp; Financial Experiences</b></div>
      <div style="margin-left:68px;font-size:25px;color:#202124;line-height:1.38;margin-top:4px">
        <b>CatSight — Event-aware contract intelligence for catastrophe reinsurance:</b> After a typhoon or earthquake, a reinsurer cannot say quickly or defensibly how much it owes because the answer depends on contract clauses buried in PDF treaty wordings.
      </div>
    </div>
  </div>
  <div class="btm-bar"></div>
</section>""")

    # Slide 2 — Template Page 3: Brief about the idea
    s.append(content_slide(
        "Brief about the idea",
        """<div class="grid2">
  <div>
    <p style="font-size:25px"><b>CatSight</b> tells a reinsurer, <b>about 11 seconds</b> (median) after a typhoon or earthquake, which contracts pay, how much, and which clauses could change that, with every quote checked against the contract page.</p>
    <p><b>The problem, in people terms</b></p>
    <ul>
      <li>After Typhoon Jebi, insurers paid <b>857,284 claims (¥1,067.8bn)</b> <span class="tag">GIAJ</span> to families and businesses.</li>
      <li>They recover much of it from <b>reinsurers</b>, under 50-page legal contracts called <b>treaties</b>.</li>
      <li>Working that out takes an estimated <b>30–60 analyst-hours</b>, and unclear clauses (wind vs. storm-surge flooding) lead to disputes. Slow payouts mean slower rebuilding.</li>
    </ul>
    <p><b>Real disasters, fictional contracts.</b> Real treaties are confidential, so we replay real public hazard data over <b>24 synthetic treaties for 8 fictional insurers</b> in Japan, the Philippines and Taiwan.</p>
  </div>
  <div class="card-strong">
    <table>
      <tr><th>Source</th><th>Time to arrive</th><th>What it gives you</th></tr>
      <tr><td>Catastrophe-model estimate</td><td><b>4–20 days</b></td><td>A market-wide range, not your contracts</td></tr>
      <tr><td>PERILS (Asia loss index)</td><td><b>6 weeks</b></td><td>An industry total, not treaty payouts</td></tr>
      <tr><td>Verisk PCS Japan</td><td><b>up to 90 days</b></td><td>Market index, events ≥ $2bn only</td></tr>
      <tr><td>Manual spreadsheet review</td><td><b>2–4 days</b></td><td>Slow; easy to miss endorsements</td></tr>
      <tr><td><b>CatSight</b></td><td><b>0.7 s money · ~11 s full check</b></td><td><b>Your treaties, priced, with checked quotes</b></td></tr>
    </table>
    <p class="muted" style="margin-top:14px">Hazard data: NOAA IBTrACS (typhoon tracks), USGS ShakeMap (earthquakes).</p>
  </div>
</div>"""
    ))

    # Slide 3 — Template Page 4: Opportunities
    s.append(content_slide(
        "Opportunities",
        """<div class="grid2" style="grid-template-columns: 1.15fr 0.85fr; gap: 32px; align-items: start;">
  <div>
    <ul style="font-size:24px;line-height:1.42;margin-top:0;padding-left:26px">
      <li style="margin-bottom:14px">
        <b>How is it different?</b>
        <div style="font-size:21px;margin-top:4px;color:#202124">
          • Catastrophe models estimate the loss but stop before your contracts. Document AI reads contracts but not the disaster. <b>CatSight joins the two, in seconds.</b><br>
          • Works <b>alongside</b> licensed models (Moody's RMS, Verisk): their footprint can plug in.
        </div>
      </li>
      <li style="margin-bottom:14px">
        <b>How does it solve the problem?</b>
        <div style="font-size:21px;margin-top:4px;color:#202124">
          • <b>Tested code does every calculation:</b> money on screen in <b>0.7 s</b> (median). The AI never does maths.<br>
          • <b>Gemini finds the clauses that matter;</b> every quote is matched word-for-word, then checked by a second model.
        </div>
      </li>
      <li style="margin-bottom:6px">
        <b>What's unique, and the social impact</b>
        <div style="font-size:21px;margin-top:4px;color:#202124">
          • <b>Clause Courtroom:</b> two AI lawyers argue an unclear clause; the engine prices both readings (<b>$11.6M</b> at stake on the recorded run).<br>
          • <b>Reads scanned, stamped endorsements</b> that have no text layer.<br>
          • <b>91%</b> of APAC disaster losses ($65B) are uninsured; <b>48%</b> of insurers lack catastrophe models. Faster, clearer settlements help communities rebuild.
        </div>
      </li>
    </ul>
  </div>
  
  <div class="card-strong" style="padding:16px 20px;background:#f8f9fa">
    <div style="font-size:19px;font-weight:700;color:#000;margin-bottom:12px;border-bottom:2px solid #000;padding-bottom:6px">
      Visualizing the Disputed Claim Gap (Typhoon Jebi: $11.6M at 20% Surge Share)
    </div>
    
    <div style="display:flex;flex-direction:column;gap:8px">
      <!-- Ground up -->
      <div style="background:#ea4335;color:#fff;border-radius:6px;padding:9px 14px;display:flex;justify-content:space-between;align-items:center">
        <div><b>Ground-Up Insured Claims</b><div style="font-size:13px;opacity:0.9">Total local damage across Japan</div></div>
        <div style="font-size:23px;font-weight:700">$733.0M</div>
      </div>
      <div style="text-align:center;font-size:15px;color:#5f6368;font-weight:700;line-height:1">▼ Loss Waterfall Cascade</div>
      
      <!-- Primary insurer retention -->
      <div style="background:#e8eaed;border:1.5px solid #bdc1c6;color:#202124;border-radius:6px;padding:8px 14px;display:flex;justify-content:space-between;align-items:center">
        <div><b>Primary Insurer Deductible</b><div style="font-size:13px;color:#5f6368">Kept locally by 8 primary insurers</div></div>
        <div style="font-size:21px;font-weight:700;color:#3c4043">$242.1M</div>
      </div>
      
      <!-- Reinsurers layer -->
      <div style="background:#1fa99c;color:#fff;border-radius:6px;padding:8px 14px;display:flex;justify-content:space-between;align-items:center">
        <div><b>Reinsurance Market Payout</b><div style="font-size:13px;opacity:0.9">Across Cat XL &amp; Quota Share contracts</div></div>
        <div style="font-size:21px;font-weight:700">$490.9M</div>
      </div>

      <!-- Lion Re share -->
      <div style="background:#1a73e8;color:#fff;border-radius:6px;padding:8px 14px;display:flex;justify-content:space-between;align-items:center">
        <div><b>Our Net Share (Lion Re)</b><div style="font-size:13px;opacity:0.9">Recovered ($78.4M) − Refill Fee ($8.0M)</div></div>
        <div style="font-size:21px;font-weight:700">$70.4M</div>
      </div>

      <!-- Dispute gap highlight -->
      <div style="background:#fff8e1;border:2px dashed #f29900;border-radius:6px;padding:9px 14px;margin-top:2px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div>
            <b style="color:#b06000;font-size:17px">⚖ Disputed Claim Gap at Stake</b>
            <div style="font-size:13px;color:#795548">T-004 Osaka 329cm Storm Surge Clause</div>
          </div>
          <div style="font-size:23px;font-weight:700;color:#b06000">$11.6M</div>
        </div>
        <div style="font-size:13px;color:#5d4037;margin-top:4px;line-height:1.3">
          Without CatSight: Months of legal argument delay settlement.<br>
          With CatSight: Clause Courtroom prices both readings in about 8 s (p50).
        </div>
      </div>
    </div>
  </div>
</div>""",
        bold_title=True,
    ))

    # Slide 4 — Template Page 5: List of features offered by the solution
    s.append(content_slide(
        "List of features offered by the solution",
        """<table style="font-size:23px">
  <tr><th style="width:24%">Feature</th><th style="width:46%">What it gives the analyst</th><th style="width:30%">How it stays trustworthy</th></tr>
  <tr><td><b>1. Who pays what</b></td><td>Matches all 24 contracts by peril, place and dates (with a reason for each of the 11 that don't respond); payout per layer, coverage used, refill fees, and where the insurer, all reinsurers and Lion Re end up.</td><td>Tested code; exact match with a hand-worked example.</td></tr>
  <tr><td><b>2. "How was this calculated?"</b></td><td>Each contract step by step: wind or shaking, damage %, insured value × damage % = loss, and each layer's formula with its citation.</td><td>Every number can be inspected.</td></tr>
  <tr><td><b>3. Clause flags &amp; scanned pages</b></td><td>Flags clauses that bite on <i>this</i> event (T-004 excludes storm surge; Jebi's 329 cm Osaka tide) and reads a scanned endorsement (168 h replaces 72 h).</td><td>Two-step quote check; failures shown as withheld; scanned pages badged <i>transcribed</i>.</td></tr>
  <tr><td><b>4. Clause Courtroom</b></td><td>Two AI lawyers argue opposite readings in parallel, from checked quotes; the engine prices both; a neutral arbiter summarises.</td><td>Issue-spotting only; the analyst records the decision.</td></tr>
  <tr><td><b>5. What-if &amp; follow-up questions</b></td><td>Try a labelled hypothetical storm window; ask plain questions about the contracts and results.</td><td>Bounded inputs; questions screened by a local filter + <b>Google Cloud Model Armor</b>.</td></tr>
  <tr><td><b>6. Replay, tour &amp; reports</b></td><td>6-second free replay of a real run, 9-stop guided tour, colour-blind-safe themes, Word &amp; Markdown reports.</td><td>Every report carries the method version, check counts and disclaimers.</td></tr>
</table>"""
    ))

    # Slide 5 — Template Page 6: Process flow diagram or Use-case diagram
    s.append(content_slide(
        "Process flow diagram or Use-case diagram",
        """<div class="grid2">
  <div>
    <p style="margin-top:0"><b>Workflow 1: live analysis (ADK 2.11 <code>Workflow</code>)</b></p>
    <div class="box"><b>1. event_intel</b>Loads the real storm track or earthquake shaking map, and the event's timeline</div>
    <div class="arrow">▼</div>
    <div class="box" style="border-width:2.5px"><b>2. exposure_analyst (no AI: tested Python)</b>Matches 24 treaties → loss by region → payout per layer. Money on screen in ~0.7 s</div>
    <div class="arrow">▼</div>
    <div class="box"><b>3. wording_checker (Gemini 3.5 Flash-Lite)</b>Searches each treaty's clauses (Firestore vector search) → candidate flags with page, clause and quote</div>
    <div class="arrow">▼</div>
    <div class="box" style="border-width:2.5px"><b>4. verifier ⇄ reviser (one retry)</b>Word-for-word quote match, then Gemini 3.8 Flash checks the quote supports the claim → one retry → else withheld</div>
    <div class="arrow">▼</div>
    <div class="box"><b>5. reporter (Gemini 3.5 Flash-Lite + number check)</b>Writes the memo from verified facts; code checks every number against the engine</div>
  </div>
  <div>
    <p style="margin-top:0"><b>Workflow 2: Clause Courtroom (parallel)</b></p>
    <div class="box"><b>1. brief</b>Picks the most material verified exclusion flag and the clauses around it</div>
    <div class="arrow">▼</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
      <div class="box"><b>2a. cedent_counsel</b>Flash-Lite · argues the insurer's reading + excluded share (0–50%)</div>
      <div class="box"><b>2b. reinsurer_counsel</b>Flash-Lite · argues the reinsurers' reading + excluded share (0–50%)</div>
    </div>
    <div class="arrow">▼ Join + quote &amp; support check (one retry per side)</div>
    <div class="box" style="border-width:2.5px"><b>3. price (tested Python)</b>Prices both readings through the treaty layers; money at stake for each party</div>
    <div class="arrow">▼</div>
    <div class="box"><b>4. arbiter (Gemini 3.8 Flash) → the analyst decides</b>Summarises both sides without deciding; the analyst records a position</div>
  </div>
</div>"""
    ))

    # Slide 6 — Template Page 7: Wireframes/Mock diagrams of the proposed solution (optional)
    s.append(content_slide(
        "Wireframes/Mock diagrams of the proposed solution (optional)",
        """<div class="grid2" style="grid-template-columns: 1.05fr 0.95fr; gap: 28px; align-items: stretch;">
  <!-- Left: Visual UI Cockpit Wireframe -->
  <div class="card" style="padding:16px 18px;background:#ffffff;border:2px solid #000000;display:flex;flex-direction:column;justify-content:space-between">
    <div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <span style="font-size:19px;font-weight:700">Analyst Cockpit: 5-Step Progressive UI Wireframe</span>
        <span style="font-size:13px;background:#e8f0fe;color:#1a73e8;padding:2px 8px;border-radius:4px;font-weight:600">React 18 + SSE Stream</span>
      </div>

      <!-- Browser Mockup Frame -->
      <div style="border:1.5px solid #bdc1c6;border-radius:6px;overflow:hidden;background:#f8f9fa">
        <!-- Chrome Bar -->
        <div style="background:#dadce0;padding:5px 10px;display:flex;align-items:center;gap:6px">
          <span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#ea4335"></span>
          <span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#fbbc04"></span>
          <span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#34a853"></span>
          <span style="font-size:12px;color:#5f6368;margin-left:10px;font-family:Consolas,monospace">https://catsight-api-342162443546.us-central1.run.app</span>
        </div>

        <!-- Sticky Summary Bar -->
        <div style="background:#1e293b;color:#fff;padding:8px 12px;display:flex;justify-content:space-between;align-items:center;font-size:13px">
          <span><b>CatSight</b> · Typhoon Jebi</span>
          <span>Local Claims: <b>$733.0M</b></span>
          <span>Reinsurers: <b>$490.9M</b></span>
          <span style="color:#38bdf8">Our Net: <b>$70.4M</b></span>
          <span style="background:#059669;padding:1px 6px;border-radius:3px;font-size:11px">✓ 1 Verified · 1 Withheld</span>
        </div>

        <!-- Stepper Nav -->
        <div style="background:#ffffff;border-bottom:1px solid #dadce0;padding:6px 10px;display:flex;justify-content:space-between;font-size:12px;font-weight:600">
          <span style="color:#5f6368">1. Event Track</span>
          <span style="color:#5f6368">2. Who's Hit</span>
          <span style="color:#1fa99c;border-bottom:2px solid #1fa99c;padding-bottom:2px">3. What It Costs</span>
          <span style="color:#5f6368">4. Clauses</span>
          <span style="color:#5f6368">5. Decide</span>
        </div>

        <!-- Two-pane Mockup Body -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:10px;background:#f1f3f4;height:195px">
          <!-- Left Pane: Map / Exposure -->
          <div style="background:#ffffff;border:1px solid #dadce0;border-radius:4px;padding:8px;display:flex;flex-direction:column;justify-content:space-between">
            <div style="font-size:12px;font-weight:700;color:#202124">Exposure Choropleth Map</div>
            <!-- SVG Map Sketch -->
            <div style="height:120px;display:flex;align-items:center;justify-content:center;background:#f8f9fa;border-radius:4px;position:relative">
              <svg width="220" height="95" viewBox="0 0 220 95">
                <path d="M 20 75 Q 70 55 120 42 T 200 20" stroke="#ea4335" stroke-width="3" stroke-dasharray="4" fill="none"/>
                <circle cx="95" cy="54" r="16" fill="rgba(234,67,53,0.25)" stroke="#ea4335" stroke-width="1.5"/>
                <circle cx="95" cy="54" r="5" fill="#ea4335"/>
                <text x="115" y="56" font-size="10" font-family="sans-serif" font-weight="bold" fill="#202124">Osaka (329 cm tide)</text>
                <rect x="25" y="20" width="35" height="15" rx="3" fill="#1fa99c" opacity="0.3"/>
                <rect x="150" y="50" width="45" height="20" rx="3" fill="#1a73e8" opacity="0.25"/>
              </svg>
            </div>
            <div style="font-size:11px;color:#5f6368">34 prefectures overlaid on peak gust contours</div>
          </div>

          <!-- Right Pane: Waterfall & Courtroom -->
          <div style="background:#ffffff;border:1px solid #dadce0;border-radius:4px;padding:8px;display:flex;flex-direction:column;justify-content:space-between">
            <div style="font-size:12px;font-weight:700;color:#202124">Clause Courtroom &amp; Layer Stack</div>
            <div style="display:flex;gap:4px;height:120px">
              <div style="flex:1;background:#f0fdf4;border:1px solid #86efac;border-radius:4px;padding:6px;font-size:11px">
                <b style="color:#166534">Insurer Counsel</b><br>
                "Windstorm caused collapse; surge excluded."<br>
                <span style="color:#15803d;font-weight:bold">0% Surge share</span>
              </div>
              <div style="flex:1;background:#eff6ff;border:1px solid #93c5fd;border-radius:4px;padding:6px;font-size:11px">
                <b style="color:#1e40af">Reinsurer Counsel</b><br>
                "Flooded by storm tide; clause 8 bites."<br>
                <span style="color:#1d4ed8;font-weight:bold">20% Surge share</span>
              </div>
            </div>
            <div style="font-size:11px;color:#b45309;font-weight:600">Disputed Gap: $11.64M priced live (at 20% surge share)</div>
          </div>
        </div>
        
        <!-- Footer Bar -->
        <div style="background:#ffffff;border-top:1px solid #dadce0;padding:6px 12px;display:flex;justify-content:space-between;font-size:11px;color:#5f6368">
          <span>⚡ Instant Replay: <b>6 s</b> · Live Agent SSE: <b>11.3 s p50</b></span>
          <span>Python Decimal: <b>Zero LLM arithmetic</b></span>
        </div>
      </div>
    </div>
  </div>

  <!-- Right: Trust Architecture 2-Stage Verification Funnel -->
  <div class="card" style="padding:16px 18px;background:#ffffff;border:2px solid #000000;display:flex;flex-direction:column;justify-content:space-between">
    <div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <span style="font-size:19px;font-weight:700">Trust Architecture: 2-Stage Verification Funnel</span>
        <span style="font-size:13px;background:#e6f4ea;color:#137333;padding:2px 8px;border-radius:4px;font-weight:600">Every quote checked</span>
      </div>

      <!-- Funnel Graphic -->
      <div style="display:flex;flex-direction:column;gap:6px">
        <!-- Input -->
        <div style="background:#f1f3f4;border:1.5px solid #bdc1c6;border-radius:6px;padding:8px 12px">
          <div style="font-size:13px;font-weight:700;color:#202124">1. Candidate AI Clause Flag / Counsel Argument</div>
          <div style="font-size:12px;color:#5f6368">Model proposes: <code>treaty_id</code>, <code>page</code>, <code>clause_no</code>, and verbatim <code>quote</code></div>
        </div>

        <div style="text-align:center;font-size:14px;color:#1a73e8;font-weight:700;line-height:1">▼ Filter 1</div>

        <!-- Stage 1 -->
        <div style="background:#e8f0fe;border:1.5px solid #1a73e8;border-radius:6px;padding:8px 12px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <b style="color:#1a73e8;font-size:13px">Stage 1: Deterministic Word-Aligned Quote Matcher</b>
            <span style="font-size:11px;background:#1a73e8;color:#fff;padding:1px 6px;border-radius:3px">0 ms Python</span>
          </div>
          <div style="font-size:12px;color:#202124;margin-top:2px">Normalised substring + ellipsis (<code>...</code>) matcher against Firestore treaty PDF text chunk. Catches 40/40 corrupted quotes; tags scanned endorsements as <code>transcribed</code>.</div>
        </div>

        <div style="text-align:center;font-size:14px;color:#7060e8;font-weight:700;line-height:1">▼ Filter 2</div>

        <!-- Stage 2 -->
        <div style="background:#f3e8fd;border:1.5px solid #8430ce;border-radius:6px;padding:8px 12px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <b style="color:#8430ce;font-size:13px">Stage 2: Semantic Support Check (Gemini 3.8 Flash)</b>
            <span style="font-size:11px;background:#8430ce;color:#fff;padding:1px 6px;border-radius:3px">~1.2 s Reasoning</span>
          </div>
          <div style="font-size:12px;color:#202124;margin-top:2px">Verifies quote + event timeline (<code>start</code>, <code>end</code>, <code>duration_h</code>) + JMA facts directly support the exclusion. 1 revision retry loop on failure.</div>
        </div>

        <!-- Forked Outcomes -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:4px">
          <div style="background:#e6f4ea;border:2px solid #137333;border-radius:6px;padding:8px 10px;text-align:center">
            <div style="color:#137333;font-size:13px;font-weight:700">✓ Verified Citation</div>
            <div style="font-size:11px;color:#1e4620;margin-top:2px">Rendered in UI with clickable source PDF page pill &amp; pricing impact</div>
          </div>
          <div style="background:#fce8e6;border:2px solid #c5221f;border-radius:6px;padding:8px 10px;text-align:center">
            <div style="color:#c5221f;font-size:13px;font-weight:700">⊘ Visibly Withheld</div>
            <div style="font-size:11px;color:#5c1d1d;margin-top:2px">Suppressed from findings; shown as <code>n verified · k withheld</code></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>"""
    ))

    # Slide 7 — Template Page 8: Architecture diagram of the proposed solution
    s.append(content_slide(
        "Architecture diagram of the proposed solution",
        """<div style="display:grid;grid-template-columns:1.15fr 0.85fr;gap:34px">
  <div>
    <div class="box"><b>Analyst / judge browser (React 18 + TypeScript)</b>One origin over HTTPS · results stream live (server-sent events)</div>
    <div class="arrow">▼</div>
    <div class="box" style="border-width:2.5px"><b>Google Cloud Run — <code>catsight-api</code> (us-central1)</b>One container: UI + FastAPI · ADK 2.11 <code>Workflow</code> graphs · tested Python loss engine · least-privilege service account · max 3 instances · hourly &amp; daily caps</div>
    <div class="arrow">▼</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:12px">
      <div class="box"><b>Gemini Enterprise Agent Platform</b>(formerly Vertex AI)<br>• 3.5 Flash-Lite<br>• 3.8 Flash<br>• embedding-001</div>
      <div class="box"><b>Firestore</b>• Treaty book &amp; events<br>• 252 clause vectors<br>• Saved runs</div>
      <div class="box"><b>Cloud Storage</b>• Treaty PDFs<br>• Stamped endorsements</div>
      <div class="box"><b>Model Armor</b>• Screens follow-up questions &amp; answers</div>
    </div>
    <div class="arrow">▼</div>
    <div class="box"><b>Cloud Logging · Trace · Monitoring · Log Analytics</b>A log line per stage · guardrail metrics (citations withheld, lawyers dropped, unsupported figures) · live dashboard</div>
  </div>
  <div class="card-strong">
    <p style="margin-top:0"><b>Key decisions</b></p>
    <ul style="font-size:21px">
      <li><b>Money first, AI second:</b> tested code prices the loss before any AI call (0.7 s). The AI never calculates.</li>
      <li><b>Rules are data, not code:</b> treaty terms, damage curves and market rules live in versioned data files; the version in force is stamped on every run.</li>
      <li><b>One service, no keys:</b> UI and API on one Cloud Run service; a dedicated service account, no API keys.</li>
      <li><b>Ready for judging:</b> pre-computed searches (no embedding calls on a cold start), one warm instance, and rate limits that fall back to the recorded replay.</li>
    </ul>
  </div>
</div>"""
    ))

    # Slide 8 — Template Page 9: Technologies to be used in the solution
    s.append(content_slide(
        "Technologies to be used in the solution",
        """<table>
  <tr><th style="width:28%">Technology / Service</th><th style="width:23%">Role</th><th style="width:49%">Why we chose it</th></tr>
  <tr><td><b>Gemini 3.5 Flash-Lite</b><br><span class="muted">Gemini Enterprise Agent Platform</span></td><td>Agents &amp; page reading</td><td>Fast, low-cost structured output for wording checks, the two Courtroom lawyers, report text and the scanned page.</td></tr>
  <tr><td><b>Gemini 3.8 Flash</b><br><span class="muted">Gemini Enterprise Agent Platform</span></td><td>Checking &amp; arbiter</td><td>Stronger reasoning to check that each quote supports its claim, and to summarise the Courtroom fairly.</td></tr>
  <tr><td><b>Google ADK 2.11</b></td><td>Agent workflows</td><td>Graph <code>Workflow</code>: a 5-step analysis with a bounded retry, and a Courtroom with two lawyers in parallel (<code>JoinNode</code>).</td></tr>
  <tr><td><b>Firestore + Vector Search</b><br><span class="muted"><code>gemini-embedding-001</code></span></td><td>Data &amp; clause search</td><td>Treaty book, 252 clause vectors filtered by treaty (186/186 governing clauses found), runs and audit trail.</td></tr>
  <tr><td><b>Google Cloud Model Armor</b></td><td>Question screening</td><td>Screens follow-up questions and answers for prompt injection, jailbreaks and harmful content, after a local filter.</td></tr>
  <tr><td><b>Cloud Run &amp; Cloud Storage</b></td><td>Hosting &amp; PDFs</td><td>One container for UI + API; scale-to-zero by default, one warm instance during judging; Storage holds the treaty PDFs.</td></tr>
  <tr><td><b>Cloud Logging, Trace &amp; Monitoring</b></td><td>Observability</td><td>A log line per stage, per-agent traces, and a live dashboard built from log-based metrics.</td></tr>
  <tr><td><b>Python 3.12 · FastAPI · React 18</b></td><td>Engine &amp; UI</td><td>Tested loss engine (870+ offline + 13 live tests), Word report generator, accessible TypeScript UI.</td></tr>
</table>"""
    ))

    # Slide 9 — Template Page 10: Estimated implementation cost (optional)
    s.append(content_slide(
        "Estimated implementation cost (optional)",
        """<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin-bottom:22px">
  <div class="card-strong"><div class="big">$0.010</div><div class="lbl">Median AI cost per live analysis ($0.008–$0.014)</div></div>
  <div class="card-strong"><div class="big">$0.005</div><div class="lbl">Median AI cost per Clause Courtroom run ($0.005–$0.006)</div></div>
  <div class="card-strong"><div class="big">$0.000</div><div class="lbl">Instant Replay (a recorded real run, no AI calls)</div></div>
  <div class="card-strong"><div class="big">$0.003</div><div class="lbl">Follow-up question (from token counts)</div></div>
</div>
<div class="grid2">
  <div class="card">
    <p style="margin-top:0"><b>Measured Cloud &amp; Token Breakdown</b></p>
    <table>
      <tr><th>Workload</th><th>Model / Service</th><th>Measured Cost</th></tr>
      <tr><td>One-time ingestion (8 PDF wordings, 252 chunks)</td><td><code>gemini-embedding-001</code> + <code>3.5-flash-lite</code></td><td><b>&lt; $0.08 total</b> (57 s runtime)</td></tr>
      <tr><td>Live event analysis (13 responding treaties)</td><td><code>3.5-flash-lite</code> + <code>3.8-flash</code> verifier</td><td><b>$0.0097 p50</b> ($0.0081–$0.0140)</td></tr>
      <tr><td>Clause Courtroom (parallel counsel + arbiter)</td><td>2× <code>3.5-flash-lite</code> + <code>3.8-flash</code></td><td><b>$0.0052 p50</b> ($0.0047–$0.0064)</td></tr>
      <tr><td>Cloud Run + Firestore</td><td><code>min-instances 0</code> by default (1 during judging), <code>max 3</code></td><td><b>~$0 idle</b> at zero instances · pennies per active hour</td></tr>
    </table>
  </div>
  <div class="card">
    <p style="margin-top:0"><b>Annual Run-Rate vs. Manual Analyst Effort</b></p>
    <ul style="font-size:20px">
      <li><b>A mid-size reinsurer:</b> 8 major events + 20 smaller checks a year (≈ 500 runs) → <b>~$7/year of Gemini cost</b>, plus ~$25–$40/month for Cloud Run and Firestore when active.</li>
      <li><b>Analyst time saved (estimate):</b> 30–60 hours per event down to 3.5–8 hours → <b>165–675 hours a year</b> (about $12k–$100k; labelled <i>simulated</i>).</li>
      <li><b>Cost guards:</b> 20 live runs/hour per visitor, 300/day cap, automatic fallback to Instant Replay, billing budget alerts.</li>
    </ul>
  </div>
</div>"""
    ))

    # Slide 10 — Template Page 11: Snapshots of the prototype
    s.append(content_slide(
        "Snapshots of the prototype",
        f"""<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px">
  <div>
    <img class="shot" style="max-height:335px;object-fit:cover;object-position:top" src="{img('cap_6.png')}" alt="">
    <p style="font-size:17px;margin:6px 0 0"><b>1. Live Agent Streaming:</b> ADK 2.11 stages stream over SSE; deterministic loss figures arrive in ~0.7 s while Gemini retrieves &amp; verifies treaty clauses.</p>
  </div>
  <div>
    <img class="shot" style="max-height:335px;object-fit:cover;object-position:top" src="{img('cap_12.png')}" alt="">
    <p style="font-size:17px;margin:6px 0 0"><b>2. Three-Party Loss Waterfall:</b> 13 of 24 treaties respond on Typhoon Jebi ($733.04M claims → $242.12M insurer retention, $490.92M reinsurers, $70.36M Lion Re net).</p>
  </div>
  <div>
    <img class="shot" style="max-height:335px;object-fit:cover;object-position:top" src="{img('cap_45.png')}" alt="">
    <p style="font-size:17px;margin:6px 0 0"><b>3. Clause Courtroom (Jebi T-004 Storm-Surge Exclusion):</b> Parallel counsel argue 0% vs 20% surge share; engine prices both (Ceded −$11.64M, Insurer +$10.31M, Reinsurers −$10.31M, Lion Re −$1.34M).</p>
  </div>
  <div>
    <img class="shot" style="max-height:335px;object-fit:cover;object-position:top" src="{img('cap_72.png')}" alt="">
    <p style="font-size:17px;margin:6px 0 0"><b>4. Scanned Endorsement Detective (T-004 p.7):</b> Gemini transcribes a rasterised stamped endorsement with no text layer (168 hours replaces 72 hours) and badges it <code>transcribed</code>.</p>
  </div>
</div>"""
    ))

    # Slide 11 — Template Page 12: Prototype Performance report/Benchmarking
    s.append(content_slide(
        "Prototype Performance report/Benchmarking",
        f"""<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin-bottom:20px">
  <div class="card-strong"><div class="big">0.7 s</div><div class="lbl">Money on screen (median; 0.5–1.1 s over 10 live runs)</div></div>
  <div class="card-strong"><div class="big">11.3 s</div><div class="lbl">Full analysis with checked quotes (median; 7.8–19.3 s)</div></div>
  <div class="card-strong"><div class="big">99.5%</div><div class="lbl">Treaty terms extracted (185/186 fields, in 57 s vs ~25 min)</div></div>
  <div class="card-strong"><div class="big">870+</div><div class="lbl">Automated tests (870+ offline + 13 live; CI on GitHub)</div></div>
</div>
<div class="grid2" style="grid-template-columns:1.05fr 0.95fr;gap:26px">
  <table style="font-size:19px">
    <tr><th>What we measured (<code>docs/RESULTS.md</code>)</th><th>Result</th></tr>
    <tr><td><b>Loss engine vs. hand-worked example</b><br><span class="muted">every layer, reinstatement and quota-share formula</span></td><td><b>100% exact</b></td></tr>
    <tr><td><b>Clause search &amp; citation audit</b><br><span class="muted">1 scanned page transcribed; 1 unverified withheld</span></td><td><b>186/186 found · 185/186 verified</b></td></tr>
    <tr><td><b>Clause Courtroom, live</b><br><span class="muted">skipped in 2 when the T-004 flag was withheld; $10.3M–$26.0M at stake priced live</span></td><td><b>Ran in 8 of 10; both sides verified in all 8</b></td></tr>
    <tr><td><b>Bad-quote rejection</b> <span class="muted">(offline test suite)</span></td><td><b>40/40 rejected, 0 false withholds</b></td></tr>
    <tr><td><b>Untraceable numbers in AI-written text</b></td><td><b>0 across all live runs</b></td></tr>
  </table>
  <div>
    <img class="shot" src="{docimg('observability_dashboard.png')}" alt="Live-service dashboard">
    <p style="font-size:16px;margin:6px 0 0">The live-service dashboard in Cloud Monitoring (screenshot, 15 Oct 2026). "Citations withheld" counts quotes the checker refused to show: the guardrail working, not an error.</p>
  </div>
</div>
<p class="muted" style="font-size:17px;margin-top:12px"><b>Honest limits:</b> extraction prompts were tuned on the same 8 synthetic wordings (99.5% is an upper bound; a blind set is next). Analyst-time savings are labelled <i>simulated estimates</i>.</p>"""
    ))

    # Slide 12 — Template Page 13: Additional Details/Future Development (if any)
    s.append(content_slide(
        "Additional Details/Future Development (if any)",
        """<div class="grid2">
  <div class="card">
    <p style="margin-top:0"><b>Why pricing each party matters</b></p>
    <p style="font-size:21px"><b>1. Jebi Courtroom (T-004 storm-surge exclusion, p.2 cl.8):</b><br>
    At a 20% surge share (the recorded run), reinsurance payouts fall <b>−$11.64M</b> ($39.58M → $27.94M); net of refill fees, reinsurers save <b>$10.31M</b> and the insurer carries <b>+$10.31M</b>; Lion Re saves <b>$1.34M</b>. The demo video shows a separate 30% run: <b style="white-space:nowrap">−$17.46M</b> ceded, Lion Re <b style="white-space:nowrap">−$2.44M</b>.</p>
    <p style="font-size:21px"><b>2. Hours clause (worked example, What-if):</b><br>
    Splitting one $54.4M event into two ($35.0M + $19.4M) cuts reinsurers' recoveries by <b>−22.5% (−$10.0M)</b>, yet <b>raises Lion Re's loss +7.4%</b> ($6.82M → $7.33M), because the split moves loss into the layer where Lion Re's share is largest.</p>
    <p style="margin-top:12px"><b>Team Techno Crackers — Roles</b></p>
    <p style="font-size:18px;margin:4px 0">• <b>Venket Raj S (Lead):</b> Architecture, Cloud Run / Firestore / IAM deployment &amp; observability<br>
    • <b>Malik Chandra Pandian:</b> Reinsurance domain modelling, <code>Decimal</code> loss engine &amp; worked examples<br>
    • <b>Arun Veerappan:</b> ADK 2.11 workflows, RAG extraction, citation verifier &amp; Clause Courtroom<br>
    • <b>Nagaraj:</b> React 18 + TypeScript + custom SVG choropleth UI, 5-step analyst workflow, tour &amp; exports</p>
  </div>
  <div class="card">
    <p style="margin-top:0"><b>Future Development Roadmap (Designed / Investigated)</b></p>
    <ul style="font-size:20px">
      <li><b>A real hours-clause dispute:</b> the 2024 Hualien earthquake (Taiwan). Its real aftershocks ~20 days later are a second occurrence worth ~$11–15M per treaty.</li>
      <li><b>Damage curves per country:</b> calibrated for the Philippines, bringing Typhoon Haiyan back into the demo.</li>
      <li><b>Licensed hazard footprints:</b> Moody's RMS or Verisk behind our hazard interface.</li>
      <li><b>Your own contracts:</b> authenticated treaty upload, and BigQuery for portfolio-scale exposure.</li>
      <li><b>Automatic start:</b> USGS / GDACS disaster alerts via Pub/Sub, plus an A2A/MCP endpoint for other agents.</li>
    </ul>
  </div>
</div>"""
    ))

    # Slide 13 — Template Page 14: Provide links to your:
    s.append(content_slide(
        "Provide links to your:",
        f"""<ul style="font-size:28px;line-height:1.75;margin-top:14px">
  <li style="margin-bottom:18px">
    <b>GitHub Public Repository</b><br>
    <a href="{REPO}" style="font-size:23px;font-family:Consolas,monospace;color:#1fa99c;text-decoration:none">{REPO}</a>
    <div class="muted" style="margin-top:2px">Apache-2.0 licence · 870+ offline tests + 13 opt-in live tests · GitHub Actions CI · Full architecture &amp; assumptions in <code>docs/</code>.</div>
  </li>
  <li style="margin-bottom:18px">
    <b>Demo Video Link (under 3 minutes: 2 min 45 s)</b><br>
    <a href="{VIDEO}" style="font-size:23px;font-family:Consolas,monospace;color:#1fa99c;text-decoration:none">{VIDEO}</a>
    <div class="muted" style="margin-top:2px">The problem, a live Typhoon Jebi analysis, a scanned endorsement read by Gemini, and the Clause Courtroom.</div>
  </li>
  <li style="margin-bottom:18px">
    <b>Final Product Link</b><br>
    <a href="{LIVE}" style="font-size:23px;font-family:Consolas,monospace;color:#1fa99c;text-decoration:none">{LIVE}</a>
    <div class="muted" style="margin-top:2px">Live on Google Cloud Run · No login · <b>Instant replay</b> (~6 s) or <b>Run live</b> (~11 s median) · 9-stop tour · 3 example questions built in · the README has a 2-minute judge guide.</div>
  </li>
  <li style="margin-bottom:18px">
    <b>Submission Folder (Google Drive)</b><br>
    <a href="{FOLDER}" style="font-size:23px;font-family:Consolas,monospace;color:#1fa99c;text-decoration:none">{FOLDER}</a>
    <div class="muted" style="margin-top:2px">The demo video and this deck (PDF).</div>
  </li>
</ul>
<div class="card" style="margin-top:16px;padding:12px 18px">
  <p class="muted" style="margin:0;font-size:18px"><b>Disclaimers &amp; Data Attribution:</b> {DISCLAIMER} Jebi, Hagibis, Haiyan and Noto were real events in which people died. Portfolio, insurers and treaty wordings are 100% synthetic; hazard data is public (NOAA IBTrACS v04r01, USGS ShakeMap, Natural Earth).</p>
</div>"""
    ))

    # Slide 14 — Template Page 16: Full-bleed "Thank you" slide
    s.append(f"""<section class="s">
  <img class="thankyou-full" src="{asset('Image11.jpg')}" alt="Thank you">
</section>""")

    return s


def main() -> None:
    missing_shots = [n for n in ("cap_6.png", "cap_12.png", "cap_45.png", "cap_72.png") if not (FRAMES / n).exists()]
    if missing_shots:
        raise SystemExit(f"missing screenshots in {FRAMES}: {missing_shots} - run scripts/create_video.py first")
    missing_assets = [n for n in ("Image5.jpg", "Image9.jpg", "Image11.jpg") if not (ASSETS / n).exists()]
    if missing_assets:
        raise SystemExit(f"missing template assets in {ASSETS}: {missing_assets}")

    all_slides = build_slides()
    total = len(all_slides)
    body = "".join(all_slides)
    html_path = ROOT / "scratch" / "deck.html"
    title = "CatSight — Google Cloud AI Builder Cup 2026 Submission Deck (Team Techno Crackers)"
    html_path.write_text(
        f"<!doctype html><html><head><meta charset=utf-8><title>{title}</title><style>{CSS}</style></head><body>{body}</body></html>",
        encoding="utf-8",
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(html_path.as_uri(), wait_until="networkidle")
        page.pdf(
            path=str(OUT),
            width="1920px",
            height="1080px",
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
        )
        for i in range(1, total + 1):
            page.set_viewport_size({"width": 1920, "height": 1080})
            page.evaluate(f"window.scrollTo(0, {(i - 1) * 1080})")
            page.screenshot(path=str(ROOT / "scratch" / f"deck_{i}.png"))
        browser.close()
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {total} slides)")


if __name__ == "__main__":
    main()
