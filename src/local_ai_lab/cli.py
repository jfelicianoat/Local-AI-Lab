from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from local_ai_lab.broker.compatibility import BrokerCompatibilityChecker, PHASE_REQUIREMENTS
from local_ai_lab.capabilities.model import verify_serialized_report
from local_ai_lab.capabilities.probe import NodeProbe
from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.domain.common import utc_timestamp
from local_ai_lab.knowledge_index.projection import KnowledgeIndexBuilder
from local_ai_lab.knowledge_index.snapshot import SnapshotBuilder, SnapshotError, SnapshotVerifier
from local_ai_lab.knowledge_index.vault import ReadOnlyVaultAdapter, VaultSecurityError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-ai-lab")
    subparsers = parser.add_subparsers(dest="command", required=True)
    probe = subparsers.add_parser("probe-node", help="collect read-only node capability evidence")
    probe.add_argument("--data-root", type=Path, required=True)
    probe.add_argument("--output", type=Path)
    verify = subparsers.add_parser("verify-report", help="verify a capability report SHA-256")
    verify.add_argument("report", type=Path)
    broker = subparsers.add_parser(
        "check-broker", help="read only Broker health and capability negotiation"
    )
    broker.add_argument("--endpoint", required=True)
    broker.add_argument("--phase", choices=sorted(PHASE_REQUIREMENTS), required=True)
    broker.add_argument("--token-env", help="name of the environment variable holding the admin token")
    broker.add_argument("--timeout", type=float, default=5.0)
    broker.add_argument("--output", type=Path)
    evidence = subparsers.add_parser(
        "record-evidence", help="record a hashed phase-gate evidence artifact"
    )
    evidence.add_argument("--database", type=Path, required=True)
    evidence.add_argument("--id", required=True)
    evidence.add_argument("--label", required=True)
    evidence.add_argument("--status", choices=("tested", "detected", "blocked"), required=True)
    evidence.add_argument("--artifact", type=Path, required=True)
    pairing = subparsers.add_parser(
        "pair-code", help="mint a single-use pairing code so a Worker can enrol"
    )
    pairing.add_argument("--database", type=Path, required=True)
    pairing.add_argument("--valid-seconds", type=int, default=300)
    snapshot = subparsers.add_parser(
        "snapshot-vault", help="create an immutable local snapshot through the read-only vault port"
    )
    snapshot.add_argument("--allowed-root", type=Path, required=True)
    snapshot.add_argument("--vault", type=Path, required=True)
    snapshot.add_argument("--output-root", type=Path, required=True)
    snapshot.add_argument("--vault-id")
    snapshot.add_argument("--coordinator-database", type=Path)
    index = subparsers.add_parser(
        "build-index", help="build a new local SQLite projection from a verified snapshot"
    )
    index.add_argument("--snapshot", type=Path, required=True)
    index.add_argument("--database", type=Path, required=True)
    index.add_argument("--coordinator-database", type=Path)
    index.add_argument("--previous-database", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify-report":
        try:
            valid, expected, actual = verify_serialized_report(
                args.report.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            print(f"invalid report: {error}", file=sys.stderr)
            return 2
        if not valid:
            print(f"invalid report: expected {expected}, found {actual}", file=sys.stderr)
            return 2
        print(f"valid {actual}")
        return 0
    if args.command == "check-broker":
        token = os.environ.get(args.token_env) if args.token_env else None
        if args.token_env and token is None:
            print(f"missing token environment variable: {args.token_env}", file=sys.stderr)
            return 2
        try:
            report = BrokerCompatibilityChecker().check(
                endpoint=args.endpoint,
                phase=args.phase,
                token=token,
                timeout=args.timeout,
            )
        except ValueError as error:
            print(f"invalid Broker check: {error}", file=sys.stderr)
            return 2
        encoded = report.to_json()
        if args.output is None:
            sys.stdout.write(encoded)
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_suffix(args.output.suffix + ".tmp")
            temporary.write_text(encoded, encoding="utf-8", newline="\n")
            temporary.replace(args.output)
            print(args.output.resolve())
        return 0 if report.status in ("satisfied", "degraded") else 3
    if args.command == "record-evidence":
        try:
            artifact = args.artifact.resolve(strict=True)
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            result = CoordinatorService(args.database).record_phase_evidence(
                evidence_id=args.id,
                label=args.label,
                status=args.status,
                artifact_sha256=digest,
                source_reference=str(artifact),
                observed_at=utc_timestamp(),
            )
        except (OSError, ValueError) as error:
            print(f"could not record evidence: {error}", file=sys.stderr)
            return 2
        print(f"recorded {result['evidence_id']} sha256:{digest}")
        return 0
    if args.command == "pair-code":
        # Sin esto el emparejamiento documentado en WORKER_DEPLOYMENT.md no se puede
        # ejecutar: el servicio sabe acuñar el código pero nada lo exponía.
        try:
            code = CoordinatorService(args.database).create_pairing_code(args.valid_seconds)
        except (OSError, ValueError) as error:
            print(f"could not create a pairing code: {error}", file=sys.stderr)
            return 2
        print(code)
        return 0
    if args.command == "snapshot-vault":
        try:
            adapter = ReadOnlyVaultAdapter(allowed_root=args.allowed_root, vault_root=args.vault)
            result = SnapshotBuilder().build(
                adapter, args.output_root, vault_id=args.vault_id
            )
        except (OSError, ValueError, VaultSecurityError, SnapshotError) as error:
            print(f"could not create snapshot: {error}", file=sys.stderr)
            return 2
        if args.coordinator_database:
            manifest = SnapshotVerifier().verify(result.path)["manifest"]
            coordinator = CoordinatorService(args.coordinator_database)
            coordinator.record_product_item(
                record_id=result.snapshot_id,
                category="snapshot",
                title=f"Snapshot {args.vault.name}",
                status=result.state,
                artifact_sha256=result.global_hash,
                summary={
                    "vault": args.vault.name,
                    "notes": manifest["counts"]["notes"],
                    "chunks": manifest["counts"]["chunks"],
                    "holes": manifest["counts"]["holes"],
                    "read_only": True,
                },
            )
            coordinator.repository.record_artifact_location(
                record_id=result.snapshot_id,
                artifact_kind="vault_snapshot",
                local_path=result.path,
                artifact_sha256=result.global_hash,
            )
        print(f"{result.state} sha256:{result.global_hash} {result.path}")
        return 0 if result.state == "COMPLETE" else 3
    if args.command == "build-index":
        try:
            result = KnowledgeIndexBuilder().build(
                args.snapshot, args.database, previous_database=args.previous_database
            )
            if args.coordinator_database:
                verified = SnapshotVerifier().verify(args.snapshot)
                database_hash = hashlib.sha256(result.read_bytes()).hexdigest()
                CoordinatorService(args.coordinator_database).record_product_item(
                    record_id=f"index-{verified['manifest']['snapshot_id']}",
                    category="index",
                    title="Índice de conocimiento",
                    status="READY",
                    artifact_sha256=database_hash,
                    summary={
                        "snapshot_id": verified["manifest"]["snapshot_id"],
                        "snapshot_hash": verified["manifest"]["global_hash"],
                        "engine": "SQLite FTS5",
                        "regenerable": True,
                    },
                )
        except (OSError, ValueError, SnapshotError) as error:
            print(f"could not build index: {error}", file=sys.stderr)
            return 2
        print(result)
        return 0
    if args.command != "probe-node":
        raise AssertionError(f"unhandled command: {args.command}")
    report = NodeProbe().collect(data_root=args.data_root)
    encoded = report.to_json()
    if args.output is None:
        sys.stdout.write(encoded)
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8", newline="\n")
    temporary.replace(args.output)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
