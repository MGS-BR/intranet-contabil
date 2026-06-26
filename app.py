import os
import subprocess
import json
import re
import sqlite3
import psutil
import shutil
import sys
import socket
import uuid
import requests
import ocrmypdf
import threading
import pandas as pd
from bs4 import BeautifulSoup
from waitress import serve
from urllib.parse import quote
from pdde_importador import gerar_planilha_importacao, gerar_planilha_manual_pdde
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from flask import Flask, render_template, send_from_directory, request, send_file, abort, redirect, session, flash, jsonify

app = Flask(__name__)

load_dotenv()

app.secret_key = os.getenv("SECRET_KEY")
SENHA_SITE = os.getenv("SENHA_SITE")
SENHA_ADMIN = os.getenv("SENHA_ADMIN") or SENHA_SITE

with open("config.json", "r", encoding="utf-8") as arquivo:
    config = json.load(arquivo)

PASTAS_PROCEDIMENTOS = config["PASTAS_PROCEDIMENTOS"]
PASTA_ARQUIVOS = config["PASTA_ARQUIVOS"]
SCRIPT_BACKUP = config["SCRIPT_BACKUP"]
LOG_BACKUP = config["LOG_BACKUP"]
SCRIPT_REINICIAR = config["SCRIPT_REINICIAR"]

PASTA_UPLOAD_PDDE = config["PASTA_UPLOAD_PDDE"]
PASTA_SAIDA_PDDE = config["PASTA_SAIDA_PDDE"]
PLANO_CONTAS_PDDE = config["PLANO_CONTAS_PDDE"]
MODELO_IMPORTACAO_CONTMATIC = config["MODELO_IMPORTACAO_CONTMATIC"]

PASTA_UPLOAD_PDF = config["PASTA_UPLOAD_PDF"]
PASTA_SAIDA_PDF = config["PASTA_SAIDA_PDF"]

os.makedirs(PASTA_UPLOAD_PDDE, exist_ok=True)
os.makedirs(PASTA_SAIDA_PDDE, exist_ok=True)

os.makedirs(PASTA_UPLOAD_PDF, exist_ok=True)
os.makedirs(PASTA_SAIDA_PDF, exist_ok=True)

tarefas_ocr = {}

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


def adicionar_coluna_se_nao_existir(cursor, tabela, coluna, definicao):
    cursor.execute(f"PRAGMA table_info({tabela})")
    colunas = [c[1] for c in cursor.fetchall()]

    if coluna not in colunas:
        definicao_alter = definicao.replace("UNIQUE", "").strip()
        cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao_alter}")


def garantir_banco():
    """Cria/atualiza as tabelas necessárias sem apagar dados existentes."""
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS indice_arquivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            caminho TEXT,
            pasta TEXT,
            extensao TEXT,
            tamanho INTEGER,
            modificado_em TEXT
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_indice_nome ON indice_arquivos(nome)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_indice_caminho ON indice_arquivos(caminho)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj TEXT UNIQUE,
            razao_social TEXT,
            nome_fantasia TEXT,
            porte TEXT,
            data_abertura TEXT,
            situacao_cadastral TEXT,
            data_situacao_cadastral TEXT,
            natureza_juridica TEXT,
            atividade_principal TEXT,
            capital_social TEXT,
            telefone TEXT,
            email TEXT,
            logradouro TEXT,
            numero TEXT,
            complemento TEXT,
            bairro TEXT,
            municipio TEXT,
            uf TEXT,
            cep TEXT,
            caminho_empresa TEXT,
            cnpj_arquivo TEXT,
            qsa_arquivo TEXT,
            atualizado_em TEXT,
            observacoes TEXT
        )
    """)

    colunas_empresas = {
        "cnpj": "TEXT UNIQUE",
        "razao_social": "TEXT",
        "nome_fantasia": "TEXT",
        "porte": "TEXT",
        "data_abertura": "TEXT",
        "situacao_cadastral": "TEXT",
        "data_situacao_cadastral": "TEXT",
        "natureza_juridica": "TEXT",
        "atividade_principal": "TEXT",
        "capital_social": "TEXT",
        "telefone": "TEXT",
        "email": "TEXT",
        "logradouro": "TEXT",
        "numero": "TEXT",
        "complemento": "TEXT",
        "bairro": "TEXT",
        "municipio": "TEXT",
        "uf": "TEXT",
        "cep": "TEXT",
        "caminho_empresa": "TEXT",
        "cnpj_arquivo": "TEXT",
        "qsa_arquivo": "TEXT",
        "atualizado_em": "TEXT",
        "observacoes": "TEXT",
    }

    for coluna, definicao in colunas_empresas.items():
        try:
            adicionar_coluna_se_nao_existir(cursor, "empresas", coluna, definicao)
        except sqlite3.OperationalError:
            pass

    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_empresas_cnpj_unico ON empresas(cnpj)")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS socios_empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj_empresa TEXT,
            nome TEXT,
            qualificacao TEXT
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_socios_cnpj ON socios_empresas(cnpj_empresa)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS funcionarios_horas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS horas_extras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            funcionario_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            hora_inicio TEXT NOT NULL,
            hora_fim TEXT NOT NULL,
            total_horas REAL NOT NULL,
            observacao TEXT,
            FOREIGN KEY (funcionario_id) REFERENCES funcionarios_horas(id)
        )
    """)

    conn.commit()
    conn.close()


