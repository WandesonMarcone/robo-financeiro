"""Serviço de API Keys (Fase 5, Etapa 9).

Gerencia o ciclo de vida das chaves de API dos usuários reutilizando o modelo
``ChaveApi`` (Etapa 1), a trilha de auditoria (``services/auditoria.py``), o
motor central de autorização (``services/autorizacao.py``) e o padrão de sessão
do projeto. Nenhuma responsabilidade existente é duplicada.

Garantias de segurança:
- A chave original é gerada com ``secrets.token_urlsafe`` e retornada somente no
  momento da criação; apenas o hash SHA-256 é persistido.
- A chave original nunca é recuperável posteriormente, nunca vai para logs e
  nunca vai para a auditoria (nem o hash completo).
- Validação sem distinção de motivo: chave inexistente/revogada/expirada e
  usuário inexistente/desativado retornam ``None``.
- Cada usuário gerencia apenas as PRÓPRIAS chaves; operações administrativas
  sobre chaves de outros usuários exigem permissão da matriz central (nenhuma
  permissão nova é criada; SUPERADMIN permanece irrestrito via ``"*"``).

Nesta etapa não há endpoints HTTP, Blueprint, login web nem integração da chave
com o transporte — apenas o serviço de ciclo de vida.
"""
import hashlib
import logging
import secrets
from datetime import datetime

from pipeline_dados.banco_dados import ChaveApi, Usuario
from services import auditoria, autorizacao
from services.usuarios import _sessao

logger = logging.getLogger(__name__)


def _alvo(usuario):
    """Rótulo de alvo para auditoria (email quando disponível, senão o id)."""
    if usuario is None:
        return None
    email = getattr(usuario, "email", None)
    return email if email else f"usuario:{usuario.id}"


def _hash_chave(chave):
    """SHA-256 da chave original (única forma persistida e consultada)."""
    return hashlib.sha256(chave.encode("utf-8")).hexdigest()


def _autorizar(autor, alvo, permissao):
    """Exige permissão da matriz central para operar sobre chaves de OUTRO usuário.

    ``autor`` None (ou o próprio dono das chaves) é auto-atendimento e é
    permitido. Qualquer outro usuário precisa da permissão informada
    (SUPERADMIN possui ``"*"``). Levanta ``PermissaoNegadaError`` quando negado.
    """
    if autor is None:
        return
    if getattr(autor, "id", None) == getattr(alvo, "id", None):
        return
    autorizacao.requer_permissao(autor, permissao)


# ==========================================
# CRIAÇÃO
# ==========================================


