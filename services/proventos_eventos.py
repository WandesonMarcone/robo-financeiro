"""Coleta curta de distribuições e desdobramentos para a Carteira.

Yahoo é tratado como fonte complementar. Ele não distingue com segurança JCP,
dividendo e rendimento de FII; por isso a API publica ``DISTRIBUICAO`` sem
inventar uma classificação fiscal. Uma fonte oficial poderá refinar o registro
mantendo o mesmo contrato.
"""
from __future__ import annotations

from base64 import b64encode
from datetime import date, timedelta
from hashlib import sha256
import json
import math
import re
import time

import requests
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


_B3_PROXY = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall"


def _data_oficial(valor):
    """Converte somente datas explícitas devolvidas pela fonte oficial."""
    if isinstance(valor, date):
        return valor
    texto = str(valor or "").strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    return None


def _b3_url(metodo, parametros):
    serializado = json.dumps(parametros, separators=(",", ":"), ensure_ascii=False)
    token = b64encode(serializado.encode("utf-8")).decode("ascii")
    return f"{_B3_PROXY}/{metodo}/{token}"


def _b3_json(metodo, parametros, http_get=requests.get):
    resposta = http_get(
        _b3_url(metodo, parametros),
        headers={"Accept": "application/json", "User-Agent": "robo-financeiro/2.0"},
        timeout=20,
    )
    if hasattr(resposta, "raise_for_status"):
        resposta.raise_for_status()
    elif int(getattr(resposta, "status_code", 200)) >= 400:
        raise RuntimeError(f"B3_HTTP_{resposta.status_code}")
    return resposta.json()


def extrair_proventos_oficiais_b3(ticker, http_get=requests.get):
    """Resolve na B3 o ISIN do ticker e consulta as datas de pagamento."""
    ticker = str(ticker or "").upper().strip()
    emissor = re.sub(r"\d+$", "", ticker)
    catalogo = _b3_json("GetInitialCompanies", {
        "language": "pt-br", "pageNumber": 1, "pageSize": 20, "company": emissor,
    }, http_get=http_get)
    empresa = next((item for item in catalogo.get("results", [])
                    if str(item.get("issuingCompany") or "").upper() == emissor), None)
    if not empresa or not empresa.get("codeCVM"):
        return []

    detalhe = _b3_json("GetDetail", {
        "codeCVM": str(empresa["codeCVM"]), "language": "pt-br",
    }, http_get=http_get)
    isins = {
        str(item["isin"]).strip().upper()
        for item in detalhe.get("otherCodes", [])
        if str(item.get("code") or "").strip().upper() == ticker and item.get("isin")
    }
    if len(isins) != 1:
        return []

    metodo = "GetListedSupplementCompany"
    parametros = {"issuingCompany": emissor, "language": "pt-br"}
    suplementos = _b3_json(metodo, parametros, http_get=http_get)
    if not isinstance(suplementos, list):
        raise RuntimeError("B3_SUPLEMENTO_FORMATO_INESPERADO")
    isin = next(iter(isins))
    url_fonte = _b3_url(metodo, parametros)
    oficiais = []
    for suplemento in suplementos:
        if str(suplemento.get("code") or "").strip().upper() != emissor:
            continue
        for item in suplemento.get("cashDividends") or []:
            if str(item.get("isinCode") or "").strip().upper() != isin:
                continue
            pagamento = _data_oficial(item.get("paymentDate"))
            try:
                taxa = item["rate"]
                if isinstance(taxa, str) and "," in taxa:
                    taxa = taxa.replace(".", "").replace(",", ".")
                valor = float(taxa)
            except (KeyError, TypeError, ValueError):
                continue
            if not pagamento or not math.isfinite(valor) or valor <= 0:
                continue
            oficiais.append({
                "ticker": ticker, "classe": "ACAO", "isin": isin,
                "data_com": _data_oficial(item.get("lastDatePrior")),
                "data_pagamento": pagamento, "valor_unitario": valor,
                "tipo_original": str(item.get("label") or "PROVENTO"),
                "fonte": "B3_LISTED_COMPANIES", "url_fonte": url_fonte,
            })
    return oficiais


