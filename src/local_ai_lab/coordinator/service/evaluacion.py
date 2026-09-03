"""Benchmarks controlados y reales, deriva de modelos y compatibilidad.

Todo lo que mide. Ningun metodo de aqui decide nada: producen informes
que otros contextos usan para elegir.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from local_ai_lab.artifacts.archive import deterministic_zip
from local_ai_lab.benchmark.real import RealBenchmarkSuite
from local_ai_lab.benchmark.orchestration import bundled_controlled_suite_root, run_controlled_lexical_benchmark
from local_ai_lab.domain.common import canonical_json, sha256_json
from local_ai_lab.domain.jobs import JobSpec
from local_ai_lab.model_drift.integration import (
    ExternalTreatmentRef,
    FormalEvaluationPlan,
    ModelDriftIntegration,
)
from local_ai_lab.broker.compatibility import BrokerCompatibilityChecker
from local_ai_lab.coordinator.service.conocimiento import ConocimientoMixin


class EvaluacionMixin(ConocimientoMixin):
    """Benchmarks controlados y reales, deriva de modelos y compatibilidad."""

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
