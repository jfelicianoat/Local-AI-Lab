from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

import local_ai_lab.training.distillation as distillation_module
from local_ai_lab.training.contracts import TrainingContractReport
from local_ai_lab.training.distillation import (
    DistillationExecutionError,
    DistillationPlanBuilder,
    DistillationProposal,
    TransformersSequenceDistillationExecutor,
    sequence_distill_records,
)
from local_ai_lab.training.resolver import HardwareResolution
from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.domain.common import canonical_json, sha256_json
from local_ai_lab.domain.jobs import JobSpec


def _proposal(**changes: object) -> DistillationProposal:
    values: dict[str, object] = {
        "proposal_id": "distill-1",
        "objective": "behavior",
        "hypothesis": "El alumno igualará al profesor con menor coste local.",
        "baseline_evidence_sha256": "a" * 64,
        "dataset_fingerprint": "b" * 64,
        "teacher_model": "local/teacher-7b",
        "teacher_model_fingerprint": "c" * 64,
        "student_model": "local/student-1b",
        "student_model_fingerprint": "d" * 64,
        "teacher_license": "Apache-2.0",
        "student_license": "Apache-2.0",
        "teacher_outputs_training_allowed": True,
        "student_finetuning_allowed": True,
        "teacher_source": "local",
        "teacher_broker_endpoint": None,
        "teacher_target_model": None,
        "broker_capability_fingerprint": None,
        "approved_by": "lead-reviewer",
    }
    values.update(changes)
    return DistillationProposal(**values)  # type: ignore[arg-type]


def _contract() -> TrainingContractReport:
    return TrainingContractReport(True, True, True, True, True, True, ())


def _checks() -> dict[str, bool]:
    return {
        "overfit_8_examples": True,
        "save": True,
        "reload": True,
        "resume": True,
        "contamination_check": True,
        "manifest_check": True,
    }


def test_sequence_distillation_preserves_prompt_and_records_teacher_provenance() -> None:
    source = [{
        "example_id": "source-1",
        "split": "train",
        "messages": [
            {"role": "system", "content": "Responde en JSON."},
            {"role": "user", "content": "Clasifica este caso."},
            {"role": "assistant", "content": "respuesta humana original"},
        ],
        "provenance": {"review_id": "review-1"},
    }]
    original = deepcopy(source)

    distilled = sequence_distill_records(
        source,
        lambda prompt: '{"label":"positivo"}',
        teacher_model="local/teacher-7b",
        teacher_model_fingerprint="c" * 64,
    )

    assert source == original
    assert distilled[0]["messages"][:-1] == source[0]["messages"][:-1]
    assert distilled[0]["messages"][-1]["content"] == '{"label":"positivo"}'
    assert distilled[0]["provenance"] == {"review_id": "review-1"}
    assert distilled[0]["distillation"]["method"] == "sequence_level_supervision.v1"
    assert distilled[0]["distillation"]["teacher_model_fingerprint"] == "c" * 64
    assert len(distilled[0]["distillation"]["source_example_sha256"]) == 64
    assert len(distilled[0]["example_id"]) == 64


