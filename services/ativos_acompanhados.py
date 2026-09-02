"""Serviço central de ativos acompanhados por usuário (Fase 6, Etapa 4).

Gerencia ``AtivoAcompanhado`` reutilizando exclusivamente:
- ``services/autorizacao.py`` — matriz central (nenhuma regra paralela);
- ``services/escopo.py`` — isolamento por usuário e anti-IDOR/BOLA;
- ``services/auditoria.py`` — trilha de eventos sem segredos;
- padrão de sessão do projeto (``services.usuarios._sessao``).

O proprietário é SEMPRE o ``usuario`` informado pelo chamador autenticado —
nunca um ``usuario_id`` vindo do cliente. Nenhuma senha, token, API Key ou
segredo é lido ou registrado aqui.
"""
import logging
from datetime import datetime

from sqlalchemy import func, insert, literal, select
from sqlalchemy.exc import IntegrityError

from pipeline_dados.banco_dados import Ativo, AtivoAcompanhado
from services import auditoria, autorizacao, escopo, planos
from services.usuarios import _sessao

logger = logging.getLogger(__name__)

ACAO_ADICIONADO = "ATIVO_ACOMPANHADO_ADICIONADO"
ACAO_REMOVIDO = "ATIVO_ACOMPANHADO_REMOVIDO"


def _alvo(usuario):
    """Rótulo de alvo para auditoria (email quando disponível, senão o id)."""
    if usuario is None:
        return None
    email = getattr(usuario, "email", None)
    return email if email else f"usuario:{usuario.id}"


# ==========================================
# CRIAÇÃO
# ==========================================


def adicionar_acompanhamento(usuario, ativo_id, session=None, ip=None):
    """Adiciona um ativo ao acompanhamento do ``usuario`` autenticado.

    O proprietário é sempre ``usuario.id`` — a única entrada do cliente é o
    ``ativo_id``. Exige usuário ativo (papel efetivo válido) e ativo existente.
    Duplicidade ``(usuario_id, ativo_id)`` é rejeitada com ``ValueError``.
    Registra ``ATIVO_ACOMPANHADO_ADICIONADO`` na auditoria (sem segredos).
    """
    if autorizacao.papel_de(usuario) is None:
        raise autorizacao.PermissaoNegadaError(
            permissao="ativos.proprios",
            papel=None,
            usuario_id=getattr(usuario, "id", None),
        )
    with _sessao(session) as s:
        ativo = s.get(Ativo, ativo_id)
        if ativo is None:
            raise ValueError("Ativo não encontrado.")
        if usuario_acompanha_ativo(usuario, ativo_id, session=s):
            raise ValueError("Este ativo já está na sua lista de acompanhamento.")
        limite = planos.obter_limite(usuario, "limite.ativos_acompanhados")
        if limite is None:
            registro = AtivoAcompanhado(usuario_id=usuario.id, ativo_id=ativo_id)
            s.add(registro)
        else:
            # Inserção ATÔMICA (INSERT...SELECT): contagem e inclusão na mesma
            # instrução eliminam a corrida entre leitura e escrita no limite
            # (SQLite e PostgreSQL). ``rowcount == 0`` -> limite atingido.
            resultado = s.execute(
                insert(AtivoAcompanhado).from_select(
                    (
                        AtivoAcompanhado.usuario_id,
                        AtivoAcompanhado.ativo_id,
                        AtivoAcompanhado.criado_em,
                    ),
                    select(
                        literal(usuario.id),
                        literal(ativo_id),
                        literal(datetime.now()),
                    ).where(
                        select(func.count(AtivoAcompanhado.id))
                        .where(AtivoAcompanhado.usuario_id == usuario.id)
                        .scalar_subquery()
                        < limite
                    ),
                )
            )
            if resultado.rowcount == 0:
                raise ValueError(
                    "Limite de ativos acompanhados atingido para o seu plano. "
                    "Remova itens ou evolua de plano para incluir mais."
                )
            registro = (
                s.query(AtivoAcompanhado)
                .filter(
                    AtivoAcompanhado.usuario_id == usuario.id,
                    AtivoAcompanhado.ativo_id == ativo_id,
                )
                .one()
            )
        try:
            s.commit()
        except IntegrityError:
            # Corrida de duplicidade (mesmo usuário + ativo em requisições
            # simultâneas): a unicidade do banco prevalece e a resposta é a
            # mesma de uma duplicidade sequencial.
            s.rollback()
            raise ValueError(
                "Este ativo já está na sua lista de acompanhamento."
            ) from None
        auditoria.registrar_evento(
            acao=ACAO_ADICIONADO,
            alvo=_alvo(usuario),
            detalhe=f"ativo_id={ativo_id}",
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
        return registro


# ==========================================
# CONSULTA
# ==========================================


def listar_acompanhamentos(usuario, session=None):
    """Lista os acompanhamentos do próprio ``usuario``, em ordem de criação."""
    if usuario is None or getattr(usuario, "id", None) is None:
        return []
    with _sessao(session) as s:
        return (
            s.query(AtivoAcompanhado)
            .filter(AtivoAcompanhado.usuario_id == usuario.id)
            .order_by(AtivoAcompanhado.id)
            .all()
        )


def buscar_acompanhamento(usuario, acompanhamento_id, session=None):
    """Busca um acompanhamento aplicando o escopo (anti-IDOR/BOLA).

    Retorna o registro apenas quando ``usuario`` pode acessá-lo; ``None`` para
    recurso inexistente OU de outro usuário — resposta indistinguível.
    """
    with _sessao(session) as s:
        return escopo.buscar_recurso_escopado(
            s, AtivoAcompanhado, acompanhamento_id, usuario
        )


def usuario_acompanha_ativo(usuario, ativo_id, session=None):
    """True quando ``usuario`` já acompanha o ``ativo_id``."""
    if usuario is None or getattr(usuario, "id", None) is None:
        return False
    with _sessao(session) as s:
        registro = (
            s.query(AtivoAcompanhado)
            .filter(
                AtivoAcompanhado.usuario_id == usuario.id,
                AtivoAcompanhado.ativo_id == ativo_id,
            )
            .first()
        )
        return registro is not None


# ==========================================
# REMOÇÃO
# ==========================================


def remover_acompanhamento(usuario, acompanhamento_id, session=None, ip=None):
    """Remove um acompanhamento aplicando o escopo. Retorna ``True``/``False``.

    ``False`` tanto para recurso inexistente quanto para recurso de outro
    usuário. Registra ``ATIVO_ACOMPANHADO_REMOVIDO`` na auditoria.
    """
    with _sessao(session) as s:
        registro = escopo.buscar_recurso_escopado(
            s, AtivoAcompanhado, acompanhamento_id, usuario
        )
        if registro is None:
            return False
        ativo_id = registro.ativo_id
        s.delete(registro)
        s.commit()
        auditoria.registrar_evento(
            acao=ACAO_REMOVIDO,
            alvo=_alvo(usuario),
            detalhe=f"ativo_id={ativo_id}",
            usuario_id=getattr(usuario, "id", None),
            ip=ip,
            session=s,
        )
        return True
