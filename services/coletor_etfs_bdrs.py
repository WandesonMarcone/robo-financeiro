"""Coleta auditável para ETFs e BDRs.

O fechamento negociado na B3 é obtido por fonte complementar de mercado;
documentos, composição e dados fundamentais oficiais entram somente quando a
fonte oficial foi identificada. Assim o painel nunca chama um número de
"oficial" quando ele não é.
"""
from __future__ import annotations

from datetime import datetime
import os

from sqlalchemy import text


def _numero(valor):
    try:
        valor = float(valor)
        return valor if valor == valor else None
    except (TypeError, ValueError):
        return None


def registrar_instrumento(ticker, tipo, simbolo_exterior=None, session_factory=None):
    """Inclui ETF/BDR no cadastro sem fingir que os metadados são oficiais."""
    ticker = str(ticker or "").strip().upper()
    tipo = str(tipo or "").strip().upper()
    if not ticker or tipo not in {"ETF", "BDR"}:
        raise ValueError("ticker ou tipo inválido")
    from atualizador_documentos import SessionDB
    sessao = session_factory() if session_factory else SessionDB()
    try:
        row = sessao.execute(text("""
            INSERT INTO instrumentos_internacionais
                (ticker, tipo, simbolo_yahoo_br, simbolo_exterior, fonte_cadastro)
            VALUES (:ticker, :tipo, :yahoo, :externo, 'PAINEL_TELEGRAM')
            ON CONFLICT (ticker) DO UPDATE SET tipo=EXCLUDED.tipo,
                simbolo_exterior=COALESCE(EXCLUDED.simbolo_exterior, instrumentos_internacionais.simbolo_exterior),
                ativo=TRUE, atualizado_em=NOW()
            RETURNING id, ticker, tipo
        """), {"ticker": ticker, "tipo": tipo, "yahoo": f"{ticker}.SA", "externo": simbolo_exterior or None}).mappings().one()
        sessao.commit()
        return dict(row)
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao.close()


def _upsert_metrica(sessao, instrumento_id, chave, valor, unidade, fonte, qualidade="COMPLEMENTAR"):
    numerico = _numero(valor)
    texto_valor = None if numerico is not None else (str(valor)[:1000] if valor not in (None, "") else None)
    if numerico is None and texto_valor is None:
        return
    sessao.execute(text("""
        INSERT INTO metricas_instrumentos_internacionais
          (instrumento_id,chave,valor_numerico,valor_texto,unidade,fonte,qualidade_fonte,referencia_em,atualizado_em)
        VALUES (:id,:chave,:numero,:texto,:unidade,:fonte,:qualidade,NOW(),NOW())
        ON CONFLICT (instrumento_id,chave) DO UPDATE SET
          valor_numerico=CASE WHEN metricas_instrumentos_internacionais.bloqueado THEN metricas_instrumentos_internacionais.valor_numerico ELSE EXCLUDED.valor_numerico END,
          valor_texto=CASE WHEN metricas_instrumentos_internacionais.bloqueado THEN metricas_instrumentos_internacionais.valor_texto ELSE EXCLUDED.valor_texto END,
          unidade=CASE WHEN metricas_instrumentos_internacionais.bloqueado THEN metricas_instrumentos_internacionais.unidade ELSE EXCLUDED.unidade END,
          fonte=CASE WHEN metricas_instrumentos_internacionais.bloqueado THEN metricas_instrumentos_internacionais.fonte ELSE EXCLUDED.fonte END,
          qualidade_fonte=CASE WHEN metricas_instrumentos_internacionais.bloqueado THEN metricas_instrumentos_internacionais.qualidade_fonte ELSE EXCLUDED.qualidade_fonte END,
          referencia_em=CASE WHEN metricas_instrumentos_internacionais.bloqueado THEN metricas_instrumentos_internacionais.referencia_em ELSE EXCLUDED.referencia_em END,
          atualizado_em=NOW()
    """), {"id": instrumento_id, "chave": chave, "numero": numerico, "texto": texto_valor,
             "unidade": unidade, "fonte": fonte, "qualidade": qualidade})


