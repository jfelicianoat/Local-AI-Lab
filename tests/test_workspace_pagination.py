"""The desktop loads bounded, stable pages of product history."""
from pathlib import Path

from fastapi.testclient import TestClient

from local_ai_lab.coordinator.api import create_app
from local_ai_lab.coordinator.service import CoordinatorService


def test_workspace_pages_are_bounded_and_do_not_repeat_after_new_insert(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "state.db")
    for number in range(125):
        service.record_product_item(
            record_id=f"experiment-{number:04}", category="experiment",
            title=f"Run {number}", status="EXPERIMENT_SUCCEEDED",
            artifact_sha256="a" * 64, summary={"number": number},
        )
    client = TestClient(create_app(service, app_token="desktop-test"))
    assert client.get("/app/v1/workspace").status_code == 401
    headers = {"X-App-Token": "desktop-test"}
    first = client.get("/app/v1/workspace", headers=headers)
    assert first.status_code == 200
    page = first.json()
    assert len(page["experiments"]) == 50
    assert page["pagination"]["experiments"]["total"] == 125
    assert page["pagination"]["experiments"]["has_more"] is True
    seen = {item["record_id"] for item in page["experiments"]}
    cursor = page["pagination"]["experiments"]["cursor"]

    service.record_product_item(
        record_id="experiment-new", category="experiment", title="New run",
        status="EXPERIMENT_QUEUED", artifact_sha256="b" * 64, summary={},
    )
    while cursor is not None:
        response = client.post(
            "/app/v1/workspace/page", headers=headers,
            json={"limit": 50, "groups": ["experiments"], "cursors": {"experiments": cursor}},
        )
        assert response.status_code == 200
        page = response.json()
        assert len(page["experiments"]) <= 50
        assert page["knowledge"] == []
        batch = {item["record_id"] for item in page["experiments"]}
        assert not seen.intersection(batch)
        seen.update(batch)
        if not page["pagination"]["experiments"]["has_more"]:
            break
        cursor = page["pagination"]["experiments"]["cursor"]
    assert len(seen) == 125
    refreshed = client.get("/app/v1/workspace", headers=headers).json()
    assert refreshed["experiments"][0]["record_id"] == "experiment-new"


def test_workspace_page_rejects_unknown_group_and_cursor(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "state.db")
    client = TestClient(create_app(service, app_token="desktop-test"))
    headers = {"X-App-Token": "desktop-test"}
    invalid = client.post(
        "/app/v1/workspace/page", headers=headers,
        json={"groups": ["other"], "cursors": {}},
    )
    assert invalid.status_code == 422
    invalid = client.post(
        "/app/v1/workspace/page", headers=headers,
        json={"groups": ["experiments"], "cursors": {"datasets": {
            "updated_at": "2026-09-29T00:00:00Z", "record_id": "a",
        }}},
    )
    assert invalid.status_code == 422
