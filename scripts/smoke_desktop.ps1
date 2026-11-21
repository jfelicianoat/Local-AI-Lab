param(
    [string]$Executable = "",
    [ValidateRange(1, 60)] [int]$TimeoutSeconds = 20
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
$PreviousWebviewRoot = $env:WEBVIEW2_USER_DATA_FOLDER
$env:LOCAL_AI_LAB_DATA_DIR = $DataRoot
$env:WEBVIEW2_USER_DATA_FOLDER = Join-Path $DataRoot "webview-profile"
$Desktop = $null
$Failure = $null
$CleanupFailure = $null
$Ready = $false
Write-Output "Smoke evidence: $DataRoot"
try {
    $Desktop = Start-Process `
        -FilePath $Executable `
        -WorkingDirectory (Split-Path -Parent $Executable) `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $DataRoot "desktop.stdout.log") `
        -RedirectStandardError (Join-Path $DataRoot "desktop.stderr.log") `
        -PassThru
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
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
        throw "The Coordinator did not become ready within $TimeoutSeconds seconds."
    }
    $Database = Join-Path $DataRoot "coordinator\state.db"
    if (-not (Test-Path -LiteralPath $Database -PathType Leaf)) {
        throw "The Coordinator did not initialize its database."
    }
}
catch { $Failure = $_ }
finally {
    try {
        if ($null -ne $Desktop) {
            $Desktop.Refresh()
            if (-not $Desktop.HasExited) {
                try {
                    # Kill(bool) is available in modern .NET, but not in the
                    # .NET Framework used by Windows PowerShell 5.1.
                    $TreeKill = $Desktop.GetType().GetMethod("Kill", [type[]]@([bool]))
                    if ($null -ne $TreeKill) {
                        $Desktop.Kill($true)
                    }
                    else {
                        $CleanupLog = Join-Path $DataRoot "cleanup.log"
                        & taskkill.exe /PID $Desktop.Id /T /F *> $CleanupLog
                        $KillExit = $LASTEXITCODE
                        $Desktop.Refresh()
                        if ($KillExit -ne 0 -and -not $Desktop.HasExited) {
                            throw "Could not stop the isolated test process. See $CleanupLog"
                        }
                    }
                    if (-not $Desktop.WaitForExit(5000)) {
                        $CleanupFailure = "The isolated desktop did not exit after termination."
                    }
                }
                catch {
                    $Desktop.Refresh()
                    if (-not $Desktop.HasExited) { $CleanupFailure = $_.Exception.Message }
                }
            }
        }
    }
    catch { $CleanupFailure = $_.Exception.Message }
    finally {
        $env:LOCAL_AI_LAB_DATA_DIR = $PreviousDataRoot
        $env:WEBVIEW2_USER_DATA_FOLDER = $PreviousWebviewRoot
    }
}
$Report = [ordered]@{
    executable = $Executable
    data_root = $DataRoot
    ready = $Ready
    status = $(if ($null -eq $Failure -and $null -eq $CleanupFailure) { "PASS" } else { "FAILED" })
    startup_error = $(if ($null -ne $Failure) { $Failure.Exception.Message } else { $null })
    cleanup_error = $CleanupFailure
}
$Report | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $DataRoot "smoke.json") -Encoding utf8
if ($null -ne $CleanupFailure) { Write-Warning "Smoke cleanup: $CleanupFailure" }
if ($null -ne $Failure) { throw $Failure }
if ($null -ne $CleanupFailure) { throw "Smoke cleanup failed: $CleanupFailure" }
Write-Output "Desktop startup smoke passed."
Write-Output $Executable
