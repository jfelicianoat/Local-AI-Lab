from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from local_ai_lab.domain.common import sha256_json
from local_ai_lab.domain.jobs import DisconnectPolicy, IdempotencyClass, JobSpec, ReassignmentPolicy
from local_ai_lab.training.contracts import TrainingContractReport
from local_ai_lab.training.resolver import HardwareResolution

ALLOWED_OBJECTIVES = {"behavior", "format", "style", "classification", "procedure", "tool_selection", "structured_arguments", "repeatable_transformation"}


@dataclass(frozen=True, slots=True)
class FineTuningProposal:
    proposal_id: str
    objective: str
    hypothesis: str
    baseline_evidence_sha256: str
    dataset_fingerprint: str
    contains_mutable_facts: bool
    approved_by: str | None


class TrainingPlanBuilder:
    def build(
        self,
        proposal: FineTuningProposal,
        *,
        contract: TrainingContractReport,
        hardware: HardwareResolution,
        preflight: dict[str, bool],
        base_model: str,
        chat_template_fingerprint: str,
        seed: int,
        lora_config: dict[str, Any],
    ) -> JobSpec:
        if proposal.objective not in ALLOWED_OBJECTIVES or proposal.contains_mutable_facts:
            raise ValueError("fine-tuning objective is ineligible or attempts to memorize mutable facts")
        if not proposal.approved_by:
            raise ValueError("fine-tuning proposal requires explicit human approval")
        if any(len(value) != 64 for value in (proposal.baseline_evidence_sha256, proposal.dataset_fingerprint)):
            raise ValueError("proposal evidence and dataset require SHA-256 fingerprints")
        if not contract.passed:
            raise ValueError("C1-C6 training contract has not passed")
        required_preflight = {"overfit_8_examples", "save", "reload", "resume", "contamination_check", "manifest_check"}
        if set(preflight) != required_preflight or not all(preflight.values()):
            raise ValueError("all short-training preflight checks must pass")
        if hardware.status != "selected" or not hardware.node_id:
            raise ValueError("no tested training hardware has been selected")
        payload = {
            "proposal": asdict(proposal),
            "base_model": base_model,
            "dataset_fingerprint": proposal.dataset_fingerprint,
            "chat_template_fingerprint": chat_template_fingerprint,
            "seed": seed,
            "nondeterminism_recorded": True,
            "dtype": hardware.dtype,
            "backend": hardware.backend,
            "lora_config": lora_config,
            "contract": contract.as_dict(),
            "preflight": preflight,
        }
        payload["training_manifest_fingerprint"] = sha256_json(payload)
        return JobSpec(
            kind="training.lora.v1",
            payload=payload,
            requirements={
                "node_ids": [hardware.node_id],
                "required_facts": {"gpu.backend": hardware.backend, f"dtype.{hardware.dtype}": True},
                "required_workloads": ["training.lora"],
            },
            idempotency_class=IdempotencyClass.CHECKPOINTABLE,
            disconnect_policy=DisconnectPolicy.CHECKPOINT_THEN_STOP,
            reassignment_policy=ReassignmentPolicy.HUMAN_ONLY,
        )
