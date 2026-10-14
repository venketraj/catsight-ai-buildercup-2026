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
    <p><b>CatSight</b> tells a reinsurer in <b>about 9–15 seconds</b> after a typhoon or earthquake which contracts respond, what each layer pays, and which contract clauses decide that payout — with every quote machine-verified against the source PDF page.</p>
    <p><b>The Human &amp; Community Problem:</b></p>
    <ul>
      <li>When a catastrophe hits, <b>primary insurance companies</b> must rapidly pay hundreds of thousands of claims to rebuilding families and local businesses (e.g., <b>857,284 claims &amp; ¥1,067.8bn paid</b> after Typhoon Jebi <span class="tag">GIAJ</span>).</li>
      <li>To stay solvent, primary insurers rely on multi-million dollar payouts from <b>reinsurance contracts</b>.</li>
      <li><b>The bottleneck:</b> Reinsurance contracts are 50-page legal PDFs. While industry loss models take <b>4–20 days</b>, claims teams spend <b>30–60 analyst-hours</b> manually reviewing contracts and arguing over ambiguous exclusions (like windstorm vs. storm-surge flooding). When reinsurance payouts stall, community recovery stalls.</li>
    </ul>
    <p><b>The Plain-English Translation:</b> <i>Primary Insurer (Cedent)</i> = company paying local claims; <i>Deductible (Retention)</i> = what the insurer pays first; <i>Coverage Used (Burn %)</i> = percentage of policy limit paid out; <i>Fee to Refill Coverage (RIP)</i> = fee to restore protection after a claim.</p>
  </div>
  <div class="card-strong">
    <table>
      <tr><th>Source / Workflow</th><th>Time to Arrive</th><th>Scope &amp; Practical Limitation</th></tr>
      <tr><td>Cat-modeller event response</td><td><b>4–20 days</b></td><td>Broad market range; ignores your specific PDF contracts</td></tr>
      <tr><td>PERILS (Asia loss index)</td><td><b>6 weeks</b></td><td>Industry loss index, not treaty-level payout calculation</td></tr>
      <tr><td>Verisk PCS Japan</td><td><b>up to 90 days</b></td><td>Market-wide index for events ≥ $2bn</td></tr>
      <tr><td>Manual in-house spreadsheet review</td><td><b>2–4 days</b></td><td>Slow, error-prone; missed endorsements and exclusions</td></tr>
      <tr><td><b>CatSight (Lion Re's book)</b></td><td><b>0.7 s math · ~9–12 s full AI check</b></td><td><b>Event × exposure × layer math × verified PDF wording</b></td></tr>
    </table>
    <p class="muted" style="margin-top:14px">Replays real public hazard footprints (NOAA IBTrACS, USGS ShakeMap) over a synthetic book of <b>24 reinsurance contracts written for 8 primary insurers</b> in Japan, the Philippines, and Taiwan.</p>
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
        <b>How different is it from existing ideas?</b>
        <div style="font-size:19px;margin-top:4px;color:#202124">
          • <b>CatSight is the join:</b> Cat models (Moody's RMS, Verisk) estimate hazard on generic terms, stopping before the contract PDF. Doc AI extracts text at underwriting, stopping before the storm. Generic LLMs hallucinate math. CatSight joins both in seconds.<br>
          • <b>Complementary by design:</b> Plugs directly into licensed vendor hazard footprints.
        </div>
      </li>
      <li style="margin-bottom:14px">
        <b>How will it solve the problem?</b>
        <div style="font-size:19px;margin-top:4px;color:#202124">
          • <b>Deterministic Python engine (<code>Decimal</code>, 874 tests):</b> Computes regional gross loss, tier payouts, burn %, and refill fees in <b>0.7–1.0 s</b> — zero LLM arithmetic.<br>
          • <b>Firestore vector RAG + 2-stage verification:</b> 252 clause vectors (768-d) + deterministic quote matching + Gemini 3.8 Flash semantic support check.
        </div>
      </li>
      <li style="margin-bottom:6px">
        <b>USP &amp; Social Impact</b>
        <div style="font-size:19px;margin-top:4px;color:#202124">
          • <b>Clause Courtroom:</b> Dual AI counsel argue opposing readings of ambiguous exclusions, pricing the exact <b>$14.6M disputed claim gap</b> live.<br>
          • <b>Scanned Endorsement Detective:</b> Transcribes stamped, rasterised image endorsements.<br>
          • <b>Protection Gap:</b> 91% of APAC disaster losses ($65B) are uninsured, and 48% of insurers lack cat models. Transparent settlements speed community recovery.
        </div>
      </li>
    </ul>
  </div>
  
  <div class="card-strong" style="padding:16px 20px;background:#f8f9fa">
    <div style="font-size:19px;font-weight:700;color:#000;margin-bottom:12px;border-bottom:2px solid #000;padding-bottom:6px">
      Visualizing the $14.6M Dispute Problem (Typhoon Jebi)
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
          <div style="font-size:23px;font-weight:700;color:#b06000">$14.6M</div>
        </div>
        <div style="font-size:13px;color:#5d4037;margin-top:4px;line-height:1.3">
          Without CatSight: Months of legal argument delay settlement.<br>
          With CatSight: Clause Courtroom prices both readings in 15 seconds.
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
        """<table>
  <tr><th style="width:24%">Feature</th><th style="width:46%">What it gives the claims analyst &amp; primary insurer</th><th style="width:30%">Verification &amp; Trust Guardrail</th></tr>
  <tr><td><b>1. Contract Matching &amp; Payout Waterfall</b></td><td>Matches all 24 contracts on peril ∩ territory ∩ period (with exclusion reasons for the other 11); computes per-tier payout, coverage limit used (burn %), refill fees, and 3-party net positions (Primary Insurer, All Reinsurers, Lion Re).</td><td>Deterministic <code>Decimal</code> engine; 100% exact match against hand-checked worked examples.</td></tr>
  <tr><td><b>2. "How was this calculated?"</b></td><td>Step-by-step audit drawer per contract: regional peak wind/MMI, vulnerability curve damage %, insured value × damage % = gross loss, and exact layer formula with citations.</td><td>Every intermediate number is inspectable and reproducible.</td></tr>
  <tr><td><b>3. Cited Wording Flags &amp; Endorsement Detective</b></td><td>Flags clauses that bite on <i>this</i> event (e.g., T-004 storm-surge exclusion on Jebi's 329 cm Osaka tide) and transcribes scanned image endorsements (T-004 p.7: 168h replaces 72h).</td><td>2-stage verifier loop; unverified flags visibly withheld (<code>n verified · k withheld</code>); scanned pages badged <code>transcribed</code>.</td></tr>
  <tr><td><b>4. Clause Courtroom (Dispute Resolution)</b></td><td>Parallel ADK agents (<code>cedent_counsel</code> ∥ <code>reinsurer_counsel</code>) argue opposing readings from verified quotes (with dynamic <code>COVER</code> clause retrieval &amp; <code>...</code> fragment matching); engine prices both readings; Arbiter summarises without deciding.</td><td>Issue-spotting only; human analyst records the decision with an audit timestamp.</td></tr>
  <tr><td><b>5. Bounded What-if &amp; Grounded Q&amp;A</b></td><td>Interactive storm-window scenario pricing (clearly labelled HYPOTHETICAL on Jebi's 9-hour window) and live follow-up Q&amp;A over contract clauses screened by Google Model Armor.</td><td>Typed, bounded tool schema; Model Armor prompt injection &amp; leakage filtering; 0 untraceable figures.</td></tr>
  <tr><td><b>6. Instant Replay, 9-Stop Tour &amp; Word Export</b></td><td>6-second zero-cost replay of a recorded real run, live SSE streaming (~9–12 s), colour-blind-safe themes, keyboard navigation, and Word (<code>.docx</code>) &amp; Markdown memos.</td><td>Every export carries the methodology version, verification counts, and mandatory disclaimers.</td></tr>
</table>"""
    ))

    # Slide 5 — Template Page 6: Process flow diagram or Use-case diagram
    s.append(content_slide(
        "Process flow diagram or Use-case diagram",
        """<div class="grid2">
  <div>
    <p style="margin-top:0"><b>Workflow 1: Live Event Analysis Graph (ADK 2.11 <code>Workflow</code>)</b></p>
    <div class="box"><b>1. event_intel</b>Loads NOAA IBTrACS / USGS ShakeMap footprint, event window (<code>start</code>, <code>end</code>, <code>duration_h</code>) &amp; JMA facts</div>
    <div class="arrow">▼</div>
    <div class="box" style="border-width:2.5px"><b>2. exposure_analyst (NO LLM — Pure Python Engine)</b>Matches 24 treaties → regional gross loss → Cat XL / QS waterfall → emits <code>result</code> SSE frame in ~0.7–1.0 s</div>
    <div class="arrow">▼</div>
    <div class="box"><b>3. wording_checker (Gemini 3.5 Flash-Lite)</b>Firestore 768-d vector search per treaty (<code>treaty_id</code> pre-filter) → candidate flags with page, clause &amp; quote</div>
    <div class="arrow">▼</div>
    <div class="box" style="border-width:2.5px"><b>4. verifier ⇄ reviser (Bounded 1-Retry Loop)</b>Stage 1: deterministic normalised + <code>...</code> fragment quote match · Stage 2: Gemini 3.8 Flash semantic support check → 1 revision retry on failure → withhold if still unverified</div>
    <div class="arrow">▼</div>
    <div class="box"><b>5. reporter (Gemini 3.5 Flash-Lite + Python Number Gate)</b>Drafts executive memo from verified facts; Python checks every number against engine output (0 untraceable figures)</div>
  </div>
  <div>
    <p style="margin-top:0"><b>Workflow 2: On-Demand Clause Courtroom (Parallel Fan-Out / Join)</b></p>
    <div class="box"><b>1. brief</b>Selects top verified HIGH/MEDIUM exclusion flag + loads Clause 2 (Business Covered) &amp; exclusion clauses</div>
    <div class="arrow">▼</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
      <div class="box"><b>2a. cedent_counsel</b>Gemini 3.5 Flash-Lite · argues insurer reading + excluded share (0–50%)</div>
      <div class="box"><b>2b. reinsurer_counsel</b>Gemini 3.5 Flash-Lite · argues reinsurer reading + excluded share (0–50%)</div>
    </div>
    <div class="arrow">▼ JoinNode + Quote &amp; Support Check (with 1 revision retry per side)</div>
    <div class="box" style="border-width:2.5px"><b>3. price (Deterministic Python Scenario Engine)</b>Prices both verified readings through the treaty layers; computes <code>money_at_stake</code> per party by subtraction</div>
    <div class="arrow">▼</div>
    <div class="box"><b>4. arbiter (Gemini 3.8 Flash) → Human Analyst Decision</b>Summarises both arguments without deciding; analyst records position (<code>cedent</code> / <code>reinsurer</code> / <code>unresolved</code>)</div>
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
          <span style="background:#059669;padding:1px 6px;border-radius:3px;font-size:11px">✓ 2 of 2 Verified</span>
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
            <div style="font-size:11px;color:#b45309;font-weight:600">Disputed Gap: $14.6M priced live</div>
          </div>
        </div>
        
        <!-- Footer Bar -->
        <div style="background:#ffffff;border-top:1px solid #dadce0;padding:6px 12px;display:flex;justify-content:space-between;font-size:11px;color:#5f6368">
          <span>⚡ Instant Replay: <b>6 s</b> · Live Agent SSE: <b>~9–12 s</b></span>
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
        <span style="font-size:13px;background:#e6f4ea;color:#137333;padding:2px 8px;border-radius:4px;font-weight:600">100% Quote Guardrail</span>
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
    <div class="box"><b>Analyst / Judge Browser (React 18 + TypeScript + Custom SVG Choropleth)</b>Same-origin HTTPS · REST + POST Server-Sent Events (<code>fetch</code> ReadableStream with 15 s heartbeat)</div>
    <div class="arrow">▼</div>
    <div class="box" style="border-width:2.5px"><b>Google Cloud Run — <code>catsight-api</code> (us-central1)</b>Single container serves React UI + FastAPI SSE API · Google ADK 2.11 <code>Workflow</code> graphs · Deterministic Python <code>Decimal</code> Loss Engine · Dedicated least-privilege SA (<code>catsight-run</code>) · <code>max-instances 3</code> · Per-IP hourly &amp; daily cost caps</div>
    <div class="arrow">▼</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px">
      <div class="box"><b>Gemini Enterprise Agent Platform</b>(formerly Vertex AI, global)<br>• Gemini 3.5 Flash-Lite<br>• Gemini 3.8 Flash<br>• gemini-embedding-001</div>
      <div class="box"><b>Cloud Firestore (Native)</b>us-central1<br>• Treaty book &amp; events<br>• 252 clause vectors (768-d)<br>• Saved runs &amp; positions</div>
      <div class="box"><b>Cloud Storage</b>us-central1<br>• Synthetic treaty PDFs<br>• Stamped endorsements</div>
    </div>
    <div class="arrow">▼</div>
    <div class="box"><b>Cloud Logging · Cloud Trace (OpenTelemetry) · Cloud Monitoring · Log Analytics SQL</b>Structured JSON logs per stage · Guardrail metrics (<code>citation_withheld</code>, <code>counsel_dropped</code>, <code>unsupported_figures</code>) · Live Service Dashboard</div>
  </div>
  <div class="card-strong">
    <p style="margin-top:0"><b>Key Architectural Decisions</b></p>
    <ul style="font-size:20px">
      <li><b>Single-origin deployment:</b> React UI and FastAPI SSE stream from one Cloud Run service — zero CORS issues or proxy buffering timeouts.</li>
      <li><b>Zero API keys in code or env:</b> Application Default Credentials via dedicated <code>catsight-run</code> IAM service account.</li>
      <li><b>Pre-embedded standard queries:</b> Ship in <code>query_embeddings.jsonl</code> so cold starts make zero embedding calls during an analysis; interactive <code>/ask</code> queries bypass batch rate-limit sleeps.</li>
      <li><b>Spoof-resistant rate limiting:</b> Reads right-most hop of <code>X-Forwarded-For</code> appended by Cloud Run's load balancer; falls back gracefully to recorded replay if cap is reached.</li>
    </ul>
  </div>
</div>"""
    ))

    # Slide 8 — Template Page 9: Technologies to be used in the solution
    s.append(content_slide(
        "Technologies to be used in the solution",
        """<table>
  <tr><th style="width:28%">Technology / Service</th><th style="width:23%">Component</th><th style="width:49%">Why it was chosen &amp; role in CatSight</th></tr>
  <tr><td><b>Gemini 3.5 Flash-Lite</b><br><span class="muted">Gemini Enterprise Agent Platform (Vertex AI)</span></td><td>Agent generation &amp; OCR</td><td>Fast, low-cost structured output (<code>response_schema</code>, <code>thinking_level=LOW</code>) for wording checks, parallel Courtroom counsel, report prose, and scanned-page transcription.</td></tr>
  <tr><td><b>Gemini 3.8 Flash</b><br><span class="muted">Gemini Enterprise Agent Platform (Vertex AI)</span></td><td>Verification &amp; Arbiter</td><td>Stronger reasoning model used as the semantic support judge in the Verifier Loop, Counsel Quote Checker, and neutral Courtroom Arbiter.</td></tr>
  <tr><td><b>Google ADK 2.11</b><br><span class="muted"><code>google-genai</code> + ADK Workflow</span></td><td>Multi-agent orchestration</td><td>Graph <code>Workflow</code> with bounded retry loops (<code>verifier ⇄ reviser</code>), parallel fan-out/fan-in (<code>JoinNode</code> for blind counsel), and OpenTelemetry Cloud Trace spans.</td></tr>
  <tr><td><b>Cloud Firestore + Vector Search</b><br><span class="muted"><code>gemini-embedding-001</code> (768-d)</span></td><td>Operational &amp; vector store</td><td>Stores the 24-treaty book, 252 clause vectors with equality pre-filtering on <code>treaty_id</code> (186/186 governing clauses retrieved), ingestion audit trail, and runs.</td></tr>
  <tr><td><b>Google Cloud Run &amp; Cloud Storage</b></td><td>Serverless runtime &amp; PDFs</td><td>Scale-to-zero container serving FastAPI SSE + React 18 UI; GCS stores treaty PDF wordings.</td></tr>
  <tr><td><b>Cloud Logging, Trace &amp; Monitoring</b></td><td>Production observability</td><td>Log-based metrics + Log Analytics SQL query (<code>observability_runs.sql</code>) powering the Cloud Monitoring dashboard.</td></tr>
  <tr><td><b>Python 3.12 · FastAPI · React 18 · Custom SVG</b></td><td>Core engine &amp; frontend</td><td>Deterministic <code>Decimal</code> loss engine (874 offline tests + 13 opt-in live tests), python-docx memo generator, accessible TypeScript UI.</td></tr>
</table>"""
    ))

    # Slide 9 — Template Page 10: Estimated implementation cost (optional)
    s.append(content_slide(
        "Estimated implementation cost (optional)",
        """<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin-bottom:22px">
  <div class="card-strong"><div class="big">$0.010</div><div class="lbl">p50 model cost per live analysis ($0.008–$0.013)</div></div>
  <div class="card-strong"><div class="big">$0.004</div><div class="lbl">p50 model cost per Clause Courtroom run</div></div>
  <div class="card-strong"><div class="big">$0.000</div><div class="lbl">Instant Replay cost (cached real SSE stream)</div></div>
  <div class="card-strong"><div class="big">$0.003</div><div class="lbl">Follow-up question (from token counts)</div></div>
</div>
<div class="grid2">
  <div class="card">
    <p style="margin-top:0"><b>Measured Cloud &amp; Token Breakdown</b></p>
    <table>
      <tr><th>Workload</th><th>Model / Service</th><th>Measured Cost</th></tr>
      <tr><td>One-time ingestion (8 PDF wordings, 252 chunks)</td><td><code>gemini-embedding-001</code> + <code>3.5-flash-lite</code></td><td><b>&lt; $0.08 total</b> (57 s runtime)</td></tr>
      <tr><td>Live event analysis (13 responding treaties)</td><td><code>3.5-flash-lite</code> + <code>3.8-flash</code> verifier</td><td><b>$0.0094–$0.0102 p50</b></td></tr>
      <tr><td>Clause Courtroom (parallel counsel + arbiter)</td><td>2× <code>3.5-flash-lite</code> + <code>3.8-flash</code></td><td><b>$0.0040 p50</b></td></tr>
      <tr><td>Cloud Run + Firestore (scale-to-zero default)</td><td><code>min-instances 0</code>, <code>max-instances 3</code></td><td><b>~$0 idle</b> · pennies per active hour</td></tr>
    </table>
  </div>
  <div class="card">
    <p style="margin-top:0"><b>Annual Run-Rate vs. Manual Analyst Effort</b></p>
    <ul style="font-size:20px">
      <li><b>Mid-size reinsurer workload:</b> 8 major events + 20 smaller checks/year (≈ 500 live analyses &amp; Courtroom runs/year) → <b>~$7/year in Gemini token cost</b> + ~$25–$40/month Cloud Run/Firestore when active.</li>
      <li><b>Estimated manual effort saved:</b> 30–60 analyst-hours per event reduced to 3.5–8 hours of review → <b>165–675 analyst-hours/year</b> (est. $12k–$100k/year in specialist time; labelled <i>simulated estimate</i>).</li>
      <li><b>Built-in cost guards:</b> 20 live runs/hour per visitor, 300/day service cap, automatic fallback to Instant Replay, and Cloud Billing budget alert.</li>
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
    <p style="font-size:17px;margin:6px 0 0"><b>1. Live Agent Streaming:</b> ADK 2.11 stages stream over SSE; deterministic loss figures arrive in ~0.7–1.0 s while Gemini retrieves &amp; verifies treaty clauses.</p>
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
        """<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin-bottom:22px">
  <div class="card-strong"><div class="big">0.7–1.0 s</div><div class="lbl">Time to money on screen (p50 across two 5-run live benchmarks)</div></div>
  <div class="card-strong"><div class="big">9.8–12.1 s</div><div class="lbl">Complete live analysis with verified flags (p50; range 8.0–31.2 s)</div></div>
  <div class="card-strong"><div class="big">99.5%</div><div class="lbl">RAG treaty-term extraction (185/186 fields in 57 s vs ~25 min whole-doc)</div></div>
  <div class="card-strong"><div class="big">874</div><div class="lbl">Automated pytest tests (874 offline tests + 13 opt-in live tests; CI on GitHub)</div></div>
</div>
<table>
  <tr><th>Benchmark / Evaluation (<code>docs/RESULTS.md</code>)</th><th>Measured Result</th><th>Methodology &amp; Honest Caveat</th></tr>
  <tr><td><b>Loss engine vs. hand-checked worked example</b></td><td><b>100% exact match</b></td><td><code>Decimal</code> half-up; verified on every Cat XL layer, reinstatement, RIP, and Quota Share formula.</td></tr>
  <tr><td><b>Governing clause retrieval &amp; citation audit</b></td><td><b>186/186 retrieved · 185/186 verified</b></td><td>Firestore 768-d vector search; 184 text-layer verified + 1 scanned endorsement transcribed; 1 unverified withheld.</td></tr>
  <tr><td><b>Clause Courtroom live on Cloud Run</b></td><td><b>3 of 3 verified live (100% rate)</b></td><td>Both counsel verified on first attempt; $10.3M to $26.0M money at stake priced live; 0 unsupported figures (build 6fbb81c).</td></tr>
  <tr><td><b>Corrupted quote rejection (Verifier unit suite)</b></td><td><b>40/40 rejected (0 false withholds)</b></td><td>Normalised + word-aligned <code>...</code> ellipsis fragment matcher + Gemini 3.8 Flash semantic check (offline stubs suite).</td></tr>
  <tr><td><b>Untraceable numbers in AI-written reports</b></td><td><b>0 across all live runs</b></td><td>Deterministic Python post-check compares every figure in reporter/arbiter prose against engine output.</td></tr>
  <tr><td><b>Honest limitations &amp; unmeasured items</b></td><td colspan="2">Extraction prompt was tuned on the 8 synthetic wordings (99.5% is an upper bound; blind set is next). Manual effort savings (30–60h → 3.5–8h) are labelled <i>simulated estimates</i> pending a timed practitioner study.</td></tr>
</table>"""
    ))

    # Slide 12 — Template Page 13: Additional Details/Future Development (if any)
    s.append(content_slide(
        "Additional Details/Future Development (if any)",
        """<div class="grid2">
  <div class="card">
    <p style="margin-top:0"><b>The Money Moment: Why Per-Party Pricing Matters</b></p>
    <p style="font-size:19px"><b>1. Live Jebi Courtroom (T-004 Storm-Surge Exclusion, p.2 cl.8):</b><br>
    At a 20% surge share (recorded live run), total ceded drops by <b>−$11.64M</b> ($39.58M → $27.94M), the insurer's net cost rises by <b>+$10.31M</b>, all reinsurers save <b>−$10.31M</b>, and Lion Re saves <b>−$1.34M</b> (at 30% share: Lion Re saves <b>−$2.44M</b>).</p>
    <p style="font-size:19px"><b>2. Worked Example Hours-Clause Asymmetry (What-if):</b><br>
    On a $54.4M loss across L1 (20 xs 10, Lion Re 25%) and L2 (30 xs 30, Lion Re 10%), splitting 1 event into 2 ($35.0M + $19.4M) cuts market ceded recoveries by <b>−22.5% (−$10.0M)</b>, but <b>increases Lion Re's net loss by +7.4% (+$0.51M, $6.82M → $7.33M)</b> because the split shifts burden down into Layer 1 where Lion Re's share is concentrated.</p>
    <p style="margin-top:12px"><b>Team Techno Crackers — Roles</b></p>
    <p style="font-size:18px;margin:4px 0">• <b>Venket Raj S (Lead):</b> Architecture, Cloud Run / Firestore / IAM deployment &amp; observability<br>
    • <b>Malik Chandra Pandian:</b> Reinsurance domain modelling, <code>Decimal</code> loss engine &amp; worked examples<br>
    • <b>Arun Veerappan:</b> ADK 2.11 workflows, RAG extraction, citation verifier &amp; Clause Courtroom<br>
    • <b>Nagaraj:</b> React 18 + TypeScript + custom SVG choropleth UI, 5-step analyst workflow, tour &amp; exports</p>
  </div>
  <div class="card">
    <p style="margin-top:0"><b>Future Development Roadmap (Designed / Investigated)</b></p>
    <ul style="font-size:20px">
      <li><b>Real multi-shock hours-clause dispute (2024 Hualien Earthquake, Taiwan):</b> Investigated in repo — its real aftershock cluster ~20 days later creates a genuine second occurrence worth ~$11–15M per treaty under the hours clause.</li>
      <li><b>Calibrated per-country vulnerability curves:</b> Adding insurance-penetration &amp; insured-loss wind curves for the Philippines (bringing Typhoon Haiyan into the live selector).</li>
      <li><b>Vendor hazard footprint adapter:</b> Plugging licensed Moody's RMS or Verisk footprints behind our typed hazard interface.</li>
      <li><b>Authenticated treaty upload &amp; BigQuery exposure:</b> Scaling from 24 treaties to enterprise treaty packs.</li>
      <li><b>Live USGS / GDACS Pub/Sub intake &amp; A2A/MCP endpoint:</b> Automated first-view triggers on disaster alerts and broker-agent interoperability.</li>
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
    <div class="muted" style="margin-top:2px">Apache-2.0 licence · 874 offline tests + 13 opt-in live tests · GitHub Actions CI · Full architecture &amp; assumptions in <code>docs/</code>.</div>
  </li>
  <li style="margin-bottom:18px">
    <b>Demo Video Link (3 Minutes)</b><br>
    <a href="{VIDEO}" style="font-size:23px;font-family:Consolas,monospace;color:#1fa99c;text-decoration:none">{VIDEO}</a>
    <div class="muted" style="margin-top:2px">3-minute walkthrough (2m 45s) of the reinsurance problem, live ~15 s Typhoon Jebi analysis, scanned endorsement transcription, and Clause Courtroom.</div>
  </li>
  <li style="margin-bottom:18px">
    <b>Final Product Link</b><br>
    <a href="{LIVE}" style="font-size:23px;font-family:Consolas,monospace;color:#1fa99c;text-decoration:none">{LIVE}</a>
    <div class="muted" style="margin-top:2px">Live on Google Cloud Run (us-central1) · No sign-up required · Click <b>Instant replay</b> (~6 s) or <b>Run live</b> (~15 s) · 9-stop guided tour included.</div>
  </li>
  <li style="margin-bottom:18px">
    <b>Submission Package Folder (All Artifacts)</b><br>
    <a href="{FOLDER}" style="font-size:23px;font-family:Consolas,monospace;color:#1fa99c;text-decoration:none">{FOLDER}</a>
    <div class="muted" style="margin-top:2px">Complete Google Drive submission folder containing pitch deck, demo video, architectural documentation, and verification reports.</div>
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
