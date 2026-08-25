from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

EvidenceStatus = Literal["declared", "detected", "tested", "benchmarked"]
ProbeStatus = Literal["completed", "unavailable", "error"]


@dataclass(frozen=True, slots=True)
class CapabilityFact:
    key: str
    value: Any
    status: EvidenceStatus
    source: str
    observed_at: str
    unit: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    probe: str
    status: ProbeStatus
    observed_at: str
    detail: str | None = None


@dataclass(slots=True)
class NodeCapabilityReport:
    schema_version: str
    report_id: str
    node_id: str
    node_id_kind: str
    observed_at: str
    facts: list[CapabilityFact] = field(default_factory=list)
    probes: list[ProbeObservation] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    content_sha256: str = ""

    def payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        if not include_hash:
            payload.pop("content_sha256", None)
        return payload

    def seal(self) -> None:
        encoded = json.dumps(
            self.payload(include_hash=False),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.content_sha256 = hashlib.sha256(encoded).hexdigest()

    def to_json(self) -> str:
        if not self.content_sha256:
            self.seal()
        return json.dumps(self.payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def verify_serialized_report(encoded: str) -> tuple[bool, str, str]:
    """Verify a report without trusting or executing any field from it."""

    try:
        payload = json.loads(encoded)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error.msg}") from error
    if not isinstance(payload, dict):
        raise ValueError("report must be a JSON object")
    actual = payload.pop("content_sha256", None)
    if not isinstance(actual, str) or len(actual) != 64:
        raise ValueError("report has no valid content_sha256")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    expected = hashlib.sha256(canonical).hexdigest()
    return actual == expected, expected, actual
