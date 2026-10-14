"""Clause retrieval — FR-INGEST-2 and the `search_treaty_clauses` tool.

Two swappable seams, so the shape of the system is settled before GCP access
is and only the backends change afterwards:

  **Embedder** - `DeterministicEmbedder` for tests and local development,
  `GeminiEmbedder` for production. The production one is written but not
  exercised here; see the warning below.

  **VectorStore** - `InMemoryVectorStore` (pure-Python cosine) and
  `FirestoreVectorStore`. Both honour C-11's constraint that **vector
  pre-filters are equality only**, so the same query works against either and
  nothing has to change when the index lands.

## What the local path does and does not prove

It proves the plumbing: chunking, filtering, ranking, the tool's contract,
and the QA harness that scores it. It does **not** prove retrieval quality.
`DeterministicEmbedder` is a hashing bag-of-words with no semantics, so a
recall figure measured against it is a measure of the harness, not of the
system. Numbers for the deck come from `GeminiEmbedder` against a real
Firestore index, and from nothing else.

`clause_type` is a filter of convenience, never a gate. W8 hides its hours
clause inside a clause titled "Definitions", which classifies as OTHER, so a
hard filter on `clause_type == "HOURS"` would miss exactly the case DR-2
planted to catch a lazy extractor.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Protocol, Sequence, runtime_checkable

from ingest.chunking import Chunk

__all__ = [
    "EMBED_DIM",
    "Embedder",
    "DeterministicEmbedder",
    "GeminiEmbedder",
    "SearchHit",
    "VectorStore",
    "InMemoryVectorStore",
    "FirestoreVectorStore",
    "l2_normalise",
    "cosine",
]

import threading

#: Serialises one-time setup of embedders shared across threads.
_SETUP_LOCK = threading.Lock()

#: C-2. 768 dimensions, matching `gemini-embedding-001`'s configured output,
#: so the local and production vectors are at least the same shape.
EMBED_DIM = 768

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def l2_normalise(vector: Sequence[float]) -> list[float]:
    """Unit-length a vector. FR-INGEST-2 requires stored embeddings to be
    L2-normalised, which makes cosine similarity a plain dot product."""
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return [0.0] * len(vector)
    return [value / norm for value in vector]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity. Assumes nothing about normalisation."""
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# --------------------------------------------------------------------------- #
# Embedders
# --------------------------------------------------------------------------- #


@runtime_checkable
class Embedder(Protocol):
    """Anything that turns text into a fixed-width vector."""

    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


@dataclass
class DeterministicEmbedder:
    """A hashing bag-of-words embedder. **Not semantic.**

    Exists so retrieval, the tool contract and the QA harness can be built and
    tested without a model call or a network. Same text always gives the same
    vector, so tests are stable and cheap.

    It will match on shared vocabulary and nothing else: "hours clause" and
    "loss occurrence" are unrelated to it, though they are the same concept.
    **Never quote a retrieval metric measured against this.** It is scaffolding.
    """

    dimensions: int = EMBED_DIM
    #: Sub-linear term weighting, so a word repeated twenty times does not
    #: dominate the vector.
    sublinear_tf: bool = True

    def _vector(self, text: str) -> list[float]:
        counts: dict[int, float] = {}
        for token in _tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, "big") % self.dimensions
            counts[bucket] = counts.get(bucket, 0.0) + 1.0
        vector = [0.0] * self.dimensions
        for bucket, count in counts.items():
            vector[bucket] = 1.0 + math.log(count) if self.sublinear_tf else count
        return l2_normalise(vector)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


