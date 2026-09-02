"""Endpoints de usuários da API (Fase 5, Etapa 10 e Fase 6, Etapa 1).

- ``GET /api/v1/me`` — permissão ``conta.propria`` (próprio escopo);
- ``GET /api/v1/usuarios`` — permissão ``usuarios.ler``;
- ``GET /api/v1/usuarios/<id>`` — permissão ``usuarios.ler``;
- ``POST /api/v1/usuarios`` — permissão ``usuarios.criar`` + política central
  de papéis (``autorizacao.pode_criar_usuario_com_papel``);
- ``PATCH /api/v1/usuarios/<id>`` — conta própria via ``conta.propria`` ou
  administração de outro usuário via ``usuarios.criar``, respeitando a proteção
  de SUPERADMIN;
- ``POST /api/v1/usuarios/<id>/ativar`` — permissão ``usuarios.ativar``;
- ``POST /api/v1/usuarios/<id>/desativar`` — permissão ``usuarios.desativar``;
- ``POST /api/v1/usuarios/<id>/papel`` — permissão ``usuarios.alterar_papel``
  + ``autorizacao.pode_alterar_papel``;
- ``POST /api/v1/usuarios/<id>/telegram`` — permissão ``telegram.administrar``
  (via ``services/telegram.py``);
- ``DELETE /api/v1/usuarios/<id>/telegram`` — idem;
- ``POST /api/v1/usuarios/<id>/sessoes/revogar`` — permissão
  ``usuarios.desativar`` (via ``services/sessoes.py``);
- ``GET /api/v1/me/plano`` — permissão ``conta.propria`` (próprio escopo,
  Fase 6, Etapa 8);
- ``POST /api/v1/usuarios/<id>/plano`` — exclusivo de SUPERADMIN via
  ``services/planos.alterar_plano`` (Fase 6, Etapa 8).

Toda decisão de autorização passa pelo motor central ``services/autorizacao.py``
(``rota_protegida``, ``tem_permissao``, ``requer_permissao``,
``pode_alterar_papel``, ``pode_criar_usuario_com_papel`` e
``usuario_protegido``). Nenhuma regra paralela é criada. Respostas nunca expõem
senha, hash, token, API Key ou segredos; tentativas administrativas negadas são
registradas na auditoria.

O plano comercial (Fase 6, Etapa 8) NUNCA é aceito do cliente: os campos
``plano`` enviados em ``POST /usuarios`` ou ``PATCH /usuarios/<id>`` são
rejeitados com erro explícito — a única via de alteração é o endpoint próprio,
restrito ao SUPERADMIN (``services/planos.py``).
"""
from flask import Blueprint, g, request

from api.auth import rota_protegida
from api.respostas import resposta_erro, resposta_ok
from api.serializadores import serializar_usuario
from pipeline_dados.banco_dados import Usuario
from services import (
    auditoria,
    autorizacao,
    planos,
    sessoes,
    telegram,
    usuarios,
)

bp = Blueprint("api_usuarios", __name__)

# Eventos de auditoria para tentativas administrativas negadas (sem segredos).
ACAO_CRIACAO_NEGADA = "USUARIO_CRIACAO_NEGADA"
ACAO_ALTERACAO_NEGADA = "USUARIO_ALTERACAO_NEGADA"
ACAO_PAPEL_NEGADA = "PAPEL_ALTERACAO_NEGADA"

# Campos atualizáveis via PATCH (nunca papel, ativo ou Telegram — esses têm
# endpoints próprios com a autorização adequada).
CAMPOS_ATUALIZAVEIS = ("nome", "email", "senha")

# Campo que o cliente NUNCA pode definir/alterar (o plano só muda via endpoint
# próprio, restrito ao SUPERADMIN — ``services/planos.py``).
CAMPOS_PLANO_REJEITADOS = ("plano",)


def _alvo(usuario):
    """Rótulo de alvo para auditoria (email quando disponível, senão o id)."""
    if usuario is None:
        return None
    email = getattr(usuario, "email", None)
    return email if email else f"usuario:{usuario.id}"


def _ip():
    """IP de origem da requisição para a trilha de auditoria."""
    return request.remote_addr


def _buscar_alvo(sessao, usuario_id):
    """Busca o usuário alvo, retornando ``None`` quando inexistente."""
    return sessao.get(Usuario, usuario_id)


def _auditar_negado(acao, autor, alvo, detalhe, sessao):
    """Registra uma tentativa administrativa negada na auditoria."""
    auditoria.registrar_evento(
        acao=acao,
        alvo=_alvo(alvo),
        detalhe=detalhe,
        usuario_id=getattr(autor, "id", None),
        ip=_ip(),
        sucesso=False,
        session=sessao,
    )


