"""FR-VERIFY and QA-10 — citation verification.

QA-10's bar is two-sided and both sides matter:

  **100% of corrupted quotes withheld.** Tested against the real w1..w8 PDFs,
  chunked through `pypdf`, with each corruption applied to a quote that would
  otherwise verify - so a failure means the check missed the corruption, not
  that the fixture was wrong.

  **0 false withholds on the planted set.** The harder half. A verifier that
  withholds everything scores 100% on the first bar, so the second bar is what
  stops the check being uselessly strict.
"""

from __future__ import annotations

import pytest

from catsight_agent.schemas import Citation, WordingFlag
from catsight_agent.tools.verify import (
    AlwaysSupports,
    InMemoryChunkIndex,
    NoRevision,
    QuoteMatch,
    locate_citation,
    match_quote,
    normalise_for_match,
    verify_deterministic,
    verify_flags,
)
from ingest.build_wordings import build_all
from ingest.chunking import Chunk, chunk_pdf


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict:
    return build_all(out_dir=tmp_path_factory.mktemp("wordings"))


@pytest.fixture(scope="module")
def chunked(built) -> dict[str, tuple[Chunk, ...]]:
    """The real wordings, chunked from the rendered PDFs.

    Deliberately via the PDF rather than the Markdown: `pypdf` is what mangles
    quotes and dashes, and normalisation only earns its keep against that.
    """
    out: dict[str, tuple[Chunk, ...]] = {}
    for row in built["manifest"]:
        treaty_id = row["treaty_id"]
        out[treaty_id] = chunk_pdf(treaty_id, built["out_dir"] / row["pdf"])
    return out


@pytest.fixture(scope="module")
def store(chunked) -> InMemoryChunkIndex:
    index = InMemoryChunkIndex()
    for chunks in chunked.values():
        index.add(chunks)
    return index


def _quotable(chunk: Chunk, words: int = 14) -> str:
    """A faithful quote taken from the middle of a clause.

    Taken from the *normalised* text and joined on single spaces, which is what
    a model quoting what it read would produce. Word-aligned by construction,
    so it must verify - that is the point of the no-false-withholds half of
    QA-10.
    """
    tokens = normalise_for_match(chunk.text).split()
    if len(tokens) <= words:
        return " ".join(tokens)
    start = max(1, (len(tokens) - words) // 2)
    quote = " ".join(tokens[start : start + words])
    return quote[:300]


def _citable_chunks(chunked) -> list[Chunk]:
    """One substantial clause per treaty whose quote is **unique to it**.

    Boilerplate will not do, and that is a finding rather than a fixture
    detail. All eight wordings share eleven boilerplate clauses, so a quote
    lifted from W1's Schedule clause genuinely appears in W2 as well -
    citing it to W2 is not a detectable error, because it is not an error.
    Only distinctive text can expose a wrong-treaty citation.

    That is also what a real flag cites: the operative hours or exclusion
    clause, never the furniture. See `data/ASSUMPTIONS.md` VF3.
    """
    corpus = {
        treaty_id: normalise_for_match(" ".join(c.text for c in chunks))
        for treaty_id, chunks in chunked.items()
    }
    picked: list[Chunk] = []
    for treaty_id, chunks in sorted(chunked.items()):
        numbers = [c.clause_no for c in chunks]
        for chunk in chunks:
            if not chunk.clause_no or numbers.count(chunk.clause_no) != 1:
                continue
            if len(normalise_for_match(chunk.text)) <= 220:
                continue
            quote = _quotable(chunk)
            if len(quote) < 10:
                continue
            if any(quote in text for other, text in corpus.items() if other != treaty_id):
                continue
            picked.append(chunk)
            break
    return picked


def _truncate_mid_word(quote: str) -> str:
    """Cut the final word in half.

    Deliberately mid-word. A *clean* truncation is allowed through
    FR-VERIFY-1 by design - see
    `test_a_clean_partial_quote_is_accepted_by_the_deterministic_check` - so
    only a mid-word cut is a corruption the deterministic check can be asked
    to catch.
    """
    tokens = quote.split()
    while tokens and len(tokens[-1]) < 4:
        tokens.pop()
    assert tokens, "need a final word long enough to cut in half"
    tokens[-1] = tokens[-1][:-2]
    return " ".join(tokens)


def _flag(chunk: Chunk, quote: str, *, treaty_id=None, page=None, clause_no=None) -> WordingFlag:
    treaty = treaty_id if treaty_id is not None else chunk.treaty_id
    return WordingFlag(
        treaty_id=treaty,
        issue_type="HOURS",
        severity="HIGH",
        explanation="Test flag.",
        citation=Citation(
            treaty_id=treaty,
            page=page if page is not None else chunk.page,
            clause_no=clause_no if clause_no is not None else (chunk.clause_no or "1"),
            quote=quote,
        ),
    )


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("“Loss Occurrence”", '"loss occurrence"'),
        ("the Reinsurer’s election", "the reinsurer's election"),
        ("72–hour period", "72-hour period"),
        ("72—hour period", "72-hour period"),
        ("72−hour", "72-hour"),
        ("one loss", "one loss"),
        ("soft­hyphen", "softhyphen"),
        ("zero​width", "zerowidth"),
        ("line\nbreak", "line break"),
        ("many     spaces", "many spaces"),
        ("  padded  ", "padded"),
        ("MiXeD CaSe", "mixed case"),
        ("and so on…", "and so on..."),
    ],
)
def test_normalisation_undoes_what_pdf_extraction_does(raw, expected):
    assert normalise_for_match(raw) == expected