garantir_banco()

@app.route("/login", methods=["GET", "POST"])
def login():
    erro = ""

    if request.method == "POST":
        senha = request.form.get("senha", "")

        if senha == SENHA_SITE:
            session["logado"] = True
            return redirect("/")
        else:
            erro = "Senha incorreta."

    return render_template("login.html", erro=erro)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.before_request
def proteger_site():
    rotas_livres = ["login", "static"]

    if request.endpoint in rotas_livres:
        return

    if not session.get("logado"):
        return redirect("/login")

@app.before_request
def log_acesso():
    print(f"[{datetime.now():%H:%M:%S}] {request.remote_addr} -> {request.path}")

@app.route("/")
def inicio():
    total_procedimentos = 0
    ultimo_backup = "Nenhum backup encontrado"

    try:
        for nome in os.listdir(PASTAS_PROCEDIMENTOS):
            if nome.lower().endswith((".doc", ".docx", ".pdf")) and not nome.startswith("~$"):
                total_procedimentos += 1
    except:
        pass

    try:
        if os.path.exists(LOG_BACKUP):
            ultimo_backup = datetime.fromtimestamp(
                os.path.getmtime(LOG_BACKUP)
            ).strftime("%d/%m/%Y %H:%M")
    except:
        pass
    
    boot = datetime.fromtimestamp(psutil.boot_time())
    tempo_ligado = datetime.now() - boot

    dias = tempo_ligado.days
    horas = tempo_ligado.seconds // 3600
    minutos = (tempo_ligado.seconds % 3600) // 60

    return render_template(
        "index.html",
        total_procedimentos=total_procedimentos,
        ultimo_backup=ultimo_backup,
        dias=dias, horas=horas, minutos=minutos
    )

@app.route("/api/eventos")
def buscar_eventos():

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM eventos")
    dados = cursor.fetchall()
    conn.close()

    eventos = []
    hoje = datetime.now()
    limite = hoje + timedelta(days=365*5)

    for e in dados:

        id = e[0]
        titulo = e[1]
        descricao = e[2]
        inicio = e[3]
        fim = e[4]
        recorrencia = e[5]
        intervalo = e[6]
        dia = e[7]
        mes = e[8]
        cor = e[9]

        # evento normal
        if not recorrencia:
            eventos.append({
                "id":id,
                "title":titulo,
                "color":cor,
                "description": descricao,
                "start":inicio,
                "end":fim
            })

        # mensal
        elif recorrencia == "mensal":

            data = datetime.strptime(
                inicio,
                "%Y-%m-%d"
            )
            while data <= limite:

                eventos.append({
                    "id":id,
                    "title":titulo,
                    "color":cor,
                    "description": descricao,
                    "start":data.strftime("%Y-%m-%d")
                })

                # adiciona X meses
                novo_mes = data.month + intervalo
                ano = data.year + (novo_mes-1)//12
                mes_atual = (novo_mes-1)%12 + 1
                data = datetime(
                    ano,
                    mes_atual,
                    dia

                )
        # anual
        elif recorrencia == "anual":
            data = datetime(
                hoje.year,
                mes,
                dia
            )
            while data <= limite:
                eventos.append({
                    "id":id,
                    "title":titulo,
                    "color":cor,
                    "description": descricao,
                    "start":data.strftime("%Y-%m-%d")
                })
                data = datetime(
                    data.year+1,
                    mes,
                    dia
                )
                
    return jsonify(eventos)

