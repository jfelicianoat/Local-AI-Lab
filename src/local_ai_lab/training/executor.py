from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Callable, Sequence

from local_ai_lab.dataset.factory import DatasetVerifier
from local_ai_lab.domain.common import canonical_json, utc_timestamp


class TrainingExecutionError(RuntimeError):
    pass


def prepare_supervised_example(
    tokenizer: Any,
    messages: Sequence[dict[str, str]],
    *,
    max_length: int,
    template_fingerprint: str,
) -> dict[str, Any]:
    if not messages or messages[-1].get("role") != "assistant":
        raise TrainingExecutionError("training example must end with an assistant message")
    prompt_ids = list(
        tokenizer.apply_chat_template(
            list(messages[:-1]), tokenize=True, add_generation_prompt=True
        )
    )
    full_ids = list(
        tokenizer.apply_chat_template(list(messages), tokenize=True, add_generation_prompt=False)
    )
    if full_ids[: len(prompt_ids)] != prompt_ids:
        raise TrainingExecutionError("chat template does not expose a stable assistant boundary")
    eos = tokenizer.eos_token_id
    if eos is None:
        raise TrainingExecutionError("tokenizer has no EOS token")
    if not full_ids or full_ids[-1] != eos:
        full_ids.append(eos)
    if len(full_ids) > max_length:
        raise TrainingExecutionError("example would truncate inside the assistant response")
    labels = [-100] * len(prompt_ids) + full_ids[len(prompt_ids):]
    return {
        "input_ids": full_ids,
        "labels": labels,
        "attention_mask": [1] * len(full_ids),
        "assistant_start": len(prompt_ids),
        "eos_token_id": eos,
        "pad_token_id": tokenizer.pad_token_id,
        "assistant_truncated": False,
        "template_fingerprint": template_fingerprint,
    }


class AssistantOnlyCollator:
    def __init__(self, *, pad_token_id: int) -> None:
        self.pad_token_id = pad_token_id

    def __call__(self, examples: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if not examples:
            raise TrainingExecutionError("cannot collate an empty batch")
        width = max(len(item["input_ids"]) for item in examples)
        input_ids, labels, attention = [], [], []
        for item in examples:
            padding = width - len(item["input_ids"])
            input_ids.append(item["input_ids"] + [self.pad_token_id] * padding)
            labels.append(item["labels"] + [-100] * padding)
            attention.append(item["attention_mask"] + [0] * padding)
        try:
            import torch
        except ImportError:
            return {"input_ids": input_ids, "labels": labels, "attention_mask": attention}
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.tensor(attention, dtype=torch.long),
        }


class TransformersLoraExecutor:
    """Worker executor for an already-approved local LoRA job."""

    def __call__(
        self,
        payload: dict[str, Any],
        progress: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        try:
            import torch
            from peft import LoraConfig, PeftModel, get_peft_model
            from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments
        except ImportError as error:
            raise TrainingExecutionError(
                "training extras are not installed on this worker; install the role-specific locked environment"
            ) from error
        dataset_path = Path(payload["resolved_dataset_path"]).resolve(strict=True)
        output = Path(payload["output_dir"]).resolve()
        if str(output).startswith(("\\\\", "//")) or output.exists():
            raise TrainingExecutionError("training output must be a new local directory")
        DatasetVerifier().verify(dataset_path)
        output.mkdir(parents=True, exist_ok=False)
        base_model = payload["base_model"]
        tokenizer = AutoTokenizer.from_pretrained(base_model, local_files_only=True)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        template = tokenizer.chat_template or ""
        template_fingerprint = hashlib.sha256(template.encode("utf-8")).hexdigest()
        if template_fingerprint != payload["chat_template_fingerprint"]:
            raise TrainingExecutionError("cached model chat template differs from the approved plan")
        records = [
            json.loads(line)
            for line in (dataset_path / "train.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not records:
            raise TrainingExecutionError("training split is empty")
        tokenized = [
            prepare_supervised_example(
                tokenizer, record["messages"], max_length=int(payload.get("max_length", 4096)),
                template_fingerprint=template_fingerprint,
            )
            for record in records
        ]
        seed = int(payload["seed"])
        random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        dtype = payload["dtype"]
        torch_dtype = torch.bfloat16 if dtype == "bf16" else torch.float16
        model = AutoModelForCausalLM.from_pretrained(
            base_model, local_files_only=True, torch_dtype=torch_dtype,
        )
        config = payload["lora_config"]
        lora = LoraConfig(
            r=int(config["rank"]), lora_alpha=int(config.get("alpha", config["rank"] * 2)),
            lora_dropout=float(config.get("dropout", 0.0)),
            target_modules=config.get("target_modules"), task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora)
        arguments = TrainingArguments(
            output_dir=str(output / "checkpoints"),
            per_device_train_batch_size=int(payload.get("batch_size", 1)),
            gradient_accumulation_steps=int(payload.get("gradient_accumulation_steps", 1)),
            learning_rate=float(payload.get("learning_rate", 2e-4)),
            num_train_epochs=float(payload.get("epochs", 1.0)),
            max_steps=int(payload.get("max_steps", -1)),
            save_steps=int(payload.get("save_steps", 50)),
            logging_steps=int(payload.get("logging_steps", 5)),
            seed=seed,
            data_seed=seed,
            bf16=dtype == "bf16",
            fp16=dtype == "fp16",
            report_to=[],
            remove_unused_columns=False,
        )
        trainer = Trainer(
            model=model, args=arguments, train_dataset=tokenized,
            data_collator=AssistantOnlyCollator(pad_token_id=tokenizer.pad_token_id),
        )
        progress({"stage": "training", "examples": len(tokenized)})
        result = trainer.train(resume_from_checkpoint=payload.get("resume_from_checkpoint"))
        adapter_path = output / "adapter"
        model.save_pretrained(adapter_path, safe_serialization=True)
        tokenizer.save_pretrained(output / "tokenizer")
        progress({"stage": "reload_verification"})
        base_reload = AutoModelForCausalLM.from_pretrained(
            base_model, local_files_only=True, torch_dtype=torch_dtype,
        )
        PeftModel.from_pretrained(base_reload, adapter_path, local_files_only=True)
        files = [path for path in sorted(output.rglob("*")) if path.is_file()]
        manifest = {
            "schema_version": "training-result.v1",
            "base_model": base_model,
            "dataset_fingerprint": payload["dataset_fingerprint"],
            "chat_template_fingerprint": template_fingerprint,
            "seed": seed,
            "dtype": dtype,
            "resume_from_checkpoint": payload.get("resume_from_checkpoint"),
            "metrics": dict(result.metrics),
            "created_at": utc_timestamp(),
            "files": [
                {
                    "relative_path": path.relative_to(output).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size": path.stat().st_size,
                }
                for path in files
            ],
        }
        encoded = canonical_json(manifest).encode("utf-8")
        manifest["content_sha256"] = hashlib.sha256(encoded).hexdigest()
        manifest_path = output / "training-manifest.json"
        manifest_path.write_text(
            canonical_json(manifest) + "\n", encoding="utf-8", newline="\n"
        )
        return {
            "output_dir": str(output),
            "manifest_sha256": manifest["content_sha256"],
            "manifest_file_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "adapter_path": str(adapter_path),
            "metrics": manifest["metrics"],
        }
