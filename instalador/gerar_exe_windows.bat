@echo off
setlocal
for %%I in ("%~dp0") do set "SCRIPT_DIR=%%~fI"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_DIR=%%~fI"
cd /d "%PROJECT_DIR%"

echo ========================================
echo GERAR EXE - HOME WASH CRM (MANAGER)
echo ========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual nao encontrado.
    echo Execute primeiro: instalador\instalar_interface_windows.bat
    echo.
    pause
    exit /b 1
)

echo [1/4] Atualizando pip e dependencias base...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo [2/4] Instalando PyInstaller...
call ".venv\Scripts\python.exe" -m pip install "pyinstaller>=6.10.0"

echo [3/4] Gerando executavel...
if exist "%SCRIPT_DIR%dist" rmdir /s /q "%SCRIPT_DIR%dist"
if exist "%SCRIPT_DIR%build" rmdir /s /q "%SCRIPT_DIR%build"
if exist "%SCRIPT_DIR%HomeWashManager.spec" del /f /q "%SCRIPT_DIR%HomeWashManager.spec"

pushd "%SCRIPT_DIR%"
call ".venv\Scripts\python.exe" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --name HomeWashManager ^
  --specpath "%SCRIPT_DIR%" ^
  --distpath "%SCRIPT_DIR%dist" ^
  --workpath "%SCRIPT_DIR%build" ^
  --exclude-module streamlit ^
  --exclude-module pandas ^
  --exclude-module reportlab ^
  --exclude-module twilio ^
  --exclude-module google ^
  --exclude-module googleapiclient ^
  --exclude-module google_auth_oauthlib ^
  --exclude-module numpy ^
  --add-data "..\iniciar_sistema.bat;." ^
  --add-data "..\iniciar_cloudflare_background.ps1;." ^
  --add-data "..\configurar_automacao.bat;." ^
  --add-data "..\config_env.py;." ^
  --add-data "..\assets;assets" ^
  homewash_manager.py
set "BUILD_RC=%errorlevel%"
popd

if not "%BUILD_RC%"=="0" (
    echo.
    echo [ERRO] Falha ao gerar executavel.
    echo.
    pause
    exit /b 1
)

echo [4/4] Build concluido.
echo Executavel: instalador\dist\HomeWashManager\HomeWashManager.exe
echo.
echo Dica: para distribuir para outra maquina, copie a pasta inteira:
echo instalador\dist\HomeWashManager\
echo.
pause
