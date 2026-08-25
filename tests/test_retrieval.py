from __future__ import annotations

import math
import shutil
import uuid
from pathlib import Path
from typing import Sequence

import pytest

from local_ai_lab.benchmark.controlled import ControlledCorpusSuite
from local_ai_lab.benchmark.retrieval_runner import RetrievalBenchmarkRunner
from local_ai_lab.knowledge_index.projection import KnowledgeIndex, KnowledgeIndexBuilder
from local_ai_lab.knowledge_index.snapshot import SnapshotBuilder
from local_ai_lab.knowledge_index.vault import ReadOnlyVaultAdapter
from local_ai_lab.retrieval.engine import HybridRetriever, LexicalRetriever, SemanticRetriever
from local_ai_lab.retrieval.metrics import evaluate_retrieval
from local_ai_lab.retrieval.graph import ContextAssembler, GraphRetriever
from local_ai_lab.retrieval.embeddings import CachedEmbeddingProvider


class ConceptEmbedding:
    provider_id = "test.concepts"
    model_fingerprint = "sha256:test-only"
    concepts = ("atlas", "local", "cloud", "latencia", "presupuesto", "cifrado", "jardín")

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return [
            [float(text.casefold().count(concept)) for concept in self.concepts]
            for text in texts
        ]


def _retrievers(tmp_path: Path):
    allowed = tmp_path / "controlled"
    vault = allowed / "v1"
    shutil.copytree(Path("benchmarks/controlled/v1"), vault)
    snapshot = SnapshotBuilder().build(
        ReadOnlyVaultAdapter(allowed_root=allowed, vault_root=vault),
        tmp_path / "snapshots",
        vault_id=str(uuid.uuid4()),
    )
    database = KnowledgeIndexBuilder().build(snapshot.path, tmp_path / "knowledge.sqlite3")
    lexical = LexicalRetriever(KnowledgeIndex(database))
    semantic = SemanticRetriever(snapshot.path, ConceptEmbedding())
    return snapshot, lexical, semantic, HybridRetriever(lexical, semantic)


def test_r1_accepts_natural_questions_and_returns_traceable_chunks(tmp_path: Path) -> None:
    snapshot, lexical, _, _ = _retrievers(tmp_path)
    candidates = lexical.retrieve("¿Cuál es el presupuesto vigente de Atlas?", limit=5)

    assert candidates
    assert any(item.relative_path.endswith("atlas-overview.md") for item in candidates)
    assert all(item.strategy == "R1.lexical-fts5.v1" for item in candidates)
    assert all(f"snapshot:sha256:{snapshot.global_hash}" in item.evidence_reference for item in candidates)


def test_r2_uses_real_provider_contract_and_validates_vectors(tmp_path: Path) -> None:
    _, _, semantic, _ = _retrievers(tmp_path)
    candidates = semantic.retrieve("latencia local cloud", limit=3)

    assert candidates[0].relative_path.endswith("atlas-benchmark.md")
    assert all(math.isfinite(item.score) for item in candidates)
    assert len(semantic.fingerprint) == 64


def test_r3_fuses_rankings_without_duplicate_chunks(tmp_path: Path) -> None:
    _, _, _, hybrid = _retrievers(tmp_path)
    candidates = hybrid.retrieve("cambio local cloud latencia", limit=5)

    assert candidates
    assert len({item.chunk_id for item in candidates}) == len(candidates)
    assert all(item.strategy == "R3.hybrid-rrf.v1" for item in candidates)


def test_retrieval_metrics_are_deterministic_and_keep_families_separate(tmp_path: Path) -> None:
    _, lexical, _, _ = _retrievers(tmp_path)
    candidates = lexical.retrieve("presupuesto Atlas", limit=5)
    relevant = {
        "documents/atlas-overview.md",
        "documents/atlas-decision-old.md",
        "documents/atlas-decision-new.md",
    }
    metrics = evaluate_retrieval(candidates, relevant, k=5)

    assert 0.0 <= metrics.recall_at_k <= 1.0
    assert 0.0 <= metrics.precision_at_k <= 1.0
    assert 0.0 <= metrics.ndcg_at_k <= 1.0
    assert metrics.deterministic is True
    assert "fidelity" not in metrics.as_dict()


