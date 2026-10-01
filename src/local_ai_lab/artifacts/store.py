from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO

from local_ai_lab.domain.common import canonical_json, new_id, utc_timestamp


class ArtifactIntegrityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class UploadManifest:
    schema_version: str
    artifact_id: str
    expected_sha256: str
    expected_size: int
    chunk_size: int
    created_at: str


class ArtifactStore:
    def __init__(self, root: Path, *, quota_bytes: int | None = None) -> None:
        raw = str(root)
        if raw.startswith(("\\\\", "//")):
            raise ValueError("artifact store must be on a local filesystem")
        self.root = root.expanduser().resolve()
        self.blobs = self.root / "sha256"
        self.uploads = self.root / "uploads"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.uploads.mkdir(parents=True, exist_ok=True)
        if self.blobs.resolve() != self.blobs or self.uploads.resolve() != self.uploads:
            raise ValueError("artifact directories must not be links")
        configured = quota_bytes if quota_bytes is not None else os.environ.get(
            "LOCAL_AI_LAB_ARTIFACT_QUOTA_BYTES", str(100 * 1024**3)
        )
        try:
            self.quota_bytes = int(configured)
        except (TypeError, ValueError) as error:
            raise ValueError("artifact quota must be a positive number of bytes") from error
        if self.quota_bytes <= 0:
            raise ValueError("artifact quota must be a positive number of bytes")
        self._quota_lock = threading.RLock()

    def usage(self) -> dict[str, int]:
        with self._quota_lock:
            return self._usage()

    @contextmanager
    def maintenance_lock(self):
        """Serialize maintenance with writes to this store."""
        with self._quota_lock:
            yield

    def _usage(self) -> dict[str, int]:
        committed = sum(path.stat().st_size for path in self.blobs.rglob("*")
                        if path.is_file() and not path.is_symlink())
        pending = 0
        temporary = 0
        for directory in self.uploads.iterdir():
            if directory.is_symlink() or not directory.is_dir():
                continue
            has_chunks = False
            for chunk in directory.glob("*.chunk"):
                has_chunks = True
                temporary += chunk.stat().st_size
            try:
                manifest = self._manifest(directory.name)
            except (ValueError, ArtifactIntegrityError):
                continue
            blob_exists = self.blob_path(manifest.expected_sha256).exists()
            if not (blob_exists and ((directory / "committed.json").exists() or not has_chunks)):
                pending += manifest.expected_size
        cleanup_pending = sum(path.stat().st_size for path in
            (self.root / "cleanup-trash").rglob("*")
            if path.is_file() and not path.is_symlink())
        return {
            "quota_bytes": self.quota_bytes,
            "committed_bytes": committed,
            "pending_reserved_bytes": pending,
            "temporary_chunk_bytes": temporary,
            "available_quota_bytes": max(0, self.quota_bytes - committed - pending - cleanup_pending),
            "free_disk_bytes": shutil.disk_usage(self.root).free,
            "cleanup_pending_bytes": cleanup_pending,
        }

    def initiate(self, *, expected_sha256: str, expected_size: int, chunk_size: int) -> UploadManifest:
        _validate_digest(expected_sha256)
        if expected_size < 0:
            raise ValueError("expected_size cannot be negative")
        if chunk_size < 1 or chunk_size > 64 * 1024 * 1024:
            raise ValueError("chunk_size must be between 1 byte and 64 MiB")
        with self._quota_lock:
            usage = self.usage()
            existing = self.blob_path(expected_sha256)
            deduplicated = existing.exists()
            if deduplicated and (existing.stat().st_size != expected_size or _hash_file(existing) != expected_sha256):
                raise ArtifactIntegrityError("existing CAS blob is corrupt")
            if not deduplicated and expected_size > usage["available_quota_bytes"]:
                raise ValueError("artifact store quota exceeded")
            if not deduplicated and expected_size * 2 > usage["free_disk_bytes"]:
                raise ValueError("insufficient disk space for artifact upload and assembly")
            manifest = UploadManifest(
                schema_version="local-ai-lab.artifact-upload.v1",
                artifact_id=new_id(),
                expected_sha256=expected_sha256,
                expected_size=expected_size,
                chunk_size=chunk_size,
                created_at=utc_timestamp(),
            )
            directory = self.uploads / manifest.artifact_id
            directory.mkdir()
            self._atomic_text(directory / "manifest.json", canonical_json(asdict(manifest)))
            if deduplicated:
                self._atomic_text(directory / "committed.json", canonical_json({"sha256": expected_sha256}))
        return manifest

    def put_chunk(
        self, *, artifact_id: str, index: int, content: bytes, chunk_sha256: str
    ) -> dict[str, object]:
        with self._quota_lock:
            return self._put_chunk(artifact_id=artifact_id, index=index, content=content,
                                   chunk_sha256=chunk_sha256)

    def _put_chunk(
        self, *, artifact_id: str, index: int, content: bytes, chunk_sha256: str
    ) -> dict[str, object]:
        if index < 0:
            raise ValueError("chunk index cannot be negative")
        _validate_digest(chunk_sha256)
        manifest = self._manifest(artifact_id)
        expected_count = (
            0 if manifest.expected_size == 0 else
            (manifest.expected_size + manifest.chunk_size - 1) // manifest.chunk_size
        )
        if index >= expected_count:
            raise ArtifactIntegrityError("chunk index exceeds declared artifact size")
        expected_length = min(manifest.chunk_size, manifest.expected_size - index * manifest.chunk_size)
        if len(content) != expected_length:
            raise ArtifactIntegrityError("chunk length does not match declared artifact size")
        actual = hashlib.sha256(content).hexdigest()
        if actual != chunk_sha256:
            raise ArtifactIntegrityError("chunk SHA-256 mismatch")
        if (self._upload_dir(artifact_id) / "committed.json").exists():
            return {"index": index, "sha256": actual, "replayed": True}
        existing = self.blob_path(manifest.expected_sha256)
        if existing.exists():
            if existing.stat().st_size != manifest.expected_size or _hash_file(existing) != manifest.expected_sha256:
                raise ArtifactIntegrityError("existing CAS blob is corrupt")
            self._atomic_text(self._upload_dir(artifact_id) / "committed.json",
                              canonical_json({"sha256": manifest.expected_sha256}))
            self._discard_committed_chunks(self._upload_dir(artifact_id))
            return {"index": index, "sha256": actual, "replayed": True}
        if len(content) > manifest.chunk_size:
            raise ArtifactIntegrityError("chunk exceeds negotiated size")
        path = self._upload_dir(artifact_id) / f"{index:08d}.chunk"
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != actual:
                raise ArtifactIntegrityError("chunk index already contains different content")
            return {"index": index, "sha256": actual, "replayed": True}
        self._atomic_bytes(path, content)
        return {"index": index, "sha256": actual, "replayed": False}

    def commit(self, artifact_id: str) -> dict[str, object]:
        with self._quota_lock:
            return self._commit(artifact_id)

    def _commit(self, artifact_id: str) -> dict[str, object]:
        manifest = self._manifest(artifact_id)
        directory = self._upload_dir(artifact_id)
        target = self.blob_path(manifest.expected_sha256)
        if target.exists():
            if target.stat().st_size != manifest.expected_size or _hash_file(target) != manifest.expected_sha256:
                raise ArtifactIntegrityError("existing CAS blob is corrupt")
            if not (directory / "committed.json").exists():
                self._atomic_text(directory / "committed.json", canonical_json({"sha256": manifest.expected_sha256}))
            self._discard_committed_chunks(directory)
            return self._committed(manifest, target, deduplicated=True)
        chunks = sorted(directory.glob("*.chunk"))
        expected_count = (
            0
            if manifest.expected_size == 0
            else (manifest.expected_size + manifest.chunk_size - 1) // manifest.chunk_size
        )
        indices = [int(path.stem) for path in chunks]
        if indices != list(range(expected_count)):
            raise ArtifactIntegrityError("upload is incomplete or has non-contiguous chunks")

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + f".{artifact_id}.tmp")
        digest = hashlib.sha256()
        size = 0
        with temporary.open("xb") as output:
            for chunk in chunks:
                with chunk.open("rb") as source:
                    size += _copy_and_hash(source, output, digest)
            output.flush()
            os.fsync(output.fileno())
        if size != manifest.expected_size or digest.hexdigest() != manifest.expected_sha256:
            quarantine = temporary.with_suffix(temporary.suffix + ".invalid")
            temporary.replace(quarantine)
            raise ArtifactIntegrityError("assembled artifact does not match its manifest")
        temporary.replace(target)
        self._atomic_text(directory / "committed.json", canonical_json({"sha256": manifest.expected_sha256}))
        self._discard_committed_chunks(directory)
        return self._committed(manifest, target, deduplicated=False)

    @staticmethod
    def _discard_committed_chunks(directory: Path) -> None:
        for chunk in directory.glob("*.chunk"):
            chunk.unlink()

    def blob_path(self, digest: str) -> Path:
        _validate_digest(digest)
        path = self.blobs / digest[:2] / digest
        if path.resolve() != path:
            raise ValueError("artifact path must not traverse a link")
        return path

    def verify(self, digest: str) -> bool:
        path = self.blob_path(digest)
        return path.is_file() and _hash_file(path) == digest

    def ingest_file(self, source: Path, *, chunk_size: int = 4 * 1024 * 1024) -> dict[str, object]:
        path = source.resolve(strict=True)
        if not path.is_file() or str(path).startswith(("\\\\", "//")):
            raise ValueError("artifact ingestion requires a local file")
        digest = _hash_file(path)
        manifest = self.initiate(
            expected_sha256=digest, expected_size=path.stat().st_size, chunk_size=chunk_size
        )
        with path.open("rb") as stream:
            index = 0
            while content := stream.read(chunk_size):
                self.put_chunk(
                    artifact_id=manifest.artifact_id, index=index, content=content,
                    chunk_sha256=hashlib.sha256(content).hexdigest(),
                )
                index += 1
        return self.commit(manifest.artifact_id)

    def _manifest(self, artifact_id: str) -> UploadManifest:
        path = self._upload_dir(artifact_id) / "manifest.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return UploadManifest(**payload)
        except (OSError, json.JSONDecodeError, TypeError) as error:
            raise ArtifactIntegrityError("upload manifest is missing or invalid") from error

    def _upload_dir(self, artifact_id: str) -> Path:
        if not artifact_id or any(character not in "0123456789abcdef-" for character in artifact_id):
            raise ValueError("invalid artifact_id")
        path = (self.uploads / artifact_id).resolve()
        if path.parent != self.uploads:
            raise ValueError("artifact path escapes upload root")
        return path

    @staticmethod
    def _atomic_bytes(path: Path, content: bytes) -> None:
        temporary = path.with_name(path.name + f".{new_id()}.tmp")
        try:
            with temporary.open("xb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _atomic_text(cls, path: Path, content: str) -> None:
        cls._atomic_bytes(path, content.encode("utf-8"))

    @staticmethod
    def _committed(
        manifest: UploadManifest, target: Path, *, deduplicated: bool
    ) -> dict[str, object]:
        return {
            "artifact_id": manifest.artifact_id,
            "sha256": manifest.expected_sha256,
            "size": manifest.expected_size,
            "cas_path": str(target),
            "deduplicated": deduplicated,
            "committed": True,
        }


def _validate_digest(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("SHA-256 must be 64 lowercase hexadecimal characters")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _copy_and_hash(source: BinaryIO, target: BinaryIO, digest: object) -> int:
    size = 0
    while block := source.read(1024 * 1024):
        target.write(block)
        digest.update(block)  # type: ignore[attr-defined]
        size += len(block)
    return size
