param(
    [string]$Python = "",
    [string]$Executable = ""
)

# Runs the seven genuine TCP/TLS tests and native startup check with synthetic
# local data. It does not change firewall/security settings or contact AI services.
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $ProjectRoot ".venv-verify\Scripts\python.exe" }
if (-not $Executable) { $Executable = Join-Path $ProjectRoot "dist\audit-20261119\local-ai-lab-desktop.exe" }
$Python = (Resolve-Path -LiteralPath $Python).Path
$Executable = (Resolve-Path -LiteralPath $Executable).Path
$OutputRoot = Join-Path $ProjectRoot (".test-tmp\pending-checks\" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path (Join-Path $OutputRoot "system-temp") -Force | Out-Null
$PreviousTemp, $PreviousTmp, $PreviousBytecode = $env:TEMP, $env:TMP, $env:PYTHONDONTWRITEBYTECODE
$NetworkExit = $null
$SmokeError = $null
Push-Location $ProjectRoot
try {
    $env:TEMP = Join-Path $OutputRoot "system-temp"
    $env:TMP = $env:TEMP
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $NetworkProbe = @'
import socket
with socket.socket() as server:
    server.bind(('127.0.0.1',0)); server.listen()
    with socket.socket() as client:
        client.settimeout(2)
        client.connect(server.getsockname())
print('Local TCP available')
'@
    $NetworkProbe | & $Python - *> (Join-Path $OutputRoot "network-precheck.log")
    if ($LASTEXITCODE -ne 0) {
        [ordered]@{ status = "BLOCKED_LOCAL_TCP"; evidence = $OutputRoot;
            network_tests_executed = $false; native_startup_executed = $false } |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputRoot "results.json") -Encoding utf8
        throw "Local TCP is unavailable; no network tests or native smoke were started. Evidence: $OutputRoot"
    }
    & $Python -m pytest tests/test_worker_tls.py `
        tests/test_ai_os_core.py::test_sin_pegar_tokens_core_da_el_del_broker_y_se_renueva `
        -v --tb=short -p no:cacheprovider `
        --basetemp (Join-Path $OutputRoot "pytest") `
        --junitxml (Join-Path $OutputRoot "network.xml") *> (Join-Path $OutputRoot "network.log")
    $NetworkExit = $LASTEXITCODE
    try {
        & (Join-Path $PSScriptRoot "smoke_desktop.ps1") -Executable $Executable *> (Join-Path $OutputRoot "smoke.log")
    } catch { $SmokeError = $_.Exception.Message }
    [ordered]@{ network_exit_code = $NetworkExit; native_startup_error = $SmokeError;
        visual_walkthrough_verified = $false; evidence = $OutputRoot } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputRoot "results.json") -Encoding utf8
}
finally {
    $env:TEMP, $env:TMP, $env:PYTHONDONTWRITEBYTECODE = $PreviousTemp, $PreviousTmp, $PreviousBytecode
    Pop-Location
}
Write-Output "Pending-check evidence: $OutputRoot"
Write-Output "Network checks exit code: $NetworkExit (0 = passed)"
if ($null -ne $SmokeError) { Write-Warning "Native startup/cleanup: $SmokeError" }
if ($NetworkExit -ne 0 -or $null -ne $SmokeError) {
    throw "Pending checks did not pass; inspect network.log, smoke.log and results.json."
}
Write-Output "Real-network and native-startup checks passed. Visual walkthrough remains separate."
