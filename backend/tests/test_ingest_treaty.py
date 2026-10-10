"""FR-INGEST-1 — the parts of ingestion that do not need a live model.

The Gemini call itself is exercised against the real project by
`python -m ingest.ingest_treaty`, whose output is recorded in `RESULTS.md`.
Everything around it - the schema adapter, the field flattening, the retry
predicate, the quarantine path - is deterministic and tested here, because
those are where a silent mistake would corrupt the QA-3 number rather than
produce an obvious failure.
"""

from __future__ import annotations

import json

import pytest

from catsight_agent.schemas import (
    FieldCitation,
    LayerTerms,
    Reinstatements,
    TreatyTerms,
    gemini_response_schema,
)
from ingest.ingest_treaty import (
    EXTRACTION_INSTRUCTION,
    ExtractionOutcome,
    _first_error_line,
    _is_retryable,
    _pages_from_payload,
    build_client,
    resolve_target,
    extract_treaty_terms,
    flatten_payload,
    flatten_terms,
)


# --------------------------------------------------------------------------- #
# The Gemini schema adapter
# --------------------------------------------------------------------------- #


def test_exclusive_bounds_are_converted_because_gemini_has_none():
    """The live API rejects `exclusiveMinimum` outright, so `Field(gt=0)` on
    LayerTerms.limit would make TreatyTerms unusable as a response_schema."""
    schema = gemini_response_schema(TreatyTerms)
    flat = json.dumps(schema)
    assert "exclusiveMinimum" not in flat
    assert "exclusiveMaximum" not in flat

    limit = schema["$defs"]["LayerTerms"]["properties"]["limit"]
    # `gt=0` became `minimum: 0`, which is deliberately weaker.
    assert any(
        branch.get("minimum") == 0 for branch in limit.get("anyOf", [limit])
    ), limit


def test_the_relaxed_schema_no_longer_forbids_a_zero_limit():
    """The consequence of the widening, asserted so nobody assumes a guarantee
    that is not there. FR-INGEST-3's validator is what rejects it."""
    zero_limit = {
        "treaty_id": "T-001",
        "cedent": "Test Re",
        "type": "CAT_XL",
        "perils": ["WS"],
        "territory": {"include": ["JPN"]},
        "inception": "2026-04-01",
        "expiry": "2027-03-31",
        "currency": "USD",
        "hours_clause": {"WS": 72, "EQ": 0, "FL": 0, "OTHER": 0},
        "layers": [
            {
                "layer_no": 1,
                "retention": 10,
                "limit": 0,
                "premium": 1,
                "our_share": 1,
                "reinstatements": {"count": 0, "rate": 0},
            }
        ],
    }
    with pytest.raises(ValueError):
        TreatyTerms.model_validate(zero_limit)


def test_unsupported_keywords_are_dropped_and_refs_are_kept():
    schema = gemini_response_schema(TreatyTerms)
    flat = json.dumps(schema)
    assert "additionalProperties" not in flat
    assert "$schema" not in flat
    # $ref/$defs are resolved by the live API, so inlining would buy nothing.
    assert "$defs" in schema
    assert "$ref" in flat


def test_the_adapter_recurses_into_lists_and_leaves_scalars_alone():
    from catsight_agent.schemas import _sanitise

    assert _sanitise([{"exclusiveMinimum": 3}]) == [{"minimum": 3}]
    assert _sanitise({"exclusiveMaximum": 9}) == {"maximum": 9}
    assert _sanitise("plain") == "plain"
    assert _sanitise(7) == 7


# --------------------------------------------------------------------------- #
# field_pages is a list
# --------------------------------------------------------------------------- #


