param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Destination = Join-Path $ProjectRoot "apps\desktop\src-tauri\resources"
$Work = Join-Path $ProjectRoot ".build\pyinstaller\work"
$Spec = Join-Path $ProjectRoot ".build\pyinstaller"
New-Item -ItemType Directory -Force $Destination | Out-Null

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name local-ai-lab-coordinator `
    --add-data "$(Join-Path $ProjectRoot 'benchmarks\controlled\v1');benchmarks\controlled\v1" `
    --paths (Join-Path $ProjectRoot "src") `
    --distpath $Destination `
    --workpath $Work `
    --specpath $Spec `
    (Join-Path $ProjectRoot "src\local_ai_lab\coordinator\api.py")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller could not build the Coordinator sidecar."
}

& (Join-Path $Destination "local-ai-lab-coordinator.exe") --help | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "The generated Coordinator sidecar did not start."
}
Write-Output (Join-Path $Destination "local-ai-lab-coordinator.exe")
