import sqlite3
import os

# Caminho do seu banco
db_path = "pipeline_dados/banco_institucional.db"

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        # Tenta adicionar a coluna
        cursor.execute("ALTER TABLE documentos_qualitativos ADD COLUMN status_processamento VARCHAR")
        conn.commit()
        print("✅ Coluna 'status_processamento' adicionada com sucesso!")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("ℹ️ A coluna já existe, tudo ok!")
        else:
            print(f"❌ Erro ao atualizar banco: {e}")
    finally:
        conn.close()
else:
    print("❌ Arquivo do banco de dados não encontrado no caminho especificado.")