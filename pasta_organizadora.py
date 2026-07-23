# -*- coding: utf-8 -*-
"""
Lógica da funcionalidade "Pasta organizadora".

Este módulo é independente do app.py principal, mas reutiliza os helpers
que já existem lá (encontrar_pasta_dp_rh, nome_disponivel) para não duplicar
regras. Basta importar as funções que precisar em app.py (ver
pasta_organizadora_routes.py para o exemplo de uso).

Dependência nova necessária (adicionar ao requirements.txt):
    pdfplumber

Instalação:
    pip install pdfplumber
"""

import os
import re
import shutil
import unicodedata
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pdfplumber

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO
# ---------------------------------------------------------------------------

# Nomes das subpastas dentro de PASTA_ORGANIZADORA (pasta de "staging").
# OBS: no pedido original a subpasta de FGTS aparece grafada como "FTS" —
# assumi que é erro de digitação e usei "FGTS" para bater com o resto do
# sistema. Se preferir manter "FTS" no disco, troque só a constante abaixo.
SUBPASTA_DCTFWEB = "DCTFWEB"
SUBPASTA_FGTS = "FGTS"
SUBPASTA_DAS = "DAS-MENSAL"
SUBPASTA_CONSULTA = "Consulta-Notas"
SUBPASTA_CLIENTES = "Clientes"
SUBPASTA_APMS = "APMS"
SUBPASTA_LOGS = "logs"

SECOES = {
    "dctfweb": SUBPASTA_DCTFWEB,
    "fgts": SUBPASTA_FGTS,
    "das": SUBPASTA_DAS,
    "consulta": SUBPASTA_CONSULTA,
    "clientes": SUBPASTA_CLIENTES,
    "apms": SUBPASTA_APMS,
}

PASTAS_DP_RH = ["DP", "RH", "DP-RH", "RH-DP", "DPRH", "RHDP"]

# Pasta criada quando o cliente ainda não tem nenhuma das pastas
# RH/DP/RHDP/... — ajuste se preferir apenas logar erro em vez de criar.
PASTA_DP_RH_PADRAO = "DP-RH"

MESES = {
    "janeiro": "01",
    "fevereiro": "02",
    "marco": "03",
    "março": "03",
    "abril": "04",
    "maio": "05",
    "junho": "06",
    "julho": "07",
    "agosto": "08",
    "setembro": "09",
    "outubro": "10",
    "novembro": "11",
    "dezembro": "12",
}

ESTADO = {
    "ultima_organizacao": None,  # datetime
    "proxima_organizacao": None,  # datetime
    "rodando": False,
}
_estado_lock = threading.Lock()


# ---------------------------------------------------------------------------
# UTILITÁRIOS
# ---------------------------------------------------------------------------


def normalizar(texto: str) -> str:
    """minúsculas, sem acento, espaços colapsados — para comparação robusta."""
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def extrair_texto_pdf(caminho: Path) -> str:
    """Extrai todo o texto de um PDF. Retorna '' em caso de falha (ex.: PDF
    escaneado sem OCR)."""
    try:
        partes = []
        with pdfplumber.open(str(caminho)) as pdf:
            for pagina in pdf.pages:
                texto = pagina.extract_text() or ""
                partes.append(texto)
        return "\n".join(partes)
    except Exception:
        return ""


def nome_disponivel(pasta: Path, nome: str) -> Path:
    """Mesma regra do app.py: evita sobrescrever arquivo já existente."""
    pasta = Path(pasta)
    base, ext = os.path.splitext(nome)
    destino = pasta / nome
    contador = 1
    while destino.exists():
        destino = pasta / f"{base} ({contador}){ext}"
        contador += 1
    return destino


def encontrar_pasta_dp_rh(pasta_empresa: Path):
    for nome in PASTAS_DP_RH:
        candidata = pasta_empresa / nome
        if candidata.is_dir():
            return candidata
    return None


def listar_pastas_codigo_nome(pasta_base: Path):
    """Gera (pasta, codigo, nome) para cada subpasta '<codigo> - <nome>'."""
    if not pasta_base.is_dir():
        return
    for item in pasta_base.iterdir():
        if not item.is_dir():
            continue
        partes = item.name.split(" - ", 1)
        if len(partes) != 2:
            continue
        codigo, nome = partes
        yield item, codigo.strip(), nome.strip()


