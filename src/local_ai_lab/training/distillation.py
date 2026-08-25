from __future__ import annotations

import hashlib
import json
import os
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from local_ai_lab.broker.client import BrokerTaskClient
from local_ai_lab.dataset.factory import DatasetVerifier
from local_ai_lab.domain.common import canonical_json, sha256_json, utc_timestamp
from local_ai_lab.domain.jobs import (
    DisconnectPolicy,
    IdempotencyClass,
    JobSpec,
    ReassignmentPolicy,
)
from local_ai_lab.training.contracts import TrainingContractReport
from local_ai_lab.training.executor import AssistantOnlyCollator, prepare_supervised_example
from local_ai_lab.training.plan import ALLOWED_OBJECTIVES
from local_ai_lab.training.resolver import HardwareResolution


class DistillationExecutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DistillationProposal:
    proposal_id: str
    objective: str
    hypothesis: str
    baseline_evidence_sha256: str
    dataset_fingerprint: str
    teacher_model: str
    teacher_model_fingerprint: str
    student_model: str
    student_model_fingerprint: str
    teacher_license: str
    student_license: str
    teacher_outputs_training_allowed: bool
    student_finetuning_allowed: bool
    teacher_source: str
    teacher_broker_endpoint: str | None
    teacher_target_model: dict[str, str] | None
    broker_capability_fingerprint: str | None
    approved_by: str | None


class DistillationPlanBuilder:
    """Builds a recoverable sequence-level teacher-to-student training job."""

    def build(
        self,
        proposal: DistillationProposal,
        *,
        contract: TrainingContractReport,
        hardware: HardwareResolution,
        preflight: dict[str, bool],
        chat_template_fingerprint: str,
        seed: int,
        lora_config: dict[str, Any],
        generation_config: dict[str, Any],
    ) -> JobSpec:
        if proposal.objective not in ALLOWED_OBJECTIVES:
            raise ValueError("distillation objective is not eligible for supervised training")
        if not proposal.approved_by:
            raise ValueError("distillation requires explicit human approval")
        if proposal.teacher_model.strip() == proposal.student_model.strip():
            raise ValueError("teacher and student must be different models")
        if proposal.teacher_source not in {"local", "broker"}:
            raise ValueError("teacher source must be local or broker")
        if proposal.teacher_source == "broker":
            target = proposal.teacher_target_model
            if (
                not proposal.teacher_broker_endpoint
                or target is None
                or set(target) != {"provider", "deployment", "model"}
                or any(not value.strip() for value in target.values())
            ):
                raise ValueError("Broker teacher requires endpoint and exact target model")
            if proposal.teacher_model != target["model"]:
                raise ValueError("teacher model must match the exact Broker target")
            if not proposal.broker_capability_fingerprint:
                raise ValueError("Broker teacher requires a satisfied capability fingerprint")
        elif any(
            value is not None
            for value in (
                proposal.teacher_broker_endpoint,
                proposal.teacher_target_model,
                proposal.broker_capability_fingerprint,
            )
        ):
            raise ValueError("local teacher cannot carry Broker configuration")
        fingerprints = (
            proposal.baseline_evidence_sha256,
            proposal.dataset_fingerprint,
            proposal.teacher_model_fingerprint,
            proposal.student_model_fingerprint,
            chat_template_fingerprint,
        )
        if proposal.broker_capability_fingerprint is not None:
            fingerprints += (proposal.broker_capability_fingerprint,)
        if any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value.lower())
            for value in fingerprints
        ):
            raise ValueError("distillation evidence and models require SHA-256 fingerprints")
        if not proposal.teacher_license.strip() or not proposal.student_license.strip():
            raise ValueError("teacher and student licenses must be recorded")
        if not proposal.teacher_outputs_training_allowed:
            raise ValueError("teacher license does not allow using outputs for training")
        if not proposal.student_finetuning_allowed:
            raise ValueError("student license does not allow fine-tuning")
        if not contract.passed:
            raise ValueError("C1-C6 student training contract has not passed")
        required_preflight = {
            "overfit_8_examples",
            "save",
            "reload",
            "resume",
            "contamination_check",
            "manifest_check",
        }
        if set(preflight) != required_preflight or not all(preflight.values()):
            raise ValueError("all student preflight checks must pass")
        if hardware.status != "selected" or not hardware.node_id:
            raise ValueError("no tested student training hardware has been selected")
        if not isinstance(lora_config.get("rank"), int) or not 1 <= lora_config["rank"] <= 1024:
            raise ValueError("LoRA rank must be an integer between 1 and 1024")
        temperature = generation_config.get("temperature", 0.0)
        max_new_tokens = generation_config.get("max_new_tokens", 0)
        if not isinstance(temperature, (int, float)) or not 0 <= float(temperature) <= 2:
            raise ValueError("teacher temperature must be between 0 and 2")
        if not isinstance(max_new_tokens, int) or not 1 <= max_new_tokens <= 8192:
            raise ValueError("teacher max_new_tokens must be between 1 and 8192")

        payload = {
            "proposal": asdict(proposal),
            "teacher_model": proposal.teacher_model,
            "teacher_model_fingerprint": proposal.teacher_model_fingerprint,
            "teacher_source": proposal.teacher_source,
            "teacher_broker_endpoint": proposal.teacher_broker_endpoint,
            "teacher_target_model": proposal.teacher_target_model,
            "broker_capability_fingerprint": proposal.broker_capability_fingerprint,
            "student_model": proposal.student_model,
            "student_model_fingerprint": proposal.student_model_fingerprint,
            "dataset_fingerprint": proposal.dataset_fingerprint,
            "chat_template_fingerprint": chat_template_fingerprint,
            "seed": seed,
            "nondeterminism_recorded": True,
            "dtype": hardware.dtype,
            "backend": hardware.backend,
            "lora_config": lora_config,
            "generation_config": generation_config,
            "contract": contract.as_dict(),
            "preflight": preflight,
            "distillation_method": "sequence_level_supervision.v1",
        }
        payload["training_manifest_fingerprint"] = sha256_json(payload)
        return JobSpec(
            kind="training.distillation.v1",
            payload=payload,
            requirements={
                "node_ids": [hardware.node_id],
                "required_facts": {
                    "gpu.backend": hardware.backend,
                    f"dtype.{hardware.dtype}": True,
                },
                "required_workloads": ["training.lora"],
            },
            idempotency_class=IdempotencyClass.CHECKPOINTABLE,
            disconnect_policy=DisconnectPolicy.CHECKPOINT_THEN_STOP,
            reassignment_policy=ReassignmentPolicy.HUMAN_ONLY,
        )


