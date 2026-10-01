"""Ciclo de vida de un trabajo: alta, reclamo, progreso, lease y cierre.

El lease es lo que permite que un nodo que se cae no bloquee un trabajo
para siempre; renovarlo es responsabilidad del que lo tiene.
"""
from __future__ import annotations

import json
import hashlib
import math
import zipfile
from dataclasses import asdict
from typing import Any

from local_ai_lab.domain.common import canonical_json
from local_ai_lab.domain.jobs import (
    DisconnectPolicy, IdempotencyClass, JobSpec, JobState, ReassignmentPolicy,
)
from local_ai_lab.coordinator.service.nodos import NodosMixin
from local_ai_lab.coordinator.service.base import _lease_payload
from local_ai_lab.coordinator.repository.base import CoordinatorConflict, LeaseRejected
from local_ai_lab.training.comparison import compare_verification_gain, verified_pass_rate
from local_ai_lab.training.checkpoints import verify_checkpoint_bundle
from local_ai_lab.training.results import ML_RESULTS, RESULT_CONTRACT_VERSION, verify_ml_result

_VALIDATED_RESULT_KINDS = set(ML_RESULTS) | {"retrieval.benchmark.v1", "broker.agent_experiment.v1", "strategy.suite.v1"}

class TrabajosMixin(NodosMixin):
    """Ciclo de vida de un trabajo: alta, reclamo, progreso, lease y cierre."""

    def _authorize_job_receipt(
        self, job_id: str, node_id: str, lease_token: str, lease_generation: int,
        attempt_id: str | None = None,
    ) -> None:
        job = self.repository.job(job_id)
        if job is None:
            raise CoordinatorConflict("job does not exist")
        # An accepted receipt remains recoverable after expiry. New operations
        # still check expiry in the repository; reassigned leases cannot replay it.
        self.repository._validate_lease_identity(job, node_id, lease_token, lease_generation)
        if attempt_id is not None and job["attempt_id"] != attempt_id:
            raise LeaseRejected("attempt is not current")

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
        self._recover_expired_jobs()

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
            authorization=lambda: self._authorize_job_receipt(job_id, node_id, lease_token, lease_generation),
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
            authorization=lambda: self._authorize_job_receipt(job_id, node_id, lease_token, lease_generation),
            operation=lambda: self.repository.record_progress(
                job_id=job_id,
                node_id=node_id,
                lease_token=lease_token,
                lease_generation=lease_generation,
                sequence=sequence,
                payload=payload,
            ),
        )

    def publish_training_checkpoint(
        self, *, node_id: str, token: str, job_id: str, attempt_id: str,
        lease_token: str, lease_generation: int, step: int,
        artifact_id: str, artifact_sha256: str, idempotency_key: str,
    ) -> dict[str, Any]:
        self._authenticate(node_id, token)

        def publish() -> dict[str, Any]:
            job = self.repository.job(job_id)
            if job is None:
                raise KeyError(job_id)
            spec = json.loads(job["spec_json"])
            if spec["kind"] not in {"training.lora.v1", "training.distillation.v1"}:
                raise ValueError("checkpoint source is not a training job")
            if not self.artifacts.verify(artifact_sha256):
                raise ValueError("checkpoint artifact is missing or corrupt")
            model_id = (spec["payload"].get("base_model") if spec["kind"] == "training.lora.v1"
                        else spec["payload"].get("student_model"))
            manifest = verify_checkpoint_bundle(
                self.artifacts.blob_path(artifact_sha256), expected={
                    "source_job_id": job_id, "source_attempt_id": attempt_id,
                    "source_lease_generation": lease_generation,
                    "source_spec_sha256": job["spec_fingerprint"],
                    "training_kind": spec["kind"],
                    "dataset_fingerprint": spec["payload"].get("dataset_fingerprint"),
                    "model_id": model_id,
                    "chat_template_fingerprint": spec["payload"].get("chat_template_fingerprint"),
                    "step": step,
                },
            )
            if manifest["step"] != step:
                raise ValueError("checkpoint step differs from publication")
            return self.repository.record_training_checkpoint(
                job_id=job_id, node_id=node_id, attempt_id=attempt_id,
                lease_token=lease_token, lease_generation=lease_generation,
                step=step, artifact_id=artifact_id, artifact_sha256=artifact_sha256,
            )

        return self._idempotent(
            scope=f"job:{job_id}:checkpoint:{attempt_id}", key=idempotency_key,
            request={"node_id": node_id, "lease_generation": lease_generation,
                     "step": step, "artifact_id": artifact_id,
                     "artifact_sha256": artifact_sha256},
            authorization=lambda: self._authorize_job_receipt(job_id, node_id, lease_token, lease_generation, attempt_id),
            operation=publish,
        )

    def training_checkpoints(self, job_id: str) -> list[dict[str, Any]]:
        return self.repository.training_checkpoints(job_id)

    def training_restart_status(self, job_id: str) -> dict[str, Any]:
        link = self.repository.training_restart_link(job_id)
        return {"restarted_job_id": link["restarted_job_id"] if link else None}

    def resume_training_from_checkpoint(
        self, *, job_id: str, checkpoint_id: str, idempotency_key: str,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        if not idempotency_key or len(idempotency_key) > 200:
            raise ValueError("a bounded recovery authorization key is required")
        job = self.repository.job(job_id)
        if job is None:
            raise KeyError(job_id)
        source_spec = json.loads(job["spec_json"])
        if source_spec["kind"] not in {"training.lora.v1", "training.distillation.v1"}:
            raise ValueError("recovery is available only for training checkpoints")
        previous = self.repository.training_resume_link(checkpoint_id)
        if previous is not None:
            if (previous["source_job_id"] != job_id
                    or previous["authorization_key"] != idempotency_key
                    or (node_id is not None and previous["target_node_id"] != node_id)):
                raise CoordinatorConflict("checkpoint already has an approved recovery")
            return {"job_id": previous["resumed_job_id"], "source_job_id": job_id,
                    "checkpoint_id": checkpoint_id, "replayed": True}
        checkpoint = next(
            (item for item in self.repository.training_checkpoints(job_id)
             if item["checkpoint_id"] == checkpoint_id), None,
        )
        if checkpoint is None or not self.artifacts.verify(checkpoint["artifact_sha256"]):
            raise ValueError("approved checkpoint is missing or corrupt")
        target_node_id = node_id or checkpoint["node_id"]
        if not self.repository.recovery_node_eligible(
            target_node_id, source_spec.get("requirements", {}),
        ):
            raise ValueError("selected Worker is unavailable or lacks training evidence")
        source_payload = source_spec["payload"]
        expected = {
            "source_job_id": job_id,
            "source_attempt_id": checkpoint["attempt_id"],
            "source_lease_generation": checkpoint["lease_generation"],
            "source_spec_sha256": job["spec_fingerprint"],
            "training_kind": source_spec["kind"],
            "dataset_fingerprint": source_payload["dataset_fingerprint"],
            "model_id": (source_payload["base_model"] if source_spec["kind"] == "training.lora.v1"
                         else source_payload["student_model"]),
            "chat_template_fingerprint": source_payload["chat_template_fingerprint"],
            "step": checkpoint["step"],
        }
        manifest = verify_checkpoint_bundle(
            self.artifacts.blob_path(checkpoint["artifact_sha256"]), expected=expected,
        )
        recovery = {
            **{key: manifest[key] for key in expected},
            "base_weights_sha256": manifest["base_weights_sha256"],
            "artifact_sha256": checkpoint["artifact_sha256"],
        }
        payload = {key: value for key, value in source_payload.items()
                   if key not in {"resume_checkpoint", "resume_from_checkpoint",
                                  "expected_base_weights_sha256"}}
        payload["input_artifacts"] = [
            item for item in source_payload.get("input_artifacts", [])
            if item.get("purpose") != "training_checkpoint"
        ] + [{
            "sha256": checkpoint["artifact_sha256"],
            "mount_as": "resolved_checkpoint_bundle", "archive": "zip",
            "purpose": "training_checkpoint",
        }]
        payload["resume_checkpoint"] = recovery
        payload["expected_base_weights_sha256"] = manifest["base_weights_sha256"]
        replacement = JobSpec(
            kind=source_spec["kind"], payload=payload,
            requirements={**source_spec.get("requirements", {}),
                          "node_ids": [target_node_id]},
            idempotency_class=IdempotencyClass(source_spec["idempotency_class"]),
            disconnect_policy=DisconnectPolicy(source_spec["disconnect_policy"]),
            reassignment_policy=ReassignmentPolicy(source_spec["reassignment_policy"]),
            schema_version=source_spec["schema_version"],
        )
        return self.repository.resume_training_from_checkpoint(
            source_job_id=job_id, checkpoint_id=checkpoint_id,
            spec=replacement, target_node_id=target_node_id,
            authorization_key=idempotency_key,
        )

    def restart_training_job(
        self, *, job_id: str, node_id: str, idempotency_key: str,
    ) -> dict[str, Any]:
        if not idempotency_key or len(idempotency_key) > 200:
            raise ValueError("a bounded restart authorization key is required")
        previous = self.repository.training_restart_link(job_id)
        if previous is not None:
            if (previous["authorization_key"] != idempotency_key
                    or previous["target_node_id"] != node_id):
                raise CoordinatorConflict("training already has an approved restart")
            return {"job_id": previous["restarted_job_id"],
                    "source_job_id": job_id, "replayed": True}
        source = self.repository.job(job_id)
        if source is None:
            raise KeyError(job_id)
        source_spec = json.loads(source["spec_json"])
        if source_spec["kind"] not in {"training.lora.v1", "training.distillation.v1"}:
            raise ValueError("only training jobs can be restarted")
        if not self.repository.recovery_node_eligible(
            node_id, source_spec.get("requirements", {}),
        ):
            raise ValueError("selected Worker is unavailable or lacks training evidence")
        source_payload = source_spec["payload"]
        inputs = [item for item in source_payload.get("input_artifacts", [])
                  if item.get("purpose") != "training_checkpoint"]
        if any(not self.artifacts.verify(item["sha256"]) for item in inputs):
            raise ValueError("original training input is missing or corrupt")
        payload = {key: value for key, value in source_payload.items()
                   if key not in {"resume_checkpoint", "resume_from_checkpoint",
                                  "expected_base_weights_sha256"}}
        payload["input_artifacts"] = inputs
        replacement = JobSpec(
            kind=source_spec["kind"], payload=payload,
            requirements={**source_spec.get("requirements", {}), "node_ids": [node_id]},
            idempotency_class=IdempotencyClass(source_spec["idempotency_class"]),
            disconnect_policy=DisconnectPolicy(source_spec["disconnect_policy"]),
            reassignment_policy=ReassignmentPolicy(source_spec["reassignment_policy"]),
            schema_version=source_spec["schema_version"],
        )
        return self.repository.restart_training_job(
            source_job_id=job_id, spec=replacement, target_node_id=node_id,
            authorization_key=idempotency_key,
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
            authorization=lambda: self._authorize_job_receipt(job_id, node_id, lease_token, lease_generation),
            operation=lambda: self.repository.renew_lease(
                job_id=job_id,
                node_id=node_id,
                lease_token=lease_token,
                lease_generation=lease_generation,
                lease_seconds=lease_seconds,
            ),
        )

    def request_cancel(self, *, job_id: str, idempotency_key: str) -> dict[str, Any]:
        def cancel() -> dict[str, Any]:
            response = self.repository.request_cancel(job_id)
            if response["state"] == JobState.CANCELLED:
                self._finalize_product_job(job_id, outcome="cancelled", payload={})
            return response

        return self._idempotent(
            scope=f"job:{job_id}:request-cancel",
            key=idempotency_key,
            request={"action": "cancel"},
            operation=cancel,
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
        # Control is an observation: caching it would hide a later cancellation.
        return self.repository.job_control(
            job_id=job_id, node_id=node_id, lease_token=lease_token,
            lease_generation=lease_generation,
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
        def authorize_completion() -> dict[str, Any] | None:
            try:
                self._authorize_job_receipt(job_id, node_id, lease_token, lease_generation, attempt_id)
            except LeaseRejected:
                # Preserve the stale-attempt audit and response without caching
                # a denial under the original Worker's completion key.
                return self.repository.complete(
                    job_id=job_id, node_id=node_id, attempt_id=attempt_id,
                    lease_token=lease_token, lease_generation=lease_generation,
                    outcome=outcome, payload=payload,
                )
            return None
        def complete() -> dict[str, Any]:
            current = self.repository.job(job_id)
            validation_version = 0
            if outcome == "succeeded" and current is not None and current["attempt_id"] == attempt_id:
                try:
                    self.repository._validate_lease(current, node_id, lease_token, lease_generation)
                except LeaseRejected:
                    pass  # complete() classifies stale attempts and retains their audit record.
                else:
                    self._validate_success_result(current, payload)
                    if json.loads(current["spec_json"])["kind"] in _VALIDATED_RESULT_KINDS:
                        validation_version = RESULT_CONTRACT_VERSION
            return self.repository.complete(
                job_id=job_id, node_id=node_id, attempt_id=attempt_id,
                lease_token=lease_token, lease_generation=lease_generation,
                outcome=outcome, payload=payload, result_validation_version=validation_version,
            )
        response = self._idempotent(
            scope=f"job:{job_id}:complete:{attempt_id}",
            key=idempotency_key,
            request={"outcome": outcome, "payload": payload},
            operation=complete,
            authorization=authorize_completion,
        )
        if response.get("accepted") is True:
            self._finalize_product_job(job_id, outcome=outcome, payload=payload)
        return response

    def _validate_success_result(self, job: dict[str, Any], payload: dict[str, Any]) -> None:
        spec = json.loads(job["spec_json"])
        expected = spec["payload"].get("collect_outputs", [])
        if spec["kind"] in ML_RESULTS:
            artifact_kind = ML_RESULTS[spec["kind"]][0]
            if (not isinstance(expected, list) or len(expected) != 1
                    or not isinstance(expected[0], dict) or expected[0].get("kind") != artifact_kind):
                raise ValueError("ML success requires the declared portable result package")
        if not expected and spec["kind"] in {"retrieval.benchmark.v1", "broker.agent_experiment.v1", "strategy.suite.v1"}:
            raise ValueError("experiment success requires a declared portable report")
        if not expected:
            return
        artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
        if not isinstance(artifacts, list) or len(artifacts) != len(expected):
            raise ValueError("successful job requires every declared result artifact")
        by_kind = {item.get("kind"): item for item in artifacts if isinstance(item, dict)}
        if len(by_kind) != len(expected) or set(by_kind) != {item["kind"] for item in expected}:
            raise ValueError("result artifact kinds do not match the job contract")
        for kind, descriptor in by_kind.items():
            digest = descriptor.get("sha256")
            artifact_id = descriptor.get("artifact_id")
            if not isinstance(digest, str) or not self.artifacts.verify(digest):
                raise ValueError("result artifact is absent or corrupt in CAS")
            if not isinstance(artifact_id, str):
                raise ValueError("result artifact has no upload identity")
            self.repository.authorize_artifact_upload(
                artifact_id=artifact_id, node_id=job["assigned_node_id"],
                job_id=job["job_id"], sha256=digest,
            )
            blob = self.artifacts.blob_path(digest)
            if descriptor.get("size") != blob.stat().st_size:
                raise ValueError("result artifact size differs from CAS")
        if spec["kind"] in ML_RESULTS:
            verify_ml_result(self.artifacts.blob_path(by_kind[artifact_kind]["sha256"]), job=job, result=payload)
            return
        report_file = {
            "retrieval.benchmark.v1": "retrieval-report.json",
            "broker.agent_experiment.v1": "agent-experiment.json",
            "strategy.suite.v1": "strategy-report.json",
        }.get(spec["kind"])
        if report_file is None:
            return
        kind = expected[0]["kind"]
        try:
            with zipfile.ZipFile(self.artifacts.blob_path(by_kind[kind]["sha256"])) as archive:
                if len(archive.namelist()) != len(set(archive.namelist())):
                    raise ValueError("experiment package has duplicate members")
                info = archive.getinfo(report_file)
                if info.file_size > 20 * 1024 * 1024:
                    raise ValueError("experiment report exceeds the validation limit")
                report_bytes = archive.read(info)
            report = json.loads(report_bytes)
        except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as error:
            raise ValueError("result artifact contains no valid experiment report") from error
        schema = {"retrieval.benchmark.v1": "retrieval-benchmark-report.v1",
                  "broker.agent_experiment.v1": "broker-agent-experiment.v1",
                  "strategy.suite.v1": "strategy-suite-report.v1"}[spec["kind"]]
        if not isinstance(report, dict) or report.get("schema_version") != schema:
            raise ValueError("experiment report schema is invalid")
        if hashlib.sha256(report_bytes).hexdigest() != payload.get("report_sha256"):
            raise ValueError("experiment report hash does not match the result")
        record = self.repository.product_record(job["job_id"])
        if record is None:
            raise ValueError("experiment has no registered product record")
        for key in ("suite_fingerprint", "snapshot_hash"):
            if report.get(key) != payload.get(key) or report.get(key) != record["summary"].get(key):
                raise ValueError(f"experiment result has a different {key}")
        case_ids = report.get("case_ids")
        if case_ids is None and isinstance(report.get("cases"), list):
            case_ids = [case.get("case_id") for case in report["cases"]]
        if case_ids != payload.get("case_ids") or case_ids != record["summary"].get("case_ids"):
            raise ValueError("experiment result case IDs differ from the selected suite")
        if spec["kind"] != "retrieval.benchmark.v1" and (
            report.get("strategy_id") != payload.get("strategy_id")
            or report.get("strategy_id") != record["summary"].get("strategy_id")
        ):
            raise ValueError("experiment result strategy differs from the job")
        if spec["kind"] == "strategy.suite.v1":
            verified_pass_rate(report, case_ids)
            if (payload.get("quality") != report.get("quality")
                    or payload.get("latency_ms") != report.get("latency_ms")
                    or report.get("target_model") != record["summary"].get("target_model")
                    or report.get("k") != record["summary"].get("k")
                    or report.get("trained_model_identity") != record["summary"].get("trained_model_identity")):
                raise ValueError("strategy result metrics or model differ from the verified report")
        common = ("latency_ms", "privacy", "formal_status")
        if spec["kind"] == "retrieval.benchmark.v1":
            fields = common + ("aggregate", "human_review_status", "embedding_model_fingerprint")
            if report.get("strategy_id") != payload.get("strategy_contract"):
                raise ValueError("retrieval result contract differs from the report")
        elif spec["kind"] == "broker.agent_experiment.v1":
            fields = common + ("quality", "review_candidates")
            verified_pass_rate({**report, "schema_version": "strategy-suite-report.v1"}, case_ids)
        else:
            fields = common + ("quality", "retrieval", "latency_scope", "generation_latency_ms",
                               "cost_amount", "cost_currency", "cost_source", "cost_verification_status",
                               "embedding_model", "embedding_model_fingerprint", "trained_model_identity", "review_candidates")
        for field in fields:
            default = [] if field == "review_candidates" else None
            if canonical_json(report.get(field, default)) != canonical_json(payload.get(field, default)):
                raise ValueError(f"experiment result {field} differs from the report")
        for field in ("latency_ms", "generation_latency_ms"):
            if field in report and (type(report[field]) not in {int, float} or not math.isfinite(report[field]) or report[field] < 0):
                raise ValueError("experiment latency must be a finite nonnegative number")
        if spec["kind"] != "retrieval.benchmark.v1" and report.get("target_model") != record["summary"].get("target_model"):
            raise ValueError("experiment model differs from the registered job")

    def _finalize_product_job(
        self, job_id: str, *, outcome: str, payload: dict[str, Any]
    ) -> None:
        job = self.repository.job(job_id)
        record = self.repository.product_record(job_id)
        if job is None or record is None:
            return
        spec = json.loads(job["spec_json"])
        kind = spec["kind"]
        if outcome == "succeeded" and kind in _VALIDATED_RESULT_KINDS and job.get("result_validation_version") != RESULT_CONTRACT_VERSION:
            # A cached historical success must not recreate invalidated capabilities.
            return
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
                "latency_scope": payload.get("latency_scope"),
                "generation_latency_ms": payload.get("generation_latency_ms"),
                "cost_amount": payload.get("cost_amount"),
                "cost_currency": payload.get("cost_currency"),
                "cost_source": payload.get("cost_source"),
                "cost_verification_status": payload.get("cost_verification_status"),
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
        if (outcome == "succeeded" and job.get("assigned_node_id")
                and job.get("environment_generation") is not None):
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
                    expected_environment_generation=job["environment_generation"],
                )
            self._record_preflight_hardware_facts(job, kind, payload)
        if kind == "strategy.suite.v1" and outcome == "succeeded" and payload.get("strategy_id") in {"F1", "F2"}:
            training_id = record["summary"].get("training_job_id")
            training = self.repository.product_record(training_id) if isinstance(training_id, str) else None
            comparison: dict[str, Any] = {
                "status": "unverifiable_legacy_baseline",
                "evaluation_experiment_id": job_id,
            }
            if training is not None and training["category"] == "training":
                training_summary = training["summary"]
                quality = payload.get("quality")
                try:
                    comparison = compare_verification_gain(
                        training_summary["baseline_verified_quality"],
                        quality.get("deterministic_pass_rate") if isinstance(quality, dict) else None,
                        training_summary["minimum_quality_gain"],
                    )
                    comparison["status"] = "verified"
                    comparison["baseline_experiment_id"] = training_summary["baseline_experiment_id"]
                except (KeyError, TypeError, ValueError):
                    pass  # Older in-flight jobs cannot prove a comparable baseline.
                comparison["evaluation_experiment_id"] = job_id
                validation_status = (
                    "deterministic_target_met" if comparison.get("target_met") else "deterministic_target_not_met"
                ) if comparison["status"] == "verified" else "unverifiable_legacy_baseline"
                self.record_product_item(
                    record_id=training_id, category="training", title=training["title"],
                    status=training["status"], artifact_sha256=training["artifact_sha256"],
                    summary={**training_summary,
                             "validation_status": validation_status,
                             "promotion_status": "requires_human_quality_review" if comparison.get("target_met") else "experimental_not_promoted",
                             "last_baseline_comparison": comparison},
                )
            summary["baseline_comparison"] = comparison
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
            job["assigned_node_id"], facts=facts, source="training.preflight.v1",
            expected_environment_generation=job["environment_generation"],
        )
