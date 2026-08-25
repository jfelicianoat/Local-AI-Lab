from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from local_ai_lab.model_drift.integration import (
    CommandResult,
    ExternalTreatmentRef,
    FormalEvaluationPlan,
    ModelDriftCompatibilityError,
    ModelDriftIntegration,
)


class FakeTransport:
    def __init__(self, help_text: str, returncode: int = 0) -> None:
        self.help_text = help_text
        self.returncode = returncode
        self.commands = []

    def run(self, command, *, cwd, timeout):
        self.commands.append(tuple(command))
        return CommandResult(self.returncode, self.help_text, "")


def _integration(tmp_path: Path, text: str) -> ModelDriftIntegration:
    return ModelDriftIntegration(
        command_prefix=("python", "-m", "model_drift.cli"),
        working_directory=tmp_path,
        transport=FakeTransport(text),
    )


def test_current_public_cli_is_detected_but_rag_gate_stays_blocked(tmp_path: Path) -> None:
    integration = _integration(tmp_path, "commands: ejecutar comparar modelos tiradas")
    capabilities = integration.inspect()

    assert capabilities.executable_observed is True
    assert capabilities.run_command is True
    assert capabilities.compare_command is True
    assert capabilities.external_treatments is False
    assert capabilities.broker_contract_required == "2.9"
    with pytest.raises(ModelDriftCompatibilityError, match="cannot formally compare R3/R4"):
        integration.require_rag_treatments(capabilities)


def test_future_external_treatment_contract_can_satisfy_compatibility(tmp_path: Path) -> None:
    integration = _integration(
        tmp_path, "commands: ejecutar comparar evaluar-tratamientos external-treatments"
    )
    capabilities = integration.inspect()

    assert capabilities.status == "satisfied"
    integration.require_rag_treatments(capabilities)


def test_formal_plan_is_immutable_hashed_and_forbids_fallback(tmp_path: Path) -> None:
    integration = _integration(tmp_path, "ejecutar comparar")
    r3 = tmp_path / "r3.zip"
    r4 = tmp_path / "r4.zip"
    r3.write_bytes(b"r3")
    r4.write_bytes(b"r4")
    plan = FormalEvaluationPlan(
        experiment_id="exp-1", correlation_id="corr-1", suite_fingerprint="a" * 64,
        snapshot_hash="b" * 64,
        baseline=ExternalTreatmentRef(
            experiment_id="r3", strategy_id="R3", artifact_path=str(r3),
            artifact_sha256=hashlib.sha256(r3.read_bytes()).hexdigest(),
        ),
        candidate=ExternalTreatmentRef(
            experiment_id="r4", strategy_id="R4", artifact_path=str(r4),
            artifact_sha256=hashlib.sha256(r4.read_bytes()).hexdigest(),
        ),
    )
    target = integration.write_plan(plan, tmp_path / "plans" / "formal.json")
    payload = json.loads(target.read_text(encoding="utf-8"))

    assert payload["fallback_allowed"] is False
    assert payload["exclude_from_model_learning"] is True
    assert payload["schema_version"] == "local-ai-lab.model-drift-plan.v2"
    assert payload["baseline"]["strategy_id"] == "R3"
    assert len(payload["content_sha256"]) == 64
    with pytest.raises(FileExistsError):
        integration.write_plan(plan, target)


def test_known_cli_commands_never_opt_into_learning_contamination(tmp_path: Path) -> None:
    integration = _integration(tmp_path, "ejecutar comparar")
    run = integration.model_run_command(
        suite=tmp_path, model="provider/local/model", repetitions=3, label="R3"
    )
    compare = integration.comparison_command(
        baseline_run="base", candidate_run="candidate", suite=tmp_path,
        report=tmp_path / "report.html",
    )

    assert "--acepto-contaminar" not in run
    assert run[:4] == ("python", "-m", "model_drift.cli", "ejecutar")
    assert compare[:4] == ("python", "-m", "model_drift.cli", "comparar")