def test_normalisation_folds_ligatures_via_nfkc():
    """pypdf emits ligatures from embedded fonts, so "ﬁrst" must match "first"."""
    assert normalise_for_match("the ﬁrst notiﬁcation") == "the first notification"


def test_a_hyphenated_line_break_rejoins_the_word():
    """A wording that wrapped "reinstatement" across a line must still match a
    quote that spells it whole - otherwise every hyphenated wrap is a false
    withhold."""
    assert normalise_for_match("reinstate-\nment premium") == "reinstatement premium"
    assert normalise_for_match("reinstate-  \n  ment") == "reinstatement"


def test_normalisation_does_not_strip_meaningful_punctuation():
    """Deliberate. Stripping punctuation wholesale would make "not covered"
    and "not, covered" interchangeable, letting a sloppy quote through."""
    assert normalise_for_match("not, covered") != normalise_for_match("not covered")
    assert normalise_for_match("shall not apply") != normalise_for_match("shall apply")


# --------------------------------------------------------------------------- #
# match_quote
# --------------------------------------------------------------------------- #


CLAUSE = (
    "All individual losses arising out of and directly occasioned by one event "
    "shall be deemed one Loss Occurrence, provided that the duration shall not "
    "exceed 72 consecutive hours."
)


def test_an_exact_quote_matches():
    outcome = match_quote("deemed one Loss Occurrence", CLAUSE)
    assert outcome.ok
    assert outcome.offset is not None
    assert outcome.reason is None


def test_a_quote_mangled_by_extraction_still_matches():
    mangled = CLAUSE.replace("one Loss Occurrence", "one Loss\nOccurrence")
    assert match_quote("deemed one Loss Occurrence", mangled).ok


def test_a_paraphrase_does_not_match():
    outcome = match_quote("treated as a single loss event", CLAUSE)
    assert not outcome.ok
    assert "paraphrased" in outcome.reason


def test_a_quote_ending_mid_word_is_rejected():
    """"72 consecutive hou" is a substring, and must still fail: an analyst
    cannot check a cut quote against the page."""
    outcome = match_quote("exceed 72 consecutive hou", CLAUSE)
    assert not outcome.ok
    assert "mid-word" in outcome.reason


def test_a_quote_beginning_mid_word_is_rejected():
    outcome = match_quote("ccasioned by one event shall", CLAUSE)
    assert not outcome.ok
    assert "mid-word" in outcome.reason


def test_a_clean_partial_quote_is_accepted_by_the_deterministic_check():
    """Documents the boundary between the two checks.

    This quote is faithful, word-aligned and genuinely present, but it omits
    the qualifier that follows. FR-VERIFY-1 must pass it - it IS a substring -
    and catching the misleading omission is FR-VERIFY-2's job. A deterministic
    check that tried to judge sufficiency would be guessing.
    """
    assert match_quote("shall be deemed one Loss Occurrence", CLAUSE).ok


def test_a_quote_matching_mid_word_first_and_cleanly_later_is_accepted():
    """Guards the all-occurrences scan. "ment premium" appears inside
    "reinstatement premium" before it appears as its own phrase."""
    text = "The reinstatement premium is due. Any payment premium is separate."
    assert match_quote("ment premium is", text).ok is False
    cleanly = "Any reinstatement premium. The ment premium is odd but present."
    assert match_quote("ment premium is", cleanly).ok


