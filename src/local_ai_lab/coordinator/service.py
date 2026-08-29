from __future__ import annotations

import json
import hashlib
import threading
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable

from local_ai_lab.artifacts.store import ArtifactStore
from local_ai_lab.artifacts.archive import deterministic_zip
from local_ai_lab.benchmark.controlled import ControlledCorpusSuite
from local_ai_lab.benchmark.real import RealBenchmarkSuite
from local_ai_lab.benchmark.orchestration import bundled_controlled_suite_root, run_controlled_lexical_benchmark
from local_ai_lab.coordinator.repository import CoordinatorConflict, CoordinatorRepository
from local_ai_lab.domain.common import canonical_json, sha256_json, sha256_text, utc_timestamp
from local_ai_lab.domain.jobs import JobSpec, JobState, LeaseGrant
from local_ai_lab.dataset.factory import DatasetFactory, DatasetVerifier
from local_ai_lab.evaluation.response_verifier import ResearchResponseVerifier
from local_ai_lab.feedback.repository import FeedbackRepository
from local_ai_lab.exporting.planner import ExportJobPlanner
from local_ai_lab.knowledge_index.projection import KnowledgeIndexBuilder
from local_ai_lab.knowledge_index.snapshot import SnapshotBuilder, SnapshotVerifier
from local_ai_lab.knowledge_index.vault import ReadOnlyVaultAdapter, discover_vaults
from local_ai_lab.training.contracts import TrainingContractReport
from local_ai_lab.training.plan import FineTuningProposal, TrainingPlanBuilder
from local_ai_lab.training.distillation import DistillationPlanBuilder, DistillationProposal
from local_ai_lab.training.resolver import HardwareResolution
from local_ai_lab.model_drift.integration import (
    ExternalTreatmentRef,
    FormalEvaluationPlan,
    ModelDriftIntegration,
)
from local_ai_lab.broker.compatibility import BrokerCompatibilityChecker
from local_ai_lab.experiments.comparison import StrategyRun
from local_ai_lab.experiments.selector import SelectionConstraints, StrategySelector
from local_ai_lab.agents.planner import AgentExperimentPlanner, AgentExperimentRequest, BrokerAgentCapabilities
from decimal import Decimal


class AuthenticationError(PermissionError):
    pass


class IdempotencyConflict(CoordinatorConflict):
    pass


