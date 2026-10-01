from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from local_ai_lab.training.checkpoints import create_checkpoint_bundle, verify_checkpoint_bundle


def _checkpoint(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    source = tmp_path / "checkpoint-4"
    source.mkdir()
    (source / "trainer_state.json").write_text('{"global_step":4}', encoding="utf-8")
    (source / "optimizer.pt").write_bytes(b"optimizer")
    (source / "scheduler.pt").write_bytes(b"scheduler")
    (source / "adapter_model.safetensors").write_bytes(b"weights")
    metadata: dict[str, object] = {
        "source_job_id": "job-1", "source_attempt_id": "attempt-1",
        "source_lease_generation": 2, "source_spec_sha256": "a" * 64,
        "training_kind": "training.lora.v1", "dataset_fingerprint": "b" * 64,
        "model_id": "local/base", "base_weights_sha256": "c" * 64,
        "chat_template_fingerprint": "d" * 64,
    }
    return source, metadata


def test_checkpoint_bundle_verifies_attempt_and_every_file(tmp_path: Path) -> None:
    source, metadata = _checkpoint(tmp_path)
    bundle, digest = create_checkpoint_bundle(
        source, tmp_path / "checkpoint.zip", metadata=metadata, step=4,
    )
    assert len(digest) == 64
    manifest = verify_checkpoint_bundle(bundle, expected=metadata)
    assert manifest["step"] == 4
    assert len(manifest["files"]) == 4
    with pytest.raises(ValueError, match="provenance"):
        verify_checkpoint_bundle(bundle, expected={"source_attempt_id": "other"})

    changed = tmp_path / "changed.zip"
    with zipfile.ZipFile(bundle) as original, zipfile.ZipFile(changed, "w") as output:
        for info in original.infolist():
            data = original.read(info)
            if info.filename.endswith("adapter_model.safetensors"):
                data = b"changed"
            output.writestr(info, data)
    with pytest.raises(ValueError, match="hash or size"):
        verify_checkpoint_bundle(changed, expected=metadata)


def test_checkpoint_bundle_rejects_incomplete_or_misnumbered_state(tmp_path: Path) -> None:
    source, metadata = _checkpoint(tmp_path)
    (source / "optimizer.pt").unlink()
    with pytest.raises(ValueError, match="lacks Trainer state"):
        create_checkpoint_bundle(source, tmp_path / "missing.zip", metadata=metadata, step=4)
    (source / "optimizer.pt").write_bytes(b"optimizer")
    (source / "trainer_state.json").write_text(json.dumps({"global_step": 5}), encoding="utf-8")
    with pytest.raises(ValueError, match="Trainer step"):
        create_checkpoint_bundle(source, tmp_path / "wrong-step.zip", metadata=metadata, step=4)
