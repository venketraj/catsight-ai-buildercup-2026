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
    "[VIDEO_LINK_PLACEHOLDER — Insert Public YouTube / Demo Video URL (< 3:00)]",
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
      <div><span style="display:inline-block;width:68px">b.</span>Team leader name: <b>Venket Raj S</b> <span style="font-size:24px;color:#3c4043">(Team: Venket Raj S · Malik Chandra Pandian · Arun Veerappan · Nagaraj)</span></div>
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
    <p><b>CatSight</b> tells a reinsurer in <b>about 15 seconds</b> after a typhoon or earthquake which treaties respond, what each layer pays, and which contract clauses could change that number — with every quote machine-verified against the source PDF page.</p>
    <p><b>Real-world anchor — Typhoon Jebi (Japan, Sept 2018):</b></p>
    <ul>
      <li><b>857,284 claims</b> and <b>¥1,067.8bn paid</b> — the largest ever for a Japanese typhoon <span class="tag">GIAJ</span></li>
      <li>First modelled range was <b>$3–5.5bn</b>, arriving ~10 days after landfall <span class="tag">Moody's RMS</span></li>
      <li>Final insured loss grew to <b>~$13bn</b> (~3× the early estimate), driven by storm surge &amp; overlapping claims <span class="tag">Swiss Re</span></li>
    </ul>
    <p><b>Why it matters:</b> While industry numbers take weeks, reinsurance teams spend <b>30–60 analyst-hours (2–4 business days)</b> assembling spreadsheets and re-reading 25+ exposed PDF treaty wordings by hand.</p>
  </div>
  <div class="card-strong">
    <table>
      <tr><th>Source / Workflow</th><th>Arrives</th><th>Scope &amp; Limitation</th></tr>
      <tr><td>Modeller event response</td><td><b>4–20 days</b></td><td>Market range; ignores your PDF wording</td></tr>
      <tr><td>PERILS (Japan typhoon)</td><td><b>6 weeks</b></td><td>Industry loss index, not treaty-level</td></tr>
      <tr><td>Verisk PCS Japan</td><td><b>up to 90 days</b></td><td>Market-wide index for events ≥ $2bn</td></tr>
      <tr><td>Manual in-house review</td><td><b>2–4 days</b></td><td>Error-prone spreadsheets; missed endorsements</td></tr>
      <tr><td><b>CatSight (Lion Re's book)</b></td><td><b>0.7 s math · ~10–12 s full AI check</b></td><td><b>Event × exposure × layers × verified PDF wording</b></td></tr>
    </table>
    <p class="muted" style="margin-top:14px">Replays real public hazard footprints (NOAA IBTrACS, USGS ShakeMap) over a synthetic book of <b>24 treaties written for 8 fictional insurers</b> in Japan, the Philippines, and Taiwan.</p>
  </div>
</div>"""
    ))

    # Slide 3 — Template Page 4: Opportunities
    s.append(content_slide(
        "Opportunities",
        """<ul style="font-size:26px;line-height:1.45;margin-top:4px">
  <li style="margin-bottom:18px">
    <b>How different is it from any of the other existing ideas?</b>
    <div style="font-size:21px;margin-top:6px;color:#202124">
      • <b>CatSight is the join:</b> Cat-model event response (Moody's RMS, Verisk) computes hazard footprints and modelled loss on pre-coded terms, stopping at the PDF wording. Document-AI platforms extract clauses at underwriting time, stopping before the storm track and layer math. Generic LLM chat over PDFs hallucinates arithmetic and lacks an audit trail.<br>
      • <b>Complementary by design:</b> CatSight is not a cat model; a licensed vendor footprint can plug directly into our typed hazard interface.
    </div>
  </li>
  <li style="margin-bottom:18px">
    <b>How will it be able to solve the problem?</b>
    <div style="font-size:21px;margin-top:6px;color:#202124">
      • <b>Deterministic Python loss engine (<code>Decimal</code>, half-up, 874 automated tests):</b> Computes regional gross loss, Cat XL layer erosion, burn %, reinstatements, reinstatement premium (RIP), and Quota Share cessions in <b>0.7–1.0 s</b> — the LLM never does arithmetic.<br>
      • <b>RAG over Firestore vector search + 2-Stage Verifier Loop:</b> Retrieves governing clauses per treaty (252 vectors, 768-d <code>gemini-embedding-001</code>) and verifies every quote via deterministic normalised/fragment matching + a Gemini 3.8 Flash semantic support check (with 1 revision retry before withholding).
    </div>
  </li>
  <li style="margin-bottom:10px">
    <b>USP of the proposed solution</b>
    <div style="font-size:21px;margin-top:6px;color:#202124">
      • <b>Adversarial Clause Courtroom:</b> Two blind parallel AI counsel argue opposing readings of ambiguous clauses (e.g., T-004 storm-surge exclusion) from verified quotes while the engine prices both readings per party (Insurer, All Reinsurers, Lion Re).<br>
      • <b>Scanned Endorsement Detective:</b> Transcribes rasterised, stamped PDF pages with no text layer (T-004 p.7: 168h overrides 72h) and badges them <code>transcribed</code>.<br>
      • <b>Community &amp; APAC Impact:</b> 91% of APAC's 2023 cat losses ($65bn) were uninsured <span class="tag">MAS</span>, and 48% of insurers license no cat model <span class="tag">Aon 2025</span>. Faster, less-disputed reinsurance settlements help primary insurers pay households and SMEs sooner.
    </div>
  </li>
</ul>""",
        bold_title=True,
    ))

    # Slide 4 — Template Page 5: List of features offered by the solution
    s.append(content_slide(
        "List of features offered by the solution",
        """<table>
  <tr><th style="width:24%">Feature</th><th style="width:46%">What it gives the catastrophe analyst</th><th style="width:30%">Verification &amp; Trust Guardrail</th></tr>
  <tr><td><b>1. Treaty Matching &amp; Layer Waterfall</b></td><td>Matches all 24 treaties on peril ∩ territory ∩ period (with exclusion reasons for the other 11); computes per-layer ceded, burn %, reinstatements, RIP, and 3-party net positions (Insurer, All Reinsurers, Lion Re).</td><td>Deterministic <code>Decimal</code> engine; 100% match against hand-checked worked examples.</td></tr>
  <tr><td><b>2. "How was this calculated?"</b></td><td>Step-by-step audit drawer per treaty: regional peak wind/MMI, vulnerability curve damage %, insured value × damage % = gross loss, and exact layer formula with citations.</td><td>Every intermediate number is inspectable and reproducible.</td></tr>
  <tr><td><b>3. Cited Wording Flags &amp; Endorsement Detective</b></td><td>Flags clauses that bite on <i>this</i> event (e.g., T-004 storm-surge exclusion on Jebi's 329 cm Osaka tide) and transcribes scanned image endorsements (T-004 p.7: 168h replaces 72h).</td><td>2-stage verifier loop; unverified flags visibly withheld (<code>n verified · k withheld</code>); scanned pages badged <code>transcribed</code>.</td></tr>
  <tr><td><b>4. Clause Courtroom</b></td><td>Parallel ADK agents (<code>cedent_counsel</code> ∥ <code>reinsurer_counsel</code>) argue opposing readings from verified quotes (with 1 revision retry &amp; <code>...</code> fragment matching); engine prices both readings; Arbiter summarises without deciding.</td><td>Issue-spotting only; human analyst records the decision with an audit timestamp.</td></tr>
  <tr><td><b>5. Bounded What-if &amp; Grounded Q&amp;A</b></td><td>Interactive hours-clause scenario pricing (clearly labelled HYPOTHETICAL on Jebi's 9-hour window) and live follow-up Q&amp;A over treaty clauses.</td><td>Typed, bounded tool schema (0–50% share); every figure in AI prose is checked against engine output.</td></tr>
  <tr><td><b>6. Instant Replay, 9-Stop Tour &amp; Word Export</b></td><td>6-second zero-cost replay of a recorded real run, live SSE streaming (~15 s), colour-blind-safe themes, keyboard navigation, and Word (<code>.docx</code>) &amp; Markdown memos.</td><td>Every export carries the methodology version, verification counts, and mandatory disclaimers.</td></tr>
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
        """<div class="grid2">
  <div class="card">
    <p style="margin-top:0"><b>Five-Step Progressive Analyst Interface Wireframe</b></p>
    <div class="box" style="margin-bottom:10px;border-width:2px"><b>Sticky Summary Bar (Always Visible)</b>Gross Claims ($733.04M) · Reinsurers Pay ($490.92M) · Lion Re Net ($70.36M) · Verified Flags · Elapsed · Method v1.0</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">
      <div class="box"><b>Step 1 · Event</b>Track / ShakeMap + JMA facts + Instant Replay (6 s) or Run Live (~15 s)</div>
      <div class="box"><b>Step 2 · Who's Hit</b>MapLibre choropleth map of 34 prefectures + accessible exposure table</div>
    </div>
    <div class="box" style="margin-bottom:10px"><b>Step 3 · What It Costs</b>3-party bar + 13 responding treaties + expandable "How was this calculated?" layer formulas</div>
    <div class="box" style="margin-bottom:10px"><b>Step 4 · Clauses That Matter</b>Verified wording flags + Side-by-side PDF/Clause Drawer + Parallel Clause Courtroom + What-if</div>
    <div class="box"><b>Step 5 · Decide &amp; Export</b>Analyst position selector + figure-checked Executive Report + Word (<code>.docx</code>) / Markdown export</div>
  </div>
  <div class="card">
    <p style="margin-top:0"><b>Trust Architecture: 2-Stage Citation Verification Funnel</b></p>
    <div class="box" style="margin-bottom:8px"><b>Candidate Wording Flag / Counsel Argument</b>Model cites <code>treaty_id</code>, <code>page</code>, <code>clause_no</code>, and verbatim <code>quote</code></div>
    <div class="arrow">▼ Stage 1: Deterministic Python Quote Match</div>
    <div class="box" style="margin-bottom:8px"><b>Word-Aligned Normalised &amp; Ellipsis (<code>...</code>) Matcher</b>Checks quote against stored Firestore chunk; tags scanned pages as <code>transcribed</code> (40/40 corrupted quotes caught in unit suite)</div>
    <div class="arrow">▼ Stage 2: Semantic Support Check (Gemini 3.8 Flash)</div>
    <div class="box" style="margin-bottom:8px"><b>Entailment &amp; Event-Window Verification</b>Verifies quote + event window (<code>start</code>, <code>end</code>, <code>duration_h</code>) + JMA facts directly support the flag</div>
    <div class="arrow">▼ Fail → 1 Revision Retry with Feedback → Still Fails?</div>
    <div class="box" style="border-width:2.5px"><b>Visibly Withheld (Never Shown as a Finding)</b>UI displays <code>n of n displayed citations verified · k withheld</code> with exact reason</div>
  </div>
</div>"""
    ))

    # Slide 7 — Template Page 8: Architecture diagram of the proposed solution
    s.append(content_slide(
        "Architecture diagram of the proposed solution",
        """<div style="display:grid;grid-template-columns:1.15fr 0.85fr;gap:34px">
  <div>
    <div class="box"><b>Analyst / Judge Browser (React 18 + TypeScript + MapLibre GL)</b>Same-origin HTTPS · REST + POST Server-Sent Events (<code>fetch</code> ReadableStream with 15 s heartbeat)</div>
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
  <tr><td><b>Python 3.12 · FastAPI · React 18 · MapLibre</b></td><td>Core engine &amp; frontend</td><td>Deterministic <code>Decimal</code> loss engine (874 pytest tests), python-docx memo generator, accessible TypeScript UI.</td></tr>
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
  <div class="card-strong"><div class="big">874</div><div class="lbl">Automated pytest tests (861 offline unit + 13 live GCP; CI on GitHub)</div></div>
</div>
<table>
  <tr><th>Benchmark / Evaluation (<code>docs/RESULTS.md</code>)</th><th>Measured Result</th><th>Methodology &amp; Honest Caveat</th></tr>
  <tr><td><b>Loss engine vs. hand-checked worked example</b></td><td><b>100% exact match</b></td><td><code>Decimal</code> half-up; verified on every Cat XL layer, reinstatement, RIP, and Quota Share formula.</td></tr>
  <tr><td><b>Governing clause retrieval &amp; citation audit</b></td><td><b>186/186 retrieved · 185/186 verified</b></td><td>Firestore 768-d vector search; 184 text-layer verified + 1 scanned endorsement transcribed; 1 unverified withheld.</td></tr>
  <tr><td><b>Corrupted quote rejection (Verifier unit suite)</b></td><td><b>40/40 rejected (0 false withholds)</b></td><td>Normalised + word-aligned <code>...</code> ellipsis fragment matcher + Gemini 3.8 Flash semantic check.</td></tr>
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
    • <b>Nagaraj:</b> React 18 + TypeScript + MapLibre UI, 5-step analyst workflow, tour &amp; exports</p>
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
        f"""<ul style="font-size:32px;line-height:1.8;margin-top:20px">
  <li style="margin-bottom:26px">
    <b>GitHub Public Repository</b><br>
    <span style="font-size:26px;font-family:Consolas,monospace">{REPO}</span>
    <div class="muted" style="margin-top:4px">Apache-2.0 licence · 874 automated pytest tests · GitHub Actions CI · Full architecture, per-field citation audit &amp; assumptions in <code>docs/</code>.</div>
  </li>
  <li style="margin-bottom:26px">
    <b>Demo Video Link (3 Minutes)</b><br>
    <span class="placeholder" style="margin-top:6px">{VIDEO}</span>
    <div class="muted" style="margin-top:6px">3-minute walkthrough of the reinsurance problem, live ~15 s Typhoon Jebi analysis, scanned endorsement transcription, and Clause Courtroom.</div>
  </li>
  <li style="margin-bottom:26px">
    <b>Final Product Link</b><br>
    <span style="font-size:26px;font-family:Consolas,monospace">{LIVE}</span>
    <div class="muted" style="margin-top:4px">Live on Google Cloud Run (us-central1) · No sign-up required · Click <b>Instant replay</b> (~6 s) or <b>Run live</b> (~15 s) · 9-stop guided tour included.</div>
  </li>
</ul>
<div class="card" style="margin-top:24px;padding:14px 20px">
  <p class="muted" style="margin:0"><b>Disclaimers &amp; Data Attribution:</b> {DISCLAIMER} Jebi, Hagibis, Haiyan and Noto were real events in which people died. Portfolio, insurers and treaty wordings are 100% synthetic; hazard data is public (NOAA IBTrACS v04r01, USGS ShakeMap, Natural Earth).</p>
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
