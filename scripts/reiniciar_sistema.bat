@echo off

set BASE=%~dp0..

cd /d "%BASE%\scripts"

taskkill /F /IM python.exe
timeout /t 3 /nobreak > nul

start "" cmd /c iniciar_sistema.bat