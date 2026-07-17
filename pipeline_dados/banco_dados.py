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
    tipo_documento: Mapped[str] = mapped_column(String(255), nullable=False) # 'Relatório Gerencial', 'Fato Relevante'
    
    # ⚠️ ALTERAÇÃO: url_pdf agora é opcional (nullable=True), pois na nova arquitetura da FNET, 
    # o documento entra como PENDENTE no banco ANTES de o upload ser feito para o Drive.
    url_pdf: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    assunto: Mapped[Optional[str]] = mapped_column(String(255)) # Opcional: título do comunicado

    # ==========================================
    # 🆕 MÁQUINA DE ESTADOS & INTELIGÊNCIA ARTIFICIAL (NOVA ARQUITETURA FNET)
    # ==========================================
    id_b3: Mapped[Optional[str]] = mapped_column(String(50), unique=True, nullable=True)
    
    # 🛡️ PROTEÇÃO CVM: O default fica "SALVO". Assim, o coletor_CVM continua salvando
    # direto no banco sem quebrar. O robô da FNET vai inserir como "PENDENTE" manualmente.
    status_processamento: Mapped[str] = mapped_column(String(20), default="SALVO", nullable=False) 
    
    hash_sha256: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    resumo_ia: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # Textos longos gerados pelo Groq
    log_erro: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # Auditoria de falhas
    data_atualizacao: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=True)

    ativo: Mapped["Ativo"] = relationship(back_populates="documentos")