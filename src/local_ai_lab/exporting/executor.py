from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
import shutil
import struct
from pathlib import Path
from typing import Any, Callable

from local_ai_lab.exporting.package import ExportArtifact, ExportPackageBuilder


class ExportExecutionError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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
            with path.open("rb") as source_stream, archive.open(info, "w") as target_stream:
                shutil.copyfileobj(source_stream, target_stream, length=1024 * 1024)
    return target


class ModelExportExecutor:
    def __call__(
        self,
        payload: dict[str, Any],
        progress: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        training_root = Path(payload["resolved_training_output"]).resolve(strict=True)
        # Una destilación produce `distillation-manifest.json`, no `training-manifest.json`.
        # El Coordinator ya acepta DISTILLATION_SUCCEEDED como origen de exportación, así
        # que aquí hay que reconocer ambos; el hash sigue siendo la garantía de integridad.
        training_manifest = next(
            (
                candidate
                for candidate in (
                    training_root / "training-manifest.json",
                    training_root / "distillation-manifest.json",
                )
                if candidate.is_file()
            ),
            None,
        )
        if training_manifest is None:
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
        tokenizer_dir = training_root / "tokenizer"
        if payload.get("required_support_artifacts") and not (tokenizer_dir / "tokenizer_config.json").is_file():
            raise ExportExecutionError("El resultado de entrenamiento no contiene su tokenizer guardado")
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
            if not tokenizer_dir.is_dir():
                raise ExportExecutionError("merged export requires the saved training tokenizer")
            shutil.copytree(tokenizer_dir, merged_dir, dirs_exist_ok=True)
            progress({"stage": "verify_merged_model"})
            # Release training model references before loading the saved conversion.
            del merged, base
            from transformers import AutoTokenizer
            saved_tokenizer = AutoTokenizer.from_pretrained(merged_dir, local_files_only=True)
            template_hash = hashlib.sha256((saved_tokenizer.chat_template or "").encode("utf-8")).hexdigest()
            expected_template = payload.get("serving", {}).get("chat_template_fingerprint")
            if expected_template and template_hash != expected_template:
                raise ExportExecutionError("export tokenizer differs from the trained chat template")
            saved_model, loading_info = AutoModelForCausalLM.from_pretrained(
                merged_dir, local_files_only=True, output_loading_info=True,
            )
            if any(loading_info.get(key) for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")):
                raise ExportExecutionError("merged model cannot be reloaded without weight discrepancies")
            del saved_model, saved_tokenizer
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
            with gguf.open("rb") as stream:
                header = stream.read(24)
            if len(header) != 24 or header[:4] != b"GGUF":
                raise ExportExecutionError("GGUF converter did not produce a valid container header")
            version, tensors, metadata = struct.unpack("<IQQ", header[4:])
            if version not in {2, 3} or not tensors or not metadata or gguf.stat().st_size <= 24:
                raise ExportExecutionError("GGUF converter produced an empty or unsupported container")
            artifacts.append(ExportArtifact("gguf", gguf, _sha(gguf), license_id, source_reference))
        if "tokenizer" in payload.get("required_support_artifacts", []):
            progress({"stage": "archive_model_metadata"})
            metadata_dir = work / "model-metadata"
            shutil.copytree(tokenizer_dir, metadata_dir)
            if (merged_dir / "config.json").is_file():
                shutil.copy2(merged_dir / "config.json", metadata_dir / "config.json")
            archive = deterministic_zip(metadata_dir, work / "model-metadata.zip")
            artifacts.append(ExportArtifact("tokenizer", archive, _sha(archive), license_id, source_reference))
        progress({"stage": "package"})
        package = ExportPackageBuilder().build(
            artifacts, output / "packages",
            source_training_manifest_sha256=payload["source_training_manifest_sha256"],
            serving=payload["serving"],
            source_attempt=payload.get("_worker_attempt"),
        )
        return {
            "package_path": str(package.path),
            "package_id": package.package_id,
            "package_fingerprint": package.fingerprint,
            "formats": list(formats),
        }
