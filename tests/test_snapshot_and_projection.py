from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path

import pytest

from local_ai_lab.knowledge_index.projection import KnowledgeIndex, KnowledgeIndexBuilder
from local_ai_lab.knowledge_index.snapshot import SnapshotBuilder, SnapshotError, SnapshotVerifier
from local_ai_lab.knowledge_index.vault import ReadOnlyVaultAdapter


def _vault(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "Vaults"
    vault = root / "Research"
    (vault / "sub").mkdir(parents=True)
    (vault / "Alpha.md").write_text(
        "---\nowner: Ana\n---\n# Decision\nUse local retrieval [[sub/Evidence#Proof]] #approved",
        encoding="utf-8",
    )
    (vault / "sub" / "Evidence.md").write_text(
        "# Proof\nControlled benchmark supports local retrieval.", encoding="utf-8"
    )
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "workspace.json").write_text('{"untouched":true}', encoding="utf-8")
    return root, vault


def _state(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*") if path.is_file()
    }


def _records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_snapshot_is_complete_reproducible_and_never_mutates_vault(tmp_path: Path) -> None:
    root, vault = _vault(tmp_path)
    before = _state(vault)
    adapter = ReadOnlyVaultAdapter(allowed_root=root, vault_root=vault)
    vault_id = str(uuid.uuid4())

    first = SnapshotBuilder().build(adapter, tmp_path / "snapshots", vault_id=vault_id)
    second = SnapshotBuilder().build(adapter, tmp_path / "snapshots", vault_id=vault_id)

    assert first.state == second.state == "COMPLETE"
    assert first.global_hash == second.global_hash
    assert _state(vault) == before
    assert [item["note_id"] for item in _records(first.path / "notes.jsonl")] == [
        item["note_id"] for item in _records(second.path / "notes.jsonl")
    ]
    assert [item["chunk_id"] for item in _records(first.path / "chunks.jsonl")] == [
        item["chunk_id"] for item in _records(second.path / "chunks.jsonl")
    ]
    assert SnapshotVerifier().verify(first.path)["manifest"]["counts"]["notes"] == 2
    assert {path.name for path in first.path.iterdir()} == {
        "manifest.json", "metadata.json", "hashes.json", "notes.jsonl",
        "chunks.jsonl", "links.jsonl", "objects",
    }


def test_snapshot_detects_non_converging_source_and_marks_incomplete(tmp_path: Path) -> None:
    root, vault = _vault(tmp_path)
    base = ReadOnlyVaultAdapter(allowed_root=root, vault_root=vault)

    class MutatingReader:
        vault_root = base.vault_root
        exclusions = base.exclusions

        def __init__(self) -> None:
            self.mutated = False

        def entries(self):
            return base.entries()

        def open_binary(self, relative_path: str):
            return base.open_binary(relative_path)

        def stat(self, relative_path: str):
            if not self.mutated:
                self.mutated = True
                (vault / relative_path).write_text("changed after read", encoding="utf-8")
            return base.stat(relative_path)

    result = SnapshotBuilder(file_retries=0, listing_retries=0).build(
        MutatingReader(), tmp_path / "snapshots", vault_id=str(uuid.uuid4())
    )

    assert result.state == "INCOMPLETE"
    assert result.holes
    assert SnapshotVerifier().verify(result.path)["manifest"]["state"] == "INCOMPLETE"


def test_verifier_rejects_tampered_record(tmp_path: Path) -> None:
    root, vault = _vault(tmp_path)
    result = SnapshotBuilder().build(
        ReadOnlyVaultAdapter(allowed_root=root, vault_root=vault),
        tmp_path / "snapshots",
        vault_id=str(uuid.uuid4()),
    )
    notes = result.path / "notes.jsonl"
    notes.chmod(0o644)
    notes.write_text(notes.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    with pytest.raises(SnapshotError, match="artifact hash mismatch"):
        SnapshotVerifier().verify(result.path)


def test_projection_is_regenerable_searchable_and_traceable(tmp_path: Path) -> None:
    root, vault = _vault(tmp_path)
    snapshot = SnapshotBuilder().build(
        ReadOnlyVaultAdapter(allowed_root=root, vault_root=vault),
        tmp_path / "snapshots",
        vault_id=str(uuid.uuid4()),
    )
    database = KnowledgeIndexBuilder().build(snapshot.path, tmp_path / "index" / "knowledge.sqlite3")
    hits = KnowledgeIndex(database).search("retrieval")

    assert hits
    assert hits[0].relative_path in {"Alpha.md", "sub/Evidence.md"}
    assert hits[0].evidence_reference.startswith(f"snapshot:sha256:{snapshot.global_hash}#chunk:")
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT count(*) FROM notes").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM links").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM tags").fetchone()[0] == 1
    finally:
        connection.close()
    with pytest.raises(FileExistsError):
        KnowledgeIndexBuilder().build(snapshot.path, database)


