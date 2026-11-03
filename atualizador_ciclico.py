"""Atualização cíclica, silenciosa e limitada de ativos da planilha.

Este processo não envia Telegram nem cria alertas. Ele atualiza somente um lote
curto e retoma a posição persistida na aba Controle_Robo depois de gravar dados.
"""
from __future__ import annotations

import argparse
import datetime
import time

import pytz

import config
from modules.lotes_atualizacao import distribuir_limite, proximo_lote
from modules.scraper_acoes import rodar_garimpo_acoes
from modules.scraper_fiis import rodar_garimpo_fiis
from modules.utils import conectar_gspread


CHAVE_ESTADO = "atualizacao_ciclica_v1"
ABA_CONTROLE = "Controle_Robo"


def _tickers(linhas):
    return [str(linha[0]).strip().upper() for linha in linhas[1:] if linha and str(linha[0]).strip()]


def _controle(planilha):
    try:
        aba = planilha.worksheet(ABA_CONTROLE)
    except Exception:
        aba = planilha.add_worksheet(title=ABA_CONTROLE, rows=10, cols=4)
        aba.append_row(["chave", "cursor_acoes", "cursor_fiis", "atualizado_em"])
    valores = aba.get_all_values()
    for indice, linha in enumerate(valores[1:], start=2):
        if linha and linha[0] == CHAVE_ESTADO:
            return aba, indice, linha
    aba.append_row([CHAVE_ESTADO, "0", "0", ""])
    return aba, len(valores) + 1, [CHAVE_ESTADO, "0", "0", ""]


def _inteiro(valor):
    try:
        return max(0, int(valor))
    except (TypeError, ValueError):
        return 0


def _gravar(aba, linha, cursor_acoes, cursor_fiis, agora_sp):
    aba.update(
        f"B{linha}:D{linha}",
        [[str(cursor_acoes), str(cursor_fiis), agora_sp]],
    )


def _persistir_lote(aba, atualizacoes, tipo):
    if not atualizacoes:
        print(f"Lote {tipo}: sem dados válidos; cursor preservado para nova tentativa.")
        return False
    aba.batch_update(atualizacoes)
    print(f"Lote {tipo}: {len(atualizacoes)} células gravadas.")
    return True


def executar(limite_total=20, orcamento_segundos=720, pausa_segundos=2.0, planilha=None, clock=time.monotonic, sleep=time.sleep):
    if not 1 <= limite_total <= 20:
        raise ValueError("limite_total_invalido")
    if not 60 <= orcamento_segundos <= 720:
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

    cursor_acoes = _inteiro(estado[1] if len(estado) > 1 else 0)
    cursor_fiis = _inteiro(estado[2] if len(estado) > 2 else 0)
    limite_acoes, limite_fiis = distribuir_limite(limite_total, len(acoes), len(fiis))
    lote_acoes, _ = proximo_lote(acoes, cursor_acoes, limite_acoes)
    lote_fiis, _ = proximo_lote(fiis, cursor_fiis, limite_fiis)

    fuso = pytz.timezone("America/Sao_Paulo")
    agora_dt = datetime.datetime.now(fuso)
    agora_sp = agora_dt.strftime("%d/%m %H:%M")
    print(
        f"Atualização cíclica: teto={limite_total}; "
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
        executados_fiis = len(digest_fiis.get("tentados") or [])
        cursor_fiis = (cursor_fiis + executados_fiis) % len(fiis) if fiis else 0
        _gravar(controle, linha_estado, cursor_acoes, cursor_fiis, agora_sp)

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
        executados_acoes = len(digest_acoes.get("tentados") or [])
        cursor_acoes = (cursor_acoes + executados_acoes) % len(acoes) if acoes else 0
        _gravar(controle, linha_estado, cursor_acoes, cursor_fiis, agora_sp)

    return {
        "limite_total": limite_total,
        "acoes_solicitadas": len(lote_acoes),
        "fiis_solicitados": len(lote_fiis),
        "acoes_avancaram": sucesso_acoes,
        "fiis_avancaram": sucesso_fiis,
        "duracao_segundos": round(clock() - inicio, 3),
        "orçamento_segundos": orcamento_segundos,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limite-total", type=int, default=20)
    parser.add_argument("--orcamento-segundos", type=int, default=720)
    parser.add_argument("--pausa-segundos", type=float, default=2.0)
    args = parser.parse_args()
    resultado = executar(args.limite_total, args.orcamento_segundos, args.pausa_segundos)
    print(resultado)


if __name__ == "__main__":
    main()
