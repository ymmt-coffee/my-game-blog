@echo off
set "SCRIPT_PATH=%~dp0set-steam-credentials.ps1"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_PATH%"
set "SETUP_RESULT=%ERRORLEVEL%"
echo.
if not "%SETUP_RESULT%"=="0" echo Setup failed. Please check the message above.
if "%SETUP_RESULT%"=="0" echo Setup finished.
pause
exit /b %SETUP_RESULT%
