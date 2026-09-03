"""Seleccion de estrategia y experimentos comparativos.

Aqui se decide, y se decide con lo que midio `evaluacion`: por eso este
modulo va despues y no al reves.
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from local_ai_lab.artifacts.archive import deterministic_zip
from local_ai_lab.benchmark.orchestration import bundled_controlled_suite_root, run_controlled_lexical_benchmark
from local_ai_lab.domain.common import canonical_json, sha256_json, sha256_text
from local_ai_lab.domain.jobs import JobSpec
from local_ai_lab.experiments.comparison import StrategyRun
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
    ) -> dict[str, Any]:
        records = [self.repository.product_record(record_id) for record_id in experiment_ids]
        if len(set(experiment_ids)) < 2:
            raise ValueError("strategy selection requires at least two distinct experiments")
        if any(record is None for record in records):
            raise ValueError("strategy selection references an unknown experiment")
        runs: list[StrategyRun] = []
        for record in records:
            assert record is not None
            summary = record["summary"]
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
                quality={}, retrieval={
                    key: float(summary[key]) for key in (
                        "recall_at_k", "precision_at_k", "mrr", "ndcg_at_k",
                        "source_coverage", "redundancy",
                    ) if isinstance(summary.get(key), (int, float))
                },
                latency_ms=float(summary.get("latency_ms", 0.0)), peak_memory_gib=None,
                cost_amount=summary.get("cost_amount") if isinstance(summary.get("cost_amount"), str) else None,
                cost_currency=str(summary.get("cost_currency", "USD")),
                cost_source=str(summary.get("cost_source", "not_available")),
                cost_verification_status=str(summary.get("cost_verification_status", "unknown")),
                privacy=str(summary.get("privacy", "unknown")),
                complexity={"components": {"R1": 1.0, "R2": 2.0, "R3": 3.0, "R4": 4.0}.get(strategy_id, 10.0)},
                formal_status=str(summary.get("formal_status", "unverified")),
                evidence_references=(f"sha256:{record['artifact_sha256']}",),
            ))
        if len({run.suite_fingerprint for run in runs}) != 1 or len({run.snapshot_hash for run in runs}) != 1 or len({run.case_ids for run in runs}) != 1:
            raise ValueError("strategy runs are not comparable on suite, snapshot and cases")
        decision = StrategySelector().select(runs, SelectionConstraints(
            privacy=privacy, max_latency_ms=max_latency_ms,
            max_cost=Decimal(max_cost) if max_cost is not None else None,
            minimum_cases=minimum_cases, require_formal_verdict=require_formal_verdict,
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
    ) -> dict[str, Any]:
        broker_check = self.repository.product_record(broker_check_id)
        if broker_check is None or broker_check["status"] != "CAPABILITIES_SATISFIED":
            raise ValueError("A1/M1 requires a satisfied read-only Broker capability report")
        summary = broker_check["summary"]
        if summary.get("phase") != "agent_experiments" or summary.get("observed_contract") is None:
            raise ValueError("Broker report was not produced for agent experiments")
        if self.repository.node_record(node_id) is None:
            raise ValueError("agent experiment requires a registered Worker")
        if set(target_model) != {"provider", "deployment", "model"} or any(
            not isinstance(value, str) or not value.strip() for value in target_model.values()
        ):
            raise ValueError("agent experiment requires an exact provider/deployment/model")
        baseline = run_controlled_lexical_benchmark(
            self.repository.path.parent / "experiments", k=k
        )
        experiment_root = baseline.report_path.parent
        package_root = self.repository.path.parent / "packages"
        snapshot_zip, _ = deterministic_zip(
            experiment_root / "snapshots" / f"vault_snapshot_{baseline.snapshot_id}",
            package_root / f"agent-snapshot-{baseline.snapshot_id}.zip",
        )
        suite_zip, _ = deterministic_zip(
            bundled_controlled_suite_root(),
            package_root / f"agent-suite-{baseline.experiment_id}.zip",
        )
        snapshot_cas = self.artifacts.ingest_file(snapshot_zip)
        suite_cas = self.artifacts.ingest_file(suite_zip)
        index_cas = self.artifacts.ingest_file(experiment_root / "knowledge.sqlite3")
        self.record_product_item(
            record_id=baseline.snapshot_id, category="snapshot",
            title="Snapshot sintético de benchmark", status="COMPLETE",
            artifact_sha256=baseline.snapshot_hash,
            summary={"benchmark_only": True, "suite_fingerprint": baseline.suite.fingerprint},
        )
        self.repository.record_artifact_location(
            record_id=baseline.snapshot_id, artifact_kind="vault_snapshot",
            local_path=experiment_root / "snapshots" / f"vault_snapshot_{baseline.snapshot_id}",
            artifact_sha256=baseline.snapshot_hash,
        )
        request = AgentExperimentRequest(
            experiment_id=str(uuid.uuid4()), strategy_id=strategy_id,
            query="controlled-suite", snapshot_hash=baseline.snapshot_hash,
            retrieval_artifact_sha256=baseline.report_sha256,
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
            record_id=job.job_id, category="experiment", title=f"{strategy_id} · AI Broker + RAG",
            status="EXPERIMENT_QUEUED", artifact_sha256=job.fingerprint(),
            summary={
                "job_id": job.job_id, "strategy_id": strategy_id,
                "suite_fingerprint": baseline.suite.fingerprint,
                "snapshot_hash": baseline.snapshot_hash,
                "case_ids": [case["case_id"] for case in baseline.suite.cases],
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
    ) -> dict[str, Any]:
        allowed = {"B0", "B1", "R1", "R2", "R3", "R4", "L1", "F1", "F2"}
        if strategy_id not in allowed:
            raise ValueError("unknown strategy suite id")
        broker_check = self.repository.product_record(broker_check_id)
        if broker_check is None or broker_check["status"] != "CAPABILITIES_SATISFIED" or broker_check["summary"].get("phase") != "retrieval":
            raise ValueError("strategy suite requires a satisfied read-only Broker retrieval report")
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
        if strategy_id in {"F1", "F2"}:
            training = self.repository.product_record(training_job_id or "")
            if training is None or training["status"] != "TRAINING_SUCCEEDED":
                raise ValueError("F1/F2 requires a successful Local AI Lab training result")
        configuration = {
            "strategy_id": strategy_id,
            "target_model": target_model,
            "embedding_model": embedding_model,
            "embedding_model_fingerprint": embedding_model_fingerprint,
            "device": device,
            "training_job_id": training_job_id,
            "k": k,
        }
        baseline = run_controlled_lexical_benchmark(self.repository.path.parent / "experiments", k=k)
        experiment_root = baseline.report_path.parent
        package_root = self.repository.path.parent / "packages"
        snapshot_path = experiment_root / "snapshots" / f"vault_snapshot_{baseline.snapshot_id}"
        snapshot_zip, _ = deterministic_zip(snapshot_path, package_root / f"strategy-snapshot-{baseline.snapshot_id}.zip")
        suite_zip, _ = deterministic_zip(bundled_controlled_suite_root(), package_root / f"strategy-suite-{baseline.experiment_id}.zip")
        snapshot_cas = self.artifacts.ingest_file(snapshot_zip)
        suite_cas = self.artifacts.ingest_file(suite_zip)
        index_cas = self.artifacts.ingest_file(experiment_root / "knowledge.sqlite3")
        self.record_product_item(
            record_id=baseline.snapshot_id, category="snapshot",
            title="Snapshot sintético de benchmark", status="COMPLETE",
            artifact_sha256=baseline.snapshot_hash,
            summary={"benchmark_only": True, "suite_fingerprint": baseline.suite.fingerprint},
        )
        self.repository.record_artifact_location(
            record_id=baseline.snapshot_id, artifact_kind="vault_snapshot",
            local_path=snapshot_path, artifact_sha256=baseline.snapshot_hash,
        )
        job = JobSpec(
            kind="strategy.suite.v1",
            payload={
                "strategy_id": strategy_id, "broker_endpoint": broker_endpoint,
                "target_model": target_model, "embedding_model": embedding_model,
                "embedding_model_fingerprint": embedding_model_fingerprint,
                "device": device, "k": k, "correlation_id": str(uuid.uuid4()),
                "input_artifacts": [
                    {"sha256": snapshot_cas["sha256"], "mount_as": "resolved_snapshot", "archive": "zip"},
                    {"sha256": suite_cas["sha256"], "mount_as": "resolved_suite", "archive": "zip"},
                    {"sha256": index_cas["sha256"], "mount_as": "resolved_index"},
                ],
                "output_mounts": ["report_dir"],
                "collect_outputs": [{"result_key": "report_dir", "kind": "strategy_suite_report"}],
            },
            requirements={"node_ids": [node_id]},
        )
        submitted = self.submit_job(job, idempotency_key)
        self.record_product_item(
            record_id=job.job_id, category="experiment", title=f"{strategy_id} · suite controlada",
            status="EXPERIMENT_QUEUED", artifact_sha256=job.fingerprint(),
            summary={
                "job_id": job.job_id, "strategy_id": strategy_id,
                "suite_fingerprint": baseline.suite.fingerprint,
                "snapshot_hash": baseline.snapshot_hash,
                "case_ids": [case["case_id"] for case in baseline.suite.cases],
                "node_id": node_id, "target_model": target_model,
                "embedding_model": embedding_model,
                "embedding_model_fingerprint": embedding_model_fingerprint,
                "device": device, "k": k,
                "configuration_label": (
                    f"{strategy_id} · {embedding_model or target_model['model']} · k={k}"
                ),
                "configuration_fingerprint": sha256_json(configuration),
                "training_job_id": training_job_id, "privacy": "local_only",
                "formal_status": "unverified", "state": submitted["state"],
            },
        )
        return self.repository.product_record(job.job_id)  # type: ignore[return-value]
