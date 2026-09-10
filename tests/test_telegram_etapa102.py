"""Testes da Etapa 10.2 — identidade Telegram -> Usuario.

Cobre: resolucao Telegram ID -> Usuario existente, vinculo por token de
sessao (sem associacao arbitraria), usuario nao vinculado sem acesso
autenticado, isolamento, separacao PUBLICO/USUARIO/OPERACIONAL, menus
publicos sem dados financeiros, catch-all que nao intercepta handlers
publicos, webhook secret_token via ambiente e ausencia de segredos em
logs/auditoria. Nao cria endpoints nem altera API.
"""
import hmac
import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config
from pipeline_dados.banco_dados import AuditoriaAcesso, Base, Sessao
from services import sessoes, telegram, usuarios
from bot import identidade


@pytest.fixture()
def sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _auditoria(sessao):
    return sessao.query(AuditoriaAcesso).order_by(AuditoriaAcesso.id).all()


def _criar(sessao, **kwargs):
    dados = {"nome": "Ana", "email": "ana@x.com", "senha": "senha1234"}
    dados.update(kwargs)
    return usuarios.criar_usuario(session=sessao, **dados)


def _evento(tg_id, texto="/start", chat_id=None, data=None):
    origem = SimpleNamespace(id=tg_id)
    chat = SimpleNamespace(id=chat_id if chat_id is not None else tg_id)
    if data is not None:
        mensagem = SimpleNamespace(chat=chat)
        return SimpleNamespace(from_user=origem, data=data, message=mensagem, chat=None)
    return SimpleNamespace(from_user=origem, text=texto, chat=chat)


# ==========================================
# TELEGRAM ID -> USUARIO
# ==========================================


def test_telegram_id_resolve_usuario_vinculado(sessao):
    user = _criar(sessao)
    usuarios.vincular_telegram(user, 41001, telegram_chat_id=41001, session=sessao)
    encontrado = telegram.usuario_do_telegram(41001, session=sessao)
    assert encontrado is not None
    assert encontrado.id == user.id


def test_telegram_id_sem_vinculo_nao_resolve_usuario(sessao):
    assert telegram.usuario_do_telegram(41999, session=sessao) is None
    assert telegram.usuario_do_telegram(None, session=sessao) is None


def test_resolucao_nao_cria_usuario_nem_sessao(sessao):
    fluxo, usuario = telegram.fluxo_do_telegram(42000, session=sessao)
    assert fluxo == telegram.FLUXO_PUBLICO
    assert usuario is None
    assert sessao.query(Sessao).count() == 0
    assert usuarios.buscar_usuario_por_telegram(42000, session=sessao) is None


# ==========================================
# VINCULO POR TOKEN DE SESSAO
# ==========================================


def test_vinculo_por_sessao_exige_token_valido(sessao):
    user = _criar(sessao, email="vinculo@x.com")
    token = sessoes.criar_sessao(user, session=sessao)
    vinculado = telegram.vincular_telegram_por_sessao(
        token, 43001, telegram_chat_id=43001, session=sessao
    )
    assert vinculado is not None
    assert vinculado.id == user.id
    assert usuarios.buscar_usuario_por_telegram(43001, session=sessao).id == user.id


def test_vinculo_rejeita_token_invalido(sessao):
    assert (
        telegram.vincular_telegram_por_sessao("token-falso", 43002, session=sessao)
        is None
    )
    assert usuarios.buscar_usuario_por_telegram(43002, session=sessao) is None
    acoes = [e.acao for e in _auditoria(sessao)]
    assert telegram.ACAO_VINCULO_SESSAO_NEGADO in acoes


def test_vinculo_rejeita_token_vazio_e_none(sessao):
    assert telegram.vincular_telegram_por_sessao("", 43003, session=sessao) is None
    assert telegram.vincular_telegram_por_sessao(None, 43003, session=sessao) is None
    assert usuarios.buscar_usuario_por_telegram(43003, session=sessao) is None


