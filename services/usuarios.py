"""Serviço de usuários e autenticação (Fase 5, Etapa 3).

Centraliza a criação, consulta, listagem, autenticação e gestão de usuários
(papel, ativação, senha e vínculo com o Telegram), registrando os eventos na
trilha de auditoria (``services/auditoria.py``).

Garantias de segurança:
- Senhas nunca são armazenadas em texto puro: apenas o hash gerado por
  ``werkzeug.security.generate_password_hash`` (sem algoritmo próprio).
- Nenhuma senha, token, chave de API ou segredo é gravado na auditoria/logs.
- Login de usuário inexistente e senha incorreta produzem a mesma resposta
  (``None``), prevenindo enumeração de usuários.

A integração com o mecanismo legado de ``modules/seguranca.py`` pertence à
etapa seguinte; este serviço apenas valida o ``papel`` contra o conjunto
definido pelo projeto.
"""
import contextlib
import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from atualizador_documentos import SessionDB
from pipeline_dados.banco_dados import Usuario
from services import auditoria

logger = logging.getLogger(__name__)

# Papéis previstos pela Fase 5. A matriz completa de permissões é da Etapa 6;
# aqui o papel é apenas validado contra este conjunto.
SUPERADMIN = "SUPERADMIN"
ADMIN = "ADMIN"
USER = "USER"
VISITOR = "VISITOR"

PAPEIS_VALIDOS = (SUPERADMIN, ADMIN, USER, VISITOR)
PAPEL_PADRAO = USER

# Comprimento mínimo de senha exigido pelo projeto.
SENHA_MINIMA = 8

# Hash descartável usado apenas para equalizar o tempo de resposta entre
# usuário inexistente e senha incorreta (anti-enumeração). Nunca é atribuído
# a nenhum usuário real.
_HASH_DUMMY = generate_password_hash("hash-dummy-anti-enumeracao")


@contextlib.contextmanager
def _sessao(session):
    """Usa a sessão informada ou abre, confirma e fecha uma própria.

    Sessões externas (informadas pelo chamador, ex.: testes com SQLite em
    memória) nunca são fechadas pelo serviço; o commit fica a cargo do chamador
    quando ele abre a sessão. Sessões próprias seguem o padrão do projeto
    (``SessionDB``) com commit no sucesso e rollback em erro.
    """
    if session is not None:
        yield session
        return
    sessao = SessionDB()
    try:
        yield sessao
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao.close()


def _validar_senha(senha):
    """Valida o comprimento mínimo da senha."""
    if not isinstance(senha, str) or len(senha) < SENHA_MINIMA:
        raise ValueError(f"A senha deve ter no mínimo {SENHA_MINIMA} caracteres.")


def _validar_papel(papel):
    """Valida o papel contra o conjunto definido pelo projeto."""
    if papel not in PAPEIS_VALIDOS:
        raise ValueError(
            f"Papel inválido: {papel!r}. Válidos: {', '.join(PAPEIS_VALIDOS)}."
        )


def _alvo(usuario):
    """Rótulo de alvo para auditoria (email quando disponível, senão o id)."""
    return usuario.email if usuario.email else f"usuario:{usuario.id}"


# ==========================================
# CRIAÇÃO E CONSULTA
# ==========================================