def test_sequence_distillation_rejects_empty_teacher_output() -> None:
    with pytest.raises(DistillationExecutionError, match="empty response"):
        sequence_distill_records(
            [{"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}],
            lambda _: "  ",
            teacher_model="teacher",
            teacher_model_fingerprint="c" * 64,
        )


def test_distillation_plan_is_checkpointable_and_keeps_models_distinct() -> None:
    job = DistillationPlanBuilder().build(
        _proposal(),
        contract=_contract(),
        hardware=HardwareResolution("selected", "worker-1", "cuda", "bf16", ()),
        preflight=_checks(),
        chat_template_fingerprint="e" * 64,
        seed=42,
        lora_config={"rank": 8, "alpha": 16},
        generation_config={"temperature": 0.0, "max_new_tokens": 512},
    )

    assert job.kind == "training.distillation.v1"
    assert job.idempotency_class.value == "checkpointable"
    assert job.disconnect_policy.value == "checkpoint_then_stop"
    assert job.reassignment_policy.value == "human_only"
    assert job.payload["teacher_model"] == "local/teacher-7b"
    assert job.payload["teacher_source"] == "local"
    assert job.payload["student_model"] == "local/student-1b"
    assert job.payload["distillation_method"] == "sequence_level_supervision.v1"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"student_model": "local/teacher-7b"}, "different models"),
        ({"teacher_outputs_training_allowed": False}, "teacher license"),
        ({"student_finetuning_allowed": False}, "student license"),
        ({"approved_by": None}, "human approval"),
    ],
)
def test_distillation_plan_rejects_unsafe_proposals(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        DistillationPlanBuilder().build(
            _proposal(**changes),
            contract=_contract(),
            hardware=HardwareResolution("selected", "worker-1", "cuda", "bf16", ()),
            preflight=_checks(),
            chat_template_fingerprint="e" * 64,
            seed=42,
            lora_config={"rank": 8},
            generation_config={"temperature": 0.0, "max_new_tokens": 256},
        )


def test_distillation_plan_accepts_exact_broker_teacher_without_a_token() -> None:
    job = DistillationPlanBuilder().build(
        _proposal(
            teacher_source="broker",
            teacher_model="qwen-teacher",
            teacher_broker_endpoint="http://127.0.0.1:8000",
            teacher_target_model={
                "provider": "local",
                "deployment": "qwen-teacher",
                "model": "qwen-teacher",
            },
            broker_capability_fingerprint="f" * 64,
        ),
        contract=_contract(),
        hardware=HardwareResolution("selected", "worker-1", "cuda", "bf16", ()),
        preflight=_checks(),
        chat_template_fingerprint="e" * 64,
        seed=42,
        lora_config={"rank": 8},
        generation_config={"temperature": 0.0, "max_new_tokens": 256},
    )

    assert job.payload["teacher_source"] == "broker"
    assert job.payload["teacher_target_model"]["model"] == "qwen-teacher"
    assert job.payload["broker_capability_fingerprint"] == "f" * 64
    assert "token" not in job.payload
    assert "broker_token" not in job.payload


def test_successful_distillation_promotes_product_and_worker_evidence(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    pairing = service.create_pairing_code()
    registration = service.pair_and_register(
        pairing_code=pairing, node_id="worker-distill", hostname="distill-host"
    )
    token = registration["device_token"]
    job = JobSpec(
        kind="training.distillation.v1",
        payload={"teacher_model": "teacher", "student_model": "student"},
        requirements={"node_ids": ["worker-distill"]},
    )
    service.submit_job(job, "submit-distillation-fixture")
    service.record_product_item(
        record_id=job.job_id,
        category="training",
        title="Destilación · teacher → student",
        status="DISTILLATION_QUEUED",
        artifact_sha256=job.fingerprint(),
        summary={"job_id": job.job_id, "kind": job.kind},
    )
    lease = service.claim_job(
        node_id="worker-distill", token=token, idempotency_key="claim-distillation"
    )
    service.ack_job(
        node_id="worker-distill",
        token=token,
        job_id=job.job_id,
        lease_token=lease["lease_token"],
        lease_generation=lease["lease_generation"],
        idempotency_key="ack-distillation",
    )
    service.complete_job(
        node_id="worker-distill",
        token=token,
        job_id=job.job_id,
        attempt_id=lease["attempt_id"],
        lease_token=lease["lease_token"],
        lease_generation=lease["lease_generation"],
        outcome="succeeded",
        payload={
            "manifest_sha256": "a" * 64,
            "manifest_file_sha256": "b" * 64,
            "distilled_examples": 12,
        },
        idempotency_key="complete-distillation",
    )

    assert service.repository.product_record(job.job_id)["status"] == "DISTILLATION_SUCCEEDED"
    node = service.repository.node_record("worker-distill")
    workloads = {
        item["kind"]: item["status"]
        for item in json.loads(node["capabilities_json"])["workloads"]
    }
    assert workloads["training.distillation"] == "benchmarked"
    assert workloads["export.adapter"] == "tested"


def test_distillation_executor_generates_trains_reloads_and_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    example = {
        "example_id": "e" * 64,
        "split": "train",
        "messages": [
            {"role": "system", "content": "Responde con precisión."},
            {"role": "user", "content": "Explica la destilación."},
            {"role": "assistant", "content": "Respuesta humana."},
        ],
        "provenance": {"review_id": "review-1"},
    }
    payloads = {
        "train.jsonl": (canonical_json(example) + "\n").encode(),
        "validation.jsonl": b"",
        "test.jsonl": b"",
        "audit.jsonl": b"",
    }
    for name, data in payloads.items():
        (dataset / name).write_bytes(data)
    split_seed_sha256 = hashlib.sha256(b"seed").hexdigest()
    fingerprint = sha256_json(
        {
            "format": "local-ai-lab.dataset.v1",
            "examples": [example["example_id"]],
            "split_seed_sha256": split_seed_sha256,
            "benchmark_fingerprints": [],
        }
    )
    manifest = {
        "format": "local-ai-lab.dataset.v1",
        "dataset_id": "dataset-distill",
        "name": "distillation-fixture",
        "fingerprint": fingerprint,
        "training_eligible": True,
        "split_seed_sha256": split_seed_sha256,
        "benchmark_case_ids_excluded": [],
        "benchmark_fingerprints": [],
        "counts": {"included": 1, "excluded": 0, "train": 1, "validation": 0, "test": 0},
        "artifacts": {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
    }
    (dataset / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8")

    template = "fixture-chat-template"
    template_fingerprint = hashlib.sha256(template.encode()).hexdigest()
    calls: dict[str, object] = {"loaded": [], "reload_verified": False, "resume": None}

    class FakeTensor:
        shape = (1, 2)

        def to(self, _device: str) -> "FakeTensor":
            return self

    class FakeTokenizer:
        eos_token_id = 2
        pad_token_id = 0
        eos_token = "</s>"
        pad_token = "<pad>"
        chat_template = template

        def apply_chat_template(
            self,
            messages: list[dict[str, str]],
            *,
            tokenize: bool,
            add_generation_prompt: bool,
            return_tensors: str | None = None,
        ) -> object:
            assert tokenize is True
            if return_tensors == "pt":
                return FakeTensor()
            return [10, 11] if add_generation_prompt else [10, 11, 12]

        def decode(self, _tokens: object, *, skip_special_tokens: bool) -> str:
            assert skip_special_tokens is True
            return "Respuesta sintetizada por el profesor."

        def save_pretrained(self, path: Path) -> None:
            path.mkdir(parents=True)
            (path / "tokenizer.json").write_text("{}", encoding="utf-8")

    class FakeModel:
        device = "cpu"

        def eval(self) -> None:
            return None

        def generate(self, _encoded: FakeTensor, **arguments: object) -> list[list[int]]:
            assert arguments["do_sample"] is False
            return [[10, 11, 90, 91]]

        def to(self, _device: str) -> "FakeModel":
            return self

        def save_pretrained(self, path: Path, *, safe_serialization: bool) -> None:
            assert safe_serialization is True
            path.mkdir(parents=True)
            (path / "adapter_model.safetensors").write_bytes(b"adapter")

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(model: str, *, local_files_only: bool) -> FakeTokenizer:
            assert local_files_only is True
            cast = calls["loaded"]
            assert isinstance(cast, list)
            cast.append(("tokenizer", model))
            return FakeTokenizer()

    class AutoModelForCausalLM:
        @staticmethod
        def from_pretrained(model: str, *, local_files_only: bool, torch_dtype: object) -> FakeModel:
            assert local_files_only is True
            assert torch_dtype == "bf16"
            cast = calls["loaded"]
            assert isinstance(cast, list)
            cast.append(("model", model))
            return FakeModel()

    class TrainingArguments:
        def __init__(self, **values: object) -> None:
            self.output_dir = str(values["output_dir"])

    class Trainer:
        def __init__(self, *, model: FakeModel, args: TrainingArguments, train_dataset: list[dict[str, object]], data_collator: object) -> None:
            self.model = model
            self.args = args
            self.train_dataset = train_dataset
            self.data_collator = data_collator

        def train(self, *, resume_from_checkpoint: object) -> SimpleNamespace:
            calls["resume"] = resume_from_checkpoint
            batch = self.data_collator(self.train_dataset)  # type: ignore[operator]
            assert batch["labels"][0][0] == -100
            checkpoint = Path(self.args.output_dir) / "checkpoint-1"
            checkpoint.mkdir(parents=True)
            (checkpoint / "trainer_state.json").write_text("{}", encoding="utf-8")
            return SimpleNamespace(metrics={"train_loss": 0.125, "train_steps": 1})

    class LoraConfig:
        def __init__(self, **values: object) -> None:
            assert values["task_type"] == "CAUSAL_LM"

    class PeftModel:
        @staticmethod
        def from_pretrained(model: FakeModel, path: Path, *, local_files_only: bool) -> FakeModel:
            assert isinstance(model, FakeModel)
            assert (path / "adapter_model.safetensors").is_file()
            assert local_files_only is True
            calls["reload_verified"] = True
            return model

    torch = ModuleType("torch")
    torch.bfloat16 = "bf16"  # type: ignore[attr-defined]
    torch.float16 = "fp16"  # type: ignore[attr-defined]
    torch.long = "long"  # type: ignore[attr-defined]
    torch.manual_seed = lambda _seed: None  # type: ignore[attr-defined]
    torch.tensor = lambda values, dtype: values  # type: ignore[attr-defined]
    torch.cuda = SimpleNamespace(is_available=lambda: False)  # type: ignore[attr-defined]
    torch.inference_mode = lambda: pytest.MonkeyPatch.context()  # type: ignore[attr-defined]
    peft = ModuleType("peft")
    peft.LoraConfig = LoraConfig  # type: ignore[attr-defined]
    peft.PeftModel = PeftModel  # type: ignore[attr-defined]
    peft.get_peft_model = lambda model, _config: model  # type: ignore[attr-defined]
    transformers = ModuleType("transformers")
    transformers.AutoModelForCausalLM = AutoModelForCausalLM  # type: ignore[attr-defined]
    transformers.AutoTokenizer = AutoTokenizer  # type: ignore[attr-defined]
    transformers.Trainer = Trainer  # type: ignore[attr-defined]
    transformers.TrainingArguments = TrainingArguments  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "peft", peft)
    monkeypatch.setitem(sys.modules, "transformers", transformers)

    stages: list[dict[str, object]] = []
    output = tmp_path / "distillation-output"
    result = TransformersSequenceDistillationExecutor()(
        {
            "resolved_dataset_path": str(dataset),
            "output_dir": str(output),
            "teacher_model": "local/teacher",
            "teacher_model_fingerprint": "a" * 64,
            "student_model": "local/student",
            "student_model_fingerprint": "b" * 64,
            "dataset_fingerprint": fingerprint,
            "chat_template_fingerprint": template_fingerprint,
            "generation_config": {"temperature": 0.0, "max_new_tokens": 64},
            "lora_config": {"rank": 4, "alpha": 8},
            "dtype": "bf16",
            "seed": 7,
            "max_steps": 1,
            "resume_from_checkpoint": "checkpoint-approved",
        },
        stages.append,
    )

    distilled = json.loads((output / "distilled-train.jsonl").read_text(encoding="utf-8"))
    result_manifest = json.loads((output / "distillation-manifest.json").read_text(encoding="utf-8"))
    assert distilled["messages"][-1]["content"] == "Respuesta sintetizada por el profesor."
    assert distilled["distillation"]["teacher_model"] == "local/teacher"
    assert calls["reload_verified"] is True
    assert calls["resume"] == "checkpoint-approved"
    assert result_manifest["distilled_examples"] == 1
    assert result_manifest["metrics"] == {"train_loss": 0.125, "train_steps": 1}
    assert result["manifest_sha256"] == result_manifest["content_sha256"]
    assert [stage["stage"] for stage in stages] == [
        "loading_teacher",
        "teacher_generation",
        "loading_student",
        "student_training",
        "reload_verification",
    ]

    class FakeBrokerClient:
        def __init__(self, *, endpoint: str, token: str | None, **_values: object) -> None:
            assert endpoint == "http://127.0.0.1:8000"
            assert token == "test-only-token"

        def invoke(self, **values: object) -> SimpleNamespace:
            assert values["target_model"] == {
                "provider": "local",
                "deployment": "qwen-teacher",
                "model": "qwen-teacher",
            }
            assert values["json_schema"] is None
            generation = values["generation"]
            assert isinstance(generation, dict)
            assert generation["max_output_tokens"] == 64
            return SimpleNamespace(
                task_id="broker-task-1",
                text="Respuesta del profesor servido por AI Broker.",
                model_used=values["target_model"],
                fallback_used=False,
                usage={"output_tokens": 9},
                cost_amount=None,
                cost_currency="USD",
                cost_source="not_available",
                cost_verification_status="unknown",
            )

    monkeypatch.setenv("LOCAL_AI_LAB_BROKER_TOKEN", "test-only-token")
    monkeypatch.setattr(distillation_module, "BrokerTaskClient", FakeBrokerClient)
    broker_stages: list[dict[str, object]] = []
    broker_output = tmp_path / "broker-distillation-output"
    broker_result = TransformersSequenceDistillationExecutor()(
        {
            "resolved_dataset_path": str(dataset),
            "output_dir": str(broker_output),
            "teacher_source": "broker",
            "teacher_broker_endpoint": "http://127.0.0.1:8000",
            "teacher_target_model": {
                "provider": "local",
                "deployment": "qwen-teacher",
                "model": "qwen-teacher",
            },
            "broker_capability_fingerprint": "f" * 64,
            "correlation_id": "distill-broker",
            "teacher_model": "qwen-teacher",
            "teacher_model_fingerprint": "a" * 64,
            "student_model": "local/student",
            "student_model_fingerprint": "b" * 64,
            "dataset_fingerprint": fingerprint,
            "chat_template_fingerprint": template_fingerprint,
            "generation_config": {"temperature": 0.0, "max_new_tokens": 64},
            "lora_config": {"rank": 4, "alpha": 8},
            "dtype": "bf16",
            "seed": 7,
            "max_steps": 1,
        },
        broker_stages.append,
    )
    broker_record = json.loads(
        (broker_output / "distilled-train.jsonl").read_text(encoding="utf-8")
    )
    broker_manifest = json.loads(
        (broker_output / "distillation-manifest.json").read_text(encoding="utf-8")
    )
    assert broker_record["messages"][-1]["content"] == "Respuesta del profesor servido por AI Broker."
    assert broker_record["distillation"]["broker_invocation"]["task_id"] == "broker-task-1"
    assert broker_manifest["teacher_source"] == "broker"
    assert broker_manifest["broker_invocations"][0]["fallback_used"] is False
    assert broker_result["distilled_examples"] == 1
    assert [stage["stage"] for stage in broker_stages] == [
        "connecting_teacher_broker",
        "teacher_generation",
        "loading_student",
        "student_training",
        "reload_verification",
    ]
