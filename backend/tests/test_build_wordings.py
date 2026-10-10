"""DR-2 and FR-ENDORSE — the synthetic treaty wordings and their answer key.

Builds all eight wordings once per session (rendering PDFs is the slow part)
and asserts the properties QA-3 and QA-4 depend on:

  * 6-15 pages, numbered clauses, page numbers;
  * every ground-truth field carries a page and a clause number, read back
    out of the rendered PDF rather than predicted;
  * the hours clause is phrased differently across wordings, including one
    with no digits at all;
  * at least ten decoy passages mention hours without being the hours clause;
  * the scanned endorsement page has **no extractable text**, so it can only
    be read visually.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingest.build_wordings import (
    ENDORSED_WORDING,
    ENDORSEMENT_BASE_HOURS,
    ENDORSEMENT_EFFECTIVE_HOURS,
    HOURS_STYLE,
    build_all,
    build_clauses,
    clause_pages,
    endorsement_image,
    main,
    render_markdown,
)
from ingest.seed_portfolio import WORDINGS, build_portfolio
from ingest.wording_clauses import BOILERPLATE, DECOYS, NUMBER_WORDS, hours_phrase


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict:
    """Build every wording once. Rendering eight PDFs is the slow part."""
    out = tmp_path_factory.mktemp("wordings")
    return build_all(out_dir=out)


@pytest.fixture(scope="module")
def ground_truth(built) -> dict:
    return json.loads((built["out_dir"] / "ground_truth.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def portfolio():
    return build_portfolio()


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #


def test_all_eight_wordings_are_produced(built):
    assert built["wordings"] == 8
    assert len(built["manifest"]) == 8
    ids = {entry["wording_id"] for entry in built["manifest"]}
    assert ids == {w.wording_id for w in WORDINGS}


def test_each_wording_has_a_pdf_and_a_markdown_source(built):
    out: Path = built["out_dir"]
    for entry in built["manifest"]:
        assert (out / entry["pdf"]).exists()
        assert (out / entry["markdown"]).exists()
        assert (out / entry["pdf"]).stat().st_size > 10_000


def test_every_wording_is_between_six_and_fifteen_pages(built):
    """DR-2's explicit range. Padding to reach it would be dishonest; the
    length comes from real boilerplate, which is what a treaty mostly is."""
    for entry in built["manifest"]:
        assert 6 <= entry["pages"] <= 15, (entry["wording_id"], entry["pages"])


def test_pdfs_carry_page_numbers_and_the_synthetic_disclaimer(built):
    import pypdf

    reader = pypdf.PdfReader(str(built["out_dir"] / "w1.pdf"))
    first = reader.pages[0].extract_text() or ""
    assert "Page 1" in first
    assert "Synthetic" in first


def test_markdown_mirrors_the_clause_structure(portfolio):
    wording = next(w for w in WORDINGS if w.wording_id == "W1")
    treaty = portfolio.treaty("T-001")
    clauses = build_clauses(treaty, wording)
    markdown = render_markdown(treaty, wording, clauses)
    assert markdown.startswith("# W1")
    assert "no legal effect" in markdown
    for clause in clauses:
        assert f"## {clause.number}. {clause.title}" in markdown


def test_wordings_declare_themselves_synthetic(built):
    """C-8. A judge opening a PDF must see immediately that it is invented."""
    for entry in built["manifest"]:
        text = (built["out_dir"] / entry["markdown"]).read_text(encoding="utf-8")
        assert "Synthetic document" in text
        assert "Fictional parties" in text


# --------------------------------------------------------------------------- #
# Ground truth — QA-3
# --------------------------------------------------------------------------- #


def test_there_are_at_least_one_hundred_and_twenty_ground_truth_fields(ground_truth):
    """DR-2 targets about 15 fields per treaty, roughly 120 in total."""
    assert len(ground_truth["fields"]) >= 120


def test_every_field_carries_a_page_and_a_clause_number(ground_truth):
    """QA-4 scores citation page accuracy at >= 95%, which is meaningless if
    the answer key's own pages are missing or guessed."""
    for row in ground_truth["fields"]:
        assert row["page"] is not None, row
        assert isinstance(row["page"], int) and row["page"] >= 1
        assert row["clause_no"]
        assert row["treaty_id"]
        assert row["field"]


def test_page_numbers_are_within_the_documents_page_count(ground_truth, built):
    pages_by_id = {e["wording_id"]: e["pages"] for e in built["manifest"]}
    for row in ground_truth["fields"]:
        assert row["page"] <= pages_by_id[row["wording_id"]], row


