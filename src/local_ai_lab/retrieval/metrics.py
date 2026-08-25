from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Sequence

from local_ai_lab.retrieval.engine import RetrievalCandidate


# Las siete métricas de retrieval del nivel 2, y nada más. `k` es el parámetro de
# la medición y `deterministic` su clasificación: ninguno es una métrica, y tratarlos
# como tales rompe a cualquier consumidor que valide el conjunto o su rango [0, 1].
RETRIEVAL_METRIC_NAMES: tuple[str, ...] = (
    "recall_at_k",
    "precision_at_k",
    "hit_rate",
    "reciprocal_rank",
    "ndcg_at_k",
    "source_coverage",
    "redundancy",
)


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    k: int
    recall_at_k: float
    precision_at_k: float
    hit_rate: float
    reciprocal_rank: float
    ndcg_at_k: float
    source_coverage: float
    redundancy: float
    deterministic: bool = True

    def as_dict(self) -> dict[str, int | float | bool]:
        return asdict(self)

    def metric_values(self) -> dict[str, float]:
        """Solo las métricas, para publicarlas como conjunto de métricas."""
        values = asdict(self)
        return {name: float(values[name]) for name in RETRIEVAL_METRIC_NAMES}


def evaluate_retrieval(
    candidates: Sequence[RetrievalCandidate],
    relevant_paths: set[str],
    *,
    k: int,
) -> RetrievalMetrics:
    if k < 1:
        raise ValueError("k must be positive")
    selected = list(candidates[:k])
    selected_paths = [item.relative_path for item in selected]
    relevant_hits = [path for path in selected_paths if path in relevant_paths]
    unique_relevant = set(relevant_hits)
    recall = len(unique_relevant) / len(relevant_paths) if relevant_paths else 1.0
    precision = len(relevant_hits) / len(selected) if selected else (1.0 if not relevant_paths else 0.0)
    first_rank = next((rank for rank, path in enumerate(selected_paths, start=1) if path in relevant_paths), None)
    reciprocal_rank = 1.0 / first_rank if first_rank else (1.0 if not relevant_paths and not selected else 0.0)
    gains = [1.0 if path in relevant_paths else 0.0 for path in selected_paths]
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    ideal_hits = min(len(relevant_paths), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    ndcg = dcg / idcg if idcg else 1.0
    coverage = len(unique_relevant) / len(relevant_paths) if relevant_paths else 1.0
    redundancy = 1.0 - (len(set(selected_paths)) / len(selected_paths)) if selected_paths else 0.0
    return RetrievalMetrics(
        k=k,
        recall_at_k=recall,
        precision_at_k=precision,
        hit_rate=1.0 if relevant_hits else (1.0 if not relevant_paths and not selected else 0.0),
        reciprocal_rank=reciprocal_rank,
        ndcg_at_k=ndcg,
        source_coverage=coverage,
        redundancy=redundancy,
    )
