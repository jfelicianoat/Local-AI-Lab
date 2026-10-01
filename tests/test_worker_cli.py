from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_lab.capabilities.model import NodeCapabilityReport
from local_ai_lab.worker import cli
from local_ai_lab.worker.cli import build_parser
from local_ai_lab.worker.executors import default_executors


def test_worker_cli_requires_explicit_role_identity_and_storage() -> None:
    args = build_parser().parse_args(
        [
            "--endpoint", "https://coordinator.lan", "--node-id", "worker-1",
            "--data-root", "worker-state", "run", "--capability-report", "caps.json",
            "--once",
        ]
    )

    assert args.node_id == "worker-1"
    assert args.command == "run"
    assert args.once is True


def test_default_worker_executors_are_explicit_and_bounded() -> None:
    assert set(default_executors()) == {
        "training.preflight.v1", "training.lora.v1", "model.export.v1",
        "training.distillation.v1",
        "retrieval.benchmark.v1",
        "broker.agent_experiment.v1",
        "strategy.suite.v1",
    }


def test_worker_refreshes_observations_instead_of_reusing_startup_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup = NodeCapabilityReport("1.0", "file-report", "worker", "paired", "2026-10-01T00:00:00Z")
    path = tmp_path / "caps.json"
    path.write_text(startup.to_json(), encoding="utf-8")
    (tmp_path / "device-token.protected").write_bytes(b"synthetic-protected-token")
    monkeypatch.setattr(cli, "platform_secret_protector", lambda: SimpleNamespace(unprotect=lambda _value: "synthetic-token"))
    sent: list[dict] = []
    monkeypatch.setattr(cli, "HttpCoordinatorTransport", lambda **_kwargs: SimpleNamespace(heartbeat=lambda report: sent.append(report)))
    clock = iter([0.0, 0.0, 1.0, 31.0, 31.0])
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)
    probes = []
    def collect(*, data_root):
        assert data_root == tmp_path
        probes.append(len(probes) + 1)
        return SimpleNamespace(payload=lambda: {"facts": [{"key": "gpu.0.driver_version", "value": f"fresh-{probes[-1]}"}]})
    monkeypatch.setattr(cli, "NodeProbe", lambda: SimpleNamespace(collect=collect))
    def run_once(_claim):
        if len(sent) == 3:
            raise KeyboardInterrupt
        return None
    monkeypatch.setattr(cli, "WorkerRuntime", lambda **_kwargs: SimpleNamespace(
        sync_all_pending=lambda: None, recover_incomplete=lambda: None, run_once=run_once,
    ))
    assert cli.main([
        "--endpoint", "https://synthetic.invalid", "--node-id", "worker", "--data-root", str(tmp_path),
        "run", "--capability-report", str(path),
    ]) == 0
    assert [item["facts"][0]["value"] for item in sent] == ["fresh-1", "fresh-1", "fresh-2"]