@app.route("/api/eventos", methods=["POST"])
def criar_evento():

    dados = request.json
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO eventos
    (
    titulo,
    cor,
    descricao,
    inicio,
    fim,
    recorrencia,
    intervalo,
    dia_recorrencia,
    mes_recorrencia
    )
    VALUES (?,?,?,?,?,?,?,?,?)
    """,
    (
    dados["titulo"],
    dados["cor"],
    dados["descricao"],
    dados["inicio"],
    dados["fim"],
    dados["recorrencia"],
    dados["intervalo"],
    dados["dia"],
    dados["mes"]
    ))

    conn.commit()
    conn.close()

    return jsonify({"ok":True})

@app.route("/api/eventos/<int:id>", methods=["PUT"])
def editar_evento(id):

    dados = request.json
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE eventos SET
    titulo=?,
    cor=?,
    descricao=?,
    inicio=?,
    fim=?,
    recorrencia=?,
    intervalo=?,
    dia_recorrencia=?,
    mes_recorrencia=?
    WHERE id=?
    """,
    (
    dados["titulo"],
    dados["cor"],
    dados["descricao"],
    dados["inicio"],
    dados["fim"],
    dados["recorrencia"],
    dados["intervalo"],
    dados["dia"],
    dados["mes"],
    id
    ))

    conn.commit()
    conn.close()

    return jsonify({"ok":True})

@app.route("/api/eventos/<int:id>", methods=["DELETE"])
def excluir_evento(id):

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM eventos WHERE id=?",
        (id,)
    )
    conn.commit()
    conn.close()

    return jsonify({"ok":True})

def definir_categoria(nome):
    nome = nome.lower()

    categorias = {
        "Departamento Pessoal": ["folha", "férias", "ferias", "rescisao", "rescisão", "admissão", "admissao", "advertencia", "advertência", "sindicais", "pro-labore", "pró-labore", "fgts", "inss", "esocial", "dirf", "salário", "salario"],
        "Fiscal": ["notas", "nota", "fiscal", "nf-e", "nf", "nfe", "icms", "iss", "ipi", "simples", "pis", "cofins", "das"],
        "Contábil": ["contábil", "contabil", "balanço", "balanco", "demonstração", "demonstracao", "lucros", "prejuízos", "escrituração", "escrituracao", "dre", "ecd", "ecf"],
        "Legalização": ["abertura", "empresa", "fechamento", "alteração", "contrato social", "capa de contrato", "capa de contrato social", "capa contrato social", "cnpj", "viabilidade"],
        "Geral": ["whatsapp", "texto"]
    }

    for categoria, palavras in categorias.items():
        for palavra in palavras:
            if palavra in nome:
                return categoria
            
    return "Outros"

def calcular_total_horas(inicio, fim):
    h_inicio = datetime.strptime(inicio, "%H:%M")
    h_fim = datetime.strptime(fim, "%H:%M")

    diferenca = h_fim - h_inicio

    if diferenca.total_seconds() < 0:
        diferenca = diferenca + timedelta(days=1)

    return round(diferenca.total_seconds() / 3600, 2)

@app.route("/procedimentos")
def procedimentos():
    busca = request.args.get("busca", "").lower()

    arquivos_por_categoria = {}

    try:
        nomes = os.listdir(PASTAS_PROCEDIMENTOS)
    except OSError:
        nomes = []

    for nome in nomes:
        if nome.lower().endswith((".doc", ".docx", ".pdf")) and not nome.startswith("~$") and busca in nome.lower():
            categoria = definir_categoria(nome)

            if categoria not in arquivos_por_categoria:
                arquivos_por_categoria[categoria] = []
            arquivos_por_categoria[categoria].append(nome)
    
    for categoria in arquivos_por_categoria:
        arquivos_por_categoria[categoria] = sorted(arquivos_por_categoria[categoria], key=str.lower)

    return render_template("procedimentos.html", arquivos_por_categoria=arquivos_por_categoria, busca=busca)

