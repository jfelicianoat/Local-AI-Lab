from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from local_ai_lab.artifacts.store import ArtifactIntegrityError, ArtifactStore


def test_chunked_upload_is_verified_and_committed_to_cas(tmp_path: Path) -> None:
    content = b"immutable-artifact-content"
    digest = hashlib.sha256(content).hexdigest()
    store = ArtifactStore(tmp_path / "artifacts")
    upload = store.initiate(expected_sha256=digest, expected_size=len(content), chunk_size=10)

    for index, start in enumerate(range(0, len(content), 10)):
        chunk = content[start : start + 10]
        result = store.put_chunk(
            artifact_id=upload.artifact_id,
            index=index,
            content=chunk,
            chunk_sha256=hashlib.sha256(chunk).hexdigest(),
        )
        assert result["replayed"] is False

    committed = store.commit(upload.artifact_id)
    assert committed["sha256"] == digest
    assert store.verify(digest)
    assert store.blob_path(digest).read_bytes() == content


def test_chunk_replay_is_idempotent_but_conflict_is_rejected(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    content = b"abc"
    upload = store.initiate(
        expected_sha256=hashlib.sha256(content).hexdigest(), expected_size=3, chunk_size=3
    )
    digest = hashlib.sha256(content).hexdigest()

    store.put_chunk(artifact_id=upload.artifact_id, index=0, content=content, chunk_sha256=digest)
    assert store.put_chunk(
        artifact_id=upload.artifact_id, index=0, content=content, chunk_sha256=digest
    )["replayed"] is True
    with pytest.raises(ArtifactIntegrityError):
        store.put_chunk(
            artifact_id=upload.artifact_id,
            index=0,
            content=b"xyz",
            chunk_sha256=hashlib.sha256(b"xyz").hexdigest(),
        )


def test_incomplete_or_corrupt_upload_cannot_commit(tmp_path: Path) -> None:
    content = b"six-bytes"
    store = ArtifactStore(tmp_path / "artifacts")
    upload = store.initiate(
        expected_sha256=hashlib.sha256(content).hexdigest(),
        expected_size=len(content),
        chunk_size=3,
    )
    first = content[:3]
    store.put_chunk(
        artifact_id=upload.artifact_id,
        index=0,
        content=first,
        chunk_sha256=hashlib.sha256(first).hexdigest(),
    )

    with pytest.raises(ArtifactIntegrityError, match="incomplete"):
        store.commit(upload.artifact_id)


def test_artifact_store_rejects_network_root_and_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ArtifactStore(Path(r"\\server\share\artifacts"))
    store = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError):
        store.put_chunk(
            artifact_id="../../escape",
            index=0,
            content=b"x",
            chunk_sha256=hashlib.sha256(b"x").hexdigest(),
        )