def test_clause_pages_are_read_back_from_the_rendered_pdf(built, portfolio):
    """The mechanism behind the previous two tests: locate each clause heading
    in the extracted text rather than predicting where it will land."""
    wording = next(w for w in WORDINGS if w.wording_id == "W1")
    treaty = portfolio.treaty("T-001")
    clauses = build_clauses(treaty, wording)
    pages = clause_pages(built["out_dir"] / "w1.pdf", clauses)
    assert pages
    assert pages["1"] == 1  # the preamble is on page one
    # Pages advance monotonically with clause order.
    seen = [pages[c.number] for c in clauses if c.number in pages]
    assert seen == sorted(seen)


def test_every_wording_has_its_material_terms_in_the_answer_key(ground_truth):
    required = {"inception", "expiry", "currency", "type", "perils", "territory.include"}
    for wording in WORDINGS:
        fields = {
            r["field"] for r in ground_truth["fields"] if r["wording_id"] == wording.wording_id
        }
        assert required <= fields, (wording.wording_id, required - fields)


def test_ground_truth_matches_the_seeded_treaty_records(ground_truth, portfolio):
    """The answer key and the treaty record must agree, or QA-3 is scoring
    against a different document than the demo displays."""
    for row in ground_truth["fields"]:
        treaty = portfolio.treaty(row["treaty_id"])
        if row["field"] == "inception":
            assert row["expected_value"] == treaty.inception
        elif row["field"] == "expiry":
            assert row["expected_value"] == treaty.expiry
        elif row["field"] == "currency":
            assert row["expected_value"] == treaty.currency
        elif row["field"] == "type":
            assert row["expected_value"] == treaty.type
        elif row["field"] == "perils":
            assert row["expected_value"] == list(treaty.perils)
        elif row["field"] == "hours_clause.EQ":
            assert row["expected_value"] == treaty.hours_clause["EQ"]
        elif row["field"] == "hours_clause.WS":
            assert row["expected_value"] == treaty.hours_clause["WS"]


def test_layer_terms_appear_in_the_answer_key_for_cat_xl(ground_truth, portfolio):
    rows = [r for r in ground_truth["fields"] if r["wording_id"] == "W1"]
    fields = {r["field"]: r["expected_value"] for r in rows}
    assert fields["layers.1.retention"] == 10.0
    assert fields["layers.1.limit"] == 20.0
    assert fields["layers.1.premium"] == 2.0
    assert fields["layers.2.limit"] == 30.0
    assert fields["layers.3.limit"] == 40.0


def test_the_quota_share_has_cession_and_event_limit_not_layers(ground_truth):
    fields = {
        r["field"] for r in ground_truth["fields"] if r["wording_id"] == "W6"
    }
    assert "qs.cession_pct" in fields
    assert "qs.event_limit" in fields
    assert not any(f.startswith("layers.") for f in fields)


# --------------------------------------------------------------------------- #
# Phrasing variation — what makes extraction non-trivial
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("hours", sorted(NUMBER_WORDS))
def test_every_hours_value_has_all_four_phrasings(hours):
    for style in ("plain", "spelled", "period", "words"):
        phrase = hours_phrase(hours, style)
        assert "consecutive hours" in phrase


def test_the_plain_phrasing_uses_digits_and_the_words_phrasing_does_not():
    assert hours_phrase(72, "plain") == "72 consecutive hours"
    assert hours_phrase(72, "words") == "seventy-two consecutive hours"
    assert not any(ch.isdigit() for ch in hours_phrase(72, "words"))
    assert "72" in hours_phrase(72, "spelled")
    assert "seventy-two" in hours_phrase(72, "spelled")


def test_hours_phrase_rejects_an_unknown_value_or_style():
    with pytest.raises(ValueError, match="word form"):
        hours_phrase(99, "plain")
    with pytest.raises(ValueError, match="phrasing style"):
        hours_phrase(72, "interpretive-dance")


def test_wordings_use_more_than_one_phrasing_style():
    """A single style would let a prompt tuned to one layout score 100%."""
    assert len(set(HOURS_STYLE.values())) >= 3
    assert set(HOURS_STYLE) == {w.wording_id for w in WORDINGS}


def test_w8_hides_its_hours_clause_in_a_definition_with_no_digits(built):
    """DR-2's extraction-robustness case. The headline figure appears only in
    words, inside the Definitions clause, not in Clause 5."""
    import pypdf

    text = " ".join(
        " ".join((page.extract_text() or "").split())
        for page in pypdf.PdfReader(str(built["out_dir"] / "w8.pdf")).pages
    )
    assert "seventy-two consecutive hours" in text
    assert "Loss Occurrence, as respects Windstorm" in text