def _chave_oficial(item):
    return _id(item["ticker"], item["classe"], item.get("isin") or "", item.get("data_com") or "", item["data_pagamento"],
               f"{float(item['valor_unitario']):.10f}", item["fonte"])


def conciliar_pagamentos_b3(sessao, ticker, http_get=requests.get, oficiais=None):
    """Associa pagamento oficial a um único evento complementar compatível."""
    resultado = {"consultados": 0, "confirmados": 0, "pendentes": 0, "conflitos": 0, "datas": {}}
    oficiais = extrair_proventos_oficiais_b3(ticker, http_get=http_get) if oficiais is None else oficiais
    for oficial in oficiais:
        resultado["consultados"] += 1
        chave = _chave_oficial(oficial)
        candidatos = []
        if oficial.get("data_com"):
            candidatos = sessao.execute(text("""
                SELECT id, identificador, data_pagamento FROM proventos_ativos
                WHERE ticker=:ticker AND classe='ACAO'
                  AND data_ex >= :data_com AND data_ex <= :limite
                  AND ABS(valor_unitario - :valor) <= :tolerancia
                ORDER BY id FOR UPDATE
            """), {
                "ticker": oficial["ticker"], "data_com": oficial["data_com"],
                "limite": oficial["data_com"] + timedelta(days=7), "valor": oficial["valor_unitario"],
                "tolerancia": max(0.00000001, abs(oficial["valor_unitario"]) * 0.00001),
            }).mappings().all()
        status = "CONFIRMADO" if len(candidatos) == 1 else "CONFLITO" if len(candidatos) > 1 else "PENDENTE_DATA_EX"
        provento_id = candidatos[0]["id"] if len(candidatos) == 1 else None
        detalhe = None if status == "CONFIRMADO" else ("Mais de um evento complementar compatível." if candidatos else "Aguardando data-ex compatível.")
        if status == "CONFIRMADO" and candidatos[0]["data_pagamento"] not in (None, oficial["data_pagamento"]):
            status = "CONFLITO"
            provento_id = None
            detalhe = "Já existe uma data de pagamento divergente para o evento."
        sessao.execute(text("""
            INSERT INTO conciliacoes_proventos_oficiais
              (chave,ticker,classe,isin,data_com,data_pagamento,tipo_original,valor_unitario,fonte,url_fonte,status,provento_id,detalhe)
            VALUES (:chave,:ticker,:classe,:isin,:data_com,:data_pagamento,:tipo_original,:valor_unitario,:fonte,:url_fonte,:status,:provento_id,:detalhe)
            ON CONFLICT (chave) DO UPDATE SET status=EXCLUDED.status, provento_id=EXCLUDED.provento_id,
              detalhe=EXCLUDED.detalhe, atualizado_em=NOW()
        """), {**oficial, "chave": chave, "status": status, "provento_id": provento_id, "detalhe": detalhe})
        if status == "CONFIRMADO":
            identificador = candidatos[0]["identificador"]
            sessao.execute(text("""
                UPDATE proventos_ativos SET data_pagamento=:pagamento, fonte='B3_LISTED_COMPANIES',
                  qualidade_fonte='OFICIAL_B3', atualizado_em=NOW() WHERE id=:id
            """), {"pagamento": oficial["data_pagamento"], "id": provento_id})
            resultado["confirmados"] += 1
            resultado["datas"][identificador] = oficial["data_pagamento"]
        elif status == "CONFLITO":
            resultado["conflitos"] += 1
        else:
            resultado["pendentes"] += 1
    return resultado


