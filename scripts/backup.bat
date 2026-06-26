@echo off
chcp 65001 > nul

echo Iniciando backup..
echo.

set BASE=%~dp0..

for /f "delims=" %%i in ('python -c "import json; print(json.load(open(r'%BASE%\config.json'))['PASTA_ARQUIVOS'])"') do set PASTA=%%i
for /f "delims=" %%i in ('python -c "import json; print(json.load(open(r'%BASE%\config.json'))['PASTA_BACKUP'])"') do set BACKUP=%%i

robocopy "%PASTA%" "%BACKUP%" /E /R:1 /W:2 /MT:8 /FFT /XJ /XA:SH /XF desktop.ini thumbs.db *.tmp *.temp /TEE /LOG:backup.log

echo.
echo Backup finalizado.
pause