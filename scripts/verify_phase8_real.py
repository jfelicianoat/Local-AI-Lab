"""Verificación real y no destructiva de la integración Local AI Lab/Model Drift.

El secreto se recibe exclusivamente por variable de entorno y se propaga al
proceso hijo. No se escribe en configuraciones, argumentos, informes ni logs.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


def _parser() -> argparse.ArgumentParser:
    project = Path(__file__).resolve().parents[1]
    model_drift = project.parent / "Model_Drift"
    parser = argparse.ArgumentParser(
        description="Comprueba AI Broker 2.9, una invocación aislada de Model Drift y, opcionalmente, un plan R3/R4."
    )
    parser.add_argument("--broker", default="http://192.168.1.52:8765")
    parser.add_argument("--model-drift-directory", type=Path, default=model_drift)
    parser.add_argument(
        "--model-drift-executable",
        type=Path,
        default=model_drift / ".venv" / "Scripts" / "model-drift.exe",
    )
    parser.add_argument("--plan", type=Path, help="plan v2 producido por Local AI Lab")
    parser.add_argument("--report", type=Path, help="HTML nuevo para la comparación del plan")
    parser.add_argument(
        "--skip-inference",
        action="store_true",
        help="limita la prueba al contrato/catálogo y no crea una tarea de inferencia",
    )
    return parser


def _token() -> str:
    value = os.environ.get("LOCAL_AI_LAB_BROKER_TOKEN") or os.environ.get(
        "MODEL_DRIFT_BROKER_TOKEN"
    )
    if not value:
        raise RuntimeError(
            "Define LOCAL_AI_LAB_BROKER_TOKEN en esta consola; el verificador no acepta secretos por argumento."
        )
    return value


def _select_local_model(model_drift_root: Path, endpoint: str, token: str) -> str:
    sys.path.insert(0, str(model_drift_root))
    from model_drift.broker_client import BrokerClient, BrokerConfig

    with BrokerClient(BrokerConfig(base_url=endpoint, admin_token=token)) as client:
        client.probe_contract()
        candidates = [
            item
            for item in client.catalog()
            if item.dispatchable and item.deployment == "local"
        ]
    if not candidates:
        raise RuntimeError("AI Broker no anuncia ningún modelo local despachable; no se usará uno remoto automáticamente.")
    return min(candidates, key=lambda item: item.key).key


def _check_broker(project: Path, endpoint: str, token: str) -> None:
    sys.path.insert(0, str(project / "src"))
    from local_ai_lab.broker.compatibility import BrokerCompatibilityChecker

    report = BrokerCompatibilityChecker().check(
        endpoint=endpoint,
        phase="formal_evaluation",
        token=token,
    )
    if report.status != "satisfied":
        details = "; ".join(error.detail for error in report.errors) or ", ".join(
            report.missing_capabilities
        )
        raise RuntimeError(f"AI Broker no satisface la evaluación formal: {report.status}. {details}")
    print(f"AI Broker: contrato {report.observed_contract}, evaluación formal satisfecha.")


def _run_smoke(
    executable: Path,
    working_directory: Path,
    endpoint: str,
    token: str,
    model: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="local-ai-lab-phase8-") as raw_root:
        root = Path(raw_root)
        suite = root / "suite"
        cases = suite / "casos"
        cases.mkdir(parents=True)
        (suite / "suite.yaml").write_text(
            "id: phase8-real-smoke\nversion: '1'\ncase_pass_rule: todas\n",
            encoding="utf-8",
        )
        (cases / "smoke.yaml").write_text(
            "- id: broker-smoke-01\n"
            "  description: Verifica el transporte real sin juzgar conocimiento.\n"
            "  prompt: 'Responde exactamente con: MODEL_DRIFT_OK'\n"
            "  assertions:\n"
            "    - type: regex\n"
            "      pattern: 'MODEL_DRIFT_OK'\n",
            encoding="utf-8",
        )
        config = root / "model_drift.yaml"
        config.write_text(
            yaml.safe_dump(
                {
                    "broker_url": endpoint,
                    "database": str(root / "state.sqlite"),
                    "reports_dir": str(root / "reports"),
                    "repetitions": 1,
                    "temperature": 0.0,
                    "seed": 1234,
                    "timeout_seconds": 300,
                    "poll_interval_seconds": 1.0,
                    "accept_learning_contamination": False,
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        environment = dict(os.environ)
        environment["MODEL_DRIFT_BROKER_TOKEN"] = token
        environment["MODEL_DRIFT_BROKER_URL"] = endpoint
        completed = subprocess.run(
            [
                str(executable),
                "--config",
                str(config),
                "ejecutar",
                str(suite),
                "--modelo",
                model,
                "--repeticiones",
                "1",
                "--etiqueta",
                "phase8-real-smoke",
            ],
            cwd=working_directory,
            env=environment,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"la invocación real de Model Drift falló con código {completed.returncode}")
    print(f"Model Drift → AI Broker: inferencia aislada correcta con {model}.")


def _compare_plan(
    executable: Path,
    working_directory: Path,
    plan: Path,
    report: Path,
) -> None:
    plan = plan.resolve(strict=True)
    report = report.resolve()
    if report.exists():
        raise FileExistsError(f"el informe ya existe: {report}")
    completed = subprocess.run(
        [
            str(executable),
            "evaluar-tratamientos",
            "--plan",
            str(plan),
            "--informe",
            str(report),
        ],
        cwd=working_directory,
        check=False,
    )
    if completed.returncode not in {0, 3} or not report.is_file():
        raise RuntimeError(
            f"la comparación externa falló con código {completed.returncode} y no produjo un informe válido"
        )
    print(f"Local AI Lab → Model Drift: informe verificado en {report}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project = Path(__file__).resolve().parents[1]
    working_directory = args.model_drift_directory.resolve(strict=True)
    executable = args.model_drift_executable.resolve(strict=True)
    token = _token()

    _check_broker(project, args.broker, token)
    model = _select_local_model(working_directory, args.broker, token)
    print(f"Modelo local despachable seleccionado para smoke: {model}")
    if not args.skip_inference:
        _run_smoke(executable, working_directory, args.broker, token, model)
    if args.plan:
        report = args.report or args.plan.with_suffix(".phase8.html")
        _compare_plan(executable, working_directory, args.plan, report)
    print("Verificación de Fase 8 completada.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"Verificación incompleta: {error}", file=sys.stderr)
        raise SystemExit(1) from None
