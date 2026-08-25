param(
    [ValidateSet("Portable", "Msi", "Nsis", "All")]
    [string]$Target = "Portable",
    [string]$Python = "python",
    [string]$Node = "node"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DesktopRoot = Join-Path $ProjectRoot "apps\desktop"
$TauriCli = Join-Path $DesktopRoot "node_modules\@tauri-apps\cli\tauri.js"

if (-not (Test-Path -LiteralPath $TauriCli -PathType Leaf)) {
    throw "Tauri CLI is not available in apps\desktop\node_modules. Restore the pinned local dependencies first."
}

& (Join-Path $PSScriptRoot "build_sidecar.ps1") -Python $Python
if ($LASTEXITCODE -ne 0) {
    throw "Coordinator sidecar build failed."
}

$Arguments = @($TauriCli, "build", "--ci", "--no-sign")
switch ($Target) {
    "Portable" { $Arguments += "--no-bundle" }
    "Msi" { $Arguments += @("--bundles", "msi") }
    "Nsis" { $Arguments += @("--bundles", "nsis") }
    "All" { $Arguments += @("--bundles", "msi,nsis") }
}

Push-Location $DesktopRoot
try {
    & $Node @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop packaging failed. MSI requires WiX 3.14 and NSIS requires NSIS 3.11 in Tauri's local cache."
    }
}
finally {
    Pop-Location
}

Write-Output (Join-Path $DesktopRoot "src-tauri\target\release\local-ai-lab-desktop.exe")
