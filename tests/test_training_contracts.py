from __future__ import annotations

import pytest

from local_ai_lab.capabilities.model import CapabilityFact, NodeCapabilityReport
from local_ai_lab.training.contracts import TrainingContractValidator
from local_ai_lab.training.executor import AssistantOnlyCollator, TrainingExecutionError, prepare_supervised_example
from local_ai_lab.training.plan import FineTuningProposal, TrainingPlanBuilder
from local_ai_lab.training.resolver import TrainingHardwareResolver


def _example(**changes):
    value = {
        "input_ids": [10, 11, 20, 21, 2, 0],
        "labels": [-100, -100, 20, 21, 2, -100],
        "attention_mask": [1, 1, 1, 1, 1, 0],
        "assistant_start": 2,
        "eos_token_id": 2,
        "pad_token_id": 0,
        "assistant_truncated": False,
        "template_fingerprint": "template-v1",
    }
    value.update(changes)
    return value


def _report(node: str, *, status: str = "tested", bf16: bool = True, memory: int = 16):
    facts = [
        CapabilityFact("training.lora", True, status, "probe", "2026-08-23T00:00:00Z"),
        CapabilityFact("training.backward", True, status, "probe", "2026-08-23T00:00:00Z"),
        CapabilityFact("training.checkpoint_resume", True, status, "probe", "2026-08-23T00:00:00Z"),
        CapabilityFact("training.twenty_steps", True, status, "probe", "2026-08-23T00:00:00Z"),
        CapabilityFact("gpu.backend", "cuda", status, "probe", "2026-08-23T00:00:00Z"),
        CapabilityFact("dtype.bf16", bf16, status, "probe", "2026-08-23T00:00:00Z"),
        CapabilityFact("dtype.fp16", True, status, "probe", "2026-08-23T00:00:00Z"),
        CapabilityFact("gpu.usable_memory_gib", memory, status, "probe", "2026-08-23T00:00:00Z", "GiB"),
    ]
    return NodeCapabilityReport("v1", f"report-{node}", node, "stable", "2026-08-23T00:00:00Z", facts=facts)


def test_c1_to_c6_pass_for_correct_supervised_batch() -> None:
    report = TrainingContractValidator().validate(
        [_example()], expected_template_fingerprint="template-v1", seed=42,
        nondeterminism_notes=["CUDA kernels may be nondeterministic"],
    )

    assert report.passed is True
    assert all(report.as_dict()[name] for name in (
        "c1_assistant_only_loss", "c2_supervised_eos", "c3_same_chat_template",
        "c4_assistant_not_truncated", "c5_padding_outside_loss",
        "c6_seed_and_nondeterminism_recorded",
    ))


def test_contract_detects_prompt_loss_truncation_padding_and_missing_seed() -> None:
    bad = _example(
        labels=[10, -100, 20, 21, -100, 0], assistant_truncated=True,
        template_fingerprint="other",
    )
    report = TrainingContractValidator().validate(
        [bad], expected_template_fingerprint="template-v1", seed=None,
        nondeterminism_notes=[],
    )

    assert report.passed is False
    assert report.c1_assistant_only_loss is False
    assert report.c2_supervised_eos is False
    assert report.c3_same_chat_template is False
    assert report.c4_assistant_not_truncated is False
    assert report.c5_padding_outside_loss is False
    assert report.c6_seed_and_nondeterminism_recorded is False


def test_hardware_resolver_uses_only_tested_facts_and_prefers_bf16() -> None:
    declared = _report("declared-node", status="declared", memory=128)
    tested = _report("tested-node", status="tested", bf16=True, memory=16)
    resolution = TrainingHardwareResolver().resolve([declared, tested])

    assert resolution.status == "selected"
    assert resolution.node_id == "tested-node"
    assert resolution.dtype == "bf16"
    assert any("declared-node" in reason for reason in resolution.reasons)


def test_long_training_job_requires_every_gate_and_is_checkpointable() -> None:
    contract = TrainingContractValidator().validate(
        [_example()], expected_template_fingerprint="template-v1", seed=42,
        nondeterminism_notes=["runtime-specific kernels recorded"],
    )
    hardware = TrainingHardwareResolver().resolve([_report("node-1")])
    proposal = FineTuningProposal(
        "proposal-1", "format", "Reduce schema failures", "a" * 64, "b" * 64,
        False, "lead@example",
    )
    preflight = {
        "overfit_8_examples": True, "save": True, "reload": True, "resume": True,
        "contamination_check": True, "manifest_check": True,
    }
    job = TrainingPlanBuilder().build(
        proposal, contract=contract, hardware=hardware, preflight=preflight,
        base_model="local/model", chat_template_fingerprint="template-v1", seed=42,
        lora_config={"rank": 8, "alpha": 16},
    )

    assert job.kind == "training.lora.v1"
    assert job.idempotency_class.value == "checkpointable"
    assert job.disconnect_policy.value == "checkpoint_then_stop"
    assert job.reassignment_policy.value == "human_only"


def test_fine_tuning_cannot_be_used_to_memorize_mutable_vault_facts() -> None:
    contract = TrainingContractValidator().validate(
        [_example()], expected_template_fingerprint="template-v1", seed=1,
        nondeterminism_notes=["noted"],
    )
    proposal = FineTuningProposal(
        "proposal-1", "behavior", "Memorize current vault", "a" * 64, "b" * 64,
        True, "lead",
    )
    with pytest.raises(ValueError, match="memorize mutable facts"):
        TrainingPlanBuilder().build(
            proposal, contract=contract, hardware=TrainingHardwareResolver().resolve([_report("node")]),
            preflight={
                "overfit_8_examples": True, "save": True, "reload": True, "resume": True,
                "contamination_check": True, "manifest_check": True,
            },
            base_model="local/model", chat_template_fingerprint="template-v1", seed=1,
            lora_config={"rank": 8},
        )


class FakeTokenizer:
    eos_token_id = 2
    pad_token_id = 0

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        prompt = [10, 11, 12]
        if add_generation_prompt:
            return prompt
        return prompt + [20, 21]


def test_training_executor_preparation_masks_prompt_and_supervises_eos() -> None:
    example = prepare_supervised_example(
        FakeTokenizer(),
        [{"role": "user", "content": "Q"}, {"role": "assistant", "content": "A"}],
        max_length=10, template_fingerprint="template-v1",
    )

    assert example["input_ids"] == [10, 11, 12, 20, 21, 2]
    assert example["labels"] == [-100, -100, -100, 20, 21, 2]
    assert example["assistant_truncated"] is False


def test_training_executor_rejects_assistant_truncation_instead_of_clipping() -> None:
    with pytest.raises(TrainingExecutionError, match="truncate inside"):
        prepare_supervised_example(
            FakeTokenizer(),
            [{"role": "user", "content": "Q"}, {"role": "assistant", "content": "A"}],
            max_length=5, template_fingerprint="template-v1",
        )


def test_assistant_collator_keeps_padding_outside_loss_without_torch_dependency() -> None:
    collator = AssistantOnlyCollator(pad_token_id=0)
    batch = collator([
        {"input_ids": [1, 2], "labels": [-100, 2], "attention_mask": [1, 1]},
        {"input_ids": [1], "labels": [1], "attention_mask": [1]},
    ])
    labels = batch["labels"].tolist() if hasattr(batch["labels"], "tolist") else batch["labels"]
    attention = batch["attention_mask"].tolist() if hasattr(batch["attention_mask"], "tolist") else batch["attention_mask"]

    assert labels[1] == [1, -100]
    assert attention[1] == [1, 0]