def _terms(**overrides) -> TreatyTerms:
    base = dict(
        treaty_id="T-001",
        cedent="Test Re",
        type="CAT_XL",
        perils=["WS", "EQ"],
        territory={"include": ["JPN"], "exclude": []},
        inception="2026-04-01",
        expiry="2027-03-31",
        currency="USD",
        hours_clause={"WS": 72, "EQ": 72, "FL": 168, "OTHER": 168},
        exclusions=["war", "nuclear"],
        layers=[
            LayerTerms(
                layer_no=1,
                retention="10.0",
                limit="20.0",
                premium="2.0",
                our_share="0.25",
                reinstatements=Reinstatements(count=1, rate="1.0"),
            ),
            LayerTerms(
                layer_no=2,
                retention="30.0",
                limit="30.0",
                premium="1.5",
                our_share="0.10",
                reinstatements=Reinstatements(count=1, rate="1.0"),
            ),
        ],
    )
    base.update(overrides)
    return TreatyTerms(**base)


def test_pages_by_field_resolves_a_restated_field_to_the_later_page():
    """An endorsement restating a field must win: that is the page the
    operative value actually came from."""
    terms = _terms(
        field_pages=[
            FieldCitation(field="hours_clause.WS", page=2, clause_no="5"),
            FieldCitation(
                field="hours_clause.WS", page=7, clause_no="END-1", source="transcription"
            ),
        ]
    )
    assert terms.pages_by_field()["hours_clause.WS"] == 7
    provenance = terms.provenance_of("hours_clause.WS")
    assert provenance.page == 7
    assert provenance.source == "transcription"
    assert terms.provenance_of("nothing.here") is None


def test_pages_from_a_raw_payload_skips_malformed_entries():
    """A quarantined treaty's provenance is read straight from the payload, so
    a half-written entry must be ignored rather than raise."""
    pages = _pages_from_payload(
        {
            "field_pages": [
                {"field": "currency", "page": 4},
                {"field": "no_page"},
                {"page": 3},
                "not a dict",
            ]
        }
    )
    assert pages == {"currency": 4}
    assert _pages_from_payload({}) == {}


# --------------------------------------------------------------------------- #
# Flattening
# --------------------------------------------------------------------------- #


def test_flattening_produces_the_answer_keys_dotted_names():
    flat = flatten_terms(_terms())
    assert flat["type"] == "CAT_XL"
    assert flat["territory.include"] == ["JPN"]
    assert flat["hours_clause.FL"] == 168
    assert flat["layers.2.limit"] == "30.0"
    assert flat["layers.1.premium"] == "2.0"


def test_reinstatements_are_reported_per_treaty_from_the_first_layer():
    """Per-layer in the schema, per-treaty in the answer key, because every
    layer of a programme shares its reinstatement terms."""
    flat = flatten_terms(_terms())
    assert flat["reinstatements.count"] == 1
    assert flat["reinstatements.basis"] == "pro rata as to amount"
    assert "layers.1.reinstatements.count" not in flat


def test_an_omitted_field_stays_absent_so_qa3_counts_it_missing():
    """Writing None would score as a wrong value; absent scores as missing,
    which is what it is."""
    flat = flatten_payload({"type": "CAT_XL", "currency": None})
    assert flat == {"type": "CAT_XL"}
    assert "currency" not in flat


def test_an_endorsed_field_carries_both_the_operative_and_base_values():
    """W4: `hours_clause.WS` is 168 from the endorsement and
    `hours_clause.WS.base` is the 72 printed in the body."""
    flat = flatten_payload(
        {
            "hours_clause": {"WS": 168, "EQ": 72, "FL": 168},
            "endorsement": {
                "overrides": "hours_clause.WS",
                "base_value": "72",
                "endorsed_value": "168",
                "source": "7",
            },
        }
    )
    assert flat["hours_clause.WS"] == 168
    assert flat["hours_clause.WS.base"] == "72"
    assert flat["endorsement.overrides"] == "hours_clause.WS"


def test_an_endorsement_without_an_overrides_name_adds_nothing():
    flat = flatten_payload({"endorsement": {"base_value": "72"}})
    assert "endorsement.overrides" not in flat