def sequence_distill_records(
    records: Sequence[dict[str, Any]],
    generate: Callable[[Sequence[dict[str, str]]], str],
    *,
    teacher_model: str,
    teacher_model_fingerprint: str,
) -> list[dict[str, Any]]:
    """Replace only training answers with teacher outputs while preserving provenance."""
    distilled: list[dict[str, Any]] = []
    for source in records:
        messages = source.get("messages")
        if not isinstance(messages, list) or len(messages) < 2:
            raise DistillationExecutionError("distillation example has no usable conversation")
        if messages[-1].get("role") != "assistant":
            raise DistillationExecutionError("distillation source must end with an assistant answer")
        prompt = [dict(message) for message in messages[:-1]]
        response = generate(prompt).strip()
        if not response:
            raise DistillationExecutionError("teacher returned an empty response")
        source_sha256 = sha256_json(source)
        example = {
            **{key: value for key, value in source.items() if key != "messages"},
            "messages": [*prompt, {"role": "assistant", "content": response}],
            "distillation": {
                "method": "sequence_level_supervision.v1",
                "teacher_model": teacher_model,
                "teacher_model_fingerprint": teacher_model_fingerprint,
                "source_example_sha256": source_sha256,
                "teacher_response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
            },
        }
        example["example_id"] = sha256_json({"messages": example["messages"], "distillation": example["distillation"]})
        distilled.append(example)
    if not distilled:
        raise DistillationExecutionError("distillation training split is empty")
    return distilled