@app.route("/procedimentos/abrir/<nome>")
def abrir_procedimento(nome):
    return send_from_directory(PASTAS_PROCEDIMENTOS, nome, as_attachment=False)

def ler_certificados_windows():
    comando = r'''
        $certs = Get-ChildItem Cert:\CurrentUser\My |
        Select-Object Subject, Issuer, NotAfter, Thumbprint

        @($certs) | ConvertTo-Json -Compress
        '''
    resultado = subprocess.run(["powershell", "-NoProfile","-Command", comando], capture_output=True, text=True, encoding="utf-8")

    if resultado.returncode != 0:
        print("Erro ao ler certificados:", resultado.stderr)
        return []

    saida = resultado.stdout.strip()

    print("SAIDA POWERSHELL:", saida)

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

        certificados.append({
            "empresa": empresa,
            "cnpj": cnpj,
            "vencimento": vencimento.strftime("%d/%m/%Y"),
            "dias": dias,
            "status": status,
            "thumbprint": c["Thumbprint"]
        })

    certificados.sort(key=lambda x: x["dias"])

    return certificados

@app.route("/certificados")
def certificados():
    certificados = ler_certificados_windows()
    return render_template("certificados.html", certificados=certificados)

@app.route("/arquivos")
def arquivos():
    pasta = request.args.get("pasta", "")
    busca = request.args.get("busca", "").strip()

    itens = []

    if busca:
        conn = sqlite3.connect("banco.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT nome, caminho, pasta
            FROM indice_arquivos
            WHERE nome LIKE ?
            ORDER BY nome
            LIMIT 200
        """, (f"%{busca}%",))

        resultados = cursor.fetchall()
        conn.close()

        for r in resultados:
            itens.append({
                "nome": r["nome"],
                "tipo": "arquivo",
                "rel": r["caminho"],
                "pasta": r["pasta"]
            })

    else:
        caminho_atual = caminho_seguro(PASTA_ARQUIVOS, pasta)

        if not os.path.isdir(caminho_atual):
            abort(404)

        for nome in os.listdir(caminho_atual):
            caminho_completo = os.path.join(caminho_atual, nome)
            rel = os.path.relpath(caminho_completo, PASTA_ARQUIVOS)

            itens.append({
                "nome": nome,
                "tipo": "pasta" if os.path.isdir(caminho_completo) else "arquivo",
                "rel": rel
            })

        itens.sort(key=lambda x: (x["tipo"] != "pasta", x["nome"].lower()))

    return render_template(
        "arquivos.html",
        itens=itens,
        pasta=pasta,
        busca=busca
    )

@app.route("/arquivos/abrir")
def abrir_arquivo():
    caminho_relativo = request.args.get("arquivo", "")

    caminho = caminho_seguro(PASTA_ARQUIVOS, caminho_relativo)

    if not os.path.isfile(caminho):
        abort(404)

    return send_file(caminho, as_attachment=False)

@app.route("/arquivos/atualizar", methods=["POST"])
def atualizar_arquivos():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(base_dir, "indexar_arquivos.py")

    subprocess.Popen(
        [sys.executable, script],
        cwd=base_dir
    )

    flash("Indexando os arquivos...", "info")
    return redirect("/arquivos")


def nome_disponivel(pasta, nome):
    base, ext = os.path.splitext(nome)
    destino = os.path.join(pasta, nome)
    contador = 1

    while os.path.exists(destino):
        nome = f"{base} ({contador}){ext}"
        destino = os.path.join(pasta, nome)
        contador += 1

    return destino

@app.route("/arquivos/upload", methods=["POST"])
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
    return redirect("/arquivos?pasta=" + quote(pasta_atual))

@app.route("/backup")
def backup():
    log = "Nenhum log encontrado."

    if os.path.exists(LOG_BACKUP):
        with open(LOG_BACKUP, "r", encoding="utf-8", errors="ignore") as f:
            log = "".join(f.readlines()[-90:])

    return render_template("backup.html", log=log)

@app.route("/backup/executar", methods=["POST"])
def executar_backup():
    subprocess.Popen(
        [SCRIPT_BACKUP],
        shell=True
    )

    flash("Backup iniciado.", "info")
    return redirect("/backup")

@app.route("/backup/vizualizar-log")
def vizualizar_log():
    return send_file(LOG_BACKUP, as_attachment=False)

@app.route("/servidor")
def servidor():
    cpu = psutil.cpu_percent(interval=1)
    memoria = psutil.virtual_memory()

    discos = []

    for unidade in ["C:\\", "D:\\", "E:\\"]:
        if os.path.exists(unidade):
            uso = shutil.disk_usage(unidade)

            total = round(uso.total / (1024 ** 3), 2)
            usado = round(uso.used / (1024 ** 3), 2)
            livre = round(uso.free / (1024 ** 3), 2)
            percentual = round((uso.used / uso.total) * 100, 1)

            discos.append({
                "unidade": unidade,
                "total": total,
                "usado": usado,
                "livre": livre,
                "percentual": percentual
            })

    boot = datetime.fromtimestamp(psutil.boot_time())
    tempo_ligado = datetime.now() - boot

    dias = tempo_ligado.days
    horas = tempo_ligado.seconds // 3600
    minutos = (tempo_ligado.seconds % 3600) // 60

    ultimo_backup = "Nenhum backup encontrado"

    if os.path.exists(LOG_BACKUP):
        ultimo_backup = datetime.fromtimestamp(
            os.path.getmtime(LOG_BACKUP)
        ).strftime("%d/%m/%Y %H:%M")

    return render_template(
        "servidor.html",
        cpu=cpu,
        memoria=memoria,
        discos=discos,
        dias=dias,
        horas=horas,
        minutos=minutos,
        ultimo_backup=ultimo_backup
    )

@app.route("/servidor/reiniciar", methods=["POST"])
def servidor_reiniciar():
    senha = request.form.get("senha", "")

    if senha != SENHA_ADMIN:
        flash("Senha incorreta.", "erro")
        return redirect("/servidor")

    if os.path.exists(SCRIPT_REINICIAR):
        subprocess.Popen([SCRIPT_REINICIAR], shell=True)
    else:
        subprocess.Popen(["shutdown", "/r", "/t", "60", "/c", "Reinício solicitado pelo sistema interno"], shell=True)

    flash("Reiniciando o servidor em 60 segundos.", "warning")
    return redirect("/servidor")

@app.route("/servidor/reiniciar-site", methods=["POST"])
def reiniciar_site():
    
    senha = request.form.get("senha", "")

    if senha != SENHA_ADMIN:
        flash("Senha incorreta.", "erro")
        return redirect("/servidor")
    
    #subprocess.Popen(r"C:\Scripts\reiniciar_sistema.bat", shell=True)
    
    subprocess.Popen('schtasks /run /tn "ReiniciarSistemaInterno"', shell=True)
    
    flash("Site reiniciado com sucesso.", "success")
    
    return redirect("/servidor")

@app.route("/empresas")
def empresas():
    busca = request.args.get("busca", "")

    conn = sqlite3.connect("banco.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
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
    """, (
        f"%{busca}%",
        f"%{busca}%",
        f"%{busca}%",
        f"%{busca}%",
        f"%{busca}%",
        f"%{busca}%",
    ))

    empresas = cursor.fetchall()
    conn.close()

    return render_template("empresas.html", empresas=empresas, busca=busca)