class CoordinatorService:
    protocol_version = 1

    def __init__(self, database_path: Path) -> None:
        self.repository = CoordinatorRepository(database_path)
        self.feedback = FeedbackRepository(database_path)
        self.artifacts = ArtifactStore(database_path.parent / "artifacts")
        self._idempotency_lock = threading.RLock()

    def create_pairing_code(self, valid_seconds: int = 300) -> str:
        return self.repository.create_pairing_code(valid_seconds)

    def overview(self) -> dict[str, Any]:
        return self.repository.overview()

    def record_phase_evidence(self, **evidence: Any) -> dict[str, Any]:
        return self.repository.record_phase_evidence(**evidence)

    def product_workspace(self) -> dict[str, Any]:
        return self.repository.product_workspace()

    def jobs(self) -> list[dict[str, Any]]:
        return self.repository.jobs_view()

    def record_product_item(self, **item: Any) -> dict[str, Any]:
        return self.repository.record_product_item(**item)

    def reviews(self) -> list[dict[str, Any]]:
        return self.feedback.list_reviews()

    def save_review_correction(
        self, *, review_id: str, actor: str, corrected_response: dict[str, Any]
    ) -> dict[str, Any]:
        review = self.feedback.get(review_id)
        snapshot = self.repository.artifact_location(
            review["snapshot_id"], expected_kind="vault_snapshot"
        )
        return self.feedback.save_correction(
            review_id, actor=actor, corrected_response=corrected_response,
            verifier=ResearchResponseVerifier(snapshot),
        )

    def transition_review(self, *, review_id: str, to_state: str, actor: str) -> dict[str, Any]:
        return self.feedback.transition_review(review_id, to_state=to_state, actor=actor)

    def transition_training_candidate(
        self, *, review_id: str, to_state: str, actor: str
    ) -> dict[str, Any]:
        return self.feedback.transition_training(review_id, to_state=to_state, actor=actor)

    def discover_vaults(self, *, allowed_root: Path) -> list[str]:
        return discover_vaults(allowed_root)

    def create_vault_snapshot(self, *, allowed_root: Path, vault_name: str) -> dict[str, Any]:
        if not vault_name.strip() or vault_name in {".", ".."} or any(char in vault_name for char in ("/", "\\")):
            raise ValueError("vault name must be a direct child name")
        vault = allowed_root / vault_name
        adapter = ReadOnlyVaultAdapter(allowed_root=allowed_root, vault_root=vault)
        result = SnapshotBuilder().build(adapter, self.repository.path.parent / "snapshots")
        manifest = SnapshotVerifier().verify(result.path)["manifest"]
        self.record_product_item(
            record_id=result.snapshot_id, category="snapshot", title=f"Snapshot {vault_name}",
            status=result.state, artifact_sha256=result.global_hash,
            summary={
                "vault": vault_name, "notes": manifest["counts"]["notes"],
                "chunks": manifest["counts"]["chunks"], "holes": manifest["counts"]["holes"],
                "read_only": True,
            },
        )
        self.repository.record_artifact_location(
            record_id=result.snapshot_id, artifact_kind="vault_snapshot",
            local_path=result.path, artifact_sha256=result.global_hash,
        )
        return next(
            record for record in self.product_workspace()["knowledge"]
            if record["record_id"] == result.snapshot_id
        )

    def create_knowledge_index(
        self, *, snapshot_id: str, previous_index_id: str | None = None
    ) -> dict[str, Any]:
        snapshot = self.repository.artifact_location(snapshot_id, expected_kind="vault_snapshot")
        previous = (
            self.repository.artifact_location(previous_index_id, expected_kind="knowledge_index")
            if previous_index_id else None
        )
        index_id = str(uuid.uuid4())
        target = self.repository.path.parent / "indexes" / f"knowledge-{index_id}.sqlite3"
        built = KnowledgeIndexBuilder().build(snapshot, target, previous_database=previous)
        digest = hashlib.sha256(built.read_bytes()).hexdigest()
        verified = SnapshotVerifier().verify(snapshot)
        self.record_product_item(
            record_id=index_id, category="index", title="Índice de conocimiento",
            status="READY", artifact_sha256=digest,
            summary={
                "snapshot_id": snapshot_id,
                "snapshot_hash": verified["manifest"]["global_hash"],
                "engine": "SQLite FTS5", "regenerable": True,
                "incremental": previous_index_id is not None,
            },
        )
        self.repository.record_artifact_location(
            record_id=index_id, artifact_kind="knowledge_index", local_path=built,
            artifact_sha256=digest,
        )
        return next(
            record for record in self.product_workspace()["knowledge"]
            if record["record_id"] == index_id
        )

    def run_controlled_retrieval_benchmark(self, *, k: int = 5) -> dict[str, Any]:
        artifact = run_controlled_lexical_benchmark(
            self.repository.path.parent / "experiments", k=k
        )
        aggregate = artifact.report["aggregate"]
        review_status = artifact.suite.review_status
        status = "LOCAL_VERIFIED" if review_status == "approved" else "PENDING_HUMAN_REVIEW"
        self.record_product_item(
            record_id=artifact.experiment_id,
            category="experiment",
            title="R1 · corpus controlado",
            status=status,
            artifact_sha256=artifact.report_sha256,
            summary={
                "strategy_id": artifact.report["strategy_id"],
                "suite_fingerprint": artifact.suite.fingerprint,
                "snapshot_hash": artifact.snapshot_hash,
                "human_review": review_status,
                "k": k,
                "recall_at_k": aggregate["recall_at_k"],
                "precision_at_k": aggregate["precision_at_k"],
                "mrr": aggregate["reciprocal_rank"],
                "ndcg_at_k": aggregate["ndcg_at_k"],
                "source_coverage": aggregate["source_coverage"],
                "redundancy": aggregate["redundancy"],
                "latency_ms": artifact.report["latency_ms"],
                "case_ids": [case["case_id"] for case in artifact.suite.cases],
                "formal_status": "unverified",
                "cost": "local / not metered",
                "privacy": "local_only",
            },
        )
        self.repository.record_artifact_location(
            record_id=artifact.experiment_id,
            artifact_kind="retrieval_benchmark_report",
            local_path=artifact.report_path,
            artifact_sha256=artifact.report_sha256,
        )
        return next(
            record for record in self.product_workspace()["experiments"]
            if record["record_id"] == artifact.experiment_id
        )

    def create_controlled_semantic_benchmark_job(
        self,
        *,
        strategy_id: str,
        node_id: str,
        embedding_model: str,
        embedding_model_fingerprint: str,
        device: str,
        k: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if strategy_id not in {"R2", "R3", "R4"}:
            raise ValueError("semantic benchmark strategy must be R2, R3 or R4")
        if self.repository.node_record(node_id) is None:
            raise ValueError("semantic benchmark requires a registered node")
        if not embedding_model.strip() or len(embedding_model_fingerprint) != 64:
            raise ValueError("semantic benchmark requires an exact local model and SHA-256 fingerprint")
        configuration = {
            "strategy_id": strategy_id,
            "embedding_model": embedding_model,
            "embedding_model_fingerprint": embedding_model_fingerprint,
            "device": device,
            "k": k,
        }
        baseline = run_controlled_lexical_benchmark(
            self.repository.path.parent / "experiments", k=k
        )
        experiment_root = baseline.report_path.parent
        snapshot_root = experiment_root / "snapshots" / f"vault_snapshot_{baseline.snapshot_id}"
        package_root = self.repository.path.parent / "packages"
        snapshot_zip, _ = deterministic_zip(
            snapshot_root, package_root / f"snapshot-{baseline.snapshot_id}.zip"
        )
        suite_zip, _ = deterministic_zip(
            bundled_controlled_suite_root(), package_root / f"suite-{baseline.experiment_id}.zip"
        )
        snapshot_cas = self.artifacts.ingest_file(snapshot_zip)
        suite_cas = self.artifacts.ingest_file(suite_zip)
        index_cas = self.artifacts.ingest_file(experiment_root / "knowledge.sqlite3")
        job = JobSpec(
            kind="retrieval.benchmark.v1",
            payload={
                "strategy_id": strategy_id,
                "embedding_model": embedding_model,
                "embedding_model_fingerprint": embedding_model_fingerprint,
                "device": device,
                "k": k,
                "input_artifacts": [
                    {"sha256": snapshot_cas["sha256"], "mount_as": "resolved_snapshot", "archive": "zip"},
                    {"sha256": suite_cas["sha256"], "mount_as": "resolved_suite", "archive": "zip"},
                    {"sha256": index_cas["sha256"], "mount_as": "resolved_index"},
                ],
                "output_mounts": ["report_dir"],
                "collect_outputs": [{"result_key": "report_dir", "kind": "retrieval_benchmark_report"}],
            },
            requirements={"node_ids": [node_id]},
        )
        submitted = self.submit_job(job, idempotency_key)
        self.record_product_item(
            record_id=job.job_id, category="experiment",
            title=f"{strategy_id} · corpus controlado", status="EXPERIMENT_QUEUED",
            artifact_sha256=job.fingerprint(),
            summary={
                "job_id": job.job_id, "strategy_id": strategy_id,
                "suite_fingerprint": baseline.suite.fingerprint,
                "snapshot_hash": baseline.snapshot_hash, "human_review": baseline.suite.review_status,
                "node_id": node_id, "embedding_model": embedding_model,
                "embedding_model_fingerprint": embedding_model_fingerprint,
                "device": device,
                "configuration_label": f"{strategy_id} · {embedding_model} · k={k}",
                "configuration_fingerprint": sha256_json(configuration),
                "k": k, "state": submitted["state"], "formal_status": "unverified",
                "case_ids": [case["case_id"] for case in baseline.suite.cases],
                "cost": "local / not metered", "privacy": "local_only",
            },
        )
        return self.repository.product_record(job.job_id)  # type: ignore[return-value]

    def register_real_benchmark(self, *, definition: dict[str, Any]) -> dict[str, Any]:
        RealBenchmarkSuite._validate(definition, require_approval=True)
        snapshot = next(
            (
                item for item in self.product_workspace()["knowledge"]
                if item["category"] == "snapshot"
                and item["artifact_sha256"] == definition["snapshot_hash"]
                and item["status"] == "COMPLETE"
            ),
            None,
        )
        if snapshot is None:
            raise ValueError("real benchmark must reference a registered COMPLETE snapshot")
        benchmark_id = str(uuid.uuid4())
        path = self.repository.path.parent / "benchmarks" / "real" / f"{benchmark_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(definition) + "\n", encoding="utf-8", newline="\n")
        suite = RealBenchmarkSuite.load(path, require_approval=True)
        self.record_product_item(
            record_id=benchmark_id, category="benchmark", title="Benchmark real multifuente",
            status="HUMAN_APPROVED", artifact_sha256=suite.fingerprint,
            summary={
                "suite_fingerprint": suite.fingerprint,
                "snapshot_hash": definition["snapshot_hash"],
                "cases": len(definition["cases"]),
                "reviewer": definition["human_review"]["reviewer"],
                "purpose": "external_validity", "training_eligible": False,
            },
        )
        self.repository.record_artifact_location(
            record_id=benchmark_id, artifact_kind="real_benchmark_suite",
            local_path=path, artifact_sha256=suite.fingerprint,
        )
        return self.repository.product_record(benchmark_id)  # type: ignore[return-value]

    def run_model_drift_comparison(
        self,
        *,
        r3_experiment_id: str,
        r4_experiment_id: str,
        executable: str,
        working_directory: str,
        confirmed: bool,
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("formal external evaluation requires explicit user confirmation")
        r3 = self.repository.product_record(r3_experiment_id)
        r4 = self.repository.product_record(r4_experiment_id)
        if r3 is None or r4 is None:
            raise ValueError("Model Drift comparison requires two registered experiments")
        if r3["status"] != "EXPERIMENT_SUCCEEDED" or r4["status"] != "EXPERIMENT_SUCCEEDED":
            raise ValueError("Model Drift comparison requires completed R3 and R4 runs")
        if r3["summary"].get("strategy_id") != "R3" or r4["summary"].get("strategy_id") != "R4":
            raise ValueError("formal RAG comparison must use R3 as baseline and R4 as candidate")
        for key in ("suite_fingerprint", "snapshot_hash"):
            if r3["summary"].get(key) != r4["summary"].get(key):
                raise ValueError(f"R3 and R4 are not comparable: {key} differs")
        for key in ("embedding_model_fingerprint", "k"):
            if not r3["summary"].get(key) or r3["summary"].get(key) != r4["summary"].get(key):
                raise ValueError(
                    f"R3 and R4 are not an isolated graph comparison: {key} differs or is missing"
                )
        if r3["summary"].get("target_model") != r4["summary"].get("target_model"):
            raise ValueError("R3 and R4 are not an isolated graph comparison: target_model differs")
        integration = ModelDriftIntegration(
            command_prefix=(str(Path(executable).resolve(strict=True)),),
            working_directory=Path(working_directory),
        )
        integration.require_rag_treatments(integration.inspect())
        def external_artifact(record_id: str) -> tuple[Path, str]:
            for kind in ("strategy_suite_report", "retrieval_benchmark_report"):
                try:
                    return self.repository.artifact_location(record_id, expected_kind=kind), kind
                except KeyError:
                    continue
            raise ValueError("R3/R4 experiment has no supported external-treatment artifact")

        r3_artifact, r3_kind = external_artifact(r3_experiment_id)
        r4_artifact, r4_kind = external_artifact(r4_experiment_id)
        if r3_kind != r4_kind:
            raise ValueError("R3 and R4 must use the same treatment artifact contract")
        comparison_id = str(uuid.uuid4())
        root = self.repository.path.parent / "model-drift" / comparison_id
        plan = FormalEvaluationPlan(
            experiment_id=comparison_id, correlation_id=str(uuid.uuid4()),
            suite_fingerprint=r3["summary"]["suite_fingerprint"],
            snapshot_hash=r3["summary"]["snapshot_hash"],
            baseline=ExternalTreatmentRef(
                experiment_id=r3_experiment_id,
                strategy_id="R3",
                artifact_path=str(r3_artifact),
                artifact_sha256=r3["artifact_sha256"],
                artifact_kind=r3_kind,
            ),
            candidate=ExternalTreatmentRef(
                experiment_id=r4_experiment_id,
                strategy_id="R4",
                artifact_path=str(r4_artifact),
                artifact_sha256=r4["artifact_sha256"],
                artifact_kind=r4_kind,
            ),
        )
        plan_path = integration.write_plan(plan, root / "plan.json")
        report_path = root / "report.html"
        integration.execute_external_treatments(plan=plan_path, report=report_path)
        report_sha256 = hashlib.sha256(report_path.read_bytes()).hexdigest()
        self.record_product_item(
            record_id=comparison_id, category="comparison", title="Model Drift · R3 vs R4",
            status="MODEL_DRIFT_VERIFIED", artifact_sha256=report_sha256,
            summary={
                "baseline_experiment_id": r3_experiment_id,
                "candidate_experiment_id": r4_experiment_id,
                "suite_fingerprint": plan.suite_fingerprint,
                "snapshot_hash": plan.snapshot_hash,
                "measurement_mode": "external_deterministic_treatments",
                "formal_status": "model_drift_verified",
                "local_rag_metrics_separate": True,
                "embedding_model": r3["summary"].get("embedding_model"),
                "embedding_model_fingerprint": r3["summary"]["embedding_model_fingerprint"],
                "k": r3["summary"]["k"],
                "case_count": len(r3["summary"].get("case_ids", [])),
                "claim_scope": "configuration_specific",
                "superiority_established": False,
                "interpretation": (
                    "R3 and R4 were compared under one exact configuration; "
                    "this does not establish general R4 superiority"
                ),
            },
        )
        self.repository.record_artifact_location(
            record_id=comparison_id, artifact_kind="model_drift_report",
            local_path=report_path, artifact_sha256=report_sha256,
        )
        return self.repository.product_record(comparison_id)  # type: ignore[return-value]

    def check_broker_compatibility(
        self, *, endpoint: str, phase: str, token: str | None
    ) -> dict[str, Any]:
        report = BrokerCompatibilityChecker().check(
            endpoint=endpoint, phase=phase, token=token
        )
        payload = report.payload()
        path = self.repository.path.parent / "broker-checks" / f"{report.report_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.to_json(), encoding="utf-8", newline="\n")
        status = {
            "satisfied": "CAPABILITIES_SATISFIED",
            "degraded": "CAPABILITIES_DEGRADED",
            "unsatisfied": "UPGRADE_REQUIRED",
            "unknown": "CAPABILITIES_UNKNOWN",
        }[report.status]
        self.record_product_item(
            record_id=report.report_id, category="experiment",
            title=f"AI Broker · {phase}", status=status,
            artifact_sha256=report.content_sha256,
            summary={
                "phase": phase, "endpoint": report.endpoint,
                "observed_contract": report.observed_contract,
                "required_contract": report.required_contract,
                "missing_capabilities": report.missing_capabilities,
                "missing_strategies": report.missing_strategies,
                "health_observed": report.health_observed,
                "capabilities_observed": report.capabilities_observed,
                "upgrade_required": report.upgrade_required,
                "recommendation": report.recommendation,
                "access_mode": "read_only_get",
            },
        )
        self.repository.record_artifact_location(
            record_id=report.report_id, artifact_kind="broker_compatibility_report",
            local_path=path, artifact_sha256=report.content_sha256,
        )
        return self.repository.product_record(report.report_id)  # type: ignore[return-value]

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

    def build_approved_feedback_dataset(
        self, *, name: str, split_seed: str, actor: str,
    ) -> dict[str, Any]:
        suite = ControlledCorpusSuite.load(
            bundled_controlled_suite_root(), require_human_approval=False
        )
        result = DatasetFactory().build(
            self.feedback,
            self.repository.path.parent / "datasets",
            name=name,
            benchmark_case_ids=[case["case_id"] for case in suite.cases],
            benchmark_fingerprints=[suite.fingerprint],
            split_seed=split_seed,
        )
        manifest = DatasetVerifier().verify(result.path)
        archive_path, archive_sha256 = deterministic_zip(
            result.path,
            self.repository.path.parent / "packages" / f"dataset-{result.dataset_id}.zip",
        )
        committed = self.artifacts.ingest_file(archive_path)
        if committed["sha256"] != archive_sha256:
            raise RuntimeError("dataset package CAS verification failed")
        self.record_product_item(
            record_id=result.dataset_id,
            category="dataset",
            title=name,
            status="READY_FOR_TRAINING",
            artifact_sha256=result.fingerprint,
            summary={
                "fingerprint": result.fingerprint,
                "included": manifest["counts"]["included"],
                "excluded": manifest["counts"]["excluded"],
                "train": manifest["counts"]["train"],
                "validation": manifest["counts"]["validation"],
                "test": manifest["counts"]["test"],
                "benchmark_fingerprints": manifest["benchmark_fingerprints"],
                "cas_sha256": archive_sha256,
                "cas_size": committed["size"],
                "privacy": "local_only",
            },
        )
        self.repository.record_artifact_location(
            record_id=result.dataset_id,
            artifact_kind="training_dataset",
            local_path=result.path,
            artifact_sha256=result.fingerprint,
        )
        for review_id in result.exported_review_ids:
            self.feedback.transition_training(review_id, to_state="exported", actor=actor)
        return next(
            record for record in self.product_workspace()["datasets"]
            if record["record_id"] == result.dataset_id
        )

    def create_training_preflight_job(
        self,
        *,
        dataset_id: str,
        node_id: str,
        base_model: str,
        dtype: str,
        seed: int,
        max_length: int,
        lora_config: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        dataset = self.repository.product_record(dataset_id)
        if dataset is None or dataset["category"] != "dataset" or dataset["status"] != "READY_FOR_TRAINING":
            raise ValueError("training preflight requires a ready dataset")
        if self.repository.node_record(node_id) is None:
            raise ValueError("training preflight requires a registered node")
        if dtype not in {"bf16", "fp16"} or not base_model.strip():
            raise ValueError("preflight requires an explicit local model and dtype")
        if not isinstance(lora_config.get("rank"), int) or not 1 <= lora_config["rank"] <= 1024:
            raise ValueError("LoRA rank must be an integer between 1 and 1024")
        cas_sha256 = dataset["summary"].get("cas_sha256")
        if not isinstance(cas_sha256, str) or not self.artifacts.verify(cas_sha256):
            raise ValueError("dataset CAS package is missing or corrupt")
        job = JobSpec(
            kind="training.preflight.v1",
            payload={
                "dataset_fingerprint": dataset["artifact_sha256"],
                "base_model": base_model,
                "dtype": dtype,
                "seed": seed,
                "max_length": max_length,
                "lora_config": lora_config,
                "input_artifacts": [{
                    "sha256": cas_sha256, "mount_as": "resolved_dataset_path", "archive": "zip",
                }],
                "output_mounts": ["preflight_output"],
                "collect_outputs": [{"result_key": "preflight_output", "kind": "training_preflight"}],
            },
            requirements={"node_ids": [node_id]},
        )
        submitted = self.submit_job(job, idempotency_key)
        self.record_product_item(
            record_id=job.job_id, category="training", title=f"Preflight · {base_model}",
            status="PREFLIGHT_QUEUED", artifact_sha256=job.fingerprint(),
            summary={
                "job_id": job.job_id, "kind": job.kind, "dataset_id": dataset_id,
                "dataset_fingerprint": dataset["artifact_sha256"], "node_id": node_id,
                "base_model": base_model, "dtype": dtype, "state": submitted["state"],
            },
        )
        return self.repository.product_record(job.job_id)  # type: ignore[return-value]

    def create_training_job(
        self,
        *,
        dataset_id: str,
        preflight_job_id: str,
        baseline_experiment_id: str,
        objective: str,
        hypothesis: str,
        approved_by: str,
        epochs: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        dataset = self.repository.product_record(dataset_id)
        baseline = self.repository.product_record(baseline_experiment_id)
        preflight_record = self.repository.product_record(preflight_job_id)
        preflight_job = self.repository.job(preflight_job_id)
        if dataset is None or dataset["category"] != "dataset":
            raise ValueError("training requires a registered dataset")
        if baseline is None or baseline["category"] not in {"experiment", "comparison"}:
            raise ValueError("training requires baseline evidence")
        if preflight_record is None or preflight_record["status"] != "PREFLIGHT_PASSED":
            raise ValueError("training requires a passed preflight")
        if preflight_job is None or preflight_job["state"] != JobState.SUCCEEDED:
            raise ValueError("preflight job has no successful result")
        result = json.loads(preflight_job["result_json"])
        if result.get("dataset_fingerprint") != dataset["artifact_sha256"]:
            raise ValueError("preflight was executed with a different dataset")
        checks = result.get("checks", {})
        contract_payload = result.get("contract", {})
        if not isinstance(checks, dict) or not all(checks.values()) or contract_payload.get("passed") is not True:
            raise ValueError("preflight evidence is incomplete")
        contract = TrainingContractReport(
            c1_assistant_only_loss=bool(contract_payload["c1_assistant_only_loss"]),
            c2_supervised_eos=bool(contract_payload["c2_supervised_eos"]),
            c3_same_chat_template=bool(contract_payload["c3_same_chat_template"]),
            c4_assistant_not_truncated=bool(contract_payload["c4_assistant_not_truncated"]),
            c5_padding_outside_loss=bool(contract_payload["c5_padding_outside_loss"]),
            c6_seed_and_nondeterminism_recorded=bool(contract_payload["c6_seed_and_nondeterminism_recorded"]),
            errors=tuple(contract_payload.get("errors", [])),
        )
        hardware = HardwareResolution(
            "selected", preflight_job["assigned_node_id"], result["backend"], result["dtype"], ()
        )
        proposal = FineTuningProposal(
            proposal_id=str(uuid.uuid4()), objective=objective, hypothesis=hypothesis,
            baseline_evidence_sha256=baseline["artifact_sha256"],
            dataset_fingerprint=dataset["artifact_sha256"], contains_mutable_facts=False,
            approved_by=approved_by,
        )
        preflight_spec = json.loads(preflight_job["spec_json"])
        planned = TrainingPlanBuilder().build(
            proposal, contract=contract, hardware=hardware, preflight=checks,
            base_model=preflight_spec["payload"]["base_model"],
            chat_template_fingerprint=result["chat_template_fingerprint"],
            seed=int(preflight_spec["payload"]["seed"]),
            lora_config=preflight_spec["payload"]["lora_config"],
        )
        cas_sha256 = dataset["summary"]["cas_sha256"]
        payload = {
            **planned.payload,
            "epochs": epochs,
            "input_artifacts": [{
                "sha256": cas_sha256, "mount_as": "resolved_dataset_path", "archive": "zip",
            }],
            "output_mounts": ["output_dir"],
            "collect_outputs": [{"result_key": "output_dir", "kind": "training_result"}],
        }
        job = replace(planned, payload=payload)
        submitted = self.submit_job(job, idempotency_key)
        self.record_product_item(
            record_id=job.job_id, category="training", title=f"LoRA · {planned.payload['base_model']}",
            status="TRAINING_QUEUED", artifact_sha256=job.fingerprint(),
            summary={
                "job_id": job.job_id, "kind": job.kind, "dataset_id": dataset_id,
                "preflight_job_id": preflight_job_id, "baseline_experiment_id": baseline_experiment_id,
                "node_id": hardware.node_id, "base_model": planned.payload["base_model"],
                "dtype": hardware.dtype, "objective": objective, "approved_by": approved_by,
                "state": submitted["state"],
            },
        )
        return self.repository.product_record(job.job_id)  # type: ignore[return-value]

    def create_distillation_job(
        self,
        *,
        dataset_id: str,
        preflight_job_id: str,
        baseline_experiment_id: str,
        teacher_model: str,
        teacher_model_fingerprint: str | None,
        student_model: str,
        student_model_fingerprint: str,
        teacher_license: str,
        student_license: str,
        teacher_outputs_training_allowed: bool,
        student_finetuning_allowed: bool,
        objective: str,
        hypothesis: str,
        approved_by: str,
        epochs: float,
        generation_config: dict[str, Any],
        idempotency_key: str,
        teacher_source: str = "local",
        broker_check_id: str | None = None,
        teacher_broker_endpoint: str | None = None,
        teacher_target_model: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        dataset = self.repository.product_record(dataset_id)
        baseline = self.repository.product_record(baseline_experiment_id)
        preflight_record = self.repository.product_record(preflight_job_id)
        preflight_job = self.repository.job(preflight_job_id)
        if dataset is None or dataset["category"] != "dataset" or dataset["status"] != "READY_FOR_TRAINING":
            raise ValueError("distillation requires a ready training dataset")
        if baseline is None or baseline["category"] not in {"experiment", "comparison"}:
            raise ValueError("distillation requires baseline evidence")
        if preflight_record is None or preflight_record["status"] != "PREFLIGHT_PASSED":
            raise ValueError("distillation requires a passed student preflight")
        if preflight_job is None or preflight_job["state"] != JobState.SUCCEEDED:
            raise ValueError("student preflight job has no successful result")
        result = json.loads(preflight_job["result_json"])
        if result.get("dataset_fingerprint") != dataset["artifact_sha256"]:
            raise ValueError("student preflight used a different dataset")
        checks = result.get("checks", {})
        contract_payload = result.get("contract", {})
        if not isinstance(checks, dict) or not all(checks.values()) or contract_payload.get("passed") is not True:
            raise ValueError("student preflight evidence is incomplete")
        preflight_spec = json.loads(preflight_job["spec_json"])
        if preflight_spec["payload"].get("base_model") != student_model:
            raise ValueError("student model differs from the model tested by preflight")
        broker_capability_fingerprint: str | None = None
        if teacher_source == "broker":
            broker_check = self.repository.product_record(broker_check_id or "")
            if (
                broker_check is None
                or broker_check["status"] != "CAPABILITIES_SATISFIED"
                or broker_check["summary"].get("phase") != "retrieval"
            ):
                raise ValueError(
                    "Broker teacher requires a satisfied exact-model capability report"
                )
            if (
                not teacher_broker_endpoint
                or teacher_target_model is None
                or set(teacher_target_model) != {"provider", "deployment", "model"}
                or any(not value.strip() for value in teacher_target_model.values())
            ):
                raise ValueError("Broker teacher requires endpoint and exact target model")
            observed_endpoint = broker_check["summary"].get("endpoint")
            if not isinstance(observed_endpoint, str) or (
                teacher_broker_endpoint.rstrip("/") != observed_endpoint.rstrip("/")
            ):
                raise ValueError(
                    "Broker teacher endpoint differs from the satisfied capability report"
                )
            if teacher_model != teacher_target_model["model"]:
                raise ValueError("teacher model differs from the exact Broker target")
            broker_capability_fingerprint = broker_check["artifact_sha256"]
            teacher_model_fingerprint = sha256_json(
                {
                    "source": "broker",
                    "target_model": teacher_target_model,
                    "capability_fingerprint": broker_capability_fingerprint,
                }
            )
        elif teacher_source == "local":
            if not isinstance(teacher_model_fingerprint, str) or len(teacher_model_fingerprint) != 64:
                raise ValueError("local teacher requires a SHA-256 model fingerprint")
            if any(
                value is not None
                for value in (broker_check_id, teacher_broker_endpoint, teacher_target_model)
            ):
                raise ValueError("local teacher cannot carry Broker configuration")
        else:
            raise ValueError("teacher source must be local or broker")
        if len(student_model_fingerprint) != 64:
            raise ValueError("student requires a SHA-256 model fingerprint")
        contract = TrainingContractReport(
            c1_assistant_only_loss=bool(contract_payload["c1_assistant_only_loss"]),
            c2_supervised_eos=bool(contract_payload["c2_supervised_eos"]),
            c3_same_chat_template=bool(contract_payload["c3_same_chat_template"]),
            c4_assistant_not_truncated=bool(contract_payload["c4_assistant_not_truncated"]),
            c5_padding_outside_loss=bool(contract_payload["c5_padding_outside_loss"]),
            c6_seed_and_nondeterminism_recorded=bool(contract_payload["c6_seed_and_nondeterminism_recorded"]),
            errors=tuple(contract_payload.get("errors", [])),
        )
        hardware = HardwareResolution(
            "selected", preflight_job["assigned_node_id"], result["backend"], result["dtype"], ()
        )
        proposal = DistillationProposal(
            proposal_id=str(uuid.uuid4()),
            objective=objective,
            hypothesis=hypothesis,
            baseline_evidence_sha256=baseline["artifact_sha256"],
            dataset_fingerprint=dataset["artifact_sha256"],
            teacher_model=teacher_model,
            teacher_model_fingerprint=teacher_model_fingerprint,
            student_model=student_model,
            student_model_fingerprint=student_model_fingerprint,
            teacher_license=teacher_license,
            student_license=student_license,
            teacher_outputs_training_allowed=teacher_outputs_training_allowed,
            student_finetuning_allowed=student_finetuning_allowed,
            teacher_source=teacher_source,
            teacher_broker_endpoint=teacher_broker_endpoint,
            teacher_target_model=teacher_target_model,
            broker_capability_fingerprint=broker_capability_fingerprint,
            approved_by=approved_by,
        )
        planned = DistillationPlanBuilder().build(
            proposal,
            contract=contract,
            hardware=hardware,
            preflight=checks,
            chat_template_fingerprint=result["chat_template_fingerprint"],
            seed=int(preflight_spec["payload"]["seed"]),
            lora_config=preflight_spec["payload"]["lora_config"],
            generation_config=generation_config,
        )
        cas_sha256 = dataset["summary"].get("cas_sha256")
        if not isinstance(cas_sha256, str) or not self.artifacts.verify(cas_sha256):
            raise ValueError("distillation dataset CAS package is missing or corrupt")
        payload = {
            **planned.payload,
            "correlation_id": planned.job_id,
            "epochs": epochs,
            "max_length": int(preflight_spec["payload"].get("max_length", 4096)),
            "input_artifacts": [{
                "sha256": cas_sha256,
                "mount_as": "resolved_dataset_path",
                "archive": "zip",
            }],
            "output_mounts": ["output_dir"],
            "collect_outputs": [{"result_key": "output_dir", "kind": "training_result"}],
        }
        job = replace(
            planned,
            payload=payload,
            requirements={**planned.requirements, "node_ids": [hardware.node_id]},
        )
        submitted = self.submit_job(job, idempotency_key)
        self.record_product_item(
            record_id=job.job_id,
            category="training",
            title=f"Destilación · {teacher_model} → {student_model}",
            status="DISTILLATION_QUEUED",
            artifact_sha256=job.fingerprint(),
            summary={
                "job_id": job.job_id,
                "kind": job.kind,
                "method": "sequence_level_supervision.v1",
                "dataset_id": dataset_id,
                "preflight_job_id": preflight_job_id,
                "baseline_experiment_id": baseline_experiment_id,
                "node_id": hardware.node_id,
                "teacher_model": teacher_model,
                "teacher_model_fingerprint": teacher_model_fingerprint,
                "teacher_source": teacher_source,
                "broker_check_id": broker_check_id,
                "teacher_target_model": teacher_target_model,
                "student_model": student_model,
                "student_model_fingerprint": student_model_fingerprint,
                "objective": objective,
                "approved_by": approved_by,
                "state": submitted["state"],
            },
        )
        return self.repository.product_record(job.job_id)  # type: ignore[return-value]

    def create_export_job(
        self,
        *,
        training_job_id: str,
        node_id: str,
        formats: list[str],
        license_id: str,
        serving: dict[str, Any],
        llama_cpp_converter: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        training_record = self.repository.product_record(training_job_id)
        training_job = self.repository.job(training_job_id)
        node = self.repository.node_record(node_id)
        if training_record is None or training_record["category"] != "training":
            raise ValueError("export requires a registered training result")
        if training_record["status"] not in {"TRAINING_SUCCEEDED", "DISTILLATION_SUCCEEDED"}:
            raise ValueError("export requires a successful training result")
        if training_job is None or training_job["state"] != JobState.SUCCEEDED:
            raise ValueError("training job has no successful portable result")
        if node is None:
            raise ValueError("export requires a registered node")
        if not license_id.strip():
            raise ValueError("export requires an explicit artifact license")
        result = json.loads(training_job["result_json"])
        manifest_sha256 = result.get("manifest_sha256")
        manifest_file_sha256 = result.get("manifest_file_sha256")
        artifacts = result.get("artifacts", [])
        training_artifact = next(
            (
                item for item in artifacts
                if isinstance(item, dict) and item.get("kind") == "training_result"
                and isinstance(item.get("sha256"), str)
            ),
            None,
        )
        if not isinstance(manifest_sha256, str) or len(manifest_sha256) != 64:
            raise ValueError("training result lacks its verified manifest fingerprint")
        if not isinstance(manifest_file_sha256, str) or len(manifest_file_sha256) != 64:
            raise ValueError("training result lacks its manifest file hash")
        if training_artifact is None or not self.artifacts.verify(training_artifact["sha256"]):
            raise ValueError("training result CAS package is missing or corrupt")
        capabilities = json.loads(node["capabilities_json"]) if node.get("capabilities_json") else {}
        tested_capabilities = {
            item["kind"]
            for item in capabilities.get("workloads", [])
            if isinstance(item, dict)
            and isinstance(item.get("kind"), str)
            and item.get("status") in {"tested", "benchmarked"}
        }
        planned = ExportJobPlanner().plan(
            source_manifest_sha256=manifest_sha256,
            source_artifact_reference=f"sha256:{training_artifact['sha256']}",
            formats=formats,
            node_id=node_id,
            tested_capabilities=tested_capabilities,
        )
        training_spec = json.loads(training_job["spec_json"])
        if "gguf" in formats and not llama_cpp_converter:
            raise ValueError("GGUF export requires a tested local llama.cpp converter path")
        payload = {
            **planned.payload,
            "source_manifest_file_sha256": manifest_file_sha256,
            "source_training_manifest_sha256": manifest_sha256,
            "license_id": license_id,
            "serving": serving,
            "base_model": training_spec["payload"].get("base_model") or training_spec["payload"].get("student_model"),
            "input_artifacts": [{
                "sha256": training_artifact["sha256"],
                "mount_as": "resolved_training_output",
                "archive": "zip",
            }],
            "output_mounts": ["output_dir"],
            "collect_outputs": [{"result_key": "package_path", "kind": "export_package"}],
        }
        if llama_cpp_converter:
            payload["llama_cpp_converter"] = llama_cpp_converter
        job = replace(planned, payload=payload)
        submitted = self.submit_job(job, idempotency_key)
        self.record_product_item(
            record_id=job.job_id,
            category="export",
            title=f"Export · {', '.join(formats)}",
            status="EXPORT_QUEUED",
            artifact_sha256=job.fingerprint(),
            summary={
                "job_id": job.job_id,
                "kind": job.kind,
                "training_job_id": training_job_id,
                "node_id": node_id,
                "formats": formats,
                "license_id": license_id,
                "source_manifest_sha256": manifest_sha256,
                "state": submitted["state"],
            },
        )
        return self.repository.product_record(job.job_id)  # type: ignore[return-value]

    def pair_and_register(
        self,
        *,
        pairing_code: str,
        node_id: str,
        hostname: str,
        protocol_min: int = 1,
        protocol_max: int = 1,
    ) -> dict[str, Any]:
        token = self.repository.consume_pairing_code(pairing_code)
        registration = self.repository.register_node(
            node_id=node_id,
            hostname=hostname,
            protocol_min=protocol_min,
            protocol_max=protocol_max,
            auth_token=token,
        )
        return {**registration, "device_token": token}

    def heartbeat(
        self, *, node_id: str, token: str, capabilities: dict[str, Any] | None
    ) -> dict[str, Any]:
        self._authenticate(node_id, token)
        return self.repository.heartbeat(node_id, capabilities)

    def initiate_artifact_upload(
        self, *, node_id: str, token: str, expected_sha256: str,
        expected_size: int, chunk_size: int, idempotency_key: str,
    ) -> dict[str, Any]:
        self._authenticate(node_id, token)
        return self._idempotent(
            scope=f"node:{node_id}:artifact:initiate", key=idempotency_key,
            request={
                "expected_sha256": expected_sha256, "expected_size": expected_size,
                "chunk_size": chunk_size,
            },
            operation=lambda: asdict(self.artifacts.initiate(
                expected_sha256=expected_sha256, expected_size=expected_size,
                chunk_size=chunk_size,
            )),
        )

    def put_artifact_chunk(
        self, *, node_id: str, token: str, artifact_id: str, index: int,
        content: bytes, chunk_sha256: str, idempotency_key: str,
    ) -> dict[str, Any]:
        self._authenticate(node_id, token)
        return self._idempotent(
            scope=f"artifact:{artifact_id}:chunk:{index}", key=idempotency_key,
            request={"index": index, "chunk_sha256": chunk_sha256, "size": len(content)},
            operation=lambda: self.artifacts.put_chunk(
                artifact_id=artifact_id, index=index, content=content,
                chunk_sha256=chunk_sha256,
            ),
        )

    def commit_artifact_upload(
        self, *, node_id: str, token: str, artifact_id: str, idempotency_key: str,
    ) -> dict[str, Any]:
        self._authenticate(node_id, token)
        return self._idempotent(
            scope=f"artifact:{artifact_id}:commit", key=idempotency_key,
            request={"artifact_id": artifact_id},
            operation=lambda: self.artifacts.commit(artifact_id),
        )

    def artifact_download(self, *, node_id: str, token: str, sha256: str) -> Path:
        self._authenticate(node_id, token)
        if not self.artifacts.verify(sha256):
            raise KeyError(f"unknown or corrupt artifact: {sha256}")
        return self.artifacts.blob_path(sha256)

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

    def _authenticate(self, node_id: str, token: str) -> None:
        if not self.repository.authenticate_node(node_id, token):
            raise AuthenticationError("node credentials are invalid")

    def _idempotent(
        self,
        *,
        scope: str,
        key: str,
        request: dict[str, Any],
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        if not key or len(key) > 200:
            raise ValueError("a bounded Idempotency-Key is required")
        request_hash = sha256_text(canonical_json(request))
        with self._idempotency_lock:
            with self.repository.transaction() as db:
                existing = db.execute(
                    "SELECT request_hash, response_json FROM idempotency WHERE scope=? AND idempotency_key=?",
                    (scope, key),
                ).fetchone()
                if existing:
                    if existing["request_hash"] != request_hash:
                        raise IdempotencyConflict("idempotency key was reused with another request")
                    return json.loads(existing["response_json"])

            response = operation()
            with self.repository.transaction() as db:
                db.execute(
                    "INSERT INTO idempotency VALUES (?, ?, ?, ?, ?)",
                    (scope, key, request_hash, canonical_json(response), utc_timestamp()),
                )
        return response


def _lease_payload(grant: LeaseGrant) -> dict[str, Any]:
    payload = asdict(grant)
    return payload
