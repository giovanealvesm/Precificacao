@echo off
setlocal
for %%I in ("%~dp0") do set "SCRIPT_DIR=%%~fI"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_DIR=%%~fI"
set "VENV_PY=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "BUILD_SCRIPT=%SCRIPT_DIR%build_manager_exe.py"
set "DIST_DIR=%SCRIPT_DIR%dist"
set "WORK_DIR=%SCRIPT_DIR%build"
set "APP_NAME=HomeWashManager"
cd /d "%PROJECT_DIR%"

echo ========================================
echo GERAR EXE - HOME WASH CRM (MANAGER)
echo ========================================
echo.

if not exist "%VENV_PY%" (
    echo [ERRO] Ambiente virtual nao encontrado.
    echo Execute primeiro: instalador\instalar_interface_windows.bat
    echo.
    pause
    exit /b 1
)

if not exist "%BUILD_SCRIPT%" (
  echo [ERRO] Script de build nao encontrado: %BUILD_SCRIPT%
  echo.
  pause
  exit /b 1
)

echo [1/4] Atualizando pip e dependencias base...
call "%VENV_PY%" -m pip install --upgrade pip >nul
call "%VENV_PY%" -m pip install -r requirements.txt

echo [2/4] Instalando PyInstaller...
call "%VENV_PY%" -m pip install "pyinstaller>=6.10.0"

echo [3/4] Gerando executavel...
if exist "%SCRIPT_DIR%dist" rmdir /s /q "%SCRIPT_DIR%dist"
if exist "%SCRIPT_DIR%build" rmdir /s /q "%SCRIPT_DIR%build"
if exist "%SCRIPT_DIR%HomeWashManager.spec" del /f /q "%SCRIPT_DIR%HomeWashManager.spec"

if exist "%SCRIPT_DIR%dist" (
  echo [AVISO] A pasta instalador\dist esta em uso. Vou gerar um build alternativo em instalador\dist_rebuild.
  set "DIST_DIR=%SCRIPT_DIR%dist_rebuild"
  set "APP_NAME=HomeWashManager_rebuild"
  if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
)

if exist "%SCRIPT_DIR%build" (
  echo [AVISO] A pasta instalador\build esta em uso. Vou usar instalador\build_rebuild para este novo build.
  set "WORK_DIR=%SCRIPT_DIR%build_rebuild"
  if exist "%WORK_DIR%" rmdir /s /q "%WORK_DIR%"
)

set "HOMEWASH_MANAGER_DIST_DIR=%DIST_DIR%"
set "HOMEWASH_MANAGER_WORK_DIR=%WORK_DIR%"
set "HOMEWASH_MANAGER_APP_NAME=%APP_NAME%"
call "%VENV_PY%" "%BUILD_SCRIPT%"
set "BUILD_RC=%errorlevel%"

if not "%BUILD_RC%"=="0" (
    echo.
    echo [ERRO] Falha ao gerar executavel.
    echo.
    pause
    exit /b 1
)

echo [4/4] Build concluido.
echo Executavel: %DIST_DIR%%APP_NAME%\%APP_NAME%.exe
echo.
echo Dica: para distribuir para outra maquina, copie a pasta inteira:
echo %DIST_DIR%%APP_NAME%\
echo.
pause
