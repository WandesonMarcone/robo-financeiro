"""Repositório das solicitações de troca de ativo favorito.

Vincula ``usuarios.id`` a dois ativos (saída e entrada) na tabela
``solicitacoes_troca`` (criada manualmente pela migração 0002). O repositório
NÃO cria/escreve a tabela em produção: nos testes ela é criada num SQLite em
memória isolado (``BaseTrocas.metadata.create_all``).

Regras:
* o ``usuario_id`` nunca vem do cliente: é resolvido pelo chamador a partir do
  Telegram ID autenticado;
* saída e entrada precisam existir na tabela ``ativos`` e ser do MESMO tipo
  (FII→FII ou Ação→Ação); nada é inventado;
* no máximo uma solicitação pendente por usuário (duplicidades retornam a
  existente com ``criado=False``);
* estados terminais (aprovada/rejeitada/expirada) nunca são redecididos;
* a aprovação aplica a troca e muda o estado na MESMA transação (atômico);
* falhas de banco propagam a exceção para o chamador negar a operação.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func

from pipeline_dados.banco_dados import Ativo
from pipeline_dados.conexao import obter_session_factory
from pipeline_dados.modelos_ativos import AtivoAcompanhado
from pipeline_dados.modelos_trocas import (
    STATUS_TROCA_APROVADA,
    STATUS_TROCA_EXPIRADA,
    STATUS_TROCA_PENDENTE,
    STATUS_TROCA_TERMINAIS,
    STATUS_TROCA_VALIDOS,
    SolicitacaoTroca,
)

logger = logging.getLogger("robo.trocas")


class TrocaInvalidaError(Exception):
    """Levantada quando os ativos de uma solicitação de troca são inválidos."""


class TrocaNaoEncontradaError(Exception):
    """Levantada quando a solicitação informada não existe."""


class TrocaDTO:
    """Representação simples (desanexada) de uma solicitação de troca."""

    __slots__ = (
        "id",
        "usuario_id",
        "ativo_saida_id",
        "ativo_entrada_id",
        "ticker_saida",
        "ticker_entrada",
        "tipo",
        "status",
        "criado_em",
        "decidido_em",
        "decidido_por",
    )

    def __init__(
        self,
        id,
        usuario_id,
        ativo_saida_id,
        ativo_entrada_id,
        ticker_saida,
        ticker_entrada,
        tipo,
        status,
        criado_em=None,
        decidido_em=None,
        decidido_por=None,
    ):
        self.id = id
        self.usuario_id = usuario_id
        self.ativo_saida_id = ativo_saida_id
        self.ativo_entrada_id = ativo_entrada_id
        self.ticker_saida = ticker_saida
        self.ticker_entrada = ticker_entrada
        self.tipo = tipo
        self.status = status
        self.criado_em = criado_em
        self.decidido_em = decidido_em
        self.decidido_por = decidido_por

    def esta_pendente(self):
        return self.status == STATUS_TROCA_PENDENTE

    def __repr__(self):  # pragma: no cover - diagnóstico
        return (
            f"TrocaDTO(id={self.id!r}, {self.ticker_saida!r}->"
            f"{self.ticker_entrada!r}, status={self.status!r})"
        )


def _tipo_str(tipo_enum):
    return str(getattr(tipo_enum, "name", tipo_enum)).upper()


class RepositorioTrocas:
    def __init__(self, session_factory=None):
        self._session_factory = session_factory

    def _nova_sessao(self):
        factory = self._session_factory or obter_session_factory()
        return factory()

    @staticmethod
    def _id(valor):
        if valor is None:
            return None
        try:
            return int(str(valor).strip())
        except (TypeError, ValueError):
            return None

    def _resolver_ativo(self, session, ativo_id):
        ativo = session.get(Ativo, ativo_id)
        if ativo is None:
            return None
        return ativo

    def _para_dto(self, sessao, troca):
        saida = sessao.get(Ativo, troca.ativo_saida_id)
        entrada = sessao.get(Ativo, troca.ativo_entrada_id)
        return TrocaDTO(
            id=troca.id,
            usuario_id=troca.usuario_id,
            ativo_saida_id=troca.ativo_saida_id,
            ativo_entrada_id=troca.ativo_entrada_id,
            ticker_saida=saida.ticker if saida else None,
            ticker_entrada=entrada.ticker if entrada else None,
            tipo=_tipo_str(entrada.tipo) if entrada else (
                _tipo_str(saida.tipo) if saida else None
            ),
            status=troca.status,
            criado_em=troca.criado_em,
            decidido_em=troca.decidido_em,
            decidido_por=troca.decidido_por,
        )

    # -- Consultas ---------------------------------------------------------

    def obter(self, troca_id):
        chave = self._id(troca_id)
        if chave is None:
            return None
        session = self._nova_sessao()
        try:
            troca = session.get(SolicitacaoTroca, chave)
            return self._para_dto(session, troca) if troca else None
        finally:
            session.close()

    def pendente_do_usuario(self, usuario_id):
        usuario = self._id(usuario_id)
        if usuario is None:
            return None
        session = self._nova_sessao()
        try:
            troca = (
                session.query(SolicitacaoTroca)
                .filter(
                    SolicitacaoTroca.usuario_id == usuario,
                    SolicitacaoTroca.status == STATUS_TROCA_PENDENTE,
                )
                .order_by(SolicitacaoTroca.id.desc())
                .first()
            )
            return self._para_dto(session, troca) if troca else None
        finally:
            session.close()

    def listar_por_status(self, status, limite=None, deslocamento=0):
        if status not in STATUS_TROCA_VALIDOS:
            raise ValueError(f"status inválido: {status!r}")
        if deslocamento is None or deslocamento < 0:
            deslocamento = 0
        session = self._nova_sessao()
        try:
            consulta = (
                session.query(SolicitacaoTroca)
                .filter(SolicitacaoTroca.status == status)
                .order_by(SolicitacaoTroca.id.asc())
            )
            if deslocamento:
                consulta = consulta.offset(deslocamento)
            if limite is not None:
                consulta = consulta.limit(limite)
            return [self._para_dto(session, troca) for troca in consulta.all()]
        finally:
            session.close()

    def listar_do_usuario(self, usuario_id, limite=None):
        usuario = self._id(usuario_id)
        if usuario is None:
            return []
        session = self._nova_sessao()
        try:
            consulta = (
                session.query(SolicitacaoTroca)
                .filter(SolicitacaoTroca.usuario_id == usuario)
                .order_by(SolicitacaoTroca.id.desc())
            )
            if limite is not None:
                consulta = consulta.limit(limite)
            return [self._para_dto(session, troca) for troca in consulta.all()]
        finally:
            session.close()

    def contar_por_status(self, status):
        if status not in STATUS_TROCA_VALIDOS:
            raise ValueError(f"status inválido: {status!r}")
        session = self._nova_sessao()
        try:
            total = (
                session.query(func.count(SolicitacaoTroca.id))
                .filter(SolicitacaoTroca.status == status)
                .scalar()
            )
            return int(total or 0)
        finally:
            session.close()

    # -- Criação -----------------------------------------------------------

    def criar(self, usuario_id, ativo_saida_id, ativo_entrada_id):
        """Cria (ou retorna) a solicitação pendente de troca.

        Retorna ``(dto, criado)``. Levanta :class:`TrocaInvalidaError` se os
        ativos não existirem, forem iguais ou de tipos diferentes. Se já existir
        solicitação pendente para o usuário, retorna a existente com
        ``criado=False``.
        """
        usuario = self._id(usuario_id)
        saida_id = self._id(ativo_saida_id)
        entrada_id = self._id(ativo_entrada_id)
        if usuario is None or saida_id is None or entrada_id is None:
            raise TrocaInvalidaError("identificadores inválidos para a troca")
        if saida_id == entrada_id:
            raise TrocaInvalidaError("saída e entrada não podem ser o mesmo ativo")

        session = self._nova_sessao()
        try:
            saida = self._resolver_ativo(session, saida_id)
            entrada = self._resolver_ativo(session, entrada_id)
            if saida is None or entrada is None:
                raise TrocaInvalidaError("ativo inexistente no catálogo")
            if _tipo_str(saida.tipo) != _tipo_str(entrada.tipo):
                raise TrocaInvalidaError("os ativos devem ser do mesmo tipo")

            existente = (
                session.query(SolicitacaoTroca)
                .filter(
                    SolicitacaoTroca.usuario_id == usuario,
                    SolicitacaoTroca.status == STATUS_TROCA_PENDENTE,
                )
                .order_by(SolicitacaoTroca.id.desc())
                .first()
            )
            if existente is not None:
                return self._para_dto(session, existente), False

            troca = SolicitacaoTroca(
                usuario_id=usuario,
                ativo_saida_id=saida_id,
                ativo_entrada_id=entrada_id,
                status=STATUS_TROCA_PENDENTE,
                criado_em=datetime.now(),
            )
            session.add(troca)
            session.commit()
            session.refresh(troca)
            return self._para_dto(session, troca), True
        finally:
            session.close()

    # -- Expiração ---------------------------------------------------------

    def expirar_vencidas(self, prazo_horas, agora=None):
        """Marca como ``expirada`` as pendentes fora do prazo.

        NUNCA aprova automaticamente: apenas muda o estado (histórico é
        preservado). Retorna a quantidade de solicitações expiradas. Quando
        ``prazo_horas`` é ``None``/0, nada é feito.
        """
        if not prazo_horas or prazo_horas <= 0:
            return 0
        referencia = agora or datetime.now()
        limite = referencia - timedelta(hours=prazo_horas)
        session = self._nova_sessao()
        try:
            pendentes = (
                session.query(SolicitacaoTroca)
                .filter(
                    SolicitacaoTroca.status == STATUS_TROCA_PENDENTE,
                    SolicitacaoTroca.criado_em.isnot(None),
                    SolicitacaoTroca.criado_em < limite,
                )
                .all()
            )
            for troca in pendentes:
                troca.status = STATUS_TROCA_EXPIRADA
                troca.decidido_em = referencia
            if pendentes:
                session.commit()
            return len(pendentes)
        finally:
            session.close()

    # -- Decisão -----------------------------------------------------------

    def decidir(self, troca_id, status, autor_id=None, origens_permitidas=None):
        """Aplica uma decisão terminal a uma solicitação (idempotente).

        Retorna ``(dto, mudou)``. Uma solicitação em estado terminal nunca é
        alterada novamente. ``origens_permitidas`` (opcional) restringe as
        origens aceitas e é conferida na própria gravação: um callback antigo não
        sobrescreve um estado que mudou.
        """
        if status not in STATUS_TROCA_TERMINAIS:
            raise ValueError(f"status de decisão inválido: {status!r}")
        chave = self._id(troca_id)
        if chave is None:
            return None, False
        session = self._nova_sessao()
        try:
            troca = session.get(SolicitacaoTroca, chave)
            if troca is None:
                return None, False
            if troca.status == status:
                return self._para_dto(session, troca), False
            if troca.status in STATUS_TROCA_TERMINAIS:
                return self._para_dto(session, troca), False
            if (
                origens_permitidas is not None
                and troca.status not in origens_permitidas
            ):
                return self._para_dto(session, troca), False
            troca.status = status
            troca.decidido_em = datetime.now()
            troca.decidido_por = self._id(autor_id)
            session.commit()
            session.refresh(troca)
            return self._para_dto(session, troca), True
        finally:
            session.close()

    def aplicar_aprovacao(self, troca_id, autor_id=None):
        """Aprova a troca aplicando o vínculo de favoritos numa única transação.

        Remove o vínculo com o ativo de saída e cria o vínculo com o de entrada,
        marcando a solicitação como ``aprovada`` atomicamente. É idempotente:
        reprocessar uma solicitação já decidida não altera favoritos e retorna
        ``(dto, False)``. Retorna ``(dto, aplicado)``.

        Levanta :class:`TrocaInvalidaError` (sem alterar favoritos nem estado)
        quando o vínculo de saída não existe mais, quando um ativo sumiu do
        catálogo ou quando os tipos divergiram. A conferência ocorre na mesma
        transação da gravação, impedindo aprovar um pedido desatualizado.
        """
        chave = self._id(troca_id)
        if chave is None:
            return None, False
        session = self._nova_sessao()
        try:
            troca = session.get(SolicitacaoTroca, chave)
            if troca is None:
                return None, False
            if troca.status in STATUS_TROCA_TERMINAIS:
                return self._para_dto(session, troca), False

            # A decisao so e valida se o ativo de saida AINDA for favorito do
            # solicitante. Isso impede aprovar um pedido antigo depois que o
            # vinculo mudou e evita aumentar favoritos indevidamente.
            vinculo_saida = (
                session.query(AtivoAcompanhado)
                .filter(
                    AtivoAcompanhado.usuario_id == troca.usuario_id,
                    AtivoAcompanhado.ativo_id == troca.ativo_saida_id,
                )
                .first()
            )
            if vinculo_saida is None:
                raise TrocaInvalidaError(
                    "o ativo de saida nao e mais favorito do solicitante"
                )

            saida = self._resolver_ativo(session, troca.ativo_saida_id)
            entrada = self._resolver_ativo(session, troca.ativo_entrada_id)
            if saida is None or entrada is None:
                raise TrocaInvalidaError("ativo inexistente no catalogo")
            if _tipo_str(saida.tipo) != _tipo_str(entrada.tipo):
                raise TrocaInvalidaError("os ativos devem ser do mesmo tipo")

            session.delete(vinculo_saida)

            ja_existe = (
                session.query(AtivoAcompanhado)
                .filter(
                    AtivoAcompanhado.usuario_id == troca.usuario_id,
                    AtivoAcompanhado.ativo_id == troca.ativo_entrada_id,
                )
                .first()
            )
            if ja_existe is None:
                session.add(
                    AtivoAcompanhado(
                        usuario_id=troca.usuario_id,
                        ativo_id=troca.ativo_entrada_id,
                        criado_em=datetime.now(),
                    )
                )

            troca.status = STATUS_TROCA_APROVADA
            troca.decidido_em = datetime.now()
            troca.decidido_por = self._id(autor_id)
            session.commit()
            session.refresh(troca)
            return self._para_dto(session, troca), True
        finally:
            session.close()
