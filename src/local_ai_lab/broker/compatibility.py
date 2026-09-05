from __future__ import annotations

import hashlib
import json
import socket
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Mapping, Protocol
from urllib.parse import urlsplit, urlunsplit

CompatibilityStatus = Literal["satisfied", "degraded", "unsatisfied", "unknown"]
FailureKind = Literal["authentication", "transient", "permanent", "contract", "unknown"]

ALLOWED_PATHS = ("/health", "/api/v1/capabilities")


@dataclass(frozen=True, slots=True)
class BrokerRequirement:
    phase: str
    minimum_contract: str | None = None
    boolean_capabilities: tuple[str, ...] = ()
    strategies: tuple[str, ...] = ()
    description: str = ""


PHASE_REQUIREMENTS: dict[str, BrokerRequirement] = {
    "phase0": BrokerRequirement(
        phase="phase0",
        description="Read health and negotiate the deployed contract; latest is not required.",
    ),
    "retrieval": BrokerRequirement(
        phase="retrieval",
        boolean_capabilities=("exact_target_model", "derived_data_boundary"),
        strategies=("single",),
        description="Target an exact model while preserving the declared data boundary.",
    ),
    "formal_evaluation": BrokerRequirement(
        phase="formal_evaluation",
        minimum_contract="2.9",
        boolean_capabilities=(
            "exact_target_model",
            "generation_determinism",
            "exclude_from_model_learning",
            "invocation_telemetry",
            "execution_fingerprint",
        ),
        strategies=("single",),
        description="Run reproducible measurements without teaching the Broker router.",
    ),
    "agent_experiments": BrokerRequirement(
        phase="agent_experiments",
        minimum_contract="2.9",
        boolean_capabilities=(
            "exact_target_model", "client_tool_passthrough",
            "exclude_from_model_learning", "invocation_telemetry",
            "execution_fingerprint",
        ),
        strategies=("agent", "mixture_of_agents"),
        description="Run A1 and M1 with exact models, client tools and traceable execution.",
    ),
    # Contrato 2.10 (Client_API.md, 12). Se añade como conjunto propio en vez de
    # endurecer `formal_evaluation`: ese quedó sellado en el artefacto de la fase
    # 0 y reescribirlo haría que un informe antiguo dijese lo que hoy pedimos, no
    # lo que se exigió entonces. Un Broker 2.9 sigue sirviendo para medir; lo que
    # no puede es DEMOSTRAR cómo midió.
    "demonstrable_execution": BrokerRequirement(
        phase="demonstrable_execution",
        minimum_contract="2.10",
        boolean_capabilities=(
            "exact_target_model",
            "generation_determinism",
            "exclude_from_model_learning",
            "invocation_telemetry",
            "execution_fingerprint",
            # 8.1: `contractual` separa el trabajo de la tarea del que el Broker
            # hace por su cuenta bajo el mismo task_id.
            "invocation_contract",
            # 8.5: acuse de recibo de que el prompt llegó sin podar.
            "prompt_compression_echo",
            # 8.3: el entregable viene marcado con `final: true` y su sha256.
            "task_artifacts",
            "canonical_artifacts",
        ),
        strategies=("single",),
        description=(
            "Prove how a measurement ran: separate the Broker's own calls from the "
            "task's, echo the prompt compression that was actually applied, and close "
            "the deliverable on a typed artifact with its sha256."
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class ReadOnlyResponse:
    status: int
    body: bytes


class ReadOnlyTransport(Protocol):
    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> ReadOnlyResponse: ...


class UrllibReadOnlyTransport:
    """Transport whose public interface cannot express a mutating HTTP method."""

    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> ReadOnlyResponse:
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return ReadOnlyResponse(status=response.status, body=response.read())
        except urllib.error.HTTPError as error:
            return ReadOnlyResponse(status=error.code, body=error.read())


@dataclass(frozen=True, slots=True)
class BrokerCheckError:
    endpoint: str
    kind: FailureKind
    detail: str
    http_status: int | None = None


@dataclass(slots=True)
class BrokerCompatibilityReport:
    schema_version: str
    report_id: str
    phase: str
    endpoint: str
    observed_at: str
    status: CompatibilityStatus
    observed_contract: str | None = None
    required_contract: str | None = None
    required_capabilities: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    required_strategies: list[str] = field(default_factory=list)
    missing_strategies: list[str] = field(default_factory=list)
    health_observed: bool = False
    capabilities_observed: bool = False
    upgrade_required: bool = False
    recommendation: str = ""
    errors: list[BrokerCheckError] = field(default_factory=list)
    content_sha256: str = ""

    def payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        if not include_hash:
            payload.pop("content_sha256", None)
        return payload

    def seal(self) -> None:
        canonical = json.dumps(
            self.payload(include_hash=False),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.content_sha256 = hashlib.sha256(canonical).hexdigest()

    def to_json(self) -> str:
        if not self.content_sha256:
            self.seal()
        return json.dumps(self.payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


class BrokerCompatibilityChecker:
    def __init__(self, transport: ReadOnlyTransport | None = None) -> None:
        self._transport = transport or UrllibReadOnlyTransport()

    def check(
        self,
        *,
        endpoint: str,
        phase: str,
        token: str | None = None,
        timeout: float = 5.0,
    ) -> BrokerCompatibilityReport:
        base_url = normalize_broker_endpoint(endpoint)
        try:
            requirement = PHASE_REQUIREMENTS[phase]
        except KeyError as error:
            raise ValueError(f"unknown Broker requirement set: {phase}") from error
        if timeout <= 0 or timeout > 60:
            raise ValueError("timeout must be greater than 0 and at most 60 seconds")

        report = BrokerCompatibilityReport(
            schema_version="local-ai-lab.broker-compatibility.v1",
            report_id=str(uuid.uuid7()),
            phase=phase,
            endpoint=base_url,
            observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            status="unknown",
            required_contract=requirement.minimum_contract,
            required_capabilities=list(requirement.boolean_capabilities),
            required_strategies=list(requirement.strategies),
        )
        headers = {"Accept": "application/json"}
        if token:
            headers["X-Admin-Token"] = token

        health = self._read_json(base_url, "/health", headers, timeout, report)
        if health is not None:
            report.health_observed = True

        capabilities = self._read_json(
            base_url, "/api/v1/capabilities", headers, timeout, report
        )
        if capabilities is not None:
            self._evaluate_capabilities(capabilities, requirement, report)

        self._finalize(requirement, report)
        report.seal()
        return report

    def _read_json(
        self,
        base_url: str,
        path: str,
        headers: Mapping[str, str],
        timeout: float,
        report: BrokerCompatibilityReport,
    ) -> dict[str, Any] | None:
        if path not in ALLOWED_PATHS:
            raise AssertionError(f"non-read-only Broker path rejected: {path}")
        try:
            response = self._transport.get(
                base_url + path, headers=headers, timeout=timeout
            )
        except (TimeoutError, socket.timeout) as error:
            report.errors.append(BrokerCheckError(path, "transient", str(error) or "timeout"))
            return None
        except (urllib.error.URLError, ConnectionError, OSError) as error:
            report.errors.append(BrokerCheckError(path, "transient", str(error)))
            return None
        except Exception as error:  # defensive boundary for injected transports
            report.errors.append(BrokerCheckError(path, "unknown", str(error)))
            return None

        if response.status != 200:
            kind: FailureKind
            if response.status in (401, 403):
                kind = "authentication"
            elif response.status == 429 or response.status >= 500:
                kind = "transient"
            else:
                kind = "permanent"
            report.errors.append(
                BrokerCheckError(path, kind, f"HTTP {response.status}", response.status)
            )
            return None
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            report.errors.append(BrokerCheckError(path, "contract", f"invalid JSON: {error}"))
            return None
        if not isinstance(payload, dict):
            report.errors.append(BrokerCheckError(path, "contract", "JSON body is not an object"))
            return None
        return payload

    @staticmethod
    def _evaluate_capabilities(
        payload: dict[str, Any],
        requirement: BrokerRequirement,
        report: BrokerCompatibilityReport,
    ) -> None:
        contract = payload.get("contract_version")
        strategies = payload.get("strategies")
        if not isinstance(contract, str) or not contract.strip():
            report.errors.append(
                BrokerCheckError("/api/v1/capabilities", "contract", "missing contract_version")
            )
            return
        if not isinstance(strategies, list) or not all(
            isinstance(item, str) for item in strategies
        ):
            report.errors.append(
                BrokerCheckError("/api/v1/capabilities", "contract", "strategies must be a string list")
            )
            return

        report.capabilities_observed = True
        report.observed_contract = contract
        report.missing_capabilities = [
            name for name in requirement.boolean_capabilities if payload.get(name) is not True
        ]
        available_strategies = set(strategies)
        report.missing_strategies = [
            name for name in requirement.strategies if name not in available_strategies
        ]
        if requirement.minimum_contract and not contract_at_least(
            contract, requirement.minimum_contract
        ):
            report.upgrade_required = True

    @staticmethod
    def _finalize(
        requirement: BrokerRequirement, report: BrokerCompatibilityReport
    ) -> None:
        if report.capabilities_observed and (
            report.upgrade_required
            or report.missing_capabilities
            or report.missing_strategies
        ):
            report.status = "unsatisfied"
            report.upgrade_required = True
            report.recommendation = (
                "Install a Broker version that advertises every required capability before "
                f"starting {requirement.phase}."
            )
        elif report.capabilities_observed and report.health_observed:
            report.status = "satisfied"
            report.recommendation = "The deployed Broker satisfies this phase requirement set."
        elif report.capabilities_observed:
            report.status = "degraded"
            report.recommendation = (
                "Capabilities satisfy the phase, but Broker health could not be confirmed."
            )
        else:
            report.status = "unknown"
            report.recommendation = (
                "Resolve connectivity, authentication, or contract errors and negotiate again; "
                "do not infer that an upgrade is required."
            )


def normalize_broker_endpoint(endpoint: str) -> str:
    value = endpoint.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Broker endpoint must use http or https")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Broker endpoint must have a host and no embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("Broker endpoint cannot contain a query or fragment")
    if parsed.path not in ("", "/"):
        raise ValueError("Broker endpoint must be an origin without an API path")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def contract_at_least(observed: str, required: str) -> bool:
    def parse(value: str) -> tuple[int, ...]:
        parts = value.split(".")
        if not parts or any(not part.isdigit() for part in parts):
            raise ValueError(f"invalid numeric contract version: {value}")
        return tuple(int(part) for part in parts)

    try:
        observed_parts = parse(observed)
        required_parts = parse(required)
    except ValueError:
        return False
    width = max(len(observed_parts), len(required_parts))
    return observed_parts + (0,) * (width - len(observed_parts)) >= required_parts + (
        0,
    ) * (width - len(required_parts))
