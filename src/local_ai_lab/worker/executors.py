from __future__ import annotations

from typing import Any, Callable

from local_ai_lab.exporting.executor import ModelExportExecutor
from local_ai_lab.training.executor import TransformersLoraExecutor
from local_ai_lab.training.distillation import TransformersSequenceDistillationExecutor
from local_ai_lab.training.preflight import TrainingPreflightExecutor
from local_ai_lab.retrieval.executor import ControlledRetrievalExecutor
from local_ai_lab.agents.executor import BrokerAgentExperimentExecutor
from local_ai_lab.strategies.executor import StrategySuiteExecutor


def default_executors() -> dict[str, Callable[..., dict[str, Any]]]:
    return {
        "training.preflight.v1": TrainingPreflightExecutor(),
        "training.lora.v1": TransformersLoraExecutor(),
        "training.distillation.v1": TransformersSequenceDistillationExecutor(),
        "model.export.v1": ModelExportExecutor(),
        "retrieval.benchmark.v1": ControlledRetrievalExecutor(),
        "broker.agent_experiment.v1": BrokerAgentExperimentExecutor(),
        "strategy.suite.v1": StrategySuiteExecutor(),
    }
