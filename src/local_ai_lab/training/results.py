"""Validate portable ML results before they become product or capability evidence.

This verifies the authenticated Worker's package and its consistency with the job.
It does not independently attest that GPU computation took place.
"""
from __future__ import annotations

import hashlib
import json
import math
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from local_ai_lab.domain.common import sha256_json
from local_ai_lab.exporting.package import EXPORT_FORMAT, ExportPackageBuilder

RESULT_CONTRACT_VERSION = 1
ML_RESULTS = {
    "training.preflight.v1": ("training_preflight", "preflight-manifest.json", "training-preflight.v1"),
    "training.lora.v1": ("training_result", "training-manifest.json", "training-result.v1"),
    "training.distillation.v1": ("training_result", "distillation-manifest.json", "distillation-result.v1"),
    "model.export.v1": ("export_package", "manifest.json", EXPORT_FORMAT),
}
PREFLIGHT_CHECKS = {
    "overfit_8_examples", "save", "reload", "resume", "contamination_check", "manifest_check",
}
CONTRACT_CHECKS = {
    "c1_assistant_only_loss", "c2_supervised_eos", "c3_same_chat_template",
    "c4_assistant_not_truncated", "c5_padding_outside_loss", "c6_seed_and_nondeterminism_recorded",
}


def result_file_inventory(root: Path) -> list[dict[str, Any]]:
    return [{"relative_path": path.relative_to(root).as_posix(), "size": path.stat().st_size,
             "sha256": _file_digest(path)} for path in sorted(root.rglob("*")) if path.is_file()]


def _file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _same(actual: Any, expected: Any, field: str) -> None:
    # bool is an int in Python; use canonical JSON for strict protocol types.
    if sha256_json(actual) != sha256_json(expected):
        raise ValueError(f"result manifest has a different {field}")


def _finite_metrics(value: Any) -> None:
    if (not isinstance(value, dict) or not value
            or any(not isinstance(key, str) or type(item) not in {int, float}
                   or not math.isfinite(item) for key, item in value.items())):
        raise ValueError("result metrics must be finite numbers")


