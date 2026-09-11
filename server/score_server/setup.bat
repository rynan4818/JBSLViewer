@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto checkvenv
if defined JBSL_PYTHON goto explicit
py -3 -c "import sys; assert sys.version_info >= (3,12)" >nul 2>&1
if not errorlevel 1 goto launcher
python -c "import sys; assert sys.version_info >= (3,12)" >nul 2>&1
if errorlevel 1 goto nopython
python -m venv .venv
goto created
:launcher
py -3 -m venv .venv
goto created
:explicit
"%JBSL_PYTHON%" -m venv .venv
:created
if errorlevel 1 exit /b 1
:checkvenv
".venv\Scripts\python.exe" -c "import sys; assert sys.version_info >= (3,12)" >nul 2>&1
if errorlevel 1 goto invalidvenv
".venv\Scripts\python.exe" scripts\check_dependencies.py >nul 2>&1
if not errorlevel 1 exit /b 0
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
exit /b %errorlevel%
:nopython
echo Python 3.12 or later is required. Install Python, or set JBSL_PYTHON to python.exe.
exit /b 1
:invalidvenv
echo The .venv Python is unavailable. Rename .venv and run setup.bat again.
exit /b 1
