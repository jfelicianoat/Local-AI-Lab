from __future__ import annotations

import io
import hashlib
import json
import tracemalloc
import urllib.error
from pathlib import Path

import pytest

from local_ai_lab.worker.http_transport import (
    CoordinatorTransportError,
    HttpCoordinatorTransport,
    normalize_coordinator_endpoint,
)


class Response:
    def __init__(self, payload: object, status: int = 200, *, raw: bool = False) -> None:
        self.status = status
        self._body = payload if raw else json.dumps(payload).encode()

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_http_transport_sends_authenticated_idempotent_protocol_request() -> None:
    observed = []

    def open_request(request: object, *, timeout: float) -> Response:
        observed.append((request, timeout))
        return Response({"lease": None})

    transport = HttpCoordinatorTransport(
        endpoint="https://coordinator.lan:8711",
        node_id="worker-1",
        device_token="secret-device-token",
        opener=open_request,
    )

    assert transport.claim(idempotency_key="claim-1") is None
    request, timeout = observed[0]
    assert request.method == "POST"
    assert request.full_url.endswith("/node/v1/jobs/claim")
    assert request.get_header("Authorization") == "Bearer secret-device-token"
    assert request.get_header("Idempotency-key") == "claim-1"
    assert timeout == 10.0


def test_pairing_uses_public_route_and_returns_token_without_logging_it() -> None:
    observed = []

    def open_request(request: object, *, timeout: float) -> Response:
        observed.append(request)
        return Response({"device_token": "one-time-secret"})

    token = HttpCoordinatorTransport.pair(
        endpoint="https://coordinator.lan",
        pairing_code="123456",
        node_id="worker-1",
        hostname="compute-node",
        opener=open_request,
    )

    assert token == "one-time-secret"
    request = observed[0]
    assert request.full_url.endswith("/node/v1/pair")
    assert request.get_header("Authorization") is None
    assert b"one-time-secret" not in request.data


def test_pairing_rejects_invalid_json_as_protocol_error() -> None:
    def open_request(request: object, *, timeout: float) -> Response:
        return Response(b"not-json", raw=True)

    with pytest.raises(CoordinatorTransportError, match="invalid JSON") as captured:
        HttpCoordinatorTransport.pair(
            endpoint="https://coordinator.lan",
            pairing_code="123456",
            node_id="worker-1",
            hostname="compute-node",
            opener=open_request,
        )
    assert captured.value.transient is False


def test_heartbeat_sends_capability_report() -> None:
    observed = []

    def open_request(request: object, *, timeout: float) -> Response:
        observed.append(request)
        return Response({"accepted": True})

    transport = HttpCoordinatorTransport(
        endpoint="https://coordinator.lan", node_id="worker-1",
        device_token="token", opener=open_request,
    )
    assert transport.heartbeat({"report_hash": "sha256:value"}) == {"accepted": True}
    assert json.loads(observed[0].data)["capabilities"]["report_hash"] == "sha256:value"


def test_worker_artifact_client_encodes_chunks_for_authenticated_protocol() -> None:
    observed = []

    def open_request(request: object, *, timeout: float) -> Response:
        observed.append(request)
        return Response({"accepted": True})

    transport = HttpCoordinatorTransport(
        endpoint="https://coordinator.lan", node_id="worker-1",
        device_token="token", opener=open_request,
    )
    content = b"artifact bytes"
    transport.put_artifact_chunk(
        artifact_id="01234567-89ab-cdef-0123-456789abcdef", index=0,
        content=content, chunk_sha256=hashlib.sha256(content).hexdigest(),
        idempotency_key="chunk-0",
    )

    payload = json.loads(observed[0].data)
    assert payload["content_base64"] == "YXJ0aWZhY3QgYnl0ZXM="
    assert observed[0].get_header("Authorization") == "Bearer token"


