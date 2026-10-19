"""Mapeamento da tabela ``alertas_eventos`` existente no banco (Neon).

A tabela ``alertas_eventos`` ja existe em producao e possui dados. Este modulo
apenas a descreve para o SQLAlchemy; ele **nao** cria, recria nem migra nada.
Usa um ``declarative_base`` proprio para que ``create_all`` de outros metadados
nunca toque nessa tabela.

Colunas e unique conforme dump do catalogo PostgreSQL (2026-10-19):

* unique ``uix_alertas_evento`` em ``(ativo_id, indicador, data_evento)``;
* ``data_evento`` e timestamp: o mesmo alerta no mesmo dia, em crons
  diferentes, nao viola a unique;
* NOT NULL: ``id``, ``tipo_alerta``, ``tipo_ativo``, ``ativo_id``,
  ``indicador``, ``regra``, ``motivo``, ``severidade``, ``data_evento``,
  ``telegram_enviado``;
* sem CHECK; o vocabulario observado vive nos dados, nao no catalogo;
* sem FK declarada aqui (isolamento de metadata); em producao a FK
  ``ativo_id -> ativos(id)`` ja existe.

Nenhuma coluna extra e presumida. ``notificacoes`` e ``preferencias_usuarios``
nao sao mapeadas neste modulo: o vocabulario de ``status`` e dos flags de
opt-in continua desconhecido (tabelas vazias no dump).
"""

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

BaseAlertas = declarative_base()


class AlertaEvento(BaseAlertas):
    """Evento persistido em ``alertas_eventos`` (fato, nao fila de entrega).

    O modelo nao e criado por ``create_all`` em producao; a tabela pre-existe
    no Neon. Nos testes ele e criado num SQLite em memoria isolado.
    """

    __tablename__ = "alertas_eventos"
    __table_args__ = (
        UniqueConstraint(
            "ativo_id",
            "indicador",
            "data_evento",
            name="uix_alertas_evento",
        ),
        Index("ix_alertas_eventos_ativo_id", "ativo_id"),
        Index("ix_alertas_eventos_tipo_alerta", "tipo_alerta"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tipo_alerta = Column(String(20), nullable=False)
    tipo_ativo = Column(String(10), nullable=False)
    ativo_id = Column(Integer, nullable=False)
    indicador = Column(String(40), nullable=False)
    valor_anterior = Column(Numeric(24, 8), nullable=True)
    valor_atual = Column(Numeric(24, 8), nullable=True)
    variacao_percentual = Column(Numeric(12, 4), nullable=True)
    regra = Column(String(60), nullable=False)
    motivo = Column(String(255), nullable=False)
    severidade = Column(String(20), nullable=False)
    recomendacao = Column(String(255), nullable=True)
    origem = Column(String(60), nullable=True)
    data_referencia = Column(Date, nullable=True)
    data_evento = Column(DateTime, nullable=False)
    telegram_enviado = Column(Boolean, nullable=False)
