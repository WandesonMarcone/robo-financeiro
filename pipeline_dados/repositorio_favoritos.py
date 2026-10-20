"""Repositorio dos favoritos individuais (tabela ``ativos_acompanhados``).

Vincula um usuario (``usuarios.id``) a um ativo (``ativos.id``) por meio da
tabela existente ``ativos_acompanhados``. Nao cria tabelas, nao executa
migracoes e nao altera registros de ``usuarios`` ou ``ativos``.

Regras:
* o vinculo persistente e ``(usuario_id, ativo_id)``; nunca se aceita o
  ``usuario_id`` vindo do cliente -- ele e resolvido pelo chamador a partir do
  Telegram ID;
* um ativo so pode ser acompanhado se existir na tabela ``ativos``; caso
  contrario :class:`AtivoNaoCadastradoError` e levantado (nada e inventado);
* duplicacoes sao impedidas pela restricao unica e tratadas de forma
  idempotente (conflito de concorrencia nao gera erro nem linha duplicada);
* falhas de banco propagam a excecao para o chamador negar a operacao.
"""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pipeline_dados.banco_dados import Ativo, TipoAtivo
from pipeline_dados.conexao import obter_session_factory
from pipeline_dados.modelos_ativos import AtivoAcompanhado
from pipeline_dados.modelos_usuarios import STATUS_APROVADO, Usuario

logger = logging.getLogger("robo.favoritos")

MAPA_TIPO = {"fii": TipoAtivo.FII, "acao": TipoAtivo.ACAO}
MAPA_TIPO_INVERSO = {TipoAtivo.FII: "fii", TipoAtivo.ACAO: "acao"}


class AtivoNaoCadastradoError(Exception):
    """Levantado quando o ticker informado nao existe na tabela ``ativos``."""


class FavoritoDTO:
    """Representacao simples (desanexada) de um favorito."""

    __slots__ = ("id", "usuario_id", "ativo_id", "ticker", "tipo", "criado_em")

    def __init__(self, id, usuario_id, ativo_id, ticker, tipo, criado_em):
        self.id = id
        self.usuario_id = usuario_id
        self.ativo_id = ativo_id
        self.ticker = ticker
        self.tipo = tipo
        self.criado_em = criado_em

    def __repr__(self):  # pragma: no cover - diagnostico
        return f"FavoritoDTO(ticker={self.ticker!r}, tipo={self.tipo!r})"


