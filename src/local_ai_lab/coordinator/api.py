from __future__ import annotations

import argparse
import base64
import binascii
import os
import secrets
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from local_ai_lab.coordinator.repository import CoordinatorConflict, LeaseRejected
from local_ai_lab.coordinator.service import (
    AuthenticationError,
    CoordinatorService,
    IdempotencyConflict,
)
from local_ai_lab.knowledge_index.snapshot import SnapshotError
from local_ai_lab.knowledge_index.vault import VaultSecurityError


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PairRequest(StrictModel):
    pairing_code: str = Field(min_length=8, max_length=64)
    node_id: str = Field(min_length=1, max_length=128)
    hostname: str = Field(min_length=1, max_length=255)
    protocol_min: int = 1
    protocol_max: int = 1


class HeartbeatRequest(StrictModel):
    capabilities: dict[str, Any] | None = None


class ClaimRequest(StrictModel):
    lease_seconds: int = Field(default=60, ge=5, le=3600)


class LeaseMutation(StrictModel):
    lease_token: str = Field(min_length=20, max_length=256)
    lease_generation: int = Field(ge=1)


class RenewRequest(LeaseMutation):
    lease_seconds: int = Field(default=60, ge=5, le=3600)


class ProgressRequest(LeaseMutation):
    sequence: int = Field(ge=1)
    payload: dict[str, Any]


class CompleteRequest(LeaseMutation):
    attempt_id: str = Field(min_length=1, max_length=128)
    outcome: str
    payload: dict[str, Any]


class ReviewCorrectionRequest(StrictModel):
    actor: str = Field(min_length=1, max_length=255)
    corrected_response: dict[str, Any]


class StateTransitionRequest(StrictModel):
    actor: str = Field(min_length=1, max_length=255)
    to_state: str = Field(min_length=1, max_length=64)


class VaultRootRequest(StrictModel):
    allowed_root: str = Field(min_length=1, max_length=1024)


class SnapshotCreateRequest(VaultRootRequest):
    vault_name: str = Field(min_length=1, max_length=255)


