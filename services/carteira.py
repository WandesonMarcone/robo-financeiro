"""Serviço central de carteira/posições por usuário (Fase 6, Etapa 4).

Gerencia ``PosicaoCarteira`` reutilizando exclusivamente:
- ``services/autorizacao.py`` — matriz central (nenhuma regra paralela);
- ``services/escopo.py`` — isolamento por usuário e anti-IDOR/BOLA;
- ``services/auditoria.py`` — trilha de eventos sem segredos;
- padrão de sessão do projeto (``services.usuarios._sessao``).

O proprietário é SEMPRE o ``usuario`` informado pelo chamador autenticado —
nunca um ``usuario_id`` vindo do cliente. Nenhuma fonte externa de preço é
consultada; apenas dados derivados simples dos campos persistidos
(``valor_investido = quantidade * preco_medio``). Compra/venda real,
tributação, IR, ordens, corretoras e sincronização são etapas posteriores.
"""
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, insert, literal, select
from sqlalchemy.exc import IntegrityError

from pipeline_dados.banco_dados import Ativo, PosicaoCarteira
from services import auditoria, autorizacao, escopo, planos
from services.usuarios import _sessao

logger = logging.getLogger(__name__)

ACAO_CRIADA = "POSICAO_CRIADA"
ACAO_ALTERADA = "POSICAO_ALTERADA"
ACAO_REMOVIDA = "POSICAO_REMOVIDA"


def _alvo(usuario):
    """Rótulo de alvo para auditoria (email quando disponível, senão o id)."""
    if usuario is None:
        return None
    email = getattr(usuario, "email", None)
    return email if email else f"usuario:{usuario.id}"


def _decimal(valor, nome):
    """Converte o valor em ``Decimal`` válido; levanta ``ValueError``."""
    if isinstance(valor, bool) or valor is None:
        raise ValueError(f"O campo '{nome}' é inválido.")
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"O campo '{nome}' é inválido.") from None


def _validar_quantidade(valor):
    """Valida a quantidade: numérica e estritamente maior que zero."""
    quantidade = _decimal(valor, "quantidade")
    if quantidade <= 0:
        raise ValueError("A quantidade deve ser maior que zero.")
    return quantidade


def _validar_preco_medio(valor):
    """Valida o preço médio: numérico e não negativo."""
    preco = _decimal(valor, "preco_medio")
    if preco < 0:
        raise ValueError("O preço médio não pode ser negativo.")
    return preco


def valor_investido_posicao(posicao):
    """Valor investido derivado (``quantidade * preco_medio``), sem fonte externa.

    Retorna ``None`` para posição nula. Apenas dados persistidos são usados.
    """
    if posicao is None:
        return None
    return posicao.quantidade * posicao.preco_medio


# ==========================================
# CRIAÇÃO
# ==========================================