def _coletar_sec(sessao, instrumento):
    """Busca fatos XBRL apenas quando um CIK foi cadastrado explicitamente."""
    cik = str(instrumento.get("sec_cik") or "").strip()
    agente = (os.getenv("SEC_EDGAR_USER_AGENT") or "").strip()
    if not cik or not agente:
        return 0
    import requests
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json"
    resposta = requests.get(url, headers={"User-Agent": agente, "Accept-Encoding": "gzip, deflate"}, timeout=30)
    resposta.raise_for_status()
    fatos = resposta.json().get("facts", {}).get("us-gaap", {})
    mapa = {"RevenueFromContractWithCustomerExcludingAssessedTax": ("receita", "USD"),
            "Revenues": ("receita", "USD"), "NetIncomeLoss": ("lucro_liquido", "USD"),
            "Assets": ("ativos", "USD"), "Liabilities": ("passivos", "USD"),
            "CashAndCashEquivalentsAtCarryingValue": ("caixa", "USD"),
            "LongTermDebtCurrent": ("divida_curto_prazo", "USD"),
            "LongTermDebtNoncurrent": ("divida_longo_prazo", "USD"),
            "NetCashProvidedByUsedInOperatingActivities": ("fluxo_caixa_operacional", "USD")}
    gravadas = 0
    for tag, (chave, unidade) in mapa.items():
        unidades = fatos.get(tag, {}).get("units", {}).get("USD", [])
        candidatos = [x for x in unidades if x.get("form") in {"10-K", "10-Q"} and x.get("val") is not None]
        if candidatos:
            ultimo = max(candidatos, key=lambda x: x.get("filed", ""))
            _upsert_metrica(sessao, instrumento["id"], chave, ultimo["val"], unidade, "SEC/EDGAR", "OFICIAL")
            gravadas += 1
    return gravadas