class IndexCreateRequest(StrictModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    previous_index_id: str | None = Field(default=None, max_length=128)


class CancelRequest(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=200)


class ArtifactInitiateRequest(StrictModel):
    expected_sha256: str = Field(min_length=64, max_length=64)
    expected_size: int = Field(ge=0)
    chunk_size: int = Field(ge=1, le=64 * 1024 * 1024)


class ArtifactChunkRequest(StrictModel):
    chunk_sha256: str = Field(min_length=64, max_length=64)
    content_base64: str = Field(min_length=1)


class ControlledBenchmarkRequest(StrictModel):
    k: int = Field(default=5, ge=1, le=100)


class SemanticBenchmarkRequest(StrictModel):
    strategy_id: str
    node_id: str = Field(min_length=1, max_length=128)
    embedding_model: str = Field(min_length=1, max_length=2048)
    embedding_model_fingerprint: str = Field(min_length=64, max_length=64)
    device: str = Field(default="cpu", min_length=1, max_length=64)
    k: int = Field(default=5, ge=1, le=100)
    idempotency_key: str = Field(min_length=1, max_length=200)


class RealBenchmarkRegisterRequest(StrictModel):
    definition: dict[str, Any]


class ModelDriftComparisonRequest(StrictModel):
    r3_experiment_id: str = Field(min_length=1, max_length=128)
    r4_experiment_id: str = Field(min_length=1, max_length=128)
    executable: str = Field(min_length=1, max_length=2048)
    working_directory: str = Field(min_length=1, max_length=2048)
    confirmed: bool


class BrokerCompatibilityRequest(StrictModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    phase: str
    token: str | None = Field(default=None, max_length=4096)


class StrategySelectionRequest(StrictModel):
    experiment_ids: list[str] = Field(min_length=1, max_length=50)
    privacy: str | None = Field(default=None, max_length=64)
    max_latency_ms: float | None = Field(default=None, gt=0)
    max_cost: str | None = Field(default=None, max_length=64)
    minimum_cases: int = Field(default=20, ge=1, le=100000)
    require_formal_verdict: bool = True


class BrokerAgentExperimentRequest(StrictModel):
    strategy_id: str
    broker_check_id: str = Field(min_length=1, max_length=128)
    broker_endpoint: str = Field(min_length=1, max_length=2048)
    node_id: str = Field(min_length=1, max_length=128)
    target_model: dict[str, str]
    embedding_model: str = Field(min_length=1, max_length=2048)
    embedding_model_fingerprint: str = Field(min_length=64, max_length=64)
    device: str = Field(default="cpu", min_length=1, max_length=64)
    k: int = Field(default=5, ge=1, le=100)
    idempotency_key: str = Field(min_length=1, max_length=200)


class StrategySuiteRequest(StrictModel):
    strategy_id: str
    broker_check_id: str = Field(min_length=1, max_length=128)
    broker_endpoint: str = Field(min_length=1, max_length=2048)
    node_id: str = Field(min_length=1, max_length=128)
    target_model: dict[str, str]
    embedding_model: str | None = Field(default=None, max_length=2048)
    embedding_model_fingerprint: str | None = Field(default=None, max_length=64)
    device: str = Field(default="cpu", min_length=1, max_length=64)
    training_job_id: str | None = Field(default=None, max_length=128)
    k: int = Field(default=5, ge=1, le=100)
    idempotency_key: str = Field(min_length=1, max_length=200)


class DatasetBuildRequest(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    split_seed: str = Field(min_length=8, max_length=255)
    actor: str = Field(min_length=1, max_length=255)


class TrainingPreflightRequest(StrictModel):
    dataset_id: str = Field(min_length=1, max_length=128)
    node_id: str = Field(min_length=1, max_length=128)
    base_model: str = Field(min_length=1, max_length=1024)
    dtype: str
    seed: int = Field(ge=0, le=2_147_483_647)
    max_length: int = Field(default=4096, ge=128, le=131072)
    lora_config: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=200)


class TrainingCreateRequest(StrictModel):
    dataset_id: str = Field(min_length=1, max_length=128)
    preflight_job_id: str = Field(min_length=1, max_length=128)
    baseline_experiment_id: str = Field(min_length=1, max_length=128)
    objective: str = Field(min_length=1, max_length=128)
    hypothesis: str = Field(min_length=1, max_length=2000)
    approved_by: str = Field(min_length=1, max_length=255)
    epochs: float = Field(default=1.0, gt=0, le=100)
    idempotency_key: str = Field(min_length=1, max_length=200)


class DistillationCreateRequest(StrictModel):
    dataset_id: str = Field(min_length=1, max_length=128)
    preflight_job_id: str = Field(min_length=1, max_length=128)
    baseline_experiment_id: str = Field(min_length=1, max_length=128)
    teacher_model: str = Field(min_length=1, max_length=1024)
    teacher_model_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    teacher_source: str = "local"
    broker_check_id: str | None = Field(default=None, max_length=128)
    teacher_broker_endpoint: str | None = Field(default=None, max_length=2048)
    teacher_target_model: dict[str, str] | None = None
    student_model: str = Field(min_length=1, max_length=1024)
    student_model_fingerprint: str = Field(min_length=64, max_length=64)
    teacher_license: str = Field(min_length=1, max_length=255)
    student_license: str = Field(min_length=1, max_length=255)
    teacher_outputs_training_allowed: bool
    student_finetuning_allowed: bool
    objective: str = Field(min_length=1, max_length=128)
    hypothesis: str = Field(min_length=1, max_length=2000)
    approved_by: str = Field(min_length=1, max_length=255)
    epochs: float = Field(default=1.0, gt=0, le=100)
    generation_config: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=200)


class ExportCreateRequest(StrictModel):
    training_job_id: str = Field(min_length=1, max_length=128)
    node_id: str = Field(min_length=1, max_length=128)
    formats: list[str] = Field(min_length=1, max_length=4)
    license_id: str = Field(min_length=1, max_length=255)
    serving: dict[str, Any]
    llama_cpp_converter: str | None = Field(default=None, max_length=2048)
    idempotency_key: str = Field(min_length=1, max_length=200)


def create_app(service: CoordinatorService, *, app_token: str | None = None) -> FastAPI:
    app = FastAPI(
        title="Local AI Lab Coordinator",
        version="0.1.0",
        description="Authenticated Coordinator/Worker protocol v1",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://tauri.localhost", "https://tauri.localhost", "tauri://localhost"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Accept", "Authorization", "Content-Type", "Idempotency-Key", "X-App-Token", "X-Node-ID"],
    )

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    def ready() -> dict[str, str]:
        with service.repository.connect() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ready"}

    @app.get("/app/v1/overview")
    def overview(
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        if app_token is None or not x_app_token or not secrets.compare_digest(
            app_token, x_app_token
        ):
            raise HTTPException(401, "valid desktop session token required")
        return service.overview()

    @app.get("/app/v1/workspace")
    def workspace(
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return service.product_workspace()

    @app.get("/app/v1/reviews")
    def reviews(
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> list[dict[str, Any]]:
        _require_app_token(app_token, x_app_token)
        return service.reviews()

    @app.get("/app/v1/jobs")
    def jobs(
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> list[dict[str, Any]]:
        _require_app_token(app_token, x_app_token)
        return service.jobs()

    @app.put("/app/v1/reviews/{review_id}/correction")
    def save_review_correction(
        review_id: str,
        body: ReviewCorrectionRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.save_review_correction,
            review_id=review_id,
            actor=body.actor,
            corrected_response=body.corrected_response,
        )

    @app.post("/app/v1/reviews/{review_id}/state")
    def transition_review(
        review_id: str,
        body: StateTransitionRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.transition_review,
            review_id=review_id,
            to_state=body.to_state,
            actor=body.actor,
        )

    @app.post("/app/v1/reviews/{review_id}/training-state")
    def transition_training_candidate(
        review_id: str,
        body: StateTransitionRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.transition_training_candidate,
            review_id=review_id,
            to_state=body.to_state,
            actor=body.actor,
        )

    @app.post("/app/v1/vaults/discover")
    def discover_vaults(
        body: VaultRootRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, list[str]]:
        _require_app_token(app_token, x_app_token)
        return {"vaults": _call(service.discover_vaults, allowed_root=Path(body.allowed_root))}

    @app.post("/app/v1/snapshots")
    def create_snapshot(
        body: SnapshotCreateRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.create_vault_snapshot,
            allowed_root=Path(body.allowed_root),
            vault_name=body.vault_name,
        )

    @app.post("/app/v1/indexes")
    def create_index(
        body: IndexCreateRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.create_knowledge_index,
            snapshot_id=body.snapshot_id,
            previous_index_id=body.previous_index_id,
        )

    @app.post("/app/v1/jobs/{job_id}/cancel")
    def cancel_job(
        job_id: str,
        body: CancelRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.request_cancel, job_id=job_id, idempotency_key=body.idempotency_key
        )

    @app.post("/app/v1/benchmarks/controlled/retrieval")
    def run_controlled_retrieval_benchmark(
        body: ControlledBenchmarkRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(service.run_controlled_retrieval_benchmark, k=body.k)

    @app.post("/app/v1/benchmarks/controlled/semantic")
    def create_controlled_semantic_benchmark(
        body: SemanticBenchmarkRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.create_controlled_semantic_benchmark_job,
            strategy_id=body.strategy_id, node_id=body.node_id,
            embedding_model=body.embedding_model,
            embedding_model_fingerprint=body.embedding_model_fingerprint,
            device=body.device, k=body.k, idempotency_key=body.idempotency_key,
        )

    @app.post("/app/v1/benchmarks/real")
    def register_real_benchmark(
        body: RealBenchmarkRegisterRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(service.register_real_benchmark, definition=body.definition)

    @app.post("/app/v1/model-drift/comparisons")
    def run_model_drift_comparison(
        body: ModelDriftComparisonRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.run_model_drift_comparison,
            r3_experiment_id=body.r3_experiment_id,
            r4_experiment_id=body.r4_experiment_id,
            executable=body.executable, working_directory=body.working_directory,
            confirmed=body.confirmed,
        )

    @app.post("/app/v1/broker/compatibility")
    def check_broker_compatibility(
        body: BrokerCompatibilityRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.check_broker_compatibility,
            endpoint=body.endpoint, phase=body.phase, token=body.token,
        )

    @app.post("/app/v1/strategy-selection")
    def select_strategy(
        body: StrategySelectionRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.select_strategy, experiment_ids=body.experiment_ids,
            privacy=body.privacy, max_latency_ms=body.max_latency_ms,
            max_cost=body.max_cost, minimum_cases=body.minimum_cases,
            require_formal_verdict=body.require_formal_verdict,
        )

    @app.post("/app/v1/broker/agent-experiments")
    def create_broker_agent_experiment(
        body: BrokerAgentExperimentRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.create_broker_agent_experiment_job,
            strategy_id=body.strategy_id, broker_check_id=body.broker_check_id,
            broker_endpoint=body.broker_endpoint, node_id=body.node_id,
            target_model=body.target_model, embedding_model=body.embedding_model,
            embedding_model_fingerprint=body.embedding_model_fingerprint,
            device=body.device, k=body.k, idempotency_key=body.idempotency_key,
        )

    @app.post("/app/v1/strategy-runs")
    def create_strategy_suite(
        body: StrategySuiteRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.create_strategy_suite_job,
            strategy_id=body.strategy_id, broker_check_id=body.broker_check_id,
            broker_endpoint=body.broker_endpoint, node_id=body.node_id,
            target_model=body.target_model, embedding_model=body.embedding_model,
            embedding_model_fingerprint=body.embedding_model_fingerprint,
            device=body.device, training_job_id=body.training_job_id,
            k=body.k, idempotency_key=body.idempotency_key,
        )

    @app.post("/app/v1/datasets")
    def build_dataset(
        body: DatasetBuildRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.build_approved_feedback_dataset,
            name=body.name, split_seed=body.split_seed, actor=body.actor,
        )

    @app.post("/app/v1/training/preflight")
    def create_training_preflight(
        body: TrainingPreflightRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.create_training_preflight_job,
            dataset_id=body.dataset_id, node_id=body.node_id, base_model=body.base_model,
            dtype=body.dtype, seed=body.seed, max_length=body.max_length,
            lora_config=body.lora_config, idempotency_key=body.idempotency_key,
        )

    @app.post("/app/v1/training/runs")
    def create_training_run(
        body: TrainingCreateRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.create_training_job,
            dataset_id=body.dataset_id, preflight_job_id=body.preflight_job_id,
            baseline_experiment_id=body.baseline_experiment_id,
            objective=body.objective, hypothesis=body.hypothesis,
            approved_by=body.approved_by, epochs=body.epochs,
            idempotency_key=body.idempotency_key,
        )

    @app.post("/app/v1/training/distillation")
    def create_distillation_run(
        body: DistillationCreateRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.create_distillation_job,
            dataset_id=body.dataset_id,
            preflight_job_id=body.preflight_job_id,
            baseline_experiment_id=body.baseline_experiment_id,
            teacher_model=body.teacher_model,
            teacher_model_fingerprint=body.teacher_model_fingerprint,
            teacher_source=body.teacher_source,
            broker_check_id=body.broker_check_id,
            teacher_broker_endpoint=body.teacher_broker_endpoint,
            teacher_target_model=body.teacher_target_model,
            student_model=body.student_model,
            student_model_fingerprint=body.student_model_fingerprint,
            teacher_license=body.teacher_license,
            student_license=body.student_license,
            teacher_outputs_training_allowed=body.teacher_outputs_training_allowed,
            student_finetuning_allowed=body.student_finetuning_allowed,
            objective=body.objective,
            hypothesis=body.hypothesis,
            approved_by=body.approved_by,
            epochs=body.epochs,
            generation_config=body.generation_config,
            idempotency_key=body.idempotency_key,
        )

    @app.post("/app/v1/exports")
    def create_export(
        body: ExportCreateRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.create_export_job,
            training_job_id=body.training_job_id,
            node_id=body.node_id,
            formats=body.formats,
            license_id=body.license_id,
            serving=body.serving,
            llama_cpp_converter=body.llama_cpp_converter,
            idempotency_key=body.idempotency_key,
        )

    @app.post("/node/v1/pair")
    def pair(body: PairRequest) -> dict[str, Any]:
        return _call(
            service.pair_and_register,
            pairing_code=body.pairing_code,
            node_id=body.node_id,
            hostname=body.hostname,
            protocol_min=body.protocol_min,
            protocol_max=body.protocol_max,
        )

    @app.post("/node/v1/heartbeats")
    def heartbeat(
        body: HeartbeatRequest,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return _call(
            service.heartbeat, node_id=node_id, token=token, capabilities=body.capabilities
        )

    @app.post("/node/v1/artifacts/initiate")
    def initiate_artifact(
        body: ArtifactInitiateRequest,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return _call(
            service.initiate_artifact_upload, node_id=node_id, token=token,
            expected_sha256=body.expected_sha256, expected_size=body.expected_size,
            chunk_size=body.chunk_size, idempotency_key=idempotency_key,
        )

    @app.post("/node/v1/artifacts/{artifact_id}/chunks/{index}")
    def put_artifact_chunk(
        artifact_id: str,
        index: int,
        body: ArtifactChunkRequest,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        try:
            content = base64.b64decode(body.content_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise HTTPException(422, "content_base64 is invalid") from error
        return _call(
            service.put_artifact_chunk, node_id=node_id, token=token,
            artifact_id=artifact_id, index=index, content=content,
            chunk_sha256=body.chunk_sha256, idempotency_key=idempotency_key,
        )

    @app.post("/node/v1/artifacts/{artifact_id}/commit")
    def commit_artifact(
        artifact_id: str,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return _call(
            service.commit_artifact_upload, node_id=node_id, token=token,
            artifact_id=artifact_id, idempotency_key=idempotency_key,
        )

    @app.get("/node/v1/artifacts/sha256/{sha256}", response_class=FileResponse)
    def download_artifact(
        sha256: str,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
    ) -> FileResponse:
        node_id, token = credentials
        path = _call(service.artifact_download, node_id=node_id, token=token, sha256=sha256)
        return FileResponse(
            path, media_type="application/octet-stream", filename=f"sha256-{sha256}.blob"
        )

    @app.post("/node/v1/jobs/claim")
    def claim(
        body: ClaimRequest,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return {
            "lease": _call(
                service.claim_job,
                node_id=node_id,
                token=token,
                idempotency_key=idempotency_key,
                lease_seconds=body.lease_seconds,
            )
        }

    @app.post("/node/v1/jobs/{job_id}/ack")
    def ack(
        job_id: str,
        body: LeaseMutation,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return _call(
            service.ack_job,
            node_id=node_id,
            token=token,
            job_id=job_id,
            lease_token=body.lease_token,
            lease_generation=body.lease_generation,
            idempotency_key=idempotency_key,
        )

    @app.post("/node/v1/jobs/{job_id}/lease/renew")
    def renew(
        job_id: str,
        body: RenewRequest,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return _call(
            service.renew_lease,
            node_id=node_id,
            token=token,
            job_id=job_id,
            lease_token=body.lease_token,
            lease_generation=body.lease_generation,
            lease_seconds=body.lease_seconds,
            idempotency_key=idempotency_key,
        )

    @app.post("/node/v1/jobs/{job_id}/progress")
    def progress(
        job_id: str,
        body: ProgressRequest,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return _call(
            service.progress,
            node_id=node_id,
            token=token,
            job_id=job_id,
            lease_token=body.lease_token,
            lease_generation=body.lease_generation,
            sequence=body.sequence,
            payload=body.payload,
            idempotency_key=idempotency_key,
        )

    @app.post("/node/v1/jobs/{job_id}/control")
    def job_control(
        job_id: str,
        body: LeaseMutation,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return _call(
            service.job_control,
            node_id=node_id, token=token, job_id=job_id,
            lease_token=body.lease_token, lease_generation=body.lease_generation,
            idempotency_key=idempotency_key,
        )

    @app.post("/node/v1/jobs/{job_id}/complete")
    def complete(
        job_id: str,
        body: CompleteRequest,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        if body.outcome not in ("succeeded", "failed", "cancelled"):
            raise HTTPException(422, "outcome must be succeeded, failed, or cancelled")
        return _call(
            service.complete_job,
            node_id=node_id,
            token=token,
            job_id=job_id,
            attempt_id=body.attempt_id,
            lease_token=body.lease_token,
            lease_generation=body.lease_generation,
            outcome=body.outcome,
            payload=body.payload,
            idempotency_key=idempotency_key,
        )

    return app


def _require_app_token(expected: str | None, supplied: str | None) -> None:
    if expected is None or not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(401, "valid desktop session token required")


def _node_credentials(
    x_node_id: Annotated[str, Header(alias="X-Node-ID")],
    authorization: Annotated[str, Header(alias="Authorization")],
) -> tuple[str, str]:
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Bearer node credential required")
    return x_node_id, token


def _call(operation: Any, **kwargs: Any) -> Any:
    try:
        return operation(**kwargs)
    except AuthenticationError as error:
        raise HTTPException(401, str(error)) from error
    except IdempotencyConflict as error:
        raise HTTPException(409, str(error)) from error
    except LeaseRejected as error:
        raise HTTPException(409, str(error)) from error
    except CoordinatorConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    except (OSError, SnapshotError, VaultSecurityError) as error:
        raise HTTPException(422, str(error)) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="local-ai-lab-coordinator")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8711)
    args = parser.parse_args(argv)
    if args.host not in ("127.0.0.1", "::1", "localhost") and os.environ.get(
        "LOCAL_AI_LAB_ALLOW_REMOTE_HTTP"
    ) != "I_ACCEPT_NO_TLS_FOR_DEVELOPMENT":
        parser.error("non-loopback binding requires a TLS terminator; development override denied")
    import uvicorn

    session_token = os.environ.get("LOCAL_AI_LAB_APP_TOKEN")
    if not session_token:
        parser.error("LOCAL_AI_LAB_APP_TOKEN must be provided by the desktop launcher")
    uvicorn.run(
        create_app(CoordinatorService(args.database), app_token=session_token),
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
