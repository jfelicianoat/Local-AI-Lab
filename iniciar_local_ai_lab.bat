@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Local AI Lab

rem Locate complete portable builds relative to this launcher.
set "LOCAL_AI_LAB_LAUNCHER_ROOT=%~dp0"
set "APP_DIR="
for /f "usebackq delims=" %%D in (`powershell.exe -NoLogo -NoProfile -Command "Get-ChildItem -LiteralPath (Join-Path $env:LOCAL_AI_LAB_LAUNCHER_ROOT 'dist') -Directory -Filter 'candidate-*' -ErrorAction SilentlyContinue | Where-Object { (Test-Path -LiteralPath (Join-Path $_.FullName 'local-ai-lab-desktop.exe') -PathType Leaf) -and (Test-Path -LiteralPath (Join-Path $_.FullName 'resources\local-ai-lab-coordinator.exe') -PathType Leaf) } | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1 -ExpandProperty FullName"`) do set "APP_DIR=%%D"

rem Fall back to a local release build when no portable is available.
if not defined APP_DIR set "APP_DIR=%~dp0apps\desktop\src-tauri\target\release"
if not exist "%APP_DIR%\local-ai-lab-desktop.exe" goto :missing_build
if exist "%APP_DIR%\resources\local-ai-lab-coordinator.exe" goto :ready
if exist "%APP_DIR%\local-ai-lab-coordinator.exe" goto :ready
goto :missing_build

:ready
echo Iniciando Local AI Lab desde:
echo "%APP_DIR%"
if /I "%~1"=="--check" exit /b 0
start "" /D "%APP_DIR%" "%APP_DIR%\local-ai-lab-desktop.exe"
if errorlevel 1 goto :launch_error
exit /b 0

:missing_build
echo.
echo ERROR: No se encuentra una compilacion completa de Local AI Lab.
echo El escritorio necesita local-ai-lab-desktop.exe y su Coordinator.
echo Conserve la carpeta resources junto al ejecutable portable.
echo Para generar una compilacion, consulte README.md.
goto :failure

:launch_error
echo.
echo ERROR: No se pudo abrir Local AI Lab.

:failure
if /I "%~1"=="--check" exit /b 1
echo.
pause
exit /b 1