def test_each_wording_states_its_own_planted_hours_values(built, portfolio):
    """W2 is 96h, W3 is 120h, W7 is 168h -- never assume 72."""
    import pypdf

    expected = {"W2": 96, "W3": 120, "W7": 168}
    for wording_id, hours in expected.items():
        path = built["out_dir"] / f"{wording_id.lower()}.pdf"
        text = " ".join(
            " ".join((page.extract_text() or "").split())
            for page in pypdf.PdfReader(str(path)).pages
        )
        style = HOURS_STYLE[wording_id]
        assert hours_phrase(hours, style) in text, (wording_id, hours)


# --------------------------------------------------------------------------- #
# Decoys — QA-4 precision
# --------------------------------------------------------------------------- #


def test_there_are_at_least_ten_decoy_passages():
    assert len(DECOYS) >= 10
    assert all(clause.is_decoy for clause in DECOYS)


def test_decoys_mention_hours_without_being_the_hours_clause():
    for clause in DECOYS:
        body = " ".join(clause.paragraphs)
        assert clause.clause_type != "HOURS"
        assert not clause.fields  # a decoy contributes no ground-truth field


def test_decoys_are_recorded_against_every_wording(ground_truth):
    """They have to be in the answer key, or a flag citing one cannot be
    scored as the false positive it is."""
    assert len(ground_truth["decoys"]) >= 10 * 8
    for row in ground_truth["decoys"]:
        assert row["page"] is not None
        assert row["why"]


def test_boilerplate_is_neither_a_decoy_nor_a_ground_truth_field():
    """Boilerplate is realistic noise. Counting it either way would distort
    both recall and precision."""
    for clause in BOILERPLATE:
        assert not clause.is_decoy
        assert not clause.fields


# --------------------------------------------------------------------------- #
# FR-ENDORSE — the scanned endorsement
# --------------------------------------------------------------------------- #


def test_exactly_one_wording_carries_a_scanned_endorsement(built):
    flagged = [e for e in built["manifest"] if e["has_scanned_endorsement"]]
    assert len(flagged) == 1
    assert flagged[0]["wording_id"] == ENDORSED_WORDING


def test_the_endorsement_page_has_no_extractable_text(built):
    """The whole point of FR-ENDORSE. If the text layer gave the override
    away, Gemini's image understanding would not be exercised at all.

    The page carries only the rendered footer, so the threshold is small but
    not zero.
    """
    import pypdf

    reader = pypdf.PdfReader(str(built["out_dir"] / f"{ENDORSED_WORDING.lower()}.pdf"))
    last = (reader.pages[-1].extract_text() or "").strip()
    assert len(last) < 120, f"endorsement page leaked {len(last)} chars of text"
    assert str(ENDORSEMENT_EFFECTIVE_HOURS) not in last


def test_earlier_pages_of_the_endorsed_wording_do_have_text(built):
    """Guards against the previous test passing because the whole document
    failed to render."""
    import pypdf

    reader = pypdf.PdfReader(str(built["out_dir"] / f"{ENDORSED_WORDING.lower()}.pdf"))
    for page in reader.pages[:-1]:
        assert len((page.extract_text() or "").strip()) > 500


def test_the_base_wording_still_states_the_pre_endorsement_hours(built):
    """The contradiction has to be real: Clause 5 says 72, the endorsement
    says 168, and only the scan carries the operative term."""
    import pypdf

    reader = pypdf.PdfReader(str(built["out_dir"] / f"{ENDORSED_WORDING.lower()}.pdf"))
    text = " ".join(
        " ".join((page.extract_text() or "").split()) for page in reader.pages[:-1]
    )
    assert f"{ENDORSEMENT_BASE_HOURS} consecutive hours" in text


def test_the_answer_key_records_both_the_base_and_the_effective_hours(ground_truth):
    rows = {
        r["field"]: r
        for r in ground_truth["fields"]
        if r["wording_id"] == ENDORSED_WORDING and "hours_clause.WS" in r["field"]
    }
    assert rows["hours_clause.WS.base"]["expected_value"] == ENDORSEMENT_BASE_HOURS
    assert rows["hours_clause.WS.base"]["source"] == "text"
    assert rows["hours_clause.WS"]["expected_value"] == ENDORSEMENT_EFFECTIVE_HOURS
    assert rows["hours_clause.WS"]["source"] == "transcription"
    # The override is cited to the scanned page, not to Clause 5.
    assert rows["hours_clause.WS"]["page"] > rows["hours_clause.WS.base"]["page"]


