import psutil
import time
import os
import json
import sqlite3
import subprocess
import re
import requests
import uuid
import ocrmypdf
import pandas as pd
import threading
import hmac
import socket
import pasta_organizadora as po
import calendar
from flask import (
    Flask,
    render_template,
    jsonify,
    request,
    send_file,
    send_from_directory,
    flash,
    redirect,
    abort,
    Blueprint,
    session,
    url_for,
)
from banco import criar_tabelas, apagar_tabelas
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from pathlib import Path
from werkzeug.utils import secure_filename
from urllib.parse import quote, urlparse
from pdde_importador import gerar_planilha_importacao, gerar_planilha_manual_pdde
from functools import wraps
from waitress import serve

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv(*args, **kwargs):
        return False


BASE_DIR = Path(__file__).resolve().parent
BANCO_PATH = str(BASE_DIR / "banco.db")

load_dotenv(dotenv_path=BASE_DIR / ".env")

app = Flask(__name__)
BOOT_TIME = psutil.boot_time()

trello_bp = Blueprint("trello", __name__)
pasta_organizadora_bp = Blueprint("pasta_organizadora", __name__)

app.secret_key = os.getenv("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError(
        "SECRET_KEY não definida no ambiente. Verifique se o arquivo .env "
        f"existe em: {BASE_DIR / '.env'}"
    )

SENHA_SITE = os.getenv("SENHA_SITE")
SENHA_ADMIN = os.getenv("SENHA_ADMIN")

TRELLO_API_BASE = "https://api.trello.com/1"

TRELLO_API_KEY = os.environ.get("TRELLO_API_KEY", "")
TRELLO_TOKEN = os.environ.get("TRELLO_TOKEN", "")
TRELLO_BOARD_ID = os.environ.get("TRELLO_BOARD_ID", "")

if not (TRELLO_API_KEY and TRELLO_TOKEN and TRELLO_BOARD_ID):
    print(
        "[AVISO] Credenciais do Trello não encontradas no ambiente. "
        f"Verifique se o arquivo .env existe em: {BASE_DIR / '.env'}"
    )


def _auth_params():
    return {"key": TRELLO_API_KEY, "token": TRELLO_TOKEN}


_CONFIG = {
    "PASTA_ORGANIZADORA": None,
    "PASTA_CLIENTES": None,
    "PASTA_APMS": None,
}

with open(BASE_DIR / "config.json", "r", encoding="utf-8") as arquivo:
    config = json.load(arquivo)

NOME_ESCRITÓRIO = config["NOME_ESCRITÓRIO"]
FAVICON_ARQUIVO = config.get("FAVICON_ARQUIVO", "static/favicon.ico")
FAVICON_VERSAO = config["FAVICON_VERSAO"]

PASTAS_PROCEDIMENTOS = config["PASTAS_PROCEDIMENTOS"]
PASTA_ARQUIVOS = config["PASTA_ARQUIVOS"]
PASTA_CLIENTES = config["PASTA_CLIENTES"]
PASTA_APMS = config["PASTA_APMS"]

SCRIPT_BACKUP = config["SCRIPT_BACKUP"]
PASTA_BACKUP = config["PASTA_BACKUP"]
LOG_BACKUP = config["LOG_BACKUP"]
SCRIPT_REINICIAR = config["SCRIPT_REINICIAR"]
SCRIPT_REINICIAR_SITE = config["SCRIPT_REINICIAR_SITE"]

PASTA_UPLOAD_PDDE = config["PASTA_UPLOAD_PDDE"]
PASTA_SAIDA_PDDE = config["PASTA_SAIDA_PDDE"]
PLANO_CONTAS_PDDE = config["PLANO_CONTAS_PDDE"]
MODELO_IMPORTACAO_CONTMATIC = config["MODELO_IMPORTACAO_CONTMATIC"]

PASTA_UPLOAD_PDF = config["PASTA_UPLOAD_PDF"]
PASTA_SAIDA_PDF = config["PASTA_SAIDA_PDF"]

PASTA_ORGANIZADORA = config["PASTA_ORGANIZADORA"]

NOME_TAREFA_REINICIAR_SITE = "ReiniciarSistemaInterno"

os.makedirs(PASTAS_PROCEDIMENTOS, exist_ok=True)
os.makedirs(PASTA_ARQUIVOS, exist_ok=True)
os.makedirs(PASTA_CLIENTES, exist_ok=True)
os.makedirs(PASTA_APMS, exist_ok=True)

os.makedirs(PASTA_UPLOAD_PDDE, exist_ok=True)
os.makedirs(PASTA_SAIDA_PDDE, exist_ok=True)

os.makedirs(PASTA_UPLOAD_PDF, exist_ok=True)
os.makedirs(PASTA_SAIDA_PDF, exist_ok=True)

criar_tabelas()

PASTAS_DP_RH = ["DP", "RH", "DP-RH", "RH-DP", "DPRH", "RHDP"]

backup_estado = {
    "rodando": False,
    "inicio": None,
    "ultima_saida": "",
    "ultimo_erro": None,
}
backup_lock = threading.Lock()

tarefas_ocr = {}
tarefas_ocr_lock = threading.Lock()
TAREFA_OCR_TTL_SEGUNDOS = 3600 * 6  # 6 horas

RECORRENCIAS_MESES = {
    "nenhuma": None,
    "mensal": 1,
    "bimestral": 2,
    "trimestral": 3,
    "semestral": 6,
    "anual": 12,
}

script_estado = {
    "rodando": False,
    "ultima_saida": "",
    "ultimo_erro": None,
}
script_lock = threading.Lock()


def requer_admin(func):
    @wraps(func)
    def decorado(*args, **kwargs):
        if not session.get("config_admin_ok"):
            return redirect("/configuracoes")
        return func(*args, **kwargs)

    return decorado


def proxima_segura(proxima, padrao="/"):
    """Só aceita caminhos relativos internos. Bloqueia URLs absolutas ou // (protocol-relative)."""
    if not proxima:
        return padrao

    url = urlparse(proxima)

    # Se tem scheme (http, https, javascript, etc.) ou netloc (domínio), é externo -> rejeita
    if url.scheme or url.netloc:
        return padrao

    # Bloqueia "//evil.com" (o navegador trata como protocol-relative URL)
    if proxima.startswith("//"):
        return padrao

    return proxima


