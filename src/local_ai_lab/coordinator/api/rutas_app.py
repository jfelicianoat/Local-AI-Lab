"""Rutas de la aplicacion de escritorio (`/app/v1`) y sondas de salud.

Todas exigen el token efimero de sesion: el Coordinator escucha en loopback,
pero loopback no es una frontera de confianza por si sola.
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

from local_ai_lab.coordinator.service import (
    CoordinatorService,
)
from local_ai_lab.coordinator.api.auxiliares import _call, _require_app_token
from local_ai_lab.coordinator.api.modelos import (
    BrokerAgentExperimentRequest,
    BrokerCompatibilityRequest,
    CancelRequest,
    CheckpointResumeRequest,
    ControlledBenchmarkRequest,
    DatasetBuildRequest,
    DistillationCreateRequest,
    ExportCreateRequest,
    HistoryPageRequest,
    IndexCreateRequest,
    ManualExampleCreateRequest,
    ManualExamplePreviewRequest,
    MissionLinkRequest,
    MissionSaveRequest,
    ModelDriftComparisonRequest,
    RealBenchmarkRegisterRequest,
    ReviewCorrectionRequest,
    ReviewStateTransitionRequest,
    SemanticBenchmarkRequest,
    SnapshotCreateRequest,
    StorageCleanupPlanRequest,
    StorageCleanupApplyRequest,
    StrategySelectionRequest,
    StrategySuiteRequest,
    TrainingCreateRequest,
    TrainingRestartRequest,
    TrainingPreflightRequest,
    VaultRootRequest,
    WorkspacePageRequest,
)


def registrar_rutas_app(
    app: FastAPI, service: CoordinatorService, app_token: str | None
) -> None:
    """Cuelga en `app` las rutas que consume el escritorio."""

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

    @app.get("/app/v1/storage")
    def storage(
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, int]:
        _require_app_token(app_token, x_app_token)
        return service.artifacts.usage()

    @app.post("/app/v1/storage/cleanup/plan")
    def storage_cleanup_plan(
        request: StorageCleanupPlanRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(service.storage_cleanup_plan, older_than_days=request.older_than_days)

    @app.get("/app/v1/storage/cleanup/pending")
    def storage_cleanup_pending(
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any] | None:
        _require_app_token(app_token, x_app_token)
        return service.pending_storage_cleanup()

    @app.post("/app/v1/storage/cleanup/apply")
    def storage_cleanup_apply(
        request: StorageCleanupApplyRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(service.apply_storage_cleanup, plan_id=request.plan_id)

    @app.post("/app/v1/nodes/{node_id}/revoke")
    def revoke_node(
        node_id: str,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, str]:
        _require_app_token(app_token, x_app_token)
        return _call(service.revoke_node, node_id=node_id)

    @app.get("/app/v1/workspace")
    def workspace(
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return service.product_workspace_page()

    @app.post("/app/v1/workspace/page")
    def workspace_page(
        body: WorkspacePageRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(service.product_workspace_page, **body.model_dump())

    @app.get("/app/v1/missions")
    def missions(
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> list[dict[str, Any]]:
        _require_app_token(app_token, x_app_token)
        return service.missions()

    @app.put("/app/v1/missions/{mission_id}")
    def save_mission(
        mission_id: str, body: MissionSaveRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(service.save_mission, mission_id=mission_id, **body.model_dump())

    @app.post("/app/v1/missions/{mission_id}/links")
    def link_mission(
        mission_id: str, body: MissionLinkRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(service.link_mission_evidence, mission_id=mission_id, **body.model_dump())

    @app.post("/app/v1/missions/{mission_id}/unlink")
    def unlink_mission(
        mission_id: str, body: MissionLinkRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(service.unlink_mission_evidence, mission_id=mission_id, **body.model_dump())

    @app.get("/app/v1/records/{record_id}/artifact")
    def product_artifact(
        record_id: str,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> FileResponse:
        _require_app_token(app_token, x_app_token)
        path, media_type, filename = _call(service.product_artifact, record_id=record_id)
        record = service.repository.product_record(record_id)
        return FileResponse(
            path,
            media_type=media_type,
            filename=filename,
            headers={"X-Artifact-SHA256": record["artifact_sha256"]},
        )

    @app.get("/app/v1/reviews")
    def reviews(
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> list[dict[str, Any]]:
        _require_app_token(app_token, x_app_token)
        return service.reviews()

    @app.post("/app/v1/reviews/page")
    def reviews_page(
        body: HistoryPageRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(service.reviews_page, limit=body.limit,
                     cursor=body.cursor.model_dump() if body.cursor else None)

    @app.post("/app/v1/manual-examples/preview")
    def preview_manual_example(
        body: ManualExamplePreviewRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> list[dict[str, str]]:
        _require_app_token(app_token, x_app_token)
        return _call(service.preview_manual_example, **body.model_dump())

    @app.post("/app/v1/manual-examples")
    def create_manual_example(
        body: ManualExampleCreateRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(service.create_manual_example_review, **body.model_dump())

    @app.get("/app/v1/jobs")
    def jobs(
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> list[dict[str, Any]]:
        _require_app_token(app_token, x_app_token)
        return service.jobs()

    @app.post("/app/v1/jobs/page")
    def jobs_page(
        body: HistoryPageRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(service.jobs_page, limit=body.limit,
                     cursor=body.cursor.model_dump() if body.cursor else None)

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
            expected_revision=body.expected_revision,
        )

    @app.post("/app/v1/reviews/{review_id}/state")
    def transition_review(
        review_id: str,
        body: ReviewStateTransitionRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.transition_review,
            review_id=review_id,
            to_state=body.to_state,
            actor=body.actor,
            reason=body.reason,
            expected_revision=body.expected_revision,
        )

    @app.post("/app/v1/reviews/{review_id}/training-state")
    def transition_training_candidate(
        review_id: str,
        body: ReviewStateTransitionRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.transition_training_candidate,
            review_id=review_id,
            to_state=body.to_state,
            actor=body.actor,
            expected_revision=body.expected_revision,
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

    @app.get("/app/v1/jobs/{job_id}/checkpoints")
    def training_checkpoints(
        job_id: str,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> list[dict[str, Any]]:
        _require_app_token(app_token, x_app_token)
        return _call(service.training_checkpoints, job_id=job_id)

    @app.get("/app/v1/jobs/{job_id}/training-restart")
    def training_restart_status(
        job_id: str,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(service.training_restart_status, job_id=job_id)

    @app.post("/app/v1/jobs/{job_id}/resume-checkpoint")
    def resume_training_checkpoint(
        job_id: str,
        body: CheckpointResumeRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.resume_training_from_checkpoint,
            job_id=job_id, checkpoint_id=body.checkpoint_id,
            idempotency_key=body.idempotency_key, node_id=body.node_id,
        )

    @app.post("/app/v1/jobs/{job_id}/restart-training")
    def restart_training(
        job_id: str,
        body: TrainingRestartRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(
            service.restart_training_job, job_id=job_id,
            node_id=body.node_id, idempotency_key=body.idempotency_key,
        )

    @app.post("/app/v1/benchmarks/controlled/retrieval")
    def run_controlled_retrieval_benchmark(
        body: ControlledBenchmarkRequest,
        x_app_token: Annotated[str | None, Header(alias="X-App-Token")] = None,
    ) -> dict[str, Any]:
        _require_app_token(app_token, x_app_token)
        return _call(service.run_controlled_retrieval_benchmark, k=body.k,
                     benchmark_id=body.benchmark_id, snapshot_id=body.snapshot_id,
                     index_id=body.index_id)

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
            benchmark_id=body.benchmark_id, snapshot_id=body.snapshot_id,
            index_id=body.index_id,
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
            quality_metric=body.quality_metric, minimum_quality=body.minimum_quality,
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
            benchmark_id=body.benchmark_id, snapshot_id=body.snapshot_id,
            index_id=body.index_id,
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
            benchmark_id=body.benchmark_id, snapshot_id=body.snapshot_id,
            index_id=body.index_id,
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
            source_snapshot_id=body.source_snapshot_id,
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
            contains_mutable_facts=body.contains_mutable_facts,
            minimum_quality_gain=body.minimum_quality_gain,
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
            contains_mutable_facts=body.contains_mutable_facts,
            minimum_quality_gain=body.minimum_quality_gain,
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
            verification_only=body.verification_only,
            idempotency_key=body.idempotency_key,
        )