def criar_usuario(
    nome,
    email=None,
    senha=None,
    papel=PAPEL_PADRAO,
    telegram_user_id=None,
    telegram_chat_id=None,
    ativo=True,
    session=None,
    ip=None,
):
    """Cria um novo usuário.

    A senha, quando fornecida, é armazenada apenas como hash (nunca em texto
    puro) e deve ter no mínimo ``SENHA_MINIMA`` caracteres. Email e
    ``telegram_user_id`` são únicos quando informados; duplicidade é rejeitada
    com ``ValueError``. Registra o evento ``USUARIO_CRIADO`` na auditoria.
    """
    _validar_papel(papel)
    if not nome or not str(nome).strip():
        raise ValueError("O nome do usuário é obrigatório.")

    senha_hash = None
    if senha is not None:
        _validar_senha(senha)
        senha_hash = generate_password_hash(senha)

    with _sessao(session) as s:
        usuario = Usuario(
            nome=str(nome).strip(),
            email=email,
            senha_hash=senha_hash,
            papel=papel,
            ativo=bool(ativo),
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
        )
        s.add(usuario)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise ValueError("Já existe um usuário com este email ou Telegram.") from None

        auditoria.registrar_evento(
            acao="USUARIO_CRIADO",
            alvo=usuario.email,
            detalhe=f"papel={papel}",
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
        return usuario


def buscar_usuario(identificador, session=None):
    """Busca um usuário por id (int) ou email (str). Retorna ``None`` se não existir."""
    with _sessao(session) as s:
        if isinstance(identificador, int):
            return s.get(Usuario, identificador)
        if isinstance(identificador, str) and identificador.strip().isdigit():
            return s.get(Usuario, int(identificador))
        return s.query(Usuario).filter(Usuario.email == identificador).first()


def buscar_usuario_por_email(email, session=None):
    """Busca um usuário pelo email. Retorna ``None`` se não existir."""
    with _sessao(session) as s:
        return s.query(Usuario).filter(Usuario.email == email).first()


def buscar_usuario_por_telegram(telegram_user_id, session=None):
    """Busca um usuário pelo ``telegram_user_id``. Retorna ``None`` se não existir."""
    if telegram_user_id is None:
        return None
    with _sessao(session) as s:
        return (
            s.query(Usuario).filter(Usuario.telegram_user_id == telegram_user_id).first()
        )


def listar_usuarios(apenas_ativos=False, session=None):
    """Lista os usuários, opcionalmente apenas os ativos, em ordem de criação."""
    with _sessao(session) as s:
        query = s.query(Usuario)
        if apenas_ativos:
            query = query.filter(Usuario.ativo.is_(True))
        return query.order_by(Usuario.id).all()


# ==========================================
# AUTENTICAÇÃO
# ==========================================


def verificar_senha(usuario, senha):
    """Verifica a senha contra o hash armazenado (nunca em texto puro).

    Retorna ``False`` para usuário nulo, hash ausente/malformado ou senha
    incorreta, sem expor o motivo.
    """
    if usuario is None or not usuario.senha_hash:
        return False
    if not isinstance(senha, str):
        return False
    try:
        return check_password_hash(usuario.senha_hash, senha)
    except ValueError:
        return False


def autenticar(email, senha, session=None, ip=None):
    """Autentica um usuário pelo email e senha.

    Retorna o objeto ``Usuario`` em caso de sucesso (atualizando
    ``ultimo_login``) ou ``None`` em qualquer falha: usuário inexistente, senha
    incorreta ou usuário desativado. A resposta é indistinguível entre os casos
    de falha para prevenir enumeração de usuários. Registra ``LOGIN`` (sucesso
    ou falha) na auditoria.
    """
    with _sessao(session) as s:
        usuario = s.query(Usuario).filter(Usuario.email == email).first()

        if usuario is None:
            check_password_hash(_HASH_DUMMY, senha if isinstance(senha, str) else "")
            auditoria.registrar_evento(
                acao="LOGIN", alvo=email, usuario_id=None, ip=ip, sucesso=False, session=s
            )
            return None

        if not verificar_senha(usuario, senha):
            auditoria.registrar_evento(
                acao="LOGIN",
                alvo=email,
                usuario_id=usuario.id,
                ip=ip,
                sucesso=False,
                session=s,
            )
            return None

        if not usuario.ativo:
            auditoria.registrar_evento(
                acao="LOGIN",
                alvo=email,
                usuario_id=usuario.id,
                ip=ip,
                sucesso=False,
                session=s,
            )
            return None

        usuario.ultimo_login = datetime.now()
        s.commit()
        auditoria.registrar_evento(
            acao="LOGIN", alvo=email, usuario_id=usuario.id, ip=ip, sucesso=True, session=s
        )
        return usuario


# ==========================================
# GESTÃO DE SENHA, PAPEL E ATIVAÇÃO
# ==========================================


def alterar_senha(usuario, nova_senha, session=None, ip=None):
    """Altera a senha de um usuário, persistindo apenas o novo hash.

    Nunca registra a senha (nem o hash) na auditoria ou em logs.
    """
    if usuario is None:
        raise ValueError("Usuário inválido.")
    _validar_senha(nova_senha)
    with _sessao(session) as s:
        usuario = s.merge(usuario)
        usuario.senha_hash = generate_password_hash(nova_senha)
        s.commit()
        auditoria.registrar_evento(
            acao="SENHA_ALTERADA",
            alvo=_alvo(usuario),
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
        return True


def ativar_usuario(usuario, session=None, ip=None):
    """Ativa um usuário desativado."""
    if usuario is None:
        raise ValueError("Usuário inválido.")
    with _sessao(session) as s:
        usuario = s.merge(usuario)
        usuario.ativo = True
        s.commit()
        auditoria.registrar_evento(
            acao="USUARIO_ATIVADO",
            alvo=_alvo(usuario),
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
        return True


def desativar_usuario(usuario, session=None, ip=None):
    """Desativa um usuário (não poderá mais autenticar)."""
    if usuario is None:
        raise ValueError("Usuário inválido.")
    with _sessao(session) as s:
        usuario = s.merge(usuario)
        usuario.ativo = False
        s.commit()
        auditoria.registrar_evento(
            acao="USUARIO_DESATIVADO",
            alvo=_alvo(usuario),
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
        return True


def alterar_papel(usuario, novo_papel, session=None, ip=None):
    """Altera o papel de um usuário, validando contra ``PAPEIS_VALIDOS``."""
    if usuario is None:
        raise ValueError("Usuário inválido.")
    _validar_papel(novo_papel)
    with _sessao(session) as s:
        usuario = s.merge(usuario)
        usuario.papel = novo_papel
        s.commit()
        auditoria.registrar_evento(
            acao="PAPEL_ALTERADO",
            alvo=_alvo(usuario),
            detalhe=f"papel={novo_papel}",
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
        return True


# ==========================================
# TELEGRAM
# ==========================================


def vincular_telegram(usuario, telegram_user_id, telegram_chat_id=None, session=None, ip=None):
    """Vincula um usuário a um ``telegram_user_id`` (e opcionalmente chat).

    O ``telegram_user_id`` é único; vincular um ID já usado por outro usuário é
    rejeitado com ``ValueError``.
    """
    if usuario is None:
        raise ValueError("Usuário inválido.")
    with _sessao(session) as s:
        usuario = s.merge(usuario)
        usuario.telegram_user_id = telegram_user_id
        if telegram_chat_id is not None:
            usuario.telegram_chat_id = telegram_chat_id
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise ValueError("Este Telegram já está vinculado a outro usuário.") from None

        auditoria.registrar_evento(
            acao="TELEGRAM_VINCULADO",
            alvo=_alvo(usuario),
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
        return True


def desvincular_telegram(usuario, session=None, ip=None):
    """Remove o vínculo do usuário com o Telegram (ID de usuário e chat)."""
    if usuario is None:
        raise ValueError("Usuário inválido.")
    with _sessao(session) as s:
        usuario = s.merge(usuario)
        usuario.telegram_user_id = None
        usuario.telegram_chat_id = None
        s.commit()
        auditoria.registrar_evento(
            acao="TELEGRAM_DESVINCULADO",
            alvo=_alvo(usuario),
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
        return True
