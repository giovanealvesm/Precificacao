@echo off
REM Modo recomendado: startup silencioso; abre janela apenas em erro
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar_cloudflare_background.ps1"
