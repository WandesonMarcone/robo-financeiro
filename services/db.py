"""Acesso centralizado ao banco de dados — Fase 7, Etapa 7.4.

Ponto único de criação do engine e das sessões ORM do projeto. Substitui as
formas concorrentes anteriores de obter conexão/sessão — o engine e o
``SessionDB`` definidos em ``atualizador_documentos`` (o "ponto central de
banco" apontado pela auditoria 7.1) e o engine local de
``espelhamento_sheets._criar_sessao`` — para os componentes do Financial
Intelligence Core e para o código novo em geral, mantendo compatibilidade com o
legado (que continua importando ``SessionDB`` de ``atualizador_documentos``,
agora delegado para cá).

Garantias:
- Um único engine por processo, com os mesmos parâmetros de pool do legado:
  ``pool_pre_ping`` cobre conexões mortas do Neon serverless,
  ``pool_recycle`` renova conexões ociosas e ``pool_size``/``max_overflow``
  limitam o uso de conexões.
- ``SessionDB`` é a fábrica padrão (callable -> sessão), mantendo o nome
  histórico do projeto para compatibilidade.
- ``sessao_db(session)`` é o contexto recomendado para os componentes novos:
  reutiliza a sessão informada pelo chamador (nunca a fecha) ou abre e fecha
  uma própria. Não faz commit automático — o chamador decide, como no padrão
  dos serviços da Fase 5/6 (``services/usuarios``, ``services/mercado``).
"""
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import config
from pipeline_dados.banco_dados import Base

logger = logging.getLogger(__name__)

engine = create_engine(
    config.obter_database_url(),
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=5,
    max_overflow=10,
)

SessionDB = sessionmaker(bind=engine)


def criar_sessao() -> Session:
    """Abre uma nova sessão ORM. O chamador é responsável por fechá-la."""
    return SessionDB()


def criar_tabelas() -> None:
    """Cria as tabelas ausentes no engine central (idempotente).

    Não remove nem altera tabelas existentes; usado em pontos que precisam
    garantir o schema antes de usar a sessão (ex.: espelhamentos legados).
    """
    Base.metadata.create_all(engine)


@contextmanager
def sessao_db(session: Session | None = None) -> Iterator[Session]:
    """Contexto recomendado para obter sessão nos componentes do Core.

    Quando ``session`` é informada, a usa sem fechar nem commitar (o chamador
    gerencia o ciclo de vida). Quando ausente, abre uma sessão própria, faz
    rollback em erro e a fecha ao final. Não faz commit automático em sessão
    própria — segue o padrão de serviços da Fase 5/6.
    """
    if session is not None:
        yield session
        return
    s = criar_sessao()
    try:
        yield s
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
