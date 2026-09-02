"""Gerenciamento de sessões, tokens, expiração e logout (Fase 5, Etapa 7).

Transforma o modelo ``Sessao`` (Fase 5) em um mecanismo funcional de
autenticação por sessão, reutilizando o que já foi implementado:

- ``services/usuarios.py``: autenticação por credenciais (``email + senha``) e
  gestão de usuários; a verificação de senha não é duplicada aqui.
- ``services/auditoria.py``: trilha de eventos sem vazamento de segredos.
- ``services/autorizacao.py``: a revogação administrativa respeita o motor de
  permissões (nenhuma permissão nova é criada).

Garantias de segurança:
- Token opaco e criptograficamente aleatório (``secrets.token_urlsafe``);
- Apenas o hash SHA-256 do token é persistido (``token_hash``); o token bruto
  existe somente em memória e nunca é gravado no banco, em logs ou na auditoria;
- Sessão expirada, revogada, usuário inexistente ou desativado sempre resultam
  em ausência de autenticação, sem revelar qual etapa falhou;
- Falha de banco é tratada como não autenticado (fail-closed) e nunca derruba
  o processo, seguindo o padrão do projeto (``seed``/``auditoria``).

O TTL das sessões usa a configuração já prevista ``SESSAO_TTL_HORAS``.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta

import config
from pipeline_dados.banco_dados import Sessao, Usuario
from services import auditoria, autorizacao
from services.usuarios import _sessao

logger = logging.getLogger(__name__)

# Origens aceitas pela Fase 5. A integração completa com o Telegram é de etapa
# posterior; aqui apenas o campo "origem" da tabela é preenchido.
ORIGENS_ACEITAS = ("web", "api", "telegram")
ORIGEM_PADRAO = "web"


def _alvo(usuario):
    """Rótulo de alvo para auditoria (email quando disponível, senão o id)."""
    if usuario is None:
        return None
    email = getattr(usuario, "email", None)
    return email if email else f"usuario:{usuario.id}"


def _alvo_da_sessao(sessao):
    """Rótulo de alvo a partir de uma sessão, sem expor o hash/token."""
    if sessao is None:
        return None
    if sessao.usuario is not None:
        return _alvo(sessao.usuario)
    return f"usuario:{sessao.usuario_id}"


def _hash_token(token):
    """SHA-256 do token bruto (única forma persistida e consultada)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _validar_origem(origem):
    """Valida a origem da sessão contra o conjunto aceito pelo projeto."""
    if origem not in ORIGENS_ACEITAS:
        raise ValueError(
            f"Origem inválida: {origem!r}. Válidas: {', '.join(ORIGENS_ACEITAS)}."
        )


# ==========================================
# CRIAÇÃO DE SESSÃO
# ==========================================


