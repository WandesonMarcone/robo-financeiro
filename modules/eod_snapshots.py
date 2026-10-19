"""Leitura do catalogo completo das abas e montagem dos payloads EOD.

Nao coleta fontes externas. Nao grava no Google Sheets. A persistencia no
Neon e opcional, isolada e desligada por padrao (``EOD_SNAPSHOTS``).
"""

import logging
import os
from datetime import date, datetime

import pytz

import config
from modules.utils import converter_numero, eh_valido

logger = logging.getLogger("robo.eod")

ABA_ACOES = "BD_Acoes"
ABA_FIIS = "BD_FIIs"
FUSO_SP = "America/Sao_Paulo"
FONTE_SHEETS = "Google Sheets"

# Indices 0-based das abas, alinhados ao scraper (A=0).
# Colunas sem correspondente no Neon nao entram no mapa.
MAPA_ACOES = {
    "preco": 2,
    "dy": 3,
    "pl": 5,
    "pvp": 6,
    "p_ativo": 7,
    "marg_bruta": 8,
    "marg_ebit": 9,
    "marg_liquida": 10,
    "p_ebit": 11,
    "ev_ebit": 12,
    "div_liq_patrimonio": 13,
    "psr": 15,
    "p_cap_giro": 16,
    "p_at_circ_liq": 17,
    "liq_corrente": 18,
    "roe": 19,
    "roa": 20,
    "roic": 21,
    "cagr_rec_5a": 25,
    "liq_media": 27,
    "vpa": 28,
    "lpa": 29,
    "peg_ratio": 30,
    "valor_mercado": 31,
}

MAPA_FIIS = {
    "preco": 3,
    "pvp": 5,
    "dy": 6,
    "qtd_imoveis": 8,
    "liquidez": 12,
    "vpa": 14,
    "lucro_12m": 15,
    "dividendo_mensal": 16,
}

CAMPOS_PRECO_POSITIVO = frozenset({"preco", "pvp"})
CAMPOS_INTEIRO = frozenset({"qtd_imoveis"})


def data_coleta_naive(agora_dt):
    """Timestamp de coleta sem tz, alinhado a coluna timestamp without time zone."""
    if agora_dt is None:
        return datetime.utcnow()
    if getattr(agora_dt, "tzinfo", None) is not None:
        return agora_dt.replace(tzinfo=None)
    return agora_dt


def eod_habilitado():
    return str(os.environ.get("EOD_SNAPSHOTS", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def data_referencia_eod(agora_dt=None):
    """Data civil em America/Sao_Paulo. Nao e fechamento oficial B3."""
    if agora_dt is None:
        agora_dt = datetime.now(pytz.timezone(FUSO_SP))
    elif getattr(agora_dt, "tzinfo", None) is None:
        agora_dt = pytz.timezone(FUSO_SP).localize(agora_dt)
    else:
        agora_dt = agora_dt.astimezone(pytz.timezone(FUSO_SP))
    return agora_dt.date() if hasattr(agora_dt, "date") else date.today()


def _celula(linha, indice):
    if indice < 0 or indice >= len(linha):
        return None
    return linha[indice]


def _numero_ou_nulo(bruto, exigir_positivo=False):
    numero = converter_numero(bruto)
    if not eh_valido(numero):
        return None
    if exigir_positivo and not (numero > 0):
        return None
    return numero


def _inteiro_ou_nulo(bruto):
    numero = _numero_ou_nulo(bruto)
    if numero is None:
        return None
    return int(round(numero))


def _indicadores_da_linha(linha, mapa):
    saida = {}
    for campo, indice in mapa.items():
        bruto = _celula(linha, indice)
        if campo in CAMPOS_INTEIRO:
            valor = _inteiro_ou_nulo(bruto)
        else:
            valor = _numero_ou_nulo(
                bruto, exigir_positivo=(campo in CAMPOS_PRECO_POSITIVO)
            )
        if valor is not None:
            saida[campo] = valor
    return saida


def _payload_meta(ticker, agora_dt):
    return {
        "ticker": ticker,
        "data_coleta": data_coleta_naive(agora_dt),
        "fonte": FONTE_SHEETS,
        "url_origem": getattr(config, "SPREADSHEET_URL", None),
        "fonte_primaria": FONTE_SHEETS,
    }


def _ticker_da_linha(linha):
    if not linha:
        return ""
    bruto = str(linha[0]).strip().upper()
    if not bruto:
        return ""
    if bruto.replace(",", "").replace(".", "").isnumeric():
        return ""
    return bruto


def montar_payloads_acoes(linhas, agora_dt=None):
    payloads = []
    for linha in linhas[1:]:
        ticker = _ticker_da_linha(linha)
        if not ticker:
            continue
        payload = _payload_meta(ticker, agora_dt)
        payload.update(_indicadores_da_linha(linha, MAPA_ACOES))
        payloads.append(payload)
    return payloads


def montar_payloads_fiis(linhas, agora_dt=None):
    payloads = []
    for linha in linhas[1:]:
        ticker = _ticker_da_linha(linha)
        if not ticker:
            continue
        payload = _payload_meta(ticker, agora_dt)
        payload.update(_indicadores_da_linha(linha, MAPA_FIIS))
        payloads.append(payload)
    return payloads


def _ler_aba(planilha, nome):
    aba = planilha.worksheet(nome)
    return aba.get_all_values()


def persistir_catalogo_sheets(planilha, agora_dt=None, session_factory=None):
    """Le o catalogo completo das abas e tenta gravar no Neon.

    Qualquer falha e registrada e devolvida; nao propaga para o chamador.
    """
    try:
        linhas_acoes = _ler_aba(planilha, ABA_ACOES)
        linhas_fiis = _ler_aba(planilha, ABA_FIIS)
        data_ref = data_referencia_eod(agora_dt)
        payloads_acoes = montar_payloads_acoes(linhas_acoes, agora_dt)
        payloads_fiis = montar_payloads_fiis(linhas_fiis, agora_dt)
        from pipeline_dados.repositorio_snapshots import persistir_snapshots

        resumo = persistir_snapshots(
            payloads_acoes,
            payloads_fiis,
            data_ref,
            session_factory=session_factory,
        )
        logger.info(
            "EOD snapshots: acoes=%s fiis=%s omitidos_sem_ativo=%s "
            "omitidos_sem_dados=%s data=%s",
            resumo.get("acoes_gravadas"),
            resumo.get("fiis_gravados"),
            resumo.get("omitidos_sem_ativo"),
            resumo.get("omitidos_sem_dados"),
            resumo.get("data_referencia"),
        )
        return resumo
    except Exception as exc:
        nome = type(exc).__name__
        if nome == "BancoNaoConfiguradoError":
            logger.warning(
                "EOD snapshots: DATABASE_URL ausente; persistencia omitida"
            )
            return None
        logger.error(
            "EOD snapshots: falha na persistencia (Sheets nao afetado): %s",
            nome,
        )
        return None


def tentar_persistir_eod(planilha, agora_dt=None, session_factory=None):
    """Ponto unico chamado pelo app. No-op se a flag nao estiver ligada."""
    if not eod_habilitado():
        return None
    return persistir_catalogo_sheets(
        planilha, agora_dt=agora_dt, session_factory=session_factory
    )
