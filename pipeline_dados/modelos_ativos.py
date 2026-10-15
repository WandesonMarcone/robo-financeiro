"""Mapeamento da tabela ``ativos_acompanhados`` existente no banco (Neon).

A tabela ``ativos_acompanhados`` ja existe em producao e possui dados. Este
modulo apenas a mapeia para o SQLAlchemy; ele **nao** cria, recria nem migra
nada. Para garantir que ``create_all`` (mesmo o opt-in de desenvolvimento) nunca
toque nessa tabela, o modelo usa um ``declarative_base`` proprio e separado do
``Base`` de ``pipeline_dados.banco_dados`` e do ``BaseUsuarios`` de
``pipeline_dados.modelos_usuarios``.

Colunas mapeadas (conforme levantamento informado): ``id``, ``usuario_id``,
``ativo_id``, ``criado_em``. A tabela **nao** esta declarada em nenhum outro
ponto do codigo; o nome real da restricao UNIQUE composta nao foi verificado,
por isso a unicidade e expressa no ORM por uma ``UniqueConstraint`` logica
(``usuario_id`` + ``ativo_id``) sem afirmar o nome da constraint no banco.

Nenhuma coluna extra e presumida: o modelo cobre apenas o que foi informado.
Nenhum registro existente e alterado.
"""

from sqlalchemy import Column, DateTime, Integer, UniqueConstraint
from sqlalchemy.orm import declarative_base

BaseAcompanhados = declarative_base()


class AtivoAcompanhado(BaseAcompanhados):
    """Vinculo persistente ``usuario`` -> ``ativo`` (favoritos individuais).

    O modelo nao e criado por ``create_all`` em producao; a tabela pre-existe no
    Neon. Nos testes ele e criado num SQLite em memoria isolado.

    As referencias a ``usuarios.id`` e ``ativos.id`` existem como chaves
    estrangeiras na tabela de producao, mas nao sao redeclaradas aqui: manter o
    modelo num ``metadata`` independente evita acoplar a criacao desta tabela as
    demais e permite o isolamento dos testes. Os vinculos sao resolvidos por
    JOIN explicito (``ativo_id == ativos.id``).
    """

    __tablename__ = "ativos_acompanhados"
    __table_args__ = (
        # Restricao logica de unicidade do vinculo. O nome real da constraint no
        # banco de producao nao foi verificado e nao e criado por este projeto.
        UniqueConstraint("usuario_id", "ativo_id", name="uix_ativos_acompanhados_usuario_ativo"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    ativo_id = Column(Integer, nullable=False, index=True)
    criado_em = Column(DateTime, nullable=True)
