from __future__ import annotations

import hashlib
import json
import os
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import fmean
from typing import Any, Callable

from local_ai_lab.agents.executor import RESPONSE_SCHEMA
from local_ai_lab.benchmark.execution import load_execution_suite
from local_ai_lab.benchmark.retrieval_runner import RetrievalBenchmarkRunner
from local_ai_lab.broker.client import BrokerTaskClient
from local_ai_lab.domain.common import canonical_json
from local_ai_lab.evaluation.response_verifier import ResearchResponseVerifier
from local_ai_lab.knowledge_index.projection import KnowledgeIndex
from local_ai_lab.retrieval.engine import HybridRetriever, LexicalRetriever, SemanticRetriever
from local_ai_lab.retrieval.executor import LocalTransformersEmbeddingProvider
from local_ai_lab.retrieval.graph import GraphRetriever
from local_ai_lab.strategies.generation import B0Strategy, B1Strategy, RagStrategy
from local_ai_lab.training.local_inference import LocalAdapterClient


class StrategySuiteExecutor:
    """Runs the common B/R/L/F strategy contract over one frozen suite."""

    def __call__(
        self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]
    ) -> dict[str, Any]:
        strategy_id = payload["strategy_id"]
        allowed = {"B0", "B1", "R1", "R2", "R3", "R4", "L1", "F1", "F2"}
        if strategy_id not in allowed:
            raise ValueError("unsupported strategy suite id")
        snapshot = Path(payload["resolved_snapshot"]).resolve(strict=True)
        suite = load_execution_suite(Path(payload["resolved_suite"]), snapshot)
        lexical = LexicalRetriever(KnowledgeIndex(Path(payload["resolved_index"])))
        retriever = None
        if strategy_id in {"R1"}:
            retriever = lexical
        elif strategy_id in {"R2", "R3", "R4", "L1", "F2"}:
            provider = LocalTransformersEmbeddingProvider(
                payload["embedding_model"], payload["embedding_model_fingerprint"],
                device=payload.get("device", "cpu"), batch_size=int(payload.get("batch_size", 8)),
            )
            semantic = SemanticRetriever(snapshot, provider)
            retriever = semantic if strategy_id == "R2" else HybridRetriever(lexical, semantic)
            if strategy_id in {"R4", "L1", "F2"}:
                retriever = GraphRetriever(snapshot, retriever)
        if strategy_id in {"F1", "F2"}:
            client = LocalAdapterClient(
                output=Path(payload["resolved_training_output"]),
                identity=payload["trained_model_identity"],
                device=payload.get("device", "cpu"),
            )
        else:
            client = BrokerTaskClient(
                endpoint=payload["broker_endpoint"], token=os.environ.get("LOCAL_AI_LAB_BROKER_TOKEN"),
                poll_interval=float(payload.get("poll_interval", 2.0)),
                max_wait=float(payload.get("max_wait", 1800.0)),
            )
        verifier = ResearchResponseVerifier(snapshot)
        target_model = payload["target_model"]
        results: list[dict[str, Any]] = []
        review_candidates: list[dict[str, Any]] = []
        for index, case in enumerate(suite.cases, start=1):
            case_started = time.monotonic()
            progress({"stage": "strategy_case", "strategy_id": strategy_id, "case": index, "total": len(suite.cases)})
            correlation = f"{payload['correlation_id']}:{case['case_id']}"
            if strategy_id == "B0":
                execution = B0Strategy(client).execute(query=case["query"], target_model=target_model, correlation_id=correlation)
            elif strategy_id in {"B1", "F1"}:
                execution = B1Strategy(client, RESPONSE_SCHEMA).execute(query=case["query"], target_model=target_model, correlation_id=correlation)
            else:
                assert retriever is not None
                execution = RagStrategy(
                    strategy_id="F2.finetuned-rag.v1" if strategy_id == "F2" else f"R{strategy_id[1:]}.suite.v1" if strategy_id.startswith("R") else "R4.large-local.v1",
                    broker=client, retriever=retriever, snapshot=snapshot,
                    response_schema=RESPONSE_SCHEMA,
                ).execute(query=case["query"], target_model=target_model, correlation_id=correlation, k=int(payload.get("k", 5)))
            parsed = execution.parsed_response
            verification = verifier.verify(parsed).as_dict() if isinstance(parsed, dict) else None
            cost = {
                "amount": execution.broker.cost_amount, "currency": execution.broker.cost_currency,
                "source": execution.broker.cost_source,
                "verification_status": execution.broker.cost_verification_status,
            }
            retrieved_context = []
            if retriever is not None:
                retrieved_context = [
                    {
                        "chunk_id": item.chunk_id, "note_id": item.note_id,
                        "note_path": item.relative_path, "section": item.section,
                        "content": item.content, "source_reference": item.evidence_reference,
                    }
                    for item in retriever.retrieve(case["query"], limit=int(payload.get("k", 5)))
                ]
            case_latency_ms = (time.monotonic() - case_started) * 1000.0
            results.append({
                "case_id": case["case_id"], "response": parsed,
                "raw_response": execution.raw_response if parsed is None else None,
                "verification": verification, "latency_ms": case_latency_ms,
                "generation_latency_ms": execution.broker.latency_ms,
                "model_used": execution.broker.model_used, "fallback_used": execution.broker.fallback_used,
                "cost": cost, "context_sha256": hashlib.sha256(execution.exact_context.encode()).hexdigest(),
                # Evidencia del contrato 2.10 (Client_API.md, 8.1/8.3/8.4/8.5).
                # `None` o vacío significa «el Broker no lo declara», que no es
                # lo mismo que «no ocurrió»: un informe que no distingue las dos
                # cosas afirma más de lo que puede sostener.
                "execution_evidence": {
                    "prompt_compression": execution.broker.prompt_compression,
                    "deliverable_sha256": execution.broker.deliverable_sha256,
                    "auxiliary_roles": list(execution.broker.auxiliary_roles),
                    "contractual_invocations": len(execution.broker.contractual_telemetry),
                },
            })
            review_candidates.append({
                "case_id": case["case_id"], "query": case["query"],
                "snapshot_id": verifier.snapshot_id,
                "prompt": execution.exact_prompt,
                "retrieval_config": {"strategy": strategy_id, "k": int(payload.get("k", 5))},
                "retrieved_context": retrieved_context,
                "original_response": parsed if isinstance(parsed, dict) else {"raw_response": execution.raw_response},
                "cost": cost,
            })
        verification_values = [
            1.0 if item["verification"] and item["verification"]["deterministic_pass"] else 0.0
            for item in results
        ]
        known_costs: list[Decimal] = []
        currencies = {item["cost"]["currency"] for item in results}
        for item in results:
            amount = item["cost"]["amount"]
            try:
                if amount is None:
                    break
                parsed = Decimal(str(amount))
                if not parsed.is_finite() or parsed < 0:
                    break
                known_costs.append(parsed)
            except (InvalidOperation, TypeError, ValueError):
                break
        complete_cost = len(known_costs) == len(results) and len(currencies) == 1
        cost_amount = str(sum(known_costs)) if complete_cost else None
        cost_currency = next(iter(currencies)) if complete_cost else "USD"
        cost_source = "measured" if complete_cost and all(
            item["cost"]["source"] == "measured" for item in results
        ) else "reported" if complete_cost else "not_available"
        cost_verification_status = "verified" if complete_cost and all(
            item["cost"]["verification_status"] == "verified" for item in results
        ) else "unknown"
        retrieval_metrics = {}
        if retriever is not None:
            retrieval_metrics = RetrievalBenchmarkRunner().run(
                suite, retriever, k=int(payload.get("k", 5))
            ).payload["aggregate"]
        report = {
            "schema_version": "strategy-suite-report.v1", "strategy_id": strategy_id,
            "suite_fingerprint": suite.fingerprint, "snapshot_hash": verifier.snapshot_hash,
            "case_ids": [case["case_id"] for case in suite.cases],
            "target_model": target_model, "k": int(payload.get("k", 5)),
            "quality": {"deterministic_pass_rate": fmean(verification_values)},
            "retrieval": retrieval_metrics, "latency_ms": sum(item["latency_ms"] for item in results),
            "latency_scope": "case_end_to_end_including_retrieval_and_generation",
            "generation_latency_ms": sum(item["generation_latency_ms"] for item in results),
            "cost_amount": cost_amount, "cost_currency": cost_currency,
            "cost_source": cost_source, "cost_verification_status": cost_verification_status,
            "privacy": "local_only", "formal_status": "unverified", "results": results,
            "embedding_model": payload.get("embedding_model"),
            "embedding_model_fingerprint": payload.get("embedding_model_fingerprint"),
            "trained_model_identity": payload.get("trained_model_identity"),
            "review_candidates": review_candidates,
        }
        output = Path(payload["report_dir"]).resolve()
        if str(output).startswith(("\\\\", "//")) or output.exists():
            raise ValueError("strategy report output must be a new local directory")
        output.mkdir(parents=True, exist_ok=False)
        report_path = output / "strategy-report.json"
        report_path.write_text(canonical_json(report) + "\n", encoding="utf-8", newline="\n")
        return {
            "report_dir": str(output), "strategy_id": strategy_id,
            "suite_fingerprint": suite.fingerprint, "snapshot_hash": verifier.snapshot_hash,
            "case_ids": report["case_ids"], "quality": report["quality"],
            "retrieval": retrieval_metrics, "latency_ms": report["latency_ms"],
            "latency_scope": report["latency_scope"],
            "generation_latency_ms": report["generation_latency_ms"],
            "cost_amount": cost_amount, "cost_currency": cost_currency,
            "cost_source": cost_source, "cost_verification_status": cost_verification_status,
            "privacy": "local_only", "formal_status": "unverified",
            "embedding_model": payload.get("embedding_model"),
            "embedding_model_fingerprint": payload.get("embedding_model_fingerprint"),
            "trained_model_identity": payload.get("trained_model_identity"),
            "review_candidates": review_candidates,
            "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        }
