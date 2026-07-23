# Intranet Contábil

![Python](https://img.shields.io/badge/Python-3.14-blue)
![Status](https://img.shields.io/badge/status-em%20desenvolvimento-yellow)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Sistema interno (intranet) desenvolvido em **Flask** para escritórios de contabilidade. Centraliza em um único painel web o acesso a arquivos de clientes, procedimentos internos, cadastro de empresas, controle de horas extras, backup, monitoramento do servidor, geração de PDDE e OCR de PDFs, entre outras rotinas do dia a dia do escritório.

> ⚠️ Este sistema foi projetado para rodar em um **servidor Windows local** (geralmente o próprio servidor de arquivos do escritório), pois algumas funcionalidades (reinício do servidor, backup via Robocopy, monitoramento de disco `C:\`, `D:\`, `E:\`) dependem do ambiente Windows.

## Funcionalidades

| Módulo | Descrição |
|---|---|
| **Login** | Acesso protegido por senha única (`SENHA_SITE`), com sessão Flask. |
| **Página inicial / Agenda** | Calendário de eventos (com suporte a recorrência) e indicadores rápidos (procedimentos cadastrados, último backup). |
| **Procedimentos** | Listagem e abertura de arquivos `.doc`, `.docx` e `.pdf` com os procedimentos internos do escritório. |
| **Certificados** | Página de referência sobre certificados digitais. |
| **Arquivos** | Navegador de arquivos dos clientes (upload, abertura e reindexação via SQLite). |
| **Empresas** | Cadastro de empresas extraído automaticamente de arquivos de CNPJ/QSA da Receita Federal, com dados de sócios. |
| **Pendências** | Lista empresas com cadastro incompleto (sem CNPJ, sem sócios, situação cadastral irregular, etc.). |
| **Horas extras** | Cadastro de funcionários e lançamento/controle de horas extras. |
| **PDDE** | Geração de planilha de importação (modelo Contmatic) a partir de extrato em PDF ou lançamento manual, usando um plano de contas de referência. |
| **OCR** | Aplica OCR em PDFs (via `ocrmypdf`) tornando documentos digitalizados pesquisáveis. |
| **Ajuda eSocial** | Base de consulta com códigos de erro do eSocial e suas soluções. |
| **Backup** | Executa rotina de backup (Robocopy) da pasta de arquivos e exibe o log da última execução. |
| **Servidor** (`monitoramento.html`) | Painel com uso de CPU, memória, disco e tempo de atividade, além de botões para reiniciar o servidor ou apenas reiniciar a aplicação (protegido por `SENHA_ADMIN`). |
| **Trello** | Cria cards em um board do Trello configurado via `TRELLO_API_KEY`, `TRELLO_TOKEN` e `TRELLO_BOARD_ID`. |
| **Pasta organizadora** | Roda rotinas de organização de arquivos e mostra status/log da última execução. |
| **Configurações** | Tela protegida por login (`/configuracoes`) para editar nome do escritório, favicon, pastas do `config.json` e apagar tabelas do banco. |

## Estrutura dos arquivos

```
intranet-contabil/
├── app.py                     # Aplicação Flask principal (rotas, regras de negócio)
├── banco.py                   # Criação/atualização do schema do SQLite e utilitários de CLI
├── criar_banco.py             # Script de conveniência: chama banco.criar_tabelas()
├── banco.db                   # Banco de dados SQLite (gerado/atualizado automaticamente, não versionado)
├── config.json                # Configuração de pastas e scripts utilizados pelo sistema
├── requirements.txt           # Dependências Python do projeto
├── config.bat                 # Script de instalação inicial (Windows) — cria venv, instala deps, gera .env e agenda as tarefas
├── run.bat                    # Ativa o venv e roda "python app.py" diretamente
├── indexar_empresas.py        # Lê PDFs de CNPJ/QSA em PASTA_CLIENTES e popula a tabela empresas
├── pasta_organizadora.py      # Rotina de organização automática de arquivos
├── pdde_importador.py         # Geração das planilhas de importação do módulo PDDE
│
├── templates/                 # Templates Jinja2 (HTML) de cada página
│   ├── base.html              # Layout base (menu, navegação, mensagens flash)
│   ├── login.html
│   ├── index.html             # Página inicial / agenda
│   ├── procedimentos.html
│   ├── certificados.html
│   ├── arquivos.html
│   ├── empresas.html
│   ├── empresa.html           # Detalhe de uma empresa
│   ├── empresas_pendencias.html
│   ├── funcionario.html
│   ├── horas_extras.html
│   ├── horas_extras_funcionario.html
│   ├── pdde.html
│   ├── ocr.html
│   ├── esocial.html
│   ├── monitoramento.html     # Painel do servidor
│   ├── configuracoes.html
│   ├── trello.html
│   ├── pasta_organizadora.html
│   └── backup.html
│
├── static/
│   ├── style.css              # Estilos da aplicação
│   ├── navbar.js
│   ├── backup.js
│   ├── ocr.js
│   ├── pdde.js
│   ├── trello.js
│   ├── pasta_organizadora.js
│   └── favicon.ico
│
├── scripts/                   # Scripts auxiliares do Windows
│   ├── iniciar_sistema.bat    # Ativa o venv e inicia "python app.py"
│   ├── reiniciar.bat          # Reinicia o servidor Windows (shutdown /r)
│   ├── reiniciar_sistema.bat  # Encerra o processo Python e reinicia só a aplicação
│   └── backup.bat             # Executa o backup via robocopy, lendo as pastas do config.json
│
├── modelos/                    # Modelos usados pelo módulo PDDE
│   ├── PLCONTAS.pdf                          # Plano de contas de referência
│   └── Planilha Importação Contmatic.xlsx    # Modelo de planilha de importação
│
├── exemplos/                   # Pastas de EXEMPLO (placeholders) — substituir em produção
│   ├── arquivos/                # Exemplo de estrutura de PASTA_ARQUIVOS
│   ├── clientes/                # Exemplo de estrutura de PASTA_CLIENTES
│   └── procedimentos/           # Exemplo de estrutura de PASTAS_PROCEDIMENTOS
│
├── uploads/                    # Arquivos enviados pelos usuários
│   ├── pdde/                    # Uploads de extratos em PDF para o módulo PDDE
│   └── pdf/                     # Uploads de PDFs para o módulo de OCR
│
├── saida/                      # Arquivos gerados pelo sistema, prontos para download
│   ├── pdde/                    # Planilhas de importação geradas
│   └── pdf/                     # PDFs após OCR
│
├── LICENSE                     # Licença MIT
└── README.md
```

### Sobre o banco de dados (`banco.db`)

O banco SQLite é criado/atualizado automaticamente (tanto por `criar_banco.py` quanto pelo próprio `app.py` ao iniciar) e contém as seguintes tabelas:

- `indice_arquivos` — índice de busca dos arquivos de `PASTA_ARQUIVOS`.
- `empresas` — dados cadastrais das empresas (CNPJ, razão social, endereço, situação cadastral, etc.).
- `socios_empresas` — sócios/QSA vinculados a cada empresa.
- `funcionarios_horas` e `horas_extras` — controle de horas extras.
- `eventos` — eventos da agenda exibida na página inicial.
- `esocial` — base de códigos de erro do eSocial e respectivas soluções.

## Pré-requisitos

- **Windows** (recomendado, para uso de todas as funcionalidades — especialmente reinício de servidor e backup via Robocopy).
- **Python 3.10+** instalado e disponível no `PATH`.
- **Tesseract** necessário para o OCR funcionar, deve ser instalado e adicionado ao `PATH`.
- Acesso de leitura/escrita às pastas que serão configuradas em `config.json`.

## Instalando o Tesseract

1. Acesse [github.com/UB-Mannheim/tesseract/wiki](https://github.com/UB-Mannheim/tesseract/wiki).
2. Faça o download do tesseract e execute o .exe.
3. Durante o download será solicitado para selecionar os componentes para instalar, faça:
    - Clique em `Additional language data (download)`.
    - Selecione `Portuguese`.
    - Prossiga com o download normalmente.
4. Após o download verifique se ele foi adicionado ao `PATH`:
    - Pressione `Win + R`, digite `sysdm.cpl` e aperte ENTER.
    - Vá em avançado > variáveis de ambiente.
    - Selecione o `PATH` e clique em editar.
    - Verifique se há algo como `C:\Program Files\Tesseract-OCR`.
    - Se não houver, adicione esse caminho manualmente clicando em novo.
    - Informe `C:\Program Files\Tesseract-OCR` se o Tesseract foi instalado no local padrão.
    - Confirme as alterações e pronto.
5. Caso não tenha sido selecionado o idioma adicional `portuguese`, faça:
    - Abra [github.com/tesseract-ocr/tessdata/blob/main/por.traineddata](https://github.com/tesseract-ocr/tessdata/blob/main/por.traineddata).
    - Faça o download do arquivo.
    - Coloque o arquivo na pasta `C:\Program Files\Tesseract-OCR\tessdata`.
    - Após isso o Tesseract esta configurado.

## Configuração e instalação

### 1. Instalação automática (recomendado)

1. Extraia o projeto em uma pasta do servidor (ex.: `D:\Escritorio\intranet-contabil`).
2. Execute o arquivo **`config.bat`** **como Administrador**, que fará automaticamente:
   - Criação do ambiente virtual (`venv`);
   - Instalação das dependências de `requirements.txt`;
   - Criação/atualização do banco de dados (`criar_banco.py`);
   - Criação de um arquivo `.env` com valores **de teste** (`SECRET_KEY`, `SENHA_SITE`, `SENHA_ADMIN`, `TRELLO_API_KEY`, `TRELLO_TOKEN`, `TRELLO_BOARD_ID` = `teste`);
   - Criação de duas tarefas no Agendador de Tarefas do Windows (`IniciarSistemaInterno` e `ReiniciarSistemaInterno`), que apontam para os scripts definidos em `SCRIPT_INICIAR_SITE`/`SCRIPT_REINICIAR_SITE` no `config.json`.

3. Ao final, o script vai pedir para você:
   - Editar o **`config.json`** com os caminhos reais do escritório;
   - Editar o **`.env`** e trocar as senhas padrão por senhas seguras.

### 2. Instalação manual

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python criar_banco.py
```

Crie manualmente um arquivo `.env` na raiz do projeto:

```env
SECRET_KEY=uma-chave-secreta-aleatoria-e-dificil-de-adivinhar
SENHA_SITE=senha-de-acesso-ao-sistema
SENHA_ADMIN=senha-para-acoes-administrativas
```

- `SECRET_KEY` — usada pelo Flask para assinar a sessão (`app.secret_key`). Use uma string longa e aleatória.
- `SENHA_SITE` — senha única usada por todos para fazer login no sistema (tela `/login`).
- `SENHA_ADMIN` — senha exigida para ações sensíveis (reiniciar o servidor ou reiniciar só a aplicação, em `/servidor`). Se não for definida, o sistema usa `SENHA_SITE` como fallback.

> 🔒 Nunca deixe o sistema em produção com as senhas de teste (`teste`) criadas pelo `config.bat`.

### 3. Configurando o `config.json`

Esse arquivo define **onde estão** as pastas reais do escritório e os scripts utilizados pelo sistema. Os caminhos podem ser relativos (à raiz do projeto) ou absolutos, usando `\\` como separador no Windows:

```json
{
    "PASTAS_PROCEDIMENTOS": "exemplos\\procedimentos",
    "PASTA_ARQUIVOS": "exemplos\\arquivos",
    "PASTA_CLIENTES": "exemplos\\clientes",
    "PASTA_BACKUP": "exemplos\\backup",

    "SCRIPT_BACKUP": "scripts\\backup.bat",
    "LOG_BACKUP": "scripts\\backup.log",
    "SCRIPT_REINICIAR": "scripts\\reiniciar.bat",
    "SCRIPT_REINICIAR_SITE": "scripts\\reiniciar_sistema.bat",

    "PASTA_UPLOAD_PDDE": "uploads\\pdde",
    "PASTA_SAIDA_PDDE": "saida\\pdde",
    "PLANO_CONTAS_PDDE": "modelos\\PLCONTAS.pdf",
    "MODELO_IMPORTACAO_CONTMATIC": "modelos\\Planilha Importação Contmatic.xlsx",

    "PASTA_UPLOAD_PDF": "uploads\\pdf",
    "PASTA_SAIDA_PDF": "saida\\pdf"
}
```

| Chave | Para que serve |
|---|---|
| `PASTAS_PROCEDIMENTOS` | Pasta onde ficam os arquivos de procedimentos internos (`.doc`, `.docx`, `.pdf`) exibidos em **/procedimentos**. |
| `PASTA_ARQUIVOS` | Pasta raiz dos arquivos/documentos dos clientes, navegável em **/arquivos**. |
| `PASTA_CLIENTES` | Pasta onde estão os PDFs de CNPJ/QSA (cartão CNPJ e quadro de sócios) usados para alimentar o módulo **/empresas** via `indexar_empresas.py`. |
| `PASTA_BACKUP` | Pasta de destino do backup (usada pelo `scripts\backup.bat` via Robocopy). |
| `SCRIPT_BACKUP` / `LOG_BACKUP` | Script de backup e arquivo de log lido pela tela **/backup**. |
| `SCRIPT_REINICIAR` | Script chamado por **/servidor/reiniciar** para reiniciar o servidor Windows. |
| `SCRIPT_REINICIAR_SITE` | Script chamado por **/servidor/reiniciar-site** para reiniciar apenas a aplicação Flask. |
| `PASTA_UPLOAD_PDDE` / `PASTA_SAIDA_PDDE` | Pastas de upload (extratos PDF) e de saída (planilhas geradas) do módulo **/pdde**. |
| `PLANO_CONTAS_PDDE` | Caminho do PDF do plano de contas de referência, consultado em **/pdde/plano_de_contas**. |
| `MODELO_IMPORTACAO_CONTMATIC` | Caminho do modelo `.xlsx` usado como base para gerar a planilha de importação no Contmatic. |
| `PASTA_UPLOAD_PDF` / `PASTA_SAIDA_PDF` | Pastas de upload e saída do módulo de **OCR**. |

> As pastas indicadas em `config.json` (e as subpastas de `uploads/` e `saida/`) são criadas automaticamente pelo `app.py` na inicialização, caso ainda não existam — exceto `PASTA_BACKUP`, que deve existir previamente para o backup funcionar.

As pastas em `exemplos/` (`arquivos`, `clientes`, `procedimentos`) são **apenas exemplos/placeholders** para o sistema funcionar logo após a instalação. Em produção, aponte cada chave do `config.json` para as pastas reais do escritório (por exemplo, `D:\Escritorio\Clientes`).

### 4. Estrutura esperada em `PASTA_CLIENTES`

Para que `indexar_empresas.py` consiga extrair os dados automaticamente, cada empresa deve ter, dentro de sua pasta, os PDFs oficiais da Receita Federal (cartão CNPJ e quadro de sócios/QSA). O script identifica CNPJ, razão social, endereço, situação cadastral e sócios a partir do texto desses PDFs.

### 5. Iniciando a aplicação

Depois de configurado, inicie o sistema com:

```bash
scripts\iniciar_sistema.bat
```

Esse script ativa o ambiente virtual e executa `python app.py`, que sobe o servidor (via `waitress`) acessível pela rede interna do escritório.

Para reiniciar o sistema (encerrando o processo Python e iniciando novamente), use:

```bash
scripts\reiniciar_sistema.bat
```

O mesmo pode ser feito diretamente pela interface, na tela **Servidor** (`/servidor`), mediante confirmação com a `SENHA_ADMIN`.

### 6. Configurando o backup

O backup é feito via `robocopy`, copiando o conteúdo de `PASTA_ARQUIVOS` para `PASTA_BACKUP` (configuradas em `config.json`). Pode ser disparado:

- Manualmente, executando `scripts\backup.bat`;
- Pela interface, na tela **Backup** (`/backup`), que também exibe o conteúdo do `LOG_BACKUP`.

Recomenda-se agendar `scripts\backup.bat` no **Agendador de Tarefas do Windows** para rodar periodicamente (ex.: diariamente fora do horário comercial).

## Primeiro acesso

1. Acesse `http://<endereço-do-servidor>:<porta>/login`.
2. Informe a senha definida em `SENHA_SITE`.
3. Funcionalidades administrativas (reiniciar servidor/aplicação) pedirão a `SENHA_ADMIN` adicionalmente.

## Segurança

- Todas as rotas, exceto `/login` e arquivos estáticos, exigem sessão autenticada (`@app.before_request`).
- O acesso a arquivos (`/arquivos`, procedimentos, uploads) é restrito à pasta configurada através de uma validação de caminho (`caminho_seguro`) que impede acessar diretórios fora da pasta base (proteção contra path traversal).
- Como o sistema expõe ações que afetam o servidor físico (reinício, leitura de uso de disco/CPU), o acesso à intranet deve ficar restrito à **rede interna** do escritório (não exponha esse sistema diretamente à internet sem um proxy/VPN com autenticação adicional).

## Licença

Este projeto é distribuído sob a licença **MIT** — veja o arquivo [LICENSE](LICENSE) para mais detalhes.