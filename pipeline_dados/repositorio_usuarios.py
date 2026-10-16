"""Repositorio de acesso a tabela ``usuarios`` (cadastro e aprovacao).

Camada isolada e testavel: aceita uma ``session_factory`` alternativa (usada nos
testes com SQLite em memoria) e, por padrao, usa a conexao central normalizada de
``pipeline_dados.conexao``.

Regras de seguranca:
* nao cria/recria tabelas nem executa migracoes;
* qualquer falha de banco e propagada como excecao para que o chamador decida
  negar acesso (o repositorio nunca "adivinha" um papel);
* nenhum dado sensivel (URL de conexao, tokens) e registrado em log.
"""

import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from pipeline_dados.conexao import obter_session_factory
from pipeline_dados.modelos_usuarios import (
    STATUS_APROVADO,
    STATUS_PENDENTE,
    STATUS_REJEITADO,
    STATUS_SUSPENSO,
    STATUS_VALIDOS,
    Usuario,
)

logger = logging.getLogger("robo.usuarios")

PAPEL_USUARIO_PADRAO = "user"


class RepositorioUsuarios:
    def __init__(self, session_factory=None):
        self._session_factory = session_factory

    def _nova_sessao(self):
        factory = self._session_factory or obter_session_factory()
        return factory()

    @staticmethod
    def _normalizar_telegram_id(telegram_user_id):
        if telegram_user_id is None:
            return None
        try:
            return int(str(telegram_user_id).strip())
        except (TypeError, ValueError):
            return None

    def obter_por_telegram_id(self, telegram_user_id):
        chave = self._normalizar_telegram_id(telegram_user_id)
        if chave is None:
            return None
        session = self._nova_sessao()
        try:
            usuario = (
                session.query(Usuario)
                .filter(Usuario.telegram_user_id == chave)
                .first()
            )
            return usuario.para_dto() if usuario else None
        finally:
            session.close()

    def obter_por_id(self, usuario_id):
        if usuario_id is None:
            return None
        session = self._nova_sessao()
        try:
            usuario = session.get(Usuario, usuario_id)
            return usuario.para_dto() if usuario else None
        finally:
            session.close()

    def listar_por_status(self, status, limite=None, deslocamento=0):
        """Lista as contas de um status, de forma paginada e somente-leitura.

        Usado pela Central de Controles administrativa para exibir as áreas
        (pendentes, aprovados, rejeitados, suspensos) sem carregar todo o banco
        de uma vez. Nao altera o schema nem cria tabelas; apenas consulta a
        coluna ``status_cadastro`` ja existente. A ordenacao e por ``id``
        (criterio estavel mesmo quando ``criado_em`` e nulo). Qualquer falha de
        banco propaga a excecao para o chamador tratar (falha segura).
        """
        if status not in STATUS_VALIDOS:
            raise ValueError(f"status invalido: {status!r}")
        if deslocamento is None or deslocamento < 0:
            deslocamento = 0
        session = self._nova_sessao()
        try:
            consulta = (
                session.query(Usuario)
                .filter(Usuario.status_cadastro == status)
                .order_by(Usuario.id.asc())
            )
            if deslocamento:
                consulta = consulta.offset(deslocamento)
            if limite is not None:
                consulta = consulta.limit(limite)
            return [usuario.para_dto() for usuario in consulta.all()]
        finally:
            session.close()

    def contar_por_status(self, status):
        """Conta as contas de um status (somente-leitura, para paginacao)."""
        if status not in STATUS_VALIDOS:
            raise ValueError(f"status invalido: {status!r}")
        session = self._nova_sessao()
        try:
            total = (
                session.query(func.count(Usuario.id))
                .filter(Usuario.status_cadastro == status)
                .scalar()
            )
            return int(total or 0)
        finally:
            session.close()

    def criar_solicitacao(self, telegram_user_id, telegram_chat_id, nome=None, email=None):
        """Cria uma solicitacao pendente, sem duplicar usuarios existentes.

        Retorna ``(dto, criado)``. Se ja existir conta para o ``telegram_user_id``,
        retorna a existente com ``criado=False`` e **nao** altera nenhum campo
        (nome, email, papel, plano, status). Nunca sobrescreve conta existente.

        ``nome`` e ``email`` alimentam colunas que ja existem na tabela
        ``usuarios`` (nenhum schema e alterado); ``email`` e gravado apenas se
        informado.
        """
        chave = self._normalizar_telegram_id(telegram_user_id)
        if chave is None:
            raise ValueError("telegram_user_id invalido para cadastro")

        existente = self.obter_por_telegram_id(chave)
        if existente is not None:
            return existente, False

        session = self._nova_sessao()
        try:
            agora = datetime.now()
            usuario = Usuario(
                nome=(nome or None),
                email=(email or None),
                papel=PAPEL_USUARIO_PADRAO,
                ativo=False,
                telegram_user_id=chave,
                telegram_chat_id=self._normalizar_telegram_id(telegram_chat_id),
                criado_em=agora,
                atualizado_em=agora,
                status_cadastro=STATUS_PENDENTE,
            )
            session.add(usuario)
            try:
                session.commit()
            except IntegrityError:
                # Corrida: outra transacao criou o mesmo telegram_user_id.
                session.rollback()
                existente = self.obter_por_telegram_id(chave)
                return existente, False
            session.refresh(usuario)
            return usuario.para_dto(), True
        finally:
            session.close()

    def atualizar_chat_id(self, usuario_id, telegram_chat_id):
        """Atualiza apenas o ``telegram_chat_id`` de um usuario.

        Regra explicita: o chat_id e o endereco de entrega e pode ser atualizado
        quando o mesmo ``telegram_user_id`` inicia a conversa. Nome, papel, plano
        e status NUNCA sao alterados por este metodo.
        """
        chave = self._normalizar_telegram_id(telegram_chat_id)
        if usuario_id is None or chave is None:
            return None
        session = self._nova_sessao()
        try:
            usuario = session.get(Usuario, usuario_id)
            if usuario is None:
                return None
            if usuario.telegram_chat_id != chave:
                usuario.telegram_chat_id = chave
                usuario.atualizado_em = datetime.now()
                session.commit()
            return usuario.para_dto()
        finally:
            session.close()

    def definir_status(self, usuario_id, status, origens_permitidas=None):
        """Define o status de cadastro de forma idempotente.

        Retorna ``(dto, mudou)``. Se o usuario ja estiver no status alvo,
        ``mudou=False`` e nada e alterado (cliques repetidos sao seguros).

        ``origens_permitidas`` (opcional) e uma colecao de status de origem
        aceitos para a transicao. Quando informada e o status **atual** (lido
        nesta mesma sessao, no momento da gravacao) nao estiver nela, nada e
        alterado e retorna ``(dto_atual, False)``: o chamador distingue "ja
        estava no alvo" de "transicao bloqueada" comparando ``dto.status`` com
        o alvo. Isso evita que uma decisao baseada em tela/botao antigo (estado
        desatualizado) sobrescreva um estado que mudou nesse intervalo.
        Sem o argumento, o comportamento anterior e preservado integralmente.
        """
        if status not in STATUS_VALIDOS:
            raise ValueError(f"status invalido: {status!r}")
        if usuario_id is None:
            return None, False

        session = self._nova_sessao()
        try:
            usuario = session.get(Usuario, usuario_id)
            if usuario is None:
                return None, False
            if usuario.status_cadastro == status:
                return usuario.para_dto(), False
            if (
                origens_permitidas is not None
                and usuario.status_cadastro not in origens_permitidas
            ):
                return usuario.para_dto(), False

            usuario.status_cadastro = status
            usuario.ativo = status == STATUS_APROVADO
            usuario.atualizado_em = datetime.now()
            session.commit()
            session.refresh(usuario)
            return usuario.para_dto(), True
        finally:
            session.close()

    def aprovar(self, usuario_id, origens_permitidas=None):
        return self.definir_status(usuario_id, STATUS_APROVADO, origens_permitidas)

    def rejeitar(self, usuario_id, origens_permitidas=None):
        return self.definir_status(usuario_id, STATUS_REJEITADO, origens_permitidas)

    def suspender(self, usuario_id, origens_permitidas=None):
        return self.definir_status(usuario_id, STATUS_SUSPENSO, origens_permitidas)

    def papel_de_usuario_aprovado(self, telegram_user_id):
        """Retorna o papel apenas de usuario aprovado e ativo (ou ``None``).

        Usado como fonte persistente de papel por ``bot.permissoes``. Qualquer
        falha de banco propaga a excecao; o chamador trata como "sem acesso".
        """
        usuario = self.obter_por_telegram_id(telegram_user_id)
        if usuario is None:
            return None
        if usuario.status != STATUS_APROVADO:
            return None
        if not usuario.ativo:
            return None
        return usuario.papel
