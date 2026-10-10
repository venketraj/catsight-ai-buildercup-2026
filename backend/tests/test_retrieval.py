"""FR-INGEST-2 / FR-WORD — embeddings, the vector store and the retrieval tool.

What these tests establish is the **plumbing**: dimensions, normalisation,
equality-only pre-filtering, deterministic ranking, idempotent indexing, and
the tool's contract.

What they deliberately do not establish is **retrieval quality**.
`DeterministicEmbedder` is a hashing bag-of-words with no semantics, so a
recall number measured here is a measure of the harness. Quality numbers come
from `GeminiEmbedder` against a live Firestore index and from nowhere else.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from catsight_agent.tools.retrieval import (
    EMBED_DIM,
    STANDARD_QUERIES,
    DeterministicEmbedder,
    Embedder,
    FirestoreVectorStore,
    GeminiEmbedder,
    InMemoryVectorStore,
    SearchHit,
    VectorStore,
    cosine,
    index_chunks,
    l2_normalise,
    search_treaty_clauses,
)
from ingest.build_wordings import build_all
from ingest.chunking import Chunk, chunk_pdf


@pytest.fixture(scope="module")
def wordings(tmp_path_factory) -> Path:
    return build_all(out_dir=tmp_path_factory.mktemp("wordings"))["out_dir"]


@pytest.fixture(scope="module")
def embedder() -> DeterministicEmbedder:
    return DeterministicEmbedder()


@pytest.fixture(scope="module")
def corpus(wordings) -> tuple[Chunk, ...]:
    chunks: list[Chunk] = []
    for index, name in enumerate(("w1", "w2", "w3", "w8"), start=1):
        treaty_id = f"T-00{index if name != 'w8' else 8}"
        chunks.extend(chunk_pdf(treaty_id, wordings / f"{name}.pdf"))
    return tuple(chunks)


@pytest.fixture(scope="module")
def store(corpus, embedder) -> InMemoryVectorStore:
    built = InMemoryVectorStore()
    index_chunks(corpus, store=built, embedder=embedder)
    return built


# --------------------------------------------------------------------------- #
# Vector maths
# --------------------------------------------------------------------------- #


def test_normalisation_produces_unit_vectors():
    vector = l2_normalise([3.0, 4.0])
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0)
    assert vector == [0.6, 0.8]


def test_normalising_a_zero_vector_does_not_divide_by_zero():
    """An empty chunk would otherwise crash ingestion."""
    assert l2_normalise([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]


def test_cosine_of_identical_and_orthogonal_vectors():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_of_a_zero_vector_is_zero_not_an_error():
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_rejects_a_dimension_mismatch():
    """A silent mismatch here would mean comparing a 768-dim query against a
    stale 1536-dim index and getting plausible nonsense."""
    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine([1.0, 0.0], [1.0, 0.0, 0.0])


# --------------------------------------------------------------------------- #
# Embedders
# --------------------------------------------------------------------------- #


def test_the_local_embedder_matches_the_production_dimensionality(embedder):
    """768, per C-2, so local and production vectors are at least the same
    shape and an index built on one is not silently incompatible."""
    assert embedder.dimensions == EMBED_DIM == 768
    assert len(embedder.embed_query("hours clause")) == 768


def test_the_local_embedder_is_deterministic(embedder):
    assert embedder.embed_query("loss occurrence") == embedder.embed_query("loss occurrence")


def test_the_local_embedder_returns_normalised_vectors(embedder):
    vector = embedder.embed_query("reinstatement premium pro rata as to amount")
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, abs_tol=1e-9)


def test_the_local_embedder_scores_shared_vocabulary_above_unrelated_text(embedder):
    shared = cosine(
        embedder.embed_query("territorial scope of this agreement"),
        embedder.embed_query("the territorial scope is Japan"),
    )
    unrelated = cosine(
        embedder.embed_query("territorial scope of this agreement"),
        embedder.embed_query("reinstatement premium calculation"),
    )
    assert shared > unrelated


def test_the_local_embedder_has_no_semantics_which_is_why_it_is_scaffolding(embedder):
    """Stated as a test so nobody mistakes a local recall number for a real
    one. "hours clause" and "loss occurrence" are the same concept and this
    embedder cannot tell."""
    synonymous = cosine(
        embedder.embed_query("hours clause"), embedder.embed_query("loss occurrence")
    )
    assert synonymous == pytest.approx(0.0)


def test_both_embedders_satisfy_the_protocol():
    assert isinstance(DeterministicEmbedder(), Embedder)
    assert isinstance(GeminiEmbedder(project="p"), Embedder)


def test_the_gemini_embedder_is_configured_for_the_specified_model():
    """C-2: gemini-embedding-001 at 768 dims on the global endpoint."""
    # A dummy project, deliberately. The real ID belongs only in the
    # environment, and a test asserting on model constants has no business
    # knowing it.
    gemini = GeminiEmbedder(project="p")
    assert gemini.model == "gemini-embedding-001"
    assert gemini.dimensions == 768
    assert gemini.location == "global"


def test_the_gemini_embedder_is_not_used_by_the_suite():
    """It needs a live project. If a test ever constructs one and calls it,
    the suite has started depending on network access."""
    gemini = GeminiEmbedder(project="p")
    assert gemini._client is None


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #


def test_indexing_stores_every_chunk(corpus, store):
    assert len(store) == len(corpus)


def test_indexing_is_idempotent(corpus, embedder):
    """Re-ingesting a wording must not duplicate it - FR-INGEST tools have to
    be safe to re-run, because a failed workflow node resumes."""
    fresh = InMemoryVectorStore()
    first = index_chunks(corpus, store=fresh, embedder=embedder)
    second = index_chunks(corpus, store=fresh, embedder=embedder)
    assert first == len(corpus)
    assert second == 0
    assert len(fresh) == len(corpus)


def test_indexing_an_empty_batch_is_a_no_op(embedder):
    fresh = InMemoryVectorStore()
    assert index_chunks([], store=fresh, embedder=embedder) == 0


def test_adding_mismatched_chunks_and_vectors_fails(corpus):
    fresh = InMemoryVectorStore()
    with pytest.raises(ValueError, match="chunks but"):
        fresh.add(corpus[:3], [[0.0] * EMBED_DIM])


def test_the_treaty_filter_is_an_equality_prefilter(store, embedder):
    """C-11: Firestore vector pre-filters are equality only, so the interface
    offers nothing richer and a query behaves the same on either store."""
    hits = store.search(embedder.embed_query("loss occurrence"), treaty_id="T-002", limit=10)
    assert hits
    assert {hit.chunk.treaty_id for hit in hits} == {"T-002"}


def test_search_without_a_filter_spans_every_treaty(store, embedder):
    hits = store.search(embedder.embed_query("exclusions"), limit=50)
    assert len({hit.chunk.treaty_id for hit in hits}) > 1


def test_an_unknown_treaty_returns_nothing_rather_than_falling_back(store, embedder):
    assert store.search(embedder.embed_query("anything"), treaty_id="T-999") == []


def test_search_respects_the_limit(store, embedder):
    assert len(store.search(embedder.embed_query("premium"), limit=3)) == 3


def test_search_rejects_a_non_positive_limit(store, embedder):
    with pytest.raises(ValueError, match="limit must be"):
        store.search(embedder.embed_query("premium"), limit=0)


def test_results_are_ordered_by_score_then_deterministically(store, embedder):
    """Ties break on chunk_id. Without that, equal scores reorder between
    runs and the ADK eval trajectory check becomes flaky."""
    hits = store.search(embedder.embed_query("the"), limit=20)
    scores = [hit.score for hit in hits]
    assert scores == sorted(scores, reverse=True)
    for earlier, later in zip(hits, hits[1:]):
        if earlier.score == later.score:
            assert earlier.chunk.chunk_id < later.chunk.chunk_id


def test_both_stores_satisfy_the_protocol():
    assert isinstance(InMemoryVectorStore(), VectorStore)
    assert isinstance(FirestoreVectorStore(client=object()), VectorStore)


def test_the_firestore_store_defaults_to_the_specified_collection():
    store = FirestoreVectorStore(client=object())
    assert store.collection == "treaty_chunks"
    assert store.embed_dim == 768


# --------------------------------------------------------------------------- #
# The tool
# --------------------------------------------------------------------------- #


def test_the_tool_finds_the_hours_clause_in_a_plainly_drafted_wording(store, embedder):
    hits = search_treaty_clauses(
        STANDARD_QUERIES["HOURS"], store=store, embedder=embedder,
        treaty_id="T-001", limit=5,
    )
    assert any(hit.chunk.clause_no == "5" for hit in hits)


def test_the_tool_refuses_an_empty_query(store, embedder):
    with pytest.raises(ValueError, match="query must not be empty"):
        search_treaty_clauses("   ", store=store, embedder=embedder)


def test_clause_type_reorders_but_never_removes(store, embedder):
    """A preference, not a pre-filter. Filtering hard on clause_type would
    lose a clause whose heading does not advertise its subject."""
    unfiltered = search_treaty_clauses(
        "period and limit", store=store, embedder=embedder, treaty_id="T-001", limit=8
    )
    preferred = search_treaty_clauses(
        "period and limit", store=store, embedder=embedder,
        treaty_id="T-001", limit=8, clause_type="LIMIT",
    )
    assert len(preferred) == len(unfiltered)
    assert preferred[0].chunk.clause_type == "LIMIT"
    # Nothing was dropped: the same chunk set, reordered.
    assert {h.chunk.chunk_id for h in preferred} <= {
        h.chunk.chunk_id
        for h in search_treaty_clauses(
            "period and limit", store=store, embedder=embedder,
            treaty_id="T-001", limit=24,
        )
    }


def test_the_tool_is_scoped_to_one_treaty_at_a_time(store, embedder):
    """FR-WORD runs per matched treaty. Leaking another treaty's clause into
    a flag would cite the wrong document."""
    hits = search_treaty_clauses(
        STANDARD_QUERIES["TERRITORY"], store=store, embedder=embedder,
        treaty_id="T-003", limit=5,
    )
    assert {hit.chunk.treaty_id for hit in hits} == {"T-003"}


def test_every_standard_query_is_phrased_as_prose_not_keywords():
    """The production embedder is semantic, so a sentence retrieves better
    than a keyword - even though the local one cannot tell the difference."""
    assert set(STANDARD_QUERIES) >= {"HOURS", "EXCLUSION", "TERRITORY", "REINSTATEMENT"}
    for query in STANDARD_QUERIES.values():
        assert len(query.split()) >= 6


def test_a_hit_exposes_exactly_the_fields_a_citation_needs(store, embedder):
    """So a caller cannot assemble a citation from one chunk's quote and
    another's page."""
    hit = search_treaty_clauses(
        STANDARD_QUERIES["HOURS"], store=store, embedder=embedder,
        treaty_id="T-001", limit=1,
    )[0]
    fields = hit.citation_fields()
    assert set(fields) == {"treaty_id", "page", "clause_no", "source"}
    assert fields["treaty_id"] == hit.chunk.treaty_id
    assert fields["page"] == hit.chunk.page
    assert fields["source"] == "text"