def _negado_por_protecao(autor, alvo, sessao):
    """True quando ``autor`` tenta administrar um SUPERADMIN protegido.

    Apenas SUPERADMIN administra outro SUPERADMIN (política central). A
    tentativa é auditada como ``ESCALONAMENTO_NEGADO`` antes de retornar.
    """
    if autorizacao.usuario_protegido(alvo) and not autorizacao.eh_superadmin(autor):
        _auditar_negado(
            telegram.ACAO_ESCALONAMENTO_NEGADO,
            autor,
            alvo,
            "motivo=superadmin_protegido",
            sessao,
        )
        return True
    return False


@bp.get("/me")
@rota_protegida("conta.propria")
def usuario_atual():
    """Dados públicos e não sensíveis do usuário autenticado."""
    return resposta_ok(serializar_usuario(g.usuario))


@bp.get("/me/plano")
@rota_protegida("conta.propria")
def meu_plano():
    """Plano/entitlements efetivos do usuário autenticado (somente leitura).

    Reflete exclusivamente a camada central ``services/planos.py``. O cliente
    nunca informa o plano: apenas consulta o que o sistema decidiu.
    """
    return resposta_ok(planos.resumo_do_usuario(g.usuario))


# ==========================================
# ADMINISTRAÇÃO DE USUÁRIOS
# ==========================================


@bp.get("/usuarios")
@rota_protegida("usuarios.ler")
def listar_usuarios():
    """Lista usuários conforme a autorização da matriz central."""
    sessao = g.sessao
    apenas_ativos = request.args.get("ativos") == "true"
    registros = usuarios.listar_usuarios(
        apenas_ativos=apenas_ativos, session=sessao
    )
    return resposta_ok(
        [serializar_usuario(registro) for registro in registros],
        meta={"total": len(registros)},
    )


@bp.get("/usuarios/<int:usuario_id>")
@rota_protegida("usuarios.ler")
def consultar_usuario(usuario_id):
    """Consulta um usuário específico (somente dados não sensíveis)."""
    sessao = g.sessao
    alvo = _buscar_alvo(sessao, usuario_id)
    if alvo is None:
        return resposta_erro("Usuário não encontrado.", 404)
    return resposta_ok(serializar_usuario(alvo))


@bp.post("/usuarios")
@rota_protegida("usuarios.criar")
def criar_usuario_rota():
    """Cria um usuário respeitando a política central de papéis."""
    sessao = g.sessao
    autor = g.usuario
    corpo = request.get_json(silent=True) or {}

    nome = corpo.get("nome")
    if not nome or not str(nome).strip():
        return resposta_erro("O nome do usuário é obrigatório.", 400)

    if any(campo in corpo for campo in CAMPOS_PLANO_REJEITADOS):
        return resposta_erro(
            "O plano do usuário não pode ser definido no cadastro: use o "
            "endpoint próprio (somente SUPERADMIN).",
            400,
        )

    papel = corpo.get("papel", usuarios.PAPEL_PADRAO)
    if papel not in usuarios.PAPEIS_VALIDOS:
        return resposta_erro(
            f"Papel inválido: {papel!r}. Válidos: {', '.join(usuarios.PAPEIS_VALIDOS)}.",
            400,
        )

    telegram_user_id = _interpretar_telegram_id(corpo.get("telegram_user_id"))
    if isinstance(telegram_user_id, tuple):
        return telegram_user_id

    if not autorizacao.pode_criar_usuario_com_papel(autor, papel):
        _auditar_negado(
            ACAO_CRIACAO_NEGADA, autor, None, f"motivo=papel_nao_atribuivel,papel={papel}", sessao
        )
        return resposta_erro("Não é permitido criar usuário com este papel.", 403)

    try:
        novo = usuarios.criar_usuario(
            nome=nome,
            email=corpo.get("email"),
            senha=corpo.get("senha"),
            papel=papel,
            telegram_user_id=telegram_user_id,
            session=sessao,
            ip=_ip(),
        )
    except ValueError as exc:
        return resposta_erro(str(exc), 400)

    return resposta_ok(serializar_usuario(novo), meta={"criado": True})


