@echo off
setlocal
cd /d "%~dp0"
call setup.bat
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt --disable-pip-version-check
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" scripts\validate.py %*
exit /b %errorlevel%