def criar_sessao(usuario, origem=ORIGEM_PADRAO, session=None, ip=None):
    """Cria uma sessão autenticada e retorna o token bruto (uma única vez).

    O token criptograficamente aleatório é retornado apenas aqui e nunca é
    persistido: somente o hash SHA-256 é gravado na tabela ``sessoes``,
    associado a ``usuario_id``, ``criada_em``, ``expira_em`` (usando
    ``SESSAO_TTL_HORAS``), ``revogada=False`` e ``origem``. Registra
    ``SESSAO_CRIADA`` na auditoria sem qualquer segredo.
    """
    if usuario is None or getattr(usuario, "id", None) is None:
        raise ValueError("Usuário inválido para criar sessão.")
    if not getattr(usuario, "ativo", False):
        raise ValueError("Usuário desativado não pode criar sessão.")
    _validar_origem(origem)

    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    agora = datetime.now()
    expira_em = agora + timedelta(hours=config.SESSAO_TTL_HORAS)

    with _sessao(session) as s:
        sessao = Sessao(
            usuario_id=usuario.id,
            token_hash=token_hash,
            criada_em=agora,
            expira_em=expira_em,
            revogada=False,
            origem=origem,
        )
        s.add(sessao)
        s.commit()
        auditoria.registrar_evento(
            acao="SESSAO_CRIADA",
            alvo=_alvo(usuario),
            detalhe=f"origem={origem}",
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
    return token


# ==========================================
# VALIDAÇÃO DE SESSÃO
# ==========================================


def validar_sessao(token, session=None):
    """Valida o token bruto e retorna o ``Usuario`` autenticado, ou ``None``.

    Verifica, em ordem: existência da sessão, não-revogação, não-expiração,
    existência do usuário e usuário ativo. Qualquer falha retorna ``None`` —
    sem revelar qual etapa falhou e sem mensagens distintas. Uma sessão
    detectada como expirada é marcada como revogada/encerrada (``SESSAO_EXPIRADA``)
    sem comprometer o fluxo. Falha de banco é tratada como não autenticado.
    """
    if not isinstance(token, str) or not token:
        return None
    token_hash = _hash_token(token)
    try:
        with _sessao(session) as s:
            sessao = s.query(Sessao).filter(Sessao.token_hash == token_hash).first()
            if sessao is None:
                return None
            if sessao.revogada:
                return None
            if sessao.expira_em <= datetime.now():
                sessao.revogada = True
                s.commit()
                auditoria.registrar_evento(
                    acao="SESSAO_EXPIRADA",
                    alvo=_alvo_da_sessao(sessao),
                    usuario_id=sessao.usuario_id,
                    sucesso=False,
                    session=s,
                )
                return None
            usuario = s.get(Usuario, sessao.usuario_id)
            if usuario is None or not usuario.ativo:
                return None
            return usuario
    except Exception as e:
        logger.warning("Falha ao validar sessão (tratada como não autenticado): %s", e)
        return None


# ==========================================
# LOGOUT E REVOGAÇÃO
# ==========================================


def revogar_sessao(token, session=None, ip=None):
    """Revoga a sessão autenticada pelo token bruto (logout).

    Localiza pelo hash SHA-256, marca ``revogada=True`` e registra
    ``SESSAO_REVOGADA`` na auditoria. Após a revogação o mesmo token torna-se
    inválido. Retorna ``True`` quando a sessão existe (recém-revogada ou já
    revogada) e ``False`` quando não existe ou o token é inválido. O token bruto
    nunca é persistido nem registrado.
    """
    if not isinstance(token, str) or not token:
        return False
    token_hash = _hash_token(token)
    try:
        with _sessao(session) as s:
            sessao = s.query(Sessao).filter(Sessao.token_hash == token_hash).first()
            if sessao is None:
                return False
            if not sessao.revogada:
                sessao.revogada = True
                s.commit()
                auditoria.registrar_evento(
                    acao="SESSAO_REVOGADA",
                    alvo=_alvo_da_sessao(sessao),
                    usuario_id=sessao.usuario_id,
                    ip=ip,
                    session=s,
                )
        return True
    except Exception as e:
        logger.warning("Falha ao revogar sessão: %s", e)
        return False


def revogar_sessao_por_id(sessao_id, autor, session=None, ip=None):
    """Revoga uma sessão específica pelo id (revogação administrativa).

    Respeita o motor de autorização: ``autor`` deve possuir a permissão
    ``usuarios.desativar`` (nenhuma permissão nova é criada). Retorna ``False``
    se a sessão não existir e ``True`` em caso de sucesso (ou se já estava
    revogada). ``PermissaoNegadaError`` é propagada para o chamador.
    """
    autorizacao.requer_permissao(autor, "usuarios.desativar")
    try:
        with _sessao(session) as s:
            sessao = s.get(Sessao, sessao_id)
            if sessao is None:
                return False
            if not sessao.revogada:
                sessao.revogada = True
                s.commit()
                auditoria.registrar_evento(
                    acao="SESSAO_REVOGADA",
                    alvo=_alvo_da_sessao(sessao),
                    usuario_id=sessao.usuario_id,
                    ip=ip,
                    session=s,
                )
        return True
    except Exception as e:
        logger.warning("Falha ao revogar sessão por id: %s", e)
        return False


def revogar_sessoes_usuario(usuario, autor=None, session=None, ip=None):
    """Revoga todas as sessões (não revogadas) de um usuário.

    Quando ``autor`` é um usuário diferente do dono das sessões, exige a
    permissão ``usuarios.desativar`` (motor de autorização). Sem ``autor`` (ou
    com ``autor`` sendo o próprio usuário) a operação é tratada como
    auto-atendimento. Retorna a quantidade de sessões revogadas e registra
    ``SESSOES_USUARIO_REVOGADAS`` quando houver revogações.
    """
    if usuario is None or getattr(usuario, "id", None) is None:
        return 0
    if autor is not None and getattr(autor, "id", None) != usuario.id:
        autorizacao.requer_permissao(autor, "usuarios.desativar")
    try:
        with _sessao(session) as s:
            sessoes = (
                s.query(Sessao)
                .filter(Sessao.usuario_id == usuario.id, Sessao.revogada.is_(False))
                .all()
            )
            for sessao in sessoes:
                sessao.revogada = True
            s.commit()
            quantidade = len(sessoes)
            if quantidade:
                auditoria.registrar_evento(
                    acao="SESSOES_USUARIO_REVOGADAS",
                    alvo=_alvo(usuario),
                    detalhe=f"quantidade={quantidade}",
                    usuario_id=usuario.id,
                    ip=ip,
                    session=s,
                )
        return quantidade
    except Exception as e:
        logger.warning("Falha ao revogar sessões do usuário: %s", e)
        return 0
