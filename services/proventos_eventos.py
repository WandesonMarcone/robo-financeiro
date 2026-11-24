"""Coleta curta de distribuições e desdobramentos para a Carteira.

Yahoo é tratado como fonte complementar. Ele não distingue com segurança JCP,
dividendo e rendimento de FII; por isso a API publica ``DISTRIBUICAO`` sem
inventar uma classificação fiscal. Uma fonte oficial poderá refinar o registro
mantendo o mesmo contrato.
"""
from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
import time

from sqlalchemy import text


ABAS_UNIVERSO = {
    "ACAO": "BD_Acoes",
    "FII": "BD_FIIs",
    "ETF": "BD_ETFs",
    "BDR": "BD_BDRs",
}


def _id(*partes) -> str:
    bruto = "|".join(str(parte) for parte in partes)
    return sha256(bruto.encode("utf-8")).hexdigest()


def listar_universo_planilha(planilha=None):
    if planilha is None:
        import config
        from modules.utils import conectar_gspread

        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
    universo = {}
    for classe, aba_nome in ABAS_UNIVERSO.items():
        linhas = planilha.worksheet(aba_nome).get_all_values()
        universo[classe] = sorted({
            str(linha[0]).strip().upper()
            for linha in linhas[1:]
            if linha and str(linha[0]).strip()
        })
    return universo


def selecionar_lote(tickers, limite, hoje=None):
    """Gira a base diariamente para cobrir todos sem uma carga maciça."""
    tickers = list(tickers or [])
    if not tickers:
        return []
    limite = max(1, min(int(limite), len(tickers)))
    hoje = hoje or date.today()
    inicio = ((hoje.toordinal() - 1) * limite) % len(tickers)
    return [tickers[(inicio + indice) % len(tickers)] for indice in range(limite)]


def extrair_eventos_yahoo(ticker, classe, papel, desde, ate):
    historico = papel.history(
        start=desde.isoformat(), end=(ate + timedelta(days=1)).isoformat(),
        interval="1d", auto_adjust=False, actions=True,
    )
    if historico is None or historico.empty:
        return [], []
    proventos, eventos = [], []
    for indice, linha in historico.iterrows():
        referencia = indice.date() if hasattr(indice, "date") else date.fromisoformat(str(indice)[:10])
        distribuicao = float(linha.get("Dividends") or 0)
        ganho_capital = float(linha.get("Capital Gains") or 0)
        desdobramento = float(linha.get("Stock Splits") or 0)
        for tipo, valor in (("DISTRIBUICAO", distribuicao), ("GANHO_CAPITAL", ganho_capital)):
            if valor > 0:
                proventos.append({
                    "identificador": _id(ticker, classe, referencia, tipo, f"{valor:.8f}", "YAHOO_FINANCE"),
                    "ticker": ticker, "classe": classe, "data_ex": referencia,
                    "data_pagamento": None, "tipo": tipo, "valor_unitario": valor,
                    "moeda": "BRL", "fonte": "YAHOO_FINANCE",
                    "qualidade_fonte": "COMPLEMENTAR",
                })
        if desdobramento > 0:
            eventos.append({
                "identificador": _id(ticker, classe, referencia, "DESDOBRAMENTO_OU_GRUPAMENTO", f"{desdobramento:.8f}", "YAHOO_FINANCE"),
                "ticker": ticker, "classe": classe, "data_referencia": referencia,
                "tipo": "DESDOBRAMENTO_OU_GRUPAMENTO", "fator": desdobramento,
                "descricao": "Fator informado pela fonte; confirmar natureza no evento oficial.",
                "fonte": "YAHOO_FINANCE", "qualidade_fonte": "COMPLEMENTAR",
            })
    return proventos, eventos


def _persistir(sessao, proventos, eventos):
    for item in proventos:
        sessao.execute(text("""
            INSERT INTO proventos_ativos
              (identificador,ticker,classe,data_ex,data_pagamento,tipo,valor_unitario,moeda,fonte,qualidade_fonte)
            VALUES (:identificador,:ticker,:classe,:data_ex,:data_pagamento,:tipo,:valor_unitario,:moeda,:fonte,:qualidade_fonte)
            ON CONFLICT (identificador) DO UPDATE SET
              data_pagamento=COALESCE(EXCLUDED.data_pagamento,proventos_ativos.data_pagamento),
              valor_unitario=EXCLUDED.valor_unitario, fonte=EXCLUDED.fonte,
              qualidade_fonte=EXCLUDED.qualidade_fonte, atualizado_em=NOW()
        """), item)
    for item in eventos:
        sessao.execute(text("""
            INSERT INTO eventos_corporativos_ativos
              (identificador,ticker,classe,data_referencia,tipo,fator,descricao,fonte,qualidade_fonte)
            VALUES (:identificador,:ticker,:classe,:data_referencia,:tipo,:fator,:descricao,:fonte,:qualidade_fonte)
            ON CONFLICT (identificador) DO UPDATE SET
              fator=EXCLUDED.fator,descricao=EXCLUDED.descricao,fonte=EXCLUDED.fonte,
              qualidade_fonte=EXCLUDED.qualidade_fonte,atualizado_em=NOW()
        """), item)


def coletar_proventos_eventos(limite_por_classe=20, janela_dias=75, pausa_segundos=1,
                              planilha=None, session_factory=None, ticker_factory=None,
                              hoje=None):
    """Coleta lote rotativo e confirma Sheets antes de cada transação Neon."""
    hoje = hoje or date.today()
    janela_dias = max(30, min(int(janela_dias), 120))
    desde = hoje - timedelta(days=janela_dias)
    universo = listar_universo_planilha(planilha=planilha)
    if ticker_factory is None:
        import yfinance as yf
        ticker_factory = yf.Ticker
    if session_factory is None:
        from atualizador_documentos import SessionDB
        session_factory = SessionDB
    from services.planilha_eventos_mercado import gravar_eventos_planilha

    resultado = {"processados": 0, "proventos": 0, "eventos": 0, "sem_eventos": 0,
                 "falhas": [], "janela_dias": janela_dias,
                 "ordem_persistencia": "PLANILHA_ANTES_NEON"}
    for classe, tickers in universo.items():
        for ticker in selecionar_lote(tickers, limite_por_classe, hoje=hoje):
            try:
                proventos, eventos = extrair_eventos_yahoo(
                    ticker, classe, ticker_factory(f"{ticker}.SA"), desde, hoje
                )
                if not proventos and not eventos:
                    resultado["sem_eventos"] += 1
                    resultado["processados"] += 1
                    continue
                gravar_eventos_planilha(proventos, eventos, planilha=planilha)
                sessao = session_factory()
                try:
                    _persistir(sessao, proventos, eventos)
                    sessao.commit()
                except Exception:
                    sessao.rollback()
                    raise
                finally:
                    sessao.close()
                resultado["processados"] += 1
                resultado["proventos"] += len(proventos)
                resultado["eventos"] += len(eventos)
            except Exception as exc:
                resultado["falhas"].append({"ticker": ticker, "classe": classe, "erro": type(exc).__name__})
            if pausa_segundos:
                time.sleep(float(pausa_segundos))
    return resultado