@dataclass
class GeminiEmbedder:
    """`gemini-embedding-001` at 768 dimensions (C-2, FR-INGEST-2).

    **Not exercised by the test suite** - it needs a live project. The call
    shape follows RESEARCH_FINDINGS: one input per request with batching done
    by the caller's loop, `output_dimensionality=768`, and `task_type`
    distinguishing a stored document from a query, which materially affects
    retrieval quality and is easy to forget.

    Vectors are L2-normalised here rather than relying on the API to do it,
    so the store's assumptions hold whatever the endpoint returns.
    """

    project: str
    location: str = "global"
    model: str = "gemini-embedding-001"
    dimensions: int = EMBED_DIM
    #: Concurrent requests across ALL callers of this instance. The per-minute
    #: embed quota on a new project is low; 32 parallel requests exhausted it.
    max_concurrency: int = 4
    #: Optional on-disk cache (JSON lines keyed by task type + text hash), so
    #: a re-run never re-embeds an unchanged clause.
    cache_path: str | None = None
    #: Read-only vectors shipped with the app (the standard queries), loaded
    #: into the cache at start so a fresh instance makes no embed calls for them.
    seed_path: str | None = None
    #: Steady pace under the project's per-minute embed quota (EMBED_RPM).
    #: Observed ~14/min sustainable on this project; 0 disables pacing.
    requests_per_minute: float = 12.0
    _next_slot: float | None = None
    _client: Any = None
    _gate: Any = None
    _cache: Any = None
    _lock: Any = None

    def _ensure_client(self) -> Any:  # pragma: no cover - needs a live project
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                enterprise=True, project=self.project, location=self.location
            )
        return self._client

    def _pace(self) -> None:  # pragma: no cover - needs a live project
        """Space requests to stay under `requests_per_minute` across threads."""
        import time

        if not self.requests_per_minute:
            return
        with self._lock:
            interval = 60.0 / self.requests_per_minute
            now = time.monotonic()
            wait = (self._next_slot or now) - now
            self._next_slot = max(now, self._next_slot or now) + interval
        if wait > 0:
            time.sleep(wait)

    def _setup(self) -> None:  # pragma: no cover - needs a live project
        import threading

        # Guarded by a module lock, and `_lock` is assigned LAST: threads test
        # `_lock` to decide whether setup is done, so it must not become
        # visible before the cache and gate exist.
        with _SETUP_LOCK:
            if self._lock is None:
                self._gate = threading.BoundedSemaphore(self.max_concurrency)
                self._cache = _EmbeddingCache(self.cache_path, seed=self.seed_path)
                self._lock = threading.Lock()

    def _embed(self, text: str, task_type: str) -> list[float]:  # pragma: no cover
        import random
        import time

        from google.genai import types

        self._setup()
        key = f"{self.model}|{self.dimensions}|{task_type}|{text}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        client = self._ensure_client()
        # For batch document ingestion, retry up to 20 times with backoff.
        # For interactive user queries (RETRIEVAL_QUERY), fail fast after 2 attempts
        # so the user never experiences multi-minute stalls on a 429 quota spike.
        attempts = 2 if task_type == "RETRIEVAL_QUERY" else 20
        for attempt in range(attempts):
            try:
                with self._gate:
                    if task_type == "RETRIEVAL_DOCUMENT":
                        self._pace()
                    response = client.models.embed_content(
                        model=self.model,
                        contents=text,
                        config=types.EmbedContentConfig(
                            output_dimensionality=self.dimensions, task_type=task_type
                        ),
                    )
                break
            except Exception as exc:  # noqa: BLE001 - quota is retried, the rest raised
                if "429" not in str(exc) and "RESOURCE_EXHAUSTED" not in str(exc) or attempt == attempts - 1:
                    raise
                # Per-minute quota: wait briefly for interactive queries, longer for batch.
                sleep_s = 1.0 if task_type == "RETRIEVAL_QUERY" else min(60.0, 5.0 * 2**attempt)
                time.sleep(sleep_s + random.uniform(0, 0.5 if task_type == "RETRIEVAL_QUERY" else 2.0))
        vector = l2_normalise(response.embeddings[0].values)
        with self._lock:
            self._cache.put(key, vector)
        return vector

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:  # pragma: no cover
        # One input per request (RESEARCH_FINDINGS), so requests run
        # concurrently - bounded by `max_concurrency`; map preserves order.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
            return list(pool.map(lambda t: self._embed(t, "RETRIEVAL_DOCUMENT"), texts))

    def embed_query(self, text: str) -> list[float]:  # pragma: no cover
        return self._embed(text, "RETRIEVAL_QUERY")


class _EmbeddingCache:
    """Append-only JSON-lines cache of embeddings, keyed by a hash of the
    model, dimensions, task type and text. In memory only when no path.

    `seed` is a read-only file of vectors shipped with the app - the standard
    retrieval queries - loaded first and never written to. Without it a fresh
    Cloud Run instance re-embeds every query under the paced embed quota, and
    its first analysis takes minutes instead of seconds."""

    def __init__(self, path: str | None, seed: str | None = None) -> None:
        from pathlib import Path

        self._path = Path(path) if path else None
        self._rows: dict[str, list[float]] = {}
        for source in (Path(seed) if seed else None, self._path):
            if source and source.exists():
                self._load(source)

    def _load(self, source: Any) -> None:
        import json

        for line in source.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                self._rows[row["k"]] = row["v"]

    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def get(self, key: str) -> list[float] | None:
        return self._rows.get(self._hash(key))

    def put(self, key: str, vector: list[float]) -> None:
        import json

        digest = self._hash(key)
        self._rows[digest] = vector
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"k": digest, "v": vector}) + "\n")

    def __len__(self) -> int:
        return len(self._rows)


