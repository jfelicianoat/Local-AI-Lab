param(
    [string]$Broker = "http://192.168.1.52:8765",
    [string]$Plan = "",
    [string]$Report = "",
    [switch]$SkipInference
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Arguments = @(
    (Join-Path $PSScriptRoot "verify_phase8_real.py"),
    "--broker", $Broker
)
if ($Plan) { $Arguments += @("--plan", $Plan) }
if ($Report) { $Arguments += @("--report", $Report) }
if ($SkipInference) { $Arguments += "--skip-inference" }

& python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "La verificación real de Fase 8 no terminó correctamente."
}
