@echo off

taskkill /F /IM python.exe
timeout /t 3 /nobreak > nul

start "" cmd ../scripts\iniciar_sistema.bat