def _json_object(archive: zipfile.ZipFile, name: str) -> tuple[dict, bytes]:
    info = archive.getinfo(name)
    if info.file_size > 20 * 1024**2:
        raise ValueError("result manifest exceeds the validation limit")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("result JSON has duplicate keys")
            result[key] = value
        return result
    data = archive.read(info)
    value = json.loads(data, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("result manifest must be an object")
    return value, data


def _files(archive: zipfile.ZipFile, manifest: dict, manifest_name: str, *, export: bool) -> set[str]:
    listed = manifest.get("artifacts" if export else "files")
    key = "filename" if export else "relative_path"
    if not isinstance(listed, list) or not listed or len(listed) > 10000:
        raise ValueError("result file inventory is invalid")
    if any(not isinstance(item, dict) or not isinstance(item.get(key), str)
           or not _sha(item.get("sha256")) or type(item.get("size")) is not int or item["size"] < 0
           for item in listed):
        raise ValueError("result file descriptor is invalid")
    by_name = {item[key]: item for item in listed}
    actual = {info.filename for info in archive.infolist() if not info.is_dir()} - {manifest_name}
    if len(by_name) != len(listed) or set(by_name) != actual:
        raise ValueError("result files differ from the manifest inventory")
    for name, item in by_name.items():
        if archive.getinfo(name).file_size != item["size"]:
            raise ValueError("result member size differs from the manifest")
        with archive.open(name) as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise ValueError("result member hash differs from the manifest")
    if not export:
        if ("adapter/adapter_config.json" not in actual
                or not any(name.startswith("adapter/") and name.endswith(".safetensors") for name in actual)
                or "tokenizer/tokenizer_config.json" not in actual):
            raise ValueError("result package lacks the saved adapter or tokenizer")
    return actual


def verify_ml_result(path: Path, *, job: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    spec = json.loads(job["spec_json"])
    inputs = spec["payload"]
    kind = spec["kind"]
    _, name, schema = ML_RESULTS[kind]
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or len(names) > 10001:
                raise ValueError("result archive has duplicate entries or too many members")
            if sum(info.file_size for info in infos) > 100 * 1024**3:
                raise ValueError("result archive exceeds the validation limit")
            if any(not info.filename or "\\" in info.filename or ":" in info.filename
                   or info.filename.startswith("/") or ".." in PurePosixPath(info.filename).parts
                   or (info.external_attr >> 16) & 0o170000 == 0o120000 for info in infos):
                raise ValueError("result archive contains an unsafe member")
            manifest, raw = _json_object(archive, name)
            export = kind == "model.export.v1"
            if manifest.get("format" if export else "schema_version") != schema:
                raise ValueError("result manifest schema is invalid")
            _same(manifest.get("source_attempt"), {
                "source_job_id": job["job_id"], "source_attempt_id": job["attempt_id"],
                "source_lease_generation": job["lease_generation"],
                "source_spec_sha256": job["spec_fingerprint"], "training_kind": kind,
            }, "authorized attempt")
            if export:
                _validate_export(manifest, inputs, result)
            else:
                content = {key: value for key, value in manifest.items() if key != "content_sha256"}
                digest = sha256_json(content)
                if digest != manifest.get("content_sha256"):
                    raise ValueError("result manifest content hash is invalid")
                _same(digest, result.get("preflight_sha256" if kind == "training.preflight.v1" else "manifest_sha256"), "manifest hash")
                if kind != "training.preflight.v1":
                    _same(hashlib.sha256(raw).hexdigest(), result.get("manifest_file_sha256"), "manifest file hash")
                for field in ("seed", "dtype", "max_length", "lora_config"):
                    _same(manifest.get(field), inputs.get(field, 4096 if field == "max_length" else None), field)
                if not _sha(manifest.get("chat_template_fingerprint")):
                    raise ValueError("result chat template fingerprint is invalid")
                if manifest.get("dtype") not in {"bf16", "fp16"} or type(manifest.get("seed")) is not int:
                    raise ValueError("result dtype or seed is invalid")
                if (type(manifest.get("max_length")) is not int or manifest["max_length"] <= 0
                        or not isinstance(manifest.get("lora_config"), dict)
                        or type(manifest["lora_config"].get("rank")) is not int
                        or not 1 <= manifest["lora_config"]["rank"] <= 1024):
                    raise ValueError("result sequence length or LoRA configuration is invalid")
                _finite_metrics(manifest.get("metrics"))
                if kind == "training.preflight.v1":
                    _validate_preflight(archive, manifest, inputs, result)
                else:
                    _validate_training(manifest, inputs, result, kind)
            files = _files(archive, manifest, name, export=export)
            if kind == "training.distillation.v1":
                if not {"distilled-train.jsonl", "teacher-evidence.json"}.issubset(files):
                    raise ValueError("distillation result lacks teacher supervision")
                distilled = next(item for item in manifest["files"] if item["relative_path"] == "distilled-train.jsonl")
                _same(distilled["sha256"], manifest.get("distilled_dataset_sha256"), "distilled data hash")
            return manifest
    except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeError, RuntimeError) as error:
        raise ValueError("result artifact contains no valid ML manifest") from error


def _validate_preflight(archive: zipfile.ZipFile, manifest: dict, inputs: dict, result: dict) -> None:
    for field in ("dataset_fingerprint", "base_model"):
        _same(manifest.get(field), inputs.get(field), field)
    for field in ("dataset_fingerprint", "chat_template_fingerprint", "dtype", "backend", "contract", "checks"):
        _same(manifest.get(field), result.get(field), field)
    checks, contract = manifest.get("checks"), manifest.get("contract")
    if not isinstance(checks, dict) or set(checks) != PREFLIGHT_CHECKS or any(v is not True for v in checks.values()):
        raise ValueError("all six preflight checks must be true booleans")
    if (not isinstance(contract, dict) or set(contract) != CONTRACT_CHECKS | {"errors", "passed"}
            or any(contract.get(key) is not True for key in CONTRACT_CHECKS | {"passed"}) or contract["errors"] != []):
        raise ValueError("preflight C1-C6 contract is incomplete")
    losses = manifest.get("losses")
    if (not isinstance(losses, list) or len(losses) < 2 or any(type(v) not in {int, float}
            or not math.isfinite(v) or v < 0 for v in losses) or losses[-1] >= losses[0]):
        raise ValueError("preflight losses do not demonstrate the overfit check")
    if (type(manifest.get("overfit_examples")) is not int or manifest["overfit_examples"] != 8
            or type(manifest.get("overfit_steps")) is not int or manifest["overfit_steps"] != 20
            or type(manifest.get("resume_global_step")) is not int or manifest["resume_global_step"] < 21):
        raise ValueError("preflight steps or resume proof are incomplete")
    notes = manifest.get("nondeterminism_notes")
    if not isinstance(notes, list) or not notes or any(not isinstance(v, str) or not v.strip() for v in notes):
        raise ValueError("preflight nondeterminism notes are missing")
    if manifest.get("backend") not in {"cuda", "rocm", "cpu"} or not _sha(manifest.get("dataset_fingerprint")):
        raise ValueError("preflight backend or dataset fingerprint is invalid")
    states = [info.filename for info in archive.infolist() if info.filename.startswith("checkpoints/checkpoint-")
              and info.filename.endswith("/trainer_state.json")]
    if not states or not any(type((state := _json_object(archive, name)[0]).get("global_step")) is int
                             and state["global_step"] >= 20 for name in states):
        raise ValueError("preflight has no saved twenty-step checkpoint")


def _validate_training(manifest: dict, inputs: dict, result: dict, kind: str) -> None:
    model_field = "student_model" if kind == "training.distillation.v1" else "base_model"
    data_field = "source_dataset_fingerprint" if kind == "training.distillation.v1" else "dataset_fingerprint"
    for field, expected in ((model_field, inputs.get(model_field)), (data_field, inputs.get("dataset_fingerprint")),
                            ("chat_template_fingerprint", inputs.get("chat_template_fingerprint"))):
        _same(manifest.get(field), expected, field)
    if not _sha(manifest.get("base_weights_sha256")) or not _sha(manifest.get(data_field)):
        raise ValueError("training model or dataset fingerprint is invalid")
    if inputs.get("expected_base_weights_sha256"):
        _same(manifest["base_weights_sha256"], inputs["expected_base_weights_sha256"], "base weights")
    _same(manifest.get("metrics"), result.get("metrics"), "metrics")
    if kind == "training.distillation.v1":
        for field in ("teacher_model", "teacher_model_fingerprint", "student_model_fingerprint",
                      "teacher_source", "teacher_target_model", "broker_capability_fingerprint", "generation_config"):
            _same(manifest.get(field), inputs.get(field, "local" if field == "teacher_source" else None), field)
        if (manifest.get("method") != "sequence_level_supervision.v1"
                or type(manifest.get("distilled_examples")) is not int or manifest["distilled_examples"] <= 0):
            raise ValueError("distillation method or example count is invalid")
        _same(manifest["distilled_examples"], result.get("distilled_examples"), "distilled example count")


def _validate_export(manifest: dict, inputs: dict, result: dict) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or any(not isinstance(item, dict) for item in artifacts):
        raise ValueError("export artifact inventory is invalid")
    expected = {"format": EXPORT_FORMAT, "training_manifest_sha256": inputs.get("source_training_manifest_sha256"),
                "artifacts": artifacts, "serving": inputs.get("serving"), "source_attempt": manifest["source_attempt"]}
    _same(sha256_json(expected), manifest.get("fingerprint"), "export fingerprint")
    _same(manifest.get("training_manifest_sha256"), inputs.get("source_training_manifest_sha256"), "training source")
    _same(manifest.get("serving"), inputs.get("serving"), "serving configuration")
    ExportPackageBuilder._reject_secrets(manifest.get("serving"))
    for field, key in (("fingerprint", "package_fingerprint"), ("package_id", "package_id")):
        _same(manifest.get(field), result.get(key), field)
    formats = inputs.get("formats")
    _same(result.get("formats"), formats, "export formats")
    support = inputs.get("required_support_artifacts", [])
    if not isinstance(support, list) or any(kind != "tokenizer" for kind in support):
        raise ValueError("export support artifact requirements are invalid")
    if not isinstance(formats, list) or not formats or {item.get("kind") for item in artifacts} != set(formats) | set(support):
        raise ValueError("export package formats differ from the job")
    for item in artifacts:
        _same(item.get("license_id"), inputs.get("license_id"), "license")
        reference = item.get("source_reference")
        source = inputs.get("source_artifact_reference")
        if not isinstance(reference, str) or not isinstance(source, str) or (reference != source and not reference.startswith(source + "#")):
            raise ValueError("export source provenance differs from the job")
