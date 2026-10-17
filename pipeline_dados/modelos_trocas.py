"""Mapeamento da tabela ``solicitacoes_troca`` (solicitações de troca de ativo).

Diferente das tabelas ``usuarios`` e ``ativos_acompanhados`` (que já existem no
banco de produção), esta tabela é **nova**. O mapeamento abaixo NÃO cria nem
migra nada por conta própria: a aplicação nunca executa ``create_all`` no banco
de produção (ver ``main.criar_tabelas_se_solicitado``) e a criação da tabela é
feita por migrações versionadas aplicadas **manualmente**:
``migrations/versions/0002_add_solicitacoes_troca.sql`` (tabela) e
``migrations/versions/0003_fix_solicitacoes_troca_unique.sql`` (índice único
parcial de pendentes).

Para garantir o isolamento (e que um ``create_all`` opt-in de desenvolvimento não
toque em outras tabelas), o modelo usa um ``declarative_base`` próprio e
separado de ``banco_dados.Base``, ``modelos_usuarios.BaseUsuarios`` e
``modelos_ativos.BaseAcompanhados``.

Ciclo de vida de uma solicitação (coluna ``status``):

* ``pendente``  - criada pelo usuário, aguardando decisão do administrador;
* ``aprovada``  - aprovada; a troca de favoritos foi aplicada;
* ``rejeitada`` - recusada pelo administrador;
* ``expirada``  - passou do prazo de decisão sem aprovação (nunca é aprovada
  automaticamente). O registro é mantido (histórico preservado).

Uma solicitação aprovada/rejeitada/expirada nunca volta a ser decidida: o estado
é terminal (ver ``repositorio_trocas``).
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import declarative_base

BaseTrocas = declarative_base()

STATUS_TROCA_PENDENTE = "pendente"
STATUS_TROCA_APROVADA = "aprovada"
STATUS_TROCA_REJEITADA = "rejeitada"
STATUS_TROCA_EXPIRADA = "expirada"

STATUS_TROCA_VALIDOS = frozenset(
    {
        STATUS_TROCA_PENDENTE,
        STATUS_TROCA_APROVADA,
        STATUS_TROCA_REJEITADA,
        STATUS_TROCA_EXPIRADA,
    }
)

STATUS_TROCA_TERMINAIS = frozenset(
    {STATUS_TROCA_APROVADA, STATUS_TROCA_REJEITADA, STATUS_TROCA_EXPIRADA}
)


class SolicitacaoTroca(BaseTrocas):
    """Vínculo persistente de uma solicitação de troca de ativo favorito."""

    __tablename__ = "solicitacoes_troca"
    __table_args__ = (
        # Apenas UMA solicitação PENDENTE por (usuário, ativo de saída). O
        # índice é parcial (``WHERE status = 'pendente'``), portanto o histórico
        # (aprovadas, rejeitadas, expiradas) pode conter quantas linhas forem
        # necessárias e o mesmo ativo pode ser solicitado novamente no futuro.
        # A migração 0003 substitui a antiga constraint que incluía ``status``
        # (e por isso bloqueava a segunda rejeição/expiração do mesmo ativo).
        Index(
            "uix_solicitacoes_troca_pendente",
            "usuario_id",
            "ativo_saida_id",
            unique=True,
            postgresql_where=text("status = 'pendente'"),
            sqlite_where=text("status = 'pendente'"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    # Ativo que o usuário quer deixar de acompanhar (deve ser favorito dele).
    ativo_saida_id = Column(Integer, nullable=False, index=True)
    # Ativo que o usuário quer passar a acompanhar (deve existir no catálogo).
    ativo_entrada_id = Column(Integer, nullable=False, index=True)
    status = Column(
        String(20),
        nullable=False,
        default=STATUS_TROCA_PENDENTE,
        server_default=STATUS_TROCA_PENDENTE,
    )
    criado_em = Column(DateTime, nullable=True)
    decidido_em = Column(DateTime, nullable=True)
    # Telegram ID do administrador que decidiu (None enquanto pendente/expiração
    # automática). Não referencia ``usuarios.id`` para não expor dados do admin.
    decidido_por = Column(BigInteger, nullable=True)
