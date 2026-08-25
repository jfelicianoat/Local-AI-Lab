from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Callable

from local_ai_lab.exporting.package import ExportArtifact, ExportPackageBuilder


class ExportExecutionError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deterministic_zip(source: Path, target: Path) -> Path:
    root = source.resolve(strict=True)
    if not root.is_dir() or target.exists():
        raise ExportExecutionError("adapter archive source must be a directory and target must be new")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return target


class ModelExportExecutor:
    def __call__(
        self,
        payload: dict[str, Any],
        progress: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        training_root = Path(payload["resolved_training_output"]).resolve(strict=True)
        training_manifest = training_root / "training-manifest.json"
        if not training_manifest.is_file():
            raise ExportExecutionError("training manifest is missing")
        manifest_sha = _sha(training_manifest)
        if manifest_sha != payload["source_manifest_file_sha256"]:
            raise ExportExecutionError("training manifest file hash mismatch")
        formats = tuple(payload["formats"])
        allowed = {"adapter", "merged_model", "safetensors", "gguf"}
        if not formats or not set(formats) <= allowed:
            raise ExportExecutionError("unsupported export formats")
        output = Path(payload["output_dir"]).resolve()
        if str(output).startswith(("\\\\", "//")) or output.exists():
            raise ExportExecutionError("export output must be a new local directory")
        work = output / "work"
        work.mkdir(parents=True, exist_ok=False)
        artifacts: list[ExportArtifact] = []
        license_id = payload["license_id"]
        source_reference = payload["source_artifact_reference"]
        adapter_dir = training_root / "adapter"
        if "adapter" in formats:
            progress({"stage": "archive_adapter"})
            archive = deterministic_zip(adapter_dir, work / "adapter.zip")
            artifacts.append(ExportArtifact("adapter", archive, _sha(archive), license_id, source_reference))
        merged_dir = work / "merged"
        if set(formats) & {"merged_model", "safetensors", "gguf"}:
            progress({"stage": "merge_model"})
            try:
                from peft import PeftModel
                from transformers import AutoModelForCausalLM
            except ImportError as error:
                raise ExportExecutionError("merge export requires transformers and PEFT") from error
            base_model = payload["base_model"]
            base = AutoModelForCausalLM.from_pretrained(base_model, local_files_only=True)
            merged = PeftModel.from_pretrained(base, adapter_dir, local_files_only=True).merge_and_unload()
            merged.save_pretrained(merged_dir, safe_serialization=True)
            safetensors = sorted(merged_dir.glob("*.safetensors"))
            if not safetensors:
                raise ExportExecutionError("merge did not produce safetensors")
            if "safetensors" in formats:
                for index, path in enumerate(safetensors):
                    artifacts.append(
                        ExportArtifact(
                            "safetensors", path, _sha(path), license_id,
                            f"{source_reference}#safetensors-{index}",
                        )
                    )
            if "merged_model" in formats:
                archive = deterministic_zip(merged_dir, work / "merged-model.zip")
                artifacts.append(ExportArtifact("merged_model", archive, _sha(archive), license_id, source_reference))
        if "gguf" in formats:
            progress({"stage": "convert_gguf"})
            converter = Path(payload["llama_cpp_converter"]).resolve(strict=True)
            if not converter.is_file():
                raise ExportExecutionError("llama.cpp converter is not a file")
            gguf = work / "model.gguf"
            command = [
                payload.get("converter_python", "python"), str(converter), str(merged_dir),
                "--outfile", str(gguf), "--outtype", payload.get("gguf_outtype", "f16"),
            ]
            completed = subprocess.run(
                command, check=False, capture_output=True, text=True, timeout=float(payload.get("conversion_timeout", 3600)),
            )
            if completed.returncode != 0 or not gguf.is_file():
                raise ExportExecutionError(f"GGUF conversion failed: {completed.stderr[-1000:]}")
            artifacts.append(ExportArtifact("gguf", gguf, _sha(gguf), license_id, source_reference))
        progress({"stage": "package"})
        package = ExportPackageBuilder().build(
            artifacts, output / "packages",
            source_training_manifest_sha256=payload["source_training_manifest_sha256"],
            serving=payload["serving"],
        )
        return {
            "package_path": str(package.path),
            "package_id": package.package_id,
            "package_fingerprint": package.fingerprint,
            "formats": list(formats),
        }
