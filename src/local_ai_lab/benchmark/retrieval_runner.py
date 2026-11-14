from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any, Protocol

from local_ai_lab.benchmark.controlled import ControlledCorpusSuite
from local_ai_lab.domain.common import sha256_json, utc_timestamp
from local_ai_lab.retrieval.engine import RetrievalCandidate
from local_ai_lab.retrieval.metrics import RETRIEVAL_METRIC_NAMES, evaluate_retrieval


class Retriever(Protocol):
    strategy_id: str

    def retrieve(self, query: str, *, limit: int = 10) -> list[RetrievalCandidate]: ...


@dataclass(frozen=True, slots=True)
class RetrievalBenchmarkReport:
    payload: dict[str, Any]

    @property
    def content_sha256(self) -> str:
        return self.payload["content_sha256"]


class RetrievalBenchmarkRunner:
    def run(
        self,
        suite: ControlledCorpusSuite,
        retriever: Retriever,
        *,
        k: int = 5,
    ) -> RetrievalBenchmarkReport:
        if k < 1 or k > 100:
            raise ValueError("k must be between 1 and 100")
        paths = {
            item["document_id"]: item["relative_path"]
            for item in suite.definition["documents"]
        }
        results: list[dict[str, Any]] = []
        for case in suite.cases:
            candidates = retriever.retrieve(case["query"], limit=k)
            relevant = {
                paths[document_id]
                for document_id in case["ground_truth"]["relevant_document_ids"]
            }
            metrics = evaluate_retrieval(candidates, relevant, k=k)
            results.append(
                {
                    "case_id": case["case_id"],
                    "kinds": case["kinds"],
                    "query": case["query"],
                    "relevant_paths": sorted(relevant),
                    "answerable": bool(relevant),
                    "retrieved": [
                        {
                            "rank": item.rank,
                            "relative_path": item.relative_path,
                            "chunk_id": item.chunk_id,
                            "score": item.score,
                            "evidence_reference": item.evidence_reference,
                        }
                        for item in candidates
                    ],
                    "k": metrics.k,
                    "deterministic": metrics.deterministic,
                    "metrics": metrics.metric_values(),
                }
            )
        # Una consulta sin relevantes puntúa 1,0 en recall y nDCG: mezclada en la
        # media la inflaría. Se mide aparte, como abstención.
        answerable = [result for result in results if result["answerable"]]
        unanswerable = [result for result in results if not result["answerable"]]
        aggregate = {
            name: fmean(result["metrics"][name] for result in answerable) if answerable else None
            for name in RETRIEVAL_METRIC_NAMES
        }
        unanswerable_summary = {
            "cases": len(unanswerable),
            # En una consulta sin respuesta, lo correcto es no devolver nada.
            "empty_result_rate": (
                fmean(1.0 if not result["retrieved"] else 0.0 for result in unanswerable) if unanswerable else None
            ),
        }
        payload: dict[str, Any] = {
            "schema_version": "retrieval-benchmark-report.v2",
            "suite_id": suite.definition["suite_id"],
            "suite_fingerprint": suite.fingerprint,
            "human_review_status": suite.review_status,
            "strategy_id": retriever.strategy_id,
            "k": k,
            "metric_classification": "deterministic",
            "generated_at": utc_timestamp(),
            "cases": results,
            "aggregate": aggregate,
            "answerable_cases": len(answerable),
            "unanswerable": unanswerable_summary,
        }
        payload["content_sha256"] = sha256_json(payload)
        return RetrievalBenchmarkReport(payload)