@bp.patch("/usuarios/<int:usuario_id>")
@rota_protegida("conta.propria")
def atualizar_usuario_rota(usuario_id):
    """Atualiza dados permitidos: própria conta ou administração autorizada."""
    sessao = g.sessao
    autor = g.usuario
    alvo = _buscar_alvo(sessao, usuario_id)
    if alvo is None:
        return resposta_erro("Usuário não encontrado.", 404)

    eh_proprio = alvo.id == autor.id
    if not eh_proprio:
        if _negado_por_protecao(autor, alvo, sessao):
            return resposta_erro("Acesso negado.", 403)
        try:
            autorizacao.requer_permissao(autor, "usuarios.criar")
        except autorizacao.PermissaoNegadaError:
            _auditar_negado(
                ACAO_ALTERACAO_NEGADA, autor, alvo, "motivo=sem_permissao", sessao
            )
            return resposta_erro("Acesso negado.", 403)

    corpo = request.get_json(silent=True) or {}
    if any(campo in corpo for campo in CAMPOS_PLANO_REJEITADOS):
        return resposta_erro(
            "O plano não pode ser alterado por este endpoint: use o endpoint "
            "próprio (somente SUPERADMIN).",
            400,
        )
    if not any(campo in corpo for campo in CAMPOS_ATUALIZAVEIS):
        return resposta_erro("Nenhum dado permitido para atualizar.", 400)

    try:
        usuarios.atualizar_dados_usuario(
            alvo,
            nome=corpo.get("nome"),
            email=corpo.get("email"),
            senha=corpo.get("senha"),
            session=sessao,
            ip=_ip(),
        )
    except ValueError as exc:
        return resposta_erro(str(exc), 400)

    return resposta_ok(serializar_usuario(sessao.get(Usuario, usuario_id)))


@bp.post("/usuarios/<int:usuario_id>/ativar")
@rota_protegida("usuarios.ativar")
def ativar_usuario_rota(usuario_id):
    """Reativa um usuário (restaura o acesso conforme as regras existentes)."""
    sessao = g.sessao
    autor = g.usuario
    alvo = _buscar_alvo(sessao, usuario_id)
    if alvo is None:
        return resposta_erro("Usuário não encontrado.", 404)
    if _negado_por_protecao(autor, alvo, sessao):
        return resposta_erro("Acesso negado.", 403)
    usuarios.ativar_usuario(alvo, session=sessao, ip=_ip())
    return resposta_ok(serializar_usuario(sessao.get(Usuario, usuario_id)))


@bp.post("/usuarios/<int:usuario_id>/desativar")
@rota_protegida("usuarios.desativar")
def desativar_usuario_rota(usuario_id):
    """Desativa um usuário (não poderá mais autenticar; dados preservados)."""
    sessao = g.sessao
    autor = g.usuario
    alvo = _buscar_alvo(sessao, usuario_id)
    if alvo is None:
        return resposta_erro("Usuário não encontrado.", 404)
    if _negado_por_protecao(autor, alvo, sessao):
        return resposta_erro("Acesso negado.", 403)
    usuarios.desativar_usuario(alvo, session=sessao, ip=_ip())
    return resposta_ok(serializar_usuario(sessao.get(Usuario, usuario_id)))


@bp.post("/usuarios/<int:usuario_id>/papel")
@rota_protegida("usuarios.alterar_papel")
def alterar_papel_rota(usuario_id):
    """Altera o papel conforme ``autorizacao.pode_alterar_papel``."""
    sessao = g.sessao
    autor = g.usuario
    alvo = _buscar_alvo(sessao, usuario_id)
    if alvo is None:
        return resposta_erro("Usuário não encontrado.", 404)

    corpo = request.get_json(silent=True) or {}
    novo_papel = corpo.get("papel")
    if novo_papel not in usuarios.PAPEIS_VALIDOS:
        return resposta_erro(
            f"Papel inválido: {novo_papel!r}. Válidos: {', '.join(usuarios.PAPEIS_VALIDOS)}.",
            400,
        )

    if not autorizacao.pode_alterar_papel(autor, alvo, novo_papel):
        _auditar_negado(
            ACAO_PAPEL_NEGADA, autor, alvo, f"motivo=nao_permitido,papel={novo_papel}", sessao
        )
        return resposta_erro("Acesso negado.", 403)

    usuarios.alterar_papel(alvo, novo_papel, session=sessao, ip=_ip())
    return resposta_ok(serializar_usuario(sessao.get(Usuario, usuario_id)))


