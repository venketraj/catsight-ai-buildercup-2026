"""Book vs wording reconciliation (ingest.reconcile)."""

from __future__ import annotations

import json
from decimal import Decimal

from ingest.reconcile import main, normalise_value, reconcile_all, reconcile_treaty

BOOK = {
    "treaty_id": "T-X",
    "wording_id": "WX",
    "type": "CAT_XL",
    "currency": "USD",
    "perils": ["WS", "EQ"],
    "hours_clause": {"WS": 72, "EQ": 72, "FL": 0},
    "layers": [{
        "layer_no": 1, "retention": 10.0, "limit": 20.0, "premium": 2.0,
        "our_share": 0.25, "reinstatements": {"count": 1, "rate": 1.0},
    }],
}


def _ok(page=3):
    return {"status": "verified", "page": page, "clause_no": "5", "quote": "q" * 12}


def _row(result, name):
    return next(f for f in result["fields"] if f["field"] == name)


def test_values_normalise_across_types():
    assert normalise_value(20) == normalise_value("20.00") == normalise_value(20.0)
    assert normalise_value(Decimal("0.250")) == normalise_value(0.25)
    assert normalise_value(["EQ", "WS"]) == normalise_value(("WS", "EQ"))
    assert normalise_value(" USD ") == normalise_value("usd")
    assert normalise_value(True) is True
    assert normalise_value(None) is None


def test_agreeing_verified_values_reconcile():
    wording = {"currency": "USD", "layers.1.limit": "20.0", "perils": ["EQ", "WS"]}
    provenance = {name: _ok() for name in wording}
    result = reconcile_treaty("T-X", BOOK, wording, provenance, wording_id="WX")
    assert _row(result, "currency")["result"] == "match"
    assert _row(result, "layers.1.limit")["result"] == "match"
    assert _row(result, "perils")["result"] == "match"
    assert _row(result, "perils")["booked"] == ["WS", "EQ"]
    assert result["wording_id"] == "WX"


def test_a_verified_disagreement_is_a_discrepancy_with_its_citation():
    """The demo case: the body says 72h, a scanned endorsement says 168h,
    and the book was never updated."""
    wording = {"hours_clause.WS": 168}
    provenance = {"hours_clause.WS": {**_ok(7), "status": "transcribed"}}
    result = reconcile_treaty("T-X", BOOK, wording, provenance)
    row = _row(result, "hours_clause.WS")
    assert row["result"] == "differs"
    assert row["booked"] == 72 and row["wording"] == 168
    assert row["citation"]["page"] == 7
    assert result["status"] == "discrepancies"


def test_an_unverified_disagreement_is_not_reported_as_one():
    wording = {"hours_clause.WS": 168}
    provenance = {"hours_clause.WS": {"status": "unverified", "page": 2}}
    result = reconcile_treaty("T-X", BOOK, wording, provenance)
    assert _row(result, "hours_clause.WS")["result"] == "unverified"
    assert result["status"] == "incomplete"


def test_one_sided_fields():
    wording = {"exclusions": ["war"], "territory.include": ["JPN"]}
    provenance = {"exclusions": _ok()}
    result = reconcile_treaty("T-X", BOOK, wording, provenance=provenance)
    assert _row(result, "exclusions")["result"] == "wording_only"
    assert _row(result, "territory.include")["result"] == "unverified"
    assert _row(result, "currency")["result"] == "book_only"
    assert _row(result, "currency")["citation"] is None


def test_endorsement_bookkeeping_is_not_compared():
    wording = {"endorsement.overrides": "hours_clause.WS"}
    result = reconcile_treaty("T-X", BOOK, wording, None)
    assert all(f["field"] != "endorsement.overrides" for f in result["fields"])


def test_decimal_wording_values_serialise_as_strings():
    result = reconcile_treaty("T-X", BOOK, {"currency": Decimal("1.5")}, None)
    assert _row(result, "currency")["wording"] == "1.5"


def test_fully_agreeing_treaty_is_reconciled():
    wording = {"currency": "USD"}
    result = reconcile_treaty("T-X", {"currency": "USD"}, wording, {"currency": _ok()})
    assert result["status"] == "reconciled"
    assert result["counts"] == {"match": 1}


def test_reconcile_all_skips_treaties_not_in_the_book():
    extracted = {
        "extracted": {"T-X": {"currency": "USD"}, "T-GHOST": {"currency": "USD"}},
        "provenance": {"T-X": {"currency": _ok()}},
    }
    result = reconcile_all([BOOK], extracted)
    assert list(result) == ["T-X"]
    assert result["T-X"]["wording_id"] == "WX"


def test_cli_writes_and_reports_discrepancies(tmp_path, capsys):
    book = tmp_path / "book"
    book.mkdir()
    (book / "treaties.json").write_text(json.dumps([BOOK]), encoding="utf-8")
    extracted = tmp_path / "extracted.json"
    extracted.write_text(json.dumps({
        "extracted": {"T-X": {"hours_clause.WS": 168, "currency": "USD"}},
        "provenance": {"T-X": {"hours_clause.WS": _ok(7), "currency": _ok()}},
    }), encoding="utf-8")
    out = tmp_path / "out" / "reconciliation.json"

    assert main(["--book", str(book), "--extracted", str(extracted), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "differs  hours_clause.WS: book 72 vs wording 168 (p.7, clause 5)" in printed
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["T-X"]["status"] == "discrepancies"


def test_discrepancies_are_exactly_the_extraction_errors():
    """Against the committed data. The book agrees with the answer key, so
    once every field is treated as cited, the fields reconciliation flags as
    `differs` must be exactly the ones the extractor got wrong - no more (the
    comparison would be noisy) and no fewer (it would hide a misread)."""
    treaties = json.loads(open("data/book/treaties.json", encoding="utf-8").read())
    extracted = json.loads(open("data/extracted/extracted.json", encoding="utf-8").read())
    truth = json.loads(
        open("data/synthetic/wordings/ground_truth.json", encoding="utf-8").read()
    )["fields"]
    extracted["provenance"] = {
        tid: {name: _ok() for name in fields} for tid, fields in extracted["extracted"].items()
    }
    result = reconcile_all(treaties, extracted)
    assert len(result) == 8

    flagged = {
        (tid, f["field"]) for tid, r in result.items() for f in r["fields"]
        if f["result"] == "differs"
    }
    wrong = {
        (row["treaty_id"], row["field"]) for row in truth
        if row["field"] in extracted["extracted"].get(row["treaty_id"], {})
        and not row["field"].endswith(".base")
        and normalise_value(extracted["extracted"][row["treaty_id"]][row["field"]])
        != normalise_value(row["expected_value"])
    }
    assert flagged == wrong
