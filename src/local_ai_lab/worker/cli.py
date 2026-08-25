from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import uuid
from pathlib import Path

from local_ai_lab.capabilities.model import verify_serialized_report
from local_ai_lab.security.secrets import platform_secret_protector
from local_ai_lab.worker.executors import default_executors
from local_ai_lab.worker.http_transport import CoordinatorTransportError, HttpCoordinatorTransport
from local_ai_lab.worker.runtime import WorkerRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-ai-lab-worker")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    pair = sub.add_parser("pair")
    pair.add_argument("--pairing-code", required=True)
    run = sub.add_parser("run")
    run.add_argument("--capability-report", type=Path, required=True)
    run.add_argument("--once", action="store_true")
    run.add_argument("--poll-seconds", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protector = platform_secret_protector()
    data_root = args.data_root.resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    token_path = data_root / "device-token.protected"
    if args.command == "pair":
        if token_path.exists():
            print("worker is already paired; remove credentials only through an explicit revoke flow", file=sys.stderr)
            return 2
        try:
            token = HttpCoordinatorTransport.pair(
                endpoint=args.endpoint, pairing_code=args.pairing_code,
                node_id=args.node_id, hostname=socket.gethostname(),
            )
            token_path.write_bytes(protector.protect(token))
        except (OSError, ValueError, CoordinatorTransportError) as error:
            print(f"pairing failed: {error}", file=sys.stderr)
            return 2
        print(f"paired {args.node_id}; credential stored with platform protection")
        return 0
    if not token_path.is_file():
        print("worker is not paired", file=sys.stderr)
        return 2
    try:
        encoded_report = args.capability_report.read_text(encoding="utf-8")
        valid, _, _ = verify_serialized_report(encoded_report)
        if not valid:
            raise ValueError("capability report hash is invalid")
        capabilities = json.loads(encoded_report)
        token = protector.unprotect(token_path.read_bytes())
        transport = HttpCoordinatorTransport(
            endpoint=args.endpoint, node_id=args.node_id, device_token=token,
        )
        runtime = WorkerRuntime(
            node_id=args.node_id, journal_path=data_root / "worker-journal.sqlite3",
            transport=transport, executors=default_executors(), secret_protector=protector,
        )
    except (OSError, ValueError) as error:
        print(f"worker configuration invalid: {error}", file=sys.stderr)
        return 2
    while True:
        try:
            transport.heartbeat(capabilities)
            runtime.sync_all_pending()
            outcome = runtime.run_once(f"claim:{args.node_id}:{uuid.uuid4().hex}")
            if args.once:
                return 0
            if outcome is None:
                time.sleep(max(0.2, args.poll_seconds))
        except CoordinatorTransportError as error:
            if not error.transient:
                print(f"worker stopped: {error}", file=sys.stderr)
                return 3
            if args.once:
                return 4
            time.sleep(max(0.5, args.poll_seconds))
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
