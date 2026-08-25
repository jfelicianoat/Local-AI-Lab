param(
    [Parameter(Mandatory = $true)]
    [string]$Output,

    [string]$DataRoot = (Join-Path $PSScriptRoot "..")
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$sourceRoot = Join-Path $projectRoot "src"
$resolvedDataRoot = (Resolve-Path -LiteralPath $DataRoot).Path
$env:PYTHONPATH = $sourceRoot

python -m local_ai_lab.cli probe-node --data-root $resolvedDataRoot --output $Output
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

python -m local_ai_lab.cli verify-report $Output
exit $LASTEXITCODE
