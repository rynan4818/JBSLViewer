@echo off
setlocal
cd /d "%~dp0..\.."
set "PYTHONUTF8=1"
set "MOCK_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%MOCK_PY%" (
  call "%~dp0setup.bat"
  if errorlevel 1 exit /b 1
)
"%MOCK_PY%" -m pytest "%~dp0tests" -q %*
exit /b %errorlevel%