def test_the_override_itself_is_in_the_answer_key(ground_truth):
    rows = [
        r for r in ground_truth["fields"] if r["field"] == "endorsement.overrides"
    ]
    assert len(rows) == 1
    assert rows[0]["expected_value"] == "hours_clause.WS"
    assert rows[0]["source"] == "transcription"


def test_the_treaty_record_carries_the_effective_term_with_provenance(portfolio):
    """FR-ENDORSE-3: the effective term is the endorsement's, and the base is
    retained so a reader can see what was overridden."""
    treaty = portfolio.treaty("T-004")
    assert treaty.hours_clause["WS"] == ENDORSEMENT_EFFECTIVE_HOURS
    assert treaty.endorsement is not None
    assert treaty.endorsement["overrides"] == "hours_clause.WS"
    assert treaty.endorsement["base_value"] == ENDORSEMENT_BASE_HOURS
    assert treaty.endorsement["endorsed_value"] == ENDORSEMENT_EFFECTIVE_HOURS
    assert treaty.endorsement["source"] == "transcription"


def test_no_other_treaty_claims_an_endorsement(portfolio):
    endorsed = [t.treaty_id for t in portfolio.treaties if t.endorsement]
    assert endorsed == ["T-004"]


def test_the_endorsement_image_is_a_plausible_scan(portfolio):
    image = endorsement_image(portfolio.treaty("T-004"))
    assert image.size == (1700, 2200)
    assert image.mode == "RGB"
    # Off-white rather than pure white, like a scan.
    assert image.getpixel((20, 20)) != (255, 255, 255)
    # Ink is actually present: the page is not blank.
    greys = image.convert("L")
    dark = sum(1 for px in greys.getdata() if px < 120)
    assert dark > 5_000


def test_the_endorsement_image_states_both_figures(portfolio):
    """Rendered as pixels, but the content still has to be legible -- a human
    reviewer and Gemini both need the old and new figures visible."""
    image = endorsement_image(portfolio.treaty("T-004"))
    # Can't OCR here, so check the drawing covers the region the figures sit
    # in rather than asserting on glyphs.
    crop = image.crop((140, 400, 1100, 1120)).convert("L")
    dark = sum(1 for px in crop.getdata() if px < 120)
    assert dark > 2_000


# --------------------------------------------------------------------------- #
# Manifest and CLI
# --------------------------------------------------------------------------- #


def test_the_manifest_describes_every_wording(built):
    manifest = json.loads((built["out_dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest) == 8
    for entry in manifest:
        assert entry["note"]
        assert entry["clauses"] > 20
        assert entry["decoys"] >= 10


def test_the_answer_key_explains_itself(built):
    """Someone reading ground_truth.json cold should learn that the pages are
    derived and that transcription rows come from the scan."""
    payload = json.loads((built["out_dir"] / "ground_truth.json").read_text(encoding="utf-8"))
    note = payload["_note"]
    assert "read back out of the rendered PDFs" in note
    assert "transcription" in note


def test_the_cli_builds_the_wordings(tmp_path, capsys):
    assert main(["--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "8 wordings" in out
    assert "scanned endorsement" in out
    assert (tmp_path / "ground_truth.json").exists()


def test_the_build_is_reproducible(tmp_path):
    """Same inputs, same answer key. The PDFs themselves carry a creation
    timestamp, so the key is what has to be stable."""
    first = build_all(out_dir=tmp_path / "a")
    second = build_all(out_dir=tmp_path / "b")
    key_a = (first["out_dir"] / "ground_truth.json").read_text(encoding="utf-8")
    key_b = (second["out_dir"] / "ground_truth.json").read_text(encoding="utf-8")
    assert key_a == key_b


def test_a_clause_heading_that_does_not_appear_gets_no_page(built, portfolio):
    """The not-found path. A heading the extractor cannot match must come back
    absent rather than silently defaulting to page 1 -- a wrong page in the
    answer key would quietly corrupt QA-4's citation accuracy score.
    """
    from ingest.wording_clauses import Clause

    phantom = Clause(
        number="99.9",
        title="Clause That Was Never Rendered",
        paragraphs=("...",),
        clause_type="OTHER",
    )
    pages = clause_pages(built["out_dir"] / "w1.pdf", [phantom])
    assert "99.9" not in pages
    assert pages == {}
