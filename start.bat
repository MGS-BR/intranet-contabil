@echo off

cd /d "%~dp0"

echo.
echo Configurando a aplicacao...
echo Nao feche esta janela ate que a configuracao seja concluida.
echo.

timeout /t 2 /nobreak > nul

echo Criando ambiente virtual...
python -m venv venv

echo Instalando dependencias...
venv\Scripts\python.exe -m pip install -r requirements.txt

echo Criando banco de dados...
venv\Scripts\python.exe criar_banco.py

echo Criando arquivo .env...

(
echo SECRET_KEY=teste
echo SENHA_SITE=teste
echo SENHA_ADMIN=teste
) > .env

echo Arquivo .env criado com sucesso!

echo.
echo Configuracao concluida com sucesso!
echo.

echo Algumas configuracoes adicionais sao necessarias:
echo.
echo 1. Abra o arquivo "config.json" e configure os parametros.
echo 2. Abra o arquivo ".env" e altere as senhas.
echo.
echo Para iniciar a aplicacao:
echo execute o arquivo "scripts\iniciar_sistema.bat"
echo.

pause