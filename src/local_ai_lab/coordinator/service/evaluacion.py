"""Benchmarks controlados y reales, deriva de modelos y compatibilidad.

Todo lo que mide. Ningun metodo de aqui decide nada: producen informes
que otros contextos usan para elegir.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from local_ai_lab.artifacts.archive import deterministic_zip
from local_ai_lab.benchmark.real import RealBenchmarkSuite
from local_ai_lab.benchmark.execution import load_execution_suite
from local_ai_lab.benchmark.retrieval_runner import RetrievalBenchmarkRunner
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
from local_ai_lab.knowledge_index.projection import KnowledgeIndex
from local_ai_lab.retrieval.engine import LexicalRetriever


class EvaluacionMixin(ConocimientoMixin):
    """Benchmarks controlados y reales, deriva de modelos y compatibilidad."""

    def _execution_inputs(
        self, *, benchmark_id: str | None, snapshot_id: str | None,
        index_id: str | None, k: int,
    ) -> dict[str, Any]:
        if benchmark_id is None:
            if snapshot_id or index_id:
                raise ValueError("snapshot and index require an explicit real benchmark")
            baseline = run_controlled_lexical_benchmark(
                self.repository.path.parent / "experiments", k=k
            )
            root = baseline.report_path.parent
            return {
                "suite_root": bundled_controlled_suite_root(),
                "snapshot_path": root / "snapshots" / f"vault_snapshot_{baseline.snapshot_id}",
                "index_path": root / "knowledge.sqlite3",
                "suite_fingerprint": baseline.suite.fingerprint,
                "snapshot_hash": baseline.snapshot_hash,
                "snapshot_id": baseline.snapshot_id,
                "case_ids": [case["case_id"] for case in baseline.suite.cases],
                "human_review": baseline.suite.review_status,
                "label": "corpus controlado",
            }
        if not snapshot_id or not index_id:
            raise ValueError("real benchmark requires an explicit snapshot and index")
        benchmark = self.repository.product_record(benchmark_id)
        snapshot_record = self.repository.product_record(snapshot_id)
        index_record = self.repository.product_record(index_id)
        if benchmark is None or benchmark["category"] != "benchmark" or benchmark["status"] != "HUMAN_APPROVED":
            raise ValueError("real benchmark must be registered and human approved")
        if snapshot_record is None or snapshot_record["category"] != "snapshot" or snapshot_record["status"] != "COMPLETE":
            raise ValueError("selected snapshot is not complete")
        if index_record is None or index_record["category"] != "index" or index_record["status"] != "READY":
            raise ValueError("selected knowledge index is not ready")
        if (
            benchmark["summary"].get("snapshot_hash") != snapshot_record["artifact_sha256"]
            or index_record["summary"].get("snapshot_hash") != snapshot_record["artifact_sha256"]
            or index_record["summary"].get("snapshot_id") != snapshot_id
        ):
            raise ValueError("benchmark, snapshot and index do not describe the same knowledge")
        snapshot_path = self.repository.artifact_location(snapshot_id, expected_kind="vault_snapshot")
        index_path = self.repository.artifact_location(index_id, expected_kind="knowledge_index")
        if hashlib.sha256(index_path.read_bytes()).hexdigest() != index_record["artifact_sha256"]:
            raise ValueError("selected knowledge index has changed")
        with sqlite3.connect(f"file:{index_path.as_posix()}?mode=ro", uri=True) as db:
            indexed_hash = db.execute(
                "SELECT value FROM build_metadata WHERE key='snapshot_global_hash'"
            ).fetchone()
        if indexed_hash is None or indexed_hash[0] != snapshot_record["artifact_sha256"]:
            raise ValueError("selected knowledge index points to another snapshot")
        definition_path = self.repository.artifact_location(
            benchmark_id, expected_kind="real_benchmark_suite"
        )
        suite = RealBenchmarkSuite.load(definition_path)
        if suite.fingerprint != benchmark["artifact_sha256"]:
            raise ValueError("registered real benchmark has changed")
        RealBenchmarkSuite.validate_against_snapshot(suite.definition, snapshot_path)
        stage = self.repository.path.parent / "packages" / "real-suites" / str(uuid.uuid4())
        stage.mkdir(parents=True, exist_ok=False)
        (stage / "real-benchmark.json").write_text(
            canonical_json(suite.definition) + "\n", encoding="utf-8", newline="\n"
        )
        return {
            "suite_root": stage,
            "snapshot_path": snapshot_path,
            "index_path": index_path,
            "suite_fingerprint": suite.fingerprint,
            "snapshot_hash": snapshot_record["artifact_sha256"],
            "snapshot_id": snapshot_id,
            "case_ids": [case["case_id"] for case in suite.definition["cases"]],
            "human_review": "approved",
            "label": "benchmark real",
            "benchmark_id": benchmark_id,
        }

    def run_controlled_retrieval_benchmark(
        self, *, k: int = 5, benchmark_id: str | None = None,
        snapshot_id: str | None = None, index_id: str | None = None,
    ) -> dict[str, Any]:
        if benchmark_id is None:
            artifact = run_controlled_lexical_benchmark(
                self.repository.path.parent / "experiments", k=k
            )
            report = artifact.report
            experiment_id = artifact.experiment_id
            report_path = artifact.report_path
            report_sha256 = artifact.report_sha256
            suite_fingerprint = artifact.suite.fingerprint
            snapshot_hash = artifact.snapshot_hash
            case_ids = [case["case_id"] for case in artifact.suite.cases]
            review_status = artifact.suite.review_status
            label = "corpus controlado"
        else:
            inputs = self._execution_inputs(
                benchmark_id=benchmark_id, snapshot_id=snapshot_id, index_id=index_id, k=k
            )
            suite = load_execution_suite(inputs["suite_root"], inputs["snapshot_path"])
            started = time.perf_counter()
            report = RetrievalBenchmarkRunner().run(
                suite, LexicalRetriever(KnowledgeIndex(inputs["index_path"])), k=k
            ).payload
            report["latency_ms"] = (time.perf_counter() - started) * 1000.0
            report["snapshot_hash"] = inputs["snapshot_hash"]
            experiment_id = str(uuid.uuid4())
            report_path = self.repository.path.parent / "experiments" / experiment_id / "retrieval-report.json"
            report_path.parent.mkdir(parents=True, exist_ok=False)
            report_path.write_text(canonical_json(report) + "\n", encoding="utf-8", newline="\n")
            report_sha256 = hashlib.sha256(report_path.read_bytes()).hexdigest()
            suite_fingerprint = inputs["suite_fingerprint"]
            snapshot_hash = inputs["snapshot_hash"]
            case_ids = inputs["case_ids"]
            review_status = inputs["human_review"]
            label = inputs["label"]
        aggregate = report["aggregate"]
        status = "LOCAL_VERIFIED" if review_status == "approved" else "PENDING_HUMAN_REVIEW"
        self.record_product_item(
            record_id=experiment_id,
            category="experiment",
            title=f"R1 · {label}",
            status=status,
            artifact_sha256=report_sha256,
            summary={
                "strategy_id": report["strategy_id"],
                "suite_fingerprint": suite_fingerprint,
                "snapshot_hash": snapshot_hash,
                "benchmark_id": benchmark_id,
                "human_review": review_status,
                "k": k,
                "recall_at_k": aggregate["recall_at_k"],
                "precision_at_k": aggregate["precision_at_k"],
                "mrr": aggregate["reciprocal_rank"],
                "ndcg_at_k": aggregate["ndcg_at_k"],
                "source_coverage": aggregate["source_coverage"],
                "redundancy": aggregate["redundancy"],
                "latency_ms": report["latency_ms"],
                "case_ids": case_ids,
                "formal_status": "unverified",
                "cost": "local / not metered",
                "privacy": "local_only",
            },
        )
        self.repository.record_artifact_location(
            record_id=experiment_id,
            artifact_kind="retrieval_benchmark_report",
            local_path=report_path,
            artifact_sha256=report_sha256,
        )
        return next(
            record for record in self.product_workspace()["experiments"]
            if record["record_id"] == experiment_id
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
        benchmark_id: str | None = None,
        snapshot_id: str | None = None,
        index_id: str | None = None,
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
        inputs = self._execution_inputs(
            benchmark_id=benchmark_id, snapshot_id=snapshot_id, index_id=index_id, k=k
        )
        package_root = self.repository.path.parent / "packages"
        package_id = str(uuid.uuid4())
        snapshot_zip, _ = deterministic_zip(
            inputs["snapshot_path"], package_root / f"snapshot-{package_id}.zip"
        )
        suite_zip, _ = deterministic_zip(
            inputs["suite_root"], package_root / f"suite-{package_id}.zip"
        )
        snapshot_cas = self.artifacts.ingest_file(snapshot_zip)
        suite_cas = self.artifacts.ingest_file(suite_zip)
        index_cas = self.artifacts.ingest_file(inputs["index_path"])
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
            title=f"{strategy_id} · {inputs['label']}", status="EXPERIMENT_QUEUED",
            artifact_sha256=job.fingerprint(),
            summary={
                "job_id": job.job_id, "strategy_id": strategy_id,
                "suite_fingerprint": inputs["suite_fingerprint"],
                "snapshot_hash": inputs["snapshot_hash"], "human_review": inputs["human_review"],
                "benchmark_id": benchmark_id, "snapshot_id": inputs["snapshot_id"], "index_id": index_id,
                "node_id": node_id, "embedding_model": embedding_model,
                "embedding_model_fingerprint": embedding_model_fingerprint,
                "device": device,
                "configuration_label": f"{strategy_id} · {embedding_model} · k={k}",
                "configuration_fingerprint": sha256_json(configuration),
                "k": k, "state": submitted["state"], "formal_status": "unverified",
                "case_ids": inputs["case_ids"],
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
        RealBenchmarkSuite.validate_against_snapshot(
            definition,
            self.repository.artifact_location(snapshot["record_id"], expected_kind="vault_snapshot"),
        )
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
                "baseline_artifact_sha256": r3["artifact_sha256"],
                "candidate_artifact_sha256": r4["artifact_sha256"],
                "baseline_configuration_fingerprint": r3["summary"].get("configuration_fingerprint"),
                "candidate_configuration_fingerprint": r4["summary"].get("configuration_fingerprint"),
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
