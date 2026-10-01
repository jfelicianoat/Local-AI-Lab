"""Datasets aprobados, preflight, entrenamiento, destilacion y exportacion.

El preflight existe para que un entrenamiento no empiece y muera a las
dos horas por falta de VRAM: se comprueba el hardware antes, no despues.
"""
from __future__ import annotations

import json
import math
import uuid
import zipfile
from dataclasses import replace
from typing import Any

from local_ai_lab.artifacts.archive import deterministic_zip
from local_ai_lab.benchmark.controlled import ControlledCorpusSuite
from local_ai_lab.benchmark.orchestration import bundled_controlled_suite_root
from local_ai_lab.domain.common import sha256_json
from local_ai_lab.domain.jobs import JobSpec, JobState
from local_ai_lab.dataset.factory import DatasetFactory, DatasetVerifier
from local_ai_lab.exporting.planner import ExportJobPlanner
from local_ai_lab.training.contracts import TrainingContractReport
from local_ai_lab.training.comparison import verified_pass_rate
from local_ai_lab.training.plan import FineTuningProposal, TrainingPlanBuilder
from local_ai_lab.training.distillation import DistillationPlanBuilder, DistillationProposal
from local_ai_lab.training.resolver import HardwareResolution
from local_ai_lab.training.results import ML_RESULTS, RESULT_CONTRACT_VERSION, verify_ml_result
from local_ai_lab.coordinator.service.estrategias import EstrategiasMixin


