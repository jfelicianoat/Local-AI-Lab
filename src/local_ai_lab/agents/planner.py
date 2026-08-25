from __future__ import annotations

from dataclasses import dataclass

from local_ai_lab.domain.jobs import DisconnectPolicy, IdempotencyClass, JobSpec, ReassignmentPolicy


@dataclass(frozen=True, slots=True)
class BrokerAgentCapabilities:
    contract_version: str
    strategies: tuple[str, ...]
    exact_target_model: bool
    client_tool_passthrough: bool
    exclude_from_model_learning: bool
    observed: bool


@dataclass(frozen=True, slots=True)
class AgentExperimentRequest:
    experiment_id: str
    strategy_id: str
    query: str
    snapshot_hash: str
    retrieval_artifact_sha256: str
    target_model: str
    tool_contracts: tuple[str, ...]
    autonomous: bool = False
    athena_contract: str | None = None


class AgentExperimentPlanner:
    """Plans Broker/Athena delegation and deliberately contains no autonomous runtime."""

    def plan(
        self,
        request: AgentExperimentRequest,
        capabilities: BrokerAgentCapabilities,
    ) -> JobSpec:
        if request.strategy_id not in {"A1", "M1"}:
            raise ValueError("agent experiment strategy must be A1 or M1")
        if not capabilities.observed:
            raise ValueError("Broker agent capabilities must be observed, not assumed")
        required_strategy = "agent" if request.strategy_id == "A1" else "mixture_of_agents"
        missing = []
        if required_strategy not in capabilities.strategies:
            missing.append(required_strategy)
        if not capabilities.exact_target_model:
            missing.append("exact_target_model")
        if not capabilities.client_tool_passthrough:
            missing.append("client_tool_passthrough")
        if not capabilities.exclude_from_model_learning:
            missing.append("exclude_from_model_learning")
        if missing:
            raise ValueError(f"Broker lacks observed agent capabilities: {sorted(missing)}")
        if any(len(value) != 64 for value in (request.snapshot_hash, request.retrieval_artifact_sha256)):
            raise ValueError("snapshot and retrieval artifacts require SHA-256")
        if not request.target_model.strip() or not request.query.strip():
            raise ValueError("agent experiment requires query and exact target model")
        if request.autonomous and not request.athena_contract:
            raise ValueError("autonomous experiments must delegate through an observed Athena contract")
        payload = {
            "experiment_id": request.experiment_id,
            "strategy_id": request.strategy_id,
            "query": request.query,
            "snapshot_hash": request.snapshot_hash,
            "retrieval_artifact_sha256": request.retrieval_artifact_sha256,
            "broker": {
                "contract_version": capabilities.contract_version,
                "strategy": required_strategy,
                "target_model": request.target_model,
                "fallback_allowed": False,
                "exclude_from_model_learning": True,
            },
            "tools": [{"contract_reference": value} for value in request.tool_contracts],
            "runtime_owner": "Athena" if request.autonomous else "AI Broker",
            "athena_contract": request.athena_contract,
        }
        return JobSpec(
            kind="athena.delegated_agent_experiment.v1" if request.autonomous else "broker.agent_experiment.v1",
            payload=payload,
            requirements={
                "required_facts": {
                    "broker.contract_version": capabilities.contract_version,
                    f"broker.strategy.{required_strategy}": True,
                    **({"athena.contract": request.athena_contract} if request.athena_contract else {}),
                },
                "required_workloads": ["broker.agent_experiment"],
            },
            idempotency_class=IdempotencyClass.NON_REPEATABLE,
            disconnect_policy=DisconnectPolicy.STOP,
            reassignment_policy=ReassignmentPolicy.HUMAN_ONLY,
        )