def test_an_empty_quote_is_rejected_rather_than_matching_everything():
    outcome = match_quote("   \n  ", CLAUSE)
    assert not outcome.ok
    assert "empty" in outcome.reason
    assert isinstance(outcome, QuoteMatch)


# --------------------------------------------------------------------------- #
# Scoping — locate_citation
# --------------------------------------------------------------------------- #


def _chunk(treaty_id="w1", clause_no="5", page=3, text=CLAUSE, spanned=(3,), source="text"):
    return Chunk(
        treaty_id=treaty_id,
        chunk_id=f"{treaty_id}#c{clause_no}",
        page=page,
        clause_no=clause_no,
        clause_title="Loss Occurrence",
        clause_type="HOURS",
        text=text,
        pages_spanned=spanned,
        source=source,
    )


def test_a_citation_to_an_unknown_treaty_fails_with_a_reason():
    store = InMemoryChunkIndex([_chunk()])
    chunk, reason = locate_citation(
        Citation(treaty_id="w9", page=3, clause_no="5", quote="deemed one Loss Occurrence"), store
    )
    assert chunk is None
    assert "no stored wording for treaty w9" in reason


def test_a_citation_to_an_unknown_clause_names_the_clauses_that_exist():
    store = InMemoryChunkIndex([_chunk()])
    chunk, reason = locate_citation(
        Citation(treaty_id="w1", page=3, clause_no="99", quote="deemed one Loss Occurrence"), store
    )
    assert chunk is None
    assert "no clause 99" in reason
    assert "stored clauses include 5" in reason


def test_a_citation_to_the_wrong_page_names_the_right_one():
    store = InMemoryChunkIndex([_chunk(page=3, spanned=(3,))])
    chunk, reason = locate_citation(
        Citation(treaty_id="w1", page=7, clause_no="5", quote="deemed one Loss Occurrence"), store
    )
    assert chunk is None
    assert "is on page 3, not page 7" in reason


def test_a_clause_spanning_a_page_break_verifies_on_either_page():
    """A long clause legitimately covers more than one page, so a citation to
    any page it spans is correct - refusing that would be a false withhold."""
    store = InMemoryChunkIndex([_chunk(page=3, spanned=(3, 4, 5))])
    for page in (3, 4, 5):
        chunk, reason = locate_citation(
            Citation(treaty_id="w1", page=page, clause_no="5", quote="deemed one Loss Occurrence"),
            store,
        )
        assert reason is None and chunk is not None


def test_a_chunk_without_pages_spanned_still_covers_its_own_page():
    store = InMemoryChunkIndex([_chunk(spanned=())])
    chunk, reason = locate_citation(
        Citation(treaty_id="w1", page=3, clause_no="5", quote="deemed one Loss Occurrence"), store
    )
    assert reason is None and chunk is not None


def test_the_index_is_idempotent_and_scopes_by_treaty():
    chunk = _chunk()
    store = InMemoryChunkIndex([chunk, chunk])
    assert len(store) == 1
    assert store.chunks_for("w1")
    assert store.chunks_for("w2") == ()


# --------------------------------------------------------------------------- #
# QA-10 — against the real wordings
# --------------------------------------------------------------------------- #


def test_qa10_no_false_withholds_on_faithful_quotes(chunked, store):
    """The half that stops the verifier being uselessly strict.

    Every faithful quote, drawn from the real PDF text of all eight wordings,
    must verify. A verifier that withholds everything passes the corruption
    half of QA-10 and fails here.
    """
    citable = _citable_chunks(chunked)
    assert len(citable) == 8, "expected one citable clause per wording"

    flags = [_flag(chunk, _quotable(chunk)) for chunk in citable]
    outcome = verify_flags(flags, store, checker=AlwaysSupports())

    assert outcome.withheld == [], [
        (r.flag_id, r.reason) for r in outcome.results.values() if r.reason
    ]
    assert outcome.verified_count == 8
    assert outcome.header() == "8 of 8 displayed citations verified · 0 withheld"