class EntrenamientoMixin(EstrategiasMixin):
    """Datasets aprobados, preflight, entrenamiento, destilacion y exportacion."""

    def _verified_completed_ml_result(self, job: dict[str, Any]) -> tuple[dict, dict]:
        if job.get("result_validation_version") != RESULT_CONTRACT_VERSION:
            raise ValueError("ML result requires a new validated Worker execution")
        spec = json.loads(job["spec_json"])
        if spec["kind"] not in ML_RESULTS or job["state"] != JobState.SUCCEEDED:
            raise ValueError("ML result has no successful supported job")
        result = json.loads(job["result_json"])
        artifacts = result.get("artifacts")
        if (not isinstance(artifacts, list) or len(artifacts) != 1 or not isinstance(artifacts[0], dict)
                or artifacts[0].get("kind") != ML_RESULTS[spec["kind"]][0]
                or not isinstance(artifacts[0].get("sha256"), str)
                or not self.artifacts.verify(artifacts[0]["sha256"])):
            raise ValueError("validated ML result package is missing or corrupt")
        return result, verify_ml_result(self.artifacts.blob_path(artifacts[0]["sha256"]), job=job, result=result)

    def _validated_training_baseline(
        self, baseline_id: str, dataset: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if dataset is None or dataset["category"] != "dataset" or dataset["status"] != "READY_FOR_TRAINING":
            raise ValueError("training requires a registered dataset")
        baseline = self.repository.product_record(baseline_id)
        job = self.repository.job(baseline_id)
        if (baseline is None or baseline["category"] != "experiment"
                or baseline["status"] != "EXPERIMENT_SUCCEEDED"
                or job is None or job["state"] != JobState.SUCCEEDED):
            raise ValueError("training requires a completed prompting or RAG baseline")
        spec = json.loads(job["spec_json"])
        summary = baseline["summary"]
        if spec["kind"] != "strategy.suite.v1" or summary.get("strategy_id") not in {"B1", "R4"}:
            raise ValueError("training baseline must be B1 prompting or R4 RAG for a comparable F1/F2 evaluation")
        if not self.artifacts.verify(baseline["artifact_sha256"]):
            raise ValueError("training baseline report is missing or corrupt")
        try:
            with zipfile.ZipFile(self.artifacts.blob_path(baseline["artifact_sha256"])) as archive:
                report = json.loads(archive.read("strategy-report.json"))
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
            raise ValueError("training baseline has no readable strategy report") from error
        if not isinstance(report, dict):
            raise ValueError("training baseline has no readable strategy report")
        if any(report.get(key) != summary.get(key) for key in (
            "strategy_id", "suite_fingerprint", "snapshot_hash", "case_ids", "target_model"
        )) or not isinstance(report.get("case_ids"), list) or not report["case_ids"]:
            raise ValueError("training baseline report does not match the completed run")
        quality = verified_pass_rate(report, report["case_ids"])
        summary_quality = summary.get("quality")
        if summary_quality is not None and (
            not isinstance(summary_quality, dict)
            or summary_quality.get("deterministic_pass_rate") != quality
        ):
            raise ValueError("training baseline quality differs from its verified report")
        source_snapshot_id = dataset["summary"].get("snapshot_id")
        source_snapshot_hash = dataset["summary"].get("snapshot_hash")
        source_snapshot = self.repository.product_record(source_snapshot_id) if source_snapshot_id else None
        if (source_snapshot is None or source_snapshot["category"] != "snapshot"
                or source_snapshot["status"] != "COMPLETE"
                or source_snapshot["artifact_sha256"] != source_snapshot_hash
                or summary.get("snapshot_id") != source_snapshot_id
                or summary.get("snapshot_hash") != source_snapshot_hash):
            raise ValueError("training baseline must evaluate the dataset's source snapshot")
        return {**baseline, "verified_quality": float(quality),
                "evaluation_strategy_id": "F1" if summary["strategy_id"] == "B1" else "F2"}

    def build_approved_feedback_dataset(
        self, *, name: str, split_seed: str, actor: str,
        source_snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        if source_snapshot_id is not None:
            source = self.repository.product_record(source_snapshot_id)
            if source is None or source["category"] != "snapshot" or source["status"] != "COMPLETE":
                raise ValueError("dataset source must be a registered complete snapshot")
        suite = ControlledCorpusSuite.load(
            bundled_controlled_suite_root(), require_human_approval=False
        )
        reserved_cases = {case["case_id"] for case in suite.cases}
        reserved_queries = {case["query"] for case in suite.cases}
        reserved_fingerprints = {suite.fingerprint}
        for benchmark in self.product_workspace()["benchmarks"]:
            if benchmark["status"] != "HUMAN_APPROVED":
                continue
            path = self.repository.artifact_location(
                benchmark["record_id"], expected_kind="real_benchmark_suite"
            )
            definition = json.loads(path.read_text(encoding="utf-8"))
            reserved_fingerprints.add(benchmark["artifact_sha256"])
            reserved_cases.update(case["case_id"] for case in definition["cases"])
            reserved_queries.update(case["query"] for case in definition["cases"])
        result = DatasetFactory().build(
            self.feedback,
            self.repository.path.parent / "datasets",
            name=name,
            benchmark_case_ids=reserved_cases,
            benchmark_fingerprints=reserved_fingerprints,
            benchmark_queries=reserved_queries,
            source_snapshot_id=source_snapshot_id,
            split_seed=split_seed,
        )
        manifest = DatasetVerifier().verify(result.path)
        source_snapshot_id = manifest["source_snapshot_ids"][0]
        source_snapshot = self.repository.product_record(source_snapshot_id)
        if (source_snapshot is None or source_snapshot["category"] != "snapshot"
                or source_snapshot["status"] != "COMPLETE"):
            raise ValueError("approved examples require a registered complete source snapshot")
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
                "snapshot_id": source_snapshot_id,
                "snapshot_hash": source_snapshot["artifact_sha256"],
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
        contains_mutable_facts: bool,
        minimum_quality_gain: float,
        approved_by: str,
        epochs: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        dataset = self.repository.product_record(dataset_id)
        baseline = self._validated_training_baseline(baseline_experiment_id, dataset)
        baseline_quality = baseline["verified_quality"]
        if (not math.isfinite(minimum_quality_gain) or minimum_quality_gain <= 0
                or baseline_quality + minimum_quality_gain > 1):
            raise ValueError("quality improvement target must be positive and achievable")
        preflight_record = self.repository.product_record(preflight_job_id)
        preflight_job = self.repository.job(preflight_job_id)
        if dataset is None or dataset["category"] != "dataset" or dataset["status"] != "READY_FOR_TRAINING":
            raise ValueError("training requires a registered dataset")
        if preflight_record is None or preflight_record["status"] != "PREFLIGHT_PASSED":
            raise ValueError("training requires a passed preflight")
        if preflight_job is None or preflight_job["state"] != JobState.SUCCEEDED:
            raise ValueError("preflight job has no successful result")
        result, _ = self._verified_completed_ml_result(preflight_job)
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
            dataset_fingerprint=dataset["artifact_sha256"],
            contains_mutable_facts=contains_mutable_facts,
            minimum_quality_gain=minimum_quality_gain,
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
            "max_length": preflight_spec["payload"].get("max_length", 4096),
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
                "evaluation_strategy_id": baseline["evaluation_strategy_id"],
                "baseline_verified_quality": baseline_quality,
                "baseline_suite_fingerprint": baseline["summary"]["suite_fingerprint"],
                "baseline_snapshot_hash": baseline["summary"]["snapshot_hash"],
                "baseline_case_ids": baseline["summary"]["case_ids"],
                "validation_status": "pending_post_training_evaluation",
                "promotion_status": "requires_human_quality_review",
                "node_id": hardware.node_id, "base_model": planned.payload["base_model"],
                "dtype": hardware.dtype, "objective": objective, "approved_by": approved_by,
                "minimum_quality_gain": minimum_quality_gain,
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
        contains_mutable_facts: bool,
        minimum_quality_gain: float,
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
        baseline = self._validated_training_baseline(baseline_experiment_id, dataset)
        baseline_quality = baseline["verified_quality"]
        if (not math.isfinite(minimum_quality_gain) or minimum_quality_gain <= 0
                or baseline_quality + minimum_quality_gain > 1):
            raise ValueError("quality improvement target must be positive and achievable")
        preflight_record = self.repository.product_record(preflight_job_id)
        preflight_job = self.repository.job(preflight_job_id)
        if dataset is None or dataset["category"] != "dataset" or dataset["status"] != "READY_FOR_TRAINING":
            raise ValueError("distillation requires a ready training dataset")
        if preflight_record is None or preflight_record["status"] != "PREFLIGHT_PASSED":
            raise ValueError("distillation requires a passed student preflight")
        if preflight_job is None or preflight_job["state"] != JobState.SUCCEEDED:
            raise ValueError("student preflight job has no successful result")
        result, _ = self._verified_completed_ml_result(preflight_job)
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
            contains_mutable_facts=contains_mutable_facts,
            minimum_quality_gain=minimum_quality_gain,
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
                "evaluation_strategy_id": baseline["evaluation_strategy_id"],
                "baseline_verified_quality": baseline_quality,
                "baseline_suite_fingerprint": baseline["summary"]["suite_fingerprint"],
                "baseline_snapshot_hash": baseline["summary"]["snapshot_hash"],
                "baseline_case_ids": baseline["summary"]["case_ids"],
                "validation_status": "pending_post_training_evaluation",
                "promotion_status": "requires_human_quality_review",
                "node_id": hardware.node_id,
                "teacher_model": teacher_model,
                "teacher_model_fingerprint": teacher_model_fingerprint,
                "teacher_source": teacher_source,
                "broker_check_id": broker_check_id,
                "teacher_target_model": teacher_target_model,
                "student_model": student_model,
                "student_model_fingerprint": student_model_fingerprint,
                "objective": objective,
                "minimum_quality_gain": minimum_quality_gain,
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
        verification_only: bool = False,
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
        if node["status"] != "online":
            raise ValueError("export requires an online, active Worker")
        if not license_id.strip():
            raise ValueError("export requires an explicit artifact license")
        result, training_manifest = self._verified_completed_ml_result(training_job)
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
            verification_only=verification_only,
            detected_dependencies={
                item["key"].removeprefix("runtime.package.")
                for item in capabilities.get("facts", [])
                if isinstance(item, dict) and isinstance(item.get("key"), str)
                and item["key"].startswith("runtime.package.")
                and isinstance(item.get("value"), str) and item["value"].strip()
            },
        )
        training_spec = json.loads(training_job["spec_json"])
        if "gguf" in formats and not llama_cpp_converter:
            raise ValueError("GGUF export requires the local llama.cpp converter path on the selected Worker")
        payload = {
            **planned.payload,
            "source_manifest_file_sha256": manifest_file_sha256,
            "source_training_manifest_sha256": manifest_sha256,
            "license_id": license_id,
            "serving": {**serving, "base_model": training_manifest.get("base_model") or training_manifest.get("student_model"),
                        "chat_template_fingerprint": training_manifest["chat_template_fingerprint"]},
            "required_support_artifacts": ["tokenizer"],
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
            title=f"{'Comprobación de exportación' if verification_only else 'Export'} · {', '.join(formats)}",
            status="EXPORT_VERIFICATION_QUEUED" if verification_only else "EXPORT_QUEUED",
            artifact_sha256=job.fingerprint(),
            summary={
                "job_id": job.job_id,
                "kind": job.kind,
                "training_job_id": training_job_id,
                "node_id": node_id,
                "formats": formats,
                "verification_only": verification_only,
                "license_id": license_id,
                "source_manifest_sha256": manifest_sha256,
                "validation_status_at_export": training_record["summary"].get(
                    "validation_status", "pending_post_training_evaluation"),
                "promotion_status": "experimental_not_promoted",
                "state": submitted["state"],
            },
        )
        return self.repository.product_record(job.job_id)  # type: ignore[return-value]
