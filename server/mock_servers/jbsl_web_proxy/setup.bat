@echo off
setlocal
cd /d "%~dp0"
set "MOCK_PY=%~dp0.venv\Scripts\python.exe"
if exist "%MOCK_PY%" (
  "%MOCK_PY%" -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
  if not errorlevel 1 goto install
  echo The existing .venv is invalid. Rename it and run setup.bat again.
  exit /b 1
)
if defined JBSL_PYTHON (
  "%JBSL_PYTHON%" -m venv "%~dp0.venv"
  if errorlevel 1 exit /b 1
  goto install
)
py -3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv "%~dp0.venv"
  if errorlevel 1 exit /b 1
  goto install
)
python -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
if not errorlevel 1 (
  python -m venv "%~dp0.venv"
  if errorlevel 1 exit /b 1
  goto install
)
echo Install Python 3.11+ or set JBSL_PYTHON to the full path to python.exe.
exit /b 1
:install
"%MOCK_PY%" -m pip install -r "%~dp0requirements.txt"
exit /b %errorlevel%
