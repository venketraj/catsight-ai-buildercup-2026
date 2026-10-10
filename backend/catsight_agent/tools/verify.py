"""Citation verification — FR-VERIFY.

Every wording claim carries a quote (C-7). This module decides whether that
quote is real, and it is the feature that makes the citation rule *visible*
rather than merely true, which is why `FR-VERIFY` sits in the never-cut set.

Two checks, in this order:

  **FR-VERIFY-1, deterministic.** Runs first, in code, at no model cost.
  Normalise the quote and the stored chunk, then assert the quote is a
  substring of the chunk **at the cited location**.

  **FR-VERIFY-2, semantic.** Only for quotes that survive check 1. Asks
  `MODEL_REASON` whether the quote actually supports the asserted issue.
  Lives behind the `SemanticChecker` protocol so the loop is testable without
  a model; the real implementation arrives with GCP access.

On failure of either check the flag is revised once and retried; on a second
failure it **abstains** (FR-VERIFY-3) — withheld from the report body, shown
in a review tray with the reason. It is never dropped silently.

## Verification is scoped to the cited location

This is the point most easily got wrong. A quote is not verified by existing
*somewhere* in the corpus; it is verified by existing **where the citation
says it is**. So a quote lifted verbatim from treaty W3 and cited to W5 fails,
as does a real quote cited to the wrong page or the wrong clause. QA-10 plants
exactly those corruptions.

Scoping this way is what makes the badge `verified · {treaty_id}, p. {page},
cl. {clause_no}` mean something: an analyst can turn to that page and find
that sentence.

## What the deterministic check can and cannot catch

It catches mechanical corruption: paraphrase (not a substring), wrong treaty,
wrong page, wrong clause, and truncation that lands **mid-word** — if the
character following the match is alphanumeric, the quote was cut rather than
quoted, and a cut quote is not a reliable audit trail.

It cannot catch a quote that is clean, genuinely present, and *misleadingly
partial* — the classic being a quote that omits the operative qualifier
("...shall be deemed one loss occurrence", dropping "unless the Reinsurer
elects otherwise"). A substring test must pass that, because it *is* a
substring. Catching it is the semantic check's job, and that division of
labour is deliberate: cheap deterministic checks first, the model only on what
survives.

## Normalisation is lossy on purpose, but only as lossy as PDF extraction

`pypdf` mangles real wordings in predictable ways: curly quotes, en and em
dashes, ligatures, soft hyphens, hyphenated line breaks, and newlines wherever
the PDF wrapped a line. Normalisation undoes exactly those, so a faithful
quote still matches text that extraction damaged. It does **not** strip
punctuation wholesale — that would make "not covered" and "not, covered"
interchangeable and let a sloppy quote through.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Protocol, Sequence, runtime_checkable

from catsight_agent.schemas import Citation, VerificationResult, WordingFlag
from ingest.chunking import Chunk

__all__ = [
    "normalise_for_match",
    "QuoteMatch",
    "match_quote",
    "ChunkLookup",
    "InMemoryChunkIndex",
    "locate_citation",
    "verify_deterministic",
    "SemanticChecker",
    "AlwaysSupports",
    "FlagReviser",
    "NoRevision",
    "VerificationOutcome",
    "verify_flags",
]


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #

#: Characters PDF extraction substitutes for their ASCII equivalents. Mapped
#: rather than deleted: a dash carries meaning in "24-hour", so it becomes a
#: plain hyphen instead of disappearing.
_CHARACTER_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",  # single quotes
    "“": '"', "”": '"', "„": '"', "‟": '"',  # double quotes
    "′": "'", "″": '"',                                 # primes
    "‐": "-", "‑": "-", "‒": "-", "–": "-",   # hyphens, dashes
    "—": "-", "―": "-", "−": "-",                  # em dash, minus
    " ": " ", " ": " ", " ": " ", " ": " ",   # fixed spaces
    " ": " ", " ": " ", " ": " ", "　": " ",
    "…": "...",                                              # ellipsis
}

#: Zero-width and soft-hyphen characters, deleted outright. A soft hyphen is a
#: rendering hint with no textual content, so keeping it would break a match
#: for no reason.
_DELETE = dict.fromkeys(map(ord, "­​‌‍﻿"))

#: A hyphen at a line break: "reinstate-\nment" is one word, not two. Undone
#: before whitespace collapse or it would become "reinstate- ment".
_HYPHEN_LINEBREAK = re.compile(r"-[ \t]*\n[ \t]*")

_WHITESPACE = re.compile(r"\s+")


def normalise_for_match(text: str) -> str:
    """Normalise text for quote matching. See the module docstring.

    NFKC first, which folds ligatures ("ﬁ" to "fi") and compatibility forms
    that `pypdf` emits from embedded fonts. Then the explicit character map,
    because NFKC leaves curly quotes and dashes alone.
    """
    flat = unicodedata.normalize("NFKC", text)
    flat = flat.translate(_DELETE)
    flat = _HYPHEN_LINEBREAK.sub("", flat)
    flat = "".join(_CHARACTER_MAP.get(char, char) for char in flat)
    flat = _WHITESPACE.sub(" ", flat)
    return flat.strip().casefold()


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #

_WORD_CHARACTER = re.compile(r"[0-9a-z]")


@dataclass(frozen=True)
class QuoteMatch:
    """The outcome of matching one quote against one chunk."""

    ok: bool
    #: Offset of the match in the *normalised* chunk, for UI highlighting.
    offset: int | None = None
    reason: str | None = None


def match_quote(quote: str, chunk_text: str) -> QuoteMatch:
    """Whether `quote` appears verbatim in `chunk_text`, word-aligned.

    Word alignment is what separates a quote from a cut. "the loss occurrenc"
    is a substring of "the loss occurrence" and must still fail, because a
    citation that stops mid-word cannot be checked by a human against the
    page.
    """
    needle = normalise_for_match(quote)
    haystack = normalise_for_match(chunk_text)

    if not needle:
        return QuoteMatch(False, reason="the quote is empty once normalised")

    # Every occurrence is considered, not just the first. A short quote can
    # appear mid-word early in a clause and cleanly later ("ment" inside
    # "reinstatement", then as its own word); accepting only the first hit
    # would withhold a faithful quote.
    truncation_reason: str | None = None
    offset = haystack.find(needle)
    while offset >= 0:
        before = haystack[offset - 1] if offset > 0 else ""
        after_index = offset + len(needle)
        after = haystack[after_index] if after_index < len(haystack) else ""

        starts_mid_word = bool(
            before and _WORD_CHARACTER.match(before) and _WORD_CHARACTER.match(needle[0])
        )
        ends_mid_word = bool(
            after and _WORD_CHARACTER.match(after) and _WORD_CHARACTER.match(needle[-1])
        )

        if not starts_mid_word and not ends_mid_word:
            return QuoteMatch(True, offset=offset)

        if truncation_reason is None:
            truncation_reason = (
                "the quote begins mid-word, so it is truncated rather than quoted"
                if starts_mid_word
                else "the quote ends mid-word, so it is truncated rather than quoted"
            )
        offset = haystack.find(needle, offset + 1)

    if truncation_reason is not None:
        return QuoteMatch(False, reason=truncation_reason)
    return QuoteMatch(
        False,
        reason="the quote does not appear in the cited clause - it may be paraphrased",
    )


# --------------------------------------------------------------------------- #
# The chunk store
# --------------------------------------------------------------------------- #


@runtime_checkable
class ChunkLookup(Protocol):
    """What verification needs from the chunk store.

    A protocol so the same verifier works against the in-memory index used in
    tests and the Firestore collection used in production, per the seam
    convention in `retrieval.py`.
    """

    def chunks_for(self, treaty_id: str) -> Sequence[Chunk]:
        ...


class InMemoryChunkIndex:
    """Chunks grouped by treaty. Deterministic ordering."""

    def __init__(self, chunks: Iterable[Chunk] = ()) -> None:
        self._by_treaty: dict[str, list[Chunk]] = {}
        self.add(chunks)

    def add(self, chunks: Iterable[Chunk]) -> None:
        for chunk in chunks:
            bucket = self._by_treaty.setdefault(chunk.treaty_id, [])
            if not any(existing.chunk_id == chunk.chunk_id for existing in bucket):
                bucket.append(chunk)

    def chunks_for(self, treaty_id: str) -> Sequence[Chunk]:
        return tuple(self._by_treaty.get(treaty_id, ()))

    def __len__(self) -> int:
        return sum(len(bucket) for bucket in self._by_treaty.values())


def _pages_of(chunk: Chunk) -> tuple[int, ...]:
    """Pages a chunk covers. `pages_spanned` is authoritative when present;
    a chunk built without it still covers its own page."""
    return chunk.pages_spanned if chunk.pages_spanned else (chunk.page,)


def locate_citation(citation: Citation, store: ChunkLookup) -> tuple[Chunk | None, str | None]:
    """Find the chunk a citation points at, or say why there isn't one.

    Narrows by treaty, then clause, then page - in that order, so the reason
    names the first thing that was wrong rather than a generic miss.
    """
    candidates = store.chunks_for(citation.treaty_id)
    if not candidates:
        return None, f"no stored wording for treaty {citation.treaty_id}"

    by_clause = [c for c in candidates if c.clause_no == citation.clause_no]
    if not by_clause:
        available = ", ".join(sorted({c.clause_no or "-" for c in candidates})[:8])
        return None, (
            f"{citation.treaty_id} has no clause {citation.clause_no} "
            f"(stored clauses include {available})"
        )

    on_page = [c for c in by_clause if citation.page in _pages_of(c)]
    if not on_page:
        actual = sorted({page for c in by_clause for page in _pages_of(c)})
        return None, (
            f"clause {citation.clause_no} of {citation.treaty_id} is on page "
            f"{', '.join(str(p) for p in actual)}, not page {citation.page}"
        )

    # More than one chunk can satisfy the citation only if a clause number
    # repeats; prefer the one whose heading page matches, then first by id.
    on_page.sort(key=lambda c: (c.page != citation.page, c.chunk_id))
    return on_page[0], None


def verify_deterministic(
    citation: Citation, store: ChunkLookup
) -> tuple[bool, str | None, Chunk | None]:
    """FR-VERIFY-1. Returns `(passed, reason, matched_chunk)`."""
    chunk, reason = locate_citation(citation, store)
    if chunk is None:
        return False, reason, None

    outcome = match_quote(citation.quote, chunk.text)
    if not outcome.ok:
        return False, outcome.reason, chunk
    return True, None, chunk


# --------------------------------------------------------------------------- #
# The semantic check and the revision step
# --------------------------------------------------------------------------- #


@runtime_checkable
class SemanticChecker(Protocol):
    """FR-VERIFY-2. Does the quote support the asserted issue?

    The production implementation calls `MODEL_REASON` with `response_schema`
    returning `{supports: bool, reason: str}`, batching an analysis's flags
    into as few calls as the context allows. It cannot be written against a
    model that has not been confirmed to exist, so the loop depends only on
    this protocol.
    """

    def supports(self, flag: WordingFlag, chunk: Chunk) -> tuple[bool, str | None]:
        ...


class AlwaysSupports:
    """A semantic checker that agrees with everything.

    For tests of the deterministic path and the loop's bookkeeping. Using it
    in production would make `semantic_pass` meaningless, so it is named to
    be obvious in a stack trace.
    """

    def supports(self, flag: WordingFlag, chunk: Chunk) -> tuple[bool, str | None]:
        return True, None


@runtime_checkable
class FlagReviser(Protocol):
    """FR-VERIFY-3's retry. AG-3 re-invoked with the checker's reason as
    feedback, returning a corrected flag or `None` to give up."""

    def revise(self, flag: WordingFlag, reason: str) -> WordingFlag | None:
        ...


class NoRevision:
    """Declines to revise, so a flag that fails once abstains immediately.

    This is the honest default when AG-3 is not wired up: pretending a retry
    happened would inflate the verified count.
    """

    def revise(self, flag: WordingFlag, reason: str) -> WordingFlag | None:
        return None


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #


@dataclass
class VerificationOutcome:
    """FR-VERIFY-4's counts, plus the two flag lists the UI renders."""

    verified: list[WordingFlag] = field(default_factory=list)
    withheld: list[WordingFlag] = field(default_factory=list)
    results: dict[str, VerificationResult] = field(default_factory=dict)

    @property
    def verified_count(self) -> int:
        return len(self.verified)

    @property
    def withheld_count(self) -> int:
        return len(self.withheld)

    def header(self) -> str:
        """The report header string from FR-VERIFY-4.

        Reads "{n} of {n} displayed citations verified" because every
        displayed flag is verified by construction - the sentence states the
        guarantee rather than a ratio that could be less than one.
        """
        shown = self.verified_count
        return (
            f"{shown} of {shown} displayed citations verified "
            f"· {self.withheld_count} withheld"
        )

    def badge(self, flag: WordingFlag) -> str:
        """The per-flag badge from FR-VERIFY-4, naming the source so a
        transcribed endorsement reads differently (QA-12)."""
        result = self.results[_flag_id(flag)]
        citation = flag.citation
        suffix = " against transcription" if result.source == "transcription" else ""
        return (
            f"verified{suffix} · {citation.treaty_id}, "
            f"p. {citation.page}, cl. {citation.clause_no}"
        )


