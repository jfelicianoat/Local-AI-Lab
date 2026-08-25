from __future__ import annotations

import hashlib
import json
import os
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
    def __init__(self, root: Path) -> None:
        raw = str(root)
        if raw.startswith(("\\\\", "//")):
            raise ValueError("artifact store must be on a local filesystem")
        self.root = root.expanduser().resolve()
        self.blobs = self.root / "sha256"
        self.uploads = self.root / "uploads"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.uploads.mkdir(parents=True, exist_ok=True)

    def initiate(self, *, expected_sha256: str, expected_size: int, chunk_size: int) -> UploadManifest:
        _validate_digest(expected_sha256)
        if expected_size < 0:
            raise ValueError("expected_size cannot be negative")
        if chunk_size < 1 or chunk_size > 64 * 1024 * 1024:
            raise ValueError("chunk_size must be between 1 byte and 64 MiB")
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
        return manifest

    def put_chunk(
        self, *, artifact_id: str, index: int, content: bytes, chunk_sha256: str
    ) -> dict[str, object]:
        if index < 0:
            raise ValueError("chunk index cannot be negative")
        _validate_digest(chunk_sha256)
        manifest = self._manifest(artifact_id)
        actual = hashlib.sha256(content).hexdigest()
        if actual != chunk_sha256:
            raise ArtifactIntegrityError("chunk SHA-256 mismatch")
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
        manifest = self._manifest(artifact_id)
        directory = self._upload_dir(artifact_id)
        chunks = sorted(directory.glob("*.chunk"))
        expected_count = (
            0
            if manifest.expected_size == 0
            else (manifest.expected_size + manifest.chunk_size - 1) // manifest.chunk_size
        )
        indices = [int(path.stem) for path in chunks]
        if indices != list(range(expected_count)):
            raise ArtifactIntegrityError("upload is incomplete or has non-contiguous chunks")

        target = self.blob_path(manifest.expected_sha256)
        if target.exists():
            if target.stat().st_size != manifest.expected_size or _hash_file(target) != manifest.expected_sha256:
                raise ArtifactIntegrityError("existing CAS blob is corrupt")
            return self._committed(manifest, target, deduplicated=True)

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
        return self._committed(manifest, target, deduplicated=False)

    def blob_path(self, digest: str) -> Path:
        _validate_digest(digest)
        return self.blobs / digest[:2] / digest

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
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)

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