def adicionar_posicao(usuario, ativo_id, quantidade, preco_medio, session=None, ip=None):
    """Cria uma posição para ``usuario`` em ``ativo_id``.

    Exige usuário ativo (papel efetivo válido), ativo existente, quantidade
    > 0 e preço médio >= 0. Uma posição já existente para o mesmo
    ``(usuario_id, ativo_id)`` é rejeitada (``ValueError``) orientando o uso da
    atualização. Registra ``POSICAO_CRIADA`` na auditoria (sem segredos).
    """
    if autorizacao.papel_de(usuario) is None:
        raise autorizacao.PermissaoNegadaError(
            permissao="carteira.propria",
            papel=None,
            usuario_id=getattr(usuario, "id", None),
        )
    quantidade_dec = _validar_quantidade(quantidade)
    preco_dec = _validar_preco_medio(preco_medio)

    with _sessao(session) as s:
        ativo = s.get(Ativo, ativo_id)
        if ativo is None:
            raise ValueError("Ativo não encontrado.")
        if buscar_posicao_por_ativo(usuario, ativo_id, session=s) is not None:
            raise ValueError(
                "Já existe uma posição para este ativo. Use a atualização da posição."
            )
        limite = planos.obter_limite(usuario, "limite.posicoes_carteira")
        if limite is None:
            posicao = PosicaoCarteira(
                usuario_id=usuario.id,
                ativo_id=ativo_id,
                quantidade=quantidade_dec,
                preco_medio=preco_dec,
            )
            s.add(posicao)
        else:
            # Inserção ATÔMICA (INSERT...SELECT): contagem e inclusão na mesma
            # instrução eliminam a corrida entre leitura e escrita no limite
            # (SQLite e PostgreSQL). ``rowcount == 0`` -> limite atingido.
            agora = datetime.now()
            resultado = s.execute(
                insert(PosicaoCarteira).from_select(
                    (
                        PosicaoCarteira.usuario_id,
                        PosicaoCarteira.ativo_id,
                        PosicaoCarteira.quantidade,
                        PosicaoCarteira.preco_medio,
                        PosicaoCarteira.criado_em,
                        PosicaoCarteira.atualizado_em,
                    ),
                    select(
                        literal(usuario.id),
                        literal(ativo_id),
                        literal(quantidade_dec),
                        literal(preco_dec),
                        literal(agora),
                        literal(agora),
                    ).where(
                        select(func.count(PosicaoCarteira.id))
                        .where(PosicaoCarteira.usuario_id == usuario.id)
                        .scalar_subquery()
                        < limite
                    ),
                )
            )
            if resultado.rowcount == 0:
                raise ValueError(
                    "Limite de posições na carteira atingido para o seu plano. "
                    "Remova posições ou evolua de plano para incluir mais."
                )
            posicao = (
                s.query(PosicaoCarteira)
                .filter(
                    PosicaoCarteira.usuario_id == usuario.id,
                    PosicaoCarteira.ativo_id == ativo_id,
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
                "Já existe uma posição para este ativo. Use a atualização da posição."
            ) from None
        auditoria.registrar_evento(
            acao=ACAO_CRIADA,
            alvo=_alvo(usuario),
            detalhe=f"ativo_id={ativo_id}",
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
        return posicao


# ==========================================
# CONSULTA
# ==========================================


def listar_posicoes(usuario, session=None):
    """Lista as posições do próprio ``usuario``, em ordem de criação."""
    if usuario is None or getattr(usuario, "id", None) is None:
        return []
    with _sessao(session) as s:
        return (
            s.query(PosicaoCarteira)
            .filter(PosicaoCarteira.usuario_id == usuario.id)
            .order_by(PosicaoCarteira.id)
            .all()
        )


def buscar_posicao(usuario, posicao_id, session=None):
    """Busca uma posição aplicando o escopo (anti-IDOR/BOLA).

    Retorna a posição apenas quando ``usuario`` pode acessá-la; ``None`` para
    recurso inexistente OU de outro usuário — resposta indistinguível.
    """
    with _sessao(session) as s:
        return escopo.buscar_recurso_escopado(
            s, PosicaoCarteira, posicao_id, usuario
        )


def buscar_posicao_por_ativo(usuario, ativo_id, session=None):
    """Busca a posição do ``usuario`` em um ``ativo_id`` (ou ``None``)."""
    if usuario is None or getattr(usuario, "id", None) is None:
        return None
    with _sessao(session) as s:
        return (
            s.query(PosicaoCarteira)
            .filter(
                PosicaoCarteira.usuario_id == usuario.id,
                PosicaoCarteira.ativo_id == ativo_id,
            )
            .first()
        )


# ==========================================
# ATUALIZAÇÃO E REMOÇÃO
# ==========================================


def atualizar_posicao(
    usuario, posicao_id, quantidade=None, preco_medio=None, session=None, ip=None
):
    """Atualiza quantidade e/ou preço médio de uma posição, aplicando o escopo.

    Retorna a posição atualizada ou ``None`` (inexistente/fora do escopo).
    Campos omitidos permanecem inalterados; valores informados são validados.
    Registra ``POSICAO_ALTERADA`` na auditoria (sem segredos).
    """
    with _sessao(session) as s:
        posicao = escopo.buscar_recurso_escopado(
            s, PosicaoCarteira, posicao_id, usuario
        )
        if posicao is None:
            return None
        if quantidade is not None:
            posicao.quantidade = _validar_quantidade(quantidade)
        if preco_medio is not None:
            posicao.preco_medio = _validar_preco_medio(preco_medio)
        s.commit()
        auditoria.registrar_evento(
            acao=ACAO_ALTERADA,
            alvo=_alvo(usuario),
            detalhe=f"posicao_id={posicao.id}, ativo_id={posicao.ativo_id}",
            usuario_id=getattr(usuario, "id", None),
            ip=ip,
            session=s,
        )
        return posicao


def remover_posicao(usuario, posicao_id, session=None, ip=None):
    """Remove uma posição aplicando o escopo. Retorna ``True``/``False``.

    ``False`` tanto para recurso inexistente quanto para recurso de outro
    usuário. Registra ``POSICAO_REMOVIDA`` na auditoria.
    """
    with _sessao(session) as s:
        posicao = escopo.buscar_recurso_escopado(
            s, PosicaoCarteira, posicao_id, usuario
        )
        if posicao is None:
            return False
        s.delete(posicao)
        s.commit()
        auditoria.registrar_evento(
            acao=ACAO_REMOVIDA,
            alvo=_alvo(usuario),
            detalhe=f"posicao_id={posicao_id}",
            usuario_id=getattr(usuario, "id", None),
            ip=ip,
            session=s,
        )
        return True
