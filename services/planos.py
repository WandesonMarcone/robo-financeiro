"""Camada central de planos e entitlements (Fase 6, Etapa 8).

Separa o conceito comercial (plano: FREE/PREMIUM/PRO) do conceito de acesso
(RBAC em ``services/autorizacao.py``). Aqui ficam o catálogo central de
entitlements (recursos habilitados) e limites numéricos por plano, e apenas as
consultas permitidas ao resto do sistema:

- ``plano_de`` — plano efetivo de um usuário (``NULL``/inválido vira
  ``PLANO_PADRAO``); ``None`` para usuário desativado/inexistente;
- ``tem_entitlement`` — True quando o usuário pode usar um recurso comercial.
  SUPERADMIN sempre possui todos os recursos (acesso administrativo pleno),
  independentemente do plano comercial;
- ``obter_limite`` — limite numérico de um recurso; SUPERADMIN não tem limite
  (``None`` = ilimitado); usuário inválido/desativado não tem limite (``0``);
- ``alterar_plano`` — única forma de mudar o plano de um usuário. Exclusiva do
  SUPERADMIN (anti-escalonamento): nenhum usuário altera o próprio plano e o
  cliente NUNCA envia o plano pela API.

Garantias de segurança:
- Nenhum segredo (senha, token, API Key, hash) é lido, persistido ou auditado;
- O plano nunca é aceito do cliente — apenas o SUPERADMIN autenticado, via
  serviço central, altera planos;
- Nenhuma regra de entitlement é espalhada pelas rotas: o restante do sistema
  consulta exclusivamente esta camada.
"""
import logging

from services import auditoria, autorizacao
from services.usuarios import _sessao

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PLANOS (catálogo fechado)
# ---------------------------------------------------------------------------
PLANO_FREE = "FREE"
PLANO_PREMIUM = "PREMIUM"
PLANO_PRO = "PRO"

PLANOS_VALIDOS = (PLANO_FREE, PLANO_PREMIUM, PLANO_PRO)
PLANO_PADRAO = PLANO_FREE

# Permissão usada pelo roteador de API para expor a gestão de planos. Só o
# SUPERADMIN a possui (via "*" na matriz central); a checagem em
# ``pode_alterar_plano`` é a segunda barreira (defesa em profundidade).
PERMISSAO_ADMINISTRAR_PLANOS = "planos.administrar"

# ---------------------------------------------------------------------------
# CATÁLOGO CENTRAL DE ENTITLEMENTS (recursos comerciais)
# ---------------------------------------------------------------------------
RECURSOS_DO_PLANO = {
    PLANO_FREE: frozenset(),
    PLANO_PREMIUM: frozenset(
        {
            "relatorios.avancados",
            "alertas.avancados",
            "notificacoes.prioridade",
            "exportacao.dados",
        }
    ),
    PLANO_PRO: frozenset(
        {
            "relatorios.avancados",
            "alertas.avancados",
            "notificacoes.prioridade",
            "exportacao.dados",
            "documentos.historico_completo",
            "dados.historico_completo",
        }
    ),
}

# ---------------------------------------------------------------------------
# LIMITES NUMÉRICOS POR PLANO (recurso -> limite; SUPERADMIN = ilimitado)
# ---------------------------------------------------------------------------
LIMITES_DO_PLANO = {
    PLANO_FREE: {
        "limite.ativos_acompanhados": 10,
        "limite.posicoes_carteira": 5,
        "limite.notificacoes_ativas": 20,
    },
    PLANO_PREMIUM: {
        "limite.ativos_acompanhados": 30,
        "limite.posicoes_carteira": 20,
        "limite.notificacoes_ativas": 100,
    },
    PLANO_PRO: {
        "limite.ativos_acompanhados": 100,
        "limite.posicoes_carteira": 200,
        "limite.notificacoes_ativas": 1000,
    },
}

RECURSOS_VALIDOS = frozenset().union(*RECURSOS_DO_PLANO.values())
LIMITES_VALIDOS = frozenset().union(*LIMITES_DO_PLANO.values())

# Eventos de auditoria (sem segredos).
ACAO_PLANO_ALTERADO = "PLANO_ALTERADO"
ACAO_PLANO_ALTERACAO_NEGADA = "PLANO_ALTERACAO_NEGADA"


def _alvo(usuario):
    """Rótulo de alvo para auditoria (email quando disponível, senão o id)."""
    if usuario is None:
        return None
    email = getattr(usuario, "email", None)
    return email if email else f"usuario:{usuario.id}"


# ---------------------------------------------------------------------------
# CONSULTA DE PLANO E ENTITLEMENTS
# ---------------------------------------------------------------------------


def plano_de(usuario):
    """Plano efetivo de ``usuario``, ou ``None``.

    Usuários ativos com ``plano`` ausente/inválido (linhas legadas anteriores à
    Etapa 8) recebem ``PLANO_PADRAO`` (FREE). Usuário desativado, inexistente
    ou ``None`` retorna ``None`` — sem plano, sem entitlement.
    """
    if usuario is None:
        return None
    if autorizacao.papel_de(usuario) is None:
        return None
    plano = getattr(usuario, "plano", None)
    if plano not in PLANOS_VALIDOS:
        return PLANO_PADRAO
    return plano


