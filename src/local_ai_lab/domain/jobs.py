from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from local_ai_lab.domain.common import new_id, sha256_json, utc_timestamp


class JobState(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    LEASED = "leased"
    ACKNOWLEDGED = "acknowledged"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED_PENDING_SYNC = "succeeded_pending_sync"
    SUCCEEDED = "succeeded"
    FAILED_PENDING_SYNC = "failed_pending_sync"
    FAILED = "failed"
    ORPHANED = "orphaned"
    SUPERSEDED = "superseded"
    NEEDS_REVIEW = "needs_review"


class IdempotencyClass(StrEnum):
    PURE = "pure"
    CHECKPOINTABLE = "checkpointable"
    NON_REPEATABLE = "non_repeatable"


class DisconnectPolicy(StrEnum):
    STOP = "stop"
    CONTINUE = "continue"
    CHECKPOINT_THEN_STOP = "checkpoint_then_stop"


class ReassignmentPolicy(StrEnum):
    AUTOMATIC = "automatic"
    AFTER_GRACE = "after_grace"
    HUMAN_ONLY = "human_only"


TERMINAL_STATES = {
    JobState.CANCELLED,
    JobState.SUCCEEDED,
    JobState.FAILED,
    JobState.SUPERSEDED,
}


ALLOWED_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.DRAFT: {JobState.READY, JobState.CANCELLED},
    JobState.READY: {JobState.LEASED, JobState.CANCELLED},
    JobState.LEASED: {JobState.ACKNOWLEDGED, JobState.ORPHANED, JobState.CANCELLING},
    JobState.ACKNOWLEDGED: {JobState.RUNNING, JobState.ORPHANED, JobState.CANCELLING},
    JobState.RUNNING: {
        JobState.PAUSING,
        JobState.CANCELLING,
        JobState.SUCCEEDED_PENDING_SYNC,
        JobState.FAILED_PENDING_SYNC,
        JobState.ORPHANED,
    },
    JobState.PAUSING: {JobState.PAUSED, JobState.RUNNING, JobState.ORPHANED},
    JobState.PAUSED: {JobState.RUNNING, JobState.CANCELLING, JobState.ORPHANED},
    JobState.CANCELLING: {JobState.CANCELLED, JobState.ORPHANED},
    JobState.SUCCEEDED_PENDING_SYNC: {JobState.SUCCEEDED},
    JobState.FAILED_PENDING_SYNC: {JobState.FAILED},
    JobState.ORPHANED: {JobState.RUNNING, JobState.SUPERSEDED, JobState.NEEDS_REVIEW},
    JobState.NEEDS_REVIEW: {JobState.RUNNING, JobState.SUPERSEDED, JobState.CANCELLED},
}


class InvalidJobTransition(ValueError):
    pass


def assert_transition(current: JobState, target: JobState) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidJobTransition(f"job cannot transition from {current} to {target}")


@dataclass(frozen=True, slots=True)
class JobSpec:
    kind: str
    payload: dict[str, Any]
    requirements: dict[str, Any] = field(default_factory=dict)
    idempotency_class: IdempotencyClass = IdempotencyClass.PURE
    disconnect_policy: DisconnectPolicy = DisconnectPolicy.CONTINUE
    reassignment_policy: ReassignmentPolicy = ReassignmentPolicy.AUTOMATIC
    schema_version: str = "local-ai-lab.job.v1"
    job_id: str = field(default_factory=new_id)
    correlation_id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=utc_timestamp)

    def fingerprint(self) -> str:
        return sha256_json(asdict(self))


@dataclass(frozen=True, slots=True)
class LeaseGrant:
    job_id: str
    attempt_id: str
    node_id: str
    lease_token: str
    lease_generation: int
    expires_at: str
    spec: JobSpec