def test_a_hit_with_no_clause_number_still_yields_a_usable_citation():
    chunk = Chunk(
        treaty_id="T-999", chunk_id="T-999#p1", page=1, clause_no=None,
        clause_title=None, clause_type="OTHER", text="unnumbered prose",
    )
    assert SearchHit(chunk=chunk, score=0.5).citation_fields()["clause_no"] == "n/a"


def test_embedding_cache_persists_and_reloads(tmp_path):
    from catsight_agent.tools.retrieval import _EmbeddingCache

    path = tmp_path / "cache" / "e.jsonl"
    cache = _EmbeddingCache(str(path))
    assert cache.get("m|768|DOC|hello") is None
    cache.put("m|768|DOC|hello", [0.6, 0.8])
    assert cache.get("m|768|DOC|hello") == [0.6, 0.8]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n")  # blank lines are tolerated
    reloaded = _EmbeddingCache(str(path))
    assert reloaded.get("m|768|DOC|hello") == [0.6, 0.8]
    assert len(reloaded) == 1
    memory_only = _EmbeddingCache(None)
    memory_only.put("k", [1.0])
    assert memory_only.get("k") == [1.0]


def test_firestore_vector_store_reads_a_treaty_s_clauses():
    from types import SimpleNamespace

    from catsight_agent.tools.retrieval import FirestoreVectorStore

    docs = {
        "T-1#c2": {"treaty_id": "T-1", "page": 2, "clause_no": "2", "text": "second clause",
                   "pages_spanned": [2, 3], "source": "text"},
        "T-1#c1": {"treaty_id": "T-1", "page": 1, "clause_no": "1", "text": "first clause"},
    }

    class Query:
        def __init__(self, wanted=None):
            self.wanted = wanted

        def where(self, *, filter):
            # The keyword FieldFilter form - positional where() is deprecated.
            assert (filter.field_path, filter.op_string) == ("treaty_id", "==")
            return Query(filter.value)

        def stream(self):
            return [SimpleNamespace(id=k, to_dict=lambda v=v: dict(v))
                    for k, v in docs.items() if v["treaty_id"] == self.wanted]

    client = SimpleNamespace(collection=lambda name: Query())
    chunks = FirestoreVectorStore(client).chunks_for("T-1")
    assert [c.chunk_id for c in chunks] == ["T-1#c1", "T-1#c2"]
    assert chunks[1].pages_spanned == (2, 3) and chunks[0].clause_type == "OTHER"
