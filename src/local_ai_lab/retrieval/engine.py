from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from local_ai_lab.domain.common import sha256_json
from local_ai_lab.knowledge_index.projection import KnowledgeIndex
from local_ai_lab.knowledge_index.snapshot import SnapshotVerifier


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    chunk_id: str
    note_id: str
    relative_path: str
    section: str
    content: str
    score: float
    rank: int
    strategy: str
    evidence_reference: str


class EmbeddingProvider(Protocol):
    provider_id: str
    model_fingerprint: str

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class LexicalRetriever:
    strategy_id = "R1.lexical-fts5.v1"

    def __init__(self, index: KnowledgeIndex) -> None:
        self.index = index

    def retrieve(self, query: str, *, limit: int = 10) -> list[RetrievalCandidate]:
        return [
            RetrievalCandidate(
                hit.chunk_id, hit.note_id, hit.relative_path, hit.section, hit.content,
                -hit.score, rank, self.strategy_id, hit.evidence_reference,
            )
            for rank, hit in enumerate(self.index.search(query, limit=limit), start=1)
        ]


class SemanticRetriever:
    strategy_id = "R2.semantic-cosine.v1"

    def __init__(self, snapshot: Path, provider: EmbeddingProvider) -> None:
        verified = SnapshotVerifier().verify(snapshot)
        self.snapshot_hash = verified["manifest"]["global_hash"]
        self.provider = provider
        self._chunks = [
            json.loads(line)
            for line in (snapshot / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        vectors = provider.embed([item["content"] for item in self._chunks])
        if len(vectors) != len(self._chunks):
            raise ValueError("embedding provider returned the wrong vector count")
        self._vectors = [self._normalize(vector) for vector in vectors]
        dimensions = {len(vector) for vector in self._vectors}
        if not dimensions or len(dimensions) != 1 or next(iter(dimensions)) == 0:
            raise ValueError("embedding vectors must have one non-zero dimension")
        self.fingerprint = sha256_json(
            {
                "strategy": self.strategy_id,
                "snapshot_hash": self.snapshot_hash,
                "provider_id": provider.provider_id,
                "model_fingerprint": provider.model_fingerprint,
                "dimension": next(iter(dimensions)),
                "chunk_ids": [item["chunk_id"] for item in self._chunks],
            }
        )

    def retrieve(self, query: str, *, limit: int = 10) -> list[RetrievalCandidate]:
        if not query.strip() or limit < 1 or limit > 100:
            raise ValueError("query must be non-empty and limit must be between 1 and 100")
        query_vectors = self.provider.embed([query])
        if len(query_vectors) != 1:
            raise ValueError("embedding provider must return exactly one query vector")
        query_vector = self._normalize(query_vectors[0])
        if self._vectors and len(query_vector) != len(self._vectors[0]):
            raise ValueError("query and corpus embedding dimensions differ")
        ranked = sorted(
            zip(self._chunks, self._vectors),
            key=lambda pair: (-sum(a * b for a, b in zip(query_vector, pair[1])), pair[0]["chunk_id"]),
        )[:limit]
        return [
            RetrievalCandidate(
                item["chunk_id"], item["note_id"], item["relative_path"], item["section"],
                item["content"], sum(a * b for a, b in zip(query_vector, vector)), rank,
                self.strategy_id,
                f"snapshot:sha256:{self.snapshot_hash}#chunk:{item['chunk_id']}",
            )
            for rank, (item, vector) in enumerate(ranked, start=1)
        ]

    @staticmethod
    def _normalize(vector: Sequence[float]) -> tuple[float, ...]:
        values = tuple(float(value) for value in vector)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("embedding vectors must contain only finite values")
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            return tuple(0.0 for _ in values)
        return tuple(value / norm for value in values)


class HybridRetriever:
    strategy_id = "R3.hybrid-rrf.v1"

    def __init__(self, lexical: LexicalRetriever, semantic: SemanticRetriever, *, rrf_k: int = 60) -> None:
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        self.lexical = lexical
        self.semantic = semantic
        self.rrf_k = rrf_k

    def retrieve(self, query: str, *, limit: int = 10) -> list[RetrievalCandidate]:
        fetch = min(100, max(limit * 3, limit))
        rankings = (self.lexical.retrieve(query, limit=fetch), self.semantic.retrieve(query, limit=fetch))
        scores: dict[str, float] = {}
        candidates: dict[str, RetrievalCandidate] = {}
        for ranking in rankings:
            for item in ranking:
                scores[item.chunk_id] = scores.get(item.chunk_id, 0.0) + 1.0 / (self.rrf_k + item.rank)
                candidates[item.chunk_id] = item
        ordered = sorted(candidates.values(), key=lambda item: (-scores[item.chunk_id], item.chunk_id))[:limit]
        return [
            RetrievalCandidate(
                item.chunk_id, item.note_id, item.relative_path, item.section, item.content,
                scores[item.chunk_id], rank, self.strategy_id, item.evidence_reference,
            )
            for rank, item in enumerate(ordered, start=1)
        ]
