param(
    [ValidateSet("Core", "Nvidia")]
    [string]$Profile = "Core",
    [string]$Python = "python",
    [string]$Environment = ".venv-worker"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvironmentPath = Join-Path $ProjectRoot $Environment

& $Python -m venv $EnvironmentPath
if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el entorno del Worker." }

$WorkerPython = Join-Path $EnvironmentPath "Scripts\python.exe"
& $WorkerPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "No se pudo preparar pip." }
& $WorkerPython -m pip install $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar Local AI Lab Worker." }

if ($Profile -eq "Nvidia") {
    & $WorkerPython -m pip install -r (Join-Path $ProjectRoot "requirements\training-nvidia.txt")
    if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias NVIDIA." }
}
& $WorkerPython -m local_ai_lab.worker.cli --help
if ($LASTEXITCODE -ne 0) { throw "La instalación del Worker no superó el smoke test." }

Write-Output "Worker instalado en $EnvironmentPath con perfil $Profile."
