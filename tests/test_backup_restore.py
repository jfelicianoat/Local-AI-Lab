from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.maintenance.backup import create_backup, restore_backup, verify_backup


def test_coordinator_backup_restores_database_and_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "live"
    root.mkdir()
    service = CoordinatorService(root / "coordinator.db")
    report = service.run_controlled_retrieval_benchmark(k=3)
    archive = tmp_path / "backup.zip"
    manifest = create_backup(root / "coordinator.db", archive)

    assert verify_backup(archive) == manifest
    assert manifest["database"] == "coordinator.db"
    restored = tmp_path / "restored"
    assert restore_backup(archive, restored) == manifest
    recovered = CoordinatorService(restored / "coordinator.db")
    assert recovered.repository.product_record(report["record_id"]) == report
    assert recovered.product_artifact(report["record_id"])[0].read_bytes() == (
        service.product_artifact(report["record_id"])[0].read_bytes()
    )
    with pytest.raises(FileExistsError):
        restore_backup(archive, restored)


def test_restore_rejects_unsafe_manifest_path(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    manifest = {
        "format": "local-ai-lab.backup.v1", "database": "../coordinator.db",
        "files": [{"path": "../coordinator.db", "sha256": "0" * 64, "size": 0}],
    }
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("manifest.json", json.dumps(manifest))
        output.writestr("files/../coordinator.db", b"")
    with pytest.raises(ValueError, match="unsafe path"):
        restore_backup(archive, tmp_path / "target")
