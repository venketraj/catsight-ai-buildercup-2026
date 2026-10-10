"""FR-INGEST-2 — clause-aware chunking.

Run against the real generated wording PDFs, because the thing being tested
is how a rendered document actually extracts, not how a fixture string does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.build_wordings import ENDORSED_WORDING, build_all
from ingest.chunking import (
    BODY_PHRASES,
    CLAUSE_TYPE_KEYWORDS,
    Chunk,
    chunk_pages,
    chunk_pdf,
    classify_clause,
    page_texts,
)


@pytest.fixture(scope="module")
def wordings(tmp_path_factory) -> Path:
    return build_all(out_dir=tmp_path_factory.mktemp("wordings"))["out_dir"]


@pytest.fixture(scope="module")
def w1_chunks(wordings) -> tuple[Chunk, ...]:
    return chunk_pdf("T-001", wordings / "w1.pdf")


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #


def test_a_wording_chunks_into_one_passage_per_clause(w1_chunks):
    assert len(w1_chunks) > 25
    numbers = [c.clause_no for c in w1_chunks]
    assert len(numbers) == len(set(numbers))  # no clause chunked twice
    assert all(c.clause_no for c in w1_chunks)


def test_chunk_ids_are_stable_and_namespaced_by_treaty(w1_chunks):
    """Stable ids make re-ingestion idempotent and let a citation be traced
    back to the exact passage that produced it."""
    for chunk in w1_chunks:
        assert chunk.chunk_id.startswith("T-001#")
        assert chunk.treaty_id == "T-001"


def test_chunking_is_deterministic(wordings):
    first = chunk_pdf("T-001", wordings / "w1.pdf")
    second = chunk_pdf("T-001", wordings / "w1.pdf")
    assert first == second


def test_every_chunk_records_the_page_its_heading_appeared_on(w1_chunks):
    """A citation points at the page where the clause starts."""
    for chunk in w1_chunks:
        assert chunk.page >= 1
        assert chunk.pages_spanned
        assert chunk.page == min(chunk.pages_spanned)


def test_clause_pages_advance_through_the_document(w1_chunks):
    pages = [c.page for c in w1_chunks]
    assert pages == sorted(pages)


def test_running_headers_and_footers_are_stripped(w1_chunks):
    """Left in, the page stamp appears in every chunk and pollutes both the
    embedding and any quote the verifier tries to match."""
    for chunk in w1_chunks:
        assert "Synthetic - no legal effect" not in chunk.text
        assert not chunk.text.strip().startswith("Page ")


def test_an_empty_chunk_is_rejected():
    with pytest.raises(ValueError, match="cannot be empty"):
        Chunk(
            treaty_id="T-001", chunk_id="x", page=1, clause_no="1",
            clause_title="t", clause_type="OTHER", text="   ",
        )


def test_a_chunk_page_must_be_one_based():
    with pytest.raises(ValueError, match="page must be"):
        Chunk(
            treaty_id="T-001", chunk_id="x", page=0, clause_no="1",
            clause_title="t", clause_type="OTHER", text="body",
        )


# --------------------------------------------------------------------------- #
# Classification — the decoys are the test
# --------------------------------------------------------------------------- #


def test_each_wording_has_exactly_one_hours_clause(wordings):
    # W8 is excluded deliberately: it cross-references from Clause 5 into the
    # Definitions clause, so two chunks legitimately type as HOURS.
    """Over-classification matters: FR-WORD filters on clause_type, so a
    decoy typed HOURS gets retrieved as if it were the material clause."""
    for index, name in enumerate(("w1", "w2", "w3", "w5", "w7"), start=1):
        chunks = chunk_pdf(f"T-00{index}", wordings / f"{name}.pdf")
        hours = [c for c in chunks if c.clause_type == "HOURS"]
        assert len(hours) == 1, (name, [c.clause_title for c in hours])
        assert hours[0].clause_title == "Loss Occurrence"


def test_the_decoys_are_not_classified_as_material_clauses(wordings):
    """Notification of Loss says "within 72 hours"; Loss Advices mentions a
    retention; Definition: Business Day mentions territory. A body-keyword
    classifier types all three wrongly."""
    chunks = chunk_pdf("T-001", wordings / "w1.pdf")
    by_title = {c.clause_title: c.clause_type for c in chunks}
    assert by_title["Notification of Loss"] == "OTHER"
    assert by_title["Loss Advices and Cash Calls"] == "OTHER"
    assert by_title["Inspection of Records"] == "OTHER"
    assert by_title["Definition: Business Day"] == "OTHER"
    assert by_title["Arbitration"] == "OTHER"


def test_material_clauses_are_classified_from_their_headings(wordings):
    chunks = chunk_pdf("T-001", wordings / "w1.pdf")
    by_title = {c.clause_title: c.clause_type for c in chunks}
    assert by_title["Loss Occurrence"] == "HOURS"
    assert by_title["Territorial Scope"] == "TERRITORY"
    assert by_title["Period"] == "PERIOD"
    assert by_title["Limit and Retention"] == "LIMIT"
    assert by_title["Reinstatement"] == "REINSTATEMENT"
    assert by_title["Exclusions"] == "EXCLUSION"


def test_classification_prefers_the_heading_over_the_body():
    """The heading is the drafter's own classification. The body is noise,
    and the decoys exploit that."""
    assert classify_clause("Notification of Loss", "advise within 72 consecutive hours") == "OTHER"
    assert classify_clause("Loss Occurrence", "nothing relevant here") == "HOURS"


def test_a_chunk_with_no_heading_falls_back_to_narrow_body_phrases():
    """The page-fallback path has no title to use, so a restricted phrase set
    applies - narrow enough that a decoy does not fire."""
    assert classify_clause(None, "all losses which first occur within 72 consecutive hours") == "HOURS"
    assert classify_clause(None, "advise the Reinsurers within 72 hours of becoming aware") == "OTHER"
    assert classify_clause(None, "the limit shall be automatically reinstated") == "REINSTATEMENT"
    assert classify_clause(None, "nothing in particular") == "OTHER"


def test_the_body_phrase_set_is_deliberately_narrow():
    """A bare "hours" would fire on every decoy. "consecutive hours" is the
    operative phrase and none of the decoys use it."""
    hours_phrases = dict(BODY_PHRASES)["HOURS"]
    assert "hours" not in hours_phrases
    assert "consecutive hours" in hours_phrases


def test_w8s_hidden_hours_clause_is_found_through_its_body(wordings):
    """W8 puts its operative period inside a clause titled "Definitions".

    A heading like "Definitions" or "Endorsement" describes structure, not
    subject matter, so for those the body is the better signal and the narrow
    phrase set applies. That is what lets DR-2's robustness case be
    classified correctly instead of being filed as OTHER.
    """
    chunks = chunk_pdf("T-008", wordings / "w8.pdf")
    definitions = next(c for c in chunks if c.clause_title == "Definitions")
    assert "consecutive hours" in definitions.text.lower()
    assert definitions.clause_type == "HOURS"


def test_w8_has_two_hours_typed_chunks_and_the_figure_is_in_the_definition(wordings):
    """Clause 5 cross-references, the Definitions clause carries the figure.
    Both are legitimately HOURS-typed; only one states the period."""
    chunks = chunk_pdf("T-008", wordings / "w8.pdf")
    hours = {c.clause_title: c for c in chunks if c.clause_type == "HOURS"}
    assert set(hours) == {"Loss Occurrence", "Definitions"}
    assert "seventy-two consecutive hours" in hours["Definitions"].text.lower()
    assert "meaning given to it in" in hours["Loss Occurrence"].text


def test_structural_headings_defer_to_the_body():
    """A bare "Definitions" carries no subject matter. The decoys named
    "Definition: ..." still type as OTHER, because their bodies do not use
    the operative phrase."""
    assert classify_clause("Definitions", "within 72 consecutive hours") == "HOURS"
    assert classify_clause("Endorsement", "the period shall read 168 CONSECUTIVE HOURS") == "HOURS"
    assert classify_clause("Definition: Business Day", "hours falling outside") == "OTHER"
    assert classify_clause("Definition: Act of God Period", "the hours there stated") == "OTHER"


def test_the_keyword_table_lists_specific_families_before_general_ones():
    order = [clause_type for clause_type, _ in CLAUSE_TYPE_KEYWORDS]
    assert order.index("HOURS") < order.index("PERIOD")
    assert order.index("REINSTATEMENT") < order.index("LIMIT")


# --------------------------------------------------------------------------- #
# Image-only pages — FR-ENDORSE
# --------------------------------------------------------------------------- #


def test_an_image_only_page_is_detected_and_skipped_without_a_transcription(wordings):
    """Skipped, not emitted empty. The caller has to notice: a silently
    dropped endorsement is how an override gets missed."""
    chunks = chunk_pdf("T-004", wordings / f"{ENDORSED_WORDING.lower()}.pdf")
    assert all(c.source == "text" for c in chunks)
    pages = page_texts(wordings / f"{ENDORSED_WORDING.lower()}.pdf")
    assert len(pages) == 7
    assert max(c.page for c in chunks) < 7  # nothing chunked from the scan


def test_a_transcription_becomes_a_distinctly_sourced_chunk(wordings):
    """FR-ENDORSE-3: verification against a transcription is badged
    differently from a text-layer read, so the chunk has to carry that."""
    transcribed = (
        "ENDORSEMENT NO. 1. It is hereby agreed that Clause 5 (Loss Occurrence) "
        "is amended as respects Windstorm so that the period shall read 168 "
        "CONSECUTIVE HOURS in place of the 72 consecutive hours previously stated."
    )
    chunks = chunk_pdf(
        "T-004",
        wordings / f"{ENDORSED_WORDING.lower()}.pdf",
        transcriptions={7: transcribed},
    )
    scanned = [c for c in chunks if c.source == "transcription"]
    assert len(scanned) == 1
    assert scanned[0].page == 7
    assert scanned[0].clause_no == "END-1"
    assert scanned[0].clause_type == "HOURS"
    assert "168" in scanned[0].text


def test_a_blank_transcription_is_ignored_rather_than_stored(wordings):
    chunks = chunk_pdf(
        "T-004", wordings / f"{ENDORSED_WORDING.lower()}.pdf", transcriptions={7: "   "}
    )
    assert all(c.source == "text" for c in chunks)


# --------------------------------------------------------------------------- #
# Page fallback
# --------------------------------------------------------------------------- #


def test_a_document_with_no_clause_headings_chunks_by_page():
    """FR-INGEST-2's stated fallback."""
    pages = [
        "This agreement is written without numbered clauses. " * 8,
        "A second page of continuous prose, equally unnumbered. " * 8,
    ]
    chunks = chunk_pages("T-999", pages)
    assert len(chunks) == 2
    assert [c.page for c in chunks] == [1, 2]
    assert all(c.clause_no is None for c in chunks)
    assert all(c.chunk_id.startswith("T-999#p") for c in chunks)


