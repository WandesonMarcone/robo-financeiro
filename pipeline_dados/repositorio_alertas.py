"""Leitura dos eventos em ``alertas_eventos`` (somente consulta).

Nao cria tabelas, nao aplica migracoes e nao grava nada. Nao toca em
``notificacoes`` nem em ``preferencias_usuarios`` (vocabulario ainda
desconhecido). Nao interpreta ``telegram_enviado`` como entrega ao usuario.

Regras:
* consulta apenas pelos ``ativo_id`` informados (favoritos do chamador);
* lista vazia de ids nao abre sessao;
* ausencia de evento nao vira zero inventado: devolve lista vazia;
* falhas de banco propagam a excecao para o chamador negar a operacao.
"""

from pipeline_dados.banco_dados import Ativo
from pipeline_dados.conexao import obter_session_factory
from pipeline_dados.modelos_alertas import AlertaEvento

LIMITE_PADRAO = 10
LIMITE_MAXIMO = 50


class AlertaEventoDTO:
    """Representacao simples (desanexada) de um evento de alerta."""

    __slots__ = (
        "id",
        "ativo_id",
        "ticker",
        "tipo_alerta",
        "tipo_ativo",
        "indicador",
        "valor_anterior",
        "valor_atual",
        "variacao_percentual",
        "regra",
        "motivo",
        "severidade",
        "recomendacao",
        "origem",
        "data_referencia",
        "data_evento",
        "telegram_enviado",
    )

    def __init__(
        self,
        id,
        ativo_id,
        ticker,
        tipo_alerta,
        tipo_ativo,
        indicador,
        valor_anterior,
        valor_atual,
        variacao_percentual,
        regra,
        motivo,
        severidade,
        recomendacao,
        origem,
        data_referencia,
        data_evento,
        telegram_enviado,
    ):
        self.id = id
        self.ativo_id = ativo_id
        self.ticker = ticker
        self.tipo_alerta = tipo_alerta
        self.tipo_ativo = tipo_ativo
        self.indicador = indicador
        self.valor_anterior = valor_anterior
        self.valor_atual = valor_atual
        self.variacao_percentual = variacao_percentual
        self.regra = regra
        self.motivo = motivo
        self.severidade = severidade
        self.recomendacao = recomendacao
        self.origem = origem
        self.data_referencia = data_referencia
        self.data_evento = data_evento
        self.telegram_enviado = telegram_enviado

    def __repr__(self):  # pragma: no cover - diagnostico
        return (
            f"AlertaEventoDTO(ticker={self.ticker!r}, "
            f"indicador={self.indicador!r}, regra={self.regra!r})"
        )


class RepositorioAlertas:
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
    def _normalizar_limite(limite):
        try:
            valor = int(limite)
        except (TypeError, ValueError):
            return LIMITE_PADRAO
        if valor < 1:
            return LIMITE_PADRAO
        if valor > LIMITE_MAXIMO:
            return LIMITE_MAXIMO
        return valor

    @staticmethod
    def _para_dto(evento, ativo):
        return AlertaEventoDTO(
            id=evento.id,
            ativo_id=evento.ativo_id,
            ticker=ativo.ticker,
            tipo_alerta=evento.tipo_alerta,
            tipo_ativo=evento.tipo_ativo,
            indicador=evento.indicador,
            valor_anterior=evento.valor_anterior,
            valor_atual=evento.valor_atual,
            variacao_percentual=evento.variacao_percentual,
            regra=evento.regra,
            motivo=evento.motivo,
            severidade=evento.severidade,
            recomendacao=evento.recomendacao,
            origem=evento.origem,
            data_referencia=evento.data_referencia,
            data_evento=evento.data_evento,
            telegram_enviado=evento.telegram_enviado,
        )

    def listar_por_ativos(self, ativo_ids, limite=LIMITE_PADRAO):
        """Eventos dos ativos informados, mais recentes primeiro.

        Nao inventa ativos: ids invalidos sao ignorados; conjunto vazio
        devolve ``[]`` sem consultar o banco.
        """
        ids = []
        vistos = set()
        for valor in ativo_ids or []:
            normalizado = self._normalizar_id(valor)
            if normalizado is None or normalizado in vistos:
                continue
            vistos.add(normalizado)
            ids.append(normalizado)
        if not ids:
            return []
        session = self._nova_sessao()
        try:
            linhas = (
                session.query(AlertaEvento, Ativo)
                .join(Ativo, AlertaEvento.ativo_id == Ativo.id)
                .filter(AlertaEvento.ativo_id.in_(ids))
                .order_by(AlertaEvento.data_evento.desc())
                .limit(self._normalizar_limite(limite))
                .all()
            )
            return [self._para_dto(evento, ativo) for evento, ativo in linhas]
        finally:
            session.close()
