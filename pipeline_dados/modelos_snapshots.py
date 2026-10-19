"""Mapeamento das tabelas existentes ``snapshots_acoes`` e ``snapshots_fiis``.

As tabelas ja existem no Neon. Este modulo apenas as descreve para o
SQLAlchemy; nao cria, nao migra e nao altera o schema. Usa um
``declarative_base`` proprio para que ``create_all`` de outros metadados
nunca toque nessas tabelas.

Colunas e uniques conforme dump do catalogo PostgreSQL (2026-10-19):

* unique ``uix_snapshots_acoes`` / ``uix_snapshots_fiis`` em
  ``(ativo_id, data_referencia)``;
* NOT NULL: ``id``, ``ativo_id``, ``data_referencia``, ``data_coleta``;
* indicadores numericos anulaveis; ``walt`` e ``alavancagem`` sao varchar
  e o diario de mercado nao os preenche;
* sem FK declarada aqui (isolamento de metadata); em producao a FK
  ``ativo_id -> ativos(id)`` ja existe.

Nenhuma coluna extra e presumida.
"""

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

BaseSnapshots = declarative_base()


class SnapshotAcao(BaseSnapshots):
    __tablename__ = "snapshots_acoes"
    __table_args__ = (
        UniqueConstraint("ativo_id", "data_referencia", name="uix_snapshots_acoes"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ativo_id = Column(Integer, nullable=False)
    data_referencia = Column(Date, nullable=False)
    data_coleta = Column(DateTime, nullable=False)
    data_publicacao = Column(Date, nullable=True)
    fonte = Column(String, nullable=True)
    url_origem = Column(String, nullable=True)
    fonte_primaria = Column(String, nullable=True)
    fonte_intermediaria = Column(String, nullable=True)

    preco = Column(Numeric, nullable=True)
    dy = Column(Numeric, nullable=True)
    pl = Column(Numeric, nullable=True)
    pvp = Column(Numeric, nullable=True)
    p_ativo = Column(Numeric, nullable=True)
    marg_bruta = Column(Numeric, nullable=True)
    marg_ebit = Column(Numeric, nullable=True)
    marg_liquida = Column(Numeric, nullable=True)
    p_ebit = Column(Numeric, nullable=True)
    ev_ebit = Column(Numeric, nullable=True)
    div_liq_ebit = Column(Numeric, nullable=True)
    div_liq_patrimonio = Column(Numeric, nullable=True)
    psr = Column(Numeric, nullable=True)
    p_cap_giro = Column(Numeric, nullable=True)
    p_at_circ_liq = Column(Numeric, nullable=True)
    liq_corrente = Column(Numeric, nullable=True)
    roe = Column(Numeric, nullable=True)
    roa = Column(Numeric, nullable=True)
    roic = Column(Numeric, nullable=True)
    cagr_rec_5a = Column(Numeric, nullable=True)
    liq_media = Column(Numeric, nullable=True)
    vpa = Column(Numeric, nullable=True)
    lpa = Column(Numeric, nullable=True)
    peg_ratio = Column(Numeric, nullable=True)
    valor_mercado = Column(Numeric, nullable=True)
    cagr_lucro_5a = Column(Numeric, nullable=True)
    patrimonio_ativos = Column(Numeric, nullable=True)
    passivos_ativos = Column(Numeric, nullable=True)
    giro_ativos = Column(Numeric, nullable=True)


class SnapshotFii(BaseSnapshots):
    __tablename__ = "snapshots_fiis"
    __table_args__ = (
        UniqueConstraint("ativo_id", "data_referencia", name="uix_snapshots_fiis"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ativo_id = Column(Integer, nullable=False)
    data_referencia = Column(Date, nullable=False)
    data_coleta = Column(DateTime, nullable=False)
    data_publicacao = Column(Date, nullable=True)
    fonte = Column(String, nullable=True)
    url_origem = Column(String, nullable=True)
    preco = Column(Numeric, nullable=True)
    pvp = Column(Numeric, nullable=True)
    dy = Column(Numeric, nullable=True)
    qtd_imoveis = Column(Integer, nullable=True)
    walt = Column(String, nullable=True)
    alavancagem = Column(String, nullable=True)
    liquidez = Column(Numeric, nullable=True)
    vpa = Column(Numeric, nullable=True)
    lucro_12m = Column(Numeric, nullable=True)
    dividendo_mensal = Column(Numeric, nullable=True)
    fonte_primaria = Column(String, nullable=True)
    fonte_intermediaria = Column(String, nullable=True)
