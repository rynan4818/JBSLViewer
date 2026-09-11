@echo off
setlocal
cd /d "%~dp0"
call setup.bat
if errorlevel 1 goto failed
if not defined JBSL_CONFIG set "JBSL_CONFIG=%~dp0config.json"
if not exist "%JBSL_CONFIG%" copy /y config.example.json "%JBSL_CONFIG%" >nul
".venv\Scripts\python.exe" -m jbsl_score --config "%JBSL_CONFIG%" init
if errorlevel 1 goto failed
echo JBSL Score Manager starting. Default admin URL: http://127.0.0.1:18763/admin/
echo Press Ctrl+C to stop both listeners safely.
".venv\Scripts\python.exe" -m jbsl_score --config "%JBSL_CONFIG%" run
if errorlevel 1 goto failed
exit /b 0
:failed
echo Startup failed. See the message above and README.md.
pause
exit /b 1
