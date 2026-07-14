import os
import sqlite3
import json
from datetime import datetime

with open("config.json", "r", encoding="utf-8") as arquivo:
    config = json.load(arquivo)

PASTA_RAIZ = config.get("PASTA_ARQUIVOS")
BANCO = "banco.db"

PASTAS_IGNORADAS = {
    "$RECYCLE.BIN",
    "System Volume Information",
    ".git",
    "node_modules",
    "__pycache__",
    ".History",
}

ARQUIVOS_IGNORADOS = {
    "desktop.ini",
    "thumbs.db",
}

conn = sqlite3.connect(BANCO)
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

cursor.execute("PRAGMA table_info(indice_arquivos)")
colunas = [c[1] for c in cursor.fetchall()]

for coluna, tipo in {
    "extensao": "TEXT",
    "tamanho": "INTEGER",
    "modificado_em": "TEXT",
}.items():
    if coluna not in colunas:
        cursor.execute(f"ALTER TABLE indice_arquivos ADD COLUMN {coluna} {tipo}")

cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_indice_nome
    ON indice_arquivos(nome)
""")

cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_indice_caminho
    ON indice_arquivos(caminho)
""")

print("Limpando índice antigo...")
cursor.execute("DELETE FROM indice_arquivos")

contador = 0

if not os.path.isdir(PASTA_RAIZ):
    print(f"[ERRO] Pasta não encontrada: {PASTA_RAIZ}")

else:
    for raiz, pastas, arquivos in os.walk(PASTA_RAIZ):

        pastas[:] = [p for p in pastas if p not in PASTAS_IGNORADAS]

        for arquivo in arquivos:

            nome_lower = arquivo.lower()

            if arquivo.startswith("~$"):
                continue

            if nome_lower in ARQUIVOS_IGNORADOS:
                continue

            if nome_lower.endswith(".lnk"):
                continue

            caminho_completo = os.path.join(raiz, arquivo)

            try:
                stat = os.stat(caminho_completo)

                caminho_relativo = os.path.relpath(caminho_completo, PASTA_RAIZ)

                pasta_relativa = os.path.relpath(raiz, PASTA_RAIZ)

                if pasta_relativa == ".":
                    pasta_relativa = ""

                extensao = os.path.splitext(arquivo)[1].lower()

                try:
                    modificado_em = datetime.fromtimestamp(stat.st_mtime).strftime(
                        "%d/%m/%Y %H:%M"
                    )
                except (OSError, OverflowError, ValueError):
                    modificado_em = "Data inválida"

                cursor.execute(
                    """
                    INSERT INTO indice_arquivos
                    (
                        nome,
                        caminho,
                        pasta,
                        extensao,
                        tamanho,
                        modificado_em
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        arquivo,
                        caminho_relativo,
                        pasta_relativa,
                        extensao,
                        stat.st_size,
                        modificado_em,
                    ),
                )

                contador += 1

                if contador % 5000 == 0:
                    print(f"{contador:,} arquivos indexados...")
                    conn.commit()

            except OSError as e:
                print(f"[IGNORADO] {caminho_completo}")
                print(f"Motivo: {e}")
                continue

conn.commit()
conn.close()

print("\nConcluído.")
print(f"{contador:,} arquivos indexados.")