# ---------------------------------------------------------------------------
# IDENTIFICAÇÃO POR CONTEÚDO (DCTFWEB, FGTS, DAS-MENSAL, Consulta)
# ---------------------------------------------------------------------------


def encontrar_pasta_por_nome_no_texto(texto: str, pasta_base: Path):
    """Procura, dentro do texto extraído do PDF, o nome de algum
    cliente/APM cadastrado (comparação normalizada, sem acento/caixa)."""
    texto_norm = normalizar(texto)
    if not texto_norm:
        return None

    melhor_pasta = None
    melhor_tamanho = 0

    for pasta, _codigo, nome in listar_pastas_codigo_nome(pasta_base):
        nome_norm = normalizar(nome)
        if len(nome_norm) >= 4 and nome_norm in texto_norm:
            if len(nome_norm) > melhor_tamanho:
                melhor_pasta = pasta
                melhor_tamanho = len(nome_norm)

    return melhor_pasta


def extrair_periodo(texto: str):
    """Tenta descobrir (ano, mes) de apuração no texto do PDF.
    Retorna (ano, mes) como strings de 4 e 2 dígitos, ou (None, None)."""

    # Ex.: "PA:06/2026" (DARF/DCTFWEB)
    m = re.search(r"PA[:\s]+(\d{2})/(\d{4})", texto)
    if m:
        return m.group(2), m.group(1)

    # Ex.: "Competência 06/2026" (FGTS)
    m = re.search(r"Compet[êe]ncia\s+(\d{2})/(\d{4})", texto, re.IGNORECASE)
    if m:
        return m.group(2), m.group(1)

    # Ex.: "Período de Apuração Junho/2026" (DAS, DARF)
    m = re.search(
        r"Per[íi]odo de Apura[çc][ãa]o\D*?([A-Za-zçÇãÃ]+)\s*/\s*(\d{4})",
        texto,
        re.IGNORECASE,
    )
    if m:
        mes_nome = normalizar(m.group(1))
        mes_num = MESES.get(mes_nome)
        if mes_num:
            return m.group(2), mes_num

    # Ex.: "Período de Apuração 06/2026" (formato numérico)
    m = re.search(
        r"Per[íi]odo de Apura[çc][ãa]o\D*?(\d{2})/(\d{4})", texto, re.IGNORECASE
    )
    if m:
        return m.group(2), m.group(1)

    return None, None


# ---------------------------------------------------------------------------
# IDENTIFICAÇÃO POR NOME DE ARQUIVO (Clientes, APMS e Notas Fiscais "cruas")
# ---------------------------------------------------------------------------


def identificar_por_nome_arquivo(nome_arquivo: str, pasta_base: Path):
    """Procura, no INÍCIO do nome do arquivo, o código ou o nome de um
    cliente/APM. Retorna (pasta_destino, nome_sem_identificacao) ou
    (None, nome_arquivo) se não identificar.
    """
    nome_norm_completo = normalizar(nome_arquivo)

    melhor_pasta = None
    melhor_tamanho_removido = 0

    for pasta, codigo, nome in listar_pastas_codigo_nome(pasta_base):
        candidatos = []
        if codigo:
            candidatos.append(codigo)
        if nome:
            candidatos.append(nome)

        for candidato in candidatos:
            candidato_norm = normalizar(candidato)
            if not candidato_norm:
                continue
            if nome_norm_completo.startswith(candidato_norm):
                tamanho = len(candidato_norm)
                if tamanho > melhor_tamanho_removido:
                    melhor_tamanho_removido = tamanho
                    melhor_pasta = pasta

    if melhor_pasta is None:
        return None, nome_arquivo

    # remove a identificação do começo do nome (usando o comprimento real
    # do texto original, não o normalizado, para não perder caracteres)
    nome_restante = nome_arquivo[melhor_tamanho_removido:]
    nome_restante = re.sub(r"^[\s\-_\.]+", "", nome_restante)
    if not nome_restante:
        nome_restante = nome_arquivo

    return melhor_pasta, nome_restante


# ---------------------------------------------------------------------------
# MOVIMENTAÇÃO + LOG
# ---------------------------------------------------------------------------


def mover_arquivo(origem: Path, pasta_destino: Path, novo_nome: str = None) -> Path:
    pasta_destino.mkdir(parents=True, exist_ok=True)
    nome_final = novo_nome or origem.name
    destino = nome_disponivel(pasta_destino, nome_final)
    shutil.move(str(origem), str(destino))
    return destino


