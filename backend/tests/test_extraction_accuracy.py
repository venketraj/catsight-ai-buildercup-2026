"""QA-3 / B3 — the extraction accuracy harness.

This harness produces the number that goes on the results slide, so the tests
are mostly about the ways a scorer can lie: coercing values it shouldn't,
skipping fields it can't find, or averaging a weakness out of sight.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from ingest.build_wordings import build_all
from qa.extraction_accuracy import (
    PASS_BAR,
    AccuracyReport,
    FieldOutcome,
    format_report,
    load_ground_truth,
    main,
    score_extraction,
    values_match,
)


@pytest.fixture(scope="module")
def truth(tmp_path_factory) -> list[dict]:
    out = build_all(out_dir=tmp_path_factory.mktemp("wordings"))["out_dir"]
    return load_ground_truth(out / "ground_truth.json")


@pytest.fixture
def perfect(truth) -> tuple[dict, dict]:
    extracted: dict[str, dict] = {}
    pages: dict[str, dict] = {}
    for row in truth:
        extracted.setdefault(row["treaty_id"], {})[row["field"]] = row["expected_value"]
        pages.setdefault(row["treaty_id"], {})[row["field"]] = row["page"]
    return extracted, pages


# --------------------------------------------------------------------------- #
# Comparison — typed, not textual
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "expected, actual",
    [
        (72, "72"),  # a model returning a string number
        (72, 72.0),
        ("72", 72),
        (0.25, Decimal("0.25")),
        (0.25, "0.250000"),
        (2.0, 2),
        ("USD", " usd "),  # case and whitespace
        ("pro rata as to amount", "Pro Rata  As To Amount"),
        (["WS", "EQ"], ["EQ", "WS"]),  # clause order carries no meaning
        (["JP-47"], ("JP-47",)),
        ([], []),
        (None, None),
    ],
)
def test_equivalent_values_match(expected, actual):
    """A string compare fails all of these and reports an accuracy far below
    the truth - the sort of error that gets a threshold loosened when the
    extractor was right."""
    assert values_match(expected, actual)


@pytest.mark.parametrize(
    "expected, actual",
    [
        (72, 96),
        (72, None),
        (None, 72),
        (0.25, 0.26),
        ("JPN", ["JPN"]),  # scalar vs list is a real mismatch
        (["JPN"], "JPN"),
        (["WS", "EQ"], ["WS"]),
        (["WS"], ["WS", "EQ"]),
        ("CAT_XL", "QS"),
        (1, True),  # True == 1 is never what a field comparison means
        (True, 1),
        (0, False),
    ],
)
def test_different_values_do_not_match(expected, actual):
    assert not values_match(expected, actual)


def test_numeric_comparison_tolerates_only_rounding_noise():
    assert values_match(Decimal("24.4"), Decimal("24.400000"))
    assert values_match(24.4, 24.4000001)
    assert not values_match(24.4, 24.41)


def test_a_non_numeric_string_is_compared_as_text():
    assert values_match("seventy-two", "Seventy-Two")
    assert not values_match("seventy-two", "ninety-six")


def test_nan_and_infinity_are_not_treated_as_numbers():
    assert not values_match(72, float("nan"))
    assert not values_match(72, float("inf"))


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def test_a_perfect_extraction_scores_one_hundred_percent(truth, perfect):
    extracted, pages = perfect
    report = score_extraction(truth, extracted, pages=pages)
    assert report.total == len(truth)
    assert report.accuracy == 1.0
    assert report.page_accuracy == 1.0
    assert report.passed
    assert report.failures() == []


def test_the_answer_key_claims_each_field_on_exactly_one_page(truth):
    """A field claimed on two pages cannot be cited correctly, which makes
    QA-4's page accuracy unscoreable for it. W8 originally did this - its
    hours clause appeared in Clause 5 and again in the Definitions clause.
    """
    seen: dict[tuple[str, str], int] = {}
    for row in truth:
        key = (row["treaty_id"], row["field"])
        seen[key] = seen.get(key, 0) + 1
    duplicates = {key: count for key, count in seen.items() if count > 1}
    assert not duplicates, duplicates


def test_a_missing_field_counts_as_wrong_not_skipped(truth, perfect):
    """Otherwise omitting the hard fields is the easiest route to a high
    score."""
    extracted, pages = perfect
    extracted["T-001"].pop("hours_clause.WS")
    report = score_extraction(truth, extracted, pages=pages)
    assert report.missing == 1
    assert report.accuracy < 1.0
    failure = next(f for f in report.failures() if f.field == "hours_clause.WS")
    assert failure.missing


def test_an_unknown_treaty_in_the_extraction_is_simply_unscored(truth, perfect):
    extracted, pages = perfect
    extracted["T-999"] = {"invented": 1}
    report = score_extraction(truth, extracted, pages=pages)
    assert report.accuracy == 1.0
    assert "T-999" not in report.by_treaty()


def test_scoring_can_be_scoped_to_particular_treaties(truth, perfect):
    extracted, pages = perfect
    report = score_extraction(truth, extracted, pages=pages, only_treaties=["T-001"])
    assert set(report.by_treaty()) == {"T-001"}
    assert report.total < len(truth)


def test_an_empty_report_does_not_pass_by_vacuous_truth():
    """0/0 is 100% arithmetically. It must not be a PASS."""
    report = AccuracyReport()
    assert report.accuracy == 0.0
    assert not report.passed


def test_the_pass_bar_is_ninety_five_percent():
    assert PASS_BAR == 0.95


def test_a_score_just_below_the_bar_fails(truth, perfect):
    extracted, pages = perfect
    to_break = int(len(truth) * 0.06) + 1
    broken = 0
    for treaty_fields in extracted.values():
        for name in list(treaty_fields):
            if broken >= to_break:
                break
            treaty_fields[name] = "deliberately wrong"
            broken += 1
    report = score_extraction(truth, extracted, pages=pages)
    assert report.accuracy < PASS_BAR
    assert not report.passed


# --------------------------------------------------------------------------- #
# Citation pages — scored separately on purpose
# --------------------------------------------------------------------------- #


def test_a_right_value_on_a_wrong_page_is_a_separate_failure(truth, perfect):
    """The number is right and the audit trail is wrong, which in a regulated
    setting is arguably worse. Averaging the two would hide both."""
    extracted, pages = perfect
    pages["T-001"]["hours_clause.WS"] = 99
    report = score_extraction(truth, extracted, pages=pages)
    assert report.accuracy == 1.0  # the value was correct
    assert report.page_accuracy is not None and report.page_accuracy < 1.0


def test_pages_are_unscored_rather_than_wrong_when_not_reported(truth, perfect):
    extracted, _ = perfect
    report = score_extraction(truth, extracted)
    assert report.accuracy == 1.0
    assert report.page_accuracy is None
    assert report.pages_scored == 0


def test_a_partially_reported_page_set_scores_only_what_was_offered(truth, perfect):
    extracted, pages = perfect
    only_one = {"T-001": {"currency": pages["T-001"]["currency"]}}
    report = score_extraction(truth, extracted, pages=only_one)
    assert report.pages_scored == 1
    assert report.page_accuracy == 1.0


def test_page_matching_is_unscored_when_either_side_is_absent():
    outcome = FieldOutcome(
        treaty_id="T-001", field="f", expected=1, actual=1, matched=True,
        expected_page=None, actual_page=3,
    )
    assert outcome.page_matched is None


# --------------------------------------------------------------------------- #
# Breakdowns — so a weakness cannot average away
# --------------------------------------------------------------------------- #


def test_results_break_down_by_treaty(truth, perfect):
    extracted, pages = perfect
    report = score_extraction(truth, extracted, pages=pages)
    rows = report.by_treaty()
    assert len(rows) == 8
    for correct, total in rows.values():
        assert correct == total


def test_transcription_reads_are_reported_separately_from_text_reads(truth, perfect):
    """FR-ENDORSE-3 badges them differently in the UI, so they are scored
    differently here. A model that reads clean text well and scans badly has
    a very different weakness from one that is uniformly mediocre - and at
    two transcription fields out of 186, the average would hide it entirely.
    """
    extracted, pages = perfect
    extracted["T-004"].pop("hours_clause.WS")  # the scanned endorsement
    report = score_extraction(truth, extracted, pages=pages)

    by_source = report.by_source()
    assert set(by_source) == {"text", "transcription"}
    text_correct, text_total = by_source["text"]
    scan_correct, scan_total = by_source["transcription"]
    assert text_correct == text_total  # text layer unaffected
    assert scan_correct < scan_total  # the scan failed
    # And the overall figure barely moves, which is the point.
    assert report.accuracy > 0.99


def test_by_source_is_a_single_row_when_nothing_was_transcribed(truth, perfect):
    extracted, pages = perfect
    report = score_extraction(
        truth, extracted, pages=pages, only_treaties=["T-001"]
    )
    assert set(report.by_source()) == {"text"}


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def test_the_report_states_the_result_and_the_bar(truth, perfect):
    extracted, pages = perfect
    text = format_report(score_extraction(truth, extracted, pages=pages))
    assert "PASS" in text
    assert "bar 95%" in text
    assert "by treaty" in text


def test_the_report_lists_failures_rather_than_only_counting_them(truth, perfect):
    """QA-4 requires known misses to be reported. A bare percentage invites
    nobody to look at them."""
    extracted, pages = perfect
    extracted["T-002"]["hours_clause.WS"] = 72  # actually 96
    text = format_report(score_extraction(truth, extracted, pages=pages))
    assert "failures (1)" in text
    assert "hours_clause.WS" in text
    assert "expected 96" in text


def test_the_report_truncates_a_long_failure_list(truth):
    report = score_extraction(truth, {})
    text = format_report(report, max_failures=5)
    assert "and " in text and "more" in text


def test_the_report_names_an_absent_field_as_absent(truth, perfect):
    extracted, pages = perfect
    extracted["T-001"].pop("currency")
    text = format_report(score_extraction(truth, extracted, pages=pages))
    assert "absent" in text


def test_the_report_says_when_no_pages_were_reported(truth, perfect):
    extracted, _ = perfect
    text = format_report(score_extraction(truth, extracted))
    assert "not reported by the extractor" in text


# --------------------------------------------------------------------------- #
# CLI — it gates a checkpoint, so the exit code matters
# --------------------------------------------------------------------------- #


def test_the_cli_exits_zero_when_the_bar_is_met(tmp_path, truth, perfect, capsys):
    extracted, pages = perfect
    truth_path = tmp_path / "truth.json"
    truth_path.write_text(json.dumps({"fields": truth}), encoding="utf-8")
    extracted_path = tmp_path / "extracted.json"
    extracted_path.write_text(
        json.dumps({"extracted": extracted, "pages": pages}), encoding="utf-8"
    )
    code = main(["--truth", str(truth_path), "--extracted", str(extracted_path)])
    assert code == 0
    assert "PASS" in capsys.readouterr().out


def test_the_cli_exits_one_when_accuracy_is_below_the_bar(tmp_path, truth, capsys):
    truth_path = tmp_path / "truth.json"
    truth_path.write_text(json.dumps({"fields": truth}), encoding="utf-8")
    extracted_path = tmp_path / "extracted.json"
    extracted_path.write_text(json.dumps({}), encoding="utf-8")
    assert main(["--truth", str(truth_path), "--extracted", str(extracted_path)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_the_cli_accepts_a_bare_extraction_without_a_pages_sibling(tmp_path, truth, perfect):
    extracted, _ = perfect
    truth_path = tmp_path / "truth.json"
    truth_path.write_text(json.dumps({"fields": truth}), encoding="utf-8")
    extracted_path = tmp_path / "extracted.json"
    extracted_path.write_text(json.dumps(extracted), encoding="utf-8")
    assert main(["--truth", str(truth_path), "--extracted", str(extracted_path)]) == 0


def test_the_cli_can_scope_to_one_treaty(tmp_path, truth, perfect, capsys):
    extracted, pages = perfect
    truth_path = tmp_path / "truth.json"
    truth_path.write_text(json.dumps({"fields": truth}), encoding="utf-8")
    extracted_path = tmp_path / "extracted.json"
    extracted_path.write_text(
        json.dumps({"extracted": extracted, "pages": pages}), encoding="utf-8"
    )
    assert main([
        "--truth", str(truth_path), "--extracted", str(extracted_path), "--only", "T-001",
    ]) == 0
    out = capsys.readouterr().out
    assert "T-001" in out
    assert "T-002" not in out


def test_loading_a_bare_list_answer_key_works(tmp_path, truth):
    """So an older or hand-written key still loads."""
    path = tmp_path / "truth.json"
    path.write_text(json.dumps(truth), encoding="utf-8")
    assert load_ground_truth(path) == truth


def test_booleans_inside_lists_are_not_coerced_to_numbers():
    """True == 1 arithmetically. In a field comparison that is never what is
    meant, so booleans compare as booleans even nested in a list."""
    assert values_match([True], [True])
    assert not values_match([True], [1])
    assert not values_match([1], [True])


def test_an_uncoercible_type_compares_by_equality():
    """A dict or an object is neither a number nor a string, so it falls
    through to a plain comparison rather than raising."""
    assert values_match({"a": 1}, {"a": 1})
    assert not values_match({"a": 1}, {"a": 2})


def test_a_malformed_numeric_string_is_treated_as_text_not_a_number():
    assert not values_match(72, "seventy-two")
    assert values_match("not a number", "not a number")
