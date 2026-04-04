@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_DIR=%%~fI"
cd /d "%PROJECT_DIR%"

set "PYTHON_GUI=%PROJECT_DIR%\.venv\Scripts\pythonw.exe"
set "PYTHON_STD=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "SCRIPT_PATH=%SCRIPT_DIR%homewash_manager.py"
set "ARGS=%*"

if exist "%PYTHON_GUI%" (
    start "Home Wash CRM" "%PYTHON_GUI%" "%SCRIPT_PATH%" %ARGS%
    exit /b 0
)

if exist "%PYTHON_STD%" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath $env:PYTHON_STD -ArgumentList @($env:SCRIPT_PATH,$env:ARGS) -WorkingDirectory $env:PROJECT_DIR -WindowStyle Hidden"
    exit /b 0
)

set "PYTHON_STD=C:/Users/mthia/AppData/Local/Microsoft/WindowsApps/python3.13.exe"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath $env:PYTHON_STD -ArgumentList @($env:SCRIPT_PATH,$env:ARGS) -WorkingDirectory $env:PROJECT_DIR -WindowStyle Hidden"
