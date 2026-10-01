"""Real loopback HTTPS tests of the production Worker client and Coordinator.

Certificates and credentials are generated only for the temporary test server.
No mocked HTTP opener or disabled certificate verification is used.
"""
from __future__ import annotations

import ipaddress
import hashlib
import socket
import threading
import time
import tracemalloc
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from local_ai_lab.coordinator.api import create_app
from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.worker.http_transport import CoordinatorTransportError, HttpCoordinatorTransport


def _certificates(root: Path, *, trusted: bool = True, hostname: bool = True,
                  expired: bool = False) -> tuple[Path, Path, Path]:
    root.mkdir()
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Local AI Lab test CA")])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(days=2)).not_valid_after(now + timedelta(days=2))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
          .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
              key_encipherment=False, data_encipherment=False, key_agreement=False,
              key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    certificate_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test Coordinator")])
    san = (x509.IPAddress(ipaddress.ip_address("127.0.0.1")) if hostname
           else x509.DNSName("wrong-coordinator.invalid"))
    certificate = (x509.CertificateBuilder().subject_name(certificate_name).issuer_name(name)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(days=2))
                   .not_valid_after(now - timedelta(days=1) if expired else now + timedelta(days=1))
                   .add_extension(x509.SubjectAlternativeName([san]), critical=False)
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                   .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                   .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                   .sign(ca_key, hashes.SHA256()))
    cert_path, key_path, ca_path = root / "server.pem", root / "key.pem", root / "ca.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    if not trusted:
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
              .public_key(other_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now - timedelta(days=2)).not_valid_after(now + timedelta(days=2))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(other_key.public_key()), critical=False)
              .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(other_key.public_key()), critical=False)
              .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                  key_encipherment=False, data_encipherment=False, key_agreement=False,
                  key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
              .sign(other_key, hashes.SHA256()))
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path, ca_path


@contextmanager
def _server(app, cert: Path, key: Path):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", ws="none", ssl_certfile=str(cert),
                                         ssl_keyfile=str(key), lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "test HTTPS server failed to start"
        yield f"https://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        assert not thread.is_alive(), "test HTTPS server did not stop"


def _trust(monkeypatch, ca: Path) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")


def test_real_https_pair_claim_revocation_and_recovery(tmp_path: Path, monkeypatch) -> None:
    cert, key, ca = _certificates(tmp_path / "tls")
    _trust(monkeypatch, ca)
    service = CoordinatorService(tmp_path / "coordinator.sqlite")
    with _server(create_app(service, app_token="temporary-test-session"), cert, key) as endpoint:
        token = HttpCoordinatorTransport.pair(endpoint=endpoint,
            pairing_code=service.repository.create_pairing_code(), node_id="worker", hostname="test worker")
        transport = HttpCoordinatorTransport(endpoint=endpoint, node_id="worker", device_token=token)
        assert transport.claim(idempotency_key="before-revocation") is None
        impostor = HttpCoordinatorTransport(endpoint=endpoint, node_id="other-worker", device_token=token)
        with pytest.raises(CoordinatorTransportError) as captured:
            impostor.claim(idempotency_key="other-identity")
        assert captured.value.status == 401 and not captured.value.transient
        service.revoke_node("worker")
        with pytest.raises(CoordinatorTransportError) as captured:
            transport.claim(idempotency_key="after-revocation")
        assert captured.value.status == 401 and not captured.value.transient
        replacement = HttpCoordinatorTransport.pair(endpoint=endpoint,
            pairing_code=service.repository.create_pairing_code(), node_id="replacement", hostname="new worker")
        assert replacement != token
        assert HttpCoordinatorTransport(endpoint=endpoint, node_id="replacement",
            device_token=replacement).claim(idempotency_key="recovered") is None


@pytest.mark.parametrize("failure", ["untrusted", "hostname", "expired"])
def test_real_https_rejects_invalid_server_certificate_before_pairing(
    tmp_path: Path, monkeypatch, failure: str,
) -> None:
    cert, key, ca = _certificates(tmp_path / "tls", trusted=failure != "untrusted",
                                 hostname=failure != "hostname", expired=failure == "expired")
    _trust(monkeypatch, ca)
    service = CoordinatorService(tmp_path / "coordinator.sqlite")
    code = service.repository.create_pairing_code()
    with _server(create_app(service), cert, key) as endpoint:
        with pytest.raises(CoordinatorTransportError, match="certificado TLS") as captured:
            HttpCoordinatorTransport.pair(endpoint=endpoint, pairing_code=code,
                                           node_id="worker", hostname="test worker", timeout=2)
        assert not captured.value.transient
        reason = captured.value.__cause__.reason.verify_message.lower()
        expected = {"untrusted": "issuer", "hostname": "ip address mismatch", "expired": "expired"}
        assert expected[failure] in reason
    with service.repository.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 0
        assert db.execute("SELECT used_at FROM pairing_codes").fetchone()[0] is None


