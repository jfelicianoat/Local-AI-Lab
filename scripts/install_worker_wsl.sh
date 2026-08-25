#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
environment_path="${1:-$project_root/.venv-worker}"

python3 -m venv "$environment_path"
"$environment_path/bin/python" -m pip install --upgrade pip
"$environment_path/bin/python" -m pip install "$project_root"
"$environment_path/bin/python" -m pip install -r "$project_root/requirements/training-amd-wsl.txt"
"$environment_path/bin/python" -m local_ai_lab.worker.cli --help

printf '%s\n' "Worker AMD/WSL instalado sin PyTorch ROCm en $environment_path."
printf '%s\n' "Selecciona e instala PyTorch ROCm solo después de la prueba oficial de capacidad."
