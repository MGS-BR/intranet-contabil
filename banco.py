import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BANCO = str(BASE_DIR / "banco.db")


def conectar():
    return sqlite3.connect(BANCO)


def adicionar_coluna(cursor, tabela, coluna, tipo):
    cursor.execute(f"PRAGMA table_info({tabela})")
    colunas = [c[1] for c in cursor.fetchall()]
    if coluna not in colunas:
        cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")


def criar_tabelas():
    conn = conectar()
    cursor = conn.cursor()

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
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_empresas_cnpj_unico ON empresas(cnpj)"
        )
    except sqlite3.OperationalError:
        print(
            "Aviso: não foi possível criar índice único em empresas.cnpj. Verifique CNPJs duplicados."
        )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS socios_empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj_empresa TEXT,
            nome TEXT,
            qualificacao TEXT
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_socios_cnpj ON socios_empresas(cnpj_empresa)"
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS funcionarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            ativo BOOLEAN DEFAULT TRUE,
            funcao TEXT,
            descricao TEXT
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
            FOREIGN KEY (funcionario_id) REFERENCES funcionarios(id)
        )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS esocial (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT NOT NULL,
        descriminador TEXT,
        solucao TEXT
    )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            descricao TEXT,
            data TEXT NOT NULL,
            cor TEXT DEFAULT '#2f5d8a',
            recorrencia TEXT NOT NULL DEFAULT 'nenhuma',
            criado_em TEXT
        )
    """)

    conn.commit()
    conn.close()
    print("Banco criado/atualizado com sucesso.")


def ver_tabelas():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    for (nome,) in cursor.fetchall():
        print(nome)
    conn.close()


def ver_conteudo():
    nome = input("Digite o nome da tabela: ").strip()
    if not nome.replace("_", "").isalnum():
        print("Nome de tabela inválido.")
        return

    conn = conectar()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT * FROM {nome} LIMIT 100")
        for linha in cursor.fetchall():
            print(dict(linha))
    except sqlite3.Error as e:
        print("Erro:", e)
    finally:
        conn.close()


def apagar_tabelas():

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = OFF")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tabelas = [t[0] for t in cursor.fetchall() if t[0] != "sqlite_sequence"]
    for nome in tabelas:
        cursor.execute(f"DROP TABLE IF EXISTS {nome}")
    conn.commit()
    conn.close()
    print("Todas as tabelas foram removidas.")


def menu():
    print("\nSelecione uma opção:")
    print("[1] Apagar tabelas")
    print("[2] Criar/atualizar tabelas")
    print("[3] Ver tabelas")
    print("[4] Ver conteúdo de uma tabela")

    escolha = input("Opção: ").strip()

    if escolha == "1":
        apagar_tabelas()
        criar_tabelas()
    elif escolha == "2":
        criar_tabelas()
    elif escolha == "3":
        ver_tabelas()
    elif escolha == "4":
        ver_conteudo()
    else:
        print("Opção inválida.")


if __name__ == "__main__":
    menu()