def test_real_https_redirect_never_forwards_credentials(tmp_path: Path, monkeypatch) -> None:
    cert, key, ca = _certificates(tmp_path / "tls")
    _trust(monkeypatch, ca)
    received = []
    target = FastAPI()
    @target.api_route("/{path:path}", methods=["GET", "POST"])
    async def capture(request: Request):
        received.append(dict(request.headers))
        return {"lease": None}
    with _server(target, cert, key) as target_endpoint:
        redirect = FastAPI()
        @redirect.post("/node/v1/jobs/claim")
        def claim():
            return RedirectResponse(target_endpoint + "/capture", status_code=302)
        @redirect.post("/node/v1/pair")
        def pair():
            return RedirectResponse(target_endpoint + "/capture", status_code=302)
        @redirect.get("/node/v1/artifacts/sha256/{digest}")
        def artifact(digest: str):
            return RedirectResponse(target_endpoint + "/capture", status_code=302)
        with _server(redirect, cert, key) as endpoint:
            transport = HttpCoordinatorTransport(endpoint=endpoint, node_id="worker", device_token="test-credential")
            with pytest.raises(CoordinatorTransportError) as captured:
                transport.claim(idempotency_key="redirect")
            assert captured.value.status == 302 and not captured.value.transient
            with pytest.raises(CoordinatorTransportError):
                HttpCoordinatorTransport.pair(endpoint=endpoint, pairing_code="test-code",
                                               node_id="worker", hostname="test worker")
            with pytest.raises(CoordinatorTransportError) as captured:
                transport.download_artifact_to("a" * 64, tmp_path / "download.bin")
            assert captured.value.status == 302 and not captured.value.transient
    assert received == []


def test_real_https_large_download_resumes_after_connection_closes(tmp_path: Path, monkeypatch) -> None:
    cert, key, ca = _certificates(tmp_path / "tls")
    _trust(monkeypatch, ca)
    service = CoordinatorService(tmp_path / "coordinator.sqlite")
    source = tmp_path / "large-model.bin"
    block = b"0123456789abcdef" * (1024 * 1024 // 16)
    digest = hashlib.sha256()
    with source.open("wb") as output:
        for _ in range(128):
            output.write(block)
            digest.update(block)
    sha = digest.hexdigest()
    service.artifacts.ingest_file(source)
    service.repository.register_node(node_id="worker", hostname="test worker", protocol_min=1,
                                     protocol_max=1, auth_token="temporary-test-credential")
    import json
    with service.repository.transaction() as db:
        db.execute("INSERT INTO jobs(job_id,spec_json,spec_fingerprint,state,assigned_node_id,"
                   "lease_expires_at,created_at,updated_at) VALUES ('download',?,'x','running','worker',?,'now','now')",
                   (json.dumps({"payload": {"input_artifacts": [{"sha256": sha}]}}),
                    (datetime.now(UTC) + timedelta(hours=1)).isoformat()))
    app = create_app(service)
    ranges = []
    interrupted = False
    async def interrupt_once(scope, receive, send):
        nonlocal interrupted
        if scope["type"] != "http" or not scope["path"].startswith("/node/v1/artifacts/sha256/"):
            return await app(scope, receive, send)
        ranges.append(dict(scope["headers"]).get(b"range"))
        sent = 0
        first = not interrupted
        interrupted = True
        async def forward(message):
            nonlocal sent
            await send(message)
            if first and message["type"] == "http.response.body":
                sent += len(message.get("body", b""))
                if sent >= 1024 * 1024:
                    raise ConnectionResetError("deliberately interrupted HTTPS transfer")
        await app(scope, receive, forward)
    destination = tmp_path / "downloaded-model.bin"
    with _server(interrupt_once, cert, key) as endpoint:
        transport = HttpCoordinatorTransport(endpoint=endpoint, node_id="worker",
            device_token="temporary-test-credential", timeout=10)
        tracemalloc.start()
        try:
            with pytest.raises(CoordinatorTransportError) as captured:
                transport.download_artifact_to(sha, destination)
            assert captured.value.transient
            partial = destination.with_name(destination.name + ".part")
            assert 0 < partial.stat().st_size < source.stat().st_size
            offset = partial.stat().st_size
            transport.download_artifact_to(sha, destination)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    assert ranges == [None, f"bytes={offset}-".encode()]
    assert destination.stat().st_size == 128 * 1024 * 1024
    actual = hashlib.sha256()
    with destination.open("rb") as incoming:
        while chunk := incoming.read(1024 * 1024):
            actual.update(chunk)
    assert actual.hexdigest() == sha
    assert peak < 16 * 1024 * 1024
