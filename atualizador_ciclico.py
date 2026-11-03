"""Atualização cíclica, silenciosa e limitada de ativos da planilha.

Não envia Telegram ou cria alertas de mercado. O estado na aba Controle_Robo
só avança depois que as respectivas células de dados foram gravadas.
"""
from __future__ import annotations

import argparse
import datetime
import time

import pytz

import config
from modules.lotes_atualizacao import (
    atualizar_pendentes,
    distribuir_limite,
    normalizar_tickers,
    selecionar_com_retentativas,
)
from modules.scraper_acoes import rodar_garimpo_acoes
from modules.scraper_fiis import rodar_garimpo_fiis
from modules.utils import conectar_gspread


CHAVE_ESTADO = "atualizacao_ciclica_v1"
ABA_CONTROLE = "Controle_Robo"
CABECALHO_CONTROLE = [
    "chave",
    "cursor_acoes",
    "cursor_fiis",
    "pendentes_acoes",
    "pendentes_fiis",
    "atualizado_em",
]


def _tickers(linhas):
    return [str(linha[0]).strip().upper() for linha in linhas[1:] if linha and str(linha[0]).strip()]


def _controle(planilha):
    try:
        aba = planilha.worksheet(ABA_CONTROLE)
    except Exception:
        aba = planilha.add_worksheet(title=ABA_CONTROLE, rows=10, cols=6)
        aba.append_row(CABECALHO_CONTROLE)

    valores = aba.get_all_values()
    if not valores:
        aba.append_row(CABECALHO_CONTROLE)
        valores = [CABECALHO_CONTROLE]
    elif len(valores[0]) < len(CABECALHO_CONTROLE):
        aba.update("A1:F1", [CABECALHO_CONTROLE])

    for indice, linha in enumerate(valores[1:], start=2):
        if linha and linha[0] == CHAVE_ESTADO:
            return aba, indice, linha + [""] * (6 - len(linha))

    aba.append_row([CHAVE_ESTADO, "0", "0", "", "", ""])
    return aba, len(valores) + 1, [CHAVE_ESTADO, "0", "0", "", "", ""]


def _inteiro(valor):
    try:
        return max(0, int(valor))
    except (TypeError, ValueError):
        return 0


def _lista(valor):
    return normalizar_tickers(str(valor or "").split(","))


def _texto_lista(valores):
    return ",".join(normalizar_tickers(valores))


def _gravar_estado(aba, linha, cursor_acoes, cursor_fiis, pendentes_acoes, pendentes_fiis, agora_sp):
    aba.update(
        f"B{linha}:F{linha}",
        [[
            str(cursor_acoes),
            str(cursor_fiis),
            _texto_lista(pendentes_acoes),
            _texto_lista(pendentes_fiis),
            agora_sp,
        ]],
    )


def _persistir_lote(aba, atualizacoes, tipo):
    if not atualizacoes:
        print(f"Lote {tipo}: sem dados válidos; estado preservado para nova tentativa.")
        return False
    aba.batch_update(atualizacoes)
    print(f"Lote {tipo}: {len(atualizacoes)} células gravadas.")
    return True


