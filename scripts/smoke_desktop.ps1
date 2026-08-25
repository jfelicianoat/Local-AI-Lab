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

$env:LOCAL_AI_LAB_DATA_DIR = $DataRoot
$Started = Get-Date
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
    Write-Output "Desktop startup smoke passed."
    Write-Output $Executable
}
finally {
    if ($null -ne $Desktop) {
        $Desktop.Refresh()
        if (-not $Desktop.HasExited) {
            Stop-Process -Id $Desktop.Id -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Milliseconds 500
    $Sidecars = @(
        Get-Process -Name "local-ai-lab-coordinator" -ErrorAction SilentlyContinue |
            Where-Object { $_.StartTime -ge $Started }
    )
    foreach ($Sidecar in $Sidecars) {
        Stop-Process -Id $Sidecar.Id -ErrorAction SilentlyContinue
    }
}
