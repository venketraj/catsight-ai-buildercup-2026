"""Clause content for the synthetic treaty wordings — DR-2.

Original prose written in the register of catastrophe excess-of-loss
reinsurance contracts. Nothing here is copied from a real contract: publicly
filed wordings were read for *style* only, as RESEARCH_FINDINGS section D9
requires, and every sentence below is composed for this project.

Two things make these wordings worth something as a test set:

**Phrasing variation.** The same term is expressed differently across
wordings - "72 consecutive hours", "seventy-two (72) consecutive hours", "a
period of ninety-six (96) consecutive hours" - and sometimes buried inside a
definition rather than given its own clause. An extractor that pattern-matches
on digits will fail W8 and pass W1, which is the point.

**Decoys.** Ten passages mention a number of hours without being the hours
clause: notification deadlines, inspection windows, arbitration service
periods. They exist so QA-4 can measure *precision*, not just recall. A model
that returns every "hours" passage scores badly, as it should.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "GroundTruthField",
    "Clause",
    "NUMBER_WORDS",
    "hours_phrase",
    "DECOYS",
    "BOILERPLATE",
    "PREAMBLE",
]


@dataclass(frozen=True)
class GroundTruthField:
    """One extractable field, and what the extractor should produce for it."""

    field: str
    expected_value: Any
    #: Set when the value comes from a scanned endorsement rather than the
    #: text layer, so verification can be badged differently (FR-ENDORSE-3).
    source: str = "text"


@dataclass(frozen=True)
class Clause:
    number: str
    title: str
    paragraphs: tuple[str, ...]
    clause_type: str  # HOURS | EXCLUSION | TERRITORY | REINSTATEMENT | LIMIT | PERIOD | OTHER
    fields: tuple[GroundTruthField, ...] = ()
    is_decoy: bool = False


NUMBER_WORDS: dict[int, str] = {
    24: "twenty-four",
    48: "forty-eight",
    72: "seventy-two",
    96: "ninety-six",
    120: "one hundred and twenty",
    168: "one hundred and sixty-eight",
    240: "two hundred and forty",
}


def hours_phrase(hours: int, style: str) -> str:
    """Render an hours figure in one of several contract registers.

    `style` is what makes extraction non-trivial:
      plain    72 consecutive hours
      spelled  seventy-two (72) consecutive hours
      period   a period of seventy-two (72) consecutive hours
      words    seventy-two consecutive hours      (no digits at all)
    """
    words = NUMBER_WORDS.get(hours)
    if words is None:
        raise ValueError(f"no word form for {hours} hours")
    if style == "plain":
        return f"{hours} consecutive hours"
    if style == "spelled":
        return f"{words} ({hours}) consecutive hours"
    if style == "period":
        return f"a period of {words} ({hours}) consecutive hours"
    if style == "words":
        return f"{words} consecutive hours"
    raise ValueError(f"unknown hours phrasing style {style!r}")


PREAMBLE = (
    "This Agreement is made between the Reinsured named in the Schedule and the "
    "Reinsurers subscribing hereto. It records the terms on which the Reinsurers "
    "agree to indemnify the Reinsured in respect of Loss Occurrences happening "
    "during the Period of this Agreement, subject to the limits, retentions, "
    "exclusions and conditions set out below.",
    "The Schedule forms part of this Agreement. Where the Schedule and the body "
    "of this Agreement are inconsistent, the Schedule prevails. Where an "
    "Endorsement attached hereto and signed by the parties is inconsistent with "
    "either, the Endorsement prevails from the date stated in it.",
    "Words defined in Clause 12 bear the defined meaning wherever they appear in "
    "this Agreement, whether or not capitalised in the clause in which they are "
    "used.",
)


# --------------------------------------------------------------------------- #
# Decoys — DR-2 requires at least ten
#
# Each one mentions a number of hours, or otherwise looks like a term the
# extractor wants, without being it. They are what stops a high recall score
# from hiding poor precision.
# --------------------------------------------------------------------------- #

DECOYS: tuple[Clause, ...] = (
    Clause(
        number="9.1",
        title="Notification of Loss",
        paragraphs=(
            "The Reinsured shall advise the Reinsurers of any Loss Occurrence "
            "likely to involve this Agreement as soon as practicable, and in any "
            "event within 72 hours of the Reinsured becoming aware of it. Failure "
            "to advise within that time does not of itself prejudice the "
            "Reinsured's right of recovery, but the Reinsurers may decline any "
            "part of a claim to the extent they are prejudiced by the delay.",
            "Advice given under this clause is for notification only and does not "
            "determine the number of Loss Occurrences, which is governed "
            "exclusively by Clause 5.",
        ),
        clause_type="OTHER",
        is_decoy=True,
    ),
    Clause(
        number="9.2",
        title="Loss Advices and Cash Calls",
        paragraphs=(
            "Where the Reinsured's paid losses in respect of a single Loss "
            "Occurrence exceed one half of the retention stated in the Schedule, "
            "the Reinsured may make a cash call, and the Reinsurers shall settle "
            "within 168 hours of receipt of a properly completed advice.",
            "A cash call is a payment on account. It is not an admission of "
            "liability and does not affect the computation of the Reinsurers' "
            "ultimate liability.",
        ),
        clause_type="OTHER",
        is_decoy=True,
    ),
    Clause(
        number="9.3",
        title="Inspection of Records",
        paragraphs=(
            "The Reinsurers or their appointed representatives may inspect the "
            "Reinsured's records relating to this Agreement at any reasonable time "
            "during the Period and for three years afterwards, on giving not less "
            "than 48 hours written notice.",
        ),
        clause_type="OTHER",
        is_decoy=True,
    ),
    Clause(
        number="10.1",
        title="Premium Payment",
        paragraphs=(
            "The premium stated in the Schedule is payable in four equal "
            "instalments, the first within 30 days of inception and thereafter "
            "quarterly. Instalments unpaid for more than 720 hours after the due "
            "date bear interest at the rate stated in the Schedule.",
        ),
        clause_type="OTHER",
        is_decoy=True,
    ),
    Clause(
        number="11.1",
        title="Arbitration",
        paragraphs=(
            "Any dispute arising out of this Agreement shall be referred to "
            "arbitration in Singapore. The party seeking arbitration shall serve "
            "written notice, and the other party shall appoint its arbitrator "
            "within 336 hours of service.",
            "The arbitrators shall interpret this Agreement as an honourable "
            "engagement rather than merely as a legal obligation, and shall be "
            "relieved of all judicial formality.",
        ),
        clause_type="OTHER",
        is_decoy=True,
    ),
    Clause(
        number="11.2",
        title="Service of Suit",
        paragraphs=(
            "Should the Reinsurers fail to pay any amount claimed to be due, they "
            "will, at the request of the Reinsured, submit to the jurisdiction of "
            "a court of competent jurisdiction, and will comply with all "
            "requirements necessary to give that court jurisdiction. Nothing in "
            "this clause constitutes a waiver of the Reinsurers' right to "
            "arbitration under Clause 11.1.",
        ),
        clause_type="OTHER",
        is_decoy=True,
    ),
    Clause(
        number="12.4",
        title="Definition: Business Day",
        paragraphs=(
            "Business Day means a day other than a Saturday, Sunday or public "
            "holiday in the territory stated in the Schedule. Where this Agreement "
            "requires an act within a stated number of hours, hours falling "
            "outside a Business Day are counted unless the contrary is stated.",
        ),
        clause_type="OTHER",
        is_decoy=True,
    ),
    Clause(
        number="12.5",
        title="Definition: Act of God Period",
        paragraphs=(
            "Act of God Period is not used in this Agreement. Where it appears in "
            "any slip, endorsement or correspondence relating to this Agreement it "
            "shall be read as a reference to Loss Occurrence as defined in "
            "Clause 5, and the hours there stated shall govern.",
        ),
        clause_type="OTHER",
        is_decoy=True,
    ),
    Clause(
        number="13.2",
        title="Extended Expiration",
        paragraphs=(
            "If a Loss Occurrence is in progress at the moment this Agreement "
            "expires, the Reinsurers remain liable as if the whole of that Loss "
            "Occurrence had happened during the Period, provided no part of it is "
            "recoverable under any renewal of this Agreement.",
            "For the purposes of this clause only, a Loss Occurrence is in "
            "progress if the first individual loss comprising it occurred before "
            "expiry, even where the remaining 24 hours or more of the relevant "
            "window fall after expiry.",
        ),
        clause_type="OTHER",
        is_decoy=True,
    ),
    Clause(
        number="13.3",
        title="Sanctions",
        paragraphs=(
            "No Reinsurer shall be liable to pay any claim or provide any benefit "
            "under this Agreement to the extent that doing so would expose that "
            "Reinsurer to any sanction, prohibition or restriction under United "
            "Nations resolutions or the trade or economic sanctions, laws or "
            "regulations of any applicable jurisdiction.",
        ),
        clause_type="OTHER",
        is_decoy=True,
    ),
)


# --------------------------------------------------------------------------- #
# Boilerplate
#
# Standard conditions carrying no extractable field and no decoy. Real
# catastrophe treaties are mostly this, and including it does two useful
# things: it brings each document into DR-2's 6-15 page range honestly rather
# than by padding, and it gives retrieval a realistic amount of irrelevant
# text to work through. A RAG demo over four pages of nothing but material
# clauses is not a demo of anything.
# --------------------------------------------------------------------------- #

BOILERPLATE: tuple[Clause, ...] = (
    Clause(
        number="16.1",
        title="Ultimate Net Loss and Loss Settlements",
        paragraphs=(
            "The Reinsurers shall follow the Reinsured's settlements in all "
            "matters falling within the terms of this Agreement, provided those "
            "settlements are within the terms and conditions of the original "
            "policies and within the terms and conditions of this Agreement.",
            "All loss settlements made by the Reinsured, including compromise "
            "settlements and the establishment of funds for the settlement of "
            "losses, shall be binding upon the Reinsurers, and the Reinsurers "
            "agree to pay or allow as the case may be their share of each such "
            "settlement in accordance with this Agreement.",
            "Nothing in this clause obliges the Reinsurers to follow a "
            "settlement made otherwise than in accordance with the terms of the "
            "original policy, or made ex gratia, unless they have consented in "
            "writing in advance.",
        ),
        clause_type="OTHER",
    ),
    Clause(
        number="16.2",
        title="Salvage and Subrogation",
        paragraphs=(
            "The Reinsurers shall be credited with their share of salvage, being "
            "reimbursement obtained or recovery made by the Reinsured, less the "
            "actual cost of obtaining it, other than from another reinsurance "
            "recoverable hereunder.",
            "The Reinsured shall enforce its rights of subrogation, and any "
            "amount recovered shall be apportioned between the parties in "
            "proportion to their respective interests in the loss, after "
            "deduction of the costs of recovery.",
        ),
        clause_type="OTHER",
    ),
    Clause(
        number="16.3",
        title="Claims Cooperation",
        paragraphs=(
            "The Reinsured shall keep the Reinsurers informed of all claims and "
            "circumstances likely to give rise to a claim under this Agreement, "
            "and shall furnish such particulars and information as the "
            "Reinsurers may reasonably require.",
            "The Reinsurers may, at their own expense, associate with the "
            "Reinsured in the defence or control of any claim or proceeding "
            "which may involve this Agreement, and the Reinsured shall "
            "cooperate in every reasonable respect.",
        ),
        clause_type="OTHER",
    ),
    Clause(
        number="17.1",
        title="Several Liability",
        paragraphs=(
            "The subscribing Reinsurers' obligations under this Agreement are "
            "several and not joint, and are limited solely to the extent of each "
            "Reinsurer's individual subscription. The subscribing Reinsurers are "
            "not responsible for the subscription of any co-subscribing "
            "Reinsurer who for any reason does not satisfy all or part of its "
            "obligations.",
        ),
        clause_type="OTHER",
    ),
    Clause(
        number="17.2",
        title="Offset",
        paragraphs=(
            "Each party may offset any balance, whether on account of premium, "
            "commission, claims, losses, adjustments or otherwise, due from one "
            "party to the other under this Agreement, provided that in the event "
            "of the insolvency of either party, offset shall only be permitted "
            "to the extent allowed by applicable law.",
        ),
        clause_type="OTHER",
    ),
    Clause(
        number="17.3",
        title="Insolvency",
        paragraphs=(
            "In the event of the insolvency of the Reinsured, the reinsurance "
            "proceeds payable under this Agreement shall be payable to the "
            "Reinsured or to its liquidator, receiver or statutory successor on "
            "the basis of the liability of the Reinsured, without diminution "
            "because of the insolvency.",
            "The liquidator, receiver or statutory successor shall give written "
            "notice of the pendency of any claim against the Reinsured which may "
            "involve this Agreement within a reasonable time after the claim is "
            "filed, and the Reinsurers may investigate and interpose any defence "
            "in the proceeding in which the claim is to be adjudicated.",
        ),
        clause_type="OTHER",
    ),
    Clause(
        number="17.4",
        title="Errors and Omissions",
        paragraphs=(
            "Any inadvertent delay, omission or error on the part of either "
            "party shall not relieve either party of liability under this "
            "Agreement, provided the delay, omission or error is rectified "
            "promptly after discovery, and provided neither party is thereby "
            "placed in a worse position than it would have occupied had the "
            "delay, omission or error not occurred.",
        ),
        clause_type="OTHER",
    ),
    Clause(
        number="18.1",
        title="Taxes and Deductions",
        paragraphs=(
            "The Reinsured is liable for all taxes on premiums paid to the "
            "Reinsurers under this Agreement, other than taxes which the "
            "Reinsurers are obliged to bear by the law of their own "
            "jurisdiction.",
            "All amounts payable under this Agreement are payable without "
            "deduction or withholding except as required by law. Where a "
            "deduction or withholding is required, the paying party shall "
            "provide the other with evidence of it on request.",
        ),
        clause_type="OTHER",
    ),
    Clause(
        number="18.2",
        title="Intermediary",
        paragraphs=(
            "All communications relating to this Agreement, including notices, "
            "statements, premiums, return premiums, commissions, taxes, losses, "
            "loss adjustment expense, salvages and loss settlements, shall be "
            "transmitted through the intermediary named in the Schedule.",
            "Payments by the Reinsured to the intermediary shall be deemed "
            "payment to the Reinsurers. Payments by the Reinsurers to the "
            "intermediary shall be deemed payment to the Reinsured only to the "
            "extent that those payments are actually received by the Reinsured.",
        ),
        clause_type="OTHER",
    ),
    Clause(
        number="18.3",
        title="Special Termination",
        paragraphs=(
            "Either party may terminate this Agreement immediately by written "
            "notice if the other party becomes insolvent, has its licence to "
            "transact business withdrawn, has its policyholders' surplus reduced "
            "by twenty per cent or more from the amount at inception, or merges "
            "with or is acquired by another entity.",
            "On termination under this clause, the Reinsurers remain liable for "
            "Loss Occurrences happening before the effective date of "
            "termination, and premium shall be adjusted pro rata as to time.",
        ),
        clause_type="OTHER",
    ),
    Clause(
        number="18.4",
        title="Confidentiality and Governing Law",
        paragraphs=(
            "Each party shall keep confidential all information received from "
            "the other in connection with this Agreement, other than "
            "information which is or becomes public through no fault of the "
            "receiving party, or which is required to be disclosed by law or by "
            "a regulator.",
            "This Agreement is governed by and construed in accordance with the "
            "law stated in the Schedule, and the parties submit to arbitration "
            "under Clause 11.1 in respect of any dispute arising out of it.",
        ),
        clause_type="OTHER",
    ),
)