class RepositorioFavoritos:
    def __init__(self, session_factory=None):
        self._session_factory = session_factory

    def _nova_sessao(self):
        factory = self._session_factory or obter_session_factory()
        return factory()

    @staticmethod
    def _normalizar_id(valor):
        if valor is None:
            return None
        try:
            return int(str(valor).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalizar_ticker(ticker):
        return str(ticker or "").strip().upper() or None

    @staticmethod
    def _tipo_str(tipo_enum):
        return MAPA_TIPO_INVERSO.get(tipo_enum, str(tipo_enum))

    def resolver_ativo(self, ticker):
        """Retorna ``(ativo_id, ticker, tipo)`` do ativo cadastrado ou ``None``.

        Nao cria ativos: se o ticker nao constar na tabela ``ativos``, retorna
        ``None`` sem inventar registros financeiros ou cadastrais.
        """
        chave = self._normalizar_ticker(ticker)
        if chave is None:
            return None
        session = self._nova_sessao()
        try:
            ativo = session.query(Ativo).filter(Ativo.ticker == chave).first()
            if ativo is None:
                return None
            return (ativo.id, ativo.ticker, self._tipo_str(ativo.tipo))
        finally:
            session.close()

    def esta_acompanhado(self, usuario_id, ativo_id):
        usuario = self._normalizar_id(usuario_id)
        ativo = self._normalizar_id(ativo_id)
        if usuario is None or ativo is None:
            return False
        session = self._nova_sessao()
        try:
            return (
                session.query(AtivoAcompanhado)
                .filter(
                    AtivoAcompanhado.usuario_id == usuario,
                    AtivoAcompanhado.ativo_id == ativo,
                )
                .first()
                is not None
            )
        finally:
            session.close()

    def listar(self, usuario_id, tipo=None):
        """Lista os favoritos de um usuario, opcionalmente filtrando por tipo."""
        usuario = self._normalizar_id(usuario_id)
        if usuario is None:
            return []
        session = self._nova_sessao()
        try:
            consulta = (
                session.query(AtivoAcompanhado, Ativo)
                .join(Ativo, AtivoAcompanhado.ativo_id == Ativo.id)
                .filter(AtivoAcompanhado.usuario_id == usuario)
            )
            if tipo is not None:
                tipo_enum = MAPA_TIPO.get(str(tipo).lower())
                if tipo_enum is None:
                    return []
                consulta = consulta.filter(Ativo.tipo == tipo_enum)
            consulta = consulta.order_by(Ativo.ticker.asc())
            return [
                FavoritoDTO(
                    id=vinculo.id,
                    usuario_id=vinculo.usuario_id,
                    ativo_id=vinculo.ativo_id,
                    ticker=ativo.ticker,
                    tipo=self._tipo_str(ativo.tipo),
                    criado_em=vinculo.criado_em,
                )
                for vinculo, ativo in consulta.all()
            ]
        finally:
            session.close()

    def listar_ids_ativos_acompanhados(self):
        """Ids distintos de ativos que algum usuario acompanha.

        Nao inventa ativo: so devolve ids com vinculo e cadastro em ``ativos``.
        Lista vazia nao e zero de mercado.
        """
        session = self._nova_sessao()
        try:
            linhas = (
                session.query(AtivoAcompanhado.ativo_id)
                .join(Ativo, AtivoAcompanhado.ativo_id == Ativo.id)
                .distinct()
                .all()
            )
            return [linha[0] for linha in linhas]
        finally:
            session.close()

    def listar_catalogo(self, tipo):
        """Tickers cadastrados na tabela ``ativos`` para o tipo informado."""
        tipo_enum = MAPA_TIPO.get(str(tipo).lower())
        if tipo_enum is None:
            return []
        session = self._nova_sessao()
        try:
            ativos = (
                session.query(Ativo)
                .filter(Ativo.tipo == tipo_enum)
                .order_by(Ativo.ticker.asc())
                .all()
            )
            return [ativo.ticker for ativo in ativos]
        finally:
            session.close()

    def usuarios_que_acompanham(self, ativo_id):
        """Usuários com cadastro aprovado e conta ativa que seguem o ativo.

        Usado pela distribuição individual de documentos. Pendentes,
        rejeitados, suspensos e inativos são excluídos na própria consulta.
        """
        ativo = self._normalizar_id(ativo_id)
        if ativo is None:
            return []
        session = self._nova_sessao()
        try:
            usuarios = (
                session.query(Usuario)
                .join(
                    AtivoAcompanhado,
                    AtivoAcompanhado.usuario_id == Usuario.id,
                )
                .filter(
                    AtivoAcompanhado.ativo_id == ativo,
                    Usuario.status_cadastro == STATUS_APROVADO,
                    Usuario.ativo.is_(True),
                )
                .order_by(Usuario.id.asc())
                .all()
            )
            return [usuario.para_dto() for usuario in usuarios]
        finally:
            session.close()

    def listar_disponiveis(self, usuario_id, tipo):
        """Tickers do tipo informado que ainda nao sao acompanhados pelo usuario."""
        usuario = self._normalizar_id(usuario_id)
        tipo_enum = MAPA_TIPO.get(str(tipo).lower())
        if usuario is None or tipo_enum is None:
            return []
        session = self._nova_sessao()
        try:
            ja_acompanhados = select(AtivoAcompanhado.ativo_id).where(
                AtivoAcompanhado.usuario_id == usuario
            )
            ativos = (
                session.query(Ativo)
                .filter(Ativo.tipo == tipo_enum)
                .filter(~Ativo.id.in_(ja_acompanhados))
                .order_by(Ativo.ticker.asc())
                .all()
            )
            return [ativo.ticker for ativo in ativos]
        finally:
            session.close()

    def adicionar(self, usuario_id, ticker):
        """Adiciona um ativo existente aos favoritos do usuario.

        Retorna ``(dto, criado)``. Levanta :class:`AtivoNaoCadastradoError` se o
        ticker nao existir em ``ativos``. Duplicacoes (inclusive por concorrencia)
        sao tratadas de forma idempotente: ``criado=False`` e nenhuma linha
        duplicada e criada.
        """
        usuario = self._normalizar_id(usuario_id)
        if usuario is None:
            raise ValueError("usuario_id invalido para favoritar")

        resolvido = self.resolver_ativo(ticker)
        if resolvido is None:
            raise AtivoNaoCadastradoError(str(ticker))

        ativo_id, ticker_normalizado, tipo_str = resolvido

        existente = self._obter_vinculo(usuario, ativo_id)
        if existente is not None:
            return existente, False

        session = self._nova_sessao()
        try:
            vinculo = AtivoAcompanhado(
                usuario_id=usuario,
                ativo_id=ativo_id,
                criado_em=datetime.now(),
            )
            session.add(vinculo)
            try:
                session.commit()
            except IntegrityError:
                # Corrida: outra transacao criou o mesmo vinculo.
                session.rollback()
                existente = self._obter_vinculo(usuario, ativo_id)
                return existente, False
            session.refresh(vinculo)
            return (
                FavoritoDTO(
                    id=vinculo.id,
                    usuario_id=vinculo.usuario_id,
                    ativo_id=vinculo.ativo_id,
                    ticker=ticker_normalizado,
                    tipo=tipo_str,
                    criado_em=vinculo.criado_em,
                ),
                True,
            )
        finally:
            session.close()

    def remover(self, usuario_id, ticker):
        """Remove o vinculo do usuario com o ativo existente.

        Retorna True se algo foi removido, False caso o vinculo (ou o ativo) nao
        exista. Somente o vinculo em ``ativos_acompanhados`` e removido; nunca o
        registro em ``ativos``.
        """
        usuario = self._normalizar_id(usuario_id)
        if usuario is None:
            return False
        resolvido = self.resolver_ativo(ticker)
        if resolvido is None:
            return False
        ativo_id = resolvido[0]

        session = self._nova_sessao()
        try:
            vinculo = (
                session.query(AtivoAcompanhado)
                .filter(
                    AtivoAcompanhado.usuario_id == usuario,
                    AtivoAcompanhado.ativo_id == ativo_id,
                )
                .first()
            )
            if vinculo is None:
                return False
            session.delete(vinculo)
            session.commit()
            return True
        finally:
            session.close()

    def _obter_vinculo(self, usuario_id, ativo_id):
        session = self._nova_sessao()
        try:
            vinculo = (
                session.query(AtivoAcompanhado)
                .filter(
                    AtivoAcompanhado.usuario_id == usuario_id,
                    AtivoAcompanhado.ativo_id == ativo_id,
                )
                .first()
            )
            if vinculo is None:
                return None
            ativo = session.get(Ativo, ativo_id)
            return FavoritoDTO(
                id=vinculo.id,
                usuario_id=vinculo.usuario_id,
                ativo_id=vinculo.ativo_id,
                ticker=ativo.ticker if ativo else None,
                tipo=self._tipo_str(ativo.tipo) if ativo else None,
                criado_em=vinculo.criado_em,
            )
        finally:
            session.close()
