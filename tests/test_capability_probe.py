from __future__ import annotations

import json
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from local_ai_lab.capabilities.model import verify_serialized_report
from local_ai_lab.capabilities.probe import (
    CommandNotAllowedError,
    CommandResult,
    NodeProbe,
    ReadOnlyCommandRunner,
)

NOW = datetime(2026, 8, 23, 18, 0, tzinfo=UTC)


class FakeRunner:
    def __init__(self, results: dict[tuple[str, ...], CommandResult]) -> None:
        self.results = results
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command: tuple[str, ...], timeout_seconds: float) -> CommandResult:
        del timeout_seconds
        command = tuple(command)
        self.commands.append(command)
        return self.results.get(command, CommandResult(127, "", "command not found"))


def _runner() -> FakeRunner:
    return FakeRunner(
        {
            NodeProbe.NVIDIA_QUERY: CommandResult(
                0,
                "0, NVIDIA GeForce RTX 4060 Ti, GPU-abc, 16380, 610.88, 48, P8\n",
                "",
            ),
            ("python", "--version"): CommandResult(0, "Python 3.14.0\n", ""),
            ("node", "--version"): CommandResult(0, "v24.11.1\n", ""),
            ("pnpm", "--version"): CommandResult(0, "11.20.0\n", ""),
            ("rustc", "--version"): CommandResult(0, "rustc 1.97.1\n", ""),
            ("cargo", "--version"): CommandResult(0, "cargo 1.97.1\n", ""),
            ("wsl", "--status"): CommandResult(1, "", "access denied"),
        }
    )


def test_probe_records_detection_without_claiming_workload_tests(tmp_path: Path) -> None:
    report = NodeProbe(runner=_runner(), clock=lambda: NOW).collect(data_root=tmp_path)

    facts = {fact.key: fact for fact in report.facts}
    assert facts["gpu.0.name"].value == "NVIDIA GeForce RTX 4060 Ti"
    assert facts["gpu.0.memory_total_mib"].value == 16380
    assert all(fact.status == "detected" for fact in report.facts)
    assert any("No ML workload" in limitation for limitation in report.limitations)
    assert not any(fact.status in {"tested", "benchmarked"} for fact in report.facts)


def test_failed_wsl_probe_is_an_error_not_a_negative_capability(tmp_path: Path) -> None:
    report = NodeProbe(runner=_runner(), clock=lambda: NOW).collect(data_root=tmp_path)

    wsl = next(observation for observation in report.probes if observation.probe == "wsl")
    assert wsl.status == "error"
    assert "access denied" in (wsl.detail or "")
    assert not any(fact.key.startswith("runtime.wsl") for fact in report.facts)


def test_report_hash_covers_the_canonical_payload(tmp_path: Path) -> None:
    report = NodeProbe(runner=_runner(), clock=lambda: NOW).collect(data_root=tmp_path)
    encoded = json.loads(report.to_json())
    original_hash = encoded["content_sha256"]
    encoded.pop("content_sha256")
    canonical = json.dumps(
        encoded, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    assert len(original_hash) == 64
    assert original_hash == hashlib.sha256(canonical).hexdigest()
    assert verify_serialized_report(report.to_json()) == (True, original_hash, original_hash)


def test_report_verification_rejects_tampering(tmp_path: Path) -> None:
    report = NodeProbe(runner=_runner(), clock=lambda: NOW).collect(data_root=tmp_path)
    encoded = json.loads(report.to_json())
    encoded["limitations"].append("tampered")

    valid, expected, actual = verify_serialized_report(json.dumps(encoded))

    assert not valid
    assert expected != actual


@pytest.mark.parametrize("encoded", ["[]", "{}", "not-json"])
def test_report_verification_rejects_malformed_documents(encoded: str) -> None:
    with pytest.raises(ValueError):
        verify_serialized_report(encoded)


def test_command_runner_rejects_everything_outside_read_only_allowlist() -> None:
    runner = ReadOnlyCommandRunner()

    with pytest.raises(CommandNotAllowedError):
        runner(("powershell", "Remove-Item", "anything"), 1.0)

    with pytest.raises(CommandNotAllowedError):
        runner((r"C:\untrusted\nvidia-smi.exe",), 1.0)


def test_windows_utf16_diagnostics_are_decoded_without_nul_characters() -> None:
    message = "Acceso denegado. Código de error: E_ACCESSDENIED"
    decoded = ReadOnlyCommandRunner._decode_output(message.encode("utf-16-le"))

    assert decoded == message
    assert "\x00" not in decoded


def test_probe_command_set_is_read_only(tmp_path: Path) -> None:
    runner = _runner()
    NodeProbe(runner=runner, clock=lambda: NOW).collect(data_root=tmp_path)

    assert {command[0] for command in runner.commands} <= ReadOnlyCommandRunner.ALLOWED_EXECUTABLES
    assert all("AI_Broker" not in part for command in runner.commands for part in command)
