"""Testes da Fase 6, Etapa 3 — Fundação de isolamento e escopo por usuário.

Cobrem a camada central ``services/escopo.py``: determinação de propriedade,
política de escopo (público / próprio / administrativo / SUPERADMIN wildcard),
ausência de acesso cruzado entre usuários, proteção contra IDOR/BOLA,
indistinção entre recurso inexistente e inacessível, comportamento de
usuários desativados/None e a não-exposição de segredos em exceções/auditoria.
"""
import pytest
from sqlalchemy import Boolean, Integer, String, create_engine
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from pipeline_dados.banco_dados import AuditoriaAcesso, Base
from services import auditoria, autorizacao, escopo, usuarios

BaseTeste = declarative_base()


class RecursoTeste(BaseTeste):
    """Modelo mínimo de um recurso com dono, seguindo o contrato da camada.

    ``usuario_id`` é o dono (``None`` = público); ``publico=True`` força o
    recurso como público. Existe APENAS para os testes da Etapa 3.
    """

    __tablename__ = "recursos_teste_etapa3"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publico: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    nome: Mapped[str] = mapped_column(String(100), nullable=False)


@pytest.fixture()
def ambiente():
    """SQLite em memória com usuários reais + recursos de teste (com dono)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    BaseTeste.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sessao = Session()

    usuarios_db = {}
    senha = "senha1234"

    def _usuario(nome, email, papel, ativo=True):
        return usuarios.criar_usuario(
            nome=nome,
            email=email,
            senha=senha,
            papel=papel,
            ativo=ativo,
            session=sessao,
        )

    usuarios_db["superadmin"] = _usuario("Root", "root@x.com", usuarios.SUPERADMIN)
    usuarios_db["admin"] = _usuario("Admin", "admin@x.com", usuarios.ADMIN)
    usuarios_db["a"] = _usuario("User A", "a@x.com", usuarios.USER)
    usuarios_db["b"] = _usuario("User B", "b@x.com", usuarios.USER)
    usuarios_db["visitor"] = _usuario("Visitante", "visitor@x.com", usuarios.VISITOR)
    usuarios_db["desativado"] = _usuario("Off", "off@x.com", usuarios.USER, ativo=False)

    recursos_db = {
        "a": RecursoTeste(usuario_id=usuarios_db["a"].id, publico=False, nome="Recurso A"),
        "b": RecursoTeste(usuario_id=usuarios_db["b"].id, publico=False, nome="Recurso B"),
        "publico": RecursoTeste(
            usuario_id=usuarios_db["a"].id, publico=True, nome="Recurso Público"
        ),
        "sem_dono": RecursoTeste(usuario_id=None, publico=False, nome="Recurso Plataforma"),
    }
    sessao.add_all(recursos_db.values())
    sessao.commit()

    ids = {
        "usuarios": {nome: u.id for nome, u in usuarios_db.items()},
        "recursos": {nome: r.id for nome, r in recursos_db.items()},
    }
    sessao.close()
    return {"Session": Session, **ids}


def _usuario(ambiente, nome):
    sessao = ambiente["Session"]()
    try:
        return sessao.get(usuarios.Usuario, ambiente["usuarios"][nome])
    finally:
        sessao.close()


def _recurso(ambiente, nome):
    sessao = ambiente["Session"]()
    try:
        return sessao.get(RecursoTeste, ambiente["recursos"][nome])
    finally:
        sessao.close()


# ==========================================
# PROPRIEDADE E PUBLICIDADE
# ==========================================


def test_recurso_eh_publico(ambiente):
    assert escopo.recurso_eh_publico(_recurso(ambiente, "publico")) is True
    assert escopo.recurso_eh_publico(_recurso(ambiente, "sem_dono")) is True
    assert escopo.recurso_eh_publico(_recurso(ambiente, "a")) is False
    assert escopo.recurso_eh_publico(_recurso(ambiente, "b")) is False


def test_recurso_pertence_ao_dono(ambiente):
    a = _usuario(ambiente, "a")
    b = _usuario(ambiente, "b")
    assert escopo.recurso_pertence_a(_recurso(ambiente, "a"), a) is True
    assert escopo.recurso_pertence_a(_recurso(ambiente, "b"), b) is True
    assert escopo.recurso_pertence_a(_recurso(ambiente, "b"), a) is False
    assert escopo.recurso_pertence_a(_recurso(ambiente, "a"), b) is False
    assert escopo.recurso_pertence_a(_recurso(ambiente, "publico"), a) is False
    assert escopo.recurso_pertence_a(_recurso(ambiente, "a"), None) is False


# ==========================================
# ACESSO POR PAPEL (POLÍTICA DE ESCOPO)
# ==========================================


def test_superadmin_acessa_recurso_permitido(ambiente):
    superadmin = _usuario(ambiente, "superadmin")
    for nome in ("a", "b", "publico", "sem_dono"):
        recurso = _recurso(ambiente, nome)
        assert escopo.usuario_pode_acessar(superadmin, recurso) is True, nome
        assert escopo.usuario_pode_alterar(superadmin, recurso) is True, nome


def test_user_acessa_proprio_recurso(ambiente):
    a = _usuario(ambiente, "a")
    recurso = _recurso(ambiente, "a")
    assert escopo.usuario_pode_acessar(a, recurso) is True
    assert escopo.usuario_pode_alterar(a, recurso) is True


def test_user_nao_acessa_recurso_de_outro_user(ambiente):
    a = _usuario(ambiente, "a")
    b = _usuario(ambiente, "b")
    recurso_b = _recurso(ambiente, "b")
    assert escopo.usuario_pode_acessar(a, recurso_b) is False
    assert escopo.usuario_pode_acessar(b, _recurso(ambiente, "a")) is False


def test_user_nao_altera_recurso_de_outro_user(ambiente):
    a = _usuario(ambiente, "a")
    recurso_b = _recurso(ambiente, "b")
    assert escopo.usuario_pode_alterar(a, recurso_b) is False
    with pytest.raises(escopo.AcessoRecursoNegadoError):
        escopo.requer_pode_alterar(a, recurso_b)


def test_user_nao_exclui_recurso_de_outro_user(ambiente):
    a = _usuario(ambiente, "a")
    recurso_b = _recurso(ambiente, "b")
    assert escopo.usuario_pode_alterar(a, recurso_b) is False


def test_visitor_acessa_recurso_publico(ambiente):
    visitor = _usuario(ambiente, "visitor")
    assert escopo.usuario_pode_acessar(visitor, _recurso(ambiente, "publico")) is True
    assert escopo.usuario_pode_acessar(visitor, _recurso(ambiente, "sem_dono")) is True


def test_visitor_nao_acessa_recurso_privado(ambiente):
    visitor = _usuario(ambiente, "visitor")
    assert escopo.usuario_pode_acessar(visitor, _recurso(ambiente, "a")) is False
    assert escopo.usuario_pode_acessar(visitor, _recurso(ambiente, "b")) is False
    assert escopo.usuario_pode_alterar(visitor, _recurso(ambiente, "a")) is False


def test_usuario_desativado_nao_acessa_recursos_privados(ambiente):
    desativado = _usuario(ambiente, "desativado")
    assert escopo.usuario_pode_acessar(desativado, _recurso(ambiente, "a")) is False
    assert escopo.usuario_pode_acessar(desativado, _recurso(ambiente, "b")) is False
    assert escopo.usuario_pode_alterar(desativado, _recurso(ambiente, "a")) is False


def test_usuario_none_nao_acessa_recurso_privado(ambiente):
    assert escopo.usuario_pode_acessar(None, _recurso(ambiente, "a")) is False
    assert escopo.usuario_pode_alterar(None, _recurso(ambiente, "a")) is False
    assert escopo.recurso_pertence_a(_recurso(ambiente, "a"), None) is False


# ==========================================
# ANTI-IDOR/BOLA E INDISTINÇÃO DE EXISTÊNCIA
# ==========================================


def test_id_inexistente_nao_revela_informacoes(ambiente):
    sessao = ambiente["Session"]()
    try:
        a = sessao.get(usuarios.Usuario, ambiente["usuarios"]["a"])
        b = sessao.get(usuarios.Usuario, ambiente["usuarios"]["b"])
        recurso_a = sessao.get(RecursoTeste, ambiente["recursos"]["a"])

        inexistente = escopo.buscar_recurso_escopado(sessao, RecursoTeste, 999999, a)
        bloqueado = escopo.buscar_recurso_escopado(
            sessao, RecursoTeste, recurso_a.id, b
        )
        assert inexistente is None
        assert bloqueado is None
        assert escopo.buscar_recurso_escopado(sessao, RecursoTeste, recurso_a.id, a) is recurso_a
    finally:
        sessao.close()


def test_idor_bola_bloqueada(ambiente):
    sessao = ambiente["Session"]()
    try:
        b = sessao.get(usuarios.Usuario, ambiente["usuarios"]["b"])
        recurso_a = sessao.get(RecursoTeste, ambiente["recursos"]["a"])

        assert escopo.buscar_recurso_escopado(sessao, RecursoTeste, recurso_a.id, b) is None
        assert escopo.usuario_pode_acessar(b, recurso_a) is False
        assert escopo.usuario_pode_alterar(b, recurso_a) is False
        with pytest.raises(escopo.AcessoRecursoNegadoError):
            escopo.requer_recurso_acessivel(b, recurso_a)
        with pytest.raises(escopo.AcessoRecursoNegadoError):
            escopo.requer_pode_alterar(b, recurso_a)
    finally:
        sessao.close()


def test_isolamento_entre_dois_usuarios(ambiente):
    sessao = ambiente["Session"]()
    try:
        a = sessao.get(usuarios.Usuario, ambiente["usuarios"]["a"])
        b = sessao.get(usuarios.Usuario, ambiente["usuarios"]["b"])
        recurso_a = sessao.get(RecursoTeste, ambiente["recursos"]["a"])
        recurso_b = sessao.get(RecursoTeste, ambiente["recursos"]["b"])

        assert escopo.usuario_pode_acessar(a, recurso_a) is True
        assert escopo.usuario_pode_acessar(b, recurso_b) is True
        assert escopo.usuario_pode_acessar(a, recurso_b) is False
        assert escopo.usuario_pode_acessar(b, recurso_a) is False
        assert escopo.usuario_pode_alterar(a, recurso_b) is False
        assert escopo.usuario_pode_alterar(b, recurso_a) is False
    finally:
        sessao.close()


def test_recurso_publico_por_busca_escopada(ambiente):
    sessao = ambiente["Session"]()
    try:
        visitor = sessao.get(usuarios.Usuario, ambiente["usuarios"]["visitor"])
        user = sessao.get(usuarios.Usuario, ambiente["usuarios"]["a"])
        publico = escopo.buscar_recurso_escopado(
            sessao, RecursoTeste, ambiente["recursos"]["publico"], visitor
        )
        sem_dono = escopo.buscar_recurso_escopado(
            sessao, RecursoTeste, ambiente["recursos"]["sem_dono"], user
        )
        assert publico is not None and publico.nome == "Recurso Público"
        assert sem_dono is not None and sem_dono.nome == "Recurso Plataforma"
    finally:
        sessao.close()


# ==========================================
# ADMIN E SUPERADMIN
# ==========================================


def test_admin_segue_regras_administrativas_existentes(ambiente):
    sessao = ambiente["Session"]()
    try:
        admin = sessao.get(usuarios.Usuario, ambiente["usuarios"]["admin"])
        user = sessao.get(usuarios.Usuario, ambiente["usuarios"]["a"])
        recurso_b = sessao.get(RecursoTeste, ambiente["recursos"]["b"])

        assert escopo.usuario_pode_acessar(admin, recurso_b) is False
        assert escopo.usuario_pode_alterar(admin, recurso_b) is False
        assert escopo.usuario_pode_administrar(admin) is False

        assert (
            escopo.usuario_pode_acessar(
                admin, recurso_b, permissao_administrativa="usuarios.ler"
            )
            is True
        )
        assert (
            escopo.usuario_pode_administrar(admin, "usuarios.ler") is True
        )
        assert (
            escopo.usuario_pode_acessar(
                user, recurso_b, permissao_administrativa="usuarios.ler"
            )
            is False
        )
        assert (
            escopo.usuario_pode_administrar(user, "usuarios.ler") is False
        )
    finally:
        sessao.close()


def test_admin_nao_recebe_acesso_privado_implicito(ambiente):
    admin = _usuario(ambiente, "admin")
    for nome in ("a", "b"):
        assert escopo.usuario_pode_acessar(admin, _recurso(ambiente, nome)) is False
        assert escopo.usuario_pode_alterar(admin, _recurso(ambiente, nome)) is False


def test_superadmin_mantem_wildcard(ambiente):
    sessao = ambiente["Session"]()
    try:
        superadmin = sessao.get(usuarios.Usuario, ambiente["usuarios"]["superadmin"])
        admin = sessao.get(usuarios.Usuario, ambiente["usuarios"]["admin"])
        recurso_b = sessao.get(RecursoTeste, ambiente["recursos"]["b"])

        assert autorizacao.tem_permissao(superadmin, "*") is True
        assert escopo.usuario_pode_administrar(superadmin) is True
        assert escopo.usuario_pode_administrar(superadmin, "qualquer.permissao") is True
        assert escopo.usuario_pode_acessar(superadmin, recurso_b) is True
        assert escopo.usuario_pode_alterar(superadmin, recurso_b) is True
        assert escopo.usuario_pode_administrar(admin) is False
    finally:
        sessao.close()


# ==========================================
# SEGREDOS
# ==========================================


def test_nenhum_segredo_em_excecao_e_auditoria(ambiente):
    sessao = ambiente["Session"]()
    try:
        b = sessao.get(usuarios.Usuario, ambiente["usuarios"]["b"])
        recurso_a = sessao.get(RecursoTeste, ambiente["recursos"]["a"])

        with pytest.raises(escopo.AcessoRecursoNegadoError) as captura:
            escopo.requer_pode_alterar(b, recurso_a, recurso_tipo="carteira")
        mensagem = str(captura.value)
        assert "senha1234" not in mensagem
        assert "senha_hash" not in mensagem
        assert "token" not in mensagem
        assert "chave_hash" not in mensagem

        auditoria.registrar_evento(
            acao="TESTE_ESCOPO_NEGADO",
            alvo=recurso_a.nome,
            detalhe="motivo=escopo",
            usuario_id=b.id,
            sucesso=False,
            session=sessao,
        )
        sessao.commit()
        registros = sessao.query(AuditoriaAcesso).all()
        texto = "\n".join(f"{e.acao} {e.alvo or ''} {e.detalhe or ''}" for e in registros)
        assert "senha1234" not in texto
        assert "senha_hash" not in texto
        assert "chave_hash" not in texto
    finally:
        sessao.close()
