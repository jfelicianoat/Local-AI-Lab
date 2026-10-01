from __future__ import annotations

import os
import tracemalloc
import zipfile
from pathlib import Path

import pytest

from local_ai_lab.artifacts.archive import deterministic_zip as artifact_zip, safe_extract_zip
from local_ai_lab.exporting.executor import deterministic_zip as export_zip


@pytest.mark.parametrize("make_archive", [artifact_zip, export_zip])
def test_model_sized_archive_uses_bounded_python_memory(tmp_path: Path, make_archive) -> None:
    source = tmp_path / "model"
    source.mkdir()
    model = source / "weights.safetensors"
    with model.open("wb") as output:
        for _ in range(12):
            output.write(os.urandom(1024 * 1024))

    tracemalloc.start()
    try:
        archive_result = make_archive(source, tmp_path / "model.zip")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    archive = archive_result[0] if isinstance(archive_result, tuple) else archive_result
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.getinfo("weights.safetensors").file_size == 12 * 1024 * 1024
    assert peak < 6 * 1024 * 1024


def test_unsafe_archive_does_not_leave_partial_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("safe.txt", "partial")
        output.writestr("../outside.txt", "escape")
    with pytest.raises(ValueError, match="escapes extraction root"):
        safe_extract_zip(archive, tmp_path / "extracted")
    assert not (tmp_path / "extracted").exists()
    assert not (tmp_path / "outside.txt").exists()
    assert not list(tmp_path.glob("extracted.staging-*"))
