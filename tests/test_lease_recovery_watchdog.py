from __future__ import annotations

import threading

from fastapi.testclient import TestClient
import pytest

from local_ai_lab.coordinator import api
from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.domain.jobs import IdempotencyClass, JobSpec, ReassignmentPolicy


def test_coordinator_recovers_leases_on_startup_and_without_client_requests(
    tmp_path, monkeypatch,
) -> None:
    service = CoordinatorService(tmp_path / "state.db")
    monkeypatch.setattr(api, "LEASE_RECOVERY_INTERVAL_SECONDS", 0.01)
    recovered_twice = threading.Event()
    calls = 0
    original = service._recover_expired_jobs

    def recover() -> None:
        nonlocal calls
        original()
        calls += 1
        if calls >= 2:
            recovered_twice.set()

    monkeypatch.setattr(service, "_recover_expired_jobs", recover)
    with TestClient(api.create_app(service)):
        assert calls >= 1
        assert recovered_twice.wait(timeout=2)


@pytest.mark.parametrize("checkpointable, expected", [(False, "ready"), (True, "needs_review")])
def test_startup_reconciles_orphans_left_by_an_interrupted_recovery(
    tmp_path, checkpointable: bool, expected: str,
) -> None:
    service = CoordinatorService(tmp_path / "state.db")
    spec = JobSpec(
        kind="interrupted",
        payload={},
        idempotency_class=(IdempotencyClass.CHECKPOINTABLE if checkpointable
                           else IdempotencyClass.PURE),
        reassignment_policy=(ReassignmentPolicy.HUMAN_ONLY if checkpointable
                             else ReassignmentPolicy.AUTOMATIC),
    )
    service.submit_job(spec, "submit")
    with service.repository.transaction() as db:
        db.execute("UPDATE jobs SET state=? WHERE job_id=?", ("orphaned", spec.job_id))
    with TestClient(api.create_app(service)):
        assert service.repository.job(spec.job_id)["state"] == expected