class TransformersSequenceDistillationExecutor:
    """Generates teacher supervision locally and trains a LoRA student without network access."""

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
            raise DistillationExecutionError(
                "distillation extras are not installed on this worker; install the locked training environment"
            ) from error

        dataset_path = Path(payload["resolved_dataset_path"]).resolve(strict=True)
        output = Path(payload["output_dir"]).resolve()
        if str(output).startswith(("\\\\", "//")) or output.exists():
            raise DistillationExecutionError("distillation output must be a new local directory")
        DatasetVerifier().verify(dataset_path)
        output.mkdir(parents=True, exist_ok=False)

        source_records = [
            json.loads(line)
            for line in (dataset_path / "train.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        teacher_model_id = payload["teacher_model"]
        student_model_id = payload["student_model"]
        dtype = payload["dtype"]
        torch_dtype = torch.bfloat16 if dtype == "bf16" else torch.float16
        seed = int(payload["seed"])
        random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

        generation_config = payload["generation_config"]
        teacher_source = payload.get("teacher_source", "local")
        broker_invocations: list[dict[str, Any]] = []
        if teacher_source == "broker":
            progress({"stage": "connecting_teacher_broker", "model": teacher_model_id})
            broker = BrokerTaskClient(
                endpoint=payload["teacher_broker_endpoint"],
                token=os.environ.get("LOCAL_AI_LAB_BROKER_TOKEN"),
                poll_interval=float(payload.get("broker_poll_interval", 2.0)),
                max_wait=float(payload.get("broker_max_wait", 1800.0)),
            )

            def generate(prompt: Sequence[dict[str, str]]) -> str:
                sequence = len(broker_invocations) + 1
                instruction = (
                    "Genera únicamente la respuesta final del asistente para este ejemplo de "
                    "entrenamiento. No añadas etiquetas, análisis ni bloques Markdown.\n\n"
                    f"CONVERSACIÓN:\n{canonical_json(list(prompt))}"
                )
                invocation = broker.invoke(
                    prompt=instruction,
                    target_model=payload["teacher_target_model"],
                    generation={
                        "temperature": float(generation_config.get("temperature", 0.0)),
                        "max_output_tokens": int(generation_config["max_new_tokens"]),
                        "seed": int(payload["seed"]),
                    },
                    json_schema=None,
                    correlation_id=f"{payload.get('correlation_id', 'distillation')}:{sequence}",
                )
                broker_invocations.append(
                    {
                        "task_id": invocation.task_id,
                        "model_used": invocation.model_used,
                        "fallback_used": invocation.fallback_used,
                        "usage": invocation.usage,
                        "cost": {
                            "amount": invocation.cost_amount,
                            "currency": invocation.cost_currency,
                            "source": invocation.cost_source,
                            "verification_status": invocation.cost_verification_status,
                        },
                    }
                )
                return invocation.text

        else:
            progress({"stage": "loading_teacher", "model": teacher_model_id})
            teacher_tokenizer = AutoTokenizer.from_pretrained(
                teacher_model_id, local_files_only=True
            )
            teacher = AutoModelForCausalLM.from_pretrained(
                teacher_model_id, local_files_only=True, torch_dtype=torch_dtype
            )
            teacher.eval()

            def generate(prompt: Sequence[dict[str, str]]) -> str:
                encoded = teacher_tokenizer.apply_chat_template(
                    list(prompt), tokenize=True, add_generation_prompt=True, return_tensors="pt"
                )
                encoded = encoded.to(teacher.device)
                temperature = float(generation_config.get("temperature", 0.0))
                generation_arguments: dict[str, Any] = {
                    "max_new_tokens": int(generation_config["max_new_tokens"]),
                    "do_sample": temperature > 0,
                    "pad_token_id": teacher_tokenizer.eos_token_id,
                }
                if temperature > 0:
                    generation_arguments["temperature"] = temperature
                with torch.inference_mode():
                    generated = teacher.generate(encoded, **generation_arguments)
                return teacher_tokenizer.decode(
                    generated[0][encoded.shape[-1]:], skip_special_tokens=True
                )

        progress({"stage": "teacher_generation", "examples": len(source_records)})
        distilled = sequence_distill_records(
            source_records,
            generate,
            teacher_model=teacher_model_id,
            teacher_model_fingerprint=payload["teacher_model_fingerprint"],
        )
        if teacher_source == "broker":
            for record, invocation in zip(distilled, broker_invocations, strict=True):
                record["distillation"]["broker_invocation"] = invocation
        else:
            teacher.to("cpu")
            del teacher
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        distilled_path = output / "distilled-train.jsonl"
        distilled_path.write_text(
            "".join(canonical_json(record) + "\n" for record in distilled),
            encoding="utf-8",
            newline="\n",
        )

        progress({"stage": "loading_student", "model": student_model_id})
        student_tokenizer = AutoTokenizer.from_pretrained(student_model_id, local_files_only=True)
        if student_tokenizer.pad_token_id is None:
            student_tokenizer.pad_token = student_tokenizer.eos_token
        template = student_tokenizer.chat_template or ""
        template_fingerprint = hashlib.sha256(template.encode("utf-8")).hexdigest()
        if template_fingerprint != payload["chat_template_fingerprint"]:
            raise DistillationExecutionError("student chat template differs from the approved preflight")
        tokenized = [
            prepare_supervised_example(
                student_tokenizer,
                record["messages"],
                max_length=int(payload.get("max_length", 4096)),
                template_fingerprint=template_fingerprint,
            )
            for record in distilled
        ]
        student = AutoModelForCausalLM.from_pretrained(
            student_model_id, local_files_only=True, torch_dtype=torch_dtype
        )
        config = payload["lora_config"]
        student = get_peft_model(
            student,
            LoraConfig(
                r=int(config["rank"]),
                lora_alpha=int(config.get("alpha", int(config["rank"]) * 2)),
                lora_dropout=float(config.get("dropout", 0.0)),
                target_modules=config.get("target_modules"),
                task_type="CAUSAL_LM",
            ),
        )
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
            model=student,
            args=arguments,
            train_dataset=tokenized,
            data_collator=AssistantOnlyCollator(pad_token_id=student_tokenizer.pad_token_id),
        )
        progress({"stage": "student_training", "examples": len(tokenized)})
        result = trainer.train(resume_from_checkpoint=payload.get("resume_from_checkpoint"))
        adapter_path = output / "adapter"
        student.save_pretrained(adapter_path, safe_serialization=True)
        student_tokenizer.save_pretrained(output / "tokenizer")
        base_reload = AutoModelForCausalLM.from_pretrained(
            student_model_id, local_files_only=True, torch_dtype=torch_dtype
        )
        PeftModel.from_pretrained(base_reload, adapter_path, local_files_only=True)

        files = [path for path in sorted(output.rglob("*")) if path.is_file()]
        manifest = {
            "schema_version": "distillation-result.v1",
            "method": "sequence_level_supervision.v1",
            "teacher_model": teacher_model_id,
            "teacher_model_fingerprint": payload["teacher_model_fingerprint"],
            "teacher_source": teacher_source,
            "teacher_target_model": payload.get("teacher_target_model"),
            "broker_capability_fingerprint": payload.get("broker_capability_fingerprint"),
            "broker_invocations": broker_invocations,
            "student_model": student_model_id,
            "student_model_fingerprint": payload["student_model_fingerprint"],
            "source_dataset_fingerprint": payload["dataset_fingerprint"],
            "distilled_examples": len(distilled),
            "distilled_dataset_sha256": hashlib.sha256(distilled_path.read_bytes()).hexdigest(),
            "chat_template_fingerprint": template_fingerprint,
            "generation_config": generation_config,
            "seed": seed,
            "dtype": dtype,
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
        manifest["content_sha256"] = hashlib.sha256(
            canonical_json(manifest).encode("utf-8")
        ).hexdigest()
        manifest_path = output / "distillation-manifest.json"
        manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8", newline="\n")
        progress({"stage": "reload_verification"})
        return {
            "output_dir": str(output),
            "manifest_sha256": manifest["content_sha256"],
            "manifest_file_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "adapter_path": str(adapter_path),
            "distilled_dataset_path": str(distilled_path),
            "distilled_examples": len(distilled),
            "metrics": manifest["metrics"],
        }
