import os
import re
import sqlite3
import unicodedata
import json
from datetime import datetime
from pypdf import PdfReader

with open("config.json", "r", encoding="utf-8") as arquivo:
    config = json.load(arquivo)

PASTA_ARQUIVOS = config["PASTA_ARQUIVOS"]
PASTA_RAIZ = config["PASTA_CLIENTES"]
BANCO = "banco.db"

def normalizar_texto(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.upper().strip()


def limpar_linha(valor):
    return " ".join((valor or "").replace("\n", " ").split()).strip()


def limpar_cnpj(valor):
    numeros = re.sub(r"\D", "", valor or "")
    return numeros if len(numeros) == 14 else ""


def formatar_cnpj(valor):
    numeros = limpar_cnpj(valor)
    if not numeros:
        return ""
    return f"{numeros[:2]}.{numeros[2:5]}.{numeros[5:8]}/{numeros[8:12]}-{numeros[12:]}"


def caminho_relativo(caminho):
    """Salva caminhos relativos a D:\\Escritório, compatíveis com /arquivos."""
    try:
        return os.path.relpath(caminho, PASTA_ARQUIVOS)
    except ValueError:
        return caminho


def ler_texto_pdf(caminho):
    try:
        reader = PdfReader(caminho)
        texto = []
        for pagina in reader.pages:
            texto.append(pagina.extract_text() or "")
        return "\n".join(texto)
    except Exception as e:
        print(f"[ERRO] Não consegui ler PDF: {caminho} - {e}")
        return ""


def linhas_pdf(texto):
    return [limpar_linha(l) for l in texto.splitlines() if limpar_linha(l)]


def valor_apos_rotulo(texto, rotulos, ignorar_valores=None):

    if isinstance(rotulos, str):
        rotulos = [rotulos]

    ignorar = {normalizar_texto(v) for v in (ignorar_valores or [])}
    linhas = linhas_pdf(texto)
    norm_rotulos = [normalizar_texto(r) for r in rotulos]

    for i, linha in enumerate(linhas):
        nlinha = normalizar_texto(linha)

        for rotulo in norm_rotulos:
            if nlinha == rotulo:
                for prox in linhas[i + 1:i + 5]:
                    nprox = normalizar_texto(prox)
                    if nprox and nprox not in ignorar:
                        return prox

            if nlinha.startswith(rotulo + " "):
                valor = linha[len(rotulos[norm_rotulos.index(rotulo)]):].strip(" :-")
                if valor and normalizar_texto(valor) not in ignorar:
                    return valor

    return ""


def eh_cnpj_receita(texto):
    n = normalizar_texto(texto)
    return (
        "CADASTRO NACIONAL DA PESSOA JURIDICA" in n
        and "COMPROVANTE DE INSCRICAO" in n
        and "NOME EMPRESARIAL" in n
        and "SITUACAO CADASTRAL" in n
    )


def eh_qsa_receita(texto):
    n = normalizar_texto(texto)
    return (
        "QUADRO DE SOCIOS" in n
        or "QUADRO DE SOCIOS E ADMINISTRADORES" in n
        or "CONSULTA QUADRO DE SOCIOS" in n
        or ("NOME/NOME EMPRESARIAL" in n and "QUALIFICACAO" in n)
    )


def extrair_dados_cnpj_pdf(caminho):
    texto = ler_texto_pdf(caminho)

    dados = {
        "cnpj": "",
        "razao_social": "",
        "nome_fantasia": "",
        "porte": "",
        "data_abertura": "",
        "situacao_cadastral": "",
        "data_situacao_cadastral": "",
        "natureza_juridica": "",
        "atividade_principal": "",
        "telefone": "",
        "email": "",
        "logradouro": "",
        "numero": "",
        "complemento": "",
        "bairro": "",
        "municipio": "",
        "uf": "",
        "cep": "",
    }

    if not eh_cnpj_receita(texto):
        return dados

    match = re.search(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", texto)
    if match:
        dados["cnpj"] = formatar_cnpj(match.group(0))

    dados["razao_social"] = valor_apos_rotulo(texto, "NOME EMPRESARIAL")
    dados["nome_fantasia"] = valor_apos_rotulo(texto, ["TÍTULO DO ESTABELECIMENTO (NOME DE FANTASIA)", "TITULO DO ESTABELECIMENTO (NOME DE FANTASIA)"])
    dados["porte"] = valor_apos_rotulo(texto, "PORTE")
    dados["data_abertura"] = valor_apos_rotulo(texto, "DATA DE ABERTURA")
    dados["atividade_principal"] = valor_apos_rotulo(texto, ["CÓDIGO E DESCRIÇÃO DA ATIVIDADE ECONÔMICA PRINCIPAL", "CODIGO E DESCRICAO DA ATIVIDADE ECONOMICA PRINCIPAL"])
    dados["natureza_juridica"] = valor_apos_rotulo(texto, ["CÓDIGO E DESCRIÇÃO DA NATUREZA JURÍDICA", "CODIGO E DESCRICAO DA NATUREZA JURIDICA"])
    dados["logradouro"] = valor_apos_rotulo(texto, "LOGRADOURO")
    dados["numero"] = valor_apos_rotulo(texto, ["NÚMERO", "NUMERO"])
    dados["complemento"] = valor_apos_rotulo(texto, "COMPLEMENTO")
    dados["cep"] = valor_apos_rotulo(texto, "CEP")
    dados["bairro"] = valor_apos_rotulo(texto, ["BAIRRO/DISTRITO", "BAIRRO / DISTRITO"])
    dados["municipio"] = valor_apos_rotulo(texto, ["MUNICÍPIO", "MUNICIPIO"])
    dados["uf"] = valor_apos_rotulo(texto, "UF")
    dados["email"] = valor_apos_rotulo(texto, ["ENDEREÇO ELETRÔNICO", "ENDERECO ELETRONICO"])
    dados["telefone"] = valor_apos_rotulo(texto, "TELEFONE")
    dados["situacao_cadastral"] = valor_apos_rotulo(texto, ["SITUAÇÃO CADASTRAL", "SITUACAO CADASTRAL"])
    dados["data_situacao_cadastral"] = valor_apos_rotulo(texto, ["DATA DA SITUAÇÃO CADASTRAL", "DATA DA SITUACAO CADASTRAL"])

    # Limpa valores comuns que não são dados reais.
    for chave, valor in list(dados.items()):
        valor = limpar_linha(valor)
        if valor in {"********", "*****", "*******"}:
            valor = ""
        dados[chave] = valor

    return dados


def extrair_qsa_pdf(caminho):
    texto = ler_texto_pdf(caminho)

    dados = {
        "cnpj": "",
        "razao_social": "",
        "capital_social": "",
        "socios": []
    }

    if not eh_qsa_receita(texto):
        return dados

    match = re.search(r"CNPJ:\s*(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})", texto, re.IGNORECASE)
    if match:
        dados["cnpj"] = formatar_cnpj(match.group(1))

    match = re.search(r"NOME EMPRESARIAL:\s*(.+)", texto, re.IGNORECASE)
    if match:
        dados["razao_social"] = limpar_linha(match.group(1))

    match = re.search(r"CAPITAL SOCIAL:\s*(.+)", texto, re.IGNORECASE)
    if match:
        dados["capital_social"] = limpar_linha(match.group(1))

    blocos = re.findall(
        r"Nome/Nome Empresarial:\s*(.*?)\s*Qualificação:\s*(.*?)(?=Nome/Nome Empresarial:|Para informações|Emitido|Voltar|$)",
        texto,
        re.IGNORECASE | re.DOTALL
    )

    for nome, qualificacao in blocos:
        nome = limpar_linha(nome)
        qualificacao = limpar_linha(qualificacao)

        if nome and qualificacao:
            dados["socios"].append({
                "nome": nome,
                "qualificacao": qualificacao
            })

    return dados


def encontrar_documentos_empresa(pasta_empresa):
    candidatos_cnpj = []
    candidatos_qsa = []

    for nome_arquivo in os.listdir(pasta_empresa):
        caminho = os.path.join(pasta_empresa, nome_arquivo)

        if not os.path.isfile(caminho):
            continue

        if not nome_arquivo.lower().endswith(".pdf"):
            continue

        texto = ler_texto_pdf(caminho)
        modificado = os.path.getmtime(caminho)

        if eh_cnpj_receita(texto):
            candidatos_cnpj.append((modificado, caminho))
            continue

        if eh_qsa_receita(texto):
            candidatos_qsa.append((modificado, caminho))
            continue

    cnpj_arquivo = max(candidatos_cnpj)[1] if candidatos_cnpj else ""
    qsa_arquivo = max(candidatos_qsa)[1] if candidatos_qsa else ""

    return cnpj_arquivo, qsa_arquivo


def encontrar_empresas():
    empresas = {}

    if not os.path.isdir(PASTA_RAIZ):
        print(f"[ERRO] Pasta não encontrada: {PASTA_RAIZ}")
        return empresas

    for nome_empresa in os.listdir(PASTA_RAIZ):
        pasta_empresa = os.path.join(PASTA_RAIZ, nome_empresa)

        if not os.path.isdir(pasta_empresa):
            continue

        cnpj_arquivo, qsa_arquivo = encontrar_documentos_empresa(pasta_empresa)

        empresas[nome_empresa] = {
            "pasta": pasta_empresa,
            "cnpj_arquivo": cnpj_arquivo,
            "qsa_arquivo": qsa_arquivo
        }

    return empresas


def adicionar_coluna(cursor, tabela, coluna, tipo):
    cursor.execute(f"PRAGMA table_info({tabela})")
    colunas = [c[1] for c in cursor.fetchall()]
    if coluna not in colunas:
        cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")


def garantir_tabelas(cursor):
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

    for coluna, tipo in {
        "cnpj": "TEXT",
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
    }.items():
        adicionar_coluna(cursor, "empresas", coluna, tipo)

    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_empresas_cnpj_unico ON empresas(cnpj)")
    except sqlite3.OperationalError:
        print("[AVISO] Não consegui criar índice único em empresas.cnpj. Verifique CNPJs duplicados.")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS socios_empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj_empresa TEXT,
            nome TEXT,
            qualificacao TEXT
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_socios_cnpj ON socios_empresas(cnpj_empresa)")


def salvar_empresas(empresas):
    conn = sqlite3.connect(BANCO)
    cursor = conn.cursor()
    garantir_tabelas(cursor)

    for nome_pasta, arquivos in empresas.items():
        pasta_empresa = arquivos["pasta"]
        cnpj_arquivo = arquivos["cnpj_arquivo"]
        qsa_arquivo = arquivos["qsa_arquivo"]

        if not cnpj_arquivo:
            print(f"[AVISO] Sem CNPJ da Receita na pasta principal: {nome_pasta}")
            continue

        dados_cnpj = extrair_dados_cnpj_pdf(cnpj_arquivo)
        cnpj = dados_cnpj["cnpj"]

        if not cnpj:
            print(f"[ERRO] PDF identificado como CNPJ, mas sem CNPJ extraído: {nome_pasta}")
            continue

        razao_social = dados_cnpj["razao_social"] or nome_pasta

        capital_social = ""
        socios = []

        if qsa_arquivo:
            dados_qsa = extrair_qsa_pdf(qsa_arquivo)

            # Só usa o QSA se ele não tiver CNPJ ou se bater com o CNPJ da Receita.
            if not dados_qsa["cnpj"] or dados_qsa["cnpj"] == cnpj:
                capital_social = dados_qsa["capital_social"]
                socios = dados_qsa["socios"]
            else:
                print(f"[AVISO] QSA ignorado por CNPJ diferente: {nome_pasta}")

        cursor.execute("""
            INSERT INTO empresas (
                cnpj,
                razao_social,
                nome_fantasia,
                porte,
                data_abertura,
                situacao_cadastral,
                data_situacao_cadastral,
                natureza_juridica,
                atividade_principal,
                capital_social,
                telefone,
                email,
                logradouro,
                numero,
                complemento,
                bairro,
                municipio,
                uf,
                cep,
                caminho_empresa,
                cnpj_arquivo,
                qsa_arquivo,
                atualizado_em
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cnpj) DO UPDATE SET
                razao_social = excluded.razao_social,
                nome_fantasia = excluded.nome_fantasia,
                porte = excluded.porte,
                data_abertura = excluded.data_abertura,
                situacao_cadastral = excluded.situacao_cadastral,
                data_situacao_cadastral = excluded.data_situacao_cadastral,
                natureza_juridica = excluded.natureza_juridica,
                atividade_principal = excluded.atividade_principal,
                capital_social = excluded.capital_social,
                telefone = excluded.telefone,
                email = excluded.email,
                logradouro = excluded.logradouro,
                numero = excluded.numero,
                complemento = excluded.complemento,
                bairro = excluded.bairro,
                municipio = excluded.municipio,
                uf = excluded.uf,
                cep = excluded.cep,
                caminho_empresa = excluded.caminho_empresa,
                cnpj_arquivo = excluded.cnpj_arquivo,
                qsa_arquivo = excluded.qsa_arquivo,
                atualizado_em = excluded.atualizado_em
        """, (
            cnpj,
            razao_social,
            dados_cnpj["nome_fantasia"],
            dados_cnpj["porte"],
            dados_cnpj["data_abertura"],
            dados_cnpj["situacao_cadastral"],
            dados_cnpj["data_situacao_cadastral"],
            dados_cnpj["natureza_juridica"],
            dados_cnpj["atividade_principal"],
            capital_social,
            dados_cnpj["telefone"],
            dados_cnpj["email"],
            dados_cnpj["logradouro"],
            dados_cnpj["numero"],
            dados_cnpj["complemento"],
            dados_cnpj["bairro"],
            dados_cnpj["municipio"],
            dados_cnpj["uf"],
            dados_cnpj["cep"],
            caminho_relativo(pasta_empresa),
            caminho_relativo(cnpj_arquivo),
            caminho_relativo(qsa_arquivo) if qsa_arquivo else "",
            datetime.now().strftime("%d/%m/%Y %H:%M")
        ))

        cursor.execute(
            "DELETE FROM socios_empresas WHERE cnpj_empresa = ?",
            (cnpj,)
        )

        for socio in socios:
            cursor.execute("""
                INSERT INTO socios_empresas (
                    cnpj_empresa,
                    nome,
                    qualificacao
                )
                VALUES (?, ?, ?)
            """, (
                cnpj,
                socio["nome"],
                socio["qualificacao"]
            ))

        print(f"[OK] {cnpj} - {razao_social}")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    empresas = encontrar_empresas()
    salvar_empresas(empresas)

    print(f"\n{len(empresas)} pastas analisadas.")
