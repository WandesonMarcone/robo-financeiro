import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

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

    dados_acoes: Mapped[list["DadosFinanceirosAcoes"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")
    dados_fiis: Mapped[list["DadosFinanceirosFiis"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")
    documentos: Mapped[list["DocumentosQualitativos"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")

    # --- Fase 3, Bloco 5B: modelagem dos indicadores de mercado (aditivo) ---
    perfil: Mapped[Optional["AtivoPerfil"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")
    snapshots_fiis: Mapped[list["SnapshotFii"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")
    snapshots_acoes: Mapped[list["SnapshotAcao"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")
    inquilinos: Mapped[list["AtivoInquilino"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")

    # --- Fase 4: motor de qualidade e alertas (aditivo) ---
    indicadores_historico: Mapped[list["IndicadorHistorico"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")
    alertas_eventos: Mapped[list["AlertaEvento"]] = relationship(back_populates="ativo", cascade="all, delete-orphan")

class DadosFinanceirosAcoes(Base):
    __tablename__ = 'dados_financeiros_acoes'
    __table_args__ = (UniqueConstraint('ativo_id', 'data_referencia', 'tipo_doc', name='uix_dados_acoes'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey('ativos.id'), nullable=False)
    data_referencia: Mapped[date] = mapped_column(Date, nullable=False)
    tipo_doc: Mapped[str] = mapped_column(String(10), nullable=False) # Ex: 'ITR', 'DFP'

    # --- BALANÇO PATRIMONIAL ---
    ativo_total: Mapped[float | None] = mapped_column(Float)
    patrimonio_liquido: Mapped[float | None] = mapped_column(Float)
    caixa: Mapped[float | None] = mapped_column(Float)
    passivo_total: Mapped[float | None] = mapped_column(Float)
    divida_bruta: Mapped[float | None] = mapped_column(Float) # Empréstimos/Debêntures
    divida_curto_prazo: Mapped[float | None] = mapped_column(Float)  # 👈 ADICIONADO
    divida_longo_prazo: Mapped[float | None] = mapped_column(Float)  # 👈 PADRONIZADO
    divida_liquida: Mapped[float | None] = mapped_column(Float)      # 👈 ADICIONADO

    # --- D.R.E (RESULTADOS) ---
    receita: Mapped[float | None] = mapped_column(Float)
    lucro_bruto: Mapped[float | None] = mapped_column(Float)
    ebitda: Mapped[float | None] = mapped_column(Float)
    resultado_financeiro: Mapped[float | None] = mapped_column(Float)
    lucro_liquido: Mapped[float | None] = mapped_column(Float)

    # --- FLUXO DE CAIXA ---
    fco: Mapped[float | None] = mapped_column(Float) # Caixa Operacional

    ativo: Mapped["Ativo"] = relationship(back_populates="dados_acoes")

class DadosFinanceirosFiis(Base):
    __tablename__ = 'dados_financeiros_fiis'
    __table_args__ = (UniqueConstraint('ativo_id', 'data_referencia', name='uix_dados_fiis'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey('ativos.id'), nullable=False)
    data_referencia: Mapped[date] = mapped_column(Date, nullable=False)

    # --- INDICADORES FINANCEIROS (XML Mensal/Trimestral) ---
    patrimonio_liquido: Mapped[float | None] = mapped_column(Float)
    ativo_total: Mapped[float | None] = mapped_column(Float)
    disponibilidades_caixa: Mapped[float | None] = mapped_column(Float)
    rendimento_por_cota: Mapped[float | None] = mapped_column(Float)

    # --- NOVOS INDICADORES DE MERCADO E OPERACIONAIS ---
    cotistas: Mapped[int | None] = mapped_column(Integer)                # Quantidade total de cotistas
    cotas_emitidas: Mapped[float | None] = mapped_column(Float)          # Total de cotas no mercado
    receita_imoveis: Mapped[float | None] = mapped_column(Float)         # Receita bruta de locação/imóveis
    resultado_ligado_venda: Mapped[float | None] = mapped_column(Float)  # Lucro na venda de ativos/imóveis

    # --- INDICADORES FÍSICOS E GERENCIAIS (XML / Informe) ---
    vacancia_fisica: Mapped[float | None] = mapped_column(Float)       # Em Porcentagem (%)
    vacancia_financeira: Mapped[float | None] = mapped_column(Float)   # Em Porcentagem (%)
    despesas_taxas: Mapped[float | None] = mapped_column(Float)        # Taxas de adm/gestão no período

    ativo: Mapped["Ativo"] = relationship(back_populates="dados_fiis")

class DocumentosQualitativos(Base):
    __tablename__ = 'documentos_qualitativos'
    __table_args__ = (UniqueConstraint('ativo_id', 'url_pdf', name='uix_docs_url'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey('ativos.id'), nullable=False, index=True) # 👈 Índice adicionado
    data_publicacao: Mapped[date] = mapped_column(Date, nullable=False, index=True)          # 👈 Índice adicionado para ordenação rápida
    tipo_documento: Mapped[str] = mapped_column(String(255), nullable=False)

    url_pdf: Mapped[str | None] = mapped_column(String(500), nullable=True)
    texto_extraido: Mapped[str | None] = mapped_column(Text, nullable=True)
    assunto = Column(Text, nullable=True)
    id_b3: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)

    # 🚀 ADICIONADO INDEX=TRUE PARA ACELERAR AS QUERIES DO RAIO-X E DA VARREDURA
    status_processamento: Mapped[str] = mapped_column(String(20), default="SALVO", nullable=False, index=True)

    hash_sha256: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    resumo_ia: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_atualizacao: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=True)

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


class IndicadorHistorico(Base):
    """Estado mais recente de um indicador de um ativo — Fase 4 (aditivo).

    Uma linha por ``(ativo_id, indicador)``. O registro não é re-escrito quando
    o valor não muda: execuções sem alteração apenas atualizam
    ``ultima_coleta``. Quando o valor muda, ``valor_anterior``,
    ``variacao_percentual`` e ``data_ultima_alteracao`` são atualizados,
    permitindo detectar alterações e comparar o valor atual com o anterior.
    """

    __tablename__ = "indicadores_historico"
    __table_args__ = (UniqueConstraint("ativo_id", "indicador", name="uix_indicadores_historico"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id"), nullable=False, index=True)
    tipo_ativo: Mapped[str] = mapped_column(String(10), nullable=False)
    indicador: Mapped[str] = mapped_column(String(40), nullable=False)
    valor_atual: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    valor_anterior: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    variacao_percentual: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    data_referencia: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_ultima_alteracao: Mapped[date | None] = mapped_column(Date, nullable=True)
    ultima_coleta: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    origem: Mapped[str | None] = mapped_column(String(60), nullable=True)

    ativo: Mapped["Ativo"] = relationship(back_populates="indicadores_historico")


class AlertaEvento(Base):
    """Evento de alerta gerado pelo motor da Fase 4 (aditivo).

    Registra a ocorrência classificada (QUALIDADE / MERCADO / CRITICO) para um
    indicador de um ativo, com o valor anterior/atual e a variação, preservando
    origem e timestamp. É a base consumível pela camada de inteligência futura
    (motor de IA, dashboards, relatórios), mantendo a Fase 4 autocontida.
    """

    __tablename__ = "alertas_eventos"
    __table_args__ = (UniqueConstraint("ativo_id", "indicador", "data_evento", name="uix_alertas_evento"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo_alerta: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    tipo_ativo: Mapped[str] = mapped_column(String(10), nullable=False)
    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id"), nullable=False, index=True)
    indicador: Mapped[str] = mapped_column(String(40), nullable=False)
    valor_anterior: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    valor_atual: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    variacao_percentual: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    regra: Mapped[str] = mapped_column(String(60), nullable=False)
    motivo: Mapped[str] = mapped_column(String(255), nullable=False)
    severidade: Mapped[str] = mapped_column(String(20), nullable=False)
    recomendacao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    origem: Mapped[str | None] = mapped_column(String(60), nullable=True)
    data_referencia: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_evento: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    telegram_enviado: Mapped[bool] = mapped_column(default=False, nullable=False)

    ativo: Mapped["Ativo"] = relationship(back_populates="alertas_eventos")


# ==========================================
# FASE 5 — USUÁRIOS, AUTENTICAÇÃO, AUTORIZAÇÃO E ADMINISTRAÇÃO
# ==========================================
# Modelos aditivos: nenhuma tabela existente é alterada. Apenas guardam
# referências com hash de segredos — senha, token e chave de API nunca são
# persistidos em texto puro.


class Usuario(Base):
    """Usuário do sistema (Fase 5, aditivo).

    Identidade única usada pela autenticação futura (web, API e Telegram).
    ``senha_hash`` guarda apenas o hash — nunca a senha. ``email`` e
    ``telegram_user_id`` são únicos somente quando informados (múltiplos NULLs
    são permitidos tanto no SQLite quanto no PostgreSQL).
    """

    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    senha_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    papel: Mapped[str] = mapped_column(String(30), default="USER", nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ultimo_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    sessoes: Mapped[list["Sessao"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan", passive_deletes=True
    )
    chaves_api: Mapped[list["ChaveApi"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan", passive_deletes=True
    )
    auditoria: Mapped[list["AuditoriaAcesso"]] = relationship(
        back_populates="usuario", passive_deletes=True
    )


class Sessao(Base):
    """Sessão de autenticação (Fase 5, aditivo).

    Persiste somente ``token_hash`` (hash do token bruto): o token em si nunca
    é gravado. ``expira_em`` permite expirar sessões e ``revogada`` permite
    logout/revogação sem apagar o histórico.
    """

    __tablename__ = "sessoes"
    __table_args__ = (Index("ix_sessoes_usuario_revogada", "usuario_id", "revogada"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    criada_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    expira_em: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    revogada: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    origem: Mapped[str | None] = mapped_column(String(30), nullable=True)

    usuario: Mapped["Usuario"] = relationship(back_populates="sessoes")


class ChaveApi(Base):
    """Chave de API para integrações (Fase 5, aditivo).

    A chave original é exibida apenas no momento da criação e nunca é
    persistida: somente ``chave_hash``. ``expira_em`` opcional permite rotação
    e expiração programada.
    """

    __tablename__ = "chaves_api"
    __table_args__ = (Index("ix_chaves_api_usuario_ativa", "usuario_id", "ativa"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rotulo: Mapped[str] = mapped_column(String(255), nullable=False)
    chave_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expira_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    usuario: Mapped["Usuario"] = relationship(back_populates="chaves_api")


class AuditoriaAcesso(Base):
    """Trilha de auditoria de acesso (Fase 5, aditivo).

    Registro imutável de eventos de acesso (login, logout, uso de chave de
    API, tentativa negada etc.). NUNCA armazena senha, token, chave de API ou
    qualquer segredo — apenas descrição da ação, alvo, detalhe e resultado.
    A exclusão de um usuário preserva os registros (usuario_id vira NULL).
    """

    __tablename__ = "auditoria_acesso"
    __table_args__ = (Index("ix_auditoria_usuario_criado", "usuario_id", "criado_em"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True
    )
    acao: Mapped[str] = mapped_column(String(60), nullable=False)
    alvo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    sucesso: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False, index=True
    )

    usuario: Mapped["Usuario | None"] = relationship(back_populates="auditoria")
