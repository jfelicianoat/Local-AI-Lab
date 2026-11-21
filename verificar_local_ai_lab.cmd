@echo off
setlocal
cd /d "%~dp0"
echo Verificando Local AI Lab...
echo La aplicacion se abrira y se cerrara automaticamente como parte de la prueba.
echo.
powershell.exe -NoLogo -NoProfile -File "%~dp0scripts\verify_pending_checks.ps1"
set "verification_exit=%ERRORLEVEL%"
echo.
if "%verification_exit%"=="0" (
  echo Verificaciones de red y arranque completadas correctamente.
) else (
  echo La comprobacion termino con errores. El detalle esta arriba y en los registros indicados.
)
echo.
pause
exit /b %verification_exit%
