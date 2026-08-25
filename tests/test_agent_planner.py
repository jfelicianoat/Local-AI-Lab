from __future__ import annotations

import pytest

from local_ai_lab.agents.planner import AgentExperimentPlanner, AgentExperimentRequest, BrokerAgentCapabilities


def _capabilities(*, strategies=("agent", "mixture_of_agents"), observed=True):
    return BrokerAgentCapabilities(
        contract_version="2.9", strategies=strategies, exact_target_model=True,
        client_tool_passthrough=True, exclude_from_model_learning=True, observed=observed,
    )


def _request(*, strategy="A1", autonomous=False, athena=None):
    return AgentExperimentRequest(
        experiment_id="exp-agent", strategy_id=strategy, query="Investiga Atlas",
        snapshot_hash="a" * 64, retrieval_artifact_sha256="b" * 64,
        target_model="local/model", tool_contracts=("tool://retrieval/v1",),
        autonomous=autonomous, athena_contract=athena,
    )


def test_a1_delegates_to_broker_with_exact_model_and_no_learning() -> None:
    job = AgentExperimentPlanner().plan(_request(), _capabilities())

    assert job.kind == "broker.agent_experiment.v1"
    assert job.payload["runtime_owner"] == "AI Broker"
    assert job.payload["broker"]["fallback_allowed"] is False
    assert job.payload["broker"]["exclude_from_model_learning"] is True
    assert job.idempotency_class.value == "non_repeatable"


def test_autonomous_experiment_requires_and_delegates_to_athena() -> None:
    with pytest.raises(ValueError, match="must delegate"):
        AgentExperimentPlanner().plan(_request(autonomous=True), _capabilities())
    job = AgentExperimentPlanner().plan(
        _request(autonomous=True, athena="athena.contract.v1"), _capabilities()
    )
    assert job.kind == "athena.delegated_agent_experiment.v1"
    assert job.payload["runtime_owner"] == "Athena"


def test_m1_requires_observed_mixture_capability() -> None:
    with pytest.raises(ValueError, match="mixture_of_agents"):
        AgentExperimentPlanner().plan(
            _request(strategy="M1"), _capabilities(strategies=("agent",))
        )
    with pytest.raises(ValueError, match="observed"):
        AgentExperimentPlanner().plan(_request(), _capabilities(observed=False))