def listar_tabelas_banco():
    """Lista as tabelas de usuário do banco.db, com a contagem de linhas de cada uma."""
    conn = sqlite3.connect(BANCO_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    nomes = [linha[0] for linha in cursor.fetchall()]

    tabelas = []
    for nome in nomes:
        cursor.execute(f'SELECT COUNT(*) FROM "{nome}"')
        total = cursor.fetchone()[0]
        tabelas.append({"nome": nome, "total": total})

    conn.close()
    return tabelas


def get_last_backup_info():
    """Encontra o arquivo mais recente na pasta de backups."""
    try:
        return {
            "arquivo": os.path.basename(LOG_BACKUP),
            "timestamp": os.path.getmtime(LOG_BACKUP),
        }
    except FileNotFoundError:
        return None


def obter_ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # não envia pacote nenhum, só força o SO a escolher uma rota/interface
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def executar_script_empresa_thread(codigo_empresa=None):
    with script_lock:
        if script_estado["rodando"]:
            return
        script_estado["rodando"] = True
        script_estado["ultimo_erro"] = None

    try:
        comando = ["python", "indexar_empresas.py"]
        if codigo_empresa:
            comando.append(codigo_empresa)

        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        script_estado["ultima_saida"] = resultado.stdout or resultado.stderr

        if resultado.returncode != 0:
            script_estado["ultimo_erro"] = (
                f"Script retornou código {resultado.returncode}."
            )

    except Exception as e:
        script_estado["ultimo_erro"] = str(e)

    finally:
        script_estado["rodando"] = False


def encontrar_pasta_dp_rh(pasta_empresa: Path) -> Path | None:
    for nome in PASTAS_DP_RH:
        candidata = pasta_empresa / nome
        if candidata.is_dir():
            return candidata
    return None


def pdf_dctfweb_fgts(
    pasta_empresa: Path, ano: str, anomes: str, subpasta_guia: str
) -> Path | None:
    """Retorna o caminho do primeiro PDF encontrado, ou None."""
    pasta_dp_rh = encontrar_pasta_dp_rh(pasta_empresa)
    if pasta_dp_rh is None:
        return None

    pasta_guia = pasta_dp_rh / ano / anomes / subpasta_guia
    if not pasta_guia.is_dir():
        return None

    for arquivo in pasta_guia.iterdir():
        if arquivo.is_file() and arquivo.suffix.lower() == ".pdf":
            return arquivo
    return None


def pdf_das_mensal(pasta_empresa: Path, ano: str, anomes: str) -> Path | None:
    pasta_das = pasta_empresa / "Fiscal" / "DAS" / ano
    if not pasta_das.is_dir():
        return None

    for arquivo in pasta_das.iterdir():
        if (
            arquivo.is_file()
            and arquivo.suffix.lower() == ".pdf"
            and anomes in arquivo.name
        ):
            return arquivo
    return None


def encontrar_pasta_empresa(codigo: str) -> Path | None:
    """Localiza a pasta da empresa a partir do código."""
    for empresa_dir in Path(PASTA_CLIENTES).iterdir():
        if empresa_dir.is_dir() and empresa_dir.name.startswith(f"{codigo} - "):
            return empresa_dir
    return None


def ler_certificados_windows():
    comando = r"""
        $certs = Get-ChildItem Cert:\CurrentUser\My |
        Select-Object Subject, Issuer, NotAfter, Thumbprint

        @($certs) | ConvertTo-Json -Compress
        """
    resultado = subprocess.run(
        ["powershell", "-NoProfile", "-Command", comando],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    if resultado.returncode != 0:
        return []

    saida = resultado.stdout.strip()

    if not saida:
        return []

    dados = json.loads(saida)

    if isinstance(dados, dict):
        dados = [dados]

    certificados = []
    hoje = datetime.now()

    def extrair_empresa_cnpj(subject):
        match = re.search(r"CN=([^,]+)", subject)

        if not match:
            return subject, ""

        cn = match.group(1).strip()

        if ":" in cn:
            empresa, cnpj = cn.rsplit(":", 1)
            return empresa.strip(), formatar_cnpj(cnpj.strip())

        return cn, ""

    def formatar_cnpj(cnpj):
        numeros = re.sub(r"\D", "", cnpj)

        if len(numeros) == 14:
            return f"{numeros[:2]}.{numeros[2:5]}.{numeros[5:8]}/{numeros[8:12]}-{numeros[12:]}"

        return cnpj

    for c in dados:
        timestamp = int(re.search(r"\d+", c["NotAfter"]).group())
        vencimento = datetime.fromtimestamp(timestamp / 1000)
        dias = (vencimento.date() - hoje.date()).days

        if dias < 0:
            status = "Vencido"
        elif dias <= 7:
            status = "Vence em até 7 dias"
        elif dias <= 30:
            status = "Vence em até 30 dias"
        else:
            status = "OK"

        empresa, cnpj = extrair_empresa_cnpj(c["Subject"])

        certificados.append(
            {
                "empresa": empresa,
                "cnpj": cnpj,
                "vencimento": vencimento.strftime("%d/%m/%Y"),
                "dias": dias,
                "status": status,
                "thumbprint": c["Thumbprint"],
            }
        )

    certificados.sort(key=lambda x: x["dias"])

    return certificados


def definir_categoria(nome):
    nome = nome.lower()

    categorias = {
        "Departamento Pessoal": [
            "folha",
            "férias",
            "ferias",
            "rescisao",
            "rescisão",
            "admissão",
            "admissao",
            "advertencia",
            "advertência",
            "sindicais",
            "pro-labore",
            "pró-labore",
            "fgts",
            "inss",
            "esocial",
            "dirf",
            "salário",
            "salario",
        ],
        "Fiscal": [
            "notas",
            "nota",
            "fiscal",
            "nf-e",
            "nf",
            "nfe",
            "icms",
            "iss",
            "ipi",
            "simples",
            "pis",
            "cofins",
            "das",
        ],
        "Contábil": [
            "contábil",
            "contabil",
            "balanço",
            "balanco",
            "demonstração",
            "demonstracao",
            "lucros",
            "prejuízos",
            "escrituração",
            "escrituracao",
            "dre",
            "ecd",
            "ecf",
        ],
        "Legalização": [
            "abertura",
            "empresa",
            "fechamento",
            "alteração",
            "contrato social",
            "capa de contrato",
            "capa de contrato social",
            "capa contrato social",
            "cnpj",
            "viabilidade",
        ],
        "TI": [
            "ti",
            "internet",
            "intranet",
            "conexão",
            "conectar",
        ],
        "Geral": ["whatsapp", "texto"],
    }

    for categoria, palavras in categorias.items():
        for palavra in palavras:
            if palavra in nome:
                return categoria

    return "Outros"


def caminho_seguro(base, caminho_relativo=""):
    """Monta caminho dentro da pasta base e impede sair dela com .. ou caminho absoluto."""
    base_abs = os.path.abspath(base)
    destino = os.path.abspath(os.path.join(base_abs, caminho_relativo or ""))

    try:
        comum = os.path.commonpath([base_abs, destino])
    except ValueError:
        abort(403)

    if comum != base_abs:
        abort(403)

    return destino


def nome_disponivel(pasta, nome):
    base, ext = os.path.splitext(nome)
    destino = os.path.join(pasta, nome)
    contador = 1

    while os.path.exists(destino):
        nome = f"{base} ({contador}){ext}"
        destino = os.path.join(pasta, nome)
        contador += 1

    return destino


def calcular_total_horas(inicio, fim):
    h_inicio = datetime.strptime(inicio, "%H:%M")
    h_fim = datetime.strptime(fim, "%H:%M")

    diferenca = h_fim - h_inicio

    if diferenca.total_seconds() < 0:
        diferenca = diferenca + timedelta(days=1)

    return round(diferenca.total_seconds() / 3600, 2)


def _dia_valido_no_mes(ano, mes, dia):
    """Evita erro em fevereiro etc: se o dia não existe no mês, usa o último dia válido."""
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    return min(dia, ultimo_dia)


def calcular_ocorrencia_no_mes(data_evento_str, recorrencia, ano, mes):
    """Retorna o dia (int) em que o evento cai no ano/mes informado, ou None se não ocorrer."""
    data_evento = datetime.strptime(data_evento_str, "%Y-%m-%d").date()

    if recorrencia == "nenhuma":
        if data_evento.year == ano and data_evento.month == mes:
            return data_evento.day
        return None

    intervalo = RECORRENCIAS_MESES.get(recorrencia)
    if not intervalo:
        return None

    if (ano, mes) < (data_evento.year, data_evento.month):
        return None

    diff_meses = (ano - data_evento.year) * 12 + (mes - data_evento.month)
    if diff_meses % intervalo != 0:
        return None

    return _dia_valido_no_mes(ano, mes, data_evento.day)


def _limpar_tarefas_ocr_antigas():
    """Remove tarefas concluídas/com erro há mais de TAREFA_OCR_TTL_SEGUNDOS."""
    agora = time.time()
    with tarefas_ocr_lock:
        expiradas = [
            id_
            for id_, tarefa in tarefas_ocr.items()
            if tarefa.get("status") in ("concluido", "erro")
            and (agora - tarefa.get("criado_em", agora)) > TAREFA_OCR_TTL_SEGUNDOS
        ]
        for id_ in expiradas:
            tarefa = tarefas_ocr.pop(id_)
            arquivo = tarefa.get("arquivo")
            if arquivo and os.path.exists(arquivo):
                try:
                    os.remove(arquivo)
                except OSError:
                    pass


def executar_ocr(id_execucao, entrada, saida, nome_original):
    try:
        ocrmypdf.ocr(entrada, saida, language="por", deskew=True)
        with tarefas_ocr_lock:
            tarefas_ocr[id_execucao] = {
                "status": "concluido",
                "arquivo": saida,
                "nome": nome_original,
                "criado_em": time.time(),
            }
    except Exception as e:
        with tarefas_ocr_lock:
            tarefas_ocr[id_execucao] = {
                "status": "erro",
                "erro": str(e),
                "criado_em": time.time(),
            }
    finally:
        # remove o PDF original enviado (não precisa mais dele)
        if os.path.exists(entrada):
            try:
                os.remove(entrada)
            except OSError:
                pass
        _limpar_tarefas_ocr_antigas()


def init_pasta_organizadora(pasta_organizadora, pasta_clientes, pasta_apms):
    """Chame isso no app.py, passando os mesmos caminhos já usados lá
    (PASTA_ORGANIZADORA, PASTA_CLIENTES, PASTA_APMS)."""
    _CONFIG["PASTA_ORGANIZADORA"] = Path(pasta_organizadora)
    _CONFIG["PASTA_CLIENTES"] = Path(pasta_clientes)
    _CONFIG["PASTA_APMS"] = Path(pasta_apms)

    for sub in po.SECOES.values():
        (_CONFIG["PASTA_ORGANIZADORA"] / sub).mkdir(parents=True, exist_ok=True)
    (_CONFIG["PASTA_ORGANIZADORA"] / po.SUBPASTA_LOGS).mkdir(
        parents=True, exist_ok=True
    )


def _garantir_config():
    """Rede de segurança: se init_pasta_organizadora(...) não foi chamado
    antes da primeira requisição, dá um erro claro em vez do
    TypeError críptico de 'NoneType / str'.

    Causas mais comuns:
      1) a chamada a init_pasta_organizadora(...) foi esquecida no app.py;
      2) ela foi colocada DENTRO do bloco `if __name__ == "__main__":` —
         isso só roda quando você executa `python app.py` diretamente, e
         NÃO roda se o site for servido via waitress/gunicorn ou via o
         processo "principal" do reloader do Flask em debug=True.

    A chamada deve ficar no nível do módulo (mesma indentação de
    `PASTA_ORGANIZADORA = config["PASTA_ORGANIZADORA"]`), fora de
    qualquer `if __name__`.
    """
    if _CONFIG["PASTA_ORGANIZADORA"] is not None:
        return

    abort(
        500,
        "Pasta organizadora não inicializada: chame "
        "init_pasta_organizadora(PASTA_ORGANIZADORA, PASTA_CLIENTES, PASTA_APMS) "
        "no nível do módulo do app.py (fora do `if __name__ == '__main__':`), "
        "antes de qualquer requisição.",
    )


def iniciar_agendador_app(intervalo_segundos=1200):
    """Inicia a thread de auto-organização a cada 20 minutos (1200s)."""
    if _CONFIG["PASTA_ORGANIZADORA"] is None:
        raise RuntimeError(
            "Chame init_pasta_organizadora(...) antes de iniciar o agendador."
        )

    po.iniciar_agendador(
        _CONFIG["PASTA_ORGANIZADORA"],
        _CONFIG["PASTA_CLIENTES"],
        _CONFIG["PASTA_APMS"],
        _CONFIG["PASTA_ORGANIZADORA"] / po.SUBPASTA_LOGS,
        intervalo_segundos=intervalo_segundos,
    )


def _pasta_secao(secao: str) -> Path:
    if secao not in po.SECOES:
        abort(404, "Seção inválida")
    return _CONFIG["PASTA_ORGANIZADORA"] / po.SECOES[secao]


def _listar_arquivos(pasta: Path):
    if not pasta.is_dir():
        return []
    itens = [a.name for a in pasta.iterdir() if a.is_file()]
    return sorted(itens, key=str.lower)


def _formatar_data(dt):
    if not dt:
        return None
    return dt.strftime("%d/%m/%Y %H:%M")


def executar_backup_thread():
    with backup_lock:
        if backup_estado["rodando"]:
            return
        backup_estado["rodando"] = True
        backup_estado["inicio"] = time.time()
        backup_estado["ultimo_erro"] = None

    try:
        resultado = subprocess.run(
            [SCRIPT_BACKUP],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            shell=True,
        )
        backup_estado["ultima_saida"] = resultado.stdout or resultado.stderr

        # robocopy: códigos 0-7 são sucesso, 8+ é erro real
        if resultado.returncode >= 8:
            backup_estado["ultimo_erro"] = (
                f"Robocopy retornou código {resultado.returncode} (falha)."
            )

    except Exception as e:
        backup_estado["ultimo_erro"] = str(e)

    finally:
        backup_estado["rodando"] = False


def ler_log_backup(linhas=50):
    """Lê as últimas N linhas do arquivo de log de backup."""
    try:
        with open(LOG_BACKUP, "r", encoding="utf-8", errors="ignore") as f:
            todas_linhas = f.readlines()
        return "".join(todas_linhas[-linhas:])
    except FileNotFoundError:
        return ""


def senha_valida(senha):
    """Compara a senha enviada com a senha de admin, sem sobra pra timing attack."""
    if not SENHA_ADMIN or not senha:
        return False
    return hmac.compare_digest(str(senha), str(SENHA_ADMIN))


def listar_discos():
    """Lista todos os discos/partições reais do servidor com uso de espaço."""
    discos = []

    for particao in psutil.disk_partitions(all=False):
        if "cdrom" in particao.opts.lower() or not particao.fstype:
            continue

        try:
            uso = psutil.disk_usage(particao.mountpoint)
        except (PermissionError, FileNotFoundError, OSError):
            continue

        discos.append(
            {
                "dispositivo": particao.device,
                "ponto_montagem": particao.mountpoint,
                "sistema_arquivos": particao.fstype,
                "total_gb": round(uso.total / (1024**3), 1),
                "usado_gb": round(uso.used / (1024**3), 1),
                "livre_gb": round(uso.free / (1024**3), 1),
                "percentual": uso.percent,
            }
        )

    return discos


def salvar_config():
    with open(BASE_DIR / "config.json", "w", encoding="utf-8") as arquivo:
        json.dump(config, arquivo, ensure_ascii=False, indent=4)


def tarefa_agendada_existe(nome_tarefa):
    """Verifica se existe uma tarefa agendada com esse nome no Agendador de Tarefas do Windows."""
    resultado = subprocess.run(
        ["schtasks", "/query", "/tn", nome_tarefa],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    return resultado.returncode == 0


@app.before_request
def exigir_login_site():

    print(f"[{datetime.now():%H:%M:%S}] {request.remote_addr} -> {request.path}\n")

    rotas_publicas = {"login", "static"}

    if request.endpoint in rotas_publicas or request.endpoint is None:
        return

    if not session.get("site_ok"):
        return redirect(url_for("login", proxima=request.path))


@app.route("/")
def index():
    return render_template("index.html")


@app.context_processor
def injetar_config_global():
    return {
        "favicon_arquivo": config.get("FAVICON_ARQUIVO", "favicon.ico"),
        "favicon_versao": config.get("FAVICON_VERSAO", "1"),
        "nome_escritorio": config.get("NOME_ESCRITÓRIO", ""),
    }


@app.template_filter("data_br")
def data_br(valor):
    """Converte data no formato YYYY-MM-DD para DD/MM/AAAA"""
    if not valor:
        return ""
    try:
        return datetime.strptime(valor, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return valor


@app.route("/api/health")
def health():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disco = psutil.disk_usage("D:\\")
    backup = get_last_backup_info()

    return jsonify(
        {
            "cpu_percent": cpu,
            "mem_percent": mem.percent,
            "disco_percent": disco.percent,
            "disco_usado_gb": round(disco.used / (1024**3), 1),
            "disco_total_gb": round(disco.total / (1024**3), 1),
            "uptime_segundos": int(time.time() - BOOT_TIME),
            "ultimo_backup_timestamp": backup["timestamp"] if backup else None,
            "ultimo_backup_arquivo": backup["arquivo"] if backup else None,
            "discos": listar_discos(),
        }
    )


@app.route("/api/eventos")
def api_eventos_listar():
    ano = request.args.get("ano", type=int)
    mes = request.args.get("mes", type=int)

    if not ano or not mes:
        agora = datetime.now()
        ano = ano or agora.year
        mes = mes or agora.month

    conn = sqlite3.connect(BANCO_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM eventos ORDER BY data")
    eventos = cursor.fetchall()
    conn.close()

    ocorrencias = []
    for evento in eventos:
        dia = calcular_ocorrencia_no_mes(
            evento["data"], evento["recorrencia"], ano, mes
        )
        if dia is not None:
            ocorrencias.append(
                {
                    "id": evento["id"],
                    "nome": evento["nome"],
                    "descricao": evento["descricao"] or "",
                    "cor": evento["cor"] or "#2f5d8a",
                    "recorrencia": evento["recorrencia"],
                    "data_original": evento["data"],
                    "dia": dia,
                    "data": f"{ano:04d}-{mes:02d}-{dia:02d}",
                }
            )

    return jsonify({"ano": ano, "mes": mes, "eventos": ocorrencias})


@app.route("/api/eventos", methods=["POST"])
def api_eventos_criar():
    dados = request.get_json(silent=True) or {}

    nome = (dados.get("nome") or "").strip()
    data = (dados.get("data") or "").strip()
    descricao = (dados.get("descricao") or "").strip()
    cor = (dados.get("cor") or "#2f5d8a").strip()
    recorrencia = (dados.get("recorrencia") or "nenhuma").strip()

    if not nome:
        return jsonify({"ok": False, "erro": "O nome do evento é obrigatório."}), 400
    if not data:
        return jsonify({"ok": False, "erro": "A data do evento é obrigatória."}), 400
    if recorrencia not in RECORRENCIAS_MESES:
        return jsonify({"ok": False, "erro": "Recorrência inválida."}), 400
    try:
        datetime.strptime(data, "%Y-%m-%d")
    except ValueError:
        return jsonify({"ok": False, "erro": "Data inválida."}), 400

    conn = sqlite3.connect(BANCO_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO eventos (nome, descricao, data, cor, recorrencia, criado_em)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            nome,
            descricao,
            data,
            cor,
            recorrencia,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    novo_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "id": novo_id})


@app.route("/api/eventos/<int:id>", methods=["PUT"])
def api_eventos_editar(id):
    dados = request.get_json(silent=True) or {}

    nome = (dados.get("nome") or "").strip()
    data = (dados.get("data") or "").strip()
    descricao = (dados.get("descricao") or "").strip()
    cor = (dados.get("cor") or "#2f5d8a").strip()
    recorrencia = (dados.get("recorrencia") or "nenhuma").strip()

    if not nome:
        return jsonify({"ok": False, "erro": "O nome do evento é obrigatório."}), 400
    if not data:
        return jsonify({"ok": False, "erro": "A data do evento é obrigatória."}), 400
    if recorrencia not in RECORRENCIAS_MESES:
        return jsonify({"ok": False, "erro": "Recorrência inválida."}), 400
    try:
        datetime.strptime(data, "%Y-%m-%d")
    except ValueError:
        return jsonify({"ok": False, "erro": "Data inválida."}), 400

    conn = sqlite3.connect(BANCO_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE eventos
        SET nome = ?, descricao = ?, data = ?, cor = ?, recorrencia = ?
        WHERE id = ?
        """,
        (nome, descricao, data, cor, recorrencia, id),
    )
    conn.commit()
    afetado = cursor.rowcount
    conn.close()

    if not afetado:
        return jsonify({"ok": False, "erro": "Evento não encontrado."}), 404

    return jsonify({"ok": True})


@app.route("/api/eventos/<int:id>", methods=["DELETE"])
def api_eventos_excluir(id):
    conn = sqlite3.connect(BANCO_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM eventos WHERE id = ?", (id,))
    conn.commit()
    afetado = cursor.rowcount
    conn.close()

    if not afetado:
        return jsonify({"ok": False, "erro": "Evento não encontrado."}), 404

    return jsonify({"ok": True})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        senha = request.form.get("senha", "")
        if SENHA_SITE and hmac.compare_digest(str(senha), str(SENHA_SITE)):
            session["site_ok"] = True
            proxima = proxima_segura(request.form.get("proxima"))
            return redirect(proxima)
        flash("Senha incorreta.", "erro")
        return redirect(url_for("login", proxima=request.form.get("proxima", "")))

    proxima = request.args.get("proxima", "/")
    return render_template("login.html", proxima=proxima)


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("config_admin_ok", None)
    session.pop("site_ok", None)
    return redirect(url_for("login"))


@app.route("/configuracoes/entrar", methods=["POST"])
def configuracoes_entrar():
    senha = request.form.get("senha", "")
    if senha_valida(senha):
        session["config_admin_ok"] = True
        flash("Acesso liberado.", "success")
    else:
        flash("Senha incorreta.", "erro")
    return redirect("/configuracoes")


@app.route("/configuracoes/sair", methods=["POST"])
def configuracoes_sair():
    session.pop("config_admin_ok", None)
    flash("Você saiu do painel de configurações.", "info")
    return redirect("/configuracoes")


@app.route("/configuracoes")
def configuracoes():
    if not session.get("config_admin_ok"):
        return render_template("configuracoes.html", autenticado=False)

    tabelas = listar_tabelas_banco()
    return render_template(
        "configuracoes.html", autenticado=True, config=config, tabelas=tabelas
    )


@app.route("/configuracoes/salvar-nome", methods=["POST"])
@requer_admin
def configuracoes_salvar_nome():
    global NOME_ESCRITÓRIO

    nome = request.form.get("nome_escritorio", "").strip()
    if not nome:
        flash("O nome do escritório não pode ficar vazio.", "erro")
        return redirect("/configuracoes")

    config["NOME_ESCRITÓRIO"] = nome
    NOME_ESCRITÓRIO = nome
    salvar_config()

    flash("Nome do escritório atualizado.", "success")
    return redirect("/configuracoes")


@app.route("/configuracoes/salvar-pastas", methods=["POST"])
@requer_admin
def configuracoes_salvar_pastas():
    global PASTAS_PROCEDIMENTOS, PASTA_ARQUIVOS, PASTA_CLIENTES
    global PASTA_APMS, PASTA_ORGANIZADORA, PASTA_BACKUP, LOG_BACKUP

    campos = {
        "PASTAS_PROCEDIMENTOS": request.form.get("pasta_procedimentos", "").strip(),
        "PASTA_ARQUIVOS": request.form.get("pasta_arquivos", "").strip(),
        "PASTA_CLIENTES": request.form.get("pasta_clientes", "").strip(),
        "PASTA_APMS": request.form.get("pasta_apms", "").strip(),
        "PASTA_ORGANIZADORA": request.form.get("pasta_organizadora", "").strip(),
        "PASTA_BACKUP": request.form.get("pasta_backup", "").strip(),
    }

    for chave, valor in campos.items():
        if not valor:
            flash(f"O campo '{chave}' não pode ficar vazio.", "erro")
            return redirect("/configuracoes")

    for chave, valor in campos.items():
        try:
            os.makedirs(valor, exist_ok=True)
        except OSError as e:
            flash(f"Não foi possível criar/acessar a pasta '{valor}': {e}", "erro")
            return redirect("/configuracoes")
        config[chave] = valor

    # arquivo de log é separado — pode ficar em disco diferente da pasta de backup
    novo_log = request.form.get("log_backup", "").strip()
    if novo_log:
        pasta_do_log = os.path.dirname(novo_log)
        try:
            os.makedirs(pasta_do_log, exist_ok=True)
        except OSError as e:
            flash(f"Não foi possível criar/acessar a pasta do log: {e}", "erro")
            return redirect("/configuracoes")
        config["LOG_BACKUP"] = novo_log

    PASTAS_PROCEDIMENTOS = config["PASTAS_PROCEDIMENTOS"]
    PASTA_ARQUIVOS = config["PASTA_ARQUIVOS"]
    PASTA_CLIENTES = config["PASTA_CLIENTES"]
    PASTA_APMS = config["PASTA_APMS"]
    PASTA_ORGANIZADORA = config["PASTA_ORGANIZADORA"]
    PASTA_BACKUP = config["PASTA_BACKUP"]
    LOG_BACKUP = config["LOG_BACKUP"]

    salvar_config()

    flash("Pastas atualizadas com sucesso.", "success")
    return redirect("/configuracoes")


@app.route("/configuracoes/favicon", methods=["POST"])
@requer_admin
def configuracoes_favicon():
    senha = request.form.get("senha", "")
    if not senha_valida(senha):
        flash("Senha incorreta.", "erro")
        return redirect("/configuracoes")

    arquivo = request.files.get("favicon")
    extensoes_permitidas = {".ico", ".png"}

    if not arquivo or not arquivo.filename:
        flash("Selecione um arquivo de favicon.", "erro")
        return redirect("/configuracoes")

    nome_seguro = secure_filename(arquivo.filename)
    ext = os.path.splitext(nome_seguro)[1].lower()

    if ext not in extensoes_permitidas:
        flash("Formato inválido. Use .ico ou .png", "erro")
        return redirect("/configuracoes")

    destino_nome = f"favicon{ext}"
    arquivo.save(os.path.join(app.static_folder, destino_nome))

    config["FAVICON_ARQUIVO"] = destino_nome
    config["FAVICON_VERSAO"] = str(int(time.time()))
    salvar_config()

    flash("Favicon atualizado com sucesso.", "success")
    return redirect("/configuracoes")


@app.route("/configuracoes/apagar-tabelas", methods=["POST"])
@requer_admin
def configuracoes_apagar_tabelas():
    confirmacao = request.form.get("confirmacao", "").strip()

    if confirmacao != "APAGAR TUDO":
        flash(
            "Confirmação incorreta. Digite exatamente 'APAGAR TUDO' para prosseguir.",
            "erro",
        )
        return redirect("/configuracoes")

    apagar_tabelas()

    flash("Todas as tabelas do banco de dados foram apagadas.", "success")
    return redirect("/configuracoes")


@app.route("/empresas")
def empresas():

    busca = request.args.get("busca", "")

    conn = sqlite3.connect(BANCO_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            e.*,
            (
                SELECT s.nome
                FROM socios_empresas s
                WHERE s.cnpj_empresa = e.cnpj
                  AND (
                    LOWER(COALESCE(s.qualificacao, '')) LIKE '%administrador%'
                    OR LOWER(COALESCE(s.qualificacao, '')) LIKE '%titular%'
                  )
                ORDER BY s.nome
                LIMIT 1
            ) AS responsavel_principal
        FROM empresas e
        WHERE
            COALESCE(e.razao_social, '') LIKE ?
            OR COALESCE(e.cnpj, '') LIKE ?
            OR COALESCE(e.nome_fantasia, '') LIKE ?
            OR COALESCE(e.situacao_cadastral, '') LIKE ?
            OR COALESCE(e.telefone, '') LIKE ?
            or COALESCE(e.email, '') LIKE ?
        ORDER BY e.razao_social
    """,
        (
            f"%{busca}%",
            f"%{busca}%",
            f"%{busca}%",
            f"%{busca}%",
            f"%{busca}%",
            f"%{busca}%",
        ),
    )

    empresas = cursor.fetchall()
    conn.close()

    return render_template("empresas.html", empresas=empresas, busca=busca)


@app.route("/empresas/executar-script", methods=["POST"])
def empresas_executar_script():
    dados = request.get_json(silent=True) or {}
    codigo_empresa = dados.get("codigo")

    with script_lock:
        if script_estado["rodando"]:
            return jsonify({"ok": False, "erro": "O script já está em execução."}), 409

    thread = threading.Thread(
        target=executar_script_empresa_thread, args=(codigo_empresa,), daemon=True
    )
    thread.start()

    return jsonify({"ok": True})


@app.route("/empresas/executar-script/status")
def empresas_executar_script_status():
    return jsonify(script_estado)


@app.route("/empresa/<int:id>")
def empresa(id):
    conn = sqlite3.connect(BANCO_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM empresas WHERE id = ?", (id,))
    empresa = cursor.fetchone()

    socios = []
    responsavel_principal = ""

    if empresa:
        cursor.execute(
            """
            SELECT *
            FROM socios_empresas
            WHERE cnpj_empresa = ?
            ORDER BY nome
        """,
            (empresa["cnpj"],),
        )
        socios = cursor.fetchall()

        for socio in socios:
            qualificacao = (socio["qualificacao"] or "").lower()
            if "administrador" in qualificacao or "titular" in qualificacao:
                responsavel_principal = socio["nome"]
                break

        if not responsavel_principal and socios:
            responsavel_principal = socios[0]["nome"]

    conn.close()

    return render_template(
        "empresa.html",
        empresa=empresa,
        socios=socios,
        responsavel_principal=responsavel_principal,
    )


@app.route("/empresas/pendencias")
def empresas_pendencias():

    busca = request.args.get("busca", "").strip().lower()

    agora = datetime.now()
    um_mes_atras = agora - relativedelta(months=1)

    mes = request.args.get("mes", um_mes_atras.strftime("%Y-%m"))

    ano, mes_num = mes.split("-")
    anomes = f"{ano}{mes_num}"

    empresas = {}

    for empresa_dir in Path(PASTA_CLIENTES).iterdir():

        if not empresa_dir.is_dir():
            continue

        partes = empresa_dir.name.split(" - ", 1)

        if len(partes) != 2:
            continue

        codigo, nome = partes

        if busca and busca not in codigo.lower() and busca not in nome.lower():
            continue

        dctfweb_pdf = pdf_dctfweb_fgts(empresa_dir, ano, anomes, "DCTFWEB")
        fgts_pdf = pdf_dctfweb_fgts(empresa_dir, ano, anomes, "FGTS")
        das_pdf = pdf_das_mensal(empresa_dir, ano, anomes)

        empresas[codigo] = {
            "codigo": codigo,
            "nome": nome,
            "dctfweb": dctfweb_pdf is not None,
            "fgts": fgts_pdf is not None,
            "das_mensal": das_pdf is not None,
        }

    return render_template(
        "empresas_pendencias.html",
        empresas=empresas,
        busca=busca,
        mes=mes,
    )


@app.route("/empresas/pendencias/abrir/<codigo>/<tipo>")
def abrir_guia(codigo, tipo):
    """
    Abre o PDF da guia no navegador.
    tipo: 'dctfweb', 'fgts' ou 'das_mensal'
    mes: vem via querystring (?mes=2026-06)
    """
    mes = request.args.get("mes")
    if not mes:
        abort(400, "Mês não informado")

    ano, mes_num = mes.split("-")
    anomes = f"{ano}{mes_num}"

    pasta_empresa = encontrar_pasta_empresa(codigo)
    if pasta_empresa is None:
        abort(404, "Empresa não encontrada")

    if tipo == "dctfweb":
        pdf = pdf_dctfweb_fgts(pasta_empresa, ano, anomes, "DCTFWEB")
    elif tipo == "fgts":
        pdf = pdf_dctfweb_fgts(pasta_empresa, ano, anomes, "FGTS")
    elif tipo == "das_mensal":
        pdf = pdf_das_mensal(pasta_empresa, ano, anomes)
    else:
        abort(400, "Tipo de guia inválido")

    if pdf is None:
        abort(404, "Guia não encontrada")

    return send_file(pdf, mimetype="application/pdf")


@app.route("/empresas/certificados")
def certificados():
    certificados = ler_certificados_windows()
    return render_template("certificados.html", certificados=certificados)


@app.route("/documentos/procedimentos")
def procedimentos():

    busca = request.args.get("busca", "").lower()

    arquivos_por_categoria = {}

    try:
        nomes = os.listdir(PASTAS_PROCEDIMENTOS)
    except OSError:
        nomes = []

    for nome in nomes:
        if (
            nome.lower().endswith((".doc", ".docx", ".pdf"))
            and not nome.startswith("~$")
            and busca in nome.lower()
        ):
            categoria = definir_categoria(nome)

            if categoria not in arquivos_por_categoria:
                arquivos_por_categoria[categoria] = []
            arquivos_por_categoria[categoria].append(nome)

    for categoria in arquivos_por_categoria:
        arquivos_por_categoria[categoria] = sorted(
            arquivos_por_categoria[categoria], key=str.lower
        )

    return render_template(
        "procedimentos.html", arquivos_por_categoria=arquivos_por_categoria, busca=busca
    )


@app.route("/documentos/procedimentos/abrir/<nome>")
def abrir_procedimento(nome):
    return send_from_directory(PASTAS_PROCEDIMENTOS, nome, as_attachment=False)


@app.route("/documentos/arquivos")
def arquivos():

    pasta = request.args.get("pasta", "")

    itens = []

    caminho_atual = caminho_seguro(PASTA_ARQUIVOS, pasta)

    if not os.path.isdir(caminho_atual):
        abort(404)

    for nome in os.listdir(caminho_atual):
        caminho_completo = os.path.join(caminho_atual, nome)
        rel = os.path.relpath(caminho_completo, PASTA_ARQUIVOS)

        itens.append(
            {
                "nome": nome,
                "tipo": "pasta" if os.path.isdir(caminho_completo) else "arquivo",
                "rel": rel,
            }
        )

    itens.sort(key=lambda x: (x["tipo"] != "pasta", x["nome"].lower()))

    return render_template("arquivos.html", itens=itens, pasta=pasta)


@app.route("/documentos/arquivos/abrir")
def abrir_arquivo():
    caminho_relativo = request.args.get("arquivo", "")

    caminho = caminho_seguro(PASTA_ARQUIVOS, caminho_relativo)

    if not os.path.isfile(caminho):
        abort(404)

    return send_file(caminho, as_attachment=False)


@app.route("/documentos/arquivos/upload", methods=["POST"])
def upload_arquivo():

    pasta_atual = request.form.get("pasta_atual", "")
    arquivos = request.files.getlist("arquivos")

    caminho_destino = caminho_seguro(PASTA_ARQUIVOS, pasta_atual)
    if not os.path.isdir(caminho_destino):
        abort(404)

    for arquivo in arquivos:
        if arquivo and arquivo.filename:
            nome_seguro = secure_filename(arquivo.filename)
            destino = nome_disponivel(caminho_destino, nome_seguro)
            arquivo.save(destino)

    flash("Arquivo enviado.", "success")
    return redirect("/documentos/arquivos?pasta=" + quote(pasta_atual))


@app.route("/contabil/pdde")
def pdde():
    return render_template("pdde.html")


@app.route("/contabil/pdde/pdf", methods=["POST"])
def pdde_pdf():
    arquivos = request.files.getlist("pdde_pdf")
    if not arquivos:
        return render_template("pdde.html", erro="Envie o PDF do PDDE.")

    planilhas = []

    for indice, arquivo in enumerate(arquivos):
        nome_seguro = secure_filename(arquivo.filename)
        id_execucao = str(uuid.uuid4())[:8]

        conta_caixa = request.form.get(f"conta_caixa_{indice}", "").strip()
        conta_receita = request.form.get(f"conta_receita_{indice}", "").strip()

        caminho_pdf = os.path.join(PASTA_UPLOAD_PDDE, f"{id_execucao}_{nome_seguro}")
        arquivo.save(caminho_pdf)

        caminho_saida = os.path.join(
            PASTA_SAIDA_PDDE, f"importacao_pdde_{id_execucao}.xlsx"
        )

        gerador = gerar_planilha_importacao(
            caminho_pdde_pdf=caminho_pdf,
            caminho_plano_pdf=PLANO_CONTAS_PDDE,
            caminho_modelo_xlsx=MODELO_IMPORTACAO_CONTMATIC,
            caminho_saida_xlsx=caminho_saida,
            conta_caixa=conta_caixa,
            conta_receita_pdde=conta_receita,
        )

        if "400" in gerador:
            flash(f"{gerador['400']}", "erro")
            return redirect("/contabil/pdde")

        df = pd.read_excel(caminho_saida, header=None, skiprows=2)
        planilhas.append(df)

    id_execucao = str(uuid.uuid4())[:8]
    planilha_resultado = os.path.join(
        PASTA_SAIDA_PDDE, f"{id_execucao}_importacao_pdde.xlsx"
    )
    resultado = pd.concat(planilhas, ignore_index=True)
    resultado.to_excel(planilha_resultado, index=False, header=False)

    return send_file(
        planilha_resultado, as_attachment=True, download_name="importacao_pdde.xlsx"
    )


@app.route("/contabil/pdde/manual", methods=["POST"])
def pdde_manual():
    conta_caixa = request.form.get("conta_caixa", "").strip()
    conta_receita = request.form.get("conta_receita", "").strip()
    saldo_inicial = float(request.form.get("saldo_inicial", "0").replace(",", "."))

    tipos = request.form.getlist("manual_tipo[]")
    datas = request.form.getlist("manual_data[]")
    historicos = request.form.getlist("manual_historico[]")
    descricoes = request.form.getlist("manual_descricao[]")
    valores = request.form.getlist("manual_valor[]")

    lancamentos = []

    for tipo, data, historico, descricao, valor in zip(
        tipos, datas, historicos, descricoes, valores
    ):
        if data and historico and valor:
            lancamentos.append(
                {
                    "tipo": tipo,
                    "data": data,
                    "historico": historico,
                    "descricao": descricao,
                    "valor": float(valor.replace(",", ".")),
                }
            )

    id_execucao = str(uuid.uuid4())[:8]
    caminho_saida = os.path.join(
        PASTA_SAIDA_PDDE, f"importacao_pdde_manual_{id_execucao}.xlsx"
    )

    gerador = gerar_planilha_manual_pdde(
        caminho_plano_pdf=PLANO_CONTAS_PDDE,
        caminho_modelo_xlsx=MODELO_IMPORTACAO_CONTMATIC,
        caminho_saida_xlsx=caminho_saida,
        conta_caixa=conta_caixa,
        conta_receita_pdde=conta_receita,
        saldo_inicial=saldo_inicial,
        lancamentos=lancamentos,
    )

    if "400" in gerador:
        flash(f"{gerador['400']}", "erro")
        return redirect("/contabil/pdde")

    return send_file(
        caminho_saida, as_attachment=True, download_name="importacao_pdde_manual.xlsx"
    )


@app.route("/contabil/pdde/plano_de_contas")
def pdde_vizualizar_plano_contas():
    return send_file(PLANO_CONTAS_PDDE, as_attachment=False)


@app.route("/rh/funcionario")
def funcionario_pagina():
    conn = sqlite3.connect(BANCO_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM funcionarios ORDER BY nome")
    funcionarios = cursor.fetchall()
    conn.close()

    return render_template("funcionario.html", funcionarios=funcionarios)


@app.route("/rh/funcionario/cadastrar", methods=["POST"])
def funcionario_cadastrar():
    nome = request.form.get("nome", "").strip()
    funcao = request.form.get("funcao", "").strip()
    descricao = request.form.get("descricao", "").strip()

    if not nome:
        flash("O nome do funcionário é obrigatório.", "erro")
        return redirect("/rh/funcionario")

    conn = sqlite3.connect(BANCO_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO funcionarios (nome, funcao, descricao, ativo)
            VALUES (?, ?, ?, 1)
            """,
            (nome, funcao, descricao),
        )
        conn.commit()
        flash(f"Funcionário {nome} cadastrado com sucesso.", "success")
    except sqlite3.IntegrityError:
        flash(f"Já existe um funcionário cadastrado com o nome {nome}.", "erro")
    finally:
        conn.close()

    return redirect("/rh/funcionario")


@app.route("/rh/funcionario/editar/<int:id>", methods=["POST"])
def funcionario_editar(id):
    nome = request.form.get("nome", "").strip()
    funcao = request.form.get("funcao", "").strip()
    descricao = request.form.get("descricao", "").strip()
    ativo = 1 if request.form.get("ativo") == "on" else 0

    if not nome:
        flash("O nome do funcionário é obrigatório.", "erro")
        return redirect("/rh/funcionario")

    conn = sqlite3.connect(BANCO_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE funcionarios
        SET nome = ?, funcao = ?, descricao = ?, ativo = ?
        WHERE id = ?
        """,
        (nome, funcao, descricao, ativo, id),
    )
    conn.commit()
    afetado = cursor.rowcount
    conn.close()

    if not afetado:
        flash("Funcionário não encontrado.", "erro")
    else:
        flash(f"Funcionário {nome} atualizado com sucesso.", "success")

    return redirect("/rh/funcionario")


@app.route("/rh/horas-extras")
def horas_extras():

    mes = request.args.get("mes", datetime.now().strftime("%Y-%m"))

    conn = sqlite3.connect(BANCO_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            f.id,
            f.nome,
            COALESCE(SUM(h.total_horas), 0) AS total_mes
        FROM funcionarios f
        LEFT JOIN horas_extras h
            ON h.funcionario_id = f.id
            AND substr(h.data, 1, 7) = ?
        GROUP BY f.id, f.nome
        ORDER BY f.nome
    """,
        (mes,),
    )

    funcionarios = cursor.fetchall()

    cursor.execute(
        """
        SELECT COALESCE(SUM(total_horas),0)
        FROM horas_extras
        WHERE substr(data,1,7)=?
    """,
        (mes,),
    )

    total_geral = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "horas_extras.html", funcionarios=funcionarios, mes=mes, total_geral=total_geral
    )


@app.route("/rh/horas-extras/funcionario/<int:id>")
def horas_extras_funcionario(id):
    mes = request.args.get("mes", datetime.now().strftime("%Y-%m"))

    conn = sqlite3.connect(BANCO_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM funcionarios WHERE id = ?", (id,))
    funcionario = cursor.fetchone()

    cursor.execute(
        """
        SELECT *
        FROM horas_extras
        WHERE funcionario_id = ?
        AND substr(data, 1, 7) = ?
        ORDER BY data DESC
    """,
        (id, mes),
    )

    registros = cursor.fetchall()

    cursor.execute(
        """
        SELECT COALESCE(SUM(total_horas), 0)
        FROM horas_extras
        WHERE funcionario_id = ?
        AND substr(data, 1, 7) = ?
    """,
        (id, mes),
    )

    total_mes = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "horas_extras_funcionario.html",
        funcionario=funcionario,
        registros=registros,
        total_mes=total_mes,
        mes=mes,
    )


@app.route("/rh/horas-extras/cadastrar/<int:funcionario_id>", methods=["POST"])
def cadastrar_hora_extra(funcionario_id):

    data = request.form["data"]
    hora_inicio = request.form["hora_inicio"]
    hora_fim = request.form["hora_fim"]
    observacao = request.form.get("observacao", "")

    total = calcular_total_horas(hora_inicio, hora_fim)

    conn = sqlite3.connect(BANCO_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO horas_extras (
            funcionario_id,
            data,
            hora_inicio,
            hora_fim,
            total_horas,
            observacao
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (funcionario_id, data, hora_inicio, hora_fim, total, observacao),
    )

    conn.commit()
    conn.close()

    flash(f"Foram adicionadas {total} horas extras em {data}.", "success")
    return redirect(f"/rh/horas-extras/funcionario/{funcionario_id}?mes={data[:7]}")


@app.route("/rh/horas-extras/excluir/<int:id>", methods=["POST"])
def excluir_hora_extra(id):

    conn = sqlite3.connect(BANCO_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT funcionario_id, data
        FROM horas_extras
        WHERE id = ?
    """,
        (id,),
    )

    registro = cursor.fetchone()

    if registro:
        funcionario_id = registro[0]
        mes = registro[1][:7]

        cursor.execute(
            """
            DELETE FROM horas_extras
            WHERE id = ?
        """,
            (id,),
        )

        conn.commit()
        conn.close()

        flash(f"Hora extra excluida com sucesso.", "success")
        return redirect(f"/rh/horas-extras/funcionario/{funcionario_id}?mes={mes}")

    conn.close()

    return redirect("/rh/horas-extras")


@app.route("/rh/esocial")
def esocial():

    busca = request.args.get("busca", "")

    conn = sqlite3.connect(BANCO_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if busca:

        cursor.execute(
            """
            SELECT id, codigo, descriminador, solucao
            FROM esocial
            WHERE codigo LIKE ?
            OR descriminador LIKE ?
            ORDER BY codigo

        """,
            (f"%{busca}%", f"%{busca}%"),
        )

    else:
        cursor.execute("""
            SELECT * FROM esocial
            ORDER BY codigo
        """)

    erros = cursor.fetchall()
    conn.close()

    return render_template("esocial.html", erros=erros, busca=busca)


@app.route("/rh/esocial/cadastrar", methods=["POST"])
def esocial_cadastrar():

    codigo = request.form["codigo"]
    descriminador = request.form["descriminador"]
    solucao = request.form["solucao"]

    conn = sqlite3.connect(BANCO_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO esocial
        (codigo, descriminador, solucao)
        VALUES (?, ?, ?)
    """,
        (codigo, descriminador, solucao),
    )

    conn.commit()
    conn.close()

    flash(f"Erro {codigo} cadastrado com sucesso.", "success")
    return redirect("/rh/esocial")


@app.route("/rh/esocial/excluir/<id>", methods=["POST"])
def esocial_excluir(id):
    conn = sqlite3.connect(BANCO_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, codigo FROM esocial WHERE id = ?", (id,))
    erro = cursor.fetchone()

    if erro:
        codigo = erro[1]
        cursor.execute("DELETE FROM esocial WHERE id = ?", (id,))
        conn.commit()
        conn.close()
        flash(f"Erro {codigo} excluido com sucesso.", "success")
        return redirect("/rh/esocial")

    conn.close()
    flash("Erro não encontrado.", "erro")
    return redirect("/rh/esocial")


@app.route("/utilidades/pdf", methods=["GET", "POST"])
def ocr_pdf():
    if request.method == "POST":
        arquivos = request.files.getlist("pdfs")
        if not arquivos:
            return jsonify({"erro": "Envie o PDF."})

        ids = []
        for arquivo in arquivos:
            nome_seguro = secure_filename(arquivo.filename)
            id_execucao = str(uuid.uuid4())[:8]
            ids.append(id_execucao)

            entrada = os.path.join(PASTA_UPLOAD_PDF, f"{id_execucao}_{nome_seguro}")
            saida = os.path.join(PASTA_SAIDA_PDF, f"ocr_pdf_{id_execucao}.pdf")
            arquivo.save(entrada)

            with tarefas_ocr_lock:
                tarefas_ocr[id_execucao] = {
                    "status": "processando",
                    "criado_em": time.time(),
                }

            thread = threading.Thread(
                target=executar_ocr,
                args=(id_execucao, entrada, saida, nome_seguro),
                daemon=True,
            )
            thread.start()

        return jsonify({"ids": ids})

    return render_template("ocr.html")


@app.route("/utilidades/pdf/status/<id_execucao>")
def ocr_status(id_execucao):
    with tarefas_ocr_lock:
        tarefa = tarefas_ocr.get(id_execucao)
    if tarefa is None:
        return jsonify({"status": "nao_encontrado"}), 404
    return jsonify(tarefa)


@app.route("/utilidades/pdf/download/<id_execucao>")
def ocr_download(id_execucao):
    with tarefas_ocr_lock:
        tarefa = tarefas_ocr.get(id_execucao)

    if tarefa is None or tarefa.get("status") != "concluido":
        abort(404, "Arquivo não encontrado ou ainda não processado.")

    return send_file(
        tarefa["arquivo"], as_attachment=True, download_name=f"OCR_{tarefa['nome']}"
    )


@trello_bp.route("/utilidades/trello", methods=["GET"])
def trello_form():
    """Renderiza a tela com o cartão estilo Trello, já carregando listas, labels e membros reais do board."""
    listas, labels, members = [], [], []
    erro_config = not (TRELLO_API_KEY and TRELLO_TOKEN and TRELLO_BOARD_ID)

    if not erro_config:
        try:
            resp_listas = requests.get(
                f"{TRELLO_API_BASE}/boards/{TRELLO_BOARD_ID}/lists",
                params={**_auth_params(), "filter": "open"},
                timeout=8,
            )
            resp_listas.raise_for_status()
            listas = resp_listas.json()

            resp_labels = requests.get(
                f"{TRELLO_API_BASE}/boards/{TRELLO_BOARD_ID}/labels",
                params=_auth_params(),
                timeout=8,
            )
            resp_labels.raise_for_status()
            labels = resp_labels.json()

            resp_members = requests.get(
                f"{TRELLO_API_BASE}/boards/{TRELLO_BOARD_ID}/members",
                params=_auth_params(),
                timeout=8,
            )
            resp_members.raise_for_status()
            members = resp_members.json()
        except requests.RequestException as e:
            flash(f"Não foi possível carregar dados do Trello: {e}", "erro")

    return render_template(
        "trello.html",
        listas=listas,
        labels=labels,
        members=members,
        config_ok=not erro_config,
    )


@trello_bp.route("/utilidades/trello/criar", methods=["POST"])
def trello_criar():
    """Recebe o payload do cartão (JSON) e cria o cartão de verdade no Trello."""
    if not (TRELLO_API_KEY and TRELLO_TOKEN):
        return (
            jsonify(
                {
                    "ok": False,
                    "erro": "Integração com o Trello não configurada no servidor.",
                }
            ),
            500,
        )

    dados = request.get_json(silent=True) or {}

    titulo = (dados.get("titulo") or "").strip()
    if not titulo:
        return jsonify({"ok": False, "erro": "O título do cartão é obrigatório."}), 400

    id_lista = (dados.get("idList") or "").strip()
    if not id_lista:
        return (
            jsonify({"ok": False, "erro": "Selecione a lista de destino do cartão."}),
            400,
        )

    descricao = dados.get("descricao", "")
    data_entrega = dados.get("dataEntrega") or None  # formato esperado: YYYY-MM-DD
    label_ids = dados.get("labelIds", [])
    member_ids = dados.get("memberIds", [])
    checklist_itens = dados.get("checklist", [])

    params = _auth_params()
    params.update(
        {
            "idList": id_lista,
            "name": titulo,
            "desc": descricao,
        }
    )
    if data_entrega:
        params["due"] = data_entrega
    if label_ids:
        params["idLabels"] = ",".join(label_ids)
    if member_ids:
        params["idMembers"] = ",".join(member_ids)

    try:
        resp = requests.post(f"{TRELLO_API_BASE}/cards", params=params, timeout=10)
        resp.raise_for_status()
        cartao = resp.json()
        card_id = cartao["id"]
        card_url = cartao.get("shortUrl") or cartao.get("url")

        # Se houver itens de checklist, cria a checklist e adiciona cada item
        # cada item pode vir como string (compatibilidade) ou como {"texto": ..., "concluido": bool}
        itens_normalizados = []
        for item in checklist_itens:
            if isinstance(item, dict):
                texto = (item.get("texto") or "").strip()
                concluido = bool(item.get("concluido"))
            else:
                texto = (item or "").strip()
                concluido = False
            if texto:
                itens_normalizados.append((texto, concluido))

        if itens_normalizados:
            resp_chk = requests.post(
                f"{TRELLO_API_BASE}/checklists",
                params={**_auth_params(), "idCard": card_id, "name": "Checklist"},
                timeout=10,
            )
            resp_chk.raise_for_status()
            checklist_id = resp_chk.json()["id"]

            for texto, concluido in itens_normalizados:
                requests.post(
                    f"{TRELLO_API_BASE}/checklists/{checklist_id}/checkItems",
                    params={
                        **_auth_params(),
                        "name": texto,
                        "checked": "true" if concluido else "false",
                    },
                    timeout=10,
                )

        return jsonify({"ok": True, "url": card_url, "id": card_id})

    except requests.RequestException as e:
        detalhe = ""
        if e.response is not None:
            detalhe = e.response.text
        return (
            jsonify(
                {
                    "ok": False,
                    "erro": f"Falha ao criar cartão no Trello: {e}. {detalhe}",
                }
            ),
            502,
        )


@pasta_organizadora_bp.route("/utilidades/pasta-organizadora")
def pasta_organizadora_pagina():
    _garantir_config()
    arquivos_por_secao = {
        secao: _listar_arquivos(_pasta_secao(secao)) for secao in po.SECOES
    }
    estado = po.obter_estado()

    return render_template(
        "pasta_organizadora.html",
        arquivos_por_secao=arquivos_por_secao,
        ultima_organizacao=_formatar_data(estado["ultima_organizacao"]),
        proxima_organizacao=_formatar_data(estado["proxima_organizacao"]),
    )


@pasta_organizadora_bp.route("/utilidades/pasta-organizadora/status")
def pasta_organizadora_status():
    _garantir_config()
    estado = po.obter_estado()
    return jsonify(
        {
            "rodando": estado["rodando"],
            "ultima_organizacao": _formatar_data(estado["ultima_organizacao"]),
            "proxima_organizacao": _formatar_data(estado["proxima_organizacao"]),
            "arquivos_por_secao": {
                secao: _listar_arquivos(_pasta_secao(secao)) for secao in po.SECOES
            },
        }
    )


@pasta_organizadora_bp.route(
    "/utilidades/pasta-organizadora/upload/<secao>", methods=["POST"]
)
def pasta_organizadora_upload(secao):
    _garantir_config()
    pasta_destino = _pasta_secao(secao)
    pasta_destino.mkdir(parents=True, exist_ok=True)

    arquivos = request.files.getlist("arquivos")
    if not arquivos:
        return jsonify({"ok": False, "erro": "Nenhum arquivo enviado."}), 400

    enviados = []
    for arquivo in arquivos:
        if not arquivo or not arquivo.filename:
            continue
        nome_seguro = secure_filename(arquivo.filename)
        destino = po.nome_disponivel(pasta_destino, nome_seguro)
        arquivo.save(str(destino))
        enviados.append(destino.name)

    return jsonify({"ok": True, "enviados": enviados})


@pasta_organizadora_bp.route(
    "/utilidades/pasta-organizadora/organizar", methods=["POST"]
)
def pasta_organizadora_organizar():
    _garantir_config()
    linhas_log = po.organizar_tudo(
        _CONFIG["PASTA_ORGANIZADORA"],
        _CONFIG["PASTA_CLIENTES"],
        _CONFIG["PASTA_APMS"],
        _CONFIG["PASTA_ORGANIZADORA"] / po.SUBPASTA_LOGS,
    )

    agora = datetime.now()
    with po._estado_lock:
        po.ESTADO["ultima_organizacao"] = agora

    return jsonify(
        {
            "ok": True,
            "movimentacoes": len(linhas_log),
            "log": linhas_log,
        }
    )


@app.route("/servidor/monitoramento")
def monitoramento():
    return render_template("monitoramento.html")


@app.route("/servidor/reiniciar-site", methods=["POST"])
def reiniciar_site():
    dados = request.get_json(silent=True) or request.form
    senha = dados.get("senha", "")

    if not senha_valida(senha):
        return jsonify({"ok": False, "erro": "Senha incorreta."}), 403

    if not SCRIPT_REINICIAR_SITE:
        return (
            jsonify(
                {"ok": False, "erro": "Script de reinício da intranet não configurado."}
            ),
            500,
        )

    def executar():
        time.sleep(1)

        if tarefa_agendada_existe(NOME_TAREFA_REINICIAR_SITE):
            subprocess.run(
                ["schtasks", "/run", "/tn", NOME_TAREFA_REINICIAR_SITE],
                shell=True,
            )
        else:
            subprocess.run([SCRIPT_REINICIAR_SITE], shell=True)

    threading.Thread(target=executar, daemon=True).start()
    return jsonify({"ok": True, "mensagem": "Reiniciando a intranet..."})


@app.route("/servidor/reiniciar-servidor", methods=["POST"])
def reiniciar_servidor():
    dados = request.get_json(silent=True) or request.form
    senha = dados.get("senha", "")

    if not senha_valida(senha):
        return jsonify({"ok": False, "erro": "Senha incorreta."}), 403

    if not SCRIPT_REINICIAR:
        return (
            jsonify(
                {"ok": False, "erro": "Script de reinício do servidor não configurado."}
            ),
            500,
        )

    def executar():
        time.sleep(1)
        subprocess.run([SCRIPT_REINICIAR], shell=True)

    threading.Thread(target=executar, daemon=True).start()
    return jsonify(
        {
            "ok": True,
            "mensagem": "Reiniciando o servidor. A intranet ficará indisponível por alguns minutos.",
        }
    )


@app.route("/servidor/backup")
def backup_central():
    backup = get_last_backup_info()
    log_conteudo = ler_log_backup()

    ultimo_backup_formatado = None
    if backup:
        dt = datetime.fromtimestamp(backup["timestamp"])
        ultimo_backup_formatado = dt.strftime("%d/%m/%Y %H:%M")

    return render_template(
        "backup.html",
        backup=backup,
        ultimo_backup_formatado=ultimo_backup_formatado,
        log_conteudo=log_conteudo,
        rodando=backup_estado["rodando"],
    )


@app.route("/servidor/backup/executar", methods=["POST"])
def backup_executar():
    with backup_lock:
        if backup_estado["rodando"]:
            return (
                jsonify({"ok": False, "erro": "Já existe um backup em execução."}),
                409,
            )

    thread = threading.Thread(target=executar_backup_thread, daemon=True)
    thread.start()

    return jsonify({"ok": True})


@app.route("/servidor/backup/status")
def backup_status():
    backup = get_last_backup_info()
    log_conteudo = ler_log_backup()

    return jsonify(
        {
            "rodando": backup_estado["rodando"],
            "ultimo_erro": backup_estado["ultimo_erro"],
            "log": log_conteudo,
            "ultimo_backup_timestamp": backup["timestamp"] if backup else None,
            "ultimo_backup_arquivo": backup["arquivo"] if backup else None,
        }
    )


@app.route("/servidor/backup/log/download")
def backup_log_download():
    if not os.path.exists(LOG_BACKUP):
        abort(404)

    return send_file(
        LOG_BACKUP,
        as_attachment=True,
        download_name="log_backup.txt",
    )


app.register_blueprint(trello_bp)
app.register_blueprint(pasta_organizadora_bp)

init_pasta_organizadora(PASTA_ORGANIZADORA, PASTA_CLIENTES, PASTA_APMS)

if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    iniciar_agendador_app(intervalo_segundos=1200)  # 20 minutos

if __name__ == "__main__":
    print(f"[OK] IP do servidor: {obter_ip_local()}")
    serve(
        app,
        host="0.0.0.0",
        port=80,
        threads=8,  # padrão do waitress é 4
        connection_limit=200,
        channel_timeout=120,
    )