def _log(linhas, mensagem):
    linhas.append(f"[{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}] {mensagem}")


# ---------------------------------------------------------------------------
# ORGANIZADORES POR TIPO
# ---------------------------------------------------------------------------


def _organizar_dctfweb_fgts(
    pasta_organizadora: Path, pasta_clientes: Path, subpasta_guia: str, linhas_log
):
    origem = pasta_organizadora / subpasta_guia
    if not origem.is_dir():
        return

    for arquivo in list(origem.iterdir()):
        if not arquivo.is_file() or arquivo.suffix.lower() != ".pdf":
            continue

        texto = extrair_texto_pdf(arquivo)
        pasta_cliente = encontrar_pasta_por_nome_no_texto(texto, pasta_clientes)
        if pasta_cliente is None:
            _log(
                linhas_log,
                f"ERRO: cliente não identificado para '{arquivo.name}' ({subpasta_guia})",
            )
            continue

        ano, mes = extrair_periodo(texto)
        if not ano:
            _log(
                linhas_log,
                f"ERRO: período de apuração não identificado para '{arquivo.name}' ({subpasta_guia})",
            )
            continue
        anomes = f"{ano}{mes}"

        pasta_dp_rh = encontrar_pasta_dp_rh(pasta_cliente)
        if pasta_dp_rh is None:
            pasta_dp_rh = pasta_cliente / PASTA_DP_RH_PADRAO
            pasta_dp_rh.mkdir(parents=True, exist_ok=True)
            _log(
                linhas_log,
                f"AVISO: pasta RH/DP não existia para '{pasta_cliente.name}', criada '{PASTA_DP_RH_PADRAO}'",
            )

        destino_pasta = pasta_dp_rh / ano / anomes / subpasta_guia
        destino = mover_arquivo(arquivo, destino_pasta)
        _log(linhas_log, f"MOVIDO: '{arquivo.name}' -> '{destino}'")


def organizar_dctfweb(pasta_organizadora: Path, pasta_clientes: Path, linhas_log):
    _organizar_dctfweb_fgts(
        pasta_organizadora, pasta_clientes, SUBPASTA_DCTFWEB, linhas_log
    )


def organizar_fgts(pasta_organizadora: Path, pasta_clientes: Path, linhas_log):
    _organizar_dctfweb_fgts(
        pasta_organizadora, pasta_clientes, SUBPASTA_FGTS, linhas_log
    )


def organizar_das(pasta_organizadora: Path, pasta_clientes: Path, linhas_log):
    origem = pasta_organizadora / SUBPASTA_DAS
    if not origem.is_dir():
        return

    for arquivo in list(origem.iterdir()):
        if not arquivo.is_file() or arquivo.suffix.lower() != ".pdf":
            continue

        texto = extrair_texto_pdf(arquivo)
        pasta_cliente = encontrar_pasta_por_nome_no_texto(texto, pasta_clientes)
        if pasta_cliente is None:
            _log(
                linhas_log,
                f"ERRO: cliente não identificado para '{arquivo.name}' (DAS-MENSAL)",
            )
            continue

        ano, _mes = extrair_periodo(texto)
        if not ano:
            _log(
                linhas_log,
                f"ERRO: período de apuração não identificado para '{arquivo.name}' (DAS-MENSAL)",
            )
            continue

        destino_pasta = pasta_cliente / "Fiscal" / "DAS" / ano
        destino = mover_arquivo(arquivo, destino_pasta)
        _log(linhas_log, f"MOVIDO: '{arquivo.name}' -> '{destino}'")


def organizar_consulta_notas(pasta_organizadora: Path, pasta_apms: Path, linhas_log):
    origem = pasta_organizadora / SUBPASTA_CONSULTA
    if not origem.is_dir():
        return

    for arquivo in list(origem.iterdir()):
        if not arquivo.is_file():
            continue

        texto = ""
        if arquivo.suffix.lower() == ".pdf":
            texto = extrair_texto_pdf(arquivo)

        apm_pasta = None
        novo_nome = arquivo.name

        # "Consulta de NF": identificado pelo conteúdo (Tomador de Serviços)
        if texto and "tomador de servi" in normalizar(texto):
            apm_pasta = encontrar_pasta_por_nome_no_texto(texto, pasta_apms)
        else:
            # Nota fiscal "crua": identificado pelo início do nome do arquivo
            apm_pasta, novo_nome = identificar_por_nome_arquivo(
                arquivo.name, pasta_apms
            )

        if apm_pasta is None:
            _log(
                linhas_log,
                f"ERRO: APM não identificada para '{arquivo.name}' (Consulta/Notas)",
            )
            continue

        destino_pasta = apm_pasta / "Fiscal" / "Notas Fiscais"
        destino = mover_arquivo(arquivo, destino_pasta, novo_nome)
        _log(linhas_log, f"MOVIDO: '{arquivo.name}' -> '{destino}'")