def coletar_instrumento(ticker, tipo=None, simbolo_exterior=None, session_factory=None):
    """Grava preço histórico e métricas calculáveis, com origem explícita."""
    ticker = str(ticker or "").strip().upper()
    if tipo:
        registrar_instrumento(ticker, tipo, simbolo_exterior, session_factory=session_factory)
    from atualizador_documentos import SessionDB
    sessao = session_factory() if session_factory else SessionDB()
    try:
        instrumento = sessao.execute(text("SELECT * FROM instrumentos_internacionais WHERE ticker=:ticker AND ativo=TRUE"), {"ticker": ticker}).mappings().first()
        if not instrumento:
            raise ValueError("instrumento não cadastrado")
        import yfinance as yf
        simbolo = instrumento["simbolo_yahoo_br"] or f"{ticker}.SA"
        papel = yf.Ticker(simbolo)
        historico = papel.history(period="1y", interval="1d", auto_adjust=False)
        if historico is None or historico.empty:
            raise RuntimeError("COTACAO_NAO_DISPONIVEL")
        ultimo = historico.iloc[-1]
        data_ref = historico.index[-1].to_pydatetime().replace(tzinfo=None)
        fechamento = _numero(ultimo.get("Close")); anterior = _numero(historico.iloc[-2].get("Close")) if len(historico) > 1 else None
        variacao = ((fechamento / anterior) - 1) * 100 if fechamento and anterior else None
        sessao.execute(text("""
          INSERT INTO observacoes_instrumentos_internacionais
            (instrumento_id,referencia_em,abertura,maxima,minima,fechamento,volume,variacao_percentual,fonte,qualidade_fonte)
          VALUES (:id,:data,:abertura,:maxima,:minima,:fechamento,:volume,:variacao,'YAHOO_FINANCE','COMPLEMENTAR')
          ON CONFLICT (instrumento_id,referencia_em) DO UPDATE SET abertura=EXCLUDED.abertura,maxima=EXCLUDED.maxima,
          minima=EXCLUDED.minima,fechamento=EXCLUDED.fechamento,volume=EXCLUDED.volume,variacao_percentual=EXCLUDED.variacao_percentual,
          fonte=EXCLUDED.fonte,qualidade_fonte=EXCLUDED.qualidade_fonte,coletado_em=NOW()
        """), {"id":instrumento["id"], "data":data_ref, "abertura":_numero(ultimo.get("Open")), "maxima":_numero(ultimo.get("High")),
                  "minima":_numero(ultimo.get("Low")), "fechamento":fechamento, "volume":int(_numero(ultimo.get("Volume")) or 0), "variacao":variacao})
        fechamentos = historico["Close"].dropna()
        retornos = fechamentos.pct_change().dropna()
        if len(retornos):
            _upsert_metrica(sessao, instrumento["id"], "volatilidade_30d", retornos.tail(30).std() * (252 ** .5) * 100, "% a.a.", "CALCULO_PROPRIO")
        if len(fechamentos):
            queda = (fechamentos / fechamentos.cummax() - 1).min() * 100
            _upsert_metrica(sessao, instrumento["id"], "max_drawdown_1a", queda, "%", "CALCULO_PROPRIO")
            _upsert_metrica(sessao, instrumento["id"], "volume_medio_30d", historico["Volume"].tail(30).mean(), "ações/dia", "YAHOO_FINANCE")
        info = papel.get_info() or {}
        campos = {"patrimonio_ou_market_cap": (info.get("totalAssets") or info.get("marketCap"), "BRL"),
                  "dividend_yield": (info.get("dividendYield"), "%"), "p_l": (info.get("trailingPE"), "x"),
                  "p_vp": (info.get("priceToBook"), "x"), "roe": (info.get("returnOnEquity"), "%"),
                  "margem_lucro": (info.get("profitMargins"), "%"), "divida_total": (info.get("totalDebt"), "moeda da fonte"),
                  "caixa": (info.get("totalCash"), "moeda da fonte"), "ev_ebitda": (info.get("enterpriseToEbitda"), "x")}
        for chave, (valor, unidade) in campos.items():
            if chave in {"dividend_yield", "roe", "margem_lucro"} and _numero(valor) is not None:
                valor = float(valor) * 100
            _upsert_metrica(sessao, instrumento["id"], chave, valor, unidade, "YAHOO_FINANCE", "COMPLEMENTAR")
        nome = info.get("longName") or info.get("shortName")
        sessao.execute(text("UPDATE instrumentos_internacionais SET nome=COALESCE(:nome,nome), moeda_origem=COALESCE(:moeda,moeda_origem), atualizado_em=NOW() WHERE id=:id"), {"id": instrumento["id"], "nome": nome, "moeda": info.get("currency")})
        oficiais = _coletar_sec(sessao, instrumento) if instrumento["tipo"] == "BDR" else 0
        sessao.commit()
        return {"ticker": ticker, "tipo": instrumento["tipo"], "referencia": data_ref.date().isoformat(), "preco": fechamento, "metricas": len([v for v, _ in campos.values() if v is not None]), "oficiais_sec": oficiais}
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao.close()


def coletar_instrumentos_ativos(limite=30, session_factory=None):
    from atualizador_documentos import SessionDB
    sessao = session_factory() if session_factory else SessionDB()
    try:
        tickers = [r[0] for r in sessao.execute(text("SELECT ticker FROM instrumentos_internacionais WHERE ativo=TRUE ORDER BY atualizado_em NULLS FIRST, ticker LIMIT :limite"), {"limite": max(1, min(int(limite), 60))}).all()]
    finally:
        sessao.close()
    resultado = {"processados": 0, "falhas": [], "ativos": []}
    for ticker in tickers:
        try:
            resultado["ativos"].append(coletar_instrumento(ticker, session_factory=session_factory)); resultado["processados"] += 1
        except Exception as exc:
            resultado["falhas"].append({"ticker": ticker, "erro": type(exc).__name__})
    return resultado