def executar(limite_total=16, orcamento_segundos=540, pausa_segundos=2.0, planilha=None, clock=time.monotonic, sleep=time.sleep, ticker=None):
    if not 1 <= limite_total <= 16:
        raise ValueError("limite_total_invalido")
    if not 60 <= orcamento_segundos <= 540:
        raise ValueError("orcamento_invalido")
    if not 0 <= pausa_segundos <= 10:
        raise ValueError("pausa_invalida")

    inicio = clock()
    prazo = inicio + orcamento_segundos
    if planilha is None:
        gc = conectar_gspread()
        planilha = gc.open_by_url(config.SPREADSHEET_URL)

    aba_acoes = planilha.worksheet("BD_Acoes")
    aba_fiis = planilha.worksheet("BD_FIIs")
    acoes = _tickers(aba_acoes.get_all_values())
    fiis = _tickers(aba_fiis.get_all_values())
    controle, linha_estado, estado = _controle(planilha)

    cursor_acoes = _inteiro(estado[1])
    cursor_fiis = _inteiro(estado[2])
    pendentes_acoes = _lista(estado[3])
    pendentes_fiis = _lista(estado[4])
    ticker_isolado = str(ticker or "").strip().upper()
    if ticker_isolado:
        if ticker_isolado in acoes:
            lote_acoes, lote_fiis = [ticker_isolado], []
        elif ticker_isolado in fiis:
            lote_acoes, lote_fiis = [], [ticker_isolado]
        else:
            raise ValueError(f"ticker_nao_encontrado:{ticker_isolado}")
        proximo_acoes, proximo_fiis = cursor_acoes, cursor_fiis
    else:
        limite_acoes, limite_fiis = distribuir_limite(limite_total, len(acoes), len(fiis))
        lote_acoes, proximo_acoes, pendentes_acoes = selecionar_com_retentativas(
            acoes, cursor_acoes, limite_acoes, pendentes_acoes
        )
        lote_fiis, proximo_fiis, pendentes_fiis = selecionar_com_retentativas(
            fiis, cursor_fiis, limite_fiis, pendentes_fiis
        )

    fuso = pytz.timezone("America/Sao_Paulo")
    agora_dt = datetime.datetime.now(fuso)
    agora_sp = agora_dt.strftime("%d/%m %H:%M")
    print(
        f"Atualização cíclica: teto={limite_total}; "
        f"ticker={ticker_isolado or 'lote'}; "
        f"ações={len(lote_acoes)}; FIIs={len(lote_fiis)}; "
        f"orçamento={orcamento_segundos}s."
    )

    atualizacoes_fiis, digest_fiis, destino_fiis = rodar_garimpo_fiis(
        planilha, agora_dt, agora_sp, fuso,
        tickers_lote=lote_fiis,
        pausa_entre_ativos=pausa_segundos,
        prazo_monotonic=prazo,
        clock=clock,
        sleep=sleep,
    )
    sucesso_fiis = _persistir_lote(destino_fiis, atualizacoes_fiis, "FIIs")
    if sucesso_fiis:
        tentados = digest_fiis.get("tentados") or []
        pendentes_fiis = atualizar_pendentes(
            pendentes_fiis, tentados, digest_fiis.get("falhas") or []
        )
        if len(tentados) == len(lote_fiis):
            cursor_fiis = proximo_fiis
        _gravar_estado(
            controle, linha_estado, cursor_acoes, cursor_fiis,
            pendentes_acoes, pendentes_fiis, agora_sp,
        )

    atualizacoes_acoes, digest_acoes, destino_acoes = rodar_garimpo_acoes(
        planilha, agora_dt, agora_sp, fuso,
        tickers_lote=lote_acoes,
        pausa_entre_ativos=pausa_segundos,
        prazo_monotonic=prazo,
        clock=clock,
        sleep=sleep,
    )
    sucesso_acoes = _persistir_lote(destino_acoes, atualizacoes_acoes, "ações")
    if sucesso_acoes:
        tentados = digest_acoes.get("tentados") or []
        pendentes_acoes = atualizar_pendentes(
            pendentes_acoes, tentados, digest_acoes.get("falhas") or []
        )
        if len(tentados) == len(lote_acoes):
            cursor_acoes = proximo_acoes
        _gravar_estado(
            controle, linha_estado, cursor_acoes, cursor_fiis,
            pendentes_acoes, pendentes_fiis, agora_sp,
        )

    return {
        "limite_total": limite_total,
        "ticker": ticker_isolado or None,
        "acoes_solicitadas": len(lote_acoes),
        "fiis_solicitados": len(lote_fiis),
        "acoes_avancaram": sucesso_acoes,
        "fiis_avancaram": sucesso_fiis,
        "duracao_segundos": round(clock() - inicio, 3),
        "orcamento_segundos": orcamento_segundos,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limite-total", type=int, default=16)
    parser.add_argument("--orcamento-segundos", type=int, default=540)
    parser.add_argument("--pausa-segundos", type=float, default=2.0)
    parser.add_argument("--ticker", default="")
    args = parser.parse_args()
    resultado = executar(args.limite_total, args.orcamento_segundos, args.pausa_segundos, ticker=args.ticker)
    print(resultado)


if __name__ == "__main__":
    main()
