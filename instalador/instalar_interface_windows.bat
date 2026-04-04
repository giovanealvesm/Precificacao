@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_DIR=%%~fI"
cd /d "%PROJECT_DIR%"

echo ========================================
echo INSTALADOR - HOME WASH CRM (WINDOWS)
echo ========================================
echo.

set "PYTHON_CMD="
where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=python"
) else if exist "C:/Users/%USERNAME%/AppData/Local/Microsoft/WindowsApps/python3.13.exe" (
    set "PYTHON_CMD=C:/Users/%USERNAME%/AppData/Local/Microsoft/WindowsApps/python3.13.exe"
)

if not defined PYTHON_CMD (
    where winget >nul 2>nul
    if not errorlevel 1 (
        echo [0/5] Python nao encontrado. Instalando via winget...
        winget install -e --id Python.Python.3.13 --accept-package-agreements --accept-source-agreements
        where python >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON_CMD=python"
        ) else if exist "C:/Users/%USERNAME%/AppData/Local/Programs/Python/Python313/python.exe" (
            set "PYTHON_CMD=C:/Users/%USERNAME%/AppData/Local/Programs/Python/Python313/python.exe"
        )
    )
)

if not defined PYTHON_CMD (
    echo [ERRO] Python nao encontrado e nao foi possivel instalar automaticamente.
    echo Instale o Python 3.13 e execute novamente este instalador.
    echo.
    pause
    exit /b 1
)

if not exist "cloudflared.exe" (
    echo [1/5] Cloudflared nao encontrado. Baixando automaticamente...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'cloudflared.exe'"
    if errorlevel 1 (
        echo [AVISO] Nao foi possivel baixar o cloudflared automaticamente.
        echo [AVISO] O programa podera funcionar apenas em modo local ate esse componente ser instalado.
    ) else (
        echo [OK] cloudflared.exe baixado para a pasta do projeto.
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo [2/5] Criando ambiente virtual...
    %PYTHON_CMD% -m venv .venv
)

echo [3/5] Instalando dependencias...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo [4/5] Criando atalho na Area de Trabalho e Menu Iniciar...
set "SHORTCUT_NAME=Home Wash CRM.lnk"
set "SYNC_SHORTCUT_NAME=Home Wash Sincronizacao.lnk"
set "TARGET=%SCRIPT_DIR%iniciar_interface_windows.bat"
set "SYNC_TARGET=%SCRIPT_DIR%abrir_sincronizacao_windows.bat"
set "WORKDIR=%PROJECT_DIR%"
set "ICON_FILE="
set "ICON_SOURCE="

if exist "%PROJECT_DIR%\assets\logo.ico" set "ICON_FILE=%PROJECT_DIR%\assets\logo.ico"
if not defined ICON_FILE if exist "%PROJECT_DIR%\assets\favicon.ico" set "ICON_FILE=%PROJECT_DIR%\assets\favicon.ico"

if not defined ICON_FILE if exist "%PROJECT_DIR%\assets\logo.png" set "ICON_SOURCE=%PROJECT_DIR%\assets\logo.png"
if not defined ICON_FILE if not defined ICON_SOURCE if exist "%PROJECT_DIR%\assets\logo_symbol_clean.png" set "ICON_SOURCE=%PROJECT_DIR%\assets\logo_symbol_clean.png"
if not defined ICON_FILE if not defined ICON_SOURCE if exist "%PROJECT_DIR%\assets\logo_full_clean.png" set "ICON_SOURCE=%PROJECT_DIR%\assets\logo_full_clean.png"
if not defined ICON_FILE if not defined ICON_SOURCE if exist "%PROJECT_DIR%\assets\favicon.png" set "ICON_SOURCE=%PROJECT_DIR%\assets\favicon.png"
if not defined ICON_FILE if not defined ICON_SOURCE if exist "%PROJECT_DIR%\assets\teste logo.jpeg" set "ICON_SOURCE=%PROJECT_DIR%\assets\teste logo.jpeg"
if not defined ICON_FILE if not defined ICON_SOURCE if exist "%PROJECT_DIR%\assets\logo.jpg" set "ICON_SOURCE=%PROJECT_DIR%\assets\logo.jpg"
if not defined ICON_FILE if not defined ICON_SOURCE if exist "%PROJECT_DIR%\assets\logo.jpeg" set "ICON_SOURCE=%PROJECT_DIR%\assets\logo.jpeg"

if not defined ICON_FILE if defined ICON_SOURCE (
    set "ICON_FILE=%PROJECT_DIR%\assets\logo_shortcut.ico"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Add-Type -AssemblyName System.Drawing; $src=$env:ICON_SOURCE; $dst=$env:ICON_FILE; $img=[System.Drawing.Image]::FromFile($src); $sz=128; $bmp=New-Object System.Drawing.Bitmap $sz $sz; $gfx=[System.Drawing.Graphics]::FromImage($bmp); $gfx.Clear([System.Drawing.Color]::Transparent); $ar=$img.Width/$img.Height; $w=$sz; $h=$sz; if($ar -gt 1){$h=[int]($sz/$ar)}else{$w=[int]($sz*$ar)}; $x=($sz-$w)/2; $y=($sz-$h)/2; $gfx.DrawImage($img,$x,$y,$w,$h); $h=$bmp.GetHicon(); $icon=[System.Drawing.Icon]::FromHandle($h); $fs=[System.IO.File]::Open($dst,[System.IO.FileMode]::Create); $icon.Save($fs); $fs.Close(); $img.Dispose(); $bmp.Dispose(); $gfx.Dispose() } catch { exit 1 }"
    if errorlevel 1 (
        echo [AVISO] Nao foi possivel gerar o icone a partir da logo. O atalho usara icone padrao.
        set "ICON_FILE="
    )
)