def entitlements_de(usuario):
    """Conjunto de recursos comerciais habilitados para ``usuario``.

    SUPERADMIN possui todos os recursos (acesso administrativo pleno); usuário
    inválido/desativado possui nenhum.
    """
    if autorizacao.eh_superadmin(usuario):
        return frozenset(RECURSOS_VALIDOS)
    plano = plano_de(usuario)
    if plano is None:
        return frozenset()
    return RECURSOS_DO_PLANO.get(plano, frozenset())


def tem_entitlement(usuario, recurso):
    """True quando ``usuario`` pode usar o recurso comercial ``recurso``.

    Decisão central e única: SUPERADMIN sempre True; demais usuários conforme
    o catálogo do plano; usuário desativado/``None`` sempre False.
    """
    return recurso in entitlements_de(usuario)


def obter_limite(usuario, recurso):
    """Limite numérico de ``recurso`` para ``usuario``.

    Retorna ``None`` (ilimitado) para SUPERADMIN, o limite do plano para os
    demais usuários ativos, e ``0`` (nenhum) para usuário desativado/``None``
    ou recurso desconhecido.
    """
    if autorizacao.eh_superadmin(usuario):
        return None
    plano = plano_de(usuario)
    if plano is None:
        return 0
    return LIMITES_DO_PLANO.get(plano, {}).get(recurso, 0)


def atingiu_limite(usuario, recurso, contagem_atual):
    """True quando ``contagem_atual`` de ``recurso`` está no limite do usuário.

    Comparação central e única para o enforcement de limites (Fase 6, Etapa 9):
    - SUPERADMIN (limite ``None``) nunca está no limite — permanece ilimitado;
    - usuário desativado/``None`` (limite ``0``) está sempre no limite;
    - demais usuários conforme o catálogo do plano (``contagem >= limite``).

    Nenhuma rota compara planos diretamente: a camada de serviço consulta esta
    função com a contagem corrente do recurso do próprio usuário autenticado.
    """
    limite = obter_limite(usuario, recurso)
    if limite is None:
        return False
    return contagem_atual >= limite


def resumo_do_plano(plano):
    """Resumo serializável do catálogo de ``plano`` (sem segredos)."""
    if plano not in PLANOS_VALIDOS:
        return {"plano": plano, "entitlements": [], "limites": {}}
    return {
        "plano": plano,
        "entitlements": sorted(RECURSOS_DO_PLANO.get(plano, frozenset())),
        "limites": dict(LIMITES_DO_PLANO.get(plano, {})),
    }


def resumo_do_usuario(usuario):
    """Resumo de plano/entitlements efetivos do ``usuario`` autenticado.

    SUPERADMIN aparece com todos os recursos e limites ilimitados (``None``).
    Usuário desativado/``None`` aparece sem plano. Nenhum segredo é exposto.
    """
    if autorizacao.eh_superadmin(usuario):
        return {
            "plano": plano_de(usuario),
            "entitlements": sorted(RECURSOS_VALIDOS),
            "limites": {recurso: None for recurso in sorted(LIMITES_VALIDOS)},
        }
    plano = plano_de(usuario)
    if plano is None:
        return {"plano": None, "entitlements": [], "limites": {}}
    return resumo_do_plano(plano)


# ---------------------------------------------------------------------------
# GESTÃO DE PLANOS (anti-escalonamento)
# ---------------------------------------------------------------------------


def pode_alterar_plano(autor, novo_plano):
    """True apenas para SUPERADMIN ativo alterando para um plano válido.

    Nenhum outro papel (incluindo ADMIN) altera planos; nenhum usuário altera o
    próprio plano. ``novo_plano`` precisa estar no catálogo fechado.
    """
    if novo_plano not in PLANOS_VALIDOS:
        return False
    return autorizacao.eh_superadmin(autor)


def alterar_plano(autor, alvo, novo_plano, session=None, ip=None):
    """Altera o plano de ``alvo`` — exclusivamente por um SUPERADMIN ativo.

    Levanta ``autorizacao.PermissaoNegadaError`` quando ``autor`` não é
    SUPERADMIN, ``ValueError`` para plano inválido ou usuário inexistente, e
    ``None`` quando ``alvo`` não existe. Persiste e audita ``PLANO_ALTERADO``.
    Nenhum segredo é manipulado.
    """
    if not autorizacao.eh_superadmin(autor):
        raise autorizacao.PermissaoNegadaError(
            permissao=PERMISSAO_ADMINISTRAR_PLANOS,
            papel=autorizacao.papel_de(autor),
            usuario_id=getattr(autor, "id", None),
        )
    if novo_plano not in PLANOS_VALIDOS:
        raise ValueError(
            f"Plano inválido: {novo_plano!r}. Válidos: {', '.join(PLANOS_VALIDOS)}."
        )
    if alvo is None:
        raise ValueError("Usuário alvo não encontrado.")

    with _sessao(session) as s:
        alvo = s.merge(alvo)
        alvo.plano = novo_plano
        s.commit()
        auditoria.registrar_evento(
            acao=ACAO_PLANO_ALTERADO,
            alvo=_alvo(alvo),
            detalhe=f"plano={novo_plano}",
            usuario_id=alvo.id,
            ip=ip,
            session=s,
        )
        return alvo