def test_an_endorsement_naming_a_field_but_no_base_records_only_the_override():
    """The model sometimes names what it replaced without quoting the old
    value. That is still worth recording - a `.base` of None would score as a
    wrong value rather than a missing one."""
    flat = flatten_payload({"endorsement": {"overrides": "hours_clause.WS"}})
    assert flat == {"endorsement.overrides": "hours_clause.WS"}
    assert "hours_clause.WS.base" not in flat


def test_a_quota_share_reports_cession_and_event_limit():
    flat = flatten_payload({"qs": {"cession_pct": "0.2", "event_limit": "15.0"}})
    assert flat["qs.cession_pct"] == "0.2"
    assert flat["qs.event_limit"] == "15.0"


def test_a_layer_without_a_number_is_skipped_rather_than_mislabelled():
    """Guessing a layer number would attach real figures to the wrong layer,
    which is worse than dropping them."""
    flat = flatten_payload(
        {"layers": [{"retention": 1, "limit": 2}, {"layer_no": 2, "limit": "5.0"}]}
    )
    assert flat == {"layers.2.limit": "5.0"}


def test_flattening_an_empty_payload_is_empty_not_an_error():
    assert flatten_payload({}) == {}


# --------------------------------------------------------------------------- #
# Retry predicate and the quarantine path
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "message",
    [
        "429 RESOURCE_EXHAUSTED",
        "ClientError: 429 Resource exhausted",
        "503 UNAVAILABLE",
    ],
)
def test_quota_and_transient_errors_are_retried(message):
    assert _is_retryable(Exception(message))


@pytest.mark.parametrize("message", ["400 INVALID_ARGUMENT", "404 Not Found", "nope"])
def test_a_bad_request_is_not_retried(message):
    """A 400 is a bug in the request. Retrying it turns a schema error into a
    slow schema error."""
    assert not _is_retryable(Exception(message))


def test_the_validation_reason_is_extracted_from_the_pydantic_noise():
    try:
        TreatyTerms.model_validate(
            {
                "treaty_id": "T-003",
                "cedent": "X",
                "type": "CAT_XL",
                "perils": ["WS"],
                "territory": {"include": ["JPN"]},
                "inception": "2026-04-01",
                "expiry": "2027-03-31",
                "currency": "USD",
                "hours_clause": {"WS": 72, "EQ": 0, "FL": 0, "OTHER": 0},
                "layers": [
                    {
                        "layer_no": 1,
                        "retention": "10.1",
                        "limit": "1.8",
                        "premium": "1.0",
                        "our_share": "0.2",
                        "reinstatements": {"count": 1, "rate": "1.0"},
                    },
                    {
                        "layer_no": 2,
                        "retention": "22.0",
                        "limit": "14.1",
                        "premium": "3.97",
                        "our_share": "0.2",
                        "reinstatements": {"count": 1, "rate": "1.0"},
                    },
                ],
            }
        )
    except Exception as exc:
        reason = _first_error_line(exc)
    else:  # pragma: no cover - the payload above is the real failing one
        pytest.fail("expected the contiguity validator to reject this")

    assert reason.startswith("layers are not contiguous")
    assert "Value error" not in reason


def test_a_non_pydantic_error_still_yields_one_line():
    assert _first_error_line(RuntimeError("boom")).startswith("RuntimeError: boom")