def extrair_eventos_yahoo(ticker, classe, papel, desde, ate, tentativas=2, espera_retentativa=3):
    """Consulta o Yahoo novamente antes de registrar uma falha pontual."""
    for tentativa in range(max(1, int(tentativas))):
        try:
            historico = papel.history(
                start=desde.isoformat(), end=(ate + timedelta(days=1)).isoformat(),
                interval="1d", auto_adjust=False, actions=True,
            )
            break
        except Exception:
            if tentativa + 1 >= max(1, int(tentativas)):
                raise
            time.sleep(float(espera_retentativa) * (tentativa + 1))
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
        gravado = sessao.execute(text("""
            INSERT INTO proventos_ativos
              (identificador,ticker,classe,data_ex,data_pagamento,tipo,valor_unitario,moeda,fonte,qualidade_fonte)
            VALUES (:identificador,:ticker,:classe,:data_ex,:data_pagamento,:tipo,:valor_unitario,:moeda,:fonte,:qualidade_fonte)
            ON CONFLICT (identificador) DO UPDATE SET
              data_pagamento=COALESCE(EXCLUDED.data_pagamento,proventos_ativos.data_pagamento),
              valor_unitario=EXCLUDED.valor_unitario,
              fonte=CASE WHEN proventos_ativos.qualidade_fonte='OFICIAL_B3'
                         THEN proventos_ativos.fonte ELSE EXCLUDED.fonte END,
              qualidade_fonte=CASE WHEN proventos_ativos.qualidade_fonte='OFICIAL_B3'
                                   THEN proventos_ativos.qualidade_fonte ELSE EXCLUDED.qualidade_fonte END,
              atualizado_em=NOW()
            RETURNING data_pagamento, fonte, qualidade_fonte
        """), item).mappings().one()
        item.update(gravado)
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
                              hoje=None, b3_fetcher=extrair_proventos_oficiais_b3):
    """Coleta e confirma Neon; depois espelha o lote no Sheets."""
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
                 "ordem_persistencia": "NEON_ANTES_PLANILHA",
                 "pagamentos_oficiais": {"confirmados": 0, "pendentes": 0, "conflitos": 0}}
    proventos_espelho, eventos_espelho, tickers_espelho = [], [], []
    for classe, tickers in universo.items():
        for ticker in selecionar_lote(tickers, limite_por_classe, hoje=hoje):
            try:
                proventos, eventos = extrair_eventos_yahoo(
                    ticker, classe, ticker_factory(f"{ticker}.SA"), desde, hoje
                )
                if not proventos and not eventos and classe != "ACAO":
                    resultado["sem_eventos"] += 1
                    resultado["processados"] += 1
                    continue
                pagamentos_b3 = []
                if classe == "ACAO":
                    try:
                        pagamentos_b3 = b3_fetcher(ticker)
                    except (requests.RequestException, RuntimeError) as exc:
                        resultado["falhas"].append({
                            "ticker": ticker, "classe": classe,
                            "erro": "CONSULTA_B3_PENDENTE", "causa": type(exc).__name__,
                        })
                sessao = session_factory()
                try:
                    _persistir(sessao, proventos, eventos)
                    if pagamentos_b3:
                        oficial = conciliar_pagamentos_b3(sessao, ticker, oficiais=pagamentos_b3)
                        for chave in ("confirmados", "pendentes", "conflitos"):
                            resultado["pagamentos_oficiais"][chave] += oficial[chave]
                        for item in proventos:
                            if item["identificador"] in oficial["datas"]:
                                item.update(
                                    data_pagamento=oficial["datas"][item["identificador"]],
                                    fonte="B3_LISTED_COMPANIES",
                                    qualidade_fonte="OFICIAL_B3",
                                )
                    sessao.commit()
                except Exception:
                    sessao.rollback()
                    raise
                finally:
                    sessao.close()
                proventos_espelho.extend(proventos)
                eventos_espelho.extend(eventos)
                tickers_espelho.append((ticker, classe))
                resultado["processados"] += 1
                resultado["proventos"] += len(proventos)
                resultado["eventos"] += len(eventos)
            except Exception as exc:
                resultado["falhas"].append({"ticker": ticker, "classe": classe, "erro": type(exc).__name__})
            if pausa_segundos:
                time.sleep(float(pausa_segundos))
    if proventos_espelho or eventos_espelho:
        try:
            resultado["espelho_planilha"] = gravar_eventos_planilha(
                proventos_espelho, eventos_espelho, planilha=planilha
            )
        except Exception as espelho_exc:
            for ticker, classe in tickers_espelho:
                resultado["falhas"].append({
                    "ticker": ticker, "classe": classe,
                    "erro": "ESPELHO_PLANILHA_PENDENTE",
                    "causa": type(espelho_exc).__name__,
                })
            resultado["espelho_planilha"] = {"estado": "PENDENTE"}
    return resultado
