from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from local_ai_lab.broker.client import BrokerInvocation, BrokerTaskClient
from local_ai_lab.domain.common import sha256_json
from local_ai_lab.evaluation.response_verifier import ResearchResponseVerifier, VerificationReport
from local_ai_lab.retrieval.engine import RetrievalCandidate
from local_ai_lab.retrieval.graph import ContextAssembler


class Retriever(Protocol):
    strategy_id: str

    def retrieve(self, query: str, *, limit: int = 10) -> list[RetrievalCandidate]: ...


@dataclass(frozen=True, slots=True)
class StrategyExecution:
    strategy_id: str
    query: str
    prompt_fingerprint: str
    retrieval_fingerprint: str | None
    exact_context: str
    raw_response: str
    parsed_response: dict[str, Any] | None
    verification: VerificationReport | None
    broker: BrokerInvocation
    exact_prompt: str = ""


class B0Strategy:
    strategy_id = "B0.base-minimal.v1"

    def __init__(self, broker: BrokerTaskClient) -> None:
        self.broker = broker

    def execute(self, *, query: str, target_model: dict[str, str], correlation_id: str) -> StrategyExecution:
        prompt = query.strip()
        invocation = self.broker.invoke(
            prompt=prompt, target_model=target_model, generation={"temperature": 0},
            json_schema=None, correlation_id=correlation_id,
        )
        return StrategyExecution(
            self.strategy_id, query, sha256_json({"prompt": prompt}), None, "",
            invocation.text, None, None, invocation, prompt,
        )


class B1Strategy:
    strategy_id = "B1.base-structured.v1"

    def __init__(self, broker: BrokerTaskClient, response_schema: dict[str, Any]) -> None:
        self.broker = broker
        self.response_schema = response_schema

    def execute(self, *, query: str, target_model: dict[str, str], correlation_id: str) -> StrategyExecution:
        prompt = (
            "Responde únicamente con el objeto JSON solicitado. No inventes citas. "
            "Si no hay evidencia, usa uncertainties o missing_information.\n\nConsulta: " + query.strip()
        )
        invocation = self.broker.invoke(
            prompt=prompt, target_model=target_model, generation={"temperature": 0},
            json_schema=self.response_schema, correlation_id=correlation_id,
        )
        parsed = self._parse(invocation.text)
        return StrategyExecution(
            self.strategy_id, query, sha256_json({"prompt": prompt}), None, "",
            invocation.text, parsed, None, invocation, prompt,
        )

    @staticmethod
    def _parse(text: str) -> dict[str, Any] | None:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None


class RagStrategy:
    def __init__(
        self,
        *,
        strategy_id: str,
        broker: BrokerTaskClient,
        retriever: Retriever,
        snapshot: Path,
        response_schema: dict[str, Any],
        context_budget: int = 24_000,
    ) -> None:
        if not strategy_id.startswith(("R1", "R2", "R3", "R4", "F2")):
            raise ValueError("RAG strategy id must be R1-R4 or F2")
        self.strategy_id = strategy_id
        self.broker = broker
        self.retriever = retriever
        self.verifier = ResearchResponseVerifier(snapshot)
        self.response_schema = response_schema
        self.context_budget = context_budget

    def execute(
        self, *, query: str, target_model: dict[str, str], correlation_id: str, k: int = 10
    ) -> StrategyExecution:
        candidates = self.retriever.retrieve(query, limit=k)
        context = ContextAssembler().assemble(
            candidates, max_characters=self.context_budget, snapshot_id=self.verifier.snapshot_id,
        )
        prompt = (
            "Usa exclusivamente la evidencia delimitada. Cada elemento de findings debe tener "
            "exactamente las claves claim y evidence. Cada elemento de evidence es un objeto con "
            "snapshot_id, note_id, note_path, section, chunk_id y source_reference copiados "
            "literalmente de la cabecera [EVIDENCE ...] del bloque citado. Declara contradicciones, "
            "incertidumbres e información ausente; no inventes referencias ni identificadores.\n\n"
            f"snapshot_id de todos los bloques: {self.verifier.snapshot_id}\n\nEVIDENCIA:\n"
            + context.rendered + "\nCONSULTA:\n" + query.strip()
        )
        invocation = self.broker.invoke(
            prompt=prompt, target_model=target_model, generation={"temperature": 0},
            json_schema=self.response_schema, correlation_id=correlation_id,
        )
        parsed = B1Strategy._parse(invocation.text)
        verification = self.verifier.verify(parsed) if parsed is not None else None
        retrieval_fingerprint = sha256_json(
            {"retriever": self.retriever.strategy_id, "candidates": [item.chunk_id for item in candidates], "context": context.rendered}
        )
        return StrategyExecution(
            self.strategy_id, query, sha256_json({"prompt": prompt}), retrieval_fingerprint,
            context.rendered, invocation.text, parsed, verification, invocation, prompt,
        )