for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP_DIR=%%I"
if not defined DESKTOP_DIR set "DESKTOP_DIR=%USERPROFILE%\Desktop"

for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Programs')"`) do set "STARTMENU_DIR=%%I"
if not defined STARTMENU_DIR set "STARTMENU_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs"

if not exist "%DESKTOP_DIR%" mkdir "%DESKTOP_DIR%" >nul 2>nul
if not exist "%STARTMENU_DIR%" mkdir "%STARTMENU_DIR%" >nul 2>nul

set "DESKTOP=%DESKTOP_DIR%\%SHORTCUT_NAME%"
set "STARTMENU=%STARTMENU_DIR%\%SHORTCUT_NAME%"
set "SYNC_DESKTOP=%DESKTOP_DIR%\%SYNC_SHORTCUT_NAME%"
set "SYNC_STARTMENU=%STARTMENU_DIR%\%SYNC_SHORTCUT_NAME%"

set "DESKTOP_LINK=%DESKTOP%"
set "STARTMENU_LINK=%STARTMENU%"
set "SYNC_DESKTOP_LINK=%SYNC_DESKTOP%"
set "SYNC_STARTMENU_LINK=%SYNC_STARTMENU%"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; function New-Link([string]$path,[string]$target,[string]$desc,[string]$iconPath){ $w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut($path); $s.TargetPath=$target; $s.WorkingDirectory=$env:WORKDIR; $s.Description=$desc; if($iconPath -and (Test-Path $iconPath)){ $s.IconLocation=($iconPath + ',0') }; $s.Save() }; New-Link $env:DESKTOP_LINK $env:TARGET 'Home Wash CRM - Gerenciador' $env:ICON_FILE; New-Link $env:STARTMENU_LINK $env:TARGET 'Home Wash CRM - Gerenciador' $env:ICON_FILE; New-Link $env:SYNC_DESKTOP_LINK $env:SYNC_TARGET 'Home Wash CRM - Sincronizacao' $env:ICON_FILE; New-Link $env:SYNC_STARTMENU_LINK $env:SYNC_TARGET 'Home Wash CRM - Sincronizacao' $env:ICON_FILE"
if errorlevel 1 (
    echo [AVISO] Nao foi possivel criar algum atalho automaticamente.
    echo [AVISO] Voce ainda pode iniciar por: %TARGET%
)

echo Atalho Desktop: %DESKTOP%
echo Atalho Menu Iniciar: %STARTMENU%
echo Atalho Sincronizacao Desktop: %SYNC_DESKTOP%
echo Atalho Sincronizacao Menu Iniciar: %SYNC_STARTMENU%
if defined ICON_FILE echo Icone do atalho: %ICON_FILE%

echo.
echo ========================================
echo INSTALACAO CONCLUIDA
echo ========================================
echo.
echo Componentes preparados:
echo - Python/venv
echo - Dependencias Python do CRM
echo - Cloudflared para link externo no celular (quando disponivel)
echo - Atalhos com icone no Windows
echo.
echo Como usar:
echo - Clique em "Home Wash CRM" na Area de Trabalho
echo - Clique em "Home Wash Sincronizacao" para abrir direto a central de sincronizacao
echo.
echo Na primeira vez:
echo - Preencha os dados da aba "Configuracao inicial" e salve
echo - A janela abrir automaticamente na aba "Controle do programa"
echo - Use os botoes Iniciar, Parar e Reiniciar normalmente
echo.
pause