def test_a_quarantined_outcome_still_carries_its_fields():
    """FR-INGEST-3 rejection is a refusal to ingest, not a measurement of
    zero. One misread limit must not read as 28 wrong fields."""

    class Rejecting:
        class models:
            @staticmethod
            def generate_content(**kwargs):
                class R:
                    text = json.dumps(
                        {
                            "cedent": "X",
                            "type": "CAT_XL",
                            "perils": ["WS"],
                            "territory": {"include": ["JPN"]},
                            "inception": "2026-04-01",
                            "expiry": "2027-03-31",
                            "currency": "USD",
                            "hours_clause": {"WS": 72, "EQ": 0, "FL": 0, "OTHER": 0},
                            "layers": [
                                {
                                    "layer_no": 1,
                                    "retention": "10.1",
                                    "limit": "1.8",
                                    "premium": "1.0",
                                    "our_share": "0.2",
                                    "reinstatements": {"count": 1, "rate": "1.0"},
                                },
                                {
                                    "layer_no": 2,
                                    "retention": "22.0",
                                    "limit": "14.1",
                                    "premium": "3.97",
                                    "our_share": "0.2",
                                    "reinstatements": {"count": 1, "rate": "1.0"},
                                },
                            ],
                            "field_pages": [
                                {"field": "currency", "page": 4, "clause_no": "14"}
                            ],
                        }
                    )

                return R()

    pdf = __import__("pathlib").Path("data/synthetic/wordings/w3.pdf")
    outcome = extract_treaty_terms(pdf, "T-003", client=Rejecting(), model="fake")

    assert not outcome.ok
    assert outcome.quarantined
    assert outcome.error is None
    assert "not contiguous" in outcome.validation_error
    # The point of the quarantine path:
    assert outcome.fields["currency"] == "USD"
    assert outcome.fields["layers.1.limit"] == "1.8"
    assert outcome.pages == {"currency": 4}


def test_a_hard_failure_records_the_error_and_no_fields():
    class Exploding:
        class models:
            @staticmethod
            def generate_content(**kwargs):
                raise RuntimeError("400 INVALID_ARGUMENT")

    pdf = __import__("pathlib").Path("data/synthetic/wordings/w1.pdf")
    outcome = extract_treaty_terms(pdf, "T-001", client=Exploding(), model="fake")
    assert outcome.error is not None
    assert not outcome.quarantined
    assert outcome.fields == {}


def test_a_successful_extraction_is_validated_and_flattened():
    payload = _terms().model_dump(mode="json")
    payload.pop("treaty_id")

    class Good:
        class models:
            @staticmethod
            def generate_content(**kwargs):
                class R:
                    text = json.dumps(payload)

                return R()

    pdf = __import__("pathlib").Path("data/synthetic/wordings/w1.pdf")
    outcome = extract_treaty_terms(pdf, "T-001", client=Good(), model="fake")
    assert outcome.ok and not outcome.quarantined
    assert outcome.fields["layers.1.limit"] == "20.0"
    assert isinstance(outcome, ExtractionOutcome)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_the_client_refuses_to_guess_a_project(monkeypatch):
    """Nothing in the codebase may hardcode a project id - the rule in
    `.env.example`. An unset variable must say so, not default to something."""
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
        build_client()
    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
        resolve_target()


