from __future__ import annotations

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
