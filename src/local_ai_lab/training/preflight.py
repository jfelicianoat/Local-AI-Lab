from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Callable

from local_ai_lab.dataset.factory import DatasetVerifier
from local_ai_lab.domain.common import canonical_json, utc_timestamp
from local_ai_lab.training.contracts import TrainingContractValidator
from local_ai_lab.training.executor import (
    AssistantOnlyCollator,
    TrainingExecutionError,
    prepare_supervised_example,
)


class TrainingPreflightExecutor:
    """Runs the mandatory short proof before a long LoRA job can be planned."""

    def __call__(
        self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]
    ) -> dict[str, Any]:
        try:
            import torch
            from peft import LoraConfig, PeftModel, get_peft_model
            from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments
        except ImportError as error:
            raise TrainingExecutionError("training extras are not installed on this worker") from error

        dataset_path = Path(payload["resolved_dataset_path"]).resolve(strict=True)
        dataset_manifest = DatasetVerifier().verify(dataset_path)
        output = Path(payload["preflight_output"]).resolve()
        if output.exists() or str(output).startswith(("\\\\", "//")):
            raise TrainingExecutionError("preflight output must be a new local directory")
        records = [
            json.loads(line)
            for line in (dataset_path / "train.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(records) < 8:
            raise TrainingExecutionError("the mandatory overfit preflight requires at least 8 train examples")

        base_model = payload["base_model"]
        tokenizer = AutoTokenizer.from_pretrained(base_model, local_files_only=True)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        template = tokenizer.chat_template or ""
        template_fingerprint = hashlib.sha256(template.encode("utf-8")).hexdigest()
        tokenized = [
            prepare_supervised_example(
                tokenizer, record["messages"], max_length=int(payload.get("max_length", 4096)),
                template_fingerprint=template_fingerprint,
            )
            for record in records[:8]
        ]
        seed = int(payload["seed"])
        nondeterminism = [
            "GPU kernels may be nondeterministic despite fixed framework and data seeds",
            "backend, driver and runtime versions are supplied by the tested node report",
        ]
        contract = TrainingContractValidator().validate(
            tokenized, expected_template_fingerprint=template_fingerprint,
            seed=seed, nondeterminism_notes=nondeterminism,
        )
        if not contract.passed:
            raise TrainingExecutionError("C1-C6 contract failed before the short training run")

        random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        dtype = payload["dtype"]
        if dtype not in {"bf16", "fp16"}:
            raise TrainingExecutionError("preflight dtype must be bf16 or fp16")
        torch_dtype = torch.bfloat16 if dtype == "bf16" else torch.float16
        config = payload["lora_config"]

        def new_model() -> Any:
            base = AutoModelForCausalLM.from_pretrained(
                base_model, local_files_only=True, torch_dtype=torch_dtype,
            )
            return get_peft_model(
                base,
                LoraConfig(
                    r=int(config["rank"]),
                    lora_alpha=int(config.get("alpha", int(config["rank"]) * 2)),
                    lora_dropout=float(config.get("dropout", 0.0)),
                    target_modules=config.get("target_modules"), task_type="CAUSAL_LM",
                ),
            )

        output.mkdir(parents=True, exist_ok=False)
        checkpoint_root = output / "checkpoints"
        common = {
            "output_dir": str(checkpoint_root), "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": 1, "learning_rate": float(payload.get("learning_rate", 2e-4)),
            "logging_steps": 1, "save_steps": 10, "seed": seed, "data_seed": seed,
            "bf16": dtype == "bf16", "fp16": dtype == "fp16", "report_to": [],
            "remove_unused_columns": False,
        }
        collator = AssistantOnlyCollator(pad_token_id=tokenizer.pad_token_id)
        progress({"stage": "preflight_overfit", "step": 0, "steps": 20})
        trainer = Trainer(
            model=new_model(), args=TrainingArguments(max_steps=20, **common),
            train_dataset=tokenized, data_collator=collator,
        )
        first_result = trainer.train()
        losses = [
            float(item["loss"]) for item in trainer.state.log_history
            if isinstance(item.get("loss"), (int, float))
        ]
        overfit_pass = len(losses) >= 2 and losses[-1] < losses[0]
        checkpoints = sorted(checkpoint_root.glob("checkpoint-*"))
        if not overfit_pass or not checkpoints:
            raise TrainingExecutionError("8-example/20-step overfit or checkpoint proof failed")

        adapter = output / "adapter"
        trainer.model.save_pretrained(adapter, safe_serialization=True)
        tokenizer.save_pretrained(output / "tokenizer")
        reload_base = AutoModelForCausalLM.from_pretrained(
            base_model, local_files_only=True, torch_dtype=torch_dtype,
        )
        PeftModel.from_pretrained(reload_base, adapter, local_files_only=True)
        progress({"stage": "preflight_resume", "checkpoint": checkpoints[-1].name})
        resumed = Trainer(
            model=new_model(), args=TrainingArguments(max_steps=21, **common),
            train_dataset=tokenized, data_collator=collator,
        )
        resumed.train(resume_from_checkpoint=str(checkpoints[-1]))
        resume_pass = resumed.state.global_step >= 21
        if not resume_pass:
            raise TrainingExecutionError("checkpoint resume proof failed")

        backend = "cuda" if torch.version.cuda else "rocm" if getattr(torch.version, "hip", None) else "cpu"
        checks = {
            "overfit_8_examples": overfit_pass,
            "save": adapter.is_dir(),
            "reload": True,
            "resume": resume_pass,
            "contamination_check": bool(dataset_manifest.get("benchmark_fingerprints")),
            "manifest_check": True,
        }
        manifest = {
            "schema_version": "training-preflight.v1", "created_at": utc_timestamp(),
            "dataset_fingerprint": dataset_manifest["fingerprint"],
            "base_model": base_model, "chat_template_fingerprint": template_fingerprint,
            "seed": seed, "nondeterminism_notes": nondeterminism, "dtype": dtype,
            "backend": backend, "contract": contract.as_dict(), "checks": checks,
            "metrics": dict(first_result.metrics), "losses": losses,
        }
        manifest["content_sha256"] = hashlib.sha256(
            canonical_json(manifest).encode("utf-8")
        ).hexdigest()
        (output / "preflight-manifest.json").write_text(
            canonical_json(manifest) + "\n", encoding="utf-8", newline="\n"
        )
        return {
            "preflight_output": str(output), "preflight_sha256": manifest["content_sha256"],
            "dataset_fingerprint": dataset_manifest["fingerprint"],
            "chat_template_fingerprint": template_fingerprint, "dtype": dtype,
            "backend": backend, "contract": contract.as_dict(), "checks": checks,
        }
