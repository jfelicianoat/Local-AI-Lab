from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from local_ai_lab.exporting.package import ExportArtifact, ExportError, ExportPackageBuilder, ExportPackageVerifier
from local_ai_lab.exporting.planner import CacheCleanupPlanner, ExportJobPlanner
from local_ai_lab.exporting.executor import ModelExportExecutor, deterministic_zip


def _artifact(tmp_path: Path, name: str, content: bytes, kind: str) -> ExportArtifact:
    path = tmp_path / name
    path.write_bytes(content)
    return ExportArtifact(
        kind=kind, path=path, sha256=hashlib.sha256(content).hexdigest(),
        license_id="Apache-2.0", source_reference="training:sha256:" + "a" * 64,
    )


def test_export_package_copies_hashes_and_preserves_serving_contract(tmp_path: Path) -> None:
    artifacts = [
        _artifact(tmp_path, "adapter.bin", b"adapter", "adapter"),
        _artifact(tmp_path, "model.gguf", b"gguf", "gguf"),
    ]
    serving = {
        "runtime": "llama.cpp", "entry_artifact_kind": "gguf",
        "chat_template_fingerprint": "template-v1", "cache_policy": "content_addressed",
    }
    result = ExportPackageBuilder().build(
        artifacts, tmp_path / "exports", source_training_manifest_sha256="b" * 64,
        serving=serving,
    )
    manifest = ExportPackageVerifier().verify(result.path)

    assert manifest["serving"] == serving
    assert {item["kind"] for item in manifest["artifacts"]} == {"adapter", "gguf"}
    assert len(result.fingerprint) == 64


def test_export_package_rejects_tampered_artifact(tmp_path: Path) -> None:
    result = ExportPackageBuilder().build(
        [_artifact(tmp_path, "model.safetensors", b"weights", "safetensors")],
        tmp_path / "exports", source_training_manifest_sha256="b" * 64,
        serving={"runtime": "transformers"},
    )
    copied = next((result.path / "artifacts").iterdir())
    copied.write_bytes(b"tampered")

    with pytest.raises(ExportError, match="verification failed"):
        ExportPackageVerifier().verify(result.path)


def test_export_job_requires_tested_conversion_capabilities() -> None:
    with pytest.raises(ValueError, match="lacks tested"):
        ExportJobPlanner().plan(
            source_manifest_sha256="a" * 64, source_artifact_reference="artifact://model",
            formats=("gguf",), node_id="node-1", tested_capabilities=set(),
        )
    job = ExportJobPlanner().plan(
        source_manifest_sha256="a" * 64, source_artifact_reference="artifact://model",
        formats=("adapter", "gguf"), node_id="node-1",
        tested_capabilities={"export.adapter", "export.gguf"},
    )
    assert job.kind == "model.export.v1"
    assert job.payload["verify_after_each_conversion"] is True


def test_cache_cleanup_is_preview_only_and_never_deletes(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    keep = cache / "keep.bin"
    stale = cache / "stale.bin"
    keep.write_bytes(b"keep")
    stale.write_bytes(b"stale")
    keep_hash = hashlib.sha256(keep.read_bytes()).hexdigest()

    plan = CacheCleanupPlanner().inspect(cache, {keep_hash})

    assert [item.relative_path for item in plan.candidates] == ["stale.bin"]
    assert plan.destructive_execution_available is False
    assert keep.exists() and stale.exists()


def test_serving_manifest_cannot_package_credentials(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="secret field"):
        ExportPackageBuilder().build(
            [_artifact(tmp_path, "adapter.bin", b"adapter", "adapter")],
            tmp_path / "exports", source_training_manifest_sha256="b" * 64,
            serving={"runtime": "test", "api_token": "must-not-be-packaged"},
        )


def test_adapter_only_export_executor_creates_verified_reproducible_package(tmp_path: Path) -> None:
    training = tmp_path / "training"
    adapter = training / "adapter"
    adapter.mkdir(parents=True)
    (adapter / "adapter_model.safetensors").write_bytes(b"adapter-weights")
    manifest = training / "training-manifest.json"
    manifest.write_text('{"schema_version":"training-result.v1"}\n', encoding="utf-8")
    payload = {
        "resolved_training_output": str(training),
        "source_manifest_file_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "source_training_manifest_sha256": "a" * 64,
        "source_artifact_reference": "training://run-1",
        "formats": ["adapter"], "output_dir": str(tmp_path / "export-job"),
        "license_id": "Apache-2.0", "serving": {"runtime": "peft"},
    }
    events = []
    result = ModelExportExecutor()(payload, events.append)

    assert result["formats"] == ["adapter"]
    assert Path(result["package_path"]).is_dir()
    assert ExportPackageVerifier().verify(Path(result["package_path"]))["serving"]["runtime"] == "peft"
    assert [event["stage"] for event in events] == ["archive_adapter", "package"]


def test_deterministic_adapter_archive_has_stable_hash(tmp_path: Path) -> None:
    source = tmp_path / "adapter"
    source.mkdir()
    (source / "b.txt").write_text("B", encoding="utf-8")
    (source / "a.txt").write_text("A", encoding="utf-8")
    first = deterministic_zip(source, tmp_path / "first.zip")
    second = deterministic_zip(source, tmp_path / "second.zip")

    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
