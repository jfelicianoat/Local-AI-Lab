from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from statistics import fmean
from typing import Any, Callable

from local_ai_lab.benchmark.controlled import ControlledCorpusSuite
from local_ai_lab.broker.client import BrokerTaskClient
from local_ai_lab.domain.common import canonical_json
from local_ai_lab.evaluation.response_verifier import ResearchResponseVerifier
from local_ai_lab.knowledge_index.projection import KnowledgeIndex
from local_ai_lab.retrieval.engine import HybridRetriever, LexicalRetriever, SemanticRetriever
from local_ai_lab.retrieval.executor import LocalTransformersEmbeddingProvider
from local_ai_lab.retrieval.graph import ContextAssembler, GraphRetriever


# Una referencia de evidencia solo es verificable si trae los identificadores que
# ResearchResponseVerifier contrasta contra el snapshot. Declararlos aquí es lo que
# permite al modelo emitir una cita que pueda pasar el nivel 1 determinista.
EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["snapshot_id", "note_id", "note_path", "section", "chunk_id", "source_reference"],
    "properties": {
        "snapshot_id": {"type": "string"},
        "note_id": {"type": "string"},
        "note_path": {"type": "string", "minLength": 1},
        "section": {"type": "string"},
        "chunk_id": {"type": "string"},
        "source_reference": {"type": "string"},
    },
}

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "findings", "contradictions", "uncertainties", "missing_information"],
    "properties": {
        "answer": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim", "evidence"],
                "properties": {
                    "claim": {"type": "string", "minLength": 1},
                    "evidence": {"type": "array", "minItems": 1, "items": EVIDENCE_SCHEMA},
                },
            },
        },
        "contradictions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["statement", "evidence"],
                "properties": {
                    "statement": {"type": "string"},
                    "evidence": {"type": "array", "items": EVIDENCE_SCHEMA},
                },
            },
        },
        "uncertainties": {"type": "array", "items": {"type": "string"}},
        "missing_information": {"type": "array", "items": {"type": "string"}},
    },
}


