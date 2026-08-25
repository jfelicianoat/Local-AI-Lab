from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from local_ai_lab.domain.common import canonical_json, publish_directory, sha256_json, utc_timestamp

EXPORT_FORMAT = "local-ai-lab.export-package.v1"
ALLOWED_KINDS = {"adapter", "merged_model", "safetensors", "gguf", "tokenizer", "chat_template"}


class ExportError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ExportArtifact:
    kind: str
    path: Path
    sha256: str
    license_id: str
    source_reference: str


@dataclass(frozen=True, slots=True)
class ExportPackageResult:
    path: Path
    package_id: str
    fingerprint: str


class ExportPackageBuilder:
    def build(
        self,
        artifacts: Sequence[ExportArtifact],
        output_root: Path,
        *,
        source_training_manifest_sha256: str,
        serving: dict[str, Any],
    ) -> ExportPackageResult:
        if not artifacts or any(item.kind not in ALLOWED_KINDS for item in artifacts):
            raise ValueError("export requires one or more supported artifact kinds")
        if len(source_training_manifest_sha256) != 64:
            raise ValueError("training manifest requires SHA-256")
        self._reject_secrets(serving)
        root = output_root.resolve()
        if str(root).startswith(("\\\\", "//")):
            raise ExportError("export package must be built on local storage")
        root.mkdir(parents=True, exist_ok=True)
        package_id = str(uuid.uuid4())
        staging = root / f".staging-export_{package_id}"
        final = root / f"export_{package_id}"
        staging.mkdir(exist_ok=False)
        artifact_root = staging / "artifacts"
        artifact_root.mkdir()
        records: list[dict[str, Any]] = []
        names: set[str] = set()
        for artifact in artifacts:
            source = artifact.path.resolve(strict=True)
            if not source.is_file() or _sha(source) != artifact.sha256:
                raise ExportError(f"source artifact hash mismatch: {artifact.kind}")
            if not artifact.license_id.strip() or not artifact.source_reference.strip():
                raise ValueError("every export artifact requires license and provenance")
            filename = f"{artifact.kind}-{source.name}"
            if filename in names:
                raise ValueError("export artifact names must be unique")
            names.add(filename)
            target = artifact_root / filename
            shutil.copyfile(source, target)
            if _sha(target) != artifact.sha256:
                raise ExportError(f"copied artifact verification failed: {artifact.kind}")
            records.append(
                {
                    "kind": artifact.kind, "filename": f"artifacts/{filename}",
                    "sha256": artifact.sha256, "size": target.stat().st_size,
                    "license_id": artifact.license_id, "source_reference": artifact.source_reference,
                }
            )
        records.sort(key=lambda item: (item["kind"], item["filename"]))
        fingerprint = sha256_json(
            {
                "format": EXPORT_FORMAT,
                "training_manifest_sha256": source_training_manifest_sha256,
                "artifacts": records,
                "serving": serving,
            }
        )
        manifest = {
            "format": EXPORT_FORMAT, "package_id": package_id, "created_at": utc_timestamp(),
            "fingerprint": fingerprint, "training_manifest_sha256": source_training_manifest_sha256,
            "artifacts": records, "serving": serving,
        }
        (staging / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8", newline="\n")
        publish_directory(staging, final)
        ExportPackageVerifier().verify(final)
        return ExportPackageResult(final, package_id, fingerprint)

    @classmethod
    def _reject_secrets(cls, value: Any, path: str = "serving") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if any(marker in str(key).casefold() for marker in ("secret", "token", "password", "credential", "api_key")):
                    raise ValueError(f"serving manifest cannot contain secret field: {path}.{key}")
                cls._reject_secrets(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                cls._reject_secrets(child, f"{path}[{index}]")


class ExportPackageVerifier:
    def verify(self, path: Path) -> dict[str, Any]:
        root = path.resolve(strict=True)
        try:
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ExportError("invalid export manifest") from error
        if manifest.get("format") != EXPORT_FORMAT:
            raise ExportError("unsupported export package format")
        expected_fingerprint = sha256_json(
            {
                "format": manifest["format"],
                "training_manifest_sha256": manifest["training_manifest_sha256"],
                "artifacts": manifest["artifacts"],
                "serving": manifest["serving"],
            }
        )
        if expected_fingerprint != manifest.get("fingerprint"):
            raise ExportError("export package fingerprint mismatch")
        for artifact in manifest["artifacts"]:
            candidate = (root / artifact["filename"]).resolve(strict=True)
            try:
                candidate.relative_to(root)
            except ValueError as error:
                raise ExportError("export artifact path escapes package") from error
            if _sha(candidate) != artifact["sha256"] or candidate.stat().st_size != artifact["size"]:
                raise ExportError(f"export artifact verification failed: {artifact['filename']}")
        return manifest
