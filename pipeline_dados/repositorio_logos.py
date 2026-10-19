"""Persistencia do cache de ``file_id`` de logos do Telegram.

Este repositorio e deliberadamente separado do cache local de URLs do
``services.logo_service``:

* o cache local (memoria) guarda URLs resolvidas e resultados negativos de rede;
* este repositorio guarda o ``file_id`` devolvido pelo Telegram, que sobrevive a
  reinicializacoes do bot e e reutilizado em ``sendPhoto``/``editMessageMedia``;
* o vinculo e preferencialmente por EMPRESA. Assim PETR3 e PETR4 compartilham a
  mesma logo, mas continuam com dados financeiros independentes em ``ativos``;
* a chave canonica considera a empresa e o grupo de identidade visual, nao
  apenas o ticker consultado.

Cache negativo: uma falha limpa o ``file_id`` antigo, grava ``status='negativo'``
e define ``expira_em``. Ate expirar, o ``file_id`` nao e reutilizado; depois
disso uma nova tentativa e permitida.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from pipeline_dados.conexao import obter_session_factory
from pipeline_dados.identidade_visual import (
    CANONICO_VISUAL,
    tickers_equivalentes,
)
from pipeline_dados.modelos_catalogo import (
    STATUS_LOGO_ATIVO,
    STATUS_LOGO_NEGATIVO,
    CacheLogoTelegram,
)
from pipeline_dados.repositorio_catalogo import (
    RepositorioCatalogo,
    normalizar_ticker,
)

logger = logging.getLogger("robo.logos.persistencia")

TTL_NEGATIVO_PADRAO_SEGUNDOS = 60 * 60


class CacheLogoDTO:
    __slots__ = (
        "id",
        "chave",
        "empresa_id",
        "file_id",
        "status",
        "falhas",
        "erro",
        "expira_em",
        "url_origem",
    )

    def __init__(self, id, chave, empresa_id, file_id, status, falhas, erro,
                 expira_em, url_origem):
        self.id = id
        self.chave = chave
        self.empresa_id = empresa_id
        self.file_id = file_id
        self.status = status
        self.falhas = falhas
        self.erro = erro
        self.expira_em = expira_em
        self.url_origem = url_origem


class RepositorioLogos:
    def __init__(self, session_factory=None, ttl_negativo_segundos=None,
                 catalogo=None):
        self._session_factory = session_factory
        self._ttl_negativo = (
            ttl_negativo_segundos
            if ttl_negativo_segundos is not None
            else TTL_NEGATIVO_PADRAO_SEGUNDOS
        )
        self._catalogo = catalogo or RepositorioCatalogo(session_factory)

    def _nova_sessao(self):
        factory = self._session_factory or obter_session_factory()
        return factory()

    # ------------------------------------------------------------------
    # Identidade canonica (empresa + grupo visual)
    # ------------------------------------------------------------------

    @staticmethod
    def _preferida(chave, chaves):
        """Escolhe uma chave estavel para o registro persistente.

        Se o grupo visual tiver um canonico explicito (PETR4), ele vence. Caso
        contrario, usa a ordem lexicografica para que todos os tickers da mesma
        empresa cheguem a MESMA chave, independentemente de qual iniciou o
        vinculo.
        """
        for candidata in chaves:
            if CANONICO_VISUAL.get(candidata) == candidata:
                return candidata
        if chaves:
            return sorted(chaves)[0]
        return chave

    def _resolver_identidade(self, ticker):
        """Retorna ``(empresa_id, chave_preferida, chaves_candidatas)``."""
        chave = normalizar_ticker(ticker)
        if not chave:
            return None, "", []

        chaves = []
        for candidata in [chave, *tickers_equivalentes(chave)]:
            candidata = normalizar_ticker(candidata)
            if candidata and candidata not in chaves:
                chaves.append(candidata)

        empresa_id = None
        for candidata in chaves:
            try:
                empresa_id = self._catalogo.obter_empresa_id_por_ticker(
                    candidata
                )
            except Exception:
                logger.debug(
                    "Catalogo indisponivel ao resolver empresa de %s",
                    candidata,
                    exc_info=True,
                )
                empresa_id = None
            if empresa_id is not None:
                break

        if empresa_id is not None:
            try:
                tickers_empresa = self._catalogo.obter_tickers_da_empresa(
                    empresa_id
                )
            except Exception:
                logger.debug(
                    "Nao foi possivel listar tickers da empresa %s",
                    empresa_id,
                    exc_info=True,
                )
                tickers_empresa = []
            for candidata in tickers_empresa:
                candidata = normalizar_ticker(candidata)
                if candidata and candidata not in chaves:
                    chaves.append(candidata)

        return empresa_id, self._preferida(chave, chaves), chaves

    def _empresa_id(self, ticker):
        return self._resolver_identidade(ticker)[0]

    def chave_canonica(self, ticker):
        """Chave canonica de identidade visual (empresa quando conhecida)."""
        _, preferida, _ = self._resolver_identidade(ticker)
        return preferida or normalizar_ticker(ticker)

    # ------------------------------------------------------------------
    # Consulta/upsert
    # ------------------------------------------------------------------

    @staticmethod
    def _consultar(session, empresa_id, chaves):
        consulta = session.query(CacheLogoTelegram)
        if empresa_id is not None:
            registro = (
                consulta.filter(CacheLogoTelegram.empresa_id == empresa_id)
                .order_by(
                    CacheLogoTelegram.atualizado_em.desc(),
                    CacheLogoTelegram.id.desc(),
                )
                .first()
            )
            if registro is not None:
                return registro
        if chaves:
            return (
                consulta.filter(CacheLogoTelegram.chave.in_(chaves))
                .order_by(
                    CacheLogoTelegram.atualizado_em.desc(),
                    CacheLogoTelegram.id.desc(),
                )
                .first()
            )
        return None

    @staticmethod
    def _dto(registro):
        if registro is None:
            return None
        return CacheLogoDTO(
            id=registro.id,
            chave=registro.chave,
            empresa_id=registro.empresa_id,
            file_id=registro.file_id,
            status=registro.status,
            falhas=registro.falhas or 0,
            erro=registro.erro,
            expira_em=registro.expira_em,
            url_origem=registro.url_origem,
        )

    @staticmethod
    def _aplicar_file_id(registro, empresa_id, file_id, url_origem,
                         file_unique_id):
        if empresa_id is not None:
            registro.empresa_id = empresa_id
        registro.file_id = str(file_id)
        if file_unique_id:
            registro.file_unique_id = str(file_unique_id)
        if url_origem:
            registro.url_origem = str(url_origem)[:500]
        registro.status = STATUS_LOGO_ATIVO
        registro.falhas = 0
        registro.erro = None
        registro.expira_em = None

    @staticmethod
    def _aplicar_falha(registro, empresa_id, erro, url_origem, expira_em):
        if empresa_id is not None:
            registro.empresa_id = empresa_id
        # O file_id anterior pode estar invalido; nao o reutilizamos ate uma
        # nova tentativa bem-sucedida.
        registro.file_id = None
        registro.file_unique_id = None
        registro.status = STATUS_LOGO_NEGATIVO
        registro.falhas = (registro.falhas or 0) + 1
        registro.erro = str(erro or "falha no envio da logo")[:500]
        if url_origem:
            registro.url_origem = str(url_origem)[:500]
        registro.expira_em = expira_em

    def obter_registro(self, ticker):
        chave = normalizar_ticker(ticker)
        if not chave:
            return None
        empresa_id, _, chaves = self._resolver_identidade(chave)
        session = self._nova_sessao()
        try:
            return self._dto(
                self._consultar(session, empresa_id, chaves)
            )
        finally:
            session.close()

    def obter_file_id(self, ticker, agora=None):
        registro = self.obter_registro(ticker)
        if registro is None:
            return None
        agora = agora or datetime.utcnow()
        if registro.status != STATUS_LOGO_ATIVO or not registro.file_id:
            return None
        if registro.expira_em is not None and registro.expira_em <= agora:
            return None
        return registro.file_id

    def registrar_file_id(self, ticker, file_id, url_origem=None,
                          file_unique_id=None):
        chave = normalizar_ticker(ticker)
        if not chave or not file_id:
            return None
        empresa_id, preferida, chaves = self._resolver_identidade(chave)
        session = self._nova_sessao()
        try:
            registro = self._consultar(session, empresa_id, chaves)
            if registro is None:
                registro = CacheLogoTelegram(
                    chave=preferida or chave, empresa_id=empresa_id
                )
                session.add(registro)
            self._aplicar_file_id(
                registro, empresa_id, file_id, url_origem, file_unique_id
            )
            try:
                session.commit()
            except IntegrityError:
                # Corrida entre tickers da mesma empresa ou entre empresas
                # distintas: reconsulta pelo vinculo e atualiza a linha vencedora
                # em vez de derrubar o envio da logo.
                session.rollback()
                registro = self._consultar(session, empresa_id, chaves)
                if registro is None:
                    raise
                self._aplicar_file_id(
                    registro, empresa_id, file_id, url_origem,
                    file_unique_id,
                )
                session.commit()
            return str(file_id)
        finally:
            session.close()

    def registrar_falha(self, ticker, erro=None, url_origem=None,
                        ttl_segundos=None, agora=None):
        chave = normalizar_ticker(ticker)
        if not chave:
            return None
        empresa_id, preferida, chaves = self._resolver_identidade(chave)
        ttl = self._ttl_negativo if ttl_segundos is None else ttl_segundos
        agora = agora or datetime.utcnow()
        expira_em = agora + timedelta(seconds=ttl)
        session = self._nova_sessao()
        try:
            registro = self._consultar(session, empresa_id, chaves)
            if registro is None:
                registro = CacheLogoTelegram(
                    chave=preferida or chave, empresa_id=empresa_id
                )
                session.add(registro)
            self._aplicar_falha(
                registro, empresa_id, erro, url_origem, expira_em
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                registro = self._consultar(session, empresa_id, chaves)
                if registro is None:
                    raise
                self._aplicar_falha(
                    registro, empresa_id, erro, url_origem, expira_em
                )
                session.commit()
            return self._dto(registro)
        finally:
            session.close()

    def limpar(self, ticker=None):
        """Remove registros de cache (operacao administrativa/testes)."""
        session = self._nova_sessao()
        try:
            consulta = session.query(CacheLogoTelegram)
            if ticker is not None:
                chave = normalizar_ticker(ticker)
                empresa_id, _, chaves = self._resolver_identidade(chave)
                filtros = []
                if chaves:
                    filtros.append(CacheLogoTelegram.chave.in_(chaves))
                if empresa_id is not None:
                    filtros.append(
                        CacheLogoTelegram.empresa_id == empresa_id
                    )
                if filtros:
                    consulta = consulta.filter(or_(*filtros))
                else:  # pragma: no cover - ticker vazio ja tratado acima
                    consulta = consulta.filter(
                        CacheLogoTelegram.chave == chave
                    )
            total = consulta.delete(synchronize_session=False)
            session.commit()
            return total
        finally:
            session.close()


__all__ = [
    "CacheLogoDTO",
    "RepositorioLogos",
    "TTL_NEGATIVO_PADRAO_SEGUNDOS",
]