def test_the_location_defaults_to_global_not_the_firestore_region(monkeypatch):
    """Gemini 3.x is not served from us-central1, where Cloud Run, Firestore
    and GCS live. Defaulting to the data region would fail at the first call."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p-from-env")
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    assert resolve_target() == ("p-from-env", "global")


def test_explicit_arguments_beat_the_environment(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p-from-env")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    assert resolve_target() == ("p-from-env", "us-central1")
    assert resolve_target("p-arg", "europe-west4") == ("p-arg", "europe-west4")


def test_the_instruction_pins_the_things_that_were_actually_got_wrong():
    """Each of these sentences exists because a live run failed without it.
    A regression here is a silent accuracy drop, so they are asserted."""
    assert "MILLIONS" in EXTRACTION_INSTRUCTION
    assert "NEVER subtract the retention from the limit" in EXTRACTION_INSTRUCTION
    assert "whether or not this treaty covers that peril" in EXTRACTION_INSTRUCTION
    assert "scope-of-business terms" in EXTRACTION_INSTRUCTION
    assert "field_pages` is a LIST" in EXTRACTION_INSTRUCTION
    assert "Leaving `endorsement` empty" in EXTRACTION_INSTRUCTION


# --------------------------------------------------------------------------- #
# Backoff and the CLI gate
# --------------------------------------------------------------------------- #


def test_a_retryable_error_is_retried_then_succeeds(capsys):
    """Quota must not be reported as a wrong answer. `base_delay` is tiny so
    the test does not actually wait out a backoff."""
    from ingest.ingest_treaty import _generate_with_retry

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        return "ok"

    assert _generate_with_retry(flaky, attempts=5, base_delay=0.001) == "ok"
    assert calls["n"] == 3
    assert "retrying in" in capsys.readouterr().out


def test_retries_are_bounded_and_the_last_error_is_raised():
    from ingest.ingest_treaty import _generate_with_retry

    calls = {"n": 0}

    def always_throttled():
        calls["n"] += 1
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    with pytest.raises(RuntimeError, match="429"):
        _generate_with_retry(always_throttled, attempts=3, base_delay=0.001)
    assert calls["n"] == 3


def test_a_non_retryable_error_is_raised_on_the_first_attempt():
    from ingest.ingest_treaty import _generate_with_retry

    calls = {"n": 0}

    def bad_request():
        calls["n"] += 1
        raise RuntimeError("400 INVALID_ARGUMENT")

    with pytest.raises(RuntimeError, match="400"):
        _generate_with_retry(bad_request, attempts=5, base_delay=0.001)
    assert calls["n"] == 1, "a 400 must not be retried"


def test_decimals_serialise_as_strings_not_floats():
    """A float round-trip reintroduces the binary error the Decimal pipeline
    exists to avoid - the reason given in schemas.py."""
    from decimal import Decimal

    from ingest.ingest_treaty import _jsonable

    assert _jsonable(Decimal("7.325")) == "7.325"
    assert _jsonable({"a": [Decimal("1.5")]}) == {"a": ["1.5"]}
    assert _jsonable((Decimal("2.0"),)) == ["2.0"]
    assert _jsonable("plain") == "plain"
    assert _jsonable(3) == 3


def _fake_outcome(treaty_id, fields, pages, **kw):
    """An outcome whose every cited page is treated as verified."""
    from ingest.provenance import FieldProvenance, ProvenanceReport

    provenance = ProvenanceReport(
        treaty_id,
        {
            name: FieldProvenance(name, "verified", page, None, "a verified quote")
            for name, page in pages.items()
        },
    )
    kw.setdefault("provenance", provenance)
    return ExtractionOutcome(
        treaty_id=treaty_id, terms=None, fields=fields, pages=pages, **kw
    )


def test_the_cli_gate_fails_when_a_treaty_is_quarantined(monkeypatch, tmp_path, capsys):
    """The point of reporting both numbers. Field accuracy can be perfect
    while the treaty would never be ingested, and the gate must fail."""
    import ingest.ingest_treaty as module

    truth = json.loads(
        (module.Path("data/synthetic/wordings/ground_truth.json")).read_text(
            encoding="utf-8"
        )
    )
    wanted = [r for r in truth["fields"] if r["treaty_id"] == "T-001"]
    perfect = {r["field"]: r["expected_value"] for r in wanted}
    pages = {r["field"]: r["page"] for r in wanted}

    monkeypatch.setattr(module, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(
        module,
        "extract_treaty_terms",
        lambda *a, **k: _fake_outcome(
            "T-001", perfect, pages, validation_error="layers are not contiguous"
        ),
    )

    code = module.main(["--only", "T-001", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert "accuracy           100.0%" in out
    assert "quarantined        1" in out
    assert "S3 gate: FAIL" in out
    assert code == 1


def test_the_cli_gate_passes_when_everything_is_clean(monkeypatch, tmp_path, capsys):
    import ingest.ingest_treaty as module

    truth = json.loads(
        (module.Path("data/synthetic/wordings/ground_truth.json")).read_text(
            encoding="utf-8"
        )
    )
    wanted = [r for r in truth["fields"] if r["treaty_id"] == "T-001"]
    perfect = {r["field"]: r["expected_value"] for r in wanted}
    pages = {r["field"]: r["page"] for r in wanted}

    class Terms:
        pass

    def clean(*a, **k):
        outcome = _fake_outcome("T-001", perfect, pages)
        outcome.terms = Terms()  # ok -> True
        return outcome

    monkeypatch.setattr(module, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(module, "extract_treaty_terms", clean)

    code = module.main(["--only", "T-001", "--out", str(tmp_path), "--chunk"])
    out = capsys.readouterr().out
    assert "S3 gate: PASS" in out
    assert "ingestable         1" in out
    assert "chunks" in out
    assert code == 0
    written = json.loads((tmp_path / "extracted.json").read_text(encoding="utf-8"))
    assert written["extracted"]["T-001"]["currency"] == "USD"
    assert written["provenance"]["T-001"]["currency"]["status"] == "verified"


def test_the_cli_gate_fails_when_citations_do_not_verify(monkeypatch, tmp_path, capsys):
    """Perfect values with unverifiable citations still fail: C-7 says a
    value without a checkable reference is not usable."""
    import ingest.ingest_treaty as module
    from ingest.provenance import FieldProvenance, ProvenanceReport

    truth = json.loads(
        module.Path("data/synthetic/wordings/ground_truth.json").read_text(encoding="utf-8")
    )
    wanted = [r for r in truth["fields"] if r["treaty_id"] == "T-001"]
    perfect = {r["field"]: r["expected_value"] for r in wanted}
    pages = {r["field"]: r["page"] for r in wanted}

    class Terms:
        pass

    def unverified(*a, **k):
        report = ProvenanceReport(
            "T-001",
            {n: FieldProvenance(n, "unverified", p, reason="paraphrased") for n, p in pages.items()},
        )
        outcome = _fake_outcome(
            "T-001", perfect, pages, provenance=report, repair_error="RuntimeError: boom"
        )
        outcome.terms = Terms()
        return outcome

    monkeypatch.setattr(module, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(module, "extract_treaty_terms", unverified)

    code = module.main(["--only", "T-001", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert "unverified  currency: paraphrased" in out
    assert "citation repair failed: RuntimeError: boom" in out
    assert "S3 gate: FAIL" in out
    assert code == 1
    written = json.loads((tmp_path / "extracted.json").read_text(encoding="utf-8"))
    # Unverified pages earn no QA-4 credit.
    assert written["pages"]["T-001"] == {}


def test_the_cli_falls_back_to_raw_pages_without_provenance(monkeypatch, tmp_path, capsys):
    import ingest.ingest_treaty as module

    def no_text(*a, **k):
        return _fake_outcome("T-001", {"currency": "USD"}, {"currency": 4}, provenance=None)

    monkeypatch.setattr(module, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(module, "extract_treaty_terms", no_text)

    module.main(["--only", "T-001", "--out", str(tmp_path)])
    written = json.loads((tmp_path / "extracted.json").read_text(encoding="utf-8"))
    assert written["pages"]["T-001"] == {"currency": 4}


def test_the_cli_reports_a_hard_failure_separately(monkeypatch, tmp_path, capsys):
    import ingest.ingest_treaty as module

    monkeypatch.setattr(module, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(
        module,
        "extract_treaty_terms",
        lambda *a, **k: _fake_outcome("T-001", {}, {}, error="RuntimeError: boom"),
    )
    code = module.main(["--only", "T-001", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert "hard failures      1" in out
    assert "failed       T-001" in out
    assert code == 1


def test_a_manifest_wrapped_in_an_object_is_also_accepted():
    """build_wordings writes a list; a dict with a `wordings` key is the other
    plausible shape and costs nothing to support."""
    import ingest.ingest_treaty as module

    rows = module._manifest_rows(module.Path("data/synthetic/wordings"))
    assert rows and rows[0]["treaty_id"].startswith("T-")