# --------------------------------------------------------------------------- #
# Stores
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    score: float

    def citation_fields(self) -> dict[str, Any]:
        """The fields a citation needs, so a caller cannot assemble one from
        the wrong chunk's metadata."""
        return {
            "treaty_id": self.chunk.treaty_id,
            "page": self.chunk.page,
            "clause_no": self.chunk.clause_no or "n/a",
            "source": self.chunk.source,
        }


@runtime_checkable
class VectorStore(Protocol):
    def add(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> int: ...

    def search(
        self,
        query_vector: Sequence[float],
        *,
        treaty_id: str | None = None,
        limit: int = 5,
    ) -> list[SearchHit]: ...


class InMemoryVectorStore:
    """Brute-force cosine search over the stored chunks.

    Exact rather than approximate, and at 8 wordings x ~31 chunks the whole
    corpus is about 250 vectors, so brute force is instant and needs no index
    to be built. That also makes it a useful reference: a recall difference
    between this and Firestore is the index's doing, not the embedder's.

    Pre-filtering is **equality only**, matching C-11, so a query written
    against this store behaves the same against Firestore.
    """

    def __init__(self) -> None:
        self._rows: list[tuple[Chunk, list[float]]] = []

    def __len__(self) -> int:
        return len(self._rows)

    def add(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> int:
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        seen = {chunk.chunk_id for chunk, _ in self._rows}
        added = 0
        for chunk, vector in zip(chunks, vectors):
            if chunk.chunk_id in seen:
                continue  # idempotent: re-ingesting a wording must not duplicate
            self._rows.append((chunk, list(vector)))
            seen.add(chunk.chunk_id)
            added += 1
        return added

    def search(
        self,
        query_vector: Sequence[float],
        *,
        treaty_id: str | None = None,
        limit: int = 5,
    ) -> list[SearchHit]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        candidates = [
            (chunk, vector)
            for chunk, vector in self._rows
            if treaty_id is None or chunk.treaty_id == treaty_id
        ]
        scored = [
            SearchHit(chunk=chunk, score=cosine(query_vector, vector))
            for chunk, vector in candidates
        ]
        # Tie-break on chunk_id so equal scores order deterministically -
        # otherwise retrieval output wobbles between runs and the ADK eval
        # trajectory check becomes flaky.
        scored.sort(key=lambda hit: (-hit.score, hit.chunk.chunk_id))
        return scored[:limit]

    def chunks_for(self, treaty_id: str) -> tuple[Chunk, ...]:
        """Every stored clause of one treaty - also makes this store a
        `verify.ChunkLookup`, so citations are checked against what was
        actually retrieved from."""
        return tuple(
            sorted((c for c, _ in self._rows if c.treaty_id == treaty_id),
                   key=lambda c: c.chunk_id)
        )


@dataclass
class FirestoreVectorStore:
    """Firestore vector search over `treaty_chunks` (C-11).

    **Not exercised by the test suite** - it needs a live database and an
    index in state READY. Two constraints are baked in rather than discovered
    later: the index is created with **gcloud, not the Firebase CLI**, and
    pre-filters are **equality only**, which is why `treaty_id` is the only
    filter the interface offers.
    """

    client: Any
    collection: str = "treaty_chunks"
    embed_dim: int = EMBED_DIM

    def add(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> int:  # pragma: no cover
        from google.cloud.firestore_v1.vector import Vector

        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        collection = self.client.collection(self.collection)
        for chunk, vector in zip(chunks, vectors):
            collection.document(chunk.chunk_id).set(
                {
                    "treaty_id": chunk.treaty_id,
                    "page": chunk.page,
                    "clause_no": chunk.clause_no,
                    "clause_title": chunk.clause_title,
                    "clause_type": chunk.clause_type,
                    "text": chunk.text,
                    "source": chunk.source,
                    "pages_spanned": list(chunk.pages_spanned),
                    "embedding": Vector(list(vector)),
                }
            )
        return len(chunks)

    def search(  # pragma: no cover - needs a live index
        self,
        query_vector: Sequence[float],
        *,
        treaty_id: str | None = None,
        limit: int = 5,
    ) -> list[SearchHit]:
        from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
        from google.cloud.firestore_v1.vector import Vector

        query: Any = self.client.collection(self.collection)
        if treaty_id is not None:
            # Equality only (C-11); keyword filter, as the client requires.
            query = query.where(filter=_treaty_filter(treaty_id))
        results = query.find_nearest(
            vector_field="embedding",
            query_vector=Vector(list(query_vector)),
            distance_measure=DistanceMeasure.COSINE,
            limit=limit,
            # Without this the distance is not returned and every hit scores 1.0.
            distance_result_field="vector_distance",
        ).get()

        return [
            SearchHit(
                chunk=_chunk_from_document(document.id, document.to_dict()),
                score=1.0 - float(document.to_dict().get("vector_distance", 0.0)),
            )
            for document in results
        ]

    def chunks_for(self, treaty_id: str) -> tuple[Chunk, ...]:
        """Every stored clause of one treaty (a `verify.ChunkLookup`)."""
        documents = (
            self.client.collection(self.collection)
            .where(filter=_treaty_filter(treaty_id))
            .stream()
        )
        return tuple(sorted(
            (_chunk_from_document(d.id, d.to_dict()) for d in documents),
            key=lambda c: c.chunk_id,
        ))


def _treaty_filter(treaty_id: str) -> Any:
    """`treaty_id == x` as a FieldFilter. Positional `where(a, op, b)` is
    deprecated in the Firestore client and logs a warning on every query."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    return FieldFilter("treaty_id", "==", treaty_id)


def _chunk_from_document(chunk_id: str, data: dict) -> Chunk:
    """A stored Firestore clause document back into a `Chunk`."""
    return Chunk(
        treaty_id=data["treaty_id"],
        chunk_id=chunk_id,
        page=data["page"],
        clause_no=data.get("clause_no"),
        clause_title=data.get("clause_title"),
        clause_type=data.get("clause_type", "OTHER"),
        text=data["text"],
        source=data.get("source", "text"),
        pages_spanned=tuple(data.get("pages_spanned") or ()),
    )


# --------------------------------------------------------------------------- #
# The agent-facing tool
# --------------------------------------------------------------------------- #

#: Canonical queries FR-WORD runs for each matched treaty. Phrased as the
#: clause would read rather than as a keyword, because the production embedder
#: is semantic even though the local one is not.
STANDARD_QUERIES: dict[str, str] = {
    "HOURS": (
        "loss occurrence definition, the number of consecutive hours within which "
        "individual losses are treated as one event"
    ),
    "EXCLUSION": "excluded perils, storm surge, flood written as such, earthquake exclusion",
    "TERRITORY": "territorial scope, which territories and regions are covered or carved out",
    "REINSTATEMENT": "reinstatement of the limit, number of reinstatements and the premium basis",
    "PERIOD": "period of the agreement, inception and expiry, extended expiration",
    "LIMIT": "limit and retention per loss occurrence for each layer",
}


def search_treaty_clauses(
    query: str,
    *,
    store: VectorStore,
    embedder: Embedder,
    treaty_id: str | None = None,
    limit: int = 5,
    clause_type: str | None = None,
) -> list[SearchHit]:
    """Retrieve clauses relevant to a query (the AG-3 tool).

    `clause_type` is applied **after** ranking, as a preference rather than a
    pre-filter: it reorders matching types ahead of others but never removes a
    hit. Dropping non-matching types would lose W8's hours clause, which lives
    in a chunk titled "Definitions".

    Idempotent and side-effect free, as ADK requires of tools, since a failed
    workflow node re-runs on resume.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    hits = store.search(embedder.embed_query(query), treaty_id=treaty_id, limit=limit * 3)
    if clause_type:
        hits.sort(key=lambda hit: (hit.chunk.clause_type != clause_type, -hit.score))
    return hits[:limit]


def index_chunks(
    chunks: Iterable[Chunk], *, store: VectorStore, embedder: Embedder
) -> int:
    """Embed and store chunks. Returns the number newly added."""
    batch = list(chunks)
    if not batch:
        return 0
    vectors = embedder.embed_documents([chunk.text for chunk in batch])
    return store.add(batch, vectors)
