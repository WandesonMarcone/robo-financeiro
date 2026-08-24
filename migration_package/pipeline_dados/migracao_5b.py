"""Migração versionada e reversível do Bloco 5B (Fase 3).

Cria as tabelas da modelagem dos indicadores de mercado definida no Bloco 5A:
``ativos_perfil``, ``snapshots_fiis``, ``snapshots_acoes`` e
``ativos_inquilinos``. NÃO altera nem remove nenhuma tabela existente e NÃO
migra dados.

Propriedades:
- Versionada: registra a aplicação na tabela ``schema_migrations`` (chave =
  MIGRACAO_ID), permitindo auditar o que foi aplicado.
- Reversível: ``reverter()`` remove somente as tabelas criadas por esta
  migração e a versão correspondente.
- Idempotente: rodar ``aplicar()``/``reverter()`` mais de uma vez não gera
  erro nem duplicata.
- Reutiliza as definições ORM (pipeline_dados.banco_dados) — sem duplicar o
  DDL das colunas.

Observação sobre produção: o startup (main.py) executa
``Base.metadata.create_all``, que já cria tabelas faltantes de forma aditiva.
Esta migração é o caminho explícito/versionado para ambientes controlados e o
alvo dos testes de schema/rollback deste bloco.
"""
import logging

from sqlalchemy import Column, DateTime, MetaData, String, Table, func
from sqlalchemy.engine import Connection, Engine

from pipeline_dados.banco_dados import Base

logger = logging.getLogger(__name__)

MIGRACAO_ID = "5b_snapshots_mercado"

# Todas as novas tabelas referenciam apenas ``ativos`` (já existente), por isso
# a ordem abaixo não depende de FKs entre si.
TABELAS_5B = ("ativos_perfil", "snapshots_fiis", "snapshots_acoes", "ativos_inquilinos")

TABELA_MIGRACOES = "schema_migrations"

_meta = MetaData()
schema_migrations = Table(
    TABELA_MIGRACOES,
    _meta,
    Column("version", String(80), primary_key=True),
    Column("aplicada_em", DateTime, nullable=False, server_default=func.now()),
)


def _garantir_tabela_migracoes(conn: Connection) -> None:
    if not conn.dialect.has_table(conn, TABELA_MIGRACOES):
        schema_migrations.create(conn)


def _migracoes_aplicadas(conn: Connection) -> set[str]:
    _garantir_tabela_migracoes(conn)
    return {row[0] for row in conn.execute(schema_migrations.select())}


def aplicar(engine: Engine, log=None) -> str:
    """Aplica a migração 5B: cria as 4 tabelas novas e registra a versão.

    Idempotente: se a versão já estiver registrada, não faz nada e retorna
    ``"ja_aplicada"``. Retorna ``"aplicada"`` quando a migração foi executada.
    """
    with engine.begin() as conn:
        if MIGRACAO_ID in _migracoes_aplicadas(conn):
            return "ja_aplicada"
        for nome in TABELAS_5B:
            Base.metadata.tables[nome].create(conn, checkfirst=True)
        conn.execute(schema_migrations.insert().values(version=MIGRACAO_ID))
    if log is not None:
        log.info("Migração %s aplicada: %s", MIGRACAO_ID, ", ".join(TABELAS_5B))
    return "aplicada"


def reverter(engine: Engine, log=None) -> str:
    """Reverte a migração 5B: remove as tabelas criadas e a versão registrada.

    Reversível e idempotente: se a versão não estiver registrada, retorna
    ``"nao_aplicada"`` sem efeito. Retorna ``"revertida"`` quando executada.
    """
    with engine.begin() as conn:
        if MIGRACAO_ID not in _migracoes_aplicadas(conn):
            return "nao_aplicada"
        for nome in reversed(TABELAS_5B):
            Base.metadata.tables[nome].drop(conn, checkfirst=True)
        conn.execute(
            schema_migrations.delete().where(schema_migrations.c.version == MIGRACAO_ID)
        )
    if log is not None:
        log.info("Migração %s revertida.", MIGRACAO_ID)
    return "revertida"


def status(engine: Engine) -> dict:
    """Estado da migração: versões aplicadas e tabelas 5B presentes."""
    from sqlalchemy import inspect

    insp = inspect(engine)
    presentes = [nome for nome in TABELAS_5B if insp.has_table(nome)]
    with engine.connect() as conn:
        aplicadas = _migracoes_aplicadas(conn)
    return {
        "migracao": MIGRACAO_ID,
        "aplicada": MIGRACAO_ID in aplicadas,
        "versoes": sorted(aplicadas),
        "tabelas_5b_presentes": presentes,
    }