class BrokerAgentExperimentExecutor:
    """Executes A1/M1 through Broker 2.9 while Local AI Lab owns retrieval tools."""

    def __call__(
        self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]
    ) -> dict[str, Any]:
        strategy = payload["strategy_id"]
        if strategy not in {"A1", "M1"}:
            raise ValueError("Broker agent executor only accepts A1 or M1")
        snapshot = Path(payload["resolved_snapshot"]).resolve(strict=True)
        suite = ControlledCorpusSuite.load(
            Path(payload["resolved_suite"]).resolve(strict=True), require_human_approval=False
        )
        provider = LocalTransformersEmbeddingProvider(
            payload["embedding_model"], payload["embedding_model_fingerprint"],
            device=payload.get("device", "cpu"), batch_size=int(payload.get("batch_size", 8)),
        )
        lexical = LexicalRetriever(KnowledgeIndex(Path(payload["resolved_index"])))
        hybrid = HybridRetriever(lexical, SemanticRetriever(snapshot, provider))
        retriever = GraphRetriever(snapshot, hybrid)
        verifier = ResearchResponseVerifier(snapshot)
        token = os.environ.get("LOCAL_AI_LAB_BROKER_TOKEN")
        client = BrokerTaskClient(
            endpoint=payload["broker_endpoint"], token=token,
            poll_interval=float(payload.get("poll_interval", 2.0)),
            max_wait=float(payload.get("max_wait", 1800.0)),
        )
        output = Path(payload["report_dir"]).resolve()
        if str(output).startswith(("\\\\", "//")) or output.exists():
            raise ValueError("agent report output must be a new local directory")
        output.mkdir(parents=True, exist_ok=False)
        results: list[dict[str, Any]] = []
        review_candidates: list[dict[str, Any]] = []
        for index, case in enumerate(suite.cases, start=1):
            progress({"stage": "broker_case", "strategy_id": strategy, "case": index, "total": len(suite.cases)})
            candidates = retriever.retrieve(case["query"], limit=int(payload.get("k", 5)))
            context = ContextAssembler().assemble(
                candidates, max_characters=int(payload.get("context_budget", 24000)),
                snapshot_id=verifier.snapshot_id,
            )
            prompt = (
                "Responde en JSON con answer, findings, contradictions, uncertainties y missing_information. "
                "No inventes evidencia y usa las referencias exactas de los bloques. Consulta: " + case["query"]
            )
            execution: dict[str, Any]
            handler = None
            schema = RESPONSE_SCHEMA
            if strategy == "A1":
                execution = {
                    "strategy": "agent", "preset": "fast", "timeout_seconds": 600,
                    "agent": {
                        "skills": [], "max_iterations": 6,
                        "client_tools": [{
                            "name": "retrieve_private_evidence",
                            "description": "Devuelve evidencia local read-only ya recuperada para la consulta.",
                            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                        }],
                    },
                }
                handler = lambda call, rendered=context.rendered: self._tool_result(call, rendered)
                schema = None
            else:
                execution = {
                    "strategy": "mixture_of_agents", "preset": "fast", "timeout_seconds": 600,
                    "max_proposers": 3, "selection": {"mode": "auto", "proposer_count": 3},
                }
                prompt += "\n\nEVIDENCIA LOCAL READ-ONLY:\n" + context.rendered
            started = time.perf_counter()
            invocation = client.invoke(
                prompt=prompt, target_model=payload["target_model"],
                generation={"temperature": 0, "seed": int(payload.get("seed", 42))},
                json_schema=schema, correlation_id=f"{payload['correlation_id']}:{case['case_id']}",
                execution=execution, client_tool_handler=handler,
            )
            try:
                parsed = json.loads(invocation.text)
            except json.JSONDecodeError:
                parsed = None
            verification = verifier.verify(parsed).as_dict() if isinstance(parsed, dict) else None
            results.append({
                "case_id": case["case_id"], "query": case["query"],
                "retrieved_chunk_ids": [item.chunk_id for item in candidates],
                "context_sha256": hashlib.sha256(context.rendered.encode("utf-8")).hexdigest(),
                "response": parsed, "raw_response": invocation.text if parsed is None else None,
                "verification": verification,
                "latency_ms": (time.perf_counter() - started) * 1000.0,
                "broker_task_id": invocation.task_id, "model_used": invocation.model_used,
                "fallback_used": invocation.fallback_used, "usage": invocation.usage,
                "cost": {
                    "amount": invocation.cost_amount, "currency": invocation.cost_currency,
                    "source": invocation.cost_source,
                    "verification_status": invocation.cost_verification_status,
                },
                # Evidencia del contrato 2.10 (Client_API.md, 8.1/8.3/8.4/8.5).
                # `None` o vacío significa «el Broker no lo declara», que no es
                # lo mismo que «no ocurrió»: un informe que no distingue las dos
                # cosas afirma más de lo que puede sostener.
                "execution_evidence": {
                    "prompt_compression": invocation.prompt_compression,
                    "deliverable_sha256": invocation.deliverable_sha256,
                    "auxiliary_roles": list(invocation.auxiliary_roles),
                    "contractual_invocations": len(invocation.contractual_telemetry),
                },
            })
            review_candidates.append({
                "case_id": case["case_id"], "query": case["query"],
                "snapshot_id": verifier.snapshot_id, "prompt": prompt,
                "retrieval_config": {"strategy": "R4", "k": int(payload.get("k", 5))},
                "retrieved_context": [
                    {
                        "chunk_id": item.chunk_id, "note_id": item.note_id,
                        "note_path": item.relative_path, "section": item.section,
                        "content": item.content, "source_reference": item.evidence_reference,
                    }
                    for item in candidates
                ],
                "original_response": parsed if isinstance(parsed, dict) else {"raw_response": invocation.text},
                "cost": {
                    "amount": invocation.cost_amount, "currency": invocation.cost_currency,
                    "source": invocation.cost_source,
                    "verification_status": invocation.cost_verification_status,
                },
            })
        pass_values = [
            1.0 if item["verification"] and item["verification"]["deterministic_pass"] else 0.0
            for item in results
        ]
        report = {
            "schema_version": "broker-agent-experiment.v1", "strategy_id": strategy,
            "suite_fingerprint": suite.fingerprint, "snapshot_hash": verifier.snapshot_hash,
            "case_ids": [case["case_id"] for case in suite.cases],
            "target_model": payload["target_model"], "results": results,
            "quality": {"deterministic_pass_rate": fmean(pass_values)},
            "latency_ms": sum(item["latency_ms"] for item in results),
            "privacy": "local_only", "formal_status": "unverified",
        }
        report_path = output / "agent-experiment.json"
        report_path.write_text(canonical_json(report) + "\n", encoding="utf-8", newline="\n")
        return {
            "report_dir": str(output), "strategy_id": strategy,
            "suite_fingerprint": suite.fingerprint, "snapshot_hash": verifier.snapshot_hash,
            "case_ids": report["case_ids"], "quality": report["quality"],
            "latency_ms": report["latency_ms"], "privacy": "local_only",
            "formal_status": "unverified",
            "review_candidates": review_candidates,
            "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        }

    @staticmethod
    def _tool_result(call: dict[str, Any], rendered: str) -> str:
        if call.get("name") != "retrieve_private_evidence":
            raise ValueError("Broker requested an undeclared Local AI Lab tool")
        return rendered or "No se recuperó evidencia; declara missing_information."