def criar_chave_api(
    usuario, rotulo, expira_em=None, autor=None, session=None, ip=None
):
    """Cria uma API Key para ``usuario`` e retorna a chave original (uma única vez).

    A chave criptograficamente aleatória é retornada apenas aqui e nunca é
    persistida: somente o hash SHA-256 é gravado na tabela ``chaves_api``, com
    ``rotulo``, ``expira_em`` opcional e ``ativa=True``. Registra
    ``API_KEY_CRIADA`` na auditoria (o rótulo pode ser registrado; a chave e o
    hash, nunca). ``autor`` é opcional: o próprio usuário cria suas chaves;
    outro usuário precisa da permissão ``usuarios.criar`` da matriz central.
    """
    if usuario is None or getattr(usuario, "id", None) is None:
        raise ValueError("Usuário inválido para criar API Key.")
    if not getattr(usuario, "ativo", False):
        raise ValueError("Usuário desativado não pode criar API Key.")
    if not rotulo or not str(rotulo).strip():
        raise ValueError("O rótulo da API Key é obrigatório.")
    if expira_em is not None and expira_em <= datetime.now():
        raise ValueError("A expiração deve ser futura.")

    _autorizar(autor, usuario, "usuarios.criar")

    chave = secrets.token_urlsafe(32)
    chave_hash = _hash_chave(chave)

    with _sessao(session) as s:
        registro = ChaveApi(
            usuario_id=usuario.id,
            rotulo=str(rotulo).strip(),
            chave_hash=chave_hash,
            ativa=True,
            expira_em=expira_em,
        )
        s.add(registro)
        s.commit()
        auditoria.registrar_evento(
            acao="API_KEY_CRIADA",
            alvo=_alvo(usuario),
            detalhe=f"rotulo={registro.rotulo}",
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
    return chave


# ==========================================
# LISTAGEM
# ==========================================


def listar_chaves_api(usuario, autor=None, session=None):
    """Lista as API Keys de ``usuario`` (próprio escopo).

    O próprio usuário lista suas chaves; outro ``autor`` precisa da permissão
    ``usuarios.ler`` da matriz central. Retorna os registros ``ChaveApi`` em
    ordem de criação (contêm apenas o hash — nunca a chave original).
    """
    if usuario is None or getattr(usuario, "id", None) is None:
        return []
    _autorizar(autor, usuario, "usuarios.ler")
    with _sessao(session) as s:
        return (
            s.query(ChaveApi)
            .filter(ChaveApi.usuario_id == usuario.id)
            .order_by(ChaveApi.id)
            .all()
        )


# ==========================================
# REVOGAÇÃO
# ==========================================


def revogar_chave_api(usuario, chave_id, autor=None, session=None, ip=None):
    """Revoga (``ativa=False``) uma API Key de ``usuario``.

    O próprio usuário revoga as próprias chaves; outro ``autor`` precisa da
    permissão ``usuarios.desativar``. O registro não é apagado e a chave torna-se
    imediatamente inválida. O filtro inclui ``usuario_id`` (isolamento): um
    usuário nunca revoga chave de outro pelo id. Retorna ``True`` em caso de
    sucesso (ou se já inativa) e ``False`` quando a chave não pertence a
    ``usuario`` ou não existe. Registra ``API_KEY_REVOGADA`` na auditoria.
    """
    if usuario is None or getattr(usuario, "id", None) is None:
        return False
    _autorizar(autor, usuario, "usuarios.desativar")
    with _sessao(session) as s:
        registro = (
            s.query(ChaveApi)
            .filter(ChaveApi.id == chave_id, ChaveApi.usuario_id == usuario.id)
            .first()
        )
        if registro is None:
            return False
        if not registro.ativa:
            return True
        registro.ativa = False
        s.commit()
        auditoria.registrar_evento(
            acao="API_KEY_REVOGADA",
            alvo=_alvo(usuario),
            detalhe=f"rotulo={registro.rotulo}",
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
    return True


# ==========================================
# VALIDAÇÃO
# ==========================================


def validar_chave_api(chave, session=None):
    """Valida a chave apresentada pelo consumidor e retorna o ``Usuario``.

    Verifica, em ordem: existência do registro, chave ativa, não-expiração,
    existência do usuário e usuário ativo. Qualquer falha retorna ``None`` —
    sem revelar qual etapa falhou. Uma chave detectada como expirada é marcada
    como inativa (``ativa=False``) sem comprometer o fluxo. Falha de banco é
    tratada como chave inválida (fail-closed).
    """
    if not isinstance(chave, str) or not chave:
        return None
    chave_hash = _hash_chave(chave)
    try:
        with _sessao(session) as s:
            registro = (
                s.query(ChaveApi).filter(ChaveApi.chave_hash == chave_hash).first()
            )
            if registro is None:
                return None
            if not registro.ativa:
                return None
            if registro.expira_em is not None and registro.expira_em <= datetime.now():
                registro.ativa = False
                s.commit()
                return None
            usuario = s.get(Usuario, registro.usuario_id)
            if usuario is None or not usuario.ativo:
                return None
            return usuario
    except Exception as e:
        logger.warning("Falha ao validar API Key (tratada como inválida): %s", e)
        return None
