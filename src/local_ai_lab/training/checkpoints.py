"""Portable, integrity-checked Trainer checkpoints for explicit recovery."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from local_ai_lab.domain.common import canonical_json


SCHEMA_VERSION = "training-checkpoint.v1"
_MODEL_FILES = {"adapter_model.safetensors", "adapter_model.bin", "model.safetensors", "pytorch_model.bin"}
_REQUIRED_FILES = {"trainer_state.json", "optimizer.pt", "scheduler.pt"}
_METADATA_KEYS = {
    "source_job_id", "source_attempt_id", "source_lease_generation",
    "source_spec_sha256", "training_kind", "dataset_fingerprint",
    "model_id", "base_weights_sha256", "chat_template_fingerprint",
}


def _digest_stream(stream: Any) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while block := stream.read(1024 * 1024):
        digest.update(block)
        size += len(block)
    return digest.hexdigest(), size


def _checked_files(names: set[str]) -> None:
    basenames = {PurePosixPath(name).name for name in names}
    model_present = bool(basenames.intersection(_MODEL_FILES)) or any(
        name.startswith(("model-", "pytorch_model-"))
        and name.endswith((".safetensors", ".bin")) for name in basenames
    )
    if not _REQUIRED_FILES.issubset(basenames) or not model_present:
        raise ValueError("checkpoint lacks Trainer state, optimizer, scheduler or model weights")


def _validate_metadata(metadata: dict[str, Any]) -> None:
    if (set(metadata) != _METADATA_KEYS
            or not isinstance(metadata["training_kind"], str)
            or metadata["training_kind"] not in {
        "training.lora.v1", "training.distillation.v1",
    }):
        raise ValueError("checkpoint provenance is incomplete")
    for key in ("source_spec_sha256", "dataset_fingerprint", "base_weights_sha256", "chat_template_fingerprint"):
        value = metadata[key]
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError(f"checkpoint {key} is not SHA-256")
    if (any(not isinstance(metadata[key], str) or not metadata[key]
            for key in ("source_job_id", "source_attempt_id", "model_id"))
            or type(metadata["source_lease_generation"]) is not int
            or metadata["source_lease_generation"] < 1):
        raise ValueError("checkpoint attempt identity is invalid")


def create_checkpoint_bundle(
    checkpoint: Path, destination: Path, *, metadata: dict[str, Any], step: int,
) -> tuple[Path, str]:
    source = checkpoint.resolve(strict=True)
    target = destination.resolve()
    if (not source.is_dir() or target.exists() or type(step) is not int or step < 1
            or source.name != f"checkpoint-{step}"
            or source == target or source in target.parents
            or str(source).startswith(("\\\\", "//"))
            or str(target).startswith(("\\\\", "//"))):
        raise ValueError("checkpoint bundle requires a new local destination and numbered checkpoint")
    files = sorted(path for path in source.rglob("*") if path.is_file())
    if not files or len(files) > 10000 or any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("checkpoint has no regular files or contains links")
    names = {path.relative_to(source).as_posix() for path in files}
    _checked_files(names)
    state = json.loads((source / "trainer_state.json").read_text(encoding="utf-8"))
    if not isinstance(state, dict) or type(state.get("global_step")) is not int or state["global_step"] != step:
        raise ValueError("checkpoint Trainer step does not match its directory")
    _validate_metadata(metadata)
    if metadata["training_kind"] == "training.distillation.v1" and not {
        "distilled-train.jsonl", "teacher-evidence.json",
    }.issubset(names):
        raise ValueError("distillation checkpoint lacks exact teacher supervision")
    manifest = {"schema_version": SCHEMA_VERSION, **metadata, "step": step, "files": []}
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + f".{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                relative = path.relative_to(source).as_posix()
                member_name = f"checkpoint-{step}/{relative}"
                info = zipfile.ZipInfo(member_name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                digest = hashlib.sha256()
                size = 0
                with path.open("rb") as input_stream, archive.open(info, "w") as output_stream:
                    while block := input_stream.read(1024 * 1024):
                        output_stream.write(block)
                        digest.update(block)
                        size += len(block)
                manifest["files"].append({"path": member_name, "sha256": digest.hexdigest(), "size": size})
            archive.writestr("checkpoint-manifest.json", canonical_json(manifest) + "\n")
        if target.exists():
            raise ValueError("checkpoint bundle destination already exists")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    with target.open("rb") as stream:
        digest, _ = _digest_stream(stream)
    return target, digest


def verify_checkpoint_bundle(path: Path, *, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path.resolve(strict=True)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or "checkpoint-manifest.json" not in names:
                raise ValueError("checkpoint archive has duplicate entries or no manifest")
            if sum(info.file_size for info in infos) > 100 * 1024**3:
                raise ValueError("checkpoint archive exceeds the size limit")
            if any(info.is_dir() or info.filename.startswith("/")
                   or "\\" in info.filename or ".." in PurePosixPath(info.filename).parts
                   or (info.external_attr >> 16) & 0o170000 == 0o120000
                   for info in infos):
                raise ValueError("checkpoint archive contains an unsafe member")
            manifest_info = archive.getinfo("checkpoint-manifest.json")
            if manifest_info.file_size > 1024 * 1024:
                raise ValueError("checkpoint manifest is too large")
            manifest = json.loads(archive.read(manifest_info))
            if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("checkpoint manifest schema is invalid")
            if set(manifest) != _METADATA_KEYS | {"schema_version", "step", "files"}:
                raise ValueError("checkpoint manifest fields are invalid")
            _validate_metadata({key: manifest.get(key) for key in _METADATA_KEYS})
            if expected and any(manifest.get(key) != value for key, value in expected.items()):
                raise ValueError("checkpoint provenance differs from the approved source")
            step = manifest.get("step")
            if type(step) is not int or step < 1:
                raise ValueError("checkpoint step is invalid")
            listed = manifest.get("files")
            if not isinstance(listed, list) or len(listed) > 10000:
                raise ValueError("checkpoint manifest file list is invalid")
            if any(not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}
                   or not isinstance(item["path"], str)
                   or not isinstance(item["sha256"], str)
                   or len(item["sha256"]) != 64
                   or any(char not in "0123456789abcdef" for char in item["sha256"])
                   for item in listed):
                raise ValueError("checkpoint manifest file entry is invalid")
            by_path = {item["path"]: item for item in listed}
            actual = set(names) - {"checkpoint-manifest.json"}
            if len(by_path) != len(listed) or set(by_path) != actual:
                raise ValueError("checkpoint files differ from the manifest")
            if any(not isinstance(name, str) or not name.startswith(f"checkpoint-{step}/")
                   for name in actual):
                raise ValueError("checkpoint member is outside the numbered directory")
            _checked_files({name.removeprefix(f"checkpoint-{step}/") for name in actual})
            if manifest["training_kind"] == "training.distillation.v1" and not {
                f"checkpoint-{step}/distilled-train.jsonl",
                f"checkpoint-{step}/teacher-evidence.json",
            }.issubset(actual):
                raise ValueError("distillation checkpoint lacks exact teacher supervision")
            for name, item in by_path.items():
                if type(item.get("size")) is not int or item["size"] < 0:
                    raise ValueError("checkpoint member size is invalid")
                if archive.getinfo(name).file_size != item["size"]:
                    raise ValueError("checkpoint member size differs from the manifest")
                with archive.open(name) as stream:
                    digest, size = _digest_stream(stream)
                if digest != item.get("sha256") or size != item["size"]:
                    raise ValueError("checkpoint member hash or size differs from the manifest")
            state_name = f"checkpoint-{step}/trainer_state.json"
            state_info = archive.getinfo(state_name)
            if state_info.file_size > 1024 * 1024:
                raise ValueError("checkpoint Trainer state is too large")
            state = json.loads(archive.read(state_info))
            if not isinstance(state, dict) or type(state.get("global_step")) is not int or state["global_step"] != step:
                raise ValueError("checkpoint Trainer state has a different step")
            return manifest
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
        raise ValueError("checkpoint archive is unreadable") from error