@app.route("/empresa/<int:id>")
def empresa(id):
    conn = sqlite3.connect("banco.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM empresas WHERE id = ?", (id,))
    empresa = cursor.fetchone()

    socios = []
    responsavel_principal = ""

    if empresa:
        cursor.execute("""
            SELECT *
            FROM socios_empresas
            WHERE cnpj_empresa = ?
            ORDER BY nome
        """, (empresa["cnpj"],))
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
        responsavel_principal=responsavel_principal
    )

@app.route("/empresas/atualizar", methods=["POST"])
def atualizar_empresas():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(base_dir, "indexar_empresas.py")

    subprocess.Popen(
        [sys.executable, script],
        cwd=base_dir
    )

    flash("Atualizando o cadastro de empresas...", "info")
    return redirect("/empresas")

@app.route("/pendencias")
def pendencias():
    conn = sqlite3.connect("banco.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            e.*,
            (
                SELECT COUNT(*)
                FROM socios_empresas s
                WHERE s.cnpj_empresa = e.cnpj
            ) AS total_socios
        FROM empresas e
        ORDER BY e.razao_social
    """)

    empresas = cursor.fetchall()
    conn.close()

    lista_pendencias = []

    for empresa in empresas:
        pendencias = []

        if not empresa["cnpj"]:
            pendencias.append("Sem CNPJ")

        if not empresa["cnpj_arquivo"]:
            pendencias.append("Arquivo CNPJ não encontrado")

        if not empresa["qsa_arquivo"]:
            pendencias.append("Arquivo QSA não encontrado")

        if empresa["total_socios"] == 0:
            pendencias.append("Sem sócios/responsáveis do QSA")

        situacao = empresa["situacao_cadastral"] or ""

        if not situacao:
            pendencias.append("Sem situação cadastral")

        elif situacao.upper() not in ["ATIVA", "ATIVO"]:
            pendencias.append(f"Situação: {situacao}")

        if pendencias:
            lista_pendencias.append({
                "id": empresa["id"],
                "razao_social": empresa["razao_social"],
                "cnpj": empresa["cnpj"],
                "pendencias": pendencias
            })

    return render_template(
        "pendencias.html",
        lista_pendencias=lista_pendencias
    )

@app.route("/horas-extras")
def horas_extras():

    mes = request.args.get(
        "mes",
        datetime.now().strftime("%Y-%m")
    )

    conn = sqlite3.connect("banco.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            f.id,
            f.nome,
            COALESCE(SUM(h.total_horas), 0) AS total_mes
        FROM funcionarios_horas f
        LEFT JOIN horas_extras h
            ON h.funcionario_id = f.id
            AND substr(h.data, 1, 7) = ?
        GROUP BY f.id, f.nome
        ORDER BY f.nome
    """, (mes,))

    funcionarios = cursor.fetchall()

    cursor.execute("""
        SELECT COALESCE(SUM(total_horas),0)
        FROM horas_extras
        WHERE substr(data,1,7)=?
    """, (mes,))

    total_geral = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "horas_extras.html",
        funcionarios=funcionarios,
        mes=mes,
        total_geral=total_geral
    )

