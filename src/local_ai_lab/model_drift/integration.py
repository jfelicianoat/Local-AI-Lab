from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from local_ai_lab.domain.common import canonical_json, utc_timestamp


class ModelDriftCompatibilityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandTransport(Protocol):
    def run(self, command: Sequence[str], *, cwd: Path, timeout: float) -> CommandResult: ...


class SubprocessTransport:
    def run(self, command: Sequence[str], *, cwd: Path, timeout: float) -> CommandResult:
        completed = subprocess.run(
            list(command), cwd=cwd, timeout=timeout, check=False, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True, slots=True)
class ModelDriftCliCapabilities:
    executable_observed: bool
    run_command: bool
    compare_command: bool
    external_treatments: bool
    broker_contract_required: str
    status: str
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExternalTreatmentRef:
    experiment_id: str
    strategy_id: str
    artifact_path: str
    artifact_sha256: str
    artifact_kind: str = "retrieval_benchmark_report"

    def validate(self) -> None:
        if not self.experiment_id.strip() or self.strategy_id not in {"R3", "R4"}:
            raise ValueError("external treatment requires an R3/R4 experiment identity")
        if len(self.artifact_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.artifact_sha256
        ):
            raise ValueError("external treatment artifact requires lowercase SHA-256")
        path = Path(self.artifact_path).resolve(strict=True)
        if not path.is_file() or str(path).startswith(("\\\\", "//")):
            raise ValueError("external treatment artifact must be a local regular file")


@dataclass(frozen=True, slots=True)
class FormalEvaluationPlan:
    experiment_id: str
    correlation_id: str
    suite_fingerprint: str
    snapshot_hash: str
    baseline: ExternalTreatmentRef
    candidate: ExternalTreatmentRef
    fallback_allowed: bool = False
    exclude_from_model_learning: bool = True
    schema_version: str = "local-ai-lab.model-drift-plan.v2"

    def validate(self) -> None:
        values = (self.suite_fingerprint, self.snapshot_hash)
        if any(len(value) != 64 or any(char not in "0123456789abcdef" for char in value) for value in values):
            raise ValueError("suite and snapshot require lowercase SHA-256")
        self.baseline.validate()
        self.candidate.validate()
        if self.baseline.strategy_id != "R3" or self.candidate.strategy_id != "R4":
            raise ValueError("formal comparison requires R3 as baseline and R4 as candidate")
        if self.baseline.experiment_id == self.candidate.experiment_id:
            raise ValueError("formal comparison requires two different experiments")
        if self.fallback_allowed or not self.exclude_from_model_learning:
            raise ValueError("formal comparison forbids fallback and learning contamination")


class ModelDriftIntegration:
    """Uses Model Drift only through its public CLI; never through its database."""

    def __init__(
        self,
        *,
        command_prefix: Sequence[str],
        working_directory: Path,
        transport: CommandTransport | None = None,
    ) -> None:
        if not command_prefix:
            raise ValueError("Model Drift command prefix cannot be empty")
        self.command_prefix = tuple(command_prefix)
        self.working_directory = working_directory.resolve(strict=True)
        self.transport = transport or SubprocessTransport()

    def inspect(self, *, timeout: float = 10.0) -> ModelDriftCliCapabilities:
        top = self.transport.run((*self.command_prefix, "--help"), cwd=self.working_directory, timeout=timeout)
        if top.returncode != 0:
            return ModelDriftCliCapabilities(
                False, False, False, False, "2.9", "unavailable",
                ("Model Drift CLI could not be inspected through --help",),
            )
        text = (top.stdout + "\n" + top.stderr).casefold()
        run_command = "ejecutar" in text
        compare_command = "comparar" in text
        external_treatments = any(
            marker in text for marker in ("evaluar-tratamientos", "external-treatments", "tratamientos-externos")
        )
        limitations: list[str] = []
        if not run_command or not compare_command:
            limitations.append("the stable ejecutar/comparar CLI is incomplete")
        if not external_treatments:
            limitations.append("the CLI does not advertise paired external RAG treatments")
        status = "satisfied" if not limitations else "blocked"
        return ModelDriftCliCapabilities(
            True, run_command, compare_command, external_treatments, "2.9", status,
            tuple(limitations),
        )

    def write_plan(self, plan: FormalEvaluationPlan, output: Path) -> Path:
        plan.validate()
        target = output.resolve()
        if str(target).startswith(("\\\\", "//")):
            raise ValueError("formal evaluation plans must be written to local storage")
        if target.exists():
            raise FileExistsError("refusing to replace a formal evaluation plan")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {**asdict(plan), "created_at": utc_timestamp()}
        payload["content_sha256"] = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        target.write_text(canonical_json(payload) + "\n", encoding="utf-8", newline="\n")
        return target

    def require_rag_treatments(self, capabilities: ModelDriftCliCapabilities) -> None:
        if capabilities.status != "satisfied" or not capabilities.external_treatments:
            raise ModelDriftCompatibilityError(
                "Model Drift cannot formally compare R3/R4 through its current public CLI; "
                "install or expose a stable external-treatment contract before executing the gate"
            )

    def model_run_command(
        self, *, suite: Path, model: str, repetitions: int, label: str
    ) -> tuple[str, ...]:
        if repetitions < 1 or not model.strip() or not label.strip():
            raise ValueError("model run requires model, label and positive repetitions")
        return (
            *self.command_prefix, "ejecutar", str(suite.resolve()), "--modelo", model,
            "--repeticiones", str(repetitions), "--etiqueta", label,
        )

    def comparison_command(
        self, *, baseline_run: str, candidate_run: str, suite: Path, report: Path
    ) -> tuple[str, ...]:
        return (
            *self.command_prefix, "comparar", baseline_run, candidate_run,
            "--suite", str(suite.resolve()), "--informe", str(report.resolve()),
        )

    def external_treatment_command(
        self, *, plan: Path, report: Path
    ) -> tuple[str, ...]:
        return (
            *self.command_prefix, "evaluar-tratamientos",
            "--plan", str(plan.resolve(strict=True)),
            "--informe", str(report.resolve()),
        )

    def execute_external_treatments(
        self, *, plan: Path, report: Path, timeout: float = 7200.0
    ) -> CommandResult:
        capabilities = self.inspect()
        self.require_rag_treatments(capabilities)
        if report.exists():
            raise FileExistsError("refusing to replace a Model Drift report")
        result = self.transport.run(
            self.external_treatment_command(plan=plan, report=report),
            cwd=self.working_directory, timeout=timeout,
        )
        if result.returncode != 0 or not report.is_file():
            raise ModelDriftCompatibilityError(
                "Model Drift external-treatment execution failed through its public CLI: "
                + result.stderr[-1000:]
            )
        return result
