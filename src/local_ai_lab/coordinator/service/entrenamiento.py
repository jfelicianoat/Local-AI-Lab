"""Datasets aprobados, preflight, entrenamiento, destilacion y exportacion.

El preflight existe para que un entrenamiento no empiece y muera a las
dos horas por falta de VRAM: se comprueba el hardware antes, no despues.
"""
from __future__ import annotations

import json
import uuid
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
from local_ai_lab.training.plan import FineTuningProposal, TrainingPlanBuilder
from local_ai_lab.training.distillation import DistillationPlanBuilder, DistillationProposal
from local_ai_lab.training.resolver import HardwareResolution
from local_ai_lab.coordinator.service.estrategias import EstrategiasMixin


class EntrenamientoMixin(EstrategiasMixin):
    """Datasets aprobados, preflight, entrenamiento, destilacion y exportacion."""

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