@app.route("/horas-extras/funcionario/<int:id>")
def horas_extras_funcionario(id):
    mes = request.args.get("mes", datetime.now().strftime("%Y-%m"))

    conn = sqlite3.connect("banco.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM funcionarios_horas WHERE id = ?", (id,))
    funcionario = cursor.fetchone()

    cursor.execute("""
        SELECT *
        FROM horas_extras
        WHERE funcionario_id = ?
        AND substr(data, 1, 7) = ?
        ORDER BY data DESC
    """, (id, mes))

    registros = cursor.fetchall()

    cursor.execute("""
        SELECT COALESCE(SUM(total_horas), 0)
        FROM horas_extras
        WHERE funcionario_id = ?
        AND substr(data, 1, 7) = ?
    """, (id, mes))

    total_mes = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "horas_extras_funcionario.html",
        funcionario=funcionario,
        registros=registros,
        total_mes=total_mes,
        mes=mes
    )


@app.route("/horas-extras/funcionario/novo", methods=["POST"])
def novo_funcionario_horas():
    nome = request.form["nome"].strip()

    if nome:
        conn = sqlite3.connect("banco.db")
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR IGNORE INTO funcionarios_horas (nome)
            VALUES (?)
        """, (nome,))

        conn.commit()
        conn.close()

    return redirect("/horas-extras")


@app.route("/horas-extras/cadastrar/<int:funcionario_id>", methods=["POST"])
def cadastrar_hora_extra(funcionario_id):
    data = request.form["data"]
    hora_inicio = request.form["hora_inicio"]
    hora_fim = request.form["hora_fim"]
    observacao = request.form.get("observacao", "")

    total = calcular_total_horas(hora_inicio, hora_fim)

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO horas_extras (
            funcionario_id,
            data,
            hora_inicio,
            hora_fim,
            total_horas,
            observacao
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        funcionario_id,
        data,
        hora_inicio,
        hora_fim,
        total,
        observacao
    ))

    conn.commit()
    conn.close()

    return redirect(f"/horas-extras/funcionario/{funcionario_id}?mes={data[:7]}")

@app.route("/horas-extras/excluir/<int:id>", methods=["POST"])
def excluir_hora_extra(id):

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT funcionario_id, data
        FROM horas_extras
        WHERE id = ?
    """, (id,))

    registro = cursor.fetchone()

    if registro:
        funcionario_id = registro[0]
        mes = registro[1][:7]

        cursor.execute("""
            DELETE FROM horas_extras
            WHERE id = ?
        """, (id,))

        conn.commit()
        conn.close()

        return redirect(
            f"/horas-extras/funcionario/{funcionario_id}?mes={mes}"
        )

    conn.close()

    return redirect("/horas-extras")

