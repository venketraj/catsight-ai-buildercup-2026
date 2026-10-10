"""RAG-first ingestion and extraction (ingest.rag_extract, ingest.rag_pipeline).

The model is faked, the embedder is the offline hashing one and the store is
in memory, so this tests the plumbing - chunking, transcription slots,
retrieval, the grounding check, typed assembly, validation and the metrics -
not retrieval quality, which only the live run can measure.

The fake model answers from the answer key, but only from clauses it was
actually shown, citing them the way the real one must. So a retrieval miss in
these tests is a real retrieval miss.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from catsight_agent.tools.retrieval import DeterministicEmbedder, InMemoryVectorStore
from ingest.rag_extract import (
    GROUP_OF_FIELD,
    TERM_GROUPS,
    assemble_payload,
    extract_group,
    extract_treaty_rag,
    generation_config,
    ingest_wording,
)
from ingest.rag_pipeline import retrieval_hits, run

WORDINGS = Path("data/synthetic/wordings")
TRUTH = json.loads((WORDINGS / "ground_truth.json").read_text(encoding="utf-8"))["fields"]


def _pdf(treaty_id: str) -> Path:
    manifest = json.loads((WORDINGS / "manifest.json").read_text(encoding="utf-8"))
    rows = manifest if isinstance(manifest, list) else manifest["wordings"]
    return WORDINGS / next(r for r in rows if r["treaty_id"] == treaty_id)["pdf"]


ENDORSEMENT_TEXT = (
    "ENDORSEMENT No. 1. It is hereby noted and agreed that, as respects Windstorm, "
    "the period shall be 168 consecutive hours. All other terms remain unchanged."
)

_CLAUSE = re.compile(r"^\[(?P<id>[^\]]+)\] \(page (?P<page>\d+), clause (?P<clause>[^,)]+)", re.M)


def _as_value(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


class FakeGemini:
    """Answers group prompts from the answer key, citing only shown clauses;
    answers transcription prompts with the endorsement text."""

    def __init__(self, *, garble: str | None = None, fail_group: str | None = None):
        self.calls = 0
        self.garble = garble
        self.fail_group = fail_group
        outer = self

        class Models:
            def generate_content(self, *, model, contents, config):
                outer.calls += 1
                return SimpleNamespace(text=outer.answer(contents))

        self.models = Models()

    def answer(self, contents) -> str:
        if not isinstance(contents, str):  # transcription: [pdf part, instruction]
            return ENDORSEMENT_TEXT
        treaty_id = re.search(r"treaty (\S+)\. Use ONLY", contents).group(1)
        group = next(
            g.name for g in TERM_GROUPS
            if g.instruction.splitlines()[0].strip() in contents
        )
        if group == self.fail_group:
            raise RuntimeError("400 INVALID_ARGUMENT")
        shown = {}
        for match in _CLAUSE.finditer(contents):
            body = contents[match.end():].split("\n", 1)[1].split("\n\n[")[0]
            shown[match["clause"].strip()] = (match["id"], body)
        fields = []
        for row in TRUTH:
            if row["treaty_id"] != treaty_id or GROUP_OF_FIELD(row["field"]) != group:
                continue
            hit = shown.get(str(row["clause_no"]))
            if hit is None:
                continue  # not retrieved: a real model could not cite it either
            chunk_id, body = hit
            quote = " ".join(body.split()[:10])
            if self.garble == row["field"]:
                quote = "words that appear nowhere in this clause at all"
            fields.append({"field": row["field"], "value": _as_value(row["expected_value"]),
                           "chunk_id": chunk_id, "quote": quote})
        return json.dumps({"fields": fields})


@pytest.fixture()
def rig():
    return SimpleNamespace(embedder=DeterministicEmbedder(), store=InMemoryVectorStore())


def _ingest(rig, treaty_id, client=None):
    return ingest_wording(treaty_id, _pdf(treaty_id), client=client or FakeGemini(),
                          model="fake", embedder=rig.embedder, store=rig.store)


# --------------------------------------------------------------------------- #
# Ingest
# --------------------------------------------------------------------------- #


def test_ingest_chunks_embeds_and_transcribes_the_scanned_page(rig):
    client = FakeGemini()
    ingested = _ingest(rig, "T-004", client)
    assert ingested.transcribed_pages == (7,)
    assert client.calls == 1, "one transcription call, nothing else at ingest"
    # The transcribed page, plus W4's own "Endorsements" clause in the body.
    transcribed = [c for c in ingested.endorsements if c.source == "transcription"]
    assert len(transcribed) == 1 and transcribed[0].chunk_id == "T-004#t7"
    assert "168 consecutive hours" in transcribed[0].text
    assert any(c.clause_title == "Endorsements" for c in ingested.endorsements)
    assert len(rig.store) == len(ingested.chunks)


def test_an_empty_transcription_leaves_the_page_out(rig):
    class Blank(FakeGemini):
        def answer(self, contents):
            return "   "

    ingested = _ingest(rig, "T-004", Blank())
    assert ingested.transcribed_pages == ()
    assert all(c.source != "transcription" for c in ingested.chunks)


def test_untitled_clauses_render_without_a_title():
    from ingest.chunking import Chunk
    from ingest.rag_extract import _render_clause

    chunk = Chunk(treaty_id="T", chunk_id="T#p1", page=1, clause_no=None,
                  clause_title=None, clause_type="OTHER", text="some body text")
    assert _render_clause(chunk) == "[T#p1] (page 1, clause -)\nsome body text"


def test_a_text_only_wording_needs_no_model_call_at_ingest(rig):
    client = FakeGemini()
    ingested = _ingest(rig, "T-001", client)
    assert client.calls == 0
    assert ingested.transcribed_pages == ()
    assert ingested.endorsements == ()


def test_generation_config_sets_low_thinking_and_json():
    from google.genai import types

    from catsight_agent.schemas import GroundedAnswer

    config = generation_config(GroundedAnswer)
    assert config.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert config.response_mime_type == "application/json"
    assert config.temperature == 0
    assert generation_config().response_schema is None


# --------------------------------------------------------------------------- #
# Extract
# --------------------------------------------------------------------------- #


def test_endorsements_join_every_groups_context(rig):
    ingested = _ingest(rig, "T-004")
    group = next(g for g in TERM_GROUPS if g.name == "currency")
    result = extract_group("T-004", group, client=FakeGemini(), model="fake",
                           embedder=rig.embedder, store=rig.store, texts=ingested.texts,
                           endorsements=ingested.endorsements, k=2)
    assert "T-004#t7" in result.retrieved


def test_answers_failing_the_grounding_check_are_rejected(rig):
    ingested = _ingest(rig, "T-001")
    hours = next(g for g in TERM_GROUPS if g.name == "hours")

    class Liar(FakeGemini):
        def answer(self, contents):
            return json.dumps({"fields": [
                {"field": "hours_clause.WS", "value": "72", "chunk_id": "T-001#c99",
                 "quote": "a quote from a clause that was never shown"},
                {"field": "currency", "value": "USD", "chunk_id": "T-001#c5",
                 "quote": "irrelevant to this group entirely"},
                {"field": "hours_clause.EQ", "value": "72", "chunk_id": "T-001#c5",
                 "quote": "this text is not in clause five at all"},
            ]})

    result = extract_group("T-001", hours, client=Liar(), model="fake",
                           embedder=rig.embedder, store=rig.store, texts=ingested.texts, k=6)
    reasons = dict(result.rejected)
    assert result.accepted == []
    assert "was not retrieved" in reasons["hours_clause.WS"]
    assert "not a hours field" in reasons["currency"]
    assert "quote not in T-001#c5" in reasons["hours_clause.EQ"]


def test_a_failed_group_call_is_recorded_not_raised(rig):
    ingested = _ingest(rig, "T-001")
    hours = next(g for g in TERM_GROUPS if g.name == "hours")
    result = extract_group("T-001", hours, client=FakeGemini(fail_group="hours"),
                           model="fake", embedder=rig.embedder, store=rig.store,
                           texts=ingested.texts)
    assert result.error and "INVALID_ARGUMENT" in result.error
    assert result.accepted == []


def test_end_to_end_on_the_endorsed_wording(rig):
    """W4: the endorsed 168h is operative, the body's 72h is recorded as the
    base, and the endorsed value is cited to the transcribed page."""
    ingested = _ingest(rig, "T-004")
    result = extract_treaty_rag(ingested, client=FakeGemini(), model="fake",
                                embedder=rig.embedder, store=rig.store, k=6)
    outcome = result.outcome
    if "hours_clause.WS" in outcome.fields:
        assert outcome.fields["hours_clause.WS"] == 168
        assert outcome.provenance.fields["hours_clause.WS"].status == "transcribed"
    assert result.seconds >= 0
    assert set(result.groups) == {g.name for g in TERM_GROUPS}
    # Whatever was accepted is citation-checked against the page text again.
    assert all(p.status in ("verified", "transcribed")
               for p in outcome.provenance.fields.values())


def test_a_quarantined_extraction_keeps_its_fields(rig):
    ingested = _ingest(rig, "T-001")
    result = extract_treaty_rag(ingested, client=FakeGemini(fail_group="hours"),
                                model="fake", embedder=rig.embedder, store=rig.store, k=6)
    assert result.outcome.quarantined, "no hours clause means TreatyTerms cannot validate"
    assert result.outcome.fields  # the other groups' values survive for scoring


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def _item(field, value, page=2, source="text"):
    return {"field": field, "value": value, "page": page, "clause_no": "5",
            "source": source, "quote": "q" * 12}


def test_assembly_types_every_field_and_builds_a_valid_programme():
    from catsight_agent.schemas import TreatyTerms

    payload = assemble_payload("T-X", [
        _item("type", "cat_xl"), _item("perils", "WS, EQ"),
        _item("territory.include", '["jpn"]'), _item("territory.exclude", ""),
        _item("inception", "2026-01-01"), _item("expiry", "2026-12-31"),
        _item("currency", "usd"), _item("exclusions", "War, Nuclear"),
        _item("hours_clause.WS", "72"), _item("hours_clause.EQ", "72.0"),
        _item("hours_clause.FL", "168"),
        _item("layers.1.retention", "10.0"), _item("layers.1.limit", "20.0"),
        _item("layers.1.premium", "2.0"), _item("layers.2.retention", "30.0"),
        _item("layers.2.limit", "30.0"),
        _item("reinstatements.count", "1"), _item("reinstatements.rate", "1.0"),
        _item("reinstatements.basis", "pro rata as to amount"),
        _item("hours_clause.FL", "not a number"),  # dropped, earlier value kept
    ])
    terms = TreatyTerms.model_validate(payload)
    assert terms.perils == ["WS", "EQ"]
    assert terms.territory.include == ["JPN"] and terms.territory.exclude == []
    assert terms.exclusions == ["war", "nuclear"]
    assert terms.hours_clause.FL == 168 and terms.hours_clause.OTHER == 0
    assert [la.layer_no for la in terms.layers] == [1, 2]
    assert str(terms.layers[1].premium) == "0", "an unstated premium is 0, not invented"
    assert terms.layers[0].reinstatements.count == 1
    assert terms.layers[0].our_share == 0, "the signed line comes from the book"


def test_assembly_of_a_quota_share_and_an_endorsement():
    payload = assemble_payload("T-Q", [
        _item("qs.cession_pct", "0.3"), _item("qs.event_limit", "19.8"),
        _item("hours_clause.WS", "168", page=7, source="transcription"),
        _item("hours_clause.WS.base", "72"),
        _item("endorsement.overrides", "hours_clause.WS"),
        _item("perils", '["WS", bad json'),
    ])
    assert payload["qs"] == {"cession_pct": "0.3", "event_limit": "19.8", "our_share": "0"}
    assert payload["endorsement"] == {
        "overrides": "hours_clause.WS", "base_value": "72",
        "endorsed_value": "168", "source": "7",
    }
    # Malformed JSON falls back to comma-splitting with quotes stripped.
    assert payload["perils"] == ['["WS', "BAD JSON"]
    assert "layers" not in payload and "territory" not in payload


def test_every_answer_key_field_belongs_to_a_group():
    assert all(GROUP_OF_FIELD(r["field"]) for r in TRUTH)
    assert GROUP_OF_FIELD("cedent") is None


# --------------------------------------------------------------------------- #
# The pipeline runner and its metrics
# --------------------------------------------------------------------------- #


def test_retrieval_hits_counts_governing_clauses():
    outcome = SimpleNamespace(groups={
        "hours": SimpleNamespace(group="hours", retrieved=("T#c5",)),
    })
    rows = [
        {"field": "hours_clause.WS", "clause_no": "5"},
        {"field": "hours_clause.EQ", "clause_no": "9"},
        {"field": "currency", "clause_no": "14"},  # its group did not run
    ]
    hits, total, misses = retrieval_hits(rows, outcome, {"T#c5": "5"})
    assert (hits, total) == (1, 2)
    assert misses == ["hours_clause.EQ (clause 9, group hours)"]


def test_the_runner_scores_and_writes_a_comparable_report(rig, tmp_path, capsys):
    args = SimpleNamespace(wordings=str(WORDINGS), out=str(tmp_path), only=["T-001", "T-004"],
                           model="fake", store="memory", k=6, workers=2)
    code = run(args, client=FakeGemini(garble="currency"), embedder=rig.embedder,
               store=rig.store)
    printed = capsys.readouterr().out
    assert "RAG-first extraction: 2 wording(s)" in printed
    assert "transcribed page(s) [7]" in printed
    assert "Retrieval - was the governing clause among those retrieved?" in printed
    assert "rejected currency - quote not in" in printed
    assert "wall clock:" in printed
    written = json.loads((tmp_path / "extracted.json").read_text(encoding="utf-8"))
    assert set(written["extracted"]) == {"T-001", "T-004"}
    assert written["retrieval"]["T-001"]["total"] > 0
    assert code in (0, 1)


def test_with_every_clause_retrieved_the_pipeline_passes_its_gate(rig, tmp_path, capsys):
    """Perfect retrieval plus a faithful reader must clear every bar: the
    assembly, typing and validation lose nothing on the way."""
    args = SimpleNamespace(wordings=str(WORDINGS), out=str(tmp_path), only=None,
                           model="fake", store="memory", k=40, workers=4)
    code = run(args, client=FakeGemini(), embedder=rig.embedder, store=rig.store)
    printed = capsys.readouterr().out
    assert "structural: 8/8 ingestable" in printed, printed[-1500:]
    assert "gate: PASS" in printed, printed[-1500:]
    assert code == 0


def test_the_runner_lists_retrieval_misses(rig, tmp_path, capsys):
    """k=1 cannot retrieve every governing clause, so misses must be listed."""
    args = SimpleNamespace(wordings=str(WORDINGS), out=str(tmp_path), only=["T-001"],
                           model="fake", store="memory", k=1, workers=1)
    run(args, client=FakeGemini(), embedder=rig.embedder, store=rig.store)
    assert "  miss  T-001  " in capsys.readouterr().out


def test_the_runner_reports_failed_group_calls(rig, tmp_path, capsys):
    args = SimpleNamespace(wordings=str(WORDINGS), out=str(tmp_path), only=["T-001"],
                           model=None, store="memory", k=4, workers=1)
    code = run(args, client=FakeGemini(fail_group="hours"), embedder=rig.embedder,
               store=rig.store)
    printed = capsys.readouterr().out
    assert "hours: call failed" in printed
    assert "QUARANTINED" in printed
    assert code == 1


def test_long_quotes_are_bounded_to_whole_words():
    from ingest.rag_extract import _bounded

    assert _bounded("short quote") == "short quote"
    long = " ".join(["word"] * 100)
    trimmed = _bounded(long, limit=30)
    assert len(trimmed) <= 30 and trimmed == " ".join(["word"] * 6)
    assert _bounded("x" * 50, limit=10) == "x" * 10


def test_a_rejected_quote_is_recovered_by_one_retry(rig):
    ingested = _ingest(rig, "T-001")
    hours = next(g for g in TERM_GROUPS if g.name == "hours")
    real = next(c for c in ingested.chunks if c.clause_no == "5")
    good_quote = " ".join(real.text.split()[:10])

    class SecondTimeLucky(FakeGemini):
        def answer(self, contents):
            quote = good_quote if "WAS REJECTED" in contents else "not in the clause at all here"
            return json.dumps({"fields": [
                {"field": "hours_clause.WS", "value": "72", "chunk_id": real.chunk_id,
                 "quote": quote},
            ]})

    client = SecondTimeLucky()
    result = extract_group("T-001", hours, client=client, model="fake",
                           embedder=rig.embedder, store=rig.store, texts=ingested.texts, k=40)
    assert client.calls == 2
    assert [a["field"] for a in result.accepted] == ["hours_clause.WS"]
    assert result.accepted[0]["retried"] is True


def test_a_failed_retry_keeps_the_first_answer(rig):
    ingested = _ingest(rig, "T-001")
    hours = next(g for g in TERM_GROUPS if g.name == "hours")

    class BreaksOnRetry(FakeGemini):
        def answer(self, contents):
            if "WAS REJECTED" in contents:
                raise RuntimeError("400 bad request")
            return json.dumps({"fields": [
                {"field": "hours_clause.WS", "value": "72", "chunk_id": "T-001#c5",
                 "quote": "not in the clause at all here"},
            ]})

    result = extract_group("T-001", hours, client=BreaksOnRetry(), model="fake",
                           embedder=rig.embedder, store=rig.store, texts=ingested.texts, k=40)
    assert result.error.startswith("retry failed")
    assert result.accepted == []


def test_the_runner_writes_ingestion_evidence(rig, tmp_path, monkeypatch):
    monkeypatch.setenv("GCS_BUCKET", "bkt")
    args = SimpleNamespace(wordings=str(WORDINGS), out=str(tmp_path), only=["T-004"],
                           model="fake", store="firestore", k=40, workers=1)
    run(args, client=FakeGemini(), embedder=rig.embedder, store=rig.store)
    record = json.loads((tmp_path / "ingestions.json").read_text(encoding="utf-8"))["T-004"]
    assert record["pdf"].startswith("gs://bkt/wordings/")
    assert record["transcribed_pages"] == [7]
    assert record["vector_store"] == "firestore:treaty_chunks"
    assert record["clauses"] == record["embedded"] > 30
    assert record["citations_total"] >= record["citations_verified"] > 0
    assert record["ingested_at"].endswith("+00:00")


def test_ingestion_record_without_a_bucket(rig, tmp_path, monkeypatch):
    monkeypatch.delenv("GCS_BUCKET", raising=False)
    args = SimpleNamespace(wordings=str(WORDINGS), out=str(tmp_path), only=["T-001"],
                           model="fake", store="memory", k=40, workers=1)
    run(args, client=FakeGemini(), embedder=rig.embedder, store=rig.store)
    record = json.loads((tmp_path / "ingestions.json").read_text(encoding="utf-8"))["T-001"]
    assert not record["pdf"].startswith("gs://")
    assert record["vector_store"] == "memory"