def test_qa10_every_corruption_is_withheld(chunked, store):
    """100% of corrupted quotes withheld.

    Each corruption is applied to a quote that verifies untouched, so any pass
    here is the check missing a corruption rather than a bad fixture.
    """
    citable = _citable_chunks(chunked)
    assert len(citable) == 8

    other_treaty = {
        chunk.treaty_id: next(c.treaty_id for c in citable if c.treaty_id != chunk.treaty_id)
        for chunk in citable
    }

    corruptions: list[tuple[str, WordingFlag]] = []
    for chunk in citable:
        good = _quotable(chunk)
        words = good.split()

        # paraphrase: swap a word for a synonym that is not in the clause
        paraphrased = " ".join(["notwithstanding" if i == len(words) // 2 else w
                                for i, w in enumerate(words)])
        corruptions.append(("paraphrased", _flag(chunk, paraphrased)))

        # truncated mid-word
        corruptions.append(("truncated", _flag(chunk, _truncate_mid_word(good))))

        # right text, wrong treaty
        corruptions.append(
            ("wrong treaty", _flag(chunk, good, treaty_id=other_treaty[chunk.treaty_id]))
        )

        # right text, wrong page
        far_page = max(chunk.pages_spanned or (chunk.page,)) + 40
        corruptions.append(("wrong page", _flag(chunk, good, page=far_page)))

        # right text, wrong clause
        corruptions.append(("wrong clause", _flag(chunk, good, clause_no="99")))

    outcome = verify_flags([flag for _, flag in corruptions], store, checker=AlwaysSupports())

    survived = {id(flag) for flag in outcome.verified}
    leaked = sorted({label for label, flag in corruptions if id(flag) in survived})
    assert not leaked, f"corruptions that slipped through: {leaked}"
    assert outcome.withheld_count == len(corruptions) == 40
    assert all(result.reason for result in outcome.results.values())


def test_a_truncated_quote_is_refused_for_truncation_not_for_absence(chunked, store):
    """The reason shown in the review tray has to be the right one - "may be
    paraphrased" would send an analyst looking for the wrong problem."""
    chunk = _citable_chunks(chunked)[0]
    good = _quotable(chunk)
    passed, reason, matched = verify_deterministic(
        _flag(chunk, _truncate_mid_word(good)).citation, store
    )
    assert not passed
    assert "mid-word" in reason
    assert matched is not None, "the clause was located; only the quote was bad"


# --------------------------------------------------------------------------- #
# The loop — FR-VERIFY-3 and -4
# --------------------------------------------------------------------------- #


class RejectsEverything:
    def supports(self, flag, chunk):
        return False, "the quote is about the period, not the hours clause"


class CountingChecker:
    """Fails the first n calls, then agrees."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def supports(self, flag, chunk):
        self.calls += 1
        if self.calls <= self.failures:
            return False, "needs a better quote"
        return True, None


class FixesTheQuote:
    """A reviser standing in for AG-3 re-invoked with the checker's reason."""

    def __init__(self, quote: str) -> None:
        self.quote = quote
        self.reasons: list[str] = []

    def revise(self, flag, reason):
        self.reasons.append(reason)
        return flag.model_copy(
            update={"citation": flag.citation.model_copy(update={"quote": self.quote})}
        )


def test_a_flag_failing_the_semantic_check_abstains_with_the_reason():
    store = InMemoryChunkIndex([_chunk()])
    flag = _flag(_chunk(), "deemed one Loss Occurrence")
    outcome = verify_flags([flag], store, checker=RejectsEverything())

    assert outcome.verified == []
    assert outcome.withheld == [flag]
    result = next(iter(outcome.results.values()))
    assert result.deterministic_pass is True
    assert result.semantic_pass is False
    assert "period, not the hours clause" in result.reason


def test_the_retry_uses_the_checkers_reason_as_feedback():
    """FR-VERIFY-3. The reviser must receive the reason, not a generic retry."""
    store = InMemoryChunkIndex([_chunk()])
    reviser = FixesTheQuote("72 consecutive hours")
    checker = CountingChecker(failures=1)

    outcome = verify_flags(
        [_flag(_chunk(), "deemed one Loss Occurrence")],
        store,
        checker=checker,
        reviser=reviser,
    )

    assert reviser.reasons == ["needs a better quote"]
    assert outcome.verified_count == 1
    result = next(iter(outcome.results.values()))
    assert result.attempts == 2
    assert result.verified


def test_only_one_retry_is_allowed_then_the_flag_abstains():
    """VERIFIER_MAX_RETRIES = 1, so a flag gets two attempts total."""
    store = InMemoryChunkIndex([_chunk()])
    checker = CountingChecker(failures=99)
    reviser = FixesTheQuote("72 consecutive hours")

    outcome = verify_flags(
        [_flag(_chunk(), "deemed one Loss Occurrence")],
        store,
        checker=checker,
        reviser=reviser,
        max_retries=1,
    )

    assert checker.calls == 2
    assert outcome.withheld_count == 1
    assert next(iter(outcome.results.values())).attempts == 2