@bp.post("/usuarios/<int:usuario_id>/plano")
@rota_protegida(planos.PERMISSAO_ADMINISTRAR_PLANOS)
def alterar_plano_rota(usuario_id):
    """Altera o plano de um usuário — exclusivamente por SUPERADMIN.

    Decisão central em ``services/planos.pode_alterar_plano`` (anti-
    escalonamento): nenhum usuário altera o próprio plano e o cliente nunca
    envia o plano em cadastro/edição. Tentativas negadas são auditadas.
    """
    sessao = g.sessao
    autor = g.usuario
    alvo = _buscar_alvo(sessao, usuario_id)
    if alvo is None:
        return resposta_erro("Usuário não encontrado.", 404)

    corpo = request.get_json(silent=True) or {}
    novo_plano = corpo.get("plano")
    if novo_plano not in planos.PLANOS_VALIDOS:
        return resposta_erro(
            f"Plano inválido: {novo_plano!r}. Válidos: {', '.join(planos.PLANOS_VALIDOS)}.",
            400,
        )

    if not planos.pode_alterar_plano(autor, novo_plano):
        _auditar_negado(
            planos.ACAO_PLANO_ALTERACAO_NEGADA,
            autor,
            alvo,
            f"motivo=nao_superadmin,plano={novo_plano}",
            sessao,
        )
        return resposta_erro("Acesso negado.", 403)

    try:
        planos.alterar_plano(
            autor, alvo, novo_plano, session=sessao, ip=_ip()
        )
    except ValueError as exc:
        return resposta_erro(str(exc), 400)

    return resposta_ok(serializar_usuario(sessao.get(Usuario, usuario_id)))


@bp.post("/usuarios/<int:usuario_id>/telegram")
@rota_protegida("telegram.administrar")
def vincular_telegram_rota(usuario_id):
    """Vincula um ``telegram_user_id`` a um usuário (``services/telegram.py``)."""
    sessao = g.sessao
    autor = g.usuario
    alvo = _buscar_alvo(sessao, usuario_id)
    if alvo is None:
        return resposta_erro("Usuário não encontrado.", 404)

    corpo = request.get_json(silent=True) or {}
    telegram_user_id = _interpretar_telegram_id(corpo.get("telegram_user_id"))
    if isinstance(telegram_user_id, tuple):
        return telegram_user_id
    if telegram_user_id is None:
        return resposta_erro("O campo 'telegram_user_id' é obrigatório.", 400)

    telegram_chat_id = _interpretar_telegram_id(corpo.get("telegram_chat_id"))
    if isinstance(telegram_chat_id, tuple):
        return telegram_chat_id

    try:
        telegram.vincular_telegram_usuario(
            autor,
            alvo,
            telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            session=sessao,
            ip=_ip(),
        )
    except autorizacao.PermissaoNegadaError:
        return resposta_erro("Acesso negado.", 403)
    except ValueError as exc:
        return resposta_erro(str(exc), 400)

    return resposta_ok(serializar_usuario(sessao.get(Usuario, usuario_id)))


@bp.delete("/usuarios/<int:usuario_id>/telegram")
@rota_protegida("telegram.administrar")
def desvincular_telegram_rota(usuario_id):
    """Remove o vínculo Telegram de um usuário (``services/telegram.py``)."""
    sessao = g.sessao
    autor = g.usuario
    alvo = _buscar_alvo(sessao, usuario_id)
    if alvo is None:
        return resposta_erro("Usuário não encontrado.", 404)

    try:
        telegram.desvincular_telegram_usuario(autor, alvo, session=sessao, ip=_ip())
    except autorizacao.PermissaoNegadaError:
        return resposta_erro("Acesso negado.", 403)

    return resposta_ok(serializar_usuario(sessao.get(Usuario, usuario_id)))


@bp.post("/usuarios/<int:usuario_id>/sessoes/revogar")
@rota_protegida("usuarios.desativar")
def revogar_sessoes_rota(usuario_id):
    """Revoga as sessões ativas de um usuário (revogação administrativa)."""
    sessao = g.sessao
    autor = g.usuario
    alvo = _buscar_alvo(sessao, usuario_id)
    if alvo is None:
        return resposta_erro("Usuário não encontrado.", 404)
    if _negado_por_protecao(autor, alvo, sessao):
        return resposta_erro("Acesso negado.", 403)

    quantidade = sessoes.revogar_sessoes_usuario(
        alvo, autor=autor, session=sessao, ip=_ip()
    )
    return resposta_ok(
        {"usuario_id": alvo.id, "sessoes_revogadas": quantidade}
    )


def _interpretar_telegram_id(valor):
    """Interpreta um ID de Telegram (int) de forma tolerante.

    Retorna o ``int``, ``None`` quando ausente, ou uma ``resposta_erro`` (tuple)
    quando o valor não pode ser interpretado como inteiro.
    """
    if valor is None:
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return resposta_erro("O Telegram ID deve ser um inteiro.", 400)