@app.route("/pdde")
def pdde():
    return render_template("pdde.html")

@app.route("/pdde/pdf", methods=["POST"])
def pdde_pdf():
    
    arquivos = request.files.getlist("pdde_pdf")
    if not arquivos:
        return render_template("pdde.html", erro="Envie o PDF do PDDE.")

    planilhas = []
    for arquivo in arquivos:
        
        nome_seguro = secure_filename(arquivo.filename)
        id_execucao = str(uuid.uuid4())[:8]
        
        conta_caixa = request.form.get(f"conta_caixa_{arquivo.filename}", "").strip()
        conta_receita = request.form.get(f"conta_receita_{arquivo.filename}", "").strip()
        
        caminho_pdf = os.path.join(PASTA_UPLOAD_PDDE, f"{id_execucao}_{nome_seguro}")
        
        arquivo.save(caminho_pdf)

        caminho_saida = os.path.join(PASTA_SAIDA_PDDE, f"importacao_pdde_{id_execucao}.xlsx")
    
        gerador = gerar_planilha_importacao(
            caminho_pdde_pdf=caminho_pdf,
            caminho_plano_pdf=PLANO_CONTAS_PDDE,
            caminho_modelo_xlsx=MODELO_IMPORTACAO_CONTMATIC,
            caminho_saida_xlsx=caminho_saida,
            conta_caixa=conta_caixa,
            conta_receita_pdde=conta_receita,
        )
        if "400" in gerador:
            flash(f"{gerador["400"]}", "erro")
            return redirect("/pdde")
            
        df = pd.read_excel(caminho_saida, header=None, skiprows=2)
        planilhas.append(df)
        
    id_execucao = str(uuid.uuid4())[:8]
    planilha_resultado = os.path.join(PASTA_SAIDA_PDDE, f"{id_execucao}_importacao_pdde.xlsx")
    
    resultado = pd.concat(planilhas, ignore_index=True)
    resultado.to_excel(planilha_resultado, index=False, header=False)

    return send_file(planilha_resultado, as_attachment=True, download_name="importacao_pdde.xlsx")

@app.route("/pdde/manual", methods=["POST"])
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

    for tipo, data, historico, descricao, valor in zip(tipos, datas, historicos, descricoes, valores):
        if data and historico and valor:
            lancamentos.append({
                "tipo": tipo,
                "data": data,
                "historico": historico,
                "descricao": descricao,
                "valor": float(valor.replace(",", "."))
            })

    id_execucao = str(uuid.uuid4())[:8]
    caminho_saida = os.path.join(PASTA_SAIDA_PDDE, f"importacao_pdde_manual_{id_execucao}.xlsx")

    gerador = gerar_planilha_manual_pdde(
        caminho_plano_pdf=PLANO_CONTAS_PDDE,
        caminho_modelo_xlsx=MODELO_IMPORTACAO_CONTMATIC,
        caminho_saida_xlsx=caminho_saida,
        conta_caixa=conta_caixa,
        conta_receita_pdde=conta_receita,
        saldo_inicial=saldo_inicial,
        lancamentos=lancamentos
    )

    if "400" in gerador:
        flash(f"{gerador["400"]}", "erro")
        return redirect("/pdde")

    return send_file(caminho_saida, as_attachment=True, download_name="importacao_pdde_manual.xlsx")