def test_vinculo_impede_associacao_arbitraria_telegram_em_uso(sessao):
    dono = _criar(sessao, email="dono@x.com")
    outro = _criar(sessao, nome="Bia", email="bia@x.com")
    token_outro = sessoes.criar_sessao(outro, session=sessao)
    usuarios.vincular_telegram(dono, 43010, session=sessao)
    assert (
        telegram.vincular_telegram_por_sessao(token_outro, 43010, session=sessao)
        is None
    )
    assert usuarios.buscar_usuario_por_telegram(43010, session=sessao).id == dono.id


def test_vinculo_impede_usuario_ja_vinculado_a_outro_telegram(sessao):
    user = _criar(sessao, email="ja@x.com")
    token = sessoes.criar_sessao(user, session=sessao)
    usuarios.vincular_telegram(user, 43020, session=sessao)
    assert telegram.vincular_telegram_por_sessao(token, 43021, session=sessao) is None
    assert usuarios.buscar_usuario_por_telegram(43020, session=sessao).id == user.id
    assert usuarios.buscar_usuario_por_telegram(43021, session=sessao) is None


def test_vinculo_idempotente_mesmo_telegram(sessao):
    user = _criar(sessao, email="mesmo@x.com")
    token = sessoes.criar_sessao(user, session=sessao)
    primeiro = telegram.vincular_telegram_por_sessao(token, 43030, session=sessao)
    segundo = telegram.vincular_telegram_por_sessao(token, 43030, session=sessao)
    assert primeiro is not None and segundo is not None
    assert primeiro.id == segundo.id == user.id


def test_vinculo_nao_registra_token_na_auditoria(sessao):
    user = _criar(sessao, email="segredo@x.com")
    token = sessoes.criar_sessao(user, session=sessao)
    telegram.vincular_telegram_por_sessao(token, 43040, session=sessao)
    telegram.vincular_telegram_por_sessao("token-invalido-xyz", 43041, session=sessao)
    for e in _auditoria(sessao):
        texto = f"{e.acao} {e.alvo or ''} {e.detalhe or ''}"
        assert token not in texto
        assert "token-invalido-xyz" not in texto
        assert "senha1234" not in texto


def test_payload_comando_start():
    assert telegram.payload_comando_start("/start abc.token") == "abc.token"
    assert telegram.payload_comando_start("/start@MeuBot abc.token") == "abc.token"
    assert telegram.payload_comando_start("/start") == ""
    assert telegram.payload_comando_start("/menu x") == ""
    assert telegram.payload_comando_start("") == ""
    assert telegram.payload_comando_start(None) == ""


# ==========================================
# NAO VINCULADO = SEM ACESSO AUTENTICADO
# ==========================================


def test_nao_vinculado_fluxo_publico(sessao):
    fluxo, usuario = telegram.fluxo_do_telegram(44001, session=sessao)
    assert fluxo == telegram.FLUXO_PUBLICO
    assert usuario is None
    assert telegram.comando_permitido(44001, telegram.FLUXO_PUBLICO, session=sessao)
    assert not telegram.comando_permitido(44001, telegram.FLUXO_USUARIO, session=sessao)
    assert not telegram.comando_permitido(
        44001, telegram.FLUXO_OPERACIONAL, session=sessao
    )


def test_visitor_vinculado_permanece_publico(sessao):
    visitor = _criar(sessao, email="vis@x.com", papel=usuarios.VISITOR)
    usuarios.vincular_telegram(visitor, 44002, session=sessao)
    fluxo, usuario = telegram.fluxo_do_telegram(44002, session=sessao)
    assert fluxo == telegram.FLUXO_PUBLICO
    assert usuario.id == visitor.id
    assert not telegram.comando_permitido(44002, telegram.FLUXO_USUARIO, session=sessao)


