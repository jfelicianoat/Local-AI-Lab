"""Jobs and review history stay bounded and stable while new work arrives."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from local_ai_lab.coordinator.api import create_app
from local_ai_lab.coordinator.service import CoordinatorService


def _seed(service: CoordinatorService, count: int) -> None:
    with service.repository.transaction() as db:
        for number in range(count):
            rank = number // 2
            stamp = f"2026-09-29T00:{rank // 60:02}:{rank % 60:02}Z"
            db.execute(
                "INSERT INTO jobs(job_id,spec_json,spec_fingerprint,state,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (f"job-{number:04}", json.dumps({"kind": "test", "correlation_id": "test"}),
                 "fingerprint", "READY", stamp, stamp),
            )
    with service.feedback.store.transaction() as db:
        for number in range(count):
            rank = number // 2
            stamp = f"2026-09-29T00:{rank // 60:02}:{rank % 60:02}Z"
            db.execute(
                "INSERT INTO reviews(review_id,run_id,case_id,snapshot_id,reviewer,status,"
                "training_state,context_json,original_json,original_sha256,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"review-{number:04}", f"run-{number}", "case", "snapshot", "tester",
                 "draft", "excluded", "{}", "{}", "hash", stamp, stamp),
            )


def test_job_and_review_pages_are_bounded_and_authenticated(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "state.db")
    _seed(service, 125)
    client = TestClient(create_app(service, app_token="desktop-test"))
    headers = {"X-App-Token": "desktop-test"}
    assert client.get("/app/v1/storage").status_code == 401
    storage = client.get("/app/v1/storage", headers=headers)
    assert storage.status_code == 200
    assert storage.json()["available_quota_bytes"] == storage.json()["quota_bytes"]
    for kind, identity in (("jobs", "job_id"), ("reviews", "review_id")):
        route = f"/app/v1/{kind}/page"
        assert client.post(route, json={}).status_code == 401
        assert client.post(route, headers=headers, json={"limit": 0}).status_code == 422
        assert client.post(route, headers=headers, json={"cursor": {"id": "x"}}).status_code == 422
        seen: set[str] = set()
        cursor = None
        for page_number in range(3):
            response = client.post(route, headers=headers, json={"limit": 50, "cursor": cursor})
            assert response.status_code == 200
            page = response.json()
            assert len(page["items"]) == (25 if page_number == 2 else 50)
            assert page["pagination"]["total"] == 125 + (page_number > 0)
            ids = {item[identity] for item in page["items"]}
            assert not ids & seen
            seen |= ids
            cursor = page["pagination"]["cursor"]
            if page_number == 0:
                # A new record ahead of the cursor must not shift the older pages.
                with (service.repository.transaction() if kind == "jobs" else service.feedback.store.transaction()) as db:
                    if kind == "jobs":
                        db.execute(
                            "INSERT INTO jobs(job_id,spec_json,spec_fingerprint,state,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                            ("job-new", '{"kind":"test","correlation_id":"test"}', "fingerprint", "READY", "2026-09-30", "2026-09-30"),
                        )
                    else:
                        db.execute(
                            "INSERT INTO reviews(review_id,run_id,case_id,snapshot_id,reviewer,status,training_state,context_json,original_json,original_sha256,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            ("review-new", "run-new", "case", "snapshot", "tester", "draft", "excluded", "{}", "{}", "hash", "2026-09-30", "2026-09-30"),
                        )
            assert page["pagination"]["has_more"] is (page_number != 2)
        assert len(seen) == 125
        assert client.post(route, headers=headers, json={}).json()["items"][0][identity] == f"{kind[:-1]}-new"
