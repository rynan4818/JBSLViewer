@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0package.ps1" %*
set "PACKAGE_EXIT=%errorlevel%"
popd
exit /b %PACKAGE_EXIT%