def test_short_pages_are_skipped_in_the_page_fallback():
    chunks = chunk_pages("T-999", ["too short", "x" * 400])
    assert len(chunks) == 1
    assert chunks[0].page == 2


def test_a_clause_spanning_a_page_break_keeps_its_full_body():
    pages = [
        "1. First Clause\nOpening text that continues past the page break and",
        "carries on here before the next heading appears.\n2. Second Clause\nMore.",
    ]
    chunks = chunk_pages("T-999", pages)
    first = next(c for c in chunks if c.clause_no == "1")
    assert "carries on here" in first.text
    assert first.page == 1
    assert first.pages_spanned == (1, 2)


def test_a_cross_reference_is_not_mistaken_for_a_heading():
    """"subject to Clause 5" mid-sentence must not start a new chunk."""
    pages = ["1. Only Clause\nThis is governed by 5. and by nothing else at all. " * 4]
    chunks = chunk_pages("T-999", pages)
    assert [c.clause_no for c in chunks] == ["1"]


def test_a_clause_spanning_two_page_breaks_gathers_the_intervening_page():
    """A long clause can swallow a whole page between its heading and the
    next. That page's text has to end up in the chunk, or a quote from the
    middle of a long clause fails to verify."""
    pages = [
        "1. First Clause\nOpening text before the break.",
        "An entire page of continuation with no heading on it whatsoever.",
        "Closing text of the first clause.\n2. Second Clause\nMore text here.",
    ]
    chunks = chunk_pages("T-999", pages)
    first = next(c for c in chunks if c.clause_no == "1")
    assert "entire page of continuation" in first.text
    assert "Closing text" in first.text
    assert first.pages_spanned == (1, 2, 3)