def test_semantic_provider_rejects_wrong_vector_count(tmp_path: Path) -> None:
    allowed = tmp_path / "controlled"
    vault = allowed / "v1"
    shutil.copytree(Path("benchmarks/controlled/v1"), vault)
    snapshot = SnapshotBuilder().build(
        ReadOnlyVaultAdapter(allowed_root=allowed, vault_root=vault),
        tmp_path / "snapshots",
        vault_id=str(uuid.uuid4()),
    )

    class BrokenProvider:
        provider_id = "broken"
        model_fingerprint = "broken"

        def embed(self, texts):
            return []

    with pytest.raises(ValueError, match="wrong vector count"):
        SemanticRetriever(snapshot.path, BrokenProvider())


def test_benchmark_report_preserves_cases_evidence_and_review_state(tmp_path: Path) -> None:
    _, lexical, _, _ = _retrievers(tmp_path)
    suite = ControlledCorpusSuite.load(Path("benchmarks/controlled/v1"))
    report = RetrievalBenchmarkRunner().run(suite, lexical, k=5)

    assert report.payload["strategy_id"] == "R1.lexical-fts5.v1"
    assert report.payload["human_review_status"] == "pending"
    assert len(report.payload["cases"]) == len(suite.cases)
    assert len(report.content_sha256) == 64
    assert all(
        candidate["evidence_reference"].startswith("snapshot:sha256:")
        for case in report.payload["cases"] for candidate in case["retrieved"]
    )


def test_r4_expands_wikilink_neighbors_and_records_trace(tmp_path: Path) -> None:
    snapshot, lexical, _, _ = _retrievers(tmp_path)

    class OneSeed:
        strategy_id = "test.seed"

        def retrieve(self, query: str, *, limit: int = 10):
            candidates = lexical.retrieve("sustituyó opción cloud inferencia local", limit=10)
            decision = next(item for item in candidates if item.relative_path.endswith("atlas-decision-new.md"))
            return [decision]

    graph = GraphRetriever(snapshot.path, OneSeed())
    candidates = graph.retrieve("¿Qué evidencia respaldó el cambio?", limit=6)

    assert any(item.relative_path.endswith("atlas-benchmark.md") for item in candidates)
    assert any(item.target_path.endswith("atlas-benchmark.md") for item in graph.last_trace)
    assert all(item.strategy == "R4.hybrid-graph.v1" for item in candidates)


def test_context_assembly_is_bounded_deduplicated_and_keeps_evidence(tmp_path: Path) -> None:
    _, lexical, _, _ = _retrievers(tmp_path)
    candidates = lexical.retrieve("Atlas presupuesto local", limit=5)
    one = ContextAssembler().assemble(candidates + candidates, max_characters=700)

    assert one.used_characters <= 700
    assert len({block.chunk_id for block in one.blocks}) == len(one.blocks)
    assert all(block.evidence_reference in one.rendered for block in one.blocks)
    assert one.truncated is True


def test_embedding_cache_is_scoped_by_model_and_avoids_recomputation(tmp_path: Path) -> None:
    class CountingProvider:
        provider_id = "counting"
        model_fingerprint = "model-a"

        def __init__(self):
            self.calls = []

        def embed(self, texts):
            self.calls.append(list(texts))
            return [[float(len(text)), 1.0] for text in texts]

    delegate = CountingProvider()
    cached = CachedEmbeddingProvider(delegate, tmp_path / "embeddings.sqlite3")
    first = cached.embed(["alpha", "beta", "alpha"])
    second = cached.embed(["beta", "alpha"])

    assert delegate.calls == [["alpha", "beta"]]
    assert first[0] == first[2]
    assert second == [first[1], first[0]]


def test_case_metric_set_contains_only_metrics(tmp_path: Path) -> None:
    """El consumidor formal valida el conjunto de métricas y su rango [0, 1].

    `k` es el parámetro de la medición y `deterministic` su clasificación. Publicarlos
    dentro de `metrics` hace que Model Drift rechace el tratamiento entero, porque un
    booleano no es una métrica y una profundidad de 5 se sale del rango.
    """
    from local_ai_lab.retrieval.metrics import RETRIEVAL_METRIC_NAMES, evaluate_retrieval

    metrics = evaluate_retrieval([], set(), k=5)
    values = metrics.metric_values()

    assert set(values) == set(RETRIEVAL_METRIC_NAMES)
    assert "k" not in values and "deterministic" not in values
    for name, value in values.items():
        assert isinstance(value, float) and not isinstance(value, bool), name
        assert 0.0 <= value <= 1.0, name
