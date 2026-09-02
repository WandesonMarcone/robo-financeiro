"""Autenticação web: cadastro, login e logout (Fase 6, Etapa 2).

Endpoints públicos de autenticação por ``email + senha`` com sessão,
reutilizando exclusivamente os serviços existentes — nenhum mecanismo paralelo
de senha, sessão ou usuário é criado:

- ``services/usuarios.py``: ``criar_usuario`` (cadastro) e ``autenticar``
  (credenciais), incluindo a auditoria ``USUARIO_CRIADO``/``LOGIN`` e a
  resposta indistinguível para credenciais inválidas (anti-enumeração);
- ``services/sessoes.py``: ``criar_sessao`` (login) e ``revogar_sessao``
  (logout), incluindo a auditoria ``SESSAO_CRIADA``/``SESSAO_REVOGADA`` e o TTL
  ``SESSAO_TTL_HORAS``;
- ``api/auth.py``: o "me" autenticado já existe em ``GET /api/v1/me`` e NÃO é
  duplicado aqui; as rotas protegidas continuam reconhecendo ``X-Session-Token``
  e ``X-API-Key`` pela infraestrutura existente.

Regras de segurança:
- ``POST /auth/register`` é público e cria SEMPRE um ``USER`` ativo: ignora
  qualquer tentativa do cliente de escolher papel/ativo/Telegram, normaliza o
  email e nunca devolve a senha (nem o hash);
- ``POST /auth/login`` devolve o token bruto apenas na resposta do login; o
  token nunca é persistido (somente o hash SHA-256), nunca vai para logs nem
  para a auditoria;
- ``POST /auth/logout`` revoga a sessão identificada por ``X-Session-Token``;
  tokens inexistentes/revogados não revelam detalhes internos.
"""
from flask import Blueprint, request

from api import dependencias
from api.respostas import resposta_erro, resposta_ok
from api.serializadores import serializar_usuario
from services import sessoes, usuarios

bp = Blueprint("api_auth_web", __name__)

# Origem das sessões criadas pelo login web (valor aceito por services/sessoes).
ORIGEM_WEB = "web"

# Mensagem genérica de credenciais inválidas (indistinguível, anti-enumeração).
MSG_CREDENCIAIS_INVALIDAS = "Credenciais inválidas."


def _ip():
    """IP de origem da requisição para a trilha de auditoria."""
    return request.remote_addr


def _normalizar_email(email):
    """Normaliza o email: remove espaços e converte para minúsculas."""
    return str(email).strip().lower()


def _corpo():
    """Corpo JSON da requisição, tolerante a payloads ausentes/inválidos."""
    return request.get_json(silent=True) or {}


@bp.post("/register")
def registrar():
    """Cadastro público: cria um ``USER`` ativo com email normalizado.

    O cadastro público NÃO pode escolher papel (nasce ``USER``), NÃO pode criar
    ADMIN/SUPERADMIN, NÃO pode definir ``ativo`` nem vincular Telegram — campos
    como ``papel``, ``ativo`` e ``telegram_user_id`` no corpo são ignorados. A
    duplicidade de email é rejeitada com mensagem genérica (sem expor se a conta
    existe). Auditoria via ``usuarios.criar_usuario`` (``USUARIO_CRIADO``).
    """
    corpo = _corpo()

    nome = corpo.get("nome")
    email = corpo.get("email")
    senha = corpo.get("senha")

    if not nome or not str(nome).strip():
        return resposta_erro("O nome é obrigatório.", 400)
    if not email or not str(email).strip():
        return resposta_erro("O email é obrigatório.", 400)
    if not isinstance(senha, str) or len(senha) < usuarios.SENHA_MINIMA:
        return resposta_erro(
            f"A senha deve ter no mínimo {usuarios.SENHA_MINIMA} caracteres.", 400
        )

    email_normalizado = _normalizar_email(email)
    sessao = dependencias.obter_sessao()
    try:
        if usuarios.buscar_usuario_por_email(email_normalizado, session=sessao) is not None:
            return resposta_erro("Não foi possível concluir o cadastro.", 400)
        novo = usuarios.criar_usuario(
            nome=nome,
            email=email_normalizado,
            senha=senha,
            session=sessao,
            ip=_ip(),
        )
        return resposta_ok(serializar_usuario(novo), meta={"criado": True})
    except ValueError:
        sessao.rollback()
        return resposta_erro("Não foi possível concluir o cadastro.", 400)
    finally:
        sessao.close()


@bp.post("/login")
def login():
    """Autentica e cria a sessão, devolvendo o token bruto (única exposição).

    Fluxo obrigatório: ``usuarios.autenticar`` -> ``sessoes.criar_sessao``.
    Falhas de credenciais (email inexistente, senha incorreta ou usuário
    desativado) produzem a mesma resposta genérica ``401``. O token bruto é
    retornado apenas aqui; somente o hash é persistido e nada é registrado em
    logs/auditoria.
    """
    corpo = _corpo()
    email = corpo.get("email")
    senha = corpo.get("senha")

    if not isinstance(email, str) or not email.strip():
        return resposta_erro(MSG_CREDENCIAIS_INVALIDAS, 401)
    if not isinstance(senha, str) or not senha:
        return resposta_erro(MSG_CREDENCIAIS_INVALIDAS, 401)

    email_normalizado = _normalizar_email(email)
    sessao = dependencias.obter_sessao()
    try:
        usuario = usuarios.autenticar(
            email_normalizado, senha, session=sessao, ip=_ip()
        )
        if usuario is None:
            return resposta_erro(MSG_CREDENCIAIS_INVALIDAS, 401)

        token = sessoes.criar_sessao(
            usuario, origem=ORIGEM_WEB, session=sessao, ip=_ip()
        )
        return resposta_ok(
            {"token": token, "usuario": serializar_usuario(usuario)}
        )
    finally:
        sessao.close()


@bp.post("/logout")
def logout():
    """Revoga a sessão atual identificada por ``X-Session-Token``.

    Reutiliza ``sessoes.revogar_sessao`` (auditoria ``SESSAO_REVOGADA``). A
    ausência do cabeçalho é um erro do cliente (``401``); tokens inexistentes ou
    já revogados completam com sucesso genérico, sem revelar detalhes internos.
    Após o logout, o mesmo token resulta em ``401`` nas rotas protegidas.
    """
    token = (request.headers.get("X-Session-Token") or "").strip()
    if not token:
        return resposta_erro("Token de sessão ausente.", 401)

    sessao = dependencias.obter_sessao()
    try:
        sessoes.revogar_sessao(token, session=sessao, ip=_ip())
    finally:
        sessao.close()
    return resposta_ok({"logout": True})
