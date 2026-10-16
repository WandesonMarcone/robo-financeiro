"""Mapeamento da tabela ``usuarios`` existente no banco (Neon).

A tabela ``usuarios`` ja existe em producao e possui dados. Este modulo apenas a
mapeia para o SQLAlchemy; ele **nao** cria, recria nem migra nada. Para garantir
que ``Base.metadata.create_all`` (mesmo o opt-in de desenvolvimento) nunca toque
nessa tabela, o modelo usa um ``declarative_base`` proprio e separado do
``Base`` de ``pipeline_dados.banco_dados``.

Representacao do estado de aprovacao
------------------------------------
A tabela nao possui (entre os campos conhecidos: ``id``, ``nome``, ``email``,
``senha_hash``, ``papel``, ``plano``, ``ativo``, ``telegram_user_id``,
``telegram_chat_id``, ``ultimo_login``, ``criado_em``, ``atualizado_em``) um
campo inequivoco de status. Combinar ``papel`` + ``ativo`` seria ambiguo (ex.:
``ativo=False`` tanto pode significar conta pendente quanto rejeitada ou
suspensa). Por isso adicionamos **uma unica coluna** ``status_cadastro`` com um
vocabulario controlado:

* ``pendente``  - solicitacao criada, aguardando decisao do administrador;
* ``aprovado``  - acesso liberado, respeitando o ``papel``;
* ``rejeitado`` - recusado pelo administrador;
* ``suspenso``  - acesso revogado apos aprovacao.

A migracao versionada e reversivel esta em
``migrations/versions/0001_add_status_cadastro_usuarios.sql`` e **nao** e
executada por este projeto automaticamente.

Regra de acesso (sem ambiguidade): a fonte de verdade do ciclo de vida e
``status_cadastro``. O campo ``ativo`` e mantido em coerencia como conveniencia
(``True`` apenas quando ``aprovado``), mas nunca substitui o status.
"""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import declarative_base

BaseUsuarios = declarative_base()

STATUS_PENDENTE = "pendente"
STATUS_APROVADO = "aprovado"
STATUS_REJEITADO = "rejeitado"
STATUS_SUSPENSO = "suspenso"

STATUS_VALIDOS = frozenset(
    {STATUS_PENDENTE, STATUS_APROVADO, STATUS_REJEITADO, STATUS_SUSPENSO}
)


class Usuario(BaseUsuarios):
    """Mapeamento somente-leitura da tabela ``usuarios`` existente.

    O modelo nao e criado por ``create_all``; a tabela pre-existe no Neon.
    """

    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    senha_hash = Column(String(255), nullable=True)
    papel = Column(String(20), nullable=True)
    plano = Column(String(50), nullable=True)
    ativo = Column(Boolean, nullable=True)
    telegram_user_id = Column(BigInteger, nullable=True, unique=True)
    telegram_chat_id = Column(BigInteger, nullable=True)
    ultimo_login = Column(DateTime, nullable=True)
    criado_em = Column(DateTime, nullable=True)
    atualizado_em = Column(DateTime, nullable=True)

    # Coluna adicionada pela migracao 0001 (nao executada automaticamente).
    status_cadastro = Column(
        String(20),
        nullable=False,
        default=STATUS_PENDENTE,
        server_default=STATUS_PENDENTE,
    )

    def para_dto(self):
        return UsuarioDTO(
            id=self.id,
            nome=self.nome,
            papel=self.papel,
            plano=self.plano,
            ativo=bool(self.ativo) if self.ativo is not None else None,
            telegram_user_id=self.telegram_user_id,
            telegram_chat_id=self.telegram_chat_id,
            status=self.status_cadastro,
            email=self.email,
            criado_em=self.criado_em,
        )


class UsuarioDTO:
    """Representacao simples (desanexada) de um usuario para uso na aplicacao.

    ``email`` e ``criado_em`` espelham colunas ja existentes na tabela
    ``usuarios`` e sao expostos aqui (sem alterar o schema) para que o fluxo de
    cadastro possa exibir/registrar o e-mail e a data da solicitacao.
    """

    __slots__ = (
        "id",
        "nome",
        "papel",
        "plano",
        "ativo",
        "telegram_user_id",
        "telegram_chat_id",
        "status",
        "email",
        "criado_em",
    )

    def __init__(
        self,
        id,
        nome,
        papel,
        plano,
        ativo,
        telegram_user_id,
        telegram_chat_id,
        status,
        email=None,
        criado_em=None,
    ):
        self.id = id
        self.nome = nome
        self.papel = papel
        self.plano = plano
        self.ativo = ativo
        self.telegram_user_id = telegram_user_id
        self.telegram_chat_id = telegram_chat_id
        self.status = status
        self.email = email
        self.criado_em = criado_em

    def esta_aprovado(self):
        return self.status == STATUS_APROVADO

    def __repr__(self):  # pragma: no cover - diagnostico
        return (
            f"UsuarioDTO(id={self.id!r}, status={self.status!r}, "
            f"papel={self.papel!r})"
        )
