"""Testes da Fase 6, Etapa 6 — Motor de notificações individualizadas.

Cobrem o motor central ``services/notificacoes.py`` e os endpoints
``/api/v1/notificacoes``: elegibilidade (usuário ativo, acompanhamento,
carteira, preferências, canais), catálogo de eventos, deduplicação/idempotência,
persistência, isolamento entre usuários (anti-IDOR/BOLA), autorização pela
matriz central, canais (WEB/Telegram com vínculo), sanitização de payload,
status, auditoria sem segredos e regressão (SQLite em memória).
"""
import hashlib
import json

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import dependencias, integrar_api
from pipeline_dados.banco_dados import (
    Ativo,
    AtivoAcompanhado,
    AuditoriaAcesso,
    Base,
    Notificacao,
    TipoAtivo,
    Usuario,
)
from services import (
    ativos_acompanhados,
    carteira,
    chaves_api,
    notificacoes,
    preferencias,
    usuarios,
)


@pytest.fixture()
def ambiente(monkeypatch):
    """Flask app com a API integrada e um SQLite em memória compartilhado."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _obter_sessao():
        return Session()

    monkeypatch.setattr(dependencias, "obter_sessao", _obter_sessao)

    app = Flask(__name__)
    app.config["TESTING"] = True
    integrar_api(app, habilitada=True)
    cliente = app.test_client()

    seed = _Semear(Session())
    seed.rodar()

    return {
        "cliente": cliente,
        "Session": Session,
        "usuarios": seed.usuarios,
        "chaves": seed.chaves,
        "ativos": seed.ativos,
    }


class _Semear:
    """Popula o banco de testes: usuários de vários papéis + ativos + chaves."""

    def __init__(self, sessao):
        self.sessao = sessao
        self.usuarios = {}
        self.chaves = {}
        self.ativos = {}

    def rodar(self):
        s = self.sessao
        for nome, papel, ativo in (
            ("superadmin", usuarios.SUPERADMIN, True),
            ("admin", usuarios.ADMIN, True),
            ("alice", usuarios.USER, True),
            ("bob", usuarios.USER, True),
            ("visitor", usuarios.VISITOR, True),
            ("desativado", usuarios.USER, False),
        ):
            self.usuarios[nome] = usuarios.criar_usuario(
                nome=nome,
                email=f"{nome}@x.com",
                senha="senha1234",
                papel=papel,
                ativo=ativo,
                session=s,
            )

        ativos = [
            Ativo(ticker="PETR4", cnpj="33.000.167/0001-01", tipo=TipoAtivo.ACAO),
            Ativo(ticker="GARE11", cnpj="00.000.000/0001-11", tipo=TipoAtivo.FII),
        ]
        s.add_all(ativos)
        s.commit()
        self.ativos = {registro.ticker: registro.id for registro in ativos}

        for nome, usuario in self.usuarios.items():
            if usuario.ativo:
                self.chaves[nome] = chaves_api.criar_chave_api(
                    usuario, f"chave-{nome}", session=s
                )
            else:
                chave_bruta = f"chave-{nome}-legado"
                s.add(
                    chaves_api.ChaveApi(
                        usuario_id=usuario.id,
                        rotulo=f"chave-{nome}",
                        chave_hash=hashlib.sha256(chave_bruta.encode("utf-8")).hexdigest(),
                        ativa=True,
                    )
                )
                self.chaves[nome] = chave_bruta
        s.commit()
        self.usuarios = {nome: usuario.id for nome, usuario in self.usuarios.items()}
        s.close()


def _h(ambiente, nome):
    return {"X-API-Key": ambiente["chaves"][nome]}


def _id(ambiente, nome):
    return ambiente["usuarios"][nome]


def _usuario(ambiente, nome):
    sessao = ambiente["Session"]()
    try:
        return sessao.get(Usuario, _id(ambiente, nome))
    finally:
        sessao.close()


def _evento(ambiente, tipo="PRECO_ATINGIDO", ativo="PETR4", evento_id=None, **extra):
    corpo = {
        "tipo": tipo,
        "titulo": f"{ativo or 'Sistema'} alerta",
        "mensagem": f"{ativo or 'Sistema'} enviou uma atualização.",
        "evento_id": evento_id,
    }
    if ativo:
        corpo["ativo_id"] = ambiente["ativos"][ativo]
    corpo.update(extra)
    return {chave: valor for chave, valor in corpo.items() if valor is not None}


def _seguir(ambiente, nome, ativo="PETR4"):
    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, nome))
        ativos_acompanhados.adicionar_acompanhamento(
            usuario, ambiente["ativos"][ativo], session=sessao
        )
    finally:
        sessao.close()


def _seguir_direto(ambiente, nome, ativo="PETR4"):
    sessao = ambiente["Session"]()
    try:
        sessao.add(
            AtivoAcompanhado(
                usuario_id=_id(ambiente, nome), ativo_id=ambiente["ativos"][ativo]
            )
        )
        sessao.commit()
    finally:
        sessao.close()


def _posicao(ambiente, nome, ativo="PETR4"):
    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, nome))
        carteira.adicionar_posicao(
            usuario,
            ambiente["ativos"][ativo],
            quantidade=10,
            preco_medio=20.0,
            session=sessao,
        )
    finally:
        sessao.close()


def _prefere(ambiente, nome, **campos):
    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, nome))
        preferencias.atualizar_preferencias(usuario, campos, session=sessao)
    finally:
        sessao.close()


def _processar(ambiente, evento):
    sessao = ambiente["Session"]()
    try:
        return notificacoes.processar_evento(evento, session=sessao)
    finally:
        sessao.close()


def _notificacoes(Session, usuario_id=None):
    sessao = Session()
    try:
        query = sessao.query(Notificacao)
        if usuario_id is not None:
            query = query.filter(Notificacao.usuario_id == usuario_id)
        return query.order_by(Notificacao.id).all()
    finally:
        sessao.close()


def _auditoria(Session):
    sessao = Session()
    try:
        return sessao.query(AuditoriaAcesso).order_by(AuditoriaAcesso.id).all()
    finally:
        sessao.close()


def _texto_auditoria(ambiente):
    return "\n".join(
        f"{evento.acao} {evento.alvo or ''} {evento.detalhe or ''}"
        for evento in _auditoria(ambiente["Session"])
    )


def _segredos(ambiente):
    """Segredos que nunca podem aparecer em respostas/auditoria/banco."""
    segredos = {"senha1234", "senha_hash", "token_hash", "chave_hash"}
    segredos.update(ambiente["chaves"].values())
    return segredos


# ==========================================
# MOTOR: ELEGIBILIDADE
# ==========================================


def test_usuario_ativo_recebe_evento_elegivel(ambiente):
    _seguir(ambiente, "alice")
    resumo = _processar(ambiente, _evento(ambiente))
    assert resumo["elegiveis"] == 1
    assert resumo["geradas"] == 1
    registro = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))
    assert len(registro) == 1
    assert registro[0].tipo == "PRECO_ATINGIDO"
    assert registro[0].status == "GERADA"
    assert registro[0].canal == "WEB"
    assert registro[0].ativo_id == ambiente["ativos"]["PETR4"]


def test_usuario_inativo_nao_recebe(ambiente):
    _seguir_direto(ambiente, "desativado")
    resumo = _processar(ambiente, _evento(ambiente))
    assert resumo["elegiveis"] == 0
    assert resumo["geradas"] == 0
    assert _notificacoes(ambiente["Session"]) == []


def test_usuario_sem_acompanhamento_nao_recebe(ambiente):
    resumo = _processar(ambiente, _evento(ambiente))
    assert resumo["elegiveis"] == 0
    assert resumo["geradas"] == 0


def test_usuario_com_acompanhamento_recebe(ambiente):
    _seguir(ambiente, "alice")
    _seguir(ambiente, "bob")
    resumo = _processar(ambiente, _evento(ambiente))
    assert resumo["elegiveis"] == 2
    assert resumo["geradas"] == 2
    assert len(_notificacoes(ambiente["Session"])) == 2


def test_usuarios_elegiveis_para_evento(ambiente):
    _seguir(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        elegiveis = notificacoes.usuarios_elegiveis_para_evento(
            _evento(ambiente), session=sessao
        )
        assert [usuario.id for usuario in elegiveis] == [_id(ambiente, "alice")]
    finally:
        sessao.close()


def test_visitor_nao_recebe(ambiente):
    _seguir_direto(ambiente, "visitor")
    resumo = _processar(ambiente, _evento(ambiente))
    assert resumo["elegiveis"] == 0
    assert resumo["geradas"] == 0


def test_admin_nao_recebe(ambiente):
    _seguir(ambiente, "admin")
    resumo = _processar(ambiente, _evento(ambiente))
    assert resumo["elegiveis"] == 0
    assert resumo["geradas"] == 0


def test_superadmin_recebe(ambiente):
    _seguir(ambiente, "superadmin")
    resumo = _processar(ambiente, _evento(ambiente))
    assert resumo["elegiveis"] == 1
    assert len(_notificacoes(ambiente["Session"], _id(ambiente, "superadmin"))) == 1


# ==========================================
# MOTOR: PREFERÊNCIAS
# ==========================================


def test_preferencia_desativada_impede_geracao(ambiente):
    _seguir(ambiente, "alice")
    _prefere(ambiente, "alice", notificacoes_preco=False)
    resumo = _processar(ambiente, _evento(ambiente, tipo="PRECO_ATINGIDO"))
    assert resumo["elegiveis"] == 0
    assert resumo["geradas"] == 0


def test_preferencia_ativa_permite_geracao(ambiente):
    _seguir(ambiente, "alice")
    _prefere(ambiente, "alice", notificacoes_preco=True)
    resumo = _processar(ambiente, _evento(ambiente, tipo="PRECO_ATINGIDO"))
    assert resumo["geradas"] == 1


def test_preferencia_especifica_do_tipo(ambiente):
    _seguir(ambiente, "alice")
    _prefere(ambiente, "alice", notificacoes_dividendos=False)
    assert _processar(ambiente, _evento(ambiente, tipo="DIVIDENDO"))["geradas"] == 0
    assert _processar(ambiente, _evento(ambiente, tipo="PRECO_ATINGIDO"))["geradas"] == 1


def test_mestre_notificacoes_ativas_bloqueia_tudo(ambiente):
    _seguir(ambiente, "alice")
    _prefere(ambiente, "alice", notificacoes_ativas=False)
    resumo = _processar(ambiente, _evento(ambiente, tipo="PRECO_ATINGIDO"))
    assert resumo["elegiveis"] == 0


# ==========================================
# MOTOR: CARTEIRA
# ==========================================


def test_carteira_origem_carteira_considera_posicao(ambiente):
    _posicao(ambiente, "alice")
    resumo = _processar(
        ambiente, _evento(ambiente, tipo="VARIACAO_PRECO", origem="CARTEIRA")
    )
    assert resumo["elegiveis"] == 1
    assert resumo["geradas"] == 1
    assert len(_notificacoes(ambiente["Session"], _id(ambiente, "alice"))) == 1


def test_carteira_origem_acompanhamento_nao_considera_posicao(ambiente):
    _posicao(ambiente, "alice")
    resumo = _processar(ambiente, _evento(ambiente, tipo="VARIACAO_PRECO"))
    assert resumo["elegiveis"] == 0
    assert resumo["geradas"] == 0


def test_carteira_exige_posicao(ambiente):
    _seguir(ambiente, "alice")
    resumo = _processar(
        ambiente, _evento(ambiente, tipo="VARIACAO_PRECO", origem="CARTEIRA")
    )
    assert resumo["elegiveis"] == 0


# ==========================================
# MOTOR: VALIDAÇÃO DE EVENTO E CANAIS
# ==========================================


def test_todos_os_tipos_de_evento_aceitos(ambiente):
    _seguir(ambiente, "alice")
    for tipo in sorted(notificacoes.TIPOS_EVENTO):
        resumo = _processar(ambiente, _evento(ambiente, tipo=tipo))
        assert resumo["geradas"] == 1, tipo


def test_evento_tipo_invalido(ambiente):
    with pytest.raises(ValueError):
        notificacoes.processar_evento({"tipo": "EVENTO_DESCONHECIDO"}, session=None)


def test_evento_sem_titulo(ambiente):
    with pytest.raises(ValueError):
        notificacoes.processar_evento(
            {"tipo": "PRECO_ATINGIDO", "mensagem": "x"}, session=None
        )


def test_evento_sem_mensagem(ambiente):
    with pytest.raises(ValueError):
        notificacoes.processar_evento(
            {"tipo": "PRECO_ATINGIDO", "titulo": "x"}, session=None
        )


def test_evento_campo_desconhecido(ambiente):
    with pytest.raises(ValueError):
        notificacoes.processar_evento(
            _evento(ambiente, extra={"modo_escuro": True}), session=None
        )


def test_evento_canal_invalido(ambiente):
    with pytest.raises(ValueError):
        notificacoes.processar_evento(
            _evento(ambiente, canais=["EMAIL"]), session=None
        )


def test_evento_ativo_id_invalido(ambiente):
    with pytest.raises(ValueError):
        notificacoes.processar_evento(
            _evento(ambiente, ativo_id=0), session=None
        )


# ==========================================
# MOTOR: DEDUPLICAÇÃO E IDEMPOTÊNCIA
# ==========================================


def test_deduplicacao_mesmo_evento(ambiente):
    _seguir(ambiente, "alice")
    evento = _evento(ambiente, evento_id="evt-1")
    _processar(ambiente, evento)
    resumo = _processar(ambiente, evento)
    assert resumo["geradas"] == 0
    assert resumo["ignoradas"] == 1
    assert len(_notificacoes(ambiente["Session"], _id(ambiente, "alice"))) == 1


def test_processamento_repetido_nao_duplica(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-2", titulo="primeira"))
    _processar(ambiente, _evento(ambiente, evento_id="evt-2", titulo="segunda"))
    registros = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))
    assert len(registros) == 1
    assert registros[0].titulo == "primeira"


def test_evento_sem_evento_id_gera_multiplas_legitimas(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    _processar(ambiente, _evento(ambiente))
    assert len(_notificacoes(ambiente["Session"], _id(ambiente, "alice"))) == 2


def test_eventos_distintos_geram_notificacoes_distintas(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-a"))
    _processar(ambiente, _evento(ambiente, evento_id="evt-b"))
    assert len(_notificacoes(ambiente["Session"], _id(ambiente, "alice"))) == 2


# ==========================================
# MOTOR: CANAIS
# ==========================================


def test_telegram_sem_vinculo_nao_gera_canal_telegram(ambiente):
    _seguir(ambiente, "alice")
    resumo = _processar(ambiente, _evento(ambiente))
    assert resumo["geradas"] == 1
    assert _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0].canal == "WEB"


def test_telegram_com_vinculo_gera_ambos_canais(ambiente):
    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, "alice"))
        usuarios.vincular_telegram(usuario, 12345, telegram_chat_id=54321, session=sessao)
    finally:
        sessao.close()
    _seguir(ambiente, "alice")
    resumo = _processar(ambiente, _evento(ambiente))
    assert resumo["geradas"] == 2
    canais = {reg.canal for reg in _notificacoes(ambiente["Session"], _id(ambiente, "alice"))}
    assert canais == {"WEB", "TELEGRAM"}


def test_telegram_ativo_com_vinculo_mais_web_desativado(ambiente):
    sessao = ambiente["Session"]()
    try:
        usuario = sessao.get(Usuario, _id(ambiente, "alice"))
        usuarios.vincular_telegram(usuario, 12345, telegram_chat_id=54321, session=sessao)
    finally:
        sessao.close()
    _seguir(ambiente, "alice")
    _prefere(ambiente, "alice", web_ativo=False)
    resumo = _processar(ambiente, _evento(ambiente))
    assert resumo["geradas"] == 1
    assert _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0].canal == "TELEGRAM"


# ==========================================
# MOTOR: PERSISTÊNCIA, SANITIZAÇÃO E AUDITORIA
# ==========================================


def test_persistencia(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-persist"))
    registros = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))
    assert len(registros) == 1
    assert registros[0].titulo == "PETR4 alerta"
    assert registros[0].mensagem == "PETR4 enviou uma atualização."


def test_dados_sanitizados(ambiente):
    _seguir(ambiente, "alice")
    _processar(
        ambiente,
        _evento(
            ambiente,
            dados={"preco": "20.00", "token": "abc-secreto", "api_key": "xyz-secreto"},
        ),
    )
    registro = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0]
    armazenado = json.loads(registro.dados)
    assert armazenado["preco"] == "20.00"
    assert armazenado["token"] == "[OCULTO]"
    assert armazenado["api_key"] == "[OCULTO]"
    assert "abc-secreto" not in registro.dados
    assert "xyz-secreto" not in registro.dados


def test_auditoria_sem_segredos(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    texto = _texto_auditoria(ambiente)
    assert "NOTIFICACAO_GERADA" in texto
    for segredo in _segredos(ambiente):
        assert segredo not in texto


# ==========================================
# MOTOR: CONSULTA, ESTADO E ISOLAMENTO
# ==========================================


def test_listar_notificacoes_proprias(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        registros = notificacoes.listar_notificacoes(alice, session=sessao)
        assert len(registros) == 1
    finally:
        sessao.close()


def test_listar_notificacoes_filtro_tipo(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, tipo="DIVIDENDO"))
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        assert len(notificacoes.listar_notificacoes(alice, tipo="DIVIDENDO", session=sessao)) == 1
        assert len(notificacoes.listar_notificacoes(alice, tipo="PRECO_ATINGIDO", session=sessao)) == 0
    finally:
        sessao.close()


def test_listar_notificacoes_filtro_invalido(ambiente):
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        with pytest.raises(ValueError):
            notificacoes.listar_notificacoes(alice, tipo="TIPO_INVALIDO", session=sessao)
    finally:
        sessao.close()


def test_buscar_notificacao_isolamento(ambiente):
    _seguir(ambiente, "alice")
    _seguir(ambiente, "bob")
    _processar(ambiente, _evento(ambiente, evento_id="evt-iso"))
    alice = _usuario(ambiente, "alice")
    bob = _usuario(ambiente, "bob")
    id_alice = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0].id
    sessao = ambiente["Session"]()
    try:
        assert notificacoes.buscar_notificacao(alice, id_alice, session=sessao) is not None
        assert notificacoes.buscar_notificacao(bob, id_alice, session=sessao) is None
    finally:
        sessao.close()


def test_marcar_como_lida(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    alice = _usuario(ambiente, "alice")
    registro = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0]
    sessao = ambiente["Session"]()
    try:
        atualizado = notificacoes.marcar_como_lida(alice, registro.id, session=sessao)
        assert atualizado.status == "LIDA"
        assert atualizado.lida_em is not None
    finally:
        sessao.close()
    assert "NOTIFICACAO_MARCADA_LIDA" in _texto_auditoria(ambiente)


def test_marcar_como_lida_idempotente(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    alice = _usuario(ambiente, "alice")
    registro = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0]
    sessao = ambiente["Session"]()
    try:
        notificacoes.marcar_como_lida(alice, registro.id, session=sessao)
    finally:
        sessao.close()
    texto_antes = _texto_auditoria(ambiente)
    sessao = ambiente["Session"]()
    try:
        notificacoes.marcar_como_lida(alice, registro.id, session=sessao)
    finally:
        sessao.close()
    assert _texto_auditoria(ambiente) == texto_antes


def test_marcar_como_lida_de_outro_usuario(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    bob = _usuario(ambiente, "bob")
    registro = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0]
    sessao = ambiente["Session"]()
    try:
        assert notificacoes.marcar_como_lida(bob, registro.id, session=sessao) is None
    finally:
        sessao.close()


def test_marcar_todas_como_lida(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-t1"))
    _processar(ambiente, _evento(ambiente, evento_id="evt-t2"))
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        total = notificacoes.marcar_todas_como_lida(alice, session=sessao)
        assert total == 2
    finally:
        sessao.close()
    registros = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))
    assert all(registro.status == "LIDA" for registro in registros)
    assert all(registro.lida_em is not None for registro in registros)
    assert "NOTIFICACOES_MARCADAS_LIDAS" in _texto_auditoria(ambiente)


def test_marcar_todas_como_lida_idempotente(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-t3"))
    alice = _usuario(ambiente, "alice")
    sessao = ambiente["Session"]()
    try:
        notificacoes.marcar_todas_como_lida(alice, session=sessao)
    finally:
        sessao.close()
    texto_antes = _texto_auditoria(ambiente)
    sessao = ambiente["Session"]()
    try:
        assert notificacoes.marcar_todas_como_lida(alice, session=sessao) == 0
    finally:
        sessao.close()
    assert _texto_auditoria(ambiente) == texto_antes


def test_marcar_todas_nao_toca_notificacoes_de_outro(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-iso2"))
    bob = _usuario(ambiente, "bob")
    sessao = ambiente["Session"]()
    try:
        assert notificacoes.marcar_todas_como_lida(bob, session=sessao) == 0
    finally:
        sessao.close()
    assert _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0].status == "GERADA"


def test_excluir_notificacao(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    alice = _usuario(ambiente, "alice")
    registro = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0]
    sessao = ambiente["Session"]()
    try:
        assert notificacoes.excluir_notificacao(alice, registro.id, session=sessao) is True
    finally:
        sessao.close()
    assert _notificacoes(ambiente["Session"]) == []
    assert "NOTIFICACAO_EXCLUIDA" in _texto_auditoria(ambiente)


def test_excluir_notificacao_de_outro_usuario(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    bob = _usuario(ambiente, "bob")
    registro = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0]
    sessao = ambiente["Session"]()
    try:
        assert notificacoes.excluir_notificacao(bob, registro.id, session=sessao) is False
    finally:
        sessao.close()
    assert len(_notificacoes(ambiente["Session"])) == 1


# ==========================================
# API
# ==========================================


def test_api_sem_credencial_401(ambiente):
    assert ambiente["cliente"].get("/api/v1/notificacoes").status_code == 401


def test_api_visitor_403(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/notificacoes", headers=_h(ambiente, "visitor")
    )
    assert resposta.status_code == 403


def test_api_admin_403(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/notificacoes", headers=_h(ambiente, "admin")
    )
    assert resposta.status_code == 403


def test_api_desativado_401(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/notificacoes", headers=_h(ambiente, "desativado")
    )
    assert resposta.status_code == 401


def test_api_listar_notificacoes(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-api"))
    resposta = ambiente["cliente"].get(
        "/api/v1/notificacoes", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["meta"]["total"] == 1
    item = dados["data"][0]
    assert item["tipo"] == "PRECO_ATINGIDO"
    assert item["status"] == "GERADA"
    assert item["canal"] == "WEB"
    assert item["ticker"] == "PETR4"
    assert "usuario_id" not in item


def test_api_filtro_tipo(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, tipo="DIVIDENDO", evento_id="evt-div"))
    resposta = ambiente["cliente"].get(
        "/api/v1/notificacoes?tipo=PRECO_ATINGIDO", headers=_h(ambiente, "alice")
    )
    assert resposta.get_json()["meta"]["total"] == 0
    resposta = ambiente["cliente"].get(
        "/api/v1/notificacoes?tipo=DIVIDENDO", headers=_h(ambiente, "alice")
    )
    assert resposta.get_json()["meta"]["total"] == 1


def test_api_filtro_tipo_invalido_400(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/notificacoes?tipo=TIPO_INVALIDO", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 400


def test_api_consultar_isolamento_404(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    registro = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0]
    resposta = ambiente["cliente"].get(
        f"/api/v1/notificacoes/{registro.id}", headers=_h(ambiente, "bob")
    )
    assert resposta.status_code == 404


def test_api_consultar_inexistente_404(ambiente):
    resposta = ambiente["cliente"].get(
        "/api/v1/notificacoes/999999", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 404


def test_api_marcar_lida(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    registro = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0]
    resposta = ambiente["cliente"].post(
        f"/api/v1/notificacoes/{registro.id}/lida", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["status"] == "LIDA"
    assert resposta.get_json()["data"]["lida_em"] is not None


def test_api_marcar_lida_de_outro_usuario_404(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    registro = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0]
    resposta = ambiente["cliente"].post(
        f"/api/v1/notificacoes/{registro.id}/lida", headers=_h(ambiente, "bob")
    )
    assert resposta.status_code == 404


def test_api_marcar_todas_lidas(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-at1"))
    _processar(ambiente, _evento(ambiente, evento_id="evt-at2"))
    resposta = ambiente["cliente"].post(
        "/api/v1/notificacoes/ler-todas", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["meta"]["total"] == 2
    registros = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))
    assert all(registro.status == "LIDA" for registro in registros)


def test_api_marcar_todas_nao_toca_notificacoes_de_outro(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente, evento_id="evt-at3"))
    resposta = ambiente["cliente"].post(
        "/api/v1/notificacoes/ler-todas", headers=_h(ambiente, "bob")
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["meta"]["total"] == 0
    assert _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0].status == "GERADA"


def test_api_marcar_todas_sem_credencial_401(ambiente):
    assert (
        ambiente["cliente"].post("/api/v1/notificacoes/ler-todas").status_code == 401
    )


def test_api_excluir(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    registro = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0]
    resposta = ambiente["cliente"].delete(
        f"/api/v1/notificacoes/{registro.id}", headers=_h(ambiente, "alice")
    )
    assert resposta.status_code == 200
    assert _notificacoes(ambiente["Session"]) == []


def test_api_excluir_de_outro_usuario_404(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    registro = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0]
    resposta = ambiente["cliente"].delete(
        f"/api/v1/notificacoes/{registro.id}", headers=_h(ambiente, "bob")
    )
    assert resposta.status_code == 404


def test_api_superadmin_le_notificacao_de_outro(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    registro = _notificacoes(ambiente["Session"], _id(ambiente, "alice"))[0]
    resposta = ambiente["cliente"].get(
        f"/api/v1/notificacoes/{registro.id}", headers=_h(ambiente, "superadmin")
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["data"]["tipo"] == "PRECO_ATINGIDO"


def test_api_nao_expoe_segredos(ambiente):
    _seguir(ambiente, "alice")
    _processar(ambiente, _evento(ambiente))
    corpo = ambiente["cliente"].get(
        "/api/v1/notificacoes", headers=_h(ambiente, "alice")
    ).get_data(as_text=True)
    for segredo in _segredos(ambiente):
        assert segredo not in corpo
    for proibido in ("usuario_id", "senha_hash", "token_hash", "chave_hash"):
        assert proibido not in corpo
