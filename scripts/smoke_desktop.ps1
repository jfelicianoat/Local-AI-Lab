param(
    [string]$Executable = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Executable) {
    $Executable = Join-Path $ProjectRoot "apps\desktop\src-tauri\target\release\local-ai-lab-desktop.exe"
}
$Executable = (Resolve-Path -LiteralPath $Executable).Path
$TestRoot = Join-Path $ProjectRoot ".test-tmp\desktop-smoke"
$DataRoot = Join-Path $TestRoot ([guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null

$PreviousDataRoot = $env:LOCAL_AI_LAB_DATA_DIR
$env:LOCAL_AI_LAB_DATA_DIR = $DataRoot
$Desktop = $null
try {
    $Desktop = Start-Process `
        -FilePath $Executable `
        -WorkingDirectory (Split-Path -Parent $Executable) `
        -WindowStyle Hidden `
        -PassThru
    $Deadline = (Get-Date).AddSeconds(20)
    $Ready = $false
    while ((Get-Date) -lt $Deadline) {
        Start-Sleep -Milliseconds 250
        $Desktop.Refresh()
        if ($Desktop.HasExited) {
            throw "Local AI Lab exited during startup with code $($Desktop.ExitCode)."
        }
        $LogPath = Join-Path $DataRoot "coordinator.log"
        if ((Test-Path -LiteralPath $LogPath) -and
            ((Get-Content -LiteralPath $LogPath -Raw) -match "Application startup complete")) {
            $Ready = $true
            break
        }
    }
    if (-not $Ready) {
        throw "The Coordinator did not become ready within 20 seconds."
    }
    $Database = Join-Path $DataRoot "coordinator\state.db"
    if (-not (Test-Path -LiteralPath $Database -PathType Leaf)) {
        throw "The Coordinator did not initialize its database."
    }
}
finally {
    try {
        if ($null -ne $Desktop) {
            $Desktop.Refresh()
            if (-not $Desktop.HasExited) {
                # Stop only this desktop and its descendants, including the sidecar.
                & taskkill.exe /PID $Desktop.Id /T /F | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    throw "Could not stop the smoke-test process tree (desktop PID $($Desktop.Id))."
                }
            }
        }
    }
    finally {
        $env:LOCAL_AI_LAB_DATA_DIR = $PreviousDataRoot
    }
}
Write-Output "Desktop startup smoke passed."
Write-Output $Executable
