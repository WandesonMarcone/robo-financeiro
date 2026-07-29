from datetime import date, datetime
from typing import List, Optional
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, UniqueConstraint, Enum, Text
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
    ativo_id: Mapped[int] = mapped_column(ForeignKey('ativos.id'), nullable=False)
    data_publicacao: Mapped[date] = mapped_column(Date, nullable=False)
    tipo_documento: Mapped[str] = mapped_column(String(255), nullable=False)

    url_pdf: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    texto_extraido: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assunto = Column(Text, nullable=True)
    id_b3: Mapped[Optional[str]] = mapped_column(String(50), unique=True, nullable=True)
    status_processamento: Mapped[str] = mapped_column(String(20), default="SALVO", nullable=False) 
    hash_sha256: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    resumo_ia: Mapped[Optional[str]] = mapped_column(Text, nullable=True) 
    log_erro: Mapped[Optional[str]] = mapped_column(Text, nullable=True) 
    data_atualizacao: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=True)

    ativo: Mapped["Ativo"] = relationship(back_populates="documentos")