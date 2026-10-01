from __future__ import annotations

import contextlib
import hashlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from local_ai_lab.domain.common import canonical_json
from local_ai_lab.training.local_inference import LocalAdapterClient


def test_f1_inference_loads_exact_adapter_and_rejects_changed_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = tmp_path / "adapter"
    tokenizer_path = tmp_path / "tokenizer"
    adapter.mkdir()
    tokenizer_path.mkdir()
    (adapter / "adapter_model.safetensors").write_bytes(b"trained-adapter")
    (tokenizer_path / "tokenizer.json").write_bytes(b"{}")
    files = [
        {"relative_path": path.relative_to(tmp_path).as_posix(),
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}
        for path in (adapter / "adapter_model.safetensors", tokenizer_path / "tokenizer.json")
    ]
    manifest = {"base_model": "local/base", "base_weights_sha256": "a" * 64,
                "dtype": "bf16", "files": files}
    content_sha = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    manifest["content_sha256"] = content_sha
    manifest_bytes = (canonical_json(manifest) + "\n").encode()
    (tmp_path / "training-manifest.json").write_bytes(manifest_bytes)
    identity = {
        "manifest_kind": "training", "manifest_sha256": content_sha,
        "manifest_file_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "base_model": "local/base", "base_weights_sha256": "a" * 64,
        "training_job_id": "training-1", "package_sha256": "b" * 64,
    }
    calls: list[str] = []

    class Tokens:
        shape = (1, 2)

        def to(self, _device: str) -> Tokens:
            return self

    class Model:
        def to(self, _device: str) -> Model:
            return self

        def eval(self) -> None:
            pass

        def generate(self, *, input_ids: Tokens, **_values: object) -> list[list[int]]:
            assert input_ids.shape == (1, 2)
            calls.append("generated-with-adapter")
            return [[10, 11, 12]]

    class AutoModelForCausalLM:
        @staticmethod
        def from_pretrained(model: str, *, local_files_only: bool, torch_dtype: object) -> Model:
            assert model == "local/base" and local_files_only and torch_dtype == "bf16"
            calls.append("base-loaded")
            return Model()

    class PeftModel:
        @staticmethod
        def from_pretrained(model: Model, path: Path, *, local_files_only: bool) -> Model:
            assert path == adapter and local_files_only and isinstance(model, Model)
            calls.append("adapter-loaded")
            return model

    class Tokenizer:
        chat_template = "template"
        pad_token_id = 0
        eos_token_id = 1

        def apply_chat_template(self, _messages: object, **_values: object) -> Tokens:
            return Tokens()

        def decode(self, _tokens: object, *, skip_special_tokens: bool) -> str:
            assert skip_special_tokens
            return "Respuesta del adaptador."

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(path: Path, *, local_files_only: bool) -> Tokenizer:
            assert path == tokenizer_path and local_files_only
            return Tokenizer()

    torch = ModuleType("torch")
    torch.bfloat16 = "bf16"  # type: ignore[attr-defined]
    torch.float16 = "fp16"  # type: ignore[attr-defined]
    torch.inference_mode = contextlib.nullcontext  # type: ignore[attr-defined]
    transformers = ModuleType("transformers")
    transformers.AutoModelForCausalLM = AutoModelForCausalLM  # type: ignore[attr-defined]
    transformers.AutoTokenizer = AutoTokenizer  # type: ignore[attr-defined]
    peft = ModuleType("peft")
    peft.PeftModel = PeftModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setitem(sys.modules, "peft", peft)
    monkeypatch.setattr("local_ai_lab.training.local_inference.model_weights_fingerprint", lambda _model: "a" * 64)

    client = LocalAdapterClient(output=tmp_path, identity=identity, device="cpu")
    target = {"provider": "local_adapter", "deployment": "training-1", "model": "local/base"}
    invocation = client.invoke(
        prompt="Pregunta", target_model=target, generation={"max_new_tokens": 16},
        json_schema=None, correlation_id="test",
    )
    assert invocation.text == "Respuesta del adaptador."
    assert calls == ["base-loaded", "adapter-loaded", "generated-with-adapter"]
    with pytest.raises(ValueError, match="target differs"):
        client.invoke(prompt="Pregunta", target_model={**target, "model": "other"},
                      generation={}, json_schema=None, correlation_id="test")
    (adapter / "adapter_model.safetensors").write_bytes(b"modified")
    with pytest.raises(ValueError, match="package file has changed"):
        LocalAdapterClient(output=tmp_path, identity=identity, device="cpu")