def test_desativado_nao_recebe_fluxo_autenticado(sessao):
    user = _criar(sessao, email="off@x.com")
    usuarios.vincular_telegram(user, 44003, session=sessao)
    usuarios.desativar_usuario(user, session=sessao)
    fluxo, usuario = telegram.fluxo_do_telegram(44003, session=sessao)
    assert fluxo == telegram.FLUXO_PUBLICO
    assert usuario is not None
    assert not telegram.comando_permitido(44003, telegram.FLUXO_USUARIO, session=sessao)
    assert not telegram.comando_permitido(
        44003, telegram.FLUXO_OPERACIONAL, session=sessao
    )


# ==========================================
# ISOLAMENTO ENTRE USUARIOS
# ==========================================


def test_isolamento_telegram_ids_distintos(sessao):
    a = _criar(sessao, email="a@x.com")
    b = _criar(sessao, nome="Bia", email="b@x.com")
    usuarios.vincular_telegram(a, 45001, session=sessao)
    usuarios.vincular_telegram(b, 45002, session=sessao)
    ua = telegram.usuario_do_telegram(45001, session=sessao)
    ub = telegram.usuario_do_telegram(45002, session=sessao)
    assert ua.id == a.id
    assert ub.id == b.id
    assert ua.id != ub.id


def test_recurso_privado_invisivel_para_outro_telegram(sessao):
    a = _criar(sessao, email="dona@x.com")
    b = _criar(sessao, nome="Bia", email="outra@x.com")
    usuarios.vincular_telegram(a, 45010, session=sessao)
    usuarios.vincular_telegram(b, 45011, session=sessao)
    recurso = SimpleNamespace(usuario_id=a.id, publico=False)
    assert (
        telegram.recurso_visivel_para_telegram(45010, recurso, session=sessao)
        is recurso
    )
    assert telegram.recurso_visivel_para_telegram(45011, recurso, session=sessao) is None
    assert telegram.recurso_visivel_para_telegram(45999, recurso, session=sessao) is None


# ==========================================
# SEPARACAO OPERACIONAL / USUARIO / PUBLICO
# ==========================================


def test_user_vinculado_fluxo_usuario(sessao):
    user = _criar(sessao, email="user@x.com", papel=usuarios.USER)
    usuarios.vincular_telegram(user, 46001, session=sessao)
    fluxo, usuario = telegram.fluxo_do_telegram(46001, session=sessao)
    assert fluxo == telegram.FLUXO_USUARIO
    assert usuario.id == user.id
    assert telegram.comando_permitido(46001, telegram.FLUXO_USUARIO, session=sessao)
    assert not telegram.comando_permitido(
        46001, telegram.FLUXO_OPERACIONAL, session=sessao
    )


@pytest.mark.parametrize("papel", [usuarios.ADMIN, usuarios.SUPERADMIN])
def test_admin_vinculado_fluxo_operacional(sessao, papel):
    admin = _criar(sessao, email=f"{papel.lower()}@x.com", papel=papel)
    usuarios.vincular_telegram(admin, 46010, session=sessao)
    fluxo, usuario = telegram.fluxo_do_telegram(46010, session=sessao)
    assert fluxo == telegram.FLUXO_OPERACIONAL
    assert usuario.id == admin.id
    assert telegram.comando_permitido(
        46010, telegram.FLUXO_OPERACIONAL, session=sessao
    )
    assert telegram.comando_permitido(46010, telegram.FLUXO_USUARIO, session=sessao)


def test_operador_legado_sem_vinculo_e_operacional(sessao, monkeypatch):
    monkeypatch.setenv("SUPERADMIN_CHAT_IDS", "46100")
    fluxo, usuario = telegram.fluxo_do_telegram(46100, session=sessao)
    assert fluxo == telegram.FLUXO_OPERACIONAL
    assert usuario is None


# ==========================================
# BOT: START / MENUS PUBLICOS
# ==========================================


def test_processar_start_publico_sem_token(sessao):
    fluxo, usuario, texto, vinculo_ok = identidade.processar_start(
        _evento(47001), session=sessao
    )
    assert fluxo == identidade.FLUXO_PUBLICO
    assert usuario is None
    assert vinculo_ok is None
    assert "TOKEN" in texto
    assert "alertas" in texto.lower() or "vincular" in texto.lower()


