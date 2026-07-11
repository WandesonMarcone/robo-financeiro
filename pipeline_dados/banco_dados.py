from datetime import date, datetime
from typing import List, Optional
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, UniqueConstraint, Enum
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

    # Relacionamentos
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
    
    receita: Mapped[Optional[float]] = mapped_column(Float)
    lucro_liquido: Mapped[Optional[float]] = mapped_column(Float)
    ebitda: Mapped[Optional[float]] = mapped_column(Float)
    caixa: Mapped[Optional[float]] = mapped_column(Float)
    passivo_total: Mapped[Optional[float]] = mapped_column(Float)

    ativo: Mapped["Ativo"] = relationship(back_populates="dados_acoes")

class DadosFinanceirosFiis(Base):
    __tablename__ = 'dados_financeiros_fiis'
    __table_args__ = (UniqueConstraint('ativo_id', 'data_referencia', name='uix_dados_fiis'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey('ativos.id'), nullable=False)
    data_referencia: Mapped[date] = mapped_column(Date, nullable=False) # Último dia do mês do informe
    
    patrimonio_liquido: Mapped[Optional[float]] = mapped_column(Float)
    ativo_total: Mapped[Optional[float]] = mapped_column(Float)
    disponibilidades_caixa: Mapped[Optional[float]] = mapped_column(Float)
    rendimento_por_cota: Mapped[Optional[float]] = mapped_column(Float)

    ativo: Mapped["Ativo"] = relationship(back_populates="dados_fiis")

class DocumentosQualitativos(Base):
    __tablename__ = 'documentos_qualitativos'
    # Evita salvar o mesmo link de documento duas vezes para o mesmo ativo
    __table_args__ = (UniqueConstraint('ativo_id', 'url_pdf', name='uix_docs_url'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey('ativos.id'), nullable=False)
    data_publicacao: Mapped[date] = mapped_column(Date, nullable=False)
    tipo_documento: Mapped[str] = mapped_column(String(50), nullable=False) # 'Relatório Gerencial', 'Fato Relevante'
    url_pdf: Mapped[str] = mapped_column(String(500), nullable=False)
    assunto: Mapped[Optional[str]] = mapped_column(String(255)) # Opcional: título do comunicado

    ativo: Mapped["Ativo"] = relationship(back_populates="documentos")
  
