from __future__ import annotations

import base64
import hashlib
import http.client
import json
import re
import ssl
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit


class CoordinatorTransportError(RuntimeError):
    def __init__(self, message: str, *, transient: bool, status: int | None = None) -> None:
        super().__init__(message)
        self.transient = transient
        self.status = status


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # The configured origin is the authorization boundary. Never forward a
        # bearer credential (or pairing code) to an HTTP redirect target.
        raise urllib.error.HTTPError(req.full_url, code, "Coordinator redirects are forbidden", headers, fp)


def _open_protocol_request(request, *, timeout):
    return urllib.request.build_opener(_RejectRedirects()).open(request, timeout=timeout)


def _network_error(error: Exception) -> CoordinatorTransportError:
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return CoordinatorTransportError(
            "No se pudo verificar el certificado TLS del Coordinator. "
            "Comprueba su nombre, vigencia y CA de confianza.", transient=False,
        )
    return CoordinatorTransportError(str(error), transient=True)


class HttpCoordinatorTransport:
    """Versioned worker client; all mutations carry an idempotency key."""

    def __init__(
        self,
        *,
        endpoint: str,
        node_id: str,
        device_token: str,
        timeout: float = 10.0,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.endpoint = normalize_coordinator_endpoint(endpoint)
        self.node_id = node_id
        self._token = device_token
        self.timeout = timeout
        self._open = opener or _open_protocol_request

    def claim(self, *, idempotency_key: str) -> dict[str, Any] | None:
        return self._post("/node/v1/jobs/claim", {}, idempotency_key)["lease"]

    def heartbeat(self, capabilities: dict[str, Any]) -> dict[str, Any]:
        return self._post(
            "/node/v1/heartbeats", {"capabilities": capabilities},
            f"heartbeat:{self.node_id}:{uuid.uuid4().hex}",
        )

    def renew(self, lease: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        return self._post(
            f"/node/v1/jobs/{_safe_id(lease['job_id'])}/lease/renew",
            {**_lease_body(lease), "lease_seconds": 60}, idempotency_key,
        )

    def control(self, lease: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        return self._post(
            f"/node/v1/jobs/{_safe_id(lease['job_id'])}/control",
            _lease_body(lease), idempotency_key,
        )

    def initiate_artifact(
        self, *, expected_sha256: str, expected_size: int, chunk_size: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._post(
            "/node/v1/artifacts/initiate",
            {
                "expected_sha256": expected_sha256, "expected_size": expected_size,
                "chunk_size": chunk_size,
            },
            idempotency_key,
        )

    def put_artifact_chunk(
        self, *, artifact_id: str, index: int, content: bytes, chunk_sha256: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._post(
            f"/node/v1/artifacts/{_safe_id(artifact_id)}/chunks/{index}",
            {
                "chunk_sha256": chunk_sha256,
                "content_base64": base64.b64encode(content).decode("ascii"),
            },
            idempotency_key,
        )

    def commit_artifact(self, *, artifact_id: str, idempotency_key: str) -> dict[str, Any]:
        return self._post(
            f"/node/v1/artifacts/{_safe_id(artifact_id)}/commit", {}, idempotency_key
        )

    def download_artifact(self, sha256: str) -> bytes:
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
            raise ValueError("artifact SHA-256 is invalid")
        request = urllib.request.Request(
            self.endpoint + f"/node/v1/artifacts/sha256/{sha256}",
            method="GET",
            headers={
                "Accept": "application/octet-stream",
                "Authorization": f"Bearer {self._token}",
                "X-Node-ID": self.node_id,
            },
        )
        try:
            response = self._open(request, timeout=self.timeout)
            with response:
                status, content = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, content = error.code, b""
            error.close()
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as error:
            raise _network_error(error) from error
        if status < 200 or status >= 300:
            raise CoordinatorTransportError(
                f"Coordinator artifact download returned HTTP {status}",
                transient=status == 429 or status >= 500, status=status,
            )
        if hashlib.sha256(content).hexdigest() != sha256:
            raise CoordinatorTransportError(
                "downloaded artifact SHA-256 mismatch", transient=False, status=status
            )
        return content

    def download_artifact_to(self, sha256: str, destination: Path) -> None:
        """Stream a CAS blob to disk and resume an interrupted transfer when possible."""
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
            raise ValueError("artifact SHA-256 is invalid")
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {
            "Accept": "application/octet-stream",
            "Authorization": f"Bearer {self._token}",
            "X-Node-ID": self.node_id,
        }
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(
            self.endpoint + f"/node/v1/artifacts/sha256/{sha256}",
            method="GET", headers=headers,
        )
        try:
            with self._open(request, timeout=self.timeout) as response:
                status = response.status
                if status not in {200, 206}:
                    raise CoordinatorTransportError(
                        f"Coordinator artifact download returned HTTP {status}",
                        transient=status == 429 or status >= 500, status=status,
                    )
                resumed = status == 206 and offset > 0
                if status == 206:
                    content_range = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)",
                        str(response.headers.get("Content-Range", "")))
                    if (not resumed or content_range is None
                        or int(content_range[1]) != offset
                        or int(content_range[2]) < offset
                        or int(content_range[3]) <= int(content_range[2])):
                        raise CoordinatorTransportError("artifact resume range does not match the partial file", transient=False)
                declared = response.headers.get("Content-Length")
                if declared is not None and not str(declared).isdigit():
                    raise CoordinatorTransportError("artifact response has an invalid length", transient=False)
                expected_length = int(declared) if declared is not None else None
                if status == 206:
                    range_length = int(content_range[2]) - offset + 1
                    if expected_length is not None and expected_length != range_length:
                        raise CoordinatorTransportError("artifact response length differs from its range", transient=False)
                    expected_length = range_length
                received = 0
                with partial.open("ab" if resumed else "wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                        received += len(chunk)
                if expected_length is not None and received < expected_length:
                    raise CoordinatorTransportError("artifact transfer was interrupted; partial file retained", transient=True)
                if expected_length is not None and received > expected_length:
                    partial.unlink(missing_ok=True)
                    raise CoordinatorTransportError("artifact response exceeds its declared length", transient=False)
                if status == 206 and int(content_range[2]) + 1 < int(content_range[3]):
                    raise CoordinatorTransportError("artifact transfer is incomplete; partial file retained", transient=True)
        except urllib.error.HTTPError as error:
            error.close()
            raise CoordinatorTransportError(
                f"Coordinator artifact download returned HTTP {error.code}",
                transient=error.code == 429 or error.code >= 500, status=error.code,
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as error:
            raise _network_error(error) from error
        digest = hashlib.sha256()
        with partial.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != sha256:
            partial.unlink(missing_ok=True)
            raise CoordinatorTransportError("downloaded artifact SHA-256 mismatch", transient=False)
        partial.replace(destination)

    @classmethod
    def pair(
        cls,
        *,
        endpoint: str,
        pairing_code: str,
        node_id: str,
        hostname: str,
        timeout: float = 10.0,
        opener: Callable[..., Any] | None = None,
    ) -> str:
        base = normalize_coordinator_endpoint(endpoint)
        body = json.dumps(
            {
                "pairing_code": pairing_code, "node_id": node_id, "hostname": hostname,
                "protocol_min": 1, "protocol_max": 1,
            },
            ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            base + "/node/v1/pair", data=body, method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            response = (opener or _open_protocol_request)(request, timeout=timeout)
            with response:
                status, encoded = response.status, response.read()
        except urllib.error.HTTPError as error:
            with error:
                status, encoded = error.code, error.read()
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as error:
            raise _network_error(error) from error
        if status < 200 or status >= 300:
            raise CoordinatorTransportError(
                f"Coordinator pairing returned HTTP {status}", transient=status == 429 or status >= 500,
                status=status,
            )
        try:
            payload = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CoordinatorTransportError(
                "Coordinator pairing returned invalid JSON", transient=False, status=status
            ) from error
        token = payload.get("device_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise CoordinatorTransportError("pairing returned no device token", transient=False)
        return token

    def ack(self, lease: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        return self._post(
            f"/node/v1/jobs/{_safe_id(lease['job_id'])}/ack",
            _lease_body(lease),
            idempotency_key,
        )

    def progress(
        self,
        lease: dict[str, Any],
        message: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._post(
            f"/node/v1/jobs/{_safe_id(lease['job_id'])}/progress",
            {**_lease_body(lease), "sequence": message["sequence"], "payload": message["payload"]},
            idempotency_key,
        )

    def publish_checkpoint(
        self, lease: dict[str, Any], *, step: int, artifact_id: str,
        artifact_sha256: str, idempotency_key: str,
    ) -> dict[str, Any]:
        return self._post(
            f"/node/v1/jobs/{_safe_id(lease['job_id'])}/checkpoints",
            {**_lease_body(lease), "attempt_id": lease["attempt_id"],
             "step": step, "artifact_id": artifact_id,
             "artifact_sha256": artifact_sha256}, idempotency_key,
        )

    def complete(
        self,
        lease: dict[str, Any],
        message: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._post(
            f"/node/v1/jobs/{_safe_id(lease['job_id'])}/complete",
            {
                **_lease_body(lease),
                "attempt_id": message["attempt_id"],
                "outcome": message["outcome"],
                "payload": message["payload"],
            },
            idempotency_key,
        )

    def _post(self, path: str, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if not path.startswith("/node/v1/") or ".." in path:
            raise ValueError("worker transport path is outside protocol v1")
        if not idempotency_key or len(idempotency_key) > 200:
            raise ValueError("a bounded idempotency key is required")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint + path,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._token}",
                "X-Node-ID": self.node_id,
                "Idempotency-Key": idempotency_key,
            },
        )
        try:
            response = self._open(request, timeout=self.timeout)
            with response:
                status = response.status
                encoded = response.read()
        except urllib.error.HTTPError as error:
            with error:
                status = error.code
                encoded = error.read()
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as error:
            raise _network_error(error) from error
        if status < 200 or status >= 300:
            transient = status == 429 or status >= 500
            raise CoordinatorTransportError(
                f"Coordinator returned HTTP {status}", transient=transient, status=status
            )
        try:
            result = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CoordinatorTransportError(
                "Coordinator returned invalid JSON", transient=False, status=status
            ) from error
        if not isinstance(result, dict):
            raise CoordinatorTransportError(
                "Coordinator response is not an object", transient=False, status=status
            )
        return result


def normalize_coordinator_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Coordinator endpoint must be an http(s) origin")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError("Coordinator endpoint cannot embed credentials, query, or fragment")
    if parsed.path not in ("", "/"):
        raise ValueError("Coordinator endpoint cannot contain an API path")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("remote Coordinator connections require HTTPS")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _safe_id(value: Any) -> str:
    encoded = str(value)
    if not encoded or any(character not in "0123456789abcdefghijklmnopqrstuvwxyz-" for character in encoded.lower()):
        raise ValueError("invalid protocol identifier")
    return encoded


def _lease_body(lease: dict[str, Any]) -> dict[str, Any]:
    return {
        "lease_token": lease["lease_token"],
        "lease_generation": lease["lease_generation"],
    }