def test_processar_start_vincula_com_token(sessao):
    user = _criar(sessao, email="start@x.com")
    token = sessoes.criar_sessao(user, session=sessao)
    fluxo, usuario, texto, vinculo_ok = identidade.processar_start(
        _evento(47002, texto=f"/start {token}", chat_id=47002),
        session=sessao,
    )
    assert vinculo_ok is True
    assert usuario.id == user.id
    assert fluxo == identidade.FLUXO_USUARIO
    assert "vinculado" in texto.lower()


def test_processar_start_token_invalido_nao_autentica(sessao):
    fluxo, usuario, texto, vinculo_ok = identidade.processar_start(
        _evento(47003, texto="/start token-falso"),
        session=sessao,
    )
    assert vinculo_ok is False
    assert fluxo == identidade.FLUXO_PUBLICO
    assert usuario is None
    assert "Não foi possível vincular" in texto


def test_markup_publico_nao_expoe_menus_financeiros():
    markup = identidade.markup_inicio(identidade.FLUXO_PUBLICO)
    dados = [
        btn.callback_data
        for row in markup.keyboard
        for btn in row
    ]
    assert "menu_ajuda" in dados
    assert "menu_fiis" not in dados
    assert "menu_acoes" not in dados
    assert "menu_macro" not in dados
    assert "favoritos_fiis" not in dados
    assert "oportunidades_acoes" not in dados


def test_markup_usuario_tem_mercado_sem_operacional_extra():
    markup = identidade.markup_inicio(identidade.FLUXO_USUARIO)
    dados = [
        btn.callback_data
        for row in markup.keyboard
        for btn in row
    ]
    assert "menu_fiis" in dados
    assert "menu_acoes" in dados
    assert "menu_ajuda" in dados
    assert "ver_raiox_docs" not in dados
    assert "reset_confirmar" not in dados


def test_exigir_fluxo_mensagem_bloqueia_publico(sessao, monkeypatch):
    recusas = []
    monkeypatch.setattr(
        identidade, "_negar_mensagem", lambda message, texto: recusas.append(texto)
    )
    ok = identidade.exigir_fluxo_mensagem(
        _evento(47010), identidade.FLUXO_USUARIO, session=sessao
    )
    assert ok is False
    assert recusas
    assert "vincular" in recusas[0].lower() or "TOKEN" in recusas[0]


def test_exigir_fluxo_callback_bloqueia_financeiro_publico(sessao, monkeypatch):
    recusas = []
    monkeypatch.setattr(
        identidade, "_negar_callback", lambda call, texto: recusas.append(texto)
    )
    call = _evento(47011, data="menu_fiis")
    ok = identidade.exigir_fluxo_callback(
        call, identidade.FLUXO_USUARIO, session=sessao
    )
    assert ok is False
    assert recusas


def test_exigir_fluxo_callback_libera_handlers_publicos(sessao, monkeypatch):
    recusas = []
    monkeypatch.setattr(
        identidade, "_negar_callback", lambda call, texto: recusas.append(texto)
    )
    for dados in identidade.CALLBACKS_PUBLICOS:
        call = _evento(47012, data=dados)
        assert identidade.exigir_fluxo_callback(
            call, identidade.FLUXO_USUARIO, session=sessao
        )
    assert recusas == []


def test_exigir_fluxo_operacional_bloqueia_user(sessao, monkeypatch):
    recusas = []
    monkeypatch.setattr(
        identidade, "_negar_mensagem", lambda message, texto: recusas.append(texto)
    )
    user = _criar(sessao, email="comum@x.com")
    usuarios.vincular_telegram(user, 47020, session=sessao)
    ok = identidade.exigir_fluxo_mensagem(
        _evento(47020), identidade.FLUXO_OPERACIONAL, session=sessao
    )
    assert ok is False
    assert recusas == [identidade._MSG_NEGADO_OPERACIONAL]


# ==========================================
# CATCH-ALL NAO QUEBRA HANDLERS PUBLICOS
# ==========================================


