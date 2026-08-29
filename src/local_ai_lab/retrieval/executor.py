from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from local_ai_lab.benchmark.controlled import ControlledCorpusSuite
from local_ai_lab.benchmark.retrieval_runner import RetrievalBenchmarkRunner
from local_ai_lab.domain.common import canonical_json
from local_ai_lab.knowledge_index.projection import KnowledgeIndex
from local_ai_lab.retrieval.engine import HybridRetriever, LexicalRetriever, SemanticRetriever
from local_ai_lab.retrieval.graph import GraphRetriever


class RetrievalExecutionError(RuntimeError):
    pass


class LocalTransformersEmbeddingProvider:
    """Local-only mean-pooled transformer embeddings; no Hub download is allowed."""

    provider_id = "transformers.local.mean-pool.v1"

    def __init__(self, model: str, model_fingerprint: str, *, device: str, batch_size: int) -> None:
        if len(model_fingerprint) != 64:
            raise RetrievalExecutionError("embedding model requires a verified SHA-256 fingerprint")
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as error:
            raise RetrievalExecutionError("semantic retrieval requires torch and transformers on the Worker") from error
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
        self._model = AutoModel.from_pretrained(model, local_files_only=True).to(device)
        self._model.eval()
        self._device = device
        self._batch_size = max(1, min(256, int(batch_size)))
        self.model_fingerprint = model_fingerprint

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        vectors: list[list[float]] = []
        torch = self._torch
        for offset in range(0, len(texts), self._batch_size):
            batch = list(texts[offset:offset + self._batch_size])
            encoded = self._tokenizer(
                batch, padding=True, truncation=True, return_tensors="pt", max_length=512
            )
            encoded = {key: value.to(self._device) for key, value in encoded.items()}
            with torch.inference_mode():
                hidden = self._model(**encoded).last_hidden_state
                mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
                normalized = torch.nn.functional.normalize(pooled, p=2, dim=1)
            vectors.extend(normalized.detach().cpu().float().tolist())
        return vectors


class ControlledRetrievalExecutor:
    def __call__(
        self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]
    ) -> dict[str, Any]:
        strategy = payload["strategy_id"]
        if strategy not in {"R2", "R3", "R4"}:
            raise RetrievalExecutionError("distributed retrieval strategy must be R2, R3 or R4")
        snapshot = Path(payload["resolved_snapshot"]).resolve(strict=True)
        suite_root = Path(payload["resolved_suite"]).resolve(strict=True)
        index_path = Path(payload["resolved_index"]).resolve(strict=True)
        output = Path(payload["report_dir"]).resolve()
        if str(output).startswith(("\\\\", "//")) or output.exists():
            raise RetrievalExecutionError("retrieval report output must be a new local directory")
        output.mkdir(parents=True, exist_ok=False)
        progress({"stage": "load_local_embedding_model", "strategy_id": strategy})
        provider = LocalTransformersEmbeddingProvider(
            payload["embedding_model"], payload["embedding_model_fingerprint"],
            device=payload.get("device", "cpu"), batch_size=int(payload.get("batch_size", 8)),
        )
        semantic = SemanticRetriever(snapshot, provider)
        lexical = LexicalRetriever(KnowledgeIndex(index_path))
        retriever = semantic if strategy == "R2" else HybridRetriever(lexical, semantic)
        if strategy == "R4":
            retriever = GraphRetriever(snapshot, retriever)
        progress({"stage": "evaluate_ground_truth", "strategy_id": strategy})
        suite = ControlledCorpusSuite.load(suite_root, require_human_approval=False)
        started = time.perf_counter()
        report = RetrievalBenchmarkRunner().run(suite, retriever, k=int(payload.get("k", 5))).payload
        report["latency_ms"] = (time.perf_counter() - started) * 1000.0
        report["snapshot_hash"] = semantic.snapshot_hash
        report["embedding_provider"] = provider.provider_id
        report["embedding_model_fingerprint"] = provider.model_fingerprint
        report_path = output / "retrieval-report.json"
        report_path.write_text(canonical_json(report) + "\n", encoding="utf-8", newline="\n")
        return {
            "report_dir": str(output),
            "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
            "strategy_id": strategy,
            "strategy_contract": report["strategy_id"],
            "suite_fingerprint": suite.fingerprint,
            "snapshot_hash": semantic.snapshot_hash,
            "human_review_status": suite.review_status,
            "aggregate": report["aggregate"],
            "latency_ms": report["latency_ms"],
            "case_ids": [case["case_id"] for case in suite.cases],
            "embedding_model": payload["embedding_model"],
            "embedding_model_fingerprint": provider.model_fingerprint,
        }
