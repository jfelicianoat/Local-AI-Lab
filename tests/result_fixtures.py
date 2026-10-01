"""Synthetic packages for protocol tests; these do not demonstrate ML execution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from local_ai_lab.artifacts.archive import deterministic_zip
from local_ai_lab.domain.common import canonical_json, sha256_json


CHECKS = {key: True for key in (
    "overfit_8_examples", "save", "reload", "resume", "contamination_check", "manifest_check",
)}
CONTRACT = {key: True for key in (
    "c1_assistant_only_loss", "c2_supervised_eos", "c3_same_chat_template",
    "c4_assistant_not_truncated", "c5_padding_outside_loss", "c6_seed_and_nondeterminism_recorded",
)} | {"errors": [], "passed": True}


def preflight_inputs(**overrides) -> dict:
    return {
        "dataset_fingerprint": "a" * 64, "base_model": "student", "dtype": "bf16",
        "seed": 42, "max_length": 2048, "lora_config": {"rank": 8, "alpha": 16},
        "collect_outputs": [{"result_key": "preflight_output", "kind": "training_preflight"}],
        **overrides,
    }


def preflight_manifest(lease: dict) -> dict:
    inputs = lease["spec"]["payload"]
    return {
        "schema_version": "training-preflight.v1", "created_at": "2026-10-01T00:00:00Z",
        "source_attempt": {
            "source_job_id": lease["job_id"], "source_attempt_id": lease["attempt_id"],
            "source_lease_generation": lease["lease_generation"],
            "source_spec_sha256": sha256_json(lease["spec"]), "training_kind": lease["spec"]["kind"],
        },
        **{key: inputs[key] for key in ("dataset_fingerprint", "base_model", "dtype", "seed", "max_length", "lora_config")},
        "chat_template_fingerprint": "2" * 64, "backend": "cuda",
        "nondeterminism_notes": ["Synthetic fixture; no GPU execution"],
        "contract": dict(CONTRACT), "checks": dict(CHECKS),
        "metrics": {"train_loss": 0.5}, "losses": [2.0, 0.5],
        "overfit_examples": 8, "overfit_steps": 20, "resume_global_step": 21,
    }


def preflight_package(service, lease: dict, root: Path, *, mutate=None, result_mutate=None) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    files = {
        "adapter/adapter_config.json": b"{}", "adapter/adapter_model.safetensors": b"synthetic weights",
        "tokenizer/tokenizer_config.json": b"{}",
        "checkpoints/checkpoint-20/trainer_state.json": b'{"global_step":20}',
        "checkpoints/checkpoint-20/optimizer.pt": b"synthetic optimizer",
    }
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = preflight_manifest(lease)
    manifest["files"] = [{"relative_path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                         for name, data in sorted(files.items())]
    if mutate:
        mutate(manifest)
    manifest["content_sha256"] = sha256_json(manifest)
    (root / "preflight-manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    archive, _ = deterministic_zip(root, root.with_suffix(".zip"))
    stored = service.artifacts.ingest_file(archive)
    service.repository.bind_artifact_upload(
        artifact_id=stored["artifact_id"], node_id=service.repository.job(lease["job_id"])["assigned_node_id"],
        job=service.repository.job(lease["job_id"]), sha256=stored["sha256"],
    )
    result = {key: manifest[key] for key in ("dataset_fingerprint", "chat_template_fingerprint", "dtype", "backend", "contract", "checks")}
    result["preflight_sha256"] = manifest["content_sha256"]
    result["artifacts"] = [{"kind": "training_preflight", **stored}]
    if result_mutate:
        result_mutate(result)
    return result


def training_inputs(*, distillation=False, **overrides) -> dict:
    common = {"dataset_fingerprint": "a" * 64, "dtype": "bf16", "seed": 42,
              "max_length": 2048, "lora_config": {"rank": 8, "alpha": 16},
              "chat_template_fingerprint": "2" * 64,
              "collect_outputs": [{"result_key": "output_dir", "kind": "training_result"}]}
    if distillation:
        common.update({"teacher_model": "teacher", "teacher_model_fingerprint": "b" * 64,
                       "student_model": "student", "student_model_fingerprint": "c" * 64,
                       "teacher_source": "local", "generation_config": {"temperature": 0.0, "max_new_tokens": 128}})
    else:
        common["base_model"] = "student"
    return {**common, **overrides}


def training_package(service, lease: dict, root: Path, *, mutate=None, result_mutate=None) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    inputs = lease["spec"]["payload"]
    distillation = lease["spec"]["kind"] == "training.distillation.v1"
    files = {"adapter/adapter_config.json": b"{}", "adapter/adapter_model.safetensors": b"synthetic weights",
             "tokenizer/tokenizer_config.json": b"{}"}
    if distillation:
        files.update({"distilled-train.jsonl": b'{"messages":[]}\n' * 12, "teacher-evidence.json": b"{}"})
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = {"schema_version": "distillation-result.v1" if distillation else "training-result.v1",
                "created_at": "2026-10-01T00:00:00Z", "base_weights_sha256": "d" * 64,
                "source_attempt": preflight_manifest({**lease, "spec": {**lease["spec"], "payload": preflight_inputs()}})["source_attempt"],
                **{key: inputs.get(key, 4096 if key == "max_length" else None) for key in
                   ("dtype", "seed", "max_length", "lora_config", "chat_template_fingerprint")},
                "metrics": {"train_loss": 0.5},
                "files": [{"relative_path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                          for name, data in sorted(files.items())]}
    manifest["source_attempt"]["source_spec_sha256"] = sha256_json(lease["spec"])
    if distillation:
        manifest.update({key: inputs.get(key, "local" if key == "teacher_source" else None) for key in
                         ("teacher_model", "teacher_model_fingerprint", "student_model", "student_model_fingerprint",
                          "teacher_source", "teacher_target_model", "broker_capability_fingerprint", "generation_config")})
        manifest.update({"source_dataset_fingerprint": inputs["dataset_fingerprint"], "distilled_examples": 12,
                         "method": "sequence_level_supervision.v1",
                         "distilled_dataset_sha256": hashlib.sha256(files["distilled-train.jsonl"]).hexdigest(),
                         "broker_invocations": []})
    else:
        manifest.update({"base_model": inputs["base_model"], "dataset_fingerprint": inputs["dataset_fingerprint"],
                         "resume_from_checkpoint": None})
    if mutate:
        mutate(manifest)
    manifest["content_sha256"] = sha256_json(manifest)
    filename = "distillation-manifest.json" if distillation else "training-manifest.json"
    raw = (canonical_json(manifest) + "\n").encode("utf-8")
    (root / filename).write_bytes(raw)
    archive, _ = deterministic_zip(root, root.with_suffix(".zip"))
    stored = service.artifacts.ingest_file(archive)
    service.repository.bind_artifact_upload(artifact_id=stored["artifact_id"], node_id=service.repository.job(lease["job_id"])["assigned_node_id"],
                                            job=service.repository.job(lease["job_id"]), sha256=stored["sha256"])
    result = {"manifest_sha256": manifest["content_sha256"], "manifest_file_sha256": hashlib.sha256(raw).hexdigest(),
              "metrics": manifest["metrics"], "artifacts": [{"kind": "training_result", **stored}]}
    if distillation:
        result["distilled_examples"] = manifest["distilled_examples"]
    if result_mutate:
        result_mutate(result)
    return result