def test_without_a_reviser_a_failing_flag_abstains_immediately():
    """The honest default: claiming a retry happened when AG-3 is not wired up
    would inflate the verified count."""
    store = InMemoryChunkIndex([_chunk()])
    outcome = verify_flags(
        [_flag(_chunk(), "deemed one Loss Occurrence")],
        store,
        checker=RejectsEverything(),
        reviser=NoRevision(),
    )
    assert next(iter(outcome.results.values())).attempts == 1


def test_a_deterministic_failure_is_also_retried_once():
    store = InMemoryChunkIndex([_chunk()])
    reviser = FixesTheQuote("deemed one Loss Occurrence")
    outcome = verify_flags(
        [_flag(_chunk(), "a quote that is simply not present here")],
        store,
        reviser=reviser,
    )
    assert outcome.verified_count == 1
    assert "paraphrased" in reviser.reasons[0]


def test_the_badge_names_the_transcription_source():
    """QA-12. An endorsement read from a scan must badge differently from one
    read off the text layer, and the chunk's own source decides it - not the
    model's claim about it."""
    transcribed = _chunk(
        treaty_id="w4", clause_no="END-1", page=9, spanned=(9,), source="transcription"
    )
    index = InMemoryChunkIndex([transcribed])
    # The citation claims "text"; the stored chunk says otherwise and wins.
    flag = _flag(transcribed, "deemed one Loss Occurrence")
    assert flag.citation.source == "text"

    outcome = verify_flags([flag], index)
    assert outcome.verified_count == 1
    badge = outcome.badge(outcome.verified[0])
    assert badge == "verified against transcription · w4, p. 9, cl. END-1"
    assert next(iter(outcome.results.values())).source == "transcription"


def test_the_badge_for_a_text_layer_flag_omits_the_source():
    store = InMemoryChunkIndex([_chunk()])
    outcome = verify_flags([_flag(_chunk(), "deemed one Loss Occurrence")], store)
    assert outcome.badge(outcome.verified[0]) == "verified · w1, p. 3, cl. 5"


def test_the_header_states_the_guarantee_not_a_ratio():
    """FR-VERIFY-4. Every displayed flag is verified by construction, so the
    header reads "n of n" and the withheld count carries the bad news."""
    store = InMemoryChunkIndex([_chunk(), _chunk(clause_no="6")])
    good = _flag(_chunk(), "deemed one Loss Occurrence")
    bad = _flag(_chunk(clause_no="6"), "not in the wording at all, promise")
    outcome = verify_flags([good, bad], store)
    assert outcome.header() == "1 of 1 displayed citations verified · 1 withheld"


def test_every_withheld_flag_carries_a_reason_for_the_review_tray():
    """The schema enforces it, and FR-VERIFY-3 requires the analyst to see why
    rather than finding a flag silently absent."""
    store = InMemoryChunkIndex([_chunk()])
    outcome = verify_flags(
        [_flag(_chunk(), "wholly absent text here")], store, checker=AlwaysSupports()
    )
    assert outcome.withheld_count == 1
    assert all(r.reason for r in outcome.results.values())


@pytest.mark.parametrize("max_retries", [0, -1])
def test_one_attempt_always_happens_however_retries_are_configured(max_retries):
    """`max_retries=0` means no retry, not no attempt. The negative case is
    nonsense input, and it must still produce one honest attempt rather than
    an `attempts=0` record the schema would reject."""
    store = InMemoryChunkIndex([_chunk()])
    checker = CountingChecker(failures=99)
    outcome = verify_flags(
        [_flag(_chunk(), "deemed one Loss Occurrence")],
        store,
        checker=checker,
        reviser=FixesTheQuote("72 consecutive hours"),
        max_retries=max_retries,
    )
    assert checker.calls == 1
    assert outcome.withheld_count == 1
    assert next(iter(outcome.results.values())).attempts == 1


def test_the_defaults_are_the_configured_ones():
    """VERIFIER_MAX_RETRIES = 1 and a checker that is not silently permissive
    in production - AlwaysSupports is named to be obvious in a stack trace."""
    store = InMemoryChunkIndex([_chunk()])
    outcome = verify_flags([_flag(_chunk(), "deemed one Loss Occurrence")], store)
    assert outcome.verified_count == 1
    assert next(iter(outcome.results.values())).attempts == 1