def _flag_id(flag: WordingFlag) -> str:
    """A stable identity for a flag, so a revision keeps the same id and the
    `attempts` count accumulates against one record rather than two."""
    return f"{flag.treaty_id}:{flag.issue_type}:{flag.citation.clause_no}"


def verify_flags(
    flags: Sequence[WordingFlag],
    store: ChunkLookup,
    *,
    checker: SemanticChecker | None = None,
    reviser: FlagReviser | None = None,
    max_retries: int = 1,
) -> VerificationOutcome:
    """Run FR-VERIFY over candidate flags.

    `max_retries` defaults to 1, matching `VERIFIER_MAX_RETRIES`. A flag that
    fails after its retries abstains: it goes to `withheld` with a reason, and
    the reason is the one from its **last** attempt, since that is what the
    analyst needs to see in the review tray.
    """
    checker = checker if checker is not None else AlwaysSupports()
    reviser = reviser if reviser is not None else NoRevision()
    outcome = VerificationOutcome()

    for original in flags:
        flag_id = _flag_id(original)
        candidate = original
        attempts = 0
        last_reason = "verification did not run"
        deterministic = False
        semantic = False
        source = candidate.citation.source

        # `while True` with the exits inside, rather than a counted loop: the
        # first attempt must always happen. A counted loop would skip the body
        # entirely for a negative `max_retries` and then build a
        # VerificationResult with attempts=0, which the schema rejects - a
        # crash on a nonsense argument instead of one honest attempt.
        while True:
            attempts += 1
            deterministic, reason, chunk = verify_deterministic(candidate.citation, store)
            semantic = False

            if deterministic and chunk is not None:
                # The chunk's own source is authoritative for the badge: what
                # the model claimed about the source is not load-bearing.
                source = chunk.source
                semantic, reason = checker.supports(candidate, chunk)
                if semantic:
                    break
                reason = reason or "the quote does not support the asserted issue"

            last_reason = reason or "verification failed without a reason"
            if attempts > max_retries:
                break
            revised = reviser.revise(candidate, last_reason)
            if revised is None:
                break
            candidate = revised

        verified = deterministic and semantic
        outcome.results[flag_id] = VerificationResult(
            flag_id=flag_id,
            deterministic_pass=deterministic,
            semantic_pass=semantic,
            reason=None if verified else last_reason,
            attempts=attempts,
            source=source,
        )
        if verified:
            outcome.verified.append(candidate)
        else:
            outcome.withheld.append(candidate)

    return outcome
