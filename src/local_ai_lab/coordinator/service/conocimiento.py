"""Vaults e indices de conocimiento.

El vault se lee siempre en solo lectura y a traves de un adaptador: el
laboratorio nunca escribe en las notas de nadie.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from local_ai_lab.knowledge_index.projection import KnowledgeIndexBuilder
from local_ai_lab.knowledge_index.snapshot import SnapshotBuilder, SnapshotVerifier
from local_ai_lab.knowledge_index.vault import ReadOnlyVaultAdapter, discover_vaults
from local_ai_lab.coordinator.service.producto import ProductoMixin


class ConocimientoMixin(ProductoMixin):
    """Vaults e indices de conocimiento."""

    def discover_vaults(self, *, allowed_root: Path) -> list[str]:
        return discover_vaults(allowed_root)

    def create_vault_snapshot(self, *, allowed_root: Path, vault_name: str) -> dict[str, Any]:
        if not vault_name.strip() or vault_name in {".", ".."} or any(char in vault_name for char in ("/", "\\")):
            raise ValueError("vault name must be a direct child name")
        vault = allowed_root / vault_name
        adapter = ReadOnlyVaultAdapter(allowed_root=allowed_root, vault_root=vault)
        result = SnapshotBuilder().build(adapter, self.repository.path.parent / "snapshots")
        manifest = SnapshotVerifier().verify(result.path)["manifest"]
        self.record_product_item(
            record_id=result.snapshot_id, category="snapshot", title=f"Snapshot {vault_name}",
            status=result.state, artifact_sha256=result.global_hash,
            summary={
                "vault": vault_name, "notes": manifest["counts"]["notes"],
                "chunks": manifest["counts"]["chunks"], "holes": manifest["counts"]["holes"],
                "read_only": True,
            },
        )
        self.repository.record_artifact_location(
            record_id=result.snapshot_id, artifact_kind="vault_snapshot",
            local_path=result.path, artifact_sha256=result.global_hash,
        )
        return next(
            record for record in self.product_workspace()["knowledge"]
            if record["record_id"] == result.snapshot_id
        )

    def create_knowledge_index(
        self, *, snapshot_id: str, previous_index_id: str | None = None
    ) -> dict[str, Any]:
        snapshot = self.repository.artifact_location(snapshot_id, expected_kind="vault_snapshot")
        previous = (
            self.repository.artifact_location(previous_index_id, expected_kind="knowledge_index")
            if previous_index_id else None
        )
        index_id = str(uuid.uuid4())
        target = self.repository.path.parent / "indexes" / f"knowledge-{index_id}.sqlite3"
        built = KnowledgeIndexBuilder().build(snapshot, target, previous_database=previous)
        digest = hashlib.sha256(built.read_bytes()).hexdigest()
        verified = SnapshotVerifier().verify(snapshot)
        self.record_product_item(
            record_id=index_id, category="index", title="Índice de conocimiento",
            status="READY", artifact_sha256=digest,
            summary={
                "snapshot_id": snapshot_id,
                "snapshot_hash": verified["manifest"]["global_hash"],
                "engine": "SQLite FTS5", "regenerable": True,
                "incremental": previous_index_id is not None,
            },
        )
        self.repository.record_artifact_location(
            record_id=index_id, artifact_kind="knowledge_index", local_path=built,
            artifact_sha256=digest,
        )
        return next(
            record for record in self.product_workspace()["knowledge"]
            if record["record_id"] == index_id
        )
