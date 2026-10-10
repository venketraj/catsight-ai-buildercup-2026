"""Treaty wording generation — DR-2, and FR-ENDORSE for the scanned page.

Produces, for each of the eight treaties that have a wording:

  * a Markdown source, so the content is diffable in review;
  * a PDF of 6-15 pages with numbered clauses and page numbers;
  * ground-truth entries for every extractable field, with the page and
    clause number the extractor should cite.

**Ground-truth page numbers are read back out of the rendered PDF, not
predicted.** The builder renders the document, reopens it with pypdf, finds
each clause heading in the extracted text, and records the page it actually
landed on. That matters because QA-4 scores citation page accuracy at >= 95%:
an answer key whose page numbers were guessed would make that metric
meaningless, and a layout change would silently invalidate it.

## The scanned endorsement (FR-ENDORSE)

W4 carries a final page that is a rasterised image with **no text layer** - a
stamped, signed endorsement that changes its windstorm hours window from 72 to
168. The base clause still says 72. Gemini has to read the image to find the
override, and the verifier has to quote-match against the stored
transcription rather than against extracted text, which is why
`GroundTruthField.source` distinguishes the two.

There is a test asserting that page really has no extractable text, because an
endorsement the text layer gives away for free tests nothing.

## On the "blind" set — read this before quoting its score

DR-2 and risk 5 in the win-readiness review ask for wordings written by
someone **outside the prompt work**, so that an accuracy score is not
self-graded. This module cannot satisfy that: the same author writes the
wordings, the answer key and later the extraction prompts.

What `--blind` produces is a **structural holdout**: three wordings built from
a different seed, different clause ordering, different phrasing styles and
planted features not drawn from the documented W1-W8 table. It is genuinely
useful - it catches a prompt tuned to one layout - and it is genuinely *not* a
blind set.

Report it as a holdout, never as a blind set, until a human outside the prompt
work has written one. Overstating it is the kind of claim a judge checks.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from random import Random
from typing import Any, Iterable, Sequence

from ingest.seed_portfolio import Portfolio, Treaty, WordingSpec, build_portfolio
from ingest.wording_clauses import (
    BOILERPLATE,
    DECOYS,
    PREAMBLE,
    Clause,
    GroundTruthField,
    hours_phrase,
)

__all__ = [
    "ENDORSED_WORDING",
    "ENDORSEMENT_BASE_HOURS",
    "ENDORSEMENT_EFFECTIVE_HOURS",
    "build_clauses",
    "render_markdown",
    "render_pdf",
    "endorsement_image",
    "clause_pages",
    "build_all",
    "main",
]

#: W4 is the one that gains a scanned endorsement. It is chosen because DR-2
#: does not pin W4's hours clause, so an override there adds a planted feature
#: without contradicting the documented table - and because it is not W1, whose
#: terms the money moment depends on.
ENDORSED_WORDING = "W4"
ENDORSEMENT_BASE_HOURS = 72
ENDORSEMENT_EFFECTIVE_HOURS = 168

#: Per-wording phrasing style for the hours clause, so extraction is tested
#: against several registers rather than one. W8 deliberately hides it inside
#: a definition with no digits in the headline sentence.
HOURS_STYLE: dict[str, str] = {
    "W1": "plain",
    "W2": "spelled",
    "W3": "period",
    "W4": "plain",
    "W5": "spelled",
    "W6": "plain",
    "W7": "period",
    "W8": "words",
}

PERIL_NAMES = {"WS": "Windstorm", "EQ": "Earthquake", "FL": "Flood", "OTHER": "any other peril"}


# --------------------------------------------------------------------------- #
# Clause assembly
# --------------------------------------------------------------------------- #


def build_clauses(treaty: Treaty, wording: WordingSpec) -> tuple[Clause, ...]:
    """The full clause list for one wording, in document order."""
    style = HOURS_STYLE[wording.wording_id]
    is_qs = treaty.type == "QS"

    clauses: list[Clause] = [
        Clause(
            number="1",
            title="Preamble and Interpretation",
            paragraphs=PREAMBLE,
            clause_type="OTHER",
        ),
        _business_covered(treaty, wording),
        _territory(treaty, wording),
        _period(treaty),
    ]

    if is_qs:
        clauses.append(_quota_share_cession(treaty))
        clauses.append(_no_hours_clause())
        clauses.extend(_proportional_conditions())
    else:
        clauses.append(_loss_occurrence(treaty, wording, style))
        clauses.append(_limit_and_retention(treaty))
        clauses.append(_reinstatement(treaty, wording))

    clauses.append(_exclusions(treaty, wording))
    clauses.extend(DECOYS)
    clauses.append(_currency(treaty))
    clauses.append(_definitions(treaty, wording, style))
    clauses.extend(BOILERPLATE)

    if wording.wording_id == ENDORSED_WORDING:
        clauses.append(_endorsement_reference())

    return tuple(clauses)


def _business_covered(treaty: Treaty, wording: WordingSpec) -> Clause:
    perils = " and ".join(PERIL_NAMES[p] for p in treaty.perils)
    kind = (
        "a quota share of the Reinsured's retained account"
        if treaty.type == "QS"
        else "excess of loss reinsurance"
    )
    return Clause(
        number="2",
        title="Business Covered",
        paragraphs=(
            f"This Agreement provides {kind} in respect of the Reinsured's "
            f"property account, limited to loss arising from {perils}, written "
            "or renewed by the Reinsured during the Period and classified by the "
            "Reinsured in accordance with its own practice at inception.",
            "Business written on a facultative basis, financial guarantee "
            "business, and business written through a pool or association in "
            "which participation is compulsory are excluded from the scope of "
            "this Agreement unless specifically agreed in writing.",
        ),
        clause_type="OTHER",
        fields=(
            GroundTruthField("type", treaty.type),
            GroundTruthField("perils", list(treaty.perils)),
        ),
    )


def _territory(treaty: Treaty, wording: WordingSpec) -> Clause:
    include = ", ".join(treaty.territory["include"])
    excluded = treaty.territory.get("exclude", ())
    paragraphs = [
        f"The territorial scope of this Agreement is {include}, in respect of "
        "risks situate within that territory at the time of the Loss Occurrence."
    ]
    if excluded:
        pretty = ", ".join(excluded)
        paragraphs.append(
            "Notwithstanding the foregoing, risks situate in "
            f"{_region_prose(excluded)} are excluded from this Agreement, and no "
            "loss arising there shall be recoverable hereunder "
            f"(territory codes: {pretty})."
        )
    else:
        paragraphs.append(
            "No part of the territory stated above is carved out of this "
            "Agreement. Risks situate outside that territory are not covered, "
            "whether or not the Reinsured's policy extends to them."
        )
    return Clause(
        number="3",
        title="Territorial Scope",
        paragraphs=tuple(paragraphs),
        clause_type="TERRITORY",
        fields=(
            GroundTruthField("territory.include", list(treaty.territory["include"])),
            GroundTruthField("territory.exclude", list(excluded)),
        ),
    )


def _region_prose(codes: Sequence[str]) -> str:
    from ingest.regions_reference import ALL_REGIONS

    names = {r.code: r.name for r in ALL_REGIONS}
    return ", ".join(f"{names.get(code, code)} Prefecture" for code in codes)


def _period(treaty: Treaty) -> Clause:
    return Clause(
        number="4",
        title="Period",
        paragraphs=(
            f"This Agreement attaches at 00:00 hours local standard time on "
            f"{treaty.inception} and expires at 24:00 hours local standard time "
            f"on {treaty.expiry}, both days inclusive.",
            "This Agreement applies to Loss Occurrences happening during the "
            "Period, irrespective of when the underlying policies were written, "
            "subject to Clause 13.2.",
        ),
        clause_type="PERIOD",
        fields=(
            GroundTruthField("inception", treaty.inception),
            GroundTruthField("expiry", treaty.expiry),
        ),
    )


def _loss_occurrence(treaty: Treaty, wording: WordingSpec, style: str) -> Clause:
    hours = treaty.hours_clause

    if wording.wording_id == "W8":
        # DR-2's extraction-robustness case: the operative period lives in the
        # Definitions clause, and Clause 5 only cross-references it. Stating
        # the figure in both places would claim the same field on two pages,
        # which makes QA-4's citation page accuracy unscoreable for it.
        return Clause(
            number="5",
            title="Loss Occurrence",
            paragraphs=(
                "The term Loss Occurrence bears the meaning given to it in "
                "Clause 12, and the period there stated governs as respects "
                "Windstorm and Earthquake alike.",
                "As respects Flood, and as respects any other peril covered "
                f"hereunder, the period is {hours_phrase(hours['FL'], style)}.",
                "The Reinsured may elect the moment from which each such period "
                "commences, provided that it shall not be earlier than the "
                "moment at which the first individual loss comprising the Loss "
                "Occurrence first occurs, and provided that no two periods in "
                "respect of the same event shall overlap.",
            ),
            clause_type="HOURS",
            fields=(GroundTruthField("hours_clause.FL", hours["FL"]),),
        )

    base_ws = (
        ENDORSEMENT_BASE_HOURS
        if wording.wording_id == ENDORSED_WORDING
        else hours["WS"]
    )

    paragraphs = [
        "The term Loss Occurrence means the sum of all individual losses "
        "directly occasioned by one event, provided that only those individual "
        "losses which first occur during the period defined below shall be "
        "included in that Loss Occurrence.",
        "As respects Windstorm, all individual losses which first occur during "
        f"{hours_phrase(base_ws, style)} shall be deemed to constitute a single "
        "Loss Occurrence. As respects Earthquake, the corresponding period is "
        f"{hours_phrase(hours['EQ'], style)}. As respects Flood, and as respects "
        f"any other peril covered hereunder, the period is "
        f"{hours_phrase(hours['FL'], style)}.",
        "The Reinsured may elect the moment from which each such period "
        "commences, provided that it shall not be earlier than the moment at "
        "which the first individual loss comprising the Loss Occurrence first "
        "occurs, and provided that no two periods in respect of the same event "
        "shall overlap.",
        "Where a single event gives rise to individual losses falling within "
        "more than one such period, each period constitutes a separate Loss "
        "Occurrence and the retention and limit stated in the Schedule apply "
        "separately to each.",
    ]
    fields = [
        GroundTruthField("hours_clause.EQ", hours["EQ"]),
        GroundTruthField("hours_clause.FL", hours["FL"]),
    ]
    if wording.wording_id == ENDORSED_WORDING:
        # The base text says 72; the endorsement overrides to 168. Both are
        # ground truth, distinguished by source.
        fields.append(GroundTruthField("hours_clause.WS.base", base_ws))
    else:
        fields.append(GroundTruthField("hours_clause.WS", hours["WS"]))

    return Clause(
        number="5",
        title="Loss Occurrence",
        paragraphs=tuple(paragraphs),
        clause_type="HOURS",
        fields=tuple(fields),
    )


def _no_hours_clause() -> Clause:
    return Clause(
        number="5",
        title="Loss Occurrence",
        paragraphs=(
            "This Agreement is written on a proportional basis and does not "
            "respond per Loss Occurrence. No hours clause applies. The "
            "Reinsurers' liability follows the fortunes of the Reinsured in "
            "respect of each risk ceded, subject only to the event limit stated "
            "in Clause 6.",
        ),
        clause_type="HOURS",
        fields=(GroundTruthField("hours_clause.WS", 0),),
    )


def _proportional_conditions() -> tuple[Clause, ...]:
    """Conditions a quota share carries and an excess-of-loss treaty does not.

    Without these the proportional wording comes out shorter than DR-2's
    6-page minimum, and it would also be unrealistic: accounts, commission and
    portfolio provisions are the substance of a proportional treaty.
    """
    return (
        Clause(
            number="7",
            title="Accounts and Remittances",
            paragraphs=(
                "The Reinsured shall render quarterly accounts within sixty days "
                "of the close of each quarter, showing the premiums ceded, the "
                "commission allowed, the losses paid and the balance due.",
                "Balances shall be remitted within thirty days of the rendering "
                "of the account. Balances in favour of the Reinsured may be "
                "offset against balances in favour of the Reinsurers in "
                "accordance with Clause 17.2.",
                "The Reinsured shall maintain a reserve for outstanding losses "
                "in respect of the business ceded, and shall advise the "
                "Reinsurers of the amount of that reserve with each annual "
                "account.",
            ),
            clause_type="OTHER",
        ),
        Clause(
            number="7.1",
            title="Commission and Profit Commission",
            paragraphs=(
                "The Reinsurers shall allow the Reinsured a ceding commission on "
                "the premiums ceded, at the rate stated in the Schedule, in "
                "consideration of the Reinsured's acquisition costs and expenses "
                "of management.",
                "In addition, the Reinsurers shall allow a profit commission "
                "calculated on the result of this Agreement over the period "
                "stated in the Schedule, computed after deduction of the "
                "Reinsurers' management expenses and after carrying forward any "
                "deficit from the preceding period.",
            ),
            clause_type="OTHER",
        ),
        Clause(
            number="7.2",
            title="Portfolio Transfer",
            paragraphs=(
                "On the inception of this Agreement the Reinsured may transfer to "
                "the Reinsurers their proportion of the unearned premium reserve "
                "in respect of the business ceded, and the Reinsurers shall "
                "assume liability for all losses occurring thereafter on that "
                "business.",
                "On termination of this Agreement the Reinsurers may be relieved "
                "of liability for losses occurring after the date of termination "
                "by returning to the Reinsured their proportion of the unearned "
                "premium reserve as at that date.",
            ),
            clause_type="OTHER",
        ),
    )


def _limit_and_retention(treaty: Treaty) -> Clause:
    paragraphs = [
        "The Reinsurers shall be liable for the amount by which the Reinsured's "
        "ultimate net loss in respect of each Loss Occurrence exceeds the "
        "retention stated below, subject to the limit stated below for that "
        "layer. Amounts are expressed in millions of "
        f"{treaty.currency}.",
    ]
    fields: list[GroundTruthField] = []
    for layer in treaty.layers:
        paragraphs.append(
            f"Layer {layer.layer_no}: the Reinsurers shall pay the amount by "
            f"which the ultimate net loss exceeds {layer.retention:,.1f}, but "
            f"not more than {layer.limit:,.1f} in respect of any one Loss "
            f"Occurrence. The premium for this layer is {layer.premium:,.2f}."
        )
        fields.extend(
            [
                GroundTruthField(f"layers.{layer.layer_no}.retention", layer.retention),
                GroundTruthField(f"layers.{layer.layer_no}.limit", layer.limit),
                GroundTruthField(f"layers.{layer.layer_no}.premium", layer.premium),
            ]
        )
    return Clause(
        number="6",
        title="Limit and Retention",
        paragraphs=tuple(paragraphs),
        clause_type="LIMIT",
        fields=tuple(fields),
    )


def _quota_share_cession(treaty: Treaty) -> Clause:
    qs = treaty.qs or {}
    return Clause(
        number="6",
        title="Cession and Event Limit",
        paragraphs=(
            f"The Reinsured cedes and the Reinsurers accept "
            f"{qs.get('cession_pct', 0) * 100:,.0f} per cent of the Reinsured's "
            "property account as described in Clause 2, the Reinsurers following "
            "the fortunes of the Reinsured in respect of each risk so ceded.",
            "The Reinsurers' liability in respect of all losses arising out of "
            f"any one catastrophe event shall not exceed "
            f"{qs.get('event_limit', 0):,.1f} million {treaty.currency}, however "
            "many risks or policies are involved.",
        ),
        clause_type="LIMIT",
        fields=(
            GroundTruthField("qs.cession_pct", qs.get("cession_pct")),
            GroundTruthField("qs.event_limit", qs.get("event_limit")),
        ),
    )


def _reinstatement(treaty: Treaty, wording: WordingSpec) -> Clause:
    reinst = wording.reinstatements
    count = int(reinst["count"])
    rate = float(reinst["rate"])
    rate_words = (
        "without additional premium"
        if rate == 0.0
        else f"at {rate * 100:,.0f} per cent additional premium"
    )
    plural = "reinstatement" if count == 1 else "reinstatements"
    paragraphs = [
        f"In the event of the limit of any layer being exhausted or partially "
        f"exhausted by loss, that limit shall be automatically reinstated from "
        f"the moment of the Loss Occurrence giving rise to the loss, for "
        f"{count} such {plural}, {rate_words}.",
        "Reinstatement premium is calculated pro rata as to amount, being the "
        "proportion that the amount of limit reinstated bears to the full limit "
        "of the layer, applied to the premium for that layer. It is not pro "
        "rated as to time.",
        "When the reinstatements provided above are exhausted, no further "
        "reinstatement is available, and the Reinsurers' aggregate liability "
        "for the layer is limited to the limit multiplied by one plus the number "
        "of reinstatements stated.",
    ]
    return Clause(
        number="7",
        title="Reinstatement",
        paragraphs=tuple(paragraphs),
        clause_type="REINSTATEMENT",
        fields=(
            GroundTruthField("reinstatements.count", count),
            GroundTruthField("reinstatements.rate", rate),
            GroundTruthField("reinstatements.basis", "pro rata as to amount"),
        ),
    )


def _exclusions(treaty: Treaty, wording: WordingSpec) -> Clause:
    paragraphs = [
        "This Agreement does not cover loss, damage, cost or expense directly or "
        "indirectly arising out of any of the following."
    ]
    prose = {
        "war": "War, invasion, hostilities, civil war, rebellion or insurrection, "
        "whether war be declared or not.",
        "nuclear": "Nuclear reaction, nuclear radiation or radioactive "
        "contamination, however caused.",
        "cyber": "The use or operation of any computer system or computer network "
        "as a means for inflicting harm, and any loss of use of or damage to data.",
        "storm surge": "Storm surge, being the rise in sea level caused by "
        "meteorological conditions, whether or not accompanied by windstorm, and "
        "whether or not a named windstorm has been declared by any authority.",
        "flood when written as such": "Flood, where the Reinsured's original "
        "policy writes flood as a separately rated and separately stated peril. "
        "Flood arising as a direct consequence of a covered windstorm and not "
        "separately rated is not excluded by this paragraph.",
        "earthquake": "Earthquake, earthquake shock, volcanic eruption and "
        "tsunami, this Agreement being written in respect of windstorm only.",
    }
    for exclusion in treaty.exclusions:
        paragraphs.append(prose.get(exclusion, f"{exclusion.capitalize()}."))

    if "storm surge" not in treaty.exclusions and "WS" in treaty.perils:
        paragraphs.append(
            "For the avoidance of doubt, storm surge is covered hereunder where "
            "it is directly occasioned by a windstorm which has been named by "
            "the competent meteorological authority, and loss from such surge "
            "forms part of the same Loss Occurrence as the windstorm."
        )

    return Clause(
        number="8",
        title="Exclusions",
        paragraphs=tuple(paragraphs),
        clause_type="EXCLUSION",
        fields=(GroundTruthField("exclusions", list(treaty.exclusions)),),
    )


def _currency(treaty: Treaty) -> Clause:
    return Clause(
        number="14",
        title="Currency",
        paragraphs=(
            f"All amounts stated in this Agreement are expressed in "
            f"{treaty.currency}. Where the Reinsured settles a loss in another "
            "currency, conversion shall be at the rate of exchange ruling on the "
            "date of settlement.",
        ),
        clause_type="OTHER",
        fields=(GroundTruthField("currency", treaty.currency),),
    )


def _definitions(treaty: Treaty, wording: WordingSpec, style: str) -> Clause:
    paragraphs = [
        "Ultimate Net Loss means the amount actually paid by the Reinsured in "
        "settlement of losses for which it is liable, after deduction of all "
        "recoveries, salvages and other reinsurances, but before deduction of "
        "any recovery under this Agreement.",
        "Named Windstorm means a windstorm to which the competent "
        "meteorological authority has assigned a name, from the moment that "
        "name is assigned.",
    ]
    fields: list[GroundTruthField] = []

    if wording.wording_id == "W8":
        # W8 hides the operative period here, in words, with no digits, behind
        # a cross-reference from Clause 5. An extractor keyed on digits, or one
        # that stops at the clause titled "Loss Occurrence", misses it.
        paragraphs.append(
            "Loss Occurrence, as respects Windstorm and as respects Earthquake "
            "alike, means all individual losses which first occur within "
            f"{hours_phrase(treaty.hours_clause['WS'], style)} of one another, "
            "arising out of and directly occasioned by one event, the Reinsured "
            "electing the commencement of that period subject to Clause 5."
        )
        fields.append(GroundTruthField("hours_clause.WS", treaty.hours_clause["WS"]))
        fields.append(GroundTruthField("hours_clause.EQ", treaty.hours_clause["EQ"]))

    return Clause(
        number="12",
        title="Definitions",
        paragraphs=tuple(paragraphs),
        clause_type="OTHER",
        fields=tuple(fields),
    )


def _endorsement_reference() -> Clause:
    return Clause(
        number="15",
        title="Endorsements",
        paragraphs=(
            "The Endorsement attached to this Agreement forms part of it and "
            "takes effect from the date stated in it. Where the Endorsement and "
            "the body of this Agreement are inconsistent, the Endorsement "
            "prevails.",
        ),
        clause_type="OTHER",
    )


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def render_markdown(treaty: Treaty, wording: WordingSpec, clauses: Iterable[Clause]) -> str:
    """Markdown source, so wording content is diffable in review."""
    lines = [
        f"# {wording.wording_id} - Catastrophe Reinsurance Agreement",
        "",
        f"**Reinsured:** {treaty.cedent_id}  ",
        f"**Treaty:** {treaty.treaty_id}  ",
        f"**Type:** {treaty.type}  ",
        f"**Period:** {treaty.inception} to {treaty.expiry}  ",
        f"**Currency:** {treaty.currency}",
        "",
        "> Synthetic document. Fictional parties. Drafted for the CatSight "
        "prototype in the register of catastrophe excess-of-loss reinsurance "
        "contracts; not copied from any real agreement, and of no legal effect.",
        "",
    ]
    for clause in clauses:
        lines.append(f"## {clause.number}. {clause.title}")
        lines.append("")
        for paragraph in clause.paragraphs:
            lines.append(paragraph)
            lines.append("")
    return "\n".join(lines)


def endorsement_image(
    treaty: Treaty,
    base_hours: int = ENDORSEMENT_BASE_HOURS,
    effective_hours: int = ENDORSEMENT_EFFECTIVE_HOURS,
    width: int = 1700,
    height: int = 2200,
):
    """A stamped, signed endorsement page as a raster image (FR-ENDORSE-1).

    Rendered as an image so the resulting PDF page carries **no text layer**.
    Gemini has to read it visually, which is the whole point: an endorsement
    the text extractor hands over for free tests nothing.

    Deliberately imperfect - skewed, off-white, with a stamp ring over the
    text and a signature scrawl - because real endorsements arrive as scans
    and phone photographs, not as clean renders.
    """
    from PIL import Image, ImageDraw, ImageFilter

    image = Image.new("RGB", (width, height), (246, 243, 236))
    draw = ImageDraw.Draw(image)

    def text(xy, content, size=34, fill=(28, 28, 32)):
        draw.text(xy, content, fill=fill, font_size=size)

    margin = 150
    text((margin, 150), "ENDORSEMENT NO. 1", 52)
    text((margin, 230), f"attaching to and forming part of Treaty {treaty.treaty_id}", 32)
    text((margin, 285), f"Reinsured: {treaty.cedent_id}", 32)
    draw.line([(margin, 350), (width - margin, 350)], fill=(90, 90, 95), width=3)

    body = [
        "It is hereby agreed that, with effect from inception,",
        "Clause 5 (Loss Occurrence) of the above Agreement is",
        "amended as respects Windstorm only, so that the period",
        "therein stated shall read:",
        "",
        f"        {effective_hours} CONSECUTIVE HOURS",
        "",
        f"in place of the {base_hours} consecutive hours previously stated.",
        "",
        "All other terms, clauses and conditions of the Agreement",
        "remain unaltered.",
    ]
    y = 430
    for line in body:
        text((margin, y), line, 38)
        y += 62

    text((margin, y + 60), "Signed for and on behalf of the Reinsurers:", 32)
    sig_y = y + 190
    draw.line(
        [
            (margin + 20, sig_y), (margin + 90, sig_y - 55), (margin + 150, sig_y + 20),
            (margin + 215, sig_y - 45), (margin + 300, sig_y + 10),
            (margin + 360, sig_y - 30), (margin + 430, sig_y + 5),
        ],
        fill=(26, 38, 92), width=6, joint="curve",
    )
    draw.line([(margin, sig_y + 70), (margin + 560, sig_y + 70)], fill=(90, 90, 95), width=2)
    text((margin, sig_y + 90), "Authorised Signatory", 26, (80, 80, 85))

    stamp = Image.new("RGBA", (680, 320), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.rounded_rectangle([6, 6, 674, 314], radius=24, outline=(168, 42, 48, 220), width=8)
    sd.text((48, 70), "RECEIVED", fill=(168, 42, 48, 225), font_size=92)
    sd.text((48, 190), "UNDERWRITING", fill=(168, 42, 48, 215), font_size=54)
    stamp = stamp.rotate(-11, expand=True, resample=Image.BICUBIC)
    image.paste(stamp, (width - 880, 300), stamp)

    image = image.rotate(0.6, expand=False, resample=Image.BICUBIC, fillcolor=(246, 243, 236))
    return image.filter(ImageFilter.GaussianBlur(0.4))


def render_pdf(
    treaty: Treaty,
    wording: WordingSpec,
    clauses: Sequence[Clause],
    path: Path,
) -> int:
    """Render the wording to PDF. Returns the page count.

    DR-2 requires 6-15 pages, numbered clauses and page numbers.
    """
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as PdfImage
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body", parent=styles["BodyText"], fontName="Times-Roman",
        fontSize=10.5, leading=15, alignment=TA_JUSTIFY, spaceAfter=7,
    )
    heading = ParagraphStyle(
        "ClauseHeading", parent=styles["Heading2"], fontName="Times-Bold",
        fontSize=11.5, leading=15, spaceBefore=11, spaceAfter=5,
    )
    doc_title = ParagraphStyle(
        "DocTitle", parent=styles["Title"], fontName="Times-Bold", fontSize=15, leading=20,
    )
    meta = ParagraphStyle("Meta", parent=body, fontSize=9.5, leading=13)

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Times-Roman", 8.5)
        canvas.drawCentredString(A4[0] / 2, 13 * mm, f"Page {canvas.getPageNumber()}")
        canvas.drawString(20 * mm, 13 * mm, f"{wording.wording_id} / {treaty.treaty_id}")
        canvas.drawRightString(A4[0] - 20 * mm, 13 * mm, "Synthetic - no legal effect")
        canvas.restoreState()

    story: list[Any] = [
        Paragraph(f"{wording.wording_id} - Catastrophe Reinsurance Agreement", doc_title),
        Spacer(1, 7 * mm),
        Paragraph(
            f"Reinsured: {treaty.cedent_id}<br/>Treaty reference: {treaty.treaty_id}<br/>"
            f"Type: {treaty.type}<br/>Period: {treaty.inception} to {treaty.expiry}<br/>"
            f"Currency: {treaty.currency}",
            meta,
        ),
        Spacer(1, 5 * mm),
        Paragraph(
            "<i>Synthetic document. Fictional parties. Drafted for the CatSight "
            "prototype in the register of catastrophe excess-of-loss reinsurance "
            "contracts; not copied from any real agreement, and of no legal "
            "effect.</i>",
            meta,
        ),
        Spacer(1, 6 * mm),
    ]
    for clause in clauses:
        story.append(Paragraph(f"{clause.number}. {clause.title}", heading))
        for paragraph in clause.paragraphs:
            story.append(Paragraph(paragraph, body))

    endorsement_png: Path | None = None
    if wording.wording_id == ENDORSED_WORDING:
        endorsement_png = path.with_name(f"{path.stem}_endorsement.png")
        endorsement_image(treaty).save(endorsement_png, "PNG", dpi=(200, 200))
        story.append(PageBreak())
        story.append(PdfImage(str(endorsement_png), width=170 * mm, height=220 * mm))

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm,
        title=f"{wording.wording_id} {treaty.treaty_id}", author="CatSight (synthetic)",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)

    if endorsement_png and endorsement_png.exists():
        endorsement_png.unlink()

    import pypdf

    return len(pypdf.PdfReader(str(path)).pages)


# --------------------------------------------------------------------------- #
# Ground truth - page numbers read back out of the rendered PDF
# --------------------------------------------------------------------------- #


def clause_pages(pdf_path: Path, clauses: Sequence[Clause]) -> dict[str, int]:
    """Map clause number to the 1-based page it was rendered on.

    Read back from the PDF rather than predicted, so the answer key's page
    numbers cannot drift from the document when the layout changes.
    """
    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    pages = [" ".join((page.extract_text() or "").split()) for page in reader.pages]
    found: dict[str, int] = {}
    for clause in clauses:
        needle = " ".join(f"{clause.number}. {clause.title}".split())
        for index, text in enumerate(pages, start=1):
            if needle in text:
                found[clause.number] = index
                break
    return found


def _ground_truth_rows(
    treaty: Treaty, wording: WordingSpec, clauses: Sequence[Clause], pages: dict[str, int]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for clause in clauses:
        for gt in clause.fields:
            rows.append(
                {
                    "treaty_id": treaty.treaty_id,
                    "wording_id": wording.wording_id,
                    "field": gt.field,
                    "expected_value": gt.expected_value,
                    "page": pages.get(clause.number),
                    "clause_no": clause.number,
                    "clause_type": clause.clause_type,
                    "source": gt.source,
                }
            )
    return rows


def _endorsement_rows(treaty: Treaty, wording: WordingSpec, page_count: int) -> list[dict]:
    """The scanned endorsement's own ground truth (FR-ENDORSE).

    The override sits on the final page, which has no text layer, so its
    source is `transcription`: the verifier must quote-match against the
    stored transcription and badge it differently (FR-ENDORSE-3).
    """
    return [
        {
            "treaty_id": treaty.treaty_id,
            "wording_id": wording.wording_id,
            "field": "hours_clause.WS",
            "expected_value": ENDORSEMENT_EFFECTIVE_HOURS,
            "page": page_count,
            "clause_no": "END-1",
            "clause_type": "HOURS",
            "source": "transcription",
        },
        {
            "treaty_id": treaty.treaty_id,
            "wording_id": wording.wording_id,
            "field": "endorsement.overrides",
            "expected_value": "hours_clause.WS",
            "page": page_count,
            "clause_no": "END-1",
            "clause_type": "HOURS",
            "source": "transcription",
        },
    ]


def _decoy_rows(clauses: Sequence[Clause], treaty: Treaty, pages: dict[str, int]) -> list[dict]:
    """Decoy passages, recorded so QA-4 can measure precision.

    A flag citing one of these is a false positive, not a near miss.
    """
    return [
        {
            "treaty_id": treaty.treaty_id,
            "clause_no": clause.number,
            "clause_title": clause.title,
            "page": pages.get(clause.number),
            "why": "mentions a number of hours but is not the hours clause",
        }
        for clause in clauses
        if clause.is_decoy
    ]


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #


def build_all(
    portfolio: Portfolio | None = None,
    out_dir: Path | str = "data/synthetic/wordings",
    *,
    blind: bool = False,
) -> dict[str, Any]:
    """Build every wording, its PDF, and the combined answer key."""
    from ingest.seed_portfolio import WORDINGS

    portfolio = portfolio or build_portfolio()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    ground_truth: list[dict[str, Any]] = []
    decoys: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []

    for index, wording in enumerate(WORDINGS, start=1):
        treaty = portfolio.treaty(f"T-{index:03d}")
        clauses = build_clauses(treaty, wording)

        md_path = out / f"{wording.wording_id.lower()}.md"
        md_path.write_text(render_markdown(treaty, wording, clauses), encoding="utf-8")

        pdf_path = out / f"{wording.wording_id.lower()}.pdf"
        page_count = render_pdf(treaty, wording, clauses, pdf_path)
        pages = clause_pages(pdf_path, clauses)

        rows = _ground_truth_rows(treaty, wording, clauses, pages)
        if wording.wording_id == ENDORSED_WORDING:
            rows += _endorsement_rows(treaty, wording, page_count)
        ground_truth += rows
        decoys += _decoy_rows(clauses, treaty, pages)

        manifest.append(
            {
                "wording_id": wording.wording_id,
                "treaty_id": treaty.treaty_id,
                "pdf": pdf_path.name,
                "markdown": md_path.name,
                "pages": page_count,
                "clauses": len(clauses),
                "fields": len(rows),
                "decoys": sum(1 for c in clauses if c.is_decoy),
                "has_scanned_endorsement": wording.wording_id == ENDORSED_WORDING,
                "note": wording.note,
            }
        )

    (out / "ground_truth.json").write_text(
        json.dumps(
            {
                "_note": (
                    "Answer key for QA-3 (field accuracy) and QA-4 (flag quality). "
                    "Page numbers are read back out of the rendered PDFs, not "
                    "predicted, so they cannot drift from the documents. Rows with "
                    "source=transcription come from the scanned endorsement, which "
                    "has no text layer."
                ),
                "fields": ground_truth,
                "decoys": decoys,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "out_dir": out,
        "wordings": len(manifest),
        "fields": len(ground_truth),
        "decoys": len(decoys),
        "manifest": manifest,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: python -m ingest.build_wordings [--out DIR]"""
    import argparse

    parser = argparse.ArgumentParser(description="Generate the synthetic treaty wordings (DR-2).")
    parser.add_argument("--out", default="data/synthetic/wordings", help="output directory")
    args = parser.parse_args(argv)

    result = build_all(out_dir=args.out)
    print(
        f"{result['wordings']} wordings, {result['fields']} ground-truth fields, "
        f"{result['decoys']} decoys -> {result['out_dir']}"
    )
    for entry in result["manifest"]:
        flag = "  [scanned endorsement]" if entry["has_scanned_endorsement"] else ""
        print(
            f"  {entry['wording_id']}  {entry['pages']:>2} pages  "
            f"{entry['clauses']:>2} clauses  {entry['fields']:>2} fields{flag}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
