"""Seleccion de estrategia y experimentos comparativos.

Aqui se decide, y se decide con lo que midio `evaluacion`: por eso este
modulo va despues y no al reves.
"""
from __future__ import annotations

import uuid
import hashlib
import json
import math
import zipfile
from dataclasses import replace
from typing import Any

from local_ai_lab.artifacts.archive import deterministic_zip
from local_ai_lab.benchmark.orchestration import bundled_controlled_suite_root, run_controlled_lexical_benchmark
from local_ai_lab.domain.common import canonical_json, sha256_json, sha256_text
from local_ai_lab.domain.jobs import JobSpec
from local_ai_lab.experiments.comparison import StrategyRun
from local_ai_lab.training.comparison import require_same_task
from local_ai_lab.experiments.selector import SelectionConstraints, StrategySelector
from local_ai_lab.agents.planner import AgentExperimentPlanner, AgentExperimentRequest, BrokerAgentCapabilities
from decimal import Decimal
from local_ai_lab.coordinator.service.evaluacion import EvaluacionMixin


class EstrategiasMixin(EvaluacionMixin):
    """Seleccion de estrategia y experimentos comparativos."""

    def select_strategy(
        self,
        *,
        experiment_ids: list[str],
        privacy: str | None,
        max_latency_ms: float | None,
        max_cost: str | None,
        minimum_cases: int,
        require_formal_verdict: bool,
        quality_metric: str = "quality.fidelity",
        minimum_quality: float | None = None,
    ) -> dict[str, Any]:
        records = [self.repository.product_record(record_id) for record_id in experiment_ids]
        if len(set(experiment_ids)) < 2:
            raise ValueError("strategy selection requires at least two distinct experiments")
        if any(record is None for record in records):
            raise ValueError("strategy selection references an unknown experiment")
        formal_evidence: dict[str, str] = {}
        by_id = {record["record_id"]: record for record in records if record is not None}
        for comparison in self.product_workspace()["experiments"]:
            if comparison["category"] != "comparison" or comparison["status"] != "MODEL_DRIFT_VERIFIED":
                continue
            detail = comparison["summary"]
            baseline = by_id.get(detail.get("baseline_experiment_id"))
            candidate = by_id.get(detail.get("candidate_experiment_id"))
            if baseline is None or candidate is None:
                continue
            if (
                detail.get("baseline_artifact_sha256") == baseline["artifact_sha256"]
                and detail.get("candidate_artifact_sha256") == candidate["artifact_sha256"]
                and detail.get("baseline_configuration_fingerprint") == baseline["summary"].get("configuration_fingerprint")
                and detail.get("candidate_configuration_fingerprint") == candidate["summary"].get("configuration_fingerprint")
            ):
                for item in (baseline, candidate):
                    formal_evidence[item["record_id"]] = comparison["artifact_sha256"]
        runs: list[StrategyRun] = []
        latency_scopes: set[str] = set()
        for record in records:
            assert record is not None
            if record["category"] != "experiment" or record["status"] not in {"EXPERIMENT_SUCCEEDED", "LOCAL_VERIFIED"}:
                raise ValueError("strategy selection requires completed experiments")
            summary = record["summary"]
            latency_scopes.add(str(summary.get("latency_scope") or "retrieval_benchmark"))
            result_artifacts = summary.get("result_artifacts")
            if record["status"] == "EXPERIMENT_SUCCEEDED":
                if not isinstance(result_artifacts, list) or not result_artifacts or not self.artifacts.verify(record["artifact_sha256"]):
                    raise ValueError("completed experiment has no verified result artifact")
            else:
                path = self.repository.artifact_location(
                    record["record_id"], expected_kind="retrieval_benchmark_report"
                )
                if hashlib.sha256(path.read_bytes()).hexdigest() != record["artifact_sha256"]:
                    raise ValueError("local experiment report is missing or corrupt")
            latency = summary.get("latency_ms")
            if isinstance(latency, bool) or not isinstance(latency, (int, float)) or not math.isfinite(latency) or latency < 0:
                raise ValueError("every selected experiment requires measured latency")
            case_ids = tuple(str(value) for value in summary.get("case_ids", []))
            strategy_id = str(summary.get("strategy_id", ""))
            if not strategy_id or not case_ids:
                raise ValueError("every selected experiment requires strategy and case evidence")
            runs.append(StrategyRun(
                strategy_run_id=record["record_id"], experiment_id="selector-comparison",
                strategy_id=strategy_id, suite_fingerprint=str(summary["suite_fingerprint"]),
                configuration_label=str(
                    summary.get("configuration_label")
                    or f"{strategy_id} · {summary.get('embedding_model') or 'sin embeddings'} · k={summary.get('k', '?')}"
                ),
                configuration_fingerprint=str(
                    summary.get("configuration_fingerprint")
                    or sha256_json({
                        "strategy_id": strategy_id,
                        "embedding_model_fingerprint": summary.get("embedding_model_fingerprint"),
                        "k": summary.get("k"),
                        "target_model": summary.get("target_model"),
                    })
                ),
                snapshot_hash=str(summary["snapshot_hash"]), case_ids=case_ids,
                model_fingerprint=str(summary.get("embedding_model_fingerprint") or "0" * 64),
                prompt_fingerprint="0" * 64, retrieval_fingerprint=record["artifact_sha256"],
                node_id=str(summary.get("node_id", "coordinator")),
                capability_report_hash=record["artifact_sha256"],
                quality={
                    key: float(value) for key, value in (summary.get("quality") or {}).items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                } if isinstance(summary.get("quality"), dict) else {}, retrieval={
                    key: float(summary[key]) for key in (
                        "recall_at_k", "precision_at_k", "mrr", "ndcg_at_k",
                        "source_coverage", "redundancy",
                    ) if isinstance(summary.get(key), (int, float))
                },
                latency_ms=float(latency), peak_memory_gib=None,
                cost_amount=summary.get("cost_amount") if isinstance(summary.get("cost_amount"), str) else None,
                cost_currency=str(summary.get("cost_currency", "USD")),
                cost_source=str(summary.get("cost_source", "not_available")),
                cost_verification_status=str(summary.get("cost_verification_status", "unknown")),
                privacy=str(summary.get("privacy", "unknown")),
                complexity={"components": {"B0": 1.0, "B1": 2.0, "R1": 3.0, "R2": 4.0, "R3": 5.0, "R4": 6.0, "L1": 7.0, "F1": 8.0, "F2": 9.0}.get(strategy_id, 10.0)},
                formal_status="model_drift_verified" if record["record_id"] in formal_evidence else str(summary.get("formal_status", "unverified")),
                evidence_references=(f"sha256:{record['artifact_sha256']}",) + (
                    (f"sha256:{formal_evidence[record['record_id']]}",)
                    if record["record_id"] in formal_evidence else ()
                ),
            ))
        if len({run.suite_fingerprint for run in runs}) != 1 or len({run.snapshot_hash for run in runs}) != 1 or len({run.case_ids for run in runs}) != 1:
            raise ValueError("strategy runs are not comparable on suite, snapshot and cases")
        if len(latency_scopes) != 1:
            raise ValueError("strategy runs measure latency over different scopes")
        decision = StrategySelector().select(runs, SelectionConstraints(
            privacy=privacy, max_latency_ms=max_latency_ms,
            max_cost=Decimal(max_cost) if max_cost is not None else None,
            minimum_cases=minimum_cases, require_formal_verdict=require_formal_verdict,
            quality_metric=quality_metric, minimum_quality=minimum_quality,
        ))
        decision_id = str(uuid.uuid4())
        payload = {
            "status": decision.status, "strategy_id": decision.strategy_id,
            "configuration_label": decision.configuration_label,
            "configuration_fingerprint": decision.configuration_fingerprint,
            "explanation": list(decision.explanation),
            "evidence_references": list(decision.evidence_references),
            "uncertainty": decision.uncertainty, "experiment_ids": experiment_ids,
        }
        fingerprint = sha256_text(canonical_json(payload))
        self.record_product_item(
            record_id=decision_id, category="comparison", title="Recomendación de estrategia",
            status="RECOMMENDATION" if decision.status == "recommendation" else "INSUFFICIENT_EVIDENCE",
            artifact_sha256=fingerprint, summary=payload,
        )
        return self.repository.product_record(decision_id)  # type: ignore[return-value]

    def create_broker_agent_experiment_job(
        self,
        *,
        strategy_id: str,
        broker_check_id: str,
        broker_endpoint: str,
        node_id: str,
        target_model: dict[str, str],
        embedding_model: str,
        embedding_model_fingerprint: str,
        device: str,
        k: int,
        idempotency_key: str,
        benchmark_id: str | None = None,
        snapshot_id: str | None = None,
        index_id: str | None = None,
    ) -> dict[str, Any]:
        broker_check = self.repository.product_record(broker_check_id)
        if broker_check is None or broker_check["status"] != "CAPABILITIES_SATISFIED":
            raise ValueError("A1/M1 requires a satisfied read-only Broker capability report")
        summary = broker_check["summary"]
        if summary.get("phase") != "agent_experiments" or summary.get("observed_contract") is None:
            raise ValueError("Broker report was not produced for agent experiments")
        if broker_endpoint.rstrip("/") != str(summary.get("endpoint", "")).rstrip("/"):
            raise ValueError("Broker endpoint differs from the satisfied capability report")
        if self.repository.node_record(node_id) is None:
            raise ValueError("agent experiment requires a registered Worker")
        if set(target_model) != {"provider", "deployment", "model"} or any(
            not isinstance(value, str) or not value.strip() for value in target_model.values()
        ):
            raise ValueError("agent experiment requires an exact provider/deployment/model")
        inputs = self._execution_inputs(
            benchmark_id=benchmark_id, snapshot_id=snapshot_id, index_id=index_id, k=k
        )
        package_root = self.repository.path.parent / "packages"
        package_id = str(uuid.uuid4())
        snapshot_zip, _ = deterministic_zip(
            inputs["snapshot_path"], package_root / f"agent-snapshot-{package_id}.zip",
        )
        suite_zip, _ = deterministic_zip(
            inputs["suite_root"], package_root / f"agent-suite-{package_id}.zip",
        )
        snapshot_cas = self.artifacts.ingest_file(snapshot_zip)
        suite_cas = self.artifacts.ingest_file(suite_zip)
        index_cas = self.artifacts.ingest_file(inputs["index_path"])
        if benchmark_id is None:
            self.record_product_item(
                record_id=inputs["snapshot_id"], category="snapshot",
                title="Snapshot sintético de benchmark", status="COMPLETE",
                artifact_sha256=inputs["snapshot_hash"],
                summary={"benchmark_only": True, "suite_fingerprint": inputs["suite_fingerprint"]},
            )
            self.repository.record_artifact_location(
                record_id=inputs["snapshot_id"], artifact_kind="vault_snapshot",
                local_path=inputs["snapshot_path"], artifact_sha256=inputs["snapshot_hash"],
            )
        request = AgentExperimentRequest(
            experiment_id=str(uuid.uuid4()), strategy_id=strategy_id,
            query="selected-suite", snapshot_hash=inputs["snapshot_hash"],
            retrieval_artifact_sha256=index_cas["sha256"],
            target_model=canonical_json(target_model),
            tool_contracts=("local-ai-lab.retrieve-private-evidence.v1",),
        )
        planned = AgentExperimentPlanner().plan(
            request,
            BrokerAgentCapabilities(
                contract_version=str(summary["observed_contract"]),
                strategies=("agent", "mixture_of_agents"), exact_target_model=True,
                client_tool_passthrough=True, exclude_from_model_learning=True,
                observed=True,
            ),
        )
        payload = {
            **planned.payload,
            "strategy_id": strategy_id,
            "broker_endpoint": broker_endpoint,
            "target_model": target_model,
            "embedding_model": embedding_model,
            "embedding_model_fingerprint": embedding_model_fingerprint,
            "device": device, "k": k, "correlation_id": planned.correlation_id,
            "input_artifacts": [
                {"sha256": snapshot_cas["sha256"], "mount_as": "resolved_snapshot", "archive": "zip"},
                {"sha256": suite_cas["sha256"], "mount_as": "resolved_suite", "archive": "zip"},
                {"sha256": index_cas["sha256"], "mount_as": "resolved_index"},
            ],
            "output_mounts": ["report_dir"],
            "collect_outputs": [{"result_key": "report_dir", "kind": "agent_experiment_report"}],
        }
        requirements = {"node_ids": [node_id]}
        job = replace(planned, payload=payload, requirements=requirements)
        submitted = self.submit_job(job, idempotency_key)
        self.record_product_item(
            record_id=job.job_id, category="experiment", title=f"{strategy_id} · {inputs['label']}",
            status="EXPERIMENT_QUEUED", artifact_sha256=job.fingerprint(),
            summary={
                "job_id": job.job_id, "strategy_id": strategy_id,
                "suite_fingerprint": inputs["suite_fingerprint"],
                "snapshot_hash": inputs["snapshot_hash"],
                "case_ids": inputs["case_ids"],
                "benchmark_id": benchmark_id, "snapshot_id": inputs["snapshot_id"], "index_id": index_id,
                "node_id": node_id, "target_model": target_model,
                "broker_contract": summary["observed_contract"],
                "broker_check_id": broker_check_id, "privacy": "local_only",
                "formal_status": "unverified", "state": submitted["state"],
            },
        )
        return self.repository.product_record(job.job_id)  # type: ignore[return-value]

    def create_strategy_suite_job(
        self,
        *,
        strategy_id: str,
        broker_check_id: str,
        broker_endpoint: str,
        node_id: str,
        target_model: dict[str, str],
        embedding_model: str | None,
        embedding_model_fingerprint: str | None,
        device: str,
        training_job_id: str | None,
        k: int,
        idempotency_key: str,
        benchmark_id: str | None = None,
        snapshot_id: str | None = None,
        index_id: str | None = None,
    ) -> dict[str, Any]:
        allowed = {"B0", "B1", "R1", "R2", "R3", "R4", "L1", "F1", "F2"}
        if strategy_id not in allowed:
            raise ValueError("unknown strategy suite id")
        fine_tuned = strategy_id in {"F1", "F2"}
        if not fine_tuned:
            broker_check = self.repository.product_record(broker_check_id)
            if broker_check is None or broker_check["status"] != "CAPABILITIES_SATISFIED" or broker_check["summary"].get("phase") != "retrieval":
                raise ValueError("strategy suite requires a satisfied read-only Broker retrieval report")
            if broker_endpoint.rstrip("/") != str(broker_check["summary"].get("endpoint", "")).rstrip("/"):
                raise ValueError("Broker endpoint differs from the satisfied capability report")
        if self.repository.node_record(node_id) is None:
            raise ValueError("strategy suite requires a registered Worker")
        if set(target_model) != {"provider", "deployment", "model"} or any(not value.strip() for value in target_model.values()):
            raise ValueError("strategy suite requires an exact target model")
        semantic = strategy_id in {"R2", "R3", "R4", "L1", "F2"}
        if semantic and (
            not embedding_model or not embedding_model.strip()
            or not embedding_model_fingerprint or len(embedding_model_fingerprint) != 64
        ):
            raise ValueError("semantic/RAG strategies require a local embedding model fingerprint")
        trained_model_identity: dict[str, str] | None = None
        training_artifact_sha256: str | None = None
        training_record: dict[str, Any] | None = None
        if fine_tuned:
            training = self.repository.product_record(training_job_id or "")
            training_job = self.repository.job(training_job_id or "")
            if training is None or training["status"] not in {"TRAINING_SUCCEEDED", "DISTILLATION_SUCCEEDED"}:
                raise ValueError("F1/F2 requires a successful Local AI Lab training result")
            if training_job is None or training_job["state"] != "succeeded":
                raise ValueError("trained model has no successful Worker result")
            result, _ = self._verified_completed_ml_result(training_job)
            artifact = next((item for item in result.get("artifacts", [])
                             if isinstance(item, dict) and item.get("kind") == "training_result"), None)
            if artifact is None or not self.artifacts.verify(artifact.get("sha256", "")):
                raise ValueError("trained adapter package is missing or corrupt")
            training_artifact_sha256 = artifact["sha256"]
            manifest_kind = "training" if training["status"] == "TRAINING_SUCCEEDED" else "distillation"
            filename = "training-manifest.json" if manifest_kind == "training" else "distillation-manifest.json"
            try:
                with zipfile.ZipFile(self.artifacts.blob_path(training_artifact_sha256)) as archive:
                    manifest_bytes = archive.read(filename)
                    manifest = json.loads(manifest_bytes)
            except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
                raise ValueError("trained adapter package has no valid manifest") from error
            manifest_content_sha256 = manifest.pop("content_sha256", None)
            if (
                hashlib.sha256(manifest_bytes).hexdigest() != result.get("manifest_file_sha256")
                or manifest_content_sha256 != result.get("manifest_sha256")
                or hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest() != manifest_content_sha256
                or not isinstance(manifest.get("base_weights_sha256"), str)
            ):
                raise ValueError("trained adapter identity is incomplete or inconsistent")
            base_model = manifest.get("base_model") or manifest.get("student_model")
            expected_target = {
                "provider": "local_adapter", "deployment": training_job_id,
                "model": base_model,
            }
            if target_model != expected_target:
                raise ValueError("F1/F2 target must identify the selected local adapter and its base model")
            trained_model_identity = {
                "training_job_id": str(training_job_id),
                "manifest_kind": manifest_kind,
                "manifest_sha256": result["manifest_sha256"],
                "manifest_file_sha256": result["manifest_file_sha256"],
                "package_sha256": training_artifact_sha256,
                "base_model": base_model,
                "base_weights_sha256": manifest["base_weights_sha256"],
            }
            training_record = training
        configuration = {
            "strategy_id": strategy_id,
            "target_model": target_model,
            "embedding_model": embedding_model,
            "embedding_model_fingerprint": embedding_model_fingerprint,
            "device": device,
            "training_job_id": training_job_id,
            "training_artifact_sha256": training_artifact_sha256,
            "k": k,
        }
        inputs = self._execution_inputs(
            benchmark_id=benchmark_id, snapshot_id=snapshot_id, index_id=index_id, k=k
        )
        if fine_tuned:
            assert training_record is not None and trained_model_identity is not None
            training_summary = training_record["summary"]
            dataset = self.repository.product_record(str(training_summary.get("dataset_id", "")))
            baseline = self._validated_training_baseline(
                str(training_summary.get("baseline_experiment_id", "")), dataset
            )
            baseline_summary = baseline["summary"]
            expected_model = (training_summary.get("base_model") if training_record["status"] == "TRAINING_SUCCEEDED"
                              else training_summary.get("teacher_model"))
            require_same_task(
                strategy_id=strategy_id, training=training_summary, baseline=baseline_summary,
                execution=inputs, benchmark_id=benchmark_id, index_id=index_id,
                embedding_model=embedding_model, embedding_model_fingerprint=embedding_model_fingerprint,
                k=k, expected_baseline_model=expected_model,
            )
            if training_summary.get("baseline_verified_quality") != baseline["verified_quality"]:
                raise ValueError("training baseline evidence changed since approval")
        package_root = self.repository.path.parent / "packages"
        package_id = str(uuid.uuid4())
        snapshot_zip, _ = deterministic_zip(inputs["snapshot_path"], package_root / f"strategy-snapshot-{package_id}.zip")
        suite_zip, _ = deterministic_zip(inputs["suite_root"], package_root / f"strategy-suite-{package_id}.zip")
        snapshot_cas = self.artifacts.ingest_file(snapshot_zip)
        suite_cas = self.artifacts.ingest_file(suite_zip)
        index_cas = self.artifacts.ingest_file(inputs["index_path"])
        if benchmark_id is None:
            self.record_product_item(
                record_id=inputs["snapshot_id"], category="snapshot",
                title="Snapshot sintético de benchmark", status="COMPLETE",
                artifact_sha256=inputs["snapshot_hash"],
                summary={"benchmark_only": True, "suite_fingerprint": inputs["suite_fingerprint"]},
            )
            self.repository.record_artifact_location(
                record_id=inputs["snapshot_id"], artifact_kind="vault_snapshot",
                local_path=inputs["snapshot_path"], artifact_sha256=inputs["snapshot_hash"],
            )
        job = JobSpec(
            kind="strategy.suite.v1",
            payload={
                "strategy_id": strategy_id, "broker_endpoint": broker_endpoint,
                "target_model": target_model, "embedding_model": embedding_model,
                "embedding_model_fingerprint": embedding_model_fingerprint,
                "device": device, "k": k, "correlation_id": str(uuid.uuid4()),
                "trained_model_identity": trained_model_identity,
                "input_artifacts": [
                    {"sha256": snapshot_cas["sha256"], "mount_as": "resolved_snapshot", "archive": "zip"},
                    {"sha256": suite_cas["sha256"], "mount_as": "resolved_suite", "archive": "zip"},
                    {"sha256": index_cas["sha256"], "mount_as": "resolved_index"},
                ] + ([{"sha256": training_artifact_sha256, "mount_as": "resolved_training_output", "archive": "zip"}]
                     if training_artifact_sha256 else []),
                "output_mounts": ["report_dir"],
                "collect_outputs": [{"result_key": "report_dir", "kind": "strategy_suite_report"}],
            },
            requirements={"node_ids": [node_id]},
        )
        submitted = self.submit_job(job, idempotency_key)
        self.record_product_item(
            record_id=job.job_id, category="experiment", title=f"{strategy_id} · {inputs['label']}",
            status="EXPERIMENT_QUEUED", artifact_sha256=job.fingerprint(),
            summary={
                "job_id": job.job_id, "strategy_id": strategy_id,
                "suite_fingerprint": inputs["suite_fingerprint"],
                "snapshot_hash": inputs["snapshot_hash"],
                "case_ids": inputs["case_ids"],
                "benchmark_id": benchmark_id, "snapshot_id": inputs["snapshot_id"], "index_id": index_id,
                "node_id": node_id, "target_model": target_model,
                "embedding_model": embedding_model,
                "embedding_model_fingerprint": embedding_model_fingerprint,
                "device": device, "k": k,
                "configuration_label": (
                    f"{strategy_id} · {embedding_model or target_model['model']} · k={k}"
                ),
                "configuration_fingerprint": sha256_json(configuration),
                "training_job_id": training_job_id, "privacy": "local_only",
                "baseline_experiment_id": training_record["summary"].get("baseline_experiment_id") if training_record else None,
                "minimum_quality_gain": training_record["summary"].get("minimum_quality_gain") if training_record else None,
                "trained_model_identity": trained_model_identity,
                "formal_status": "unverified", "state": submitted["state"],
            },
        )
        return self.repository.product_record(job.job_id)  # type: ignore[return-value]
