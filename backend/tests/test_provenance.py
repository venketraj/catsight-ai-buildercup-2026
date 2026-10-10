"""Field citation checks (ingest.provenance) and the repair round in
ingest_treaty - QA-4, C-7.

Run against the real generated wordings, because the thing under test is
whether a quote is really on a page of a real PDF. W4 is used throughout: it
carries the scanned endorsement (page 7, no text layer), so it exercises both
the string-matched path and the transcription path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingest.chunking import chunk_pdf, page_texts
from ingest.ingest_treaty import extract_treaty_terms
from ingest.provenance import (
    check_field_citations,
    required_citation_fields,
)

W4 = Path("data/synthetic/wordings")
TREATY = "T-004"


def _w4_pdf() -> Path:
    manifest = json.loads((W4 / "manifest.json").read_text(encoding="utf-8"))
    rows = manifest if isinstance(manifest, list) else manifest["wordings"]
    row = next(r for r in rows if r["treaty_id"] == TREATY)
    return W4 / row["pdf"]


@pytest.fixture(scope="module")
def w4():
    pdf = _w4_pdf()
    if not pdf.exists():
        pytest.skip("wordings not generated; run python -m ingest.build_wordings")
    texts = page_texts(pdf)
    chunks = chunk_pdf(TREATY, pdf)
    clause5 = next(c for c in chunks if c.clause_no == "5")
    # A real quote: the first twelve words of the hours clause body.
    quote = " ".join(clause5.text.split()[:12])
    return pdf, texts, chunks, clause5, quote


def _check(w4, entry, field="hours_clause.EQ"):
    _, texts, chunks, _, _ = w4
    entries = [] if entry is None else [{"field": field, **entry}]
    return check_field_citations(TREATY, entries, [field], texts, chunks).fields[field]


def test_a_real_quote_on_the_cited_page_is_verified(w4):
    _, _, _, clause5, quote = w4
    result = _check(w4, {"page": clause5.page, "clause_no": "5", "quote": quote})
    assert result.status == "verified"
    assert result.showable


def test_a_wrong_clause_number_is_corrected_from_the_page(w4):
    _, _, _, clause5, quote = w4
    result = _check(w4, {"page": clause5.page, "clause_no": "99", "quote": quote})
    assert result.status == "verified"
    assert result.clause_no == "5"


def test_the_right_quote_on_the_wrong_page_is_unverified(w4):
    _, texts, _, clause5, quote = w4
    other = 1 if clause5.page != 1 else 3
    result = _check(w4, {"page": other, "clause_no": "5", "quote": quote})
    assert result.status == "unverified"
    assert f"page {other}" in result.reason


def test_a_paraphrase_is_unverified(w4):
    _, _, _, clause5, _ = w4
    result = _check(
        w4,
        {"page": clause5.page, "clause_no": "5",
         "quote": "losses within seventy two hours count as a single event"},
    )
    assert result.status == "unverified"
    assert "paraphrased" in result.reason


def test_a_citation_without_a_quote_cannot_be_verified(w4):
    _, _, _, clause5, _ = w4
    result = _check(w4, {"page": clause5.page, "clause_no": "5"})
    assert result.status == "unverified"
    assert "no quote" in result.reason


def test_a_missing_citation_is_reported_as_missing(w4):
    assert _check(w4, None).status == "missing"


def test_a_page_outside_the_document_is_unverified(w4):
    _, texts, _, _, quote = w4
    result = _check(w4, {"page": len(texts) + 5, "clause_no": "5", "quote": quote})
    assert result.status == "unverified"
    assert "outside the document" in result.reason


def test_the_scanned_endorsement_is_labelled_transcribed_not_verified(w4):
    """Page 7 has no text layer. A quote read off the image cannot be
    string-matched, so it is shown as a transcription - never as verified."""
    _, texts, _, _, _ = w4
    assert len(texts[6].strip()) < 120, "page 7 should be image-only"
    result = _check(
        w4,
        {"page": 7, "clause_no": "END-1", "source": "transcription",
         "quote": "the period shall be 168 consecutive hours"},
        field="hours_clause.WS",
    )
    assert result.status == "transcribed"
    assert result.showable


def test_an_image_page_cited_as_text_is_unverified(w4):
    result = _check(
        w4,
        {"page": 7, "clause_no": "END-1", "source": "text",
         "quote": "the period shall be 168 consecutive hours"},
        field="hours_clause.WS",
    )
    assert result.status == "unverified"
    assert "no text layer" in result.reason


def test_the_last_citation_for_a_field_wins(w4):
    _, texts, chunks, clause5, quote = w4
    entries = [
        {"field": "hours_clause.EQ", "page": clause5.page, "quote": "not on the page at all"},
        {"field": "hours_clause.EQ", "page": clause5.page, "quote": quote},
    ]
    report = check_field_citations(TREATY, entries, ["hours_clause.EQ"], texts, chunks)
    assert report.fields["hours_clause.EQ"].status == "verified"


def test_report_counts_and_failing_fields(w4):
    _, texts, chunks, clause5, quote = w4
    entries = [{"field": "a", "page": clause5.page, "quote": quote}]
    report = check_field_citations(TREATY, entries, ["a", "b"], texts, chunks)
    assert report.total == 2
    assert report.showable_count == 1
    assert report.coverage == 0.5
    assert report.failing == ["b"]
    assert report.by_status("missing") == ["b"]
    assert report.to_json()["a"]["status"] == "verified"


def test_without_chunks_the_cited_clause_is_kept(w4):
    _, texts, _, clause5, quote = w4
    entries = [
        "not a mapping",
        {"page": 1},  # no field name
        {"field": "f", "page": clause5.page, "clause_no": "5", "quote": quote},
    ]
    report = check_field_citations(TREATY, entries, ["f"], texts, chunks=())
    assert report.fields["f"].status == "verified"
    assert report.fields["f"].clause_no == "5"


def test_endorsement_bookkeeping_needs_no_citation():
    fields = {"type": "CAT_XL", "endorsement.overrides": "hours_clause.WS",
              "hours_clause.WS.base": 72}
    assert required_citation_fields(fields) == ["hours_clause.WS.base", "type"]


# --------------------------------------------------------------------------- #
# The repair round inside extract_treaty_terms
# --------------------------------------------------------------------------- #


class _Scripted:
    """A fake genai client returning scripted response texts in order."""

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls = 0
        outer = self

        class Models:
            def generate_content(self, **kwargs):
                outer.calls += 1

                class R:
                    text = outer.texts.pop(0)

                return R()

        self.models = Models()


def _payload(field_pages):
    return json.dumps({
        "cedent": "Test Cedent",
        "type": "CAT_XL",
        "perils": ["WS"],
        "territory": {"include": ["JPN"], "exclude": []},
        "inception": "2026-01-01",
        "expiry": "2026-12-31",
        "currency": "USD",
        "hours_clause": {"WS": 72, "EQ": 72, "FL": 0, "OTHER": 0},
        "layers": [{
            "layer_no": 1, "retention": "10.0", "limit": "20.0", "premium": "2.0",
            "our_share": "0.25", "reinstatements": {"count": 1, "rate": "1.0"},
        }],
        "field_pages": field_pages,
    })


def test_failed_citations_are_repaired_in_one_follow_up(w4):
    pdf, _, _, clause5, quote = w4
    repaired = json.dumps({"citations": [
        {"field": "hours_clause.EQ", "page": clause5.page, "clause_no": "5", "quote": quote},
        # A field that did not fail must not overwrite a good citation.
        {"field": "unrelated", "page": 1, "quote": "ignored entirely here"},
    ]})
    client = _Scripted(_payload([]), repaired)

    outcome = extract_treaty_terms(pdf, TREATY, client=client, model="fake")

    assert client.calls == 2
    assert outcome.repair_error is None
    assert outcome.provenance.fields["hours_clause.EQ"].status == "verified"
    assert "unrelated" not in outcome.provenance.fields
    # Everything the repair did not fix stays labelled, not trusted.
    assert outcome.provenance.fields["currency"].status == "missing"


def test_no_follow_up_when_every_citation_already_verifies(w4, monkeypatch):
    pdf, _, _, _, _ = w4
    client = _Scripted(_payload([]))
    import ingest.ingest_treaty as module

    monkeypatch.setattr(module, "required_citation_fields", lambda flattened: [])
    outcome = extract_treaty_terms(pdf, TREATY, client=client, model="fake")
    assert client.calls == 1
    assert outcome.provenance.total == 0


def test_a_failed_repair_is_recorded_not_raised(w4):
    pdf, _, _, _, _ = w4
    client = _Scripted(_payload([]), "this is not json")
    outcome = extract_treaty_terms(pdf, TREATY, client=client, model="fake")
    assert outcome.repair_error is not None
    assert outcome.provenance.failing  # still labelled, nothing hidden


def test_repair_can_be_switched_off(w4):
    pdf, _, _, _, _ = w4
    client = _Scripted(_payload([]))
    outcome = extract_treaty_terms(pdf, TREATY, client=client, model="fake", repair=False)
    assert client.calls == 1
    assert outcome.provenance.failing


def test_an_unreadable_pdf_yields_no_provenance(tmp_path):
    missing = tmp_path / "nope.pdf"
    client = _Scripted(_payload([]))
    # The first call never reads the file in this fake, so extraction
    # "succeeds" and only the provenance step meets the missing file.
    import ingest.ingest_treaty as module

    real = module.Path.read_bytes
    try:
        module.Path.read_bytes = lambda self: b"%PDF-fake"
        outcome = extract_treaty_terms(missing, TREATY, client=client, model="fake")
    finally:
        module.Path.read_bytes = real
    assert outcome.provenance is None