def organizar_por_prefixo(
    pasta_organizadora: Path, subpasta: str, pasta_base: Path, linhas_log
):
    """Usado para as seções Clientes e APMS: o arquivo vai para a raiz da
    pasta do cliente/APM identificado pelo início do nome."""
    origem = pasta_organizadora / subpasta
    if not origem.is_dir():
        return

    for arquivo in list(origem.iterdir()):
        if not arquivo.is_file():
            continue

        pasta_destino, novo_nome = identificar_por_nome_arquivo(
            arquivo.name, pasta_base
        )
        if pasta_destino is None:
            _log(
                linhas_log, f"ERRO: não identificado para '{arquivo.name}' ({subpasta})"
            )
            continue

        destino = mover_arquivo(arquivo, pasta_destino, novo_nome)
        _log(linhas_log, f"MOVIDO: '{arquivo.name}' -> '{destino}'")


# ---------------------------------------------------------------------------
# ORQUESTRAÇÃO GERAL + AGENDADOR
# ---------------------------------------------------------------------------


def organizar_tudo(pasta_organizadora, pasta_clientes, pasta_apms, pasta_logs):
    """Roda todos os organizadores. Grava um log em .txt só se algo foi
    movido (ou algum erro ocorreu). Retorna as linhas do log."""

    pasta_organizadora = Path(pasta_organizadora)
    pasta_clientes = Path(pasta_clientes)
    pasta_apms = Path(pasta_apms)
    pasta_logs = Path(pasta_logs)

    linhas_log = []

    organizar_dctfweb(pasta_organizadora, pasta_clientes, linhas_log)
    organizar_fgts(pasta_organizadora, pasta_clientes, linhas_log)
    organizar_das(pasta_organizadora, pasta_clientes, linhas_log)
    organizar_consulta_notas(pasta_organizadora, pasta_apms, linhas_log)
    organizar_por_prefixo(
        pasta_organizadora, SUBPASTA_CLIENTES, pasta_clientes, linhas_log
    )
    organizar_por_prefixo(pasta_organizadora, SUBPASTA_APMS, pasta_apms, linhas_log)

    if linhas_log:
        pasta_logs.mkdir(parents=True, exist_ok=True)
        nome_log = datetime.now().strftime("%Y-%m-%d_%H-%M") + ".txt"
        with open(pasta_logs / nome_log, "w", encoding="utf-8") as f:
            f.write("\n".join(linhas_log) + "\n")

    return linhas_log


def _ciclo_agendador(
    pasta_organizadora, pasta_clientes, pasta_apms, pasta_logs, intervalo_segundos=1200
):
    while True:
        with _estado_lock:
            ESTADO["rodando"] = True
        try:
            organizar_tudo(pasta_organizadora, pasta_clientes, pasta_apms, pasta_logs)
        except Exception:
            pass
        finally:
            agora = datetime.now()
            with _estado_lock:
                ESTADO["rodando"] = False
                ESTADO["ultima_organizacao"] = agora
                ESTADO["proxima_organizacao"] = agora + timedelta(
                    seconds=intervalo_segundos
                )
        time.sleep(intervalo_segundos)


def iniciar_agendador(
    pasta_organizadora, pasta_clientes, pasta_apms, pasta_logs, intervalo_segundos=1200
):
    """Inicia a thread que organiza a pasta a cada `intervalo_segundos`
    (padrão: 20 minutos). Chamar uma única vez, na inicialização do app."""
    with _estado_lock:
        ESTADO["proxima_organizacao"] = datetime.now() + timedelta(
            seconds=intervalo_segundos
        )

    thread = threading.Thread(
        target=_ciclo_agendador,
        args=(
            pasta_organizadora,
            pasta_clientes,
            pasta_apms,
            pasta_logs,
            intervalo_segundos,
        ),
        daemon=True,
    )
    thread.start()
    return thread


def obter_estado():
    with _estado_lock:
        return dict(ESTADO)