def test_a_chunk_retains_its_own_heading_in_the_text():
    """Deliberate. The heading is semantically informative, so keeping it
    helps retrieval, and it is harmless to quote-matching.

    It also means a chunk body is never empty - even a heading with nothing
    under it yields the heading - which is why there is no empty-body guard.
    """
    body = "This one has a body long enough to be retrievable. " * 4
    pages = ["1. Hollow Heading\n2. Real Clause\n" + body]
    chunks = chunk_pages("T-999", pages)
    assert [c.clause_no for c in chunks] == ["1", "2"]
    hollow = next(c for c in chunks if c.clause_no == "1")
    assert hollow.text.strip() == "1. Hollow Heading"
    assert "2. Real Clause" in next(c for c in chunks if c.clause_no == "2").text


def test_a_page_that_is_entirely_furniture_is_treated_as_image_only():
    """Stripping the header and footer can leave a page empty, which must not
    produce a chunk of whitespace."""
    pages = ["1. Only Clause\nSubstantive body text here. " * 6, "Page 2\nSynthetic - no legal effect"]
    chunks = chunk_pages("T-999", pages, image_only_pages=[2])
    assert len(chunks) == 1
    assert chunks[0].clause_no == "1"


def test_blank_lines_are_stripped_from_chunk_text():
    pages = ["1. Spaced Clause\n\n\nBody after blank lines. " * 1 + "More body text here to pass the length check."]
    chunks = chunk_pages("T-999", pages)
    assert len(chunks) == 1
    assert "\n\n" not in chunks[0].text


def test_a_clause_spanning_an_image_only_page_skips_it_without_losing_the_rest():
    """A scanned insert in the middle of a long clause must not truncate the
    clause or crash the span calculation."""
    pages = [
        "1. First Clause\nText before the scanned insert.",
        "(this page is a scan with no text layer)",
        "Text after the insert.\n2. Second Clause\nMore.",
    ]
    chunks = chunk_pages("T-999", pages, image_only_pages=[2])
    first = next(c for c in chunks if c.clause_no == "1")
    assert "Text before" in first.text
    assert "Text after" in first.text
    assert 2 not in first.pages_spanned


def test_a_final_clause_ending_on_an_image_only_page_still_chunks():
    pages = [
        "1. Only Clause\n" + "Body text that is long enough to retain. " * 4,
        "(scan)",
    ]
    chunks = chunk_pages("T-999", pages, image_only_pages=[2])
    assert len(chunks) == 1
    assert chunks[0].clause_no == "1"
