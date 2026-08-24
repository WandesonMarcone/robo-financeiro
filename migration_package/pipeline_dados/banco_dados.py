from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, UniqueConstraint, Enum, Text, Numeric
from sqlalchemy.orm import declarative_base, relationship, Mapped, mapped_column
import enum

Base = declarative_base()

class TipoAtivo(enum.Enum):
    ACAO = "ACAO"
    FII = "FII"

class Ativo(Base):
    __tablename__ = 'ativos'

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    cnpj: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    tipo: Mapped[TipoAtivo] = mapped_column(Enum(TipoAtivo), nullable=False)

    dados_acoes: Mapped[List["DadosFinanceirosAcoes"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")
    dados_fiis: Mapped[List["DadosFinanceirosFiis"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")
    documentos: Mapped[List["DocumentosQualitativos"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")

    # --- Fase 3, Bloco 5B: modelagem dos indicadores de mercado (aditivo) ---
    perfil: Mapped[Optional["AtivoPerfil"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")
    snapshots_fiis: Mapped[list["SnapshotFii"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")
    snapshots_acoes: Mapped[list["SnapshotAcao"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")
    inquilinos: Mapped[list["AtivoInquilino"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")

class DadosFinanceirosAcoes(Base):
    __tablename__ = 'dados_financeiros_acoes'
    __table_args__ = (UniqueConstraint('ativo_id', 'data_referencia', 'tipo_doc', name='uix_dados_acoes'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey('ativos.id'), nullable=False)
    data_referencia: Mapped[date] = mapped_column(Date, nullable=False)
    tipo_doc: Mapped[str] = mapped_column(String(10), nullable=False) # Ex: 'ITR', 'DFP'

    # --- BALANÇO PATRIMONIAL ---
    ativo_total: Mapped[Optional[float]] = mapped_column(Float)
    patrimonio_liquido: Mapped[Optional[float]] = mapped_column(Float)
    caixa: Mapped[Optional[float]] = mapped_column(Float)
    passivo_total: Mapped[Optional[float]] = mapped_column(Float)
    divida_bruta: Mapped[Optional[float]] = mapped_column(Float) # Empréstimos/Debêntures
    divida_curto_prazo: Mapped[Optional[float]] = mapped_column(Float)  # 👈 ADICIONADO
    divida_longo_prazo: Mapped[Optional[float]] = mapped_column(Float)  # 👈 PADRONIZADO
    divida_liquida: Mapped[Optional[float]] = mapped_column(Float)      # 👈 ADICIONADO

    # --- D.R.E (RESULTADOS) ---
    receita: Mapped[Optional[float]] = mapped_column(Float)
    lucro_bruto: Mapped[Optional[float]] = mapped_column(Float)
    ebitda: Mapped[Optional[float]] = mapped_column(Float)
    resultado_financeiro: Mapped[Optional[float]] = mapped_column(Float)
    lucro_liquido: Mapped[Optional[float]] = mapped_column(Float)

    # --- FLUXO DE CAIXA ---
    fco: Mapped[Optional[float]] = mapped_column(Float) # Caixa Operacional

    ativo: Mapped["Ativo"] = relationship(back_populates="dados_acoes")

class DadosFinanceirosFiis(Base):
    __tablename__ = 'dados_financeiros_fiis'
    __table_args__ = (UniqueConstraint('ativo_id', 'data_referencia', name='uix_dados_fiis'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey('ativos.id'), nullable=False)
    data_referencia: Mapped[date] = mapped_column(Date, nullable=False)

    # --- INDICADORES FINANCEIROS (XML Mensal/Trimestral) ---
    patrimonio_liquido: Mapped[Optional[float]] = mapped_column(Float)
    ativo_total: Mapped[Optional[float]] = mapped_column(Float)
    disponibilidades_caixa: Mapped[Optional[float]] = mapped_column(Float)
    rendimento_por_cota: Mapped[Optional[float]] = mapped_column(Float)

    # --- NOVOS INDICADORES DE MERCADO E OPERACIONAIS ---
    cotistas: Mapped[Optional[int]] = mapped_column(Integer)                # Quantidade total de cotistas
    cotas_emitidas: Mapped[Optional[float]] = mapped_column(Float)          # Total de cotas no mercado
    receita_imoveis: Mapped[Optional[float]] = mapped_column(Float)         # Receita bruta de locação/imóveis
    resultado_ligado_venda: Mapped[Optional[float]] = mapped_column(Float)  # Lucro na venda de ativos/imóveis

    # --- INDICADORES FÍSICOS E GERENCIAIS (XML / Informe) ---
    vacancia_fisica: Mapped[Optional[float]] = mapped_column(Float)       # Em Porcentagem (%)
    vacancia_financeira: Mapped[Optional[float]] = mapped_column(Float)   # Em Porcentagem (%)
    despesas_taxas: Mapped[Optional[float]] = mapped_column(Float)        # Taxas de adm/gestão no período

    ativo: Mapped["Ativo"] = relationship(back_populates="dados_fiis")

class DocumentosQualitativos(Base):
    __tablename__ = 'documentos_qualitativos'
    __table_args__ = (UniqueConstraint('ativo_id', 'url_pdf', name='uix_docs_url'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey('ativos.id'), nullable=False, index=True) # 👈 Índice adicionado
    data_publicacao: Mapped[date] = mapped_column(Date, nullable=False, index=True)          # 👈 Índice adicionado para ordenação rápida
    tipo_documento: Mapped[str] = mapped_column(String(255), nullable=False)

    url_pdf: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    texto_extraido: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assunto = Column(Text, nullable=True)
    id_b3: Mapped[Optional[str]] = mapped_column(String(50), unique=True, nullable=True)

    # 🚀 ADICIONADO INDEX=TRUE PARA ACELERAR AS QUERIES DO RAIO-X E DA VARREDURA
    status_processamento: Mapped[str] = mapped_column(String(20), default="SALVO", nullable=False, index=True)

    hash_sha256: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True, index=True)
    resumo_ia: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    log_erro: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data_atualizacao: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=True)

    ativo: Mapped["Ativo"] = relationship(back_populates="documentos")


class AtivoPerfil(Base):
    """Perfil/classificação 1:1 do ativo (Fase 3, Bloco 5B).

    Guarda metadados de classificação que são propriedade do ativo, e não uma
    série temporal: ``setor`` (macro da B3 para ações / segmento para FIIs) e o
    ``tipo_fii`` (Tijolo/Papel/FOF/Híbrido). Um registro por ativo (1:1).

    O Google Sheets permanece a fonte ativa; a população das colunas ocorre no
    Bloco 5C. Criada apenas no Bloco 5B — não altera nenhuma tabela existente.
    """

    __tablename__ = "ativos_perfil"
    __table_args__ = (UniqueConstraint("ativo_id", name="uix_ativos_perfil_ativo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id"), nullable=False)
    setor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tipo_fii: Mapped[str | None] = mapped_column(String(30), nullable=True)
    data_atualizacao: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=True
    )

    ativo: Mapped["Ativo"] = relationship(back_populates="perfil")


class SnapshotFii(Base):
    """Série temporal dos indicadores de mercado de um FII (Fase 3, Bloco 5B).

    Um registro por ``(ativo_id, data_referencia)`` — UNIQUE — capturando os
    indicadores da aba BD_FIIs (preço, P/VP, DY, VPA, liquidez etc.). Valores
    financeiros usam NUMERIC (não FLOAT) para evitar drift em séries.
    """

    __tablename__ = "snapshots_fiis"
    __table_args__ = (UniqueConstraint("ativo_id", "data_referencia", name="uix_snapshots_fiis"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id"), nullable=False, index=True)
    data_referencia: Mapped[date] = mapped_column(Date, nullable=False)
    data_coleta: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    data_publicacao: Mapped[date | None] = mapped_column(Date, nullable=True)
    fonte: Mapped[str | None] = mapped_column(String(60), nullable=True)
    url_origem: Mapped[str | None] = mapped_column(String(500), nullable=True)

    preco: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    pvp: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    dy: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    qtd_imoveis: Mapped[int | None] = mapped_column(Integer)
    walt: Mapped[str | None] = mapped_column(String(30))
    alavancagem: Mapped[str | None] = mapped_column(String(30))
    liquidez: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    vpa: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    lucro_12m: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    dividendo_mensal: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))

    ativo: Mapped["Ativo"] = relationship(back_populates="snapshots_fiis")


class SnapshotAcao(Base):
    """Série temporal dos indicadores de mercado de uma ação (Fase 3, Bloco 5B).

    Um registro por ``(ativo_id, data_referencia)`` — UNIQUE — capturando os
    indicadores da aba BD_Acoes (preço, P/L, P/VP, ROE, margens etc.). Valores
    financeiros usam NUMERIC (não FLOAT) para evitar drift em séries.
    """

    __tablename__ = "snapshots_acoes"
    __table_args__ = (UniqueConstraint("ativo_id", "data_referencia", name="uix_snapshots_acoes"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id"), nullable=False, index=True)
    data_referencia: Mapped[date] = mapped_column(Date, nullable=False)
    data_coleta: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    data_publicacao: Mapped[date | None] = mapped_column(Date, nullable=True)
    fonte: Mapped[str | None] = mapped_column(String(60), nullable=True)
    url_origem: Mapped[str | None] = mapped_column(String(500), nullable=True)

    preco: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    dy: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    pl: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    pvp: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    p_ativo: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    marg_bruta: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    marg_ebit: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    marg_liquida: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    p_ebit: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    ev_ebit: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    div_liq_ebit: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    div_liq_patrimonio: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    psr: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    p_cap_giro: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    p_at_circ_liq: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    liq_corrente: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    roe: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    roa: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    roic: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    cagr_rec_5a: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    liq_media: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    vpa: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    lpa: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    peg_ratio: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    valor_mercado: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))

    ativo: Mapped["Ativo"] = relationship(back_populates="snapshots_acoes")


class AtivoInquilino(Base):
    """Inquilinos de um FII por período (Fase 3, Bloco 5B).

    Lista de principais inquilinos (``nome`` + ``participacao`` estimada). Uma
    linha por ``(ativo_id, nome, data_referencia)``; ``data_referencia``
    identifica a competência do informe de onde os inquilinos foram extraídos.
    """

    __tablename__ = "ativos_inquilinos"
    __table_args__ = (
        UniqueConstraint("ativo_id", "nome", "data_referencia", name="uix_inquilinos_periodo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id"), nullable=False, index=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    participacao: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    data_referencia: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_coleta: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    ativo: Mapped["Ativo"] = relationship(back_populates="inquilinos")
