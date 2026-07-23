@echo off

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERRO: este script precisa ser executado como Administrador.
    pause
    exit /b 1
)

cd /d "%~dp0"

set "CONFIG_FILE=%~dp0config.json"

if not exist "%CONFIG_FILE%" (
    echo ERRO: config.json nao encontrado em "%~dp0"
    pause
    exit /b 1
)

if not exist "requirements.txt" (
    echo ERRO: requirements.txt nao encontrado em "%~dp0"
    pause
    exit /b 1
)

if not exist "criar_banco.py" (
    echo ERRO: criar_banco.py nao encontrado em "%~dp0"
    pause
    exit /b 1
)

echo.
echo Configurando a aplicacao...
echo Nao feche esta janela ate que a configuracao seja concluida.
echo.

timeout /t 2 /nobreak > nul

if exist "venv\" (
    echo Ambiente virtual ja existe, pulando criacao.
) else (
	echo Criando ambiente virtual...
	python -m venv venv
	if errorlevel 1 (
		echo ERRO: falha ao criar ambiente virtual. Verifique se o Python esta instalado e no PATH.
		pause
		exit /b 1
	)
)

echo Instalando dependencias...
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERRO: falha ao instalar dependencias.
    pause
    exit /b 1
)

echo Criando banco de dados...
venv\Scripts\python.exe criar_banco.py
if errorlevel 1 (
    echo ERRO: falha ao criar banco de dados.
    pause
    exit /b 1
)

if exist ".env" (
    echo Arquivo .env ja existe, mantendo o atual.
) else (
    echo Criando arquivo .env...
    (
    echo SECRET_KEY=teste
    echo SENHA_SITE=teste
    echo SENHA_ADMIN=teste
    echo TRELLO_API_KEY=teste
    echo TRELLO_TOKEN=teste
    echo TRELLO_BOARD_ID=teste
    ) > .env
    echo Arquivo .env criado com sucesso!
)

for /f "delims=" %%A in ('powershell -NoProfile -Command ^
    "(Get-Content -Raw '%CONFIG_FILE%' | ConvertFrom-Json).SCRIPT_INICIAR_SITE"') do set "SCRIPT_INICIAR=%%A"

for /f "delims=" %%A in ('powershell -NoProfile -Command ^
    "(Get-Content -Raw '%CONFIG_FILE%' | ConvertFrom-Json).SCRIPT_REINICIAR_SITE"') do set "SCRIPT_REINICIAR=%%A"

if "%SCRIPT_INICIAR%"=="" (
    echo ERRO: SCRIPT_INICIAR_SITE nao encontrado no config.json
    pause
    exit /b 1
)

if "%SCRIPT_REINICIAR%"=="" (
    echo ERRO: SCRIPT_REINICIAR_SITE nao encontrado no config.json
    pause
    exit /b 1
)

set "CAMINHO_INICIAR=%~dp0%SCRIPT_INICIAR%"
set "CAMINHO_REINICIAR=%~dp0%SCRIPT_REINICIAR%"

echo Script de inicio: %CAMINHO_INICIAR%
echo Script de reinicio: %CAMINHO_REINICIAR%
echo.

if not exist "%CAMINHO_INICIAR%" (
    echo AVISO: arquivo "%CAMINHO_INICIAR%" nao existe!
)

if not exist "%CAMINHO_REINICIAR%" (
    echo AVISO: arquivo "%CAMINHO_REINICIAR%" nao existe!
)

echo.
echo Criando tarefa IniciarSistemaInterno...
schtasks /create ^
    /tn "IniciarSistemaInterno" ^
    /tr "\"%CAMINHO_INICIAR%\"" ^
    /sc ONSTART ^
    /ru SYSTEM ^
    /rl HIGHEST ^
    /f
if errorlevel 1 (
    echo ERRO: falha ao criar a tarefa IniciarSistemaInterno.
    pause
    exit /b 1
)

echo Criando tarefa ReiniciarSistemaInterno...
schtasks /create ^
    /tn "ReiniciarSistemaInterno" ^
    /tr "\"%CAMINHO_REINICIAR%\"" ^
    /sc ONCE ^
    /st 00:00 ^
    /sd 01/01/2099 ^
    /ru SYSTEM ^
    /rl HIGHEST ^
    /f
if errorlevel 1 (
    echo ERRO: falha ao criar a tarefa ReiniciarSistemaInterno.
    pause
    exit /b 1
)

echo.
echo Configuracao concluida com sucesso!
echo.

echo Algumas configuracoes adicionais sao necessarias:
echo.
echo 1. Abra o arquivo "config.json" e configure os parametros.
echo 2. Abra o arquivo ".env" e altere as senhas.
echo.
echo    IMPORTANTE: as senhas no .env estao como "teste".
echo    Troque TODAS antes de usar em producao!
echo.
echo Para iniciar a aplicacao:
echo execute o arquivo "run.bat"
echo.

pause