"""Resolucao centralizada da conexao com o banco de dados.

Este modulo concentra tres responsabilidades que antes estavam duplicadas em
``atualizador_documentos.py`` e ``main.py``:

* normalizar a URL de conexao (``postgres://``/``postgresql://`` ->
  ``postgresql+psycopg://``);
* criar o ``Engine`` do SQLAlchemy usando SEMPRE a URL normalizada;
* fornecer uma fabrica de sessoes *preguicosa* (lazy), criada apenas quando a
  primeira sessao e realmente solicitada.

Decisoes de projeto (etapa de correcao de inicializacao)
---------------------------------------------------------
1. Nao existe mais fallback silencioso para SQLite local. Se ``DATABASE_URL``
   nao estiver definido, a criacao do engine falha com um erro controlado em vez
   de substituir o banco de producao (Neon) por um arquivo local.
2. Importar este modulo NAO abre conexao, NAO cria tabelas e NAO executa
   migracoes. Qualquer efeito colateral acontece somente quando o engine e a
   sessao sao efetivamente usados.
3. Nenhuma credencial e registrada em log. Use :func:`mascarar_url` para exibir
   uma URL de forma segura.
"""

import logging
import os
import re
import threading

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger("robo.banco")

PREFIXO_POSTGRES_ANTIGO = "postgres://"
PREFIXO_POSTGRES_NOVO = "postgresql://"
# Driver efetivamente instalado por ``psycopg[binary]`` (psycopg 3). O prefixo
# explicito evita que o SQLAlchemy tente o driver legado ``psycopg2``, que NAO
# esta declarado em ``requirements.txt``.
PREFIXO_POSTGRES_DRIVER = "postgresql+psycopg://"

_engine = None
_session_factory = None
# RLock (reentrante): obter_session_factory adquire o lock e, em seguida,
# chama obter_engine, que tambem precisa do mesmo lock.
_lock = threading.RLock()


class BancoNaoConfiguradoError(RuntimeError):
    """Erro controlado levantado quando ``DATABASE_URL`` nao esta definido."""


def normalizar_database_url(url):
    """Normaliza a URL de conexao do banco.

    * Remove espacos acidentais.
    * Converte o prefixo legado ``postgres://`` (Heroku/Render) e o prefixo
      ``postgresql://`` (sem driver) em ``postgresql+psycopg://``, que usa o
      psycopg 3 instalado por ``psycopg[binary]``.
    * URLs com driver explicito (``postgresql+psycopg2://``, etc.) sao
      preservadas para nao quebrar configuracoes existentes.
    * Valores ``None``/vazios retornam ``None``.

    Nenhuma senha ou host e alterado alem do prefixo do esquema/driver.
    """
    if url is None:
        return None

    texto = str(url).strip()
    if not texto:
        return None

    if texto.startswith(PREFIXO_POSTGRES_ANTIGO):
        texto = PREFIXO_POSTGRES_NOVO + texto[len(PREFIXO_POSTGRES_ANTIGO):]
    # Só adiciona o driver quando a URL ainda não especifica um. Assim uma URL
    # ``postgresql+psycopg2://`` fornecida explicitamente continua intacta.
    if texto.startswith(PREFIXO_POSTGRES_NOVO) and not texto.startswith(
        "postgresql+"
    ):
        texto = PREFIXO_POSTGRES_DRIVER + texto[len(PREFIXO_POSTGRES_NOVO):]
    return texto


def resolver_database_url():
    """Retorna a URL normalizada de ``config.DATABASE_URL``/ambiente (ou None)."""
    import config  # import local: mantem ``config`` leve e evita ciclos

    url = getattr(config, "DATABASE_URL", None) or os.environ.get("DATABASE_URL")
    return normalizar_database_url(url)


def mascarar_url(url):
    """Mascara a senha embutida em uma URL de conexao, para uso em logs."""
    if not url:
        return None
    texto = str(url)
    return re.sub(r"(://[^:/@]+):[^@]*@", r"\1:***@", texto)


def _opcoes_engine(url):
    """Opcoes de pool por dialeto, sem parametros invalidos para SQLite."""
    opcoes = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        opcoes.update(
            {
                "pool_recycle": 1800,
                "pool_size": 5,
                "max_overflow": 10,
            }
        )
    return opcoes


def criar_engine(url=None):
    """Cria um ``Engine`` do SQLAlchemy a partir da URL normalizada.

    Nunca faz fallback para SQLite: sem URL configurada, levanta
    :class:`BancoNaoConfiguradoError` sem expor credenciais.
    """
    if url is None:
        url_normalizada = resolver_database_url()
    else:
        url_normalizada = normalizar_database_url(url)

    if not url_normalizada:
        raise BancoNaoConfiguradoError(
            "DATABASE_URL ausente. Defina a variavel de ambiente DATABASE_URL "
            "(string de conexao do Neon). Nenhum banco local e criado "
            "automaticamente."
        )

    return create_engine(url_normalizada, **_opcoes_engine(url_normalizada))


def obter_engine():
    """Retorna o engine em cache, criando-o na primeira chamada."""
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = criar_engine()
                logger.info("Conexao com o banco configurada: %s", mascarar_url(str(_engine.url)))
    return _engine


def obter_session_factory():
    """Retorna a fabrica de sessoes em cache, criando-a na primeira chamada."""
    global _session_factory
    if _session_factory is None:
        with _lock:
            if _session_factory is None:
                _session_factory = sessionmaker(bind=obter_engine())
    return _session_factory


def resetar_conexao():
    """Descarta engine/fabrica em cache. Existe para isolar testes."""
    global _engine, _session_factory
    with _lock:
        if _engine is not None:
            try:
                _engine.dispose()
            except Exception:  # pragma: no cover - descarte defensivo
                pass
        _engine = None
        _session_factory = None
