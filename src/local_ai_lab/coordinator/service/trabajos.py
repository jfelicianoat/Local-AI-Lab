"""Ciclo de vida de un trabajo: alta, reclamo, progreso, lease y cierre.

El lease es lo que permite que un nodo que se cae no bloquee un trabajo
para siempre; renovarlo es responsabilidad del que lo tiene.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from local_ai_lab.domain.common import canonical_json
from local_ai_lab.domain.jobs import JobSpec, JobState
from local_ai_lab.coordinator.service.nodos import NodosMixin
from local_ai_lab.coordinator.service.base import _lease_payload


class TrabajosMixin(NodosMixin):
    """Ciclo de vida de un trabajo: alta, reclamo, progreso, lease y cierre."""

    def submit_job(self, spec: JobSpec, idempotency_key: str) -> dict[str, Any]:
        return self._idempotent(
            scope="coordinator:submit-job",
            key=idempotency_key,
            request={"spec": asdict(spec)},
            operation=lambda: self.repository.submit_job(spec),
        )

    def claim_job(
        self,
        *,
        node_id: str,
        token: str,
        idempotency_key: str,
        lease_seconds: int = 60,
    ) -> dict[str, Any] | None:
        self._authenticate(node_id, token)

        def claim() -> dict[str, Any]:
            grant = self.repository.claim_job(node_id, lease_seconds)
            return {"lease": _lease_payload(grant) if grant else None}

        result = self._idempotent(
            scope=f"node:{node_id}:claim",
            key=idempotency_key,
            request={"lease_seconds": lease_seconds},
            operation=claim,
        )
        return result["lease"]

    def ack_job(
        self,
        *,
        node_id: str,
        token: str,
        job_id: str,
        lease_token: str,
        lease_generation: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._authenticate(node_id, token)
        return self._idempotent(
            scope=f"job:{job_id}:ack",
            key=idempotency_key,
            request={"node_id": node_id, "lease_generation": lease_generation},
            operation=lambda: self.repository.transition_with_lease(
                job_id=job_id,
                node_id=node_id,
                lease_token=lease_token,
                lease_generation=lease_generation,
                target=JobState.ACKNOWLEDGED,
            ),
        )

    def progress(
        self,
        *,
        node_id: str,
        token: str,
        job_id: str,
        lease_token: str,
        lease_generation: int,
        sequence: int,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._authenticate(node_id, token)
        return self._idempotent(
            scope=f"job:{job_id}:progress",
            key=idempotency_key,
            request={"sequence": sequence, "payload": payload},
            operation=lambda: self.repository.record_progress(
                job_id=job_id,
                node_id=node_id,
                lease_token=lease_token,
                lease_generation=lease_generation,
                sequence=sequence,
                payload=payload,
            ),
        )

    def renew_lease(
        self,
        *,
        node_id: str,
        token: str,
        job_id: str,
        lease_token: str,
        lease_generation: int,
        lease_seconds: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._authenticate(node_id, token)
        return self._idempotent(
            scope=f"job:{job_id}:renew",
            key=idempotency_key,
            request={
                "node_id": node_id,
                "lease_generation": lease_generation,
                "lease_seconds": lease_seconds,
            },
            operation=lambda: self.repository.renew_lease(
                job_id=job_id,
                node_id=node_id,
                lease_token=lease_token,
                lease_generation=lease_generation,
                lease_seconds=lease_seconds,
            ),
        )

    def request_cancel(self, *, job_id: str, idempotency_key: str) -> dict[str, Any]:
        return self._idempotent(
            scope=f"job:{job_id}:request-cancel",
            key=idempotency_key,
            request={"action": "cancel"},
            operation=lambda: self.repository.request_cancel(job_id),
        )

    def job_control(
        self,
        *,
        node_id: str,
        token: str,
        job_id: str,
        lease_token: str,
        lease_generation: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._authenticate(node_id, token)
        return self._idempotent(
            scope=f"job:{job_id}:control:{node_id}",
            key=idempotency_key,
            request={"lease_generation": lease_generation},
            operation=lambda: self.repository.job_control(
                job_id=job_id, node_id=node_id, lease_token=lease_token,
                lease_generation=lease_generation,
            ),
        )

    def complete_job(
        self,
        *,
        node_id: str,
        token: str,
        job_id: str,
        attempt_id: str,
        lease_token: str,
        lease_generation: int,
        outcome: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._authenticate(node_id, token)
        response = self._idempotent(
            scope=f"job:{job_id}:complete:{attempt_id}",
            key=idempotency_key,
            request={"outcome": outcome, "payload": payload},
            operation=lambda: self.repository.complete(
                job_id=job_id,
                node_id=node_id,
                attempt_id=attempt_id,
                lease_token=lease_token,
                lease_generation=lease_generation,
                outcome=outcome,
                payload=payload,
            ),
        )
        if response.get("accepted") is True:
            self._finalize_product_job(job_id, outcome=outcome, payload=payload)
        return response

    def _finalize_product_job(
        self, job_id: str, *, outcome: str, payload: dict[str, Any]
    ) -> None:
        job = self.repository.job(job_id)
        record = self.repository.product_record(job_id)
        if job is None or record is None:
            return
        spec = json.loads(job["spec_json"])
        kind = spec["kind"]
        if kind not in {"training.preflight.v1", "training.lora.v1", "training.distillation.v1", "model.export.v1", "retrieval.benchmark.v1", "broker.agent_experiment.v1", "strategy.suite.v1"}:
            return
        status = {
            "training.preflight.v1": "PREFLIGHT_PASSED",
            "training.lora.v1": "TRAINING_SUCCEEDED",
            "training.distillation.v1": "DISTILLATION_SUCCEEDED",
            "model.export.v1": "EXPORT_SUCCEEDED",
            "retrieval.benchmark.v1": "EXPERIMENT_SUCCEEDED",
            "broker.agent_experiment.v1": "EXPERIMENT_SUCCEEDED",
            "strategy.suite.v1": "EXPERIMENT_SUCCEEDED",
        }[kind] if outcome == "succeeded" else "CANCELLED" if outcome == "cancelled" else "FAILED"
        artifacts = payload.get("artifacts", []) if isinstance(payload, dict) else []
        first = artifacts[0] if isinstance(artifacts, list) and artifacts else None
        artifact_sha256 = (
            first["sha256"] if isinstance(first, dict) and isinstance(first.get("sha256"), str)
            else record["artifact_sha256"]
        )
        summary = {
            **record["summary"], "state": status,
            "result_manifest_sha256": payload.get("preflight_sha256") or payload.get("manifest_sha256"),
            "result_manifest_file_sha256": payload.get("manifest_file_sha256"),
            "package_fingerprint": payload.get("package_fingerprint"),
            "package_id": payload.get("package_id"),
            "formats": payload.get("formats", record["summary"].get("formats")),
            "result_artifacts": [
                {key: item.get(key) for key in ("kind", "sha256", "size", "media_type")}
                for item in artifacts if isinstance(item, dict)
            ],
        }
        if kind == "training.preflight.v1" and outcome == "succeeded":
            summary.update({
                "contract_passed": payload.get("contract", {}).get("passed"),
                "checks": payload.get("checks"), "backend": payload.get("backend"),
                "dtype": payload.get("dtype"),
            })
        if kind == "retrieval.benchmark.v1" and outcome == "succeeded":
            aggregate = payload.get("aggregate", {})
            summary.update({
                "strategy_id": payload.get("strategy_id"),
                "suite_fingerprint": payload.get("suite_fingerprint"),
                "snapshot_hash": payload.get("snapshot_hash"),
                "human_review": payload.get("human_review_status"),
                "recall_at_k": aggregate.get("recall_at_k"),
                "precision_at_k": aggregate.get("precision_at_k"),
                "mrr": aggregate.get("reciprocal_rank"),
                "ndcg_at_k": aggregate.get("ndcg_at_k"),
                "source_coverage": aggregate.get("source_coverage"),
                "redundancy": aggregate.get("redundancy"),
                "latency_ms": payload.get("latency_ms"),
                "case_ids": payload.get("case_ids"),
                "embedding_model": payload.get("embedding_model", record["summary"].get("embedding_model")),
                "embedding_model_fingerprint": payload.get("embedding_model_fingerprint"),
            })
        if kind == "broker.agent_experiment.v1" and outcome == "succeeded":
            summary.update({
                "strategy_id": payload.get("strategy_id"),
                "suite_fingerprint": payload.get("suite_fingerprint"),
                "snapshot_hash": payload.get("snapshot_hash"),
                "case_ids": payload.get("case_ids"),
                "quality": payload.get("quality"),
                "latency_ms": payload.get("latency_ms"),
                "privacy": payload.get("privacy"),
                "formal_status": payload.get("formal_status", "unverified"),
                "embedding_model": payload.get("embedding_model", record["summary"].get("embedding_model")),
                "embedding_model_fingerprint": payload.get(
                    "embedding_model_fingerprint",
                    record["summary"].get("embedding_model_fingerprint"),
                ),
            })
            for candidate in payload.get("review_candidates", []):
                if not isinstance(candidate, dict):
                    continue
                self.feedback.create_review(
                    run_id=job_id, case_id=candidate["case_id"],
                    snapshot_id=candidate["snapshot_id"], reviewer="desktop-user",
                    run_context={
                        "query": candidate["query"],
                        "strategy_id": payload.get("strategy_id", "unknown"),
                        "model": canonical_json(record["summary"].get("target_model", {})),
                        "prompt": candidate["prompt"],
                        "retrieval_config": candidate["retrieval_config"],
                        "snapshot_id": candidate["snapshot_id"],
                        "retrieved_context": candidate["retrieved_context"],
                        "estimated_tokens": None, "cost": candidate["cost"],
                    },
                    original_response=candidate["original_response"],
                )
        if kind == "strategy.suite.v1" and outcome == "succeeded":
            retrieval = payload.get("retrieval", {})
            summary.update({
                "strategy_id": payload.get("strategy_id"),
                "suite_fingerprint": payload.get("suite_fingerprint"),
                "snapshot_hash": payload.get("snapshot_hash"),
                "case_ids": payload.get("case_ids"), "quality": payload.get("quality"),
                "recall_at_k": retrieval.get("recall_at_k"),
                "precision_at_k": retrieval.get("precision_at_k"),
                "mrr": retrieval.get("reciprocal_rank"),
                "ndcg_at_k": retrieval.get("ndcg_at_k"),
                "source_coverage": retrieval.get("source_coverage"),
                "redundancy": retrieval.get("redundancy"),
                "latency_ms": payload.get("latency_ms"),
                "privacy": payload.get("privacy"),
                "formal_status": payload.get("formal_status", "unverified"),
            })
            for candidate in payload.get("review_candidates", []):
                if not isinstance(candidate, dict):
                    continue
                self.feedback.create_review(
                    run_id=job_id, case_id=candidate["case_id"],
                    snapshot_id=candidate["snapshot_id"], reviewer="desktop-user",
                    run_context={
                        "query": candidate["query"], "strategy_id": payload["strategy_id"],
                        "model": canonical_json(record["summary"].get("target_model", {})),
                        "prompt": candidate["prompt"],
                        "retrieval_config": candidate["retrieval_config"],
                        "snapshot_id": candidate["snapshot_id"],
                        "retrieved_context": candidate["retrieved_context"],
                        "estimated_tokens": None, "cost": candidate["cost"],
                    },
                    original_response=candidate["original_response"],
                )
        if outcome == "succeeded" and job.get("assigned_node_id"):
            workload_evidence_sha256 = (
                payload.get("preflight_sha256") or payload.get("manifest_file_sha256")
                or payload.get("report_sha256") or artifact_sha256
            )
            observed_workloads: list[tuple[str, str]] = []
            if kind == "training.preflight.v1":
                observed_workloads.append(("training.lora", "tested"))
            elif kind == "training.lora.v1":
                observed_workloads.extend((("training.lora", "benchmarked"), ("export.adapter", "tested")))
            elif kind == "training.distillation.v1":
                observed_workloads.extend((("training.distillation", "benchmarked"), ("training.lora", "benchmarked"), ("export.adapter", "tested")))
            elif kind == "retrieval.benchmark.v1":
                observed_workloads.append(("embeddings.semantic", "benchmarked"))
            elif kind == "broker.agent_experiment.v1":
                observed_workloads.extend((("broker.agent_experiment", "benchmarked"), ("embeddings.semantic", "benchmarked")))
            elif kind == "strategy.suite.v1":
                observed_workloads.append(("broker.single_experiment", "benchmarked"))
                if payload.get("strategy_id") in {"R2", "R3", "R4", "L1", "F2"}:
                    observed_workloads.append(("embeddings.semantic", "benchmarked"))
            elif kind == "model.export.v1":
                observed_workloads.extend(
                    (f"export.{value}", "benchmarked") for value in payload.get("formats", [])
                )
            for workload, evidence_status in observed_workloads:
                self.repository.record_workload_evidence(
                    job["assigned_node_id"], kind=workload,
                    status=evidence_status, evidence_sha256=workload_evidence_sha256,
                )
            self._record_preflight_hardware_facts(job, kind, payload)
        self.record_product_item(
            record_id=job_id, category=record["category"], title=record["title"],
            status=status, artifact_sha256=artifact_sha256, summary=summary,
        )
        if isinstance(first, dict) and self.artifacts.verify(first["sha256"]):
            self.repository.record_artifact_location(
                record_id=job_id, artifact_kind=first["kind"],
                local_path=self.artifacts.blob_path(first["sha256"]),
                artifact_sha256=first["sha256"],
            )

    def _record_preflight_hardware_facts(
        self, job: dict[str, Any], kind: str, payload: dict[str, Any]
    ) -> None:
        """Convierte el preflight superado en los hechos que exige `required_facts`.

        `FineTuningPlanBuilder` y `DistillationPlanBuilder` exigen `gpu.backend` y
        `dtype.<dtype>` para que un Worker pueda reclamar el job. La sonda de capacidades
        no los produce nunca porque no ejecuta cargas ML: el preflight es lo único que los
        observa de verdad. Sin este paso el job se acepta, queda en `ready` y ningún nodo
        lo reclama jamás.
        """
        if kind != "training.preflight.v1":
            return
        backend = payload.get("backend")
        dtype = payload.get("dtype")
        checks = payload.get("checks")
        if not isinstance(backend, str) or dtype not in {"bf16", "fp16"}:
            return
        if not isinstance(checks, dict) or not all(checks.values()):
            return
        detail = f"training.preflight.v1 {job['job_id']}"
        facts = [
            {"key": "gpu.backend", "value": backend, "status": "tested", "detail": detail},
            {"key": f"dtype.{dtype}", "value": True, "status": "tested", "detail": detail},
            # El preflight entrena 20 pasos con LoRA, guarda, recarga y reanuda desde el
            # checkpoint. Solo se registran los hechos que esa ejecución demuestra; la
            # memoria utilizable sigue sin medirse y por eso no se declara aquí.
            {"key": "training.lora", "value": True, "status": "tested", "detail": detail},
            {"key": "training.backward", "value": True, "status": "tested", "detail": detail},
            {"key": "training.twenty_steps", "value": True, "status": "tested", "detail": detail},
            {"key": "training.checkpoint_resume", "value": True, "status": "tested", "detail": detail},
        ]
        self.repository.record_capability_facts(
            job["assigned_node_id"], facts=facts, source="training.preflight.v1"
        )