@app.route("/pdde/plano_de_contas")
def pdde_vizualizar_plano_contas():
    return send_file(PLANO_CONTAS_PDDE, as_attachment=False)

def executar_ocr(id_execucao, entrada, saida, nome_original):

    try:

        ocrmypdf.ocr(
            entrada,
            saida,
            language="por",
            deskew=True
        )

        tarefas_ocr[id_execucao] = {
            "status": "concluido",
            "arquivo": saida,
            "nome": nome_original
        }

    except Exception as e:

        tarefas_ocr[id_execucao] = {
            "status": "erro",
            "erro": str(e)
        }

@app.route("/ocr", methods=["GET", "POST"])
def ocr():

    if request.method == "POST":

        arquivos = request.files.getlist("pdfs")
        
        if not arquivos:
            return jsonify({"erro": "Envie o PDF."})
        
        ids = []

        for arquivo in arquivos:
            nome_seguro = secure_filename(arquivo.filename)
            id_execucao = str(uuid.uuid4())[:8]
            ids.append(id_execucao)

            entrada = os.path.join(
                PASTA_UPLOAD_PDF,
                f"{id_execucao}_{nome_seguro}"
            )

            saida = os.path.join(
                PASTA_SAIDA_PDF,
                f"ocr_pdf_{id_execucao}.pdf"
            )

            arquivo.save(entrada)

            tarefas_ocr[id_execucao] = {
                "status":"processando",
            }

            thread = threading.Thread(
                target=executar_ocr,
                args=(
                    id_execucao,
                    entrada,
                    saida,
                    nome_seguro
                )
            )
            thread.start()

        return jsonify({
            "ids": ids
        })
        #return send_file(
            #saida,
            #as_attachment=True,
            #download_name=f"OCR_{nome_seguro}"
        #)

    return render_template("ocr.html")

@app.route("/download/<id_execucao>")
def download(id_execucao):

    arquivo = tarefas_ocr[id_execucao]["arquivo"]
    nome_seguro = tarefas_ocr[id_execucao]["nome"]

    return send_file(
        arquivo,
        as_attachment=True,
        download_name=f"OCR_{nome_seguro}"
    )

@app.route("/status/<id_execucao>")
def status(id_execucao):

    return jsonify(
        tarefas_ocr.get(
            id_execucao,
            {
                "status":"processando"
            }
        )
    )

@app.route("/ajuda-esocial")
def esocial():
    
    busca = request.args.get("busca", "")

    conn = sqlite3.connect("banco.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if busca:

        cursor.execute("""
            SELECT id, codigo, descriminador, solucao
            FROM esocial
            WHERE codigo LIKE ?
            OR descriminador LIKE ?
            ORDER BY codigo
        
        """, (f"%{busca}%", f"%{busca}%"))
    
    else:
        cursor.execute("""
            SELECT * FROM esocial
            ORDER BY codigo
        """)
    
    erros = cursor.fetchall()
    conn.close()

    return render_template("esocial.html", erros=erros)

@app.route("/ajuda-esocial/cadastrar", methods=["POST"])
def esocial_cadastrar():
    
    codigo = request.form["codigo"]
    descriminador = request.form["descriminador"]
    solucao = request.form["solucao"]
    
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO esocial
        (codigo, descriminador, solucao)
        VALUES (?, ?, ?)
    """, (codigo, descriminador, solucao))
    
    conn.commit()
    conn.close()
    
    flash(f"Erro {codigo} cadastrado com sucesso.", "success")
    return redirect("/ajuda-esocial")

@app.route("/ajuda-esocial/excluir/<id>", methods=["POST"])
def esocial_excluir(id):

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, codigo
        FROM esocial
        WHERE id = ?
    """, (id,))

    erro = cursor.fetchone()

    if erro:
        codigo = erro[1]
        
        cursor.execute("""
            DELETE FROM esocial
            WHERE id = ?
        """, (id,))

        conn.commit()
        conn.close()

        flash(f"Erro {codigo} excluido com sucesso.", "success")
        return redirect("/ajuda-esocial")

    conn.close()


if __name__ == "__main__":
    print("Iniciando o sitema...")
    print(f"[OK] IP do servidor: {socket.gethostbyname(socket.gethostname())}")
    serve(app, host="0.0.0.0", port=8080, threads=8)