def test_artifact_download_streams_and_resumes_after_interruption(tmp_path: Path) -> None:
    content = b"first-halfsecond-half"
    digest = hashlib.sha256(content).hexdigest()
    requests = []

    class Stream:
        def __init__(self, *, resumed: bool) -> None:
            self.status = 206 if resumed else 200
            self.headers = {"Content-Range": f"bytes 10-{len(content) - 1}/{len(content)}"} if resumed else {}
            self.parts = [content[10:], b""] if resumed else [content[:10], urllib.error.URLError("interrupted")]

        def __enter__(self) -> Stream:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _size: int) -> bytes:
            part = self.parts.pop(0)
            if isinstance(part, Exception):
                raise part
            return part

    def open_request(request: object, *, timeout: float) -> Stream:
        requests.append(request)
        return Stream(resumed=len(requests) > 1)

    transport = HttpCoordinatorTransport(
        endpoint="https://coordinator.lan", node_id="worker", device_token="token",
        opener=open_request,
    )
    destination = tmp_path / "artifact"
    with pytest.raises(CoordinatorTransportError) as error:
        transport.download_artifact_to(digest, destination)
    assert error.value.transient is True
    assert not destination.exists()
    transport.download_artifact_to(digest, destination)
    assert requests[1].get_header("Range") == "bytes=10-"
    assert destination.read_bytes() == content


def test_large_interrupted_download_stays_bounded(tmp_path: Path) -> None:
    content = b"0123456789abcdef" * (24 * 1024 * 1024 // 16)
    digest = hashlib.sha256(content).hexdigest()
    seen_ranges: list[str | None] = []

    class Stream:
        def __init__(self, offset: int, interrupt: bool) -> None:
            self.status = 206 if offset else 200
            self.headers = {"Content-Range": f"bytes {offset}-{len(content) - 1}/{len(content)}"} if offset else {}
            self.position = offset
            self.interrupt = interrupt

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, size: int) -> bytes:
            assert size <= 1024 * 1024
            if self.interrupt and self.position >= 8 * 1024 * 1024:
                raise urllib.error.URLError("simulated disconnect")
            if self.position >= len(content):
                return b""
            chunk = content[self.position:self.position + size]
            self.position += len(chunk)
            return chunk

    def open_request(request: object, *, timeout: float) -> Stream:
        value = request.get_header("Range")
        seen_ranges.append(value)
        return Stream(8 * 1024 * 1024 if value else 0, not value)

    transport = HttpCoordinatorTransport(
        endpoint="https://coordinator.lan", node_id="worker", device_token="token",
        opener=open_request,
    )
    destination = tmp_path / "large-artifact"
    tracemalloc.start()
    with pytest.raises(CoordinatorTransportError):
        transport.download_artifact_to(digest, destination)
    assert (tmp_path / "large-artifact.part").stat().st_size == 8 * 1024 * 1024
    transport.download_artifact_to(digest, destination)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 12 * 1024 * 1024
    assert seen_ranges == [None, "bytes=8388608-"]
    assert destination.stat().st_size == len(content)
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://coordinator.lan:8711",
        "file:///state.db",
        "https://user:password@coordinator.lan",
        "https://coordinator.lan/node/v1",
        "https://coordinator.lan?token=secret",
    ],
)
def test_transport_rejects_unsafe_endpoint(endpoint: str) -> None:
    with pytest.raises(ValueError):
        normalize_coordinator_endpoint(endpoint)


def test_http_error_classification_does_not_leak_response_body() -> None:
    def unavailable(request: object, *, timeout: float) -> object:
        raise urllib.error.HTTPError(
            "https://coordinator.lan/node/v1/jobs/claim",
            503,
            "down",
            {},
            io.BytesIO(b'{"private":"must-not-leak"}'),
        )

    transport = HttpCoordinatorTransport(
        endpoint="https://coordinator.lan",
        node_id="worker",
        device_token="token",
        opener=unavailable,
    )
    with pytest.raises(CoordinatorTransportError) as captured:
        transport.claim(idempotency_key="claim")
    assert captured.value.transient is True
    assert "private" not in str(captured.value)