def test_incomplete_snapshot_is_not_accepted_as_complete_index(tmp_path: Path) -> None:
    root, vault = _vault(tmp_path)
    base = ReadOnlyVaultAdapter(allowed_root=root, vault_root=vault)

    class AlwaysChanging:
        vault_root = base.vault_root
        exclusions = base.exclusions

        def entries(self):
            entries = base.entries()
            target = vault / "Alpha.md"
            target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
            return entries

        def open_binary(self, relative_path: str):
            return base.open_binary(relative_path)

        def stat(self, relative_path: str):
            return base.stat(relative_path)

    snapshot = SnapshotBuilder(file_retries=0, listing_retries=0).build(
        AlwaysChanging(), tmp_path / "snapshots", vault_id=str(uuid.uuid4())
    )
    assert snapshot.state == "INCOMPLETE"
    with pytest.raises(SnapshotError, match="incomplete snapshot"):
        KnowledgeIndexBuilder().build(snapshot.path, tmp_path / "knowledge.sqlite3")


def test_incremental_index_records_added_changed_unchanged_and_removed_notes(tmp_path: Path) -> None:
    root, vault = _vault(tmp_path)
    adapter = ReadOnlyVaultAdapter(allowed_root=root, vault_root=vault)
    vault_id = str(uuid.uuid4())
    first_snapshot = SnapshotBuilder().build(adapter, tmp_path / "snapshots", vault_id=vault_id)
    first_database = KnowledgeIndexBuilder().build(first_snapshot.path, tmp_path / "index-v1.sqlite3")
    (vault / "Alpha.md").write_text("# Decision\nChanged content", encoding="utf-8")
    (vault / "sub" / "Evidence.md").unlink()
    (vault / "New.md").write_text("# New\nStable note", encoding="utf-8")
    second_snapshot = SnapshotBuilder().build(adapter, tmp_path / "snapshots", vault_id=vault_id)
    second_database = KnowledgeIndexBuilder().build(
        second_snapshot.path, tmp_path / "index-v2.sqlite3", previous_database=first_database
    )
    connection = sqlite3.connect(second_database)
    try:
        audit = json.loads(
            connection.execute(
                "SELECT value FROM build_metadata WHERE key='incremental_audit'"
            ).fetchone()[0]
        )
    finally:
        connection.close()

    assert audit["mode"] == "generational_incremental"
    assert audit["added"] == ["New.md"]
    assert audit["changed"] == ["Alpha.md"]
    assert audit["removed"] == ["sub/Evidence.md"]
    assert audit["previous_snapshot_hash"] == first_snapshot.global_hash


def test_snapshot_preserves_accents_in_notes_that_are_not_utf8(tmp_path: Path) -> None:
    """Un vault real de Windows mezcla UTF-8 con cp1252 heredado.

    Decodificarlo todo como UTF-8 con reemplazo no falla: destruye cada acento en
    silencio, y con él la fidelidad del snapshot, el índice léxico y toda cita.
    """
    root = tmp_path / "Vaults"
    vault = root / "Mixto"
    vault.mkdir(parents=True)
    (vault / "Utf8.md").write_text("# Sección\n\nGestión de modelos.", encoding="utf-8")
    (vault / "Legacy.md").write_bytes("# Título\n\nInversión y estacionalidad.".encode("cp1252"))

    snapshot = SnapshotBuilder().build(
        ReadOnlyVaultAdapter(allowed_root=root, vault_root=vault),
        tmp_path / "snapshots", vault_id=str(uuid.uuid4()),
    )

    chunks = [
        json.loads(line)
        for line in (snapshot.path / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    notes = {
        json.loads(line)["relative_path"]: json.loads(line)
        for line in (snapshot.path / "notes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }

    rendered = json.dumps(chunks, ensure_ascii=False)
    assert "�" not in rendered
    assert "Título" in rendered
    assert "Inversión" in rendered
    assert "Sección" in rendered

    assert notes["Utf8.md"]["text_encoding"] == "utf-8"
    assert notes["Legacy.md"]["text_encoding"] == "cp1252"
    assert json.loads((snapshot.path / "manifest.json").read_text(encoding="utf-8"))["holes"] == []
