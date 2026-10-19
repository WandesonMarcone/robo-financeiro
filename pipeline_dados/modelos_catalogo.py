"""Modelos do catalogo central de empresas, ativos e taxonomia.

Este modulo apenas descreve tabelas NOVAS, de forma aditiva. Ele nao altera a
tabela existente ``ativos`` (que continua sendo a unica dona dos dados
financeiros por ticker), nao executa ``create_all`` e nao aplica migracoes. A
criacao em producao (Neon) e feita manualmente pelas migracoes
``0005_catalogo_empresas.sql`` e ``0006_cache_logos_telegram.sql``.

Decisoes de modelagem:

* ``empresas`` representa a pessoa juridica/emissor. PETR3 e PETR4 sao ativos
  distintos, mas apontam para a MESMA empresa via ``empresa_ativos``;
* os dados financeiros continuam em ``ativos`` e nas tabelas
  ``dados_financeiros_*``. Nenhum compartilhamento de logo mistura cotacoes;
* ``empresa_segmentos`` e ``empresa_atividades`` guardam o vinculo atual e o
  historico (``vigente=False``) sem apagar linhas antigas;
* ``sugestoes_catalogo`` e a fila de revisao para casos ambiguos da IA,
  preservando fonte, evidencia, justificativa e decisao;
* ``cache_logos_telegram`` guarda SOMENTE o ``file_id`` do Telegram. Ele nao se
  confunde com o cache local de URLs/imagens do ``logo_service``.

As tabelas novas usam o mesmo ``Base`` de ``pipeline_dados.banco_dados`` para
que as chaves estrangeiras para ``ativos`` sejam resolvidas no mesmo metadata.
Isso NAO cria/altera nada em producao: ``create_all`` continua opt-in
(``CRIAR_TABELAS=1``) e as migracoes sao manuais.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from pipeline_dados.banco_dados import Base as _BaseBanco

# Compatibilidade com o nome usado pelos testes/importadores. O metadata e o
# mesmo de ``banco_dados.Base`` para resolver FKs para a tabela ``ativos``.
BaseCatalogo = _BaseBanco

STATUS_CONFIRMADA = "confirmada"
STATUS_PENDENTE = "pendente"
STATUS_REJEITADA = "rejeitada"
STATUS_HISTORICO = "historico"

STATUS_SUGESTAO_PENDENTE = "pendente"
STATUS_SUGESTAO_APROVADA = "aprovada"
STATUS_SUGESTAO_REJEITADA = "rejeitada"
STATUS_SUGESTAO_APLICADA = "aplicada"
STATUS_SUGESTAO_DUPLICADA = "duplicada"

STATUS_LOGO_ATIVO = "ativo"
STATUS_LOGO_NEGATIVO = "negativo"
STATUS_LOGO_ERRO = "erro"


def _agora():
    return datetime.utcnow()


class Empresa(BaseCatalogo):
    """Cadastro unico do emissor (empresa/fundo), independente do ticker."""

    __tablename__ = "empresas"
    __table_args__ = (
        UniqueConstraint("cnpj", name="uix_empresas_cnpj"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # CNPJ pode ser nulo apenas para registros ainda nao conciliados com uma
    # fonte oficial. O PostgreSQL/SQLite permitem varios NULL em coluna unica.
    cnpj = Column(String(20), nullable=True, index=True)
    nome = Column(String(255), nullable=False, index=True)
    razao_social = Column(String(255), nullable=True)
    nome_comercial = Column(String(255), nullable=True)
    situacao = Column(String(60), nullable=True)
    fonte = Column(String(500), nullable=True)
    evidencia = Column(Text, nullable=True)
    criado_em = Column(DateTime, nullable=False, default=_agora)
    atualizado_em = Column(DateTime, nullable=False, default=_agora, onupdate=_agora)


class Setor(BaseCatalogo):
    """Macro-setor da taxonomia (ex.: Petroleo, Gas & Biocombustiveis)."""

    __tablename__ = "setores"
    __table_args__ = (
        UniqueConstraint("nome", name="uix_setores_nome"),
        UniqueConstraint("slug", name="uix_setores_slug"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String(160), nullable=False)
    slug = Column(String(160), nullable=False, index=True)
    fonte = Column(String(500), nullable=True)
    criado_em = Column(DateTime, nullable=False, default=_agora)


class Subsetor(BaseCatalogo):
    """Subdivisao de um setor. A unicidade e por setor + slug."""

    __tablename__ = "subsetores"
    __table_args__ = (
        UniqueConstraint("setor_id", "slug", name="uix_subsetores_setor_slug"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    setor_id = Column(
        Integer, ForeignKey("setores.id"), nullable=False, index=True
    )
    nome = Column(String(160), nullable=False)
    slug = Column(String(160), nullable=False)
    fonte = Column(String(500), nullable=True)
    criado_em = Column(DateTime, nullable=False, default=_agora)


class AtividadeEconomica(BaseCatalogo):
    """Atividade economica declarada por uma fonte oficial.

    A atividade e uma categoria propria: NAO e inferida automaticamente a partir
    do setor. Cada empresa recebe apenas as atividades efetivamente associadas
    em ``empresa_atividades``.
    """

    __tablename__ = "atividades_economicas"
    __table_args__ = (
        UniqueConstraint("nome", name="uix_atividades_nome"),
        UniqueConstraint("slug", name="uix_atividades_slug"),
        # Nome explicito para coincidir com a migracao 0005.
        Index("ix_atividades_slug", "slug"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False)
    codigo_cnae = Column(String(20), nullable=True)
    fonte = Column(String(500), nullable=True)
    evidencia = Column(Text, nullable=True)
    criado_em = Column(DateTime, nullable=False, default=_agora)


class EmpresaAtivo(BaseCatalogo):
    """Vinculo N:N entre empresa e ativo negociado.

    ``ativos`` continua com um registro por ticker (e seus dados financeiros
    proprios). O vinculo apenas informa a qual empresa cada ticker pertence.
    """

    __tablename__ = "empresa_ativos"
    __table_args__ = (
        UniqueConstraint("empresa_id", "ativo_id", name="uix_empresa_ativos"),
        # Um ativo/ticker pertence a, no maximo, UMA empresa. O par acima
        # impede repeticao do mesmo par, mas nao impedia o mesmo ativo em duas
        # empresas; esta restricao e a garantia de integridade.
        UniqueConstraint("ativo_id", name="uix_empresa_ativos_ativo"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    empresa_id = Column(
        Integer, ForeignKey("empresas.id"), nullable=False, index=True
    )
    ativo_id = Column(Integer, ForeignKey("ativos.id"), nullable=False, index=True)
    fonte = Column(String(500), nullable=True)
    evidencia = Column(Text, nullable=True)
    criado_em = Column(DateTime, nullable=False, default=_agora)


class EmpresaSegmento(BaseCatalogo):
    """Classificacao setorial da empresa, com historico preservado.

    Somente uma linha ``vigente`` e ``principal`` por empresa. Ao mudar a
    classificacao, a linha anterior vira ``vigente=False`` (status
    ``historico``) em vez de ser apagada.
    """

    __tablename__ = "empresa_segmentos"
    __table_args__ = (
        Index(
            "uix_empresa_segmento_principal_vigente",
            "empresa_id",
            unique=True,
            postgresql_where=text("vigente = true AND principal = true"),
            sqlite_where=text("vigente = 1 AND principal = 1"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    empresa_id = Column(
        Integer, ForeignKey("empresas.id"), nullable=False, index=True
    )
    setor_id = Column(Integer, ForeignKey("setores.id"), nullable=False, index=True)
    subsetor_id = Column(
        Integer, ForeignKey("subsetores.id"), nullable=True, index=True
    )
    principal = Column(Boolean, nullable=False, default=True)
    status = Column(String(20), nullable=False, default=STATUS_CONFIRMADA)
    fonte = Column(String(500), nullable=True)
    evidencia = Column(Text, nullable=True)
    justificativa = Column(Text, nullable=True)
    vigente = Column(Boolean, nullable=False, default=True, index=True)
    criado_em = Column(DateTime, nullable=False, default=_agora)
    atualizado_em = Column(DateTime, nullable=False, default=_agora, onupdate=_agora)


class EmpresaAtividade(BaseCatalogo):
    """Atividade economica da empresa, com historico preservado.

    A restricao parcial garante uma unica linha vigente por
    ``(empresa, atividade)``; linhas historicas continuam existindo para
    auditoria.
    """

    __tablename__ = "empresa_atividades"
    __table_args__ = (
        Index(
            "uix_empresa_atividade_vigente",
            "empresa_id",
            "atividade_id",
            unique=True,
            postgresql_where=text("vigente = true"),
            sqlite_where=text("vigente = 1"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    empresa_id = Column(
        Integer, ForeignKey("empresas.id"), nullable=False, index=True
    )
    atividade_id = Column(
        Integer, ForeignKey("atividades_economicas.id"), nullable=False, index=True
    )
    principal = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default=STATUS_CONFIRMADA)
    fonte = Column(String(500), nullable=True)
    evidencia = Column(Text, nullable=True)
    justificativa = Column(Text, nullable=True)
    vigente = Column(Boolean, nullable=False, default=True, index=True)
    criado_em = Column(DateTime, nullable=False, default=_agora)
    atualizado_em = Column(DateTime, nullable=False, default=_agora, onupdate=_agora)


class SugestaoCatalogo(BaseCatalogo):
    """Fila de revisao/auditoria de novidades sugeridas (IA ou importadores)."""

    __tablename__ = "sugestoes_catalogo"
    __table_args__ = (
        Index(
            "uix_sugestao_catalogo_pendente",
            "tipo",
            "chave",
            unique=True,
            postgresql_where=text("status = 'pendente'"),
            sqlite_where=text("status = 'pendente'"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tipo = Column(String(40), nullable=False, index=True)
    chave = Column(String(255), nullable=False, index=True)
    dados_json = Column(Text, nullable=True)
    fonte = Column(String(500), nullable=True)
    evidencia = Column(Text, nullable=True)
    justificativa = Column(Text, nullable=True)
    confianca = Column(Integer, nullable=True)
    status = Column(
        String(20), nullable=False, default=STATUS_SUGESTAO_PENDENTE, index=True
    )
    criado_em = Column(DateTime, nullable=False, default=_agora)
    decidido_em = Column(DateTime, nullable=True)
    decidido_por = Column(String(60), nullable=True)


class CacheLogoTelegram(BaseCatalogo):
    """Cache persistente do ``file_id`` de logo no Telegram.

    ``chave`` e o ticker canonico usado como fallback. ``empresa_id`` permite
    que PETR3 e PETR4 compartilhem a mesma logo sem compartilhar dados
    financeiros. ``expira_em`` implementa cache negativo com expiracao.
    """

    __tablename__ = "cache_logos_telegram"
    __table_args__ = (
        UniqueConstraint("chave", name="uix_cache_logos_telegram_chave"),
        UniqueConstraint("empresa_id", name="uix_cache_logos_telegram_empresa"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    chave = Column(String(20), nullable=False)
    empresa_id = Column(
        Integer, ForeignKey("empresas.id"), nullable=True, index=True
    )
    file_id = Column(String(255), nullable=True)
    file_unique_id = Column(String(255), nullable=True)
    url_origem = Column(String(500), nullable=True)
    status = Column(
        String(20), nullable=False, default=STATUS_LOGO_ATIVO, index=True
    )
    falhas = Column(Integer, nullable=False, default=0)
    erro = Column(String(500), nullable=True)
    expira_em = Column(DateTime, nullable=True, index=True)
    criado_em = Column(DateTime, nullable=False, default=_agora)
    atualizado_em = Column(DateTime, nullable=False, default=_agora, onupdate=_agora)
