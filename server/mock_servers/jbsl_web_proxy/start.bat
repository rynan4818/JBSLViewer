@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "MOCK_PY=%~dp0.venv\Scripts\python.exe"
if exist "%MOCK_PY%" (
  "%MOCK_PY%" -c "import fastapi,uvicorn,httpx,multipart,pydantic; assert int(pydantic.__version__.split('.')[0]) >= 2" >nul 2>nul
  if not errorlevel 1 goto run
)
call "%~dp0setup.bat"
if errorlevel 1 (
  echo Setup failed. See the error above.
  pause
  exit /b 1
)
:run
echo First startup creates an administrator here. Use that username and password to log in.
echo Open http://127.0.0.1:18764/admin/ after startup. JBSL-WEB relay. Ctrl+C stops this API and its admin.
"%MOCK_PY%" "%~dp0run.py" %*
set "MOCK_EXIT=%errorlevel%"
if not "%MOCK_EXIT%"=="0" pause
exit /b %MOCK_EXIT%
