"""Modelos de peticion de la API.

Todos heredan de `StrictModel`: un campo de mas en el cuerpo es un error,
no algo que se ignora en silencio. Es lo que impide que un cliente crea que
mando una opcion que el Coordinator nunca leyo.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field



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
