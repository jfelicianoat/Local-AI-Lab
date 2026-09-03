"""Rutas de la aplicacion de escritorio (`/app/v1`) y sondas de salud.

Todas exigen el token efimero de sesion: el Coordinator escucha en loopback,
pero loopback no es una frontera de confianza por si sola.
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException

from local_ai_lab.coordinator.service import (
    CoordinatorService,
)
from local_ai_lab.coordinator.api.auxiliares import _call, _require_app_token
from local_ai_lab.coordinator.api.modelos import (
    BrokerAgentExperimentRequest,
    BrokerCompatibilityRequest,
    CancelRequest,
    ControlledBenchmarkRequest,
    DatasetBuildRequest,
    DistillationCreateRequest,
    ExportCreateRequest,
    IndexCreateRequest,
    ModelDriftComparisonRequest,
    RealBenchmarkRegisterRequest,
    ReviewCorrectionRequest,
    SemanticBenchmarkRequest,
    SnapshotCreateRequest,
    StateTransitionRequest,
    StrategySelectionRequest,
    StrategySuiteRequest,
    TrainingCreateRequest,
    TrainingPreflightRequest,
    VaultRootRequest,
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