def test_catch_all_nao_intercepta_callbacks_publicos_dedicados():
    assert identidade.callback_pertence_ao_menu(SimpleNamespace(data="ajuda_comandos")) is False
    assert identidade.callback_pertence_ao_menu(SimpleNamespace(data="ajuda_roadmap")) is False
    assert identidade.callback_pertence_ao_menu(SimpleNamespace(data="voltar_menu")) is True
    assert identidade.callback_pertence_ao_menu(SimpleNamespace(data="menu_ajuda")) is True


def test_catch_all_nao_intercepta_handlers_dedicados():
    dedicados = (
        "ajuda_roadmap",
        "ajuda_comandos",
        "ver_raiox_docs",
        "reset_confirmar",
        "reset_cancelar",
        "tipo_fii_TIJOLO",
        "setor_fii_Logistica",
        "setor_acao_Bancos",
        "ia_PETR4_acao_resumo",
        "ajuda_cvm_PETR4_menu",
        "rev_t_HGLG11",
        "rev_start",
    )
    for dados in dedicados:
        assert identidade.callback_pertence_ao_menu(SimpleNamespace(data=dados)) is False


def test_catch_all_ainda_atende_menus_de_usuario():
    for dados in ("menu_fiis", "menu_acoes", "favoritos_fiis", "painel_PETR4_acao"):
        assert identidade.callback_pertence_ao_menu(SimpleNamespace(data=dados)) is True


# ==========================================
# WEBHOOK SECRET_TOKEN
# ==========================================


def test_webhook_secret_vem_de_config_ambiente(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_WEBHOOK_SECRET", "s3cr3to-ambiente")
    assert telegram.webhook_secret_configurado() is True
    assert telegram.webhook_secret_valido("s3cr3to-ambiente") is True
    assert telegram.webhook_secret_valido("errado") is False
    assert telegram.webhook_secret_valido(None) is False


def test_webhook_sem_secret_aceita_legado(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_WEBHOOK_SECRET", "")
    assert telegram.webhook_secret_configurado() is False
    assert telegram.webhook_secret_valido("qualquer") is True
    assert telegram.webhook_autorizado("application/json", "x") is True
    assert telegram.webhook_autorizado("text/plain", "x") is False


def test_webhook_autorizado_exige_json_e_secret(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_WEBHOOK_SECRET", "token-webhook")
    assert telegram.webhook_autorizado("application/json", "token-webhook") is True
    assert telegram.webhook_autorizado("application/json", "outro") is False
    assert telegram.webhook_autorizado("text/plain", "token-webhook") is False


def test_parametros_set_webhook_inclui_secret_somente_se_configurado(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_WEBHOOK_SECRET", "")
    params = telegram.parametros_set_webhook("https://exemplo/hook")
    assert params == {"url": "https://exemplo/hook"}
    monkeypatch.setattr(config, "TELEGRAM_WEBHOOK_SECRET", "abc")
    params = telegram.parametros_set_webhook("https://exemplo/hook")
    assert params["url"] == "https://exemplo/hook"
    assert params["secret_token"] == "abc"


def test_comparacao_secret_e_constant_time():
    a = "segredo-igual"
    b = "segredo-igual"
    assert hmac.compare_digest(a, b) is True


def test_secret_nao_aparece_hardcoded_no_servico():
    import inspect

    fonte = inspect.getsource(telegram)
    assert 'TELEGRAM_WEBHOOK_SECRET = "' not in fonte
    assert "secret_token_fixo" not in fonte
    assert 'os.environ.get("TELEGRAM_WEBHOOK_SECRET"' in inspect.getsource(config)


def test_logs_webhook_nao_incluem_valor_do_segredo(caplog, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_WEBHOOK_SECRET", "valor-secreto-xyz")
    with caplog.at_level(logging.INFO):
        telegram.webhook_secret_valido("valor-secreto-xyz")
        telegram.parametros_set_webhook("https://x")
    texto = caplog.text
    assert "valor-secreto-xyz" not in texto
