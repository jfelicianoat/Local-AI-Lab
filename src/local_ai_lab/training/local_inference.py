"""Inference from the exact verified adapter produced by a local training job."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from local_ai_lab.broker.client import BrokerInvocation
from local_ai_lab.domain.common import canonical_json
from local_ai_lab.training.identity import model_weights_fingerprint


class LocalAdapterClient:
    def __init__(self, *, output: Path, identity: dict[str, str], device: str) -> None:
        root = output.resolve(strict=True)
        kind = identity["manifest_kind"]
        filename = "training-manifest.json" if kind == "training" else "distillation-manifest.json"
        manifest_bytes = (root / filename).read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != identity["manifest_file_sha256"]:
            raise ValueError("trained model manifest file has changed")
        manifest = json.loads(manifest_bytes)
        content_hash = manifest.pop("content_sha256", None)
        if (
            content_hash != identity["manifest_sha256"]
            or hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest() != content_hash
        ):
            raise ValueError("trained model manifest content has changed")
        base_model = manifest.get("base_model") or manifest.get("student_model")
        if base_model != identity["base_model"]:
            raise ValueError("trained adapter belongs to another base model")
        for item in manifest.get("files", []):
            relative = Path(item["relative_path"])
            path = (root / relative).resolve(strict=True)
            try:
                path.relative_to(root)
            except ValueError as error:
                raise ValueError("trained model manifest escapes its package") from error
            if path.stat().st_size != item["size"] or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("trained model package file has changed")
        if not (root / "adapter").is_dir() or not (root / "tokenizer").is_dir():
            raise ValueError("trained model package lacks adapter or tokenizer")
        if not isinstance(manifest.get("base_weights_sha256"), str):
            raise ValueError("training did not record the base weights identity")
        try:
            import torch
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as error:
            raise RuntimeError("local trained-model inference requires torch, transformers and peft") from error
        dtype = torch.bfloat16 if manifest.get("dtype") == "bf16" else torch.float16
        base = AutoModelForCausalLM.from_pretrained(base_model, local_files_only=True, torch_dtype=dtype)
        if model_weights_fingerprint(base) != manifest["base_weights_sha256"]:
            raise ValueError("cached base model weights differ from those used for training")
        self.model = PeftModel.from_pretrained(base, root / "adapter", local_files_only=True).to(device)
        self.model.eval()
        self.tokenizer = AutoTokenizer.from_pretrained(root / "tokenizer", local_files_only=True)
        self.device = device
        self.identity = identity
        self._torch = torch

    def invoke(
        self, *, prompt: str, target_model: dict[str, str],
        generation: dict[str, Any], json_schema: dict[str, Any] | None,
        correlation_id: str,
    ) -> BrokerInvocation:
        expected = {
            "provider": "local_adapter",
            "deployment": self.identity["training_job_id"],
            "model": self.identity["base_model"],
        }
        if target_model != expected:
            raise ValueError("inference target differs from the trained adapter identity")
        tokenizer = self.tokenizer
        if tokenizer.chat_template:
            tokens = tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}], tokenize=True,
                add_generation_prompt=True, return_tensors="pt",
            )
        else:
            tokens = tokenizer(prompt, return_tensors="pt")["input_ids"]
        tokens = tokens.to(self.device)
        started = time.monotonic()
        with self._torch.inference_mode():
            generated = self.model.generate(
                input_ids=tokens, do_sample=False,
                max_new_tokens=int(generation.get("max_new_tokens", 512)),
                pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            )
        text = tokenizer.decode(generated[0][tokens.shape[-1]:], skip_special_tokens=True)
        return BrokerInvocation(
            task_id=correlation_id, text=text,
            model_used={**expected, "adapter_package_sha256": self.identity["package_sha256"]},
            fallback_used=False, usage={}, telemetry=(), cost_amount=None,
            cost_currency="USD", cost_source="not_available",
            cost_verification_status="unknown",
            latency_ms=(time.monotonic() - started) * 1000.0,
            deliverable_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
