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


# Lista inicial deliberadamente pequena. Ela dá cobertura aos principais tipos
# de exposição sem transformar o robô em um rastreador indiscriminado de toda a
# B3. Metadados já preenchidos manualmente não são sobrescritos pelo cadastro.
BASE_INICIAL_INSTRUMENTOS = (
    {"ticker": "BOVA11", "tipo": "ETF", "nome": "iShares Ibovespa Fundo de Índice", "externo": "IBOV", "indice": "Ibovespa", "gestora": "BlackRock"},
    {"ticker": "IVVB11", "tipo": "ETF", "nome": "iShares S&P 500 Fundo de Investimento", "externo": "IVV", "indice": "S&P 500", "gestora": "BlackRock"},
    {"ticker": "SMAL11", "tipo": "ETF", "nome": "iShares BM&FBovespa Small Cap Fundo de Índice", "externo": "EWZS", "indice": "Índice Small Cap (SMLL)", "gestora": "BlackRock"},
    {"ticker": "XFIX11", "tipo": "ETF", "nome": "Trend ETF IFIX Fundo de Índice", "externo": "IFIX", "indice": "IFIX", "gestora": "XP Asset"},
    {"ticker": "GOLD11", "tipo": "ETF", "nome": "Trend ETF LBMA Ouro", "externo": "GOLD", "indice": "LBMA Gold Price", "gestora": "XP Asset"},
    {"ticker": "HMRN31", "tipo": "BDR", "nome": "Homerun Resources Inc.", "externo": "HMR", "indice": None, "gestora": None},
)


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


def cadastrar_base_inicial(session_factory=None):
    """Registra a seleção inicial de ETFs e o BDR solicitado.

    Não dispara coleta: o chamador decide quando executar a primeira busca,
    mantendo a operação previsível e auditável.
    """
    from atualizador_documentos import SessionDB
    sessao = session_factory() if session_factory else SessionDB()
    try:
        cadastrados = []
        for item in BASE_INICIAL_INSTRUMENTOS:
            sessao.execute(text("""
                INSERT INTO instrumentos_internacionais
                  (ticker,tipo,nome,simbolo_yahoo_br,simbolo_exterior,indice_referencia,gestora,fonte_cadastro,ativo)
                VALUES (:ticker,:tipo,:nome,:yahoo,:externo,:indice,:gestora,'BASE_INICIAL_SISTEMA',TRUE)
                ON CONFLICT (ticker) DO UPDATE SET
                  tipo=EXCLUDED.tipo, ativo=TRUE,
                  nome=COALESCE(instrumentos_internacionais.nome, EXCLUDED.nome),
                  simbolo_yahoo_br=COALESCE(instrumentos_internacionais.simbolo_yahoo_br, EXCLUDED.simbolo_yahoo_br),
                  simbolo_exterior=COALESCE(instrumentos_internacionais.simbolo_exterior, EXCLUDED.simbolo_exterior),
                  indice_referencia=COALESCE(instrumentos_internacionais.indice_referencia, EXCLUDED.indice_referencia),
                  gestora=COALESCE(instrumentos_internacionais.gestora, EXCLUDED.gestora),
                  atualizado_em=NOW()
            """), {**item, "yahoo": f"{item['ticker']}.SA"})
            cadastrados.append(item["ticker"])
        sessao.commit()
        return {"cadastrados": cadastrados, "quantidade": len(cadastrados)}
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
            _upsert_metrica(sessao, instrumento["id"], "liquidez_media_30d_brl", (historico["Close"] * historico["Volume"]).tail(30).mean(), "BRL/dia", "YAHOO_FINANCE")
            _upsert_metrica(sessao, instrumento["id"], "distancia_maxima_1a", ((fechamentos.iloc[-1] / fechamentos.max()) - 1) * 100, "%", "CALCULO_PROPRIO")
            if len(fechamentos) >= 20:
                _upsert_metrica(sessao, instrumento["id"], "retorno_periodo_coletado", ((fechamentos.iloc[-1] / fechamentos.iloc[0]) - 1) * 100, "%", "CALCULO_PROPRIO")
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
        return {
            "ticker": ticker, "tipo": instrumento["tipo"],
            "referencia": data_ref.date().isoformat(), "preco": fechamento,
            "variacao": variacao,
            "metricas": len([v for v, _ in campos.values() if v is not None]),
            "oficiais_sec": oficiais,
        }
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao.close()


COLUNAS_PLANILHA_INSTRUMENTOS = (
    "TICKER", "NOME", "PREÇO", "VAR. DIA", "ÍNDICE / REFERÊNCIA",
    "LIQUIDEZ MÉDIA 30D", "VOLUME MÉDIO 30D", "DISTÂNCIA MÁXIMA 12M",
    "VOLATILIDADE 30D", "RETORNO COLETADO", "DY", "P/L", "P/VP",
    "FONTE", "DATA REFERÊNCIA", "ATUALIZADO EM",
)


def sincronizar_instrumentos_planilha(tipo, session_factory=None):
    """Espelha a última coleta de uma classe em BD_ETFs ou BD_BDRs.

    A planilha é uma visão operacional, como BD_Acoes/BD_FIIs; o Neon segue
    sendo a fonte auditável. A rotina atualiza por ticker, nunca apaga linhas
    manuais existentes e só declara sucesso quando há fechamento válido.
    """
    tipo = str(tipo or "").upper()
    if tipo not in {"ETF", "BDR"}:
        raise ValueError("tipo deve ser ETF ou BDR")
    from atualizador_documentos import SessionDB
    from modules.utils import conectar_gspread
    import config

    sessao = session_factory() if session_factory else SessionDB()
    try:
        linhas = sessao.execute(text("""
          WITH ultima AS (
            SELECT DISTINCT ON (instrumento_id) instrumento_id, referencia_em,
                   fechamento, variacao_percentual, fonte
            FROM observacoes_instrumentos_internacionais
            ORDER BY instrumento_id, referencia_em DESC
          ), metricas AS (
            SELECT instrumento_id,
              MAX(valor_numerico) FILTER (WHERE chave='liquidez_media_30d_brl') AS liquidez,
              MAX(valor_numerico) FILTER (WHERE chave='volume_medio_30d') AS volume,
              MAX(valor_numerico) FILTER (WHERE chave='distancia_maxima_1a') AS distancia,
              MAX(valor_numerico) FILTER (WHERE chave='volatilidade_30d') AS volatilidade,
              MAX(valor_numerico) FILTER (WHERE chave='retorno_periodo_coletado') AS retorno,
              MAX(valor_numerico) FILTER (WHERE chave='dividend_yield') AS dy,
              MAX(valor_numerico) FILTER (WHERE chave='p_l') AS pl,
              MAX(valor_numerico) FILTER (WHERE chave='p_vp') AS pvp
            FROM metricas_instrumentos_internacionais GROUP BY instrumento_id
          )
          SELECT i.ticker,i.nome,i.indice_referencia,u.fechamento,u.variacao_percentual,
                 u.referencia_em,u.fonte,m.liquidez,m.volume,m.distancia,m.volatilidade,
                 m.retorno,m.dy,m.pl,m.pvp
          FROM instrumentos_internacionais i
          LEFT JOIN ultima u ON u.instrumento_id=i.id
          LEFT JOIN metricas m ON m.instrumento_id=i.id
          WHERE i.ativo=TRUE AND i.tipo=:tipo ORDER BY i.ticker
        """), {"tipo": tipo}).mappings().all()
    finally:
        sessao.close()

    aba_nome = "BD_ETFs" if tipo == "ETF" else "BD_BDRs"
    planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
    aba = planilha.worksheet(aba_nome)
    existentes = aba.get_all_values()
    if not existentes or existentes[0][:len(COLUNAS_PLANILHA_INSTRUMENTOS)] != list(COLUNAS_PLANILHA_INSTRUMENTOS):
        raise RuntimeError(f"cabecalho_invalido:{aba_nome}")
    por_ticker = {str(linha[0]).strip().upper(): indice + 1 for indice, linha in enumerate(existentes[1:]) if linha and linha[0].strip()}
    agora = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    atualizacoes = []
    proxima_linha = len(existentes) + 1
    def valor_planilha(valor):
        numero = _numero(valor)
        return numero if numero is not None else (valor or "—")
    for item in linhas:
        ticker = item["ticker"]
        referencia = item["referencia_em"]
        linha = [
            ticker, item["nome"] or "—", valor_planilha(item["fechamento"]), valor_planilha(item["variacao_percentual"]),
            item["indice_referencia"] or "—", valor_planilha(item["liquidez"]), valor_planilha(item["volume"]),
            valor_planilha(item["distancia"]), valor_planilha(item["volatilidade"]), valor_planilha(item["retorno"]), valor_planilha(item["dy"]),
            valor_planilha(item["pl"]), valor_planilha(item["pvp"]), (item["fonte"] or "YAHOO_FINANCE"),
            referencia.date().isoformat() if referencia else "—", agora if item["fechamento"] is not None else "SEM COTAÇÃO",
        ]
        numero_linha = por_ticker.get(ticker)
        if numero_linha:
            atualizacoes.append({"range": f"A{numero_linha}:P{numero_linha}", "values": [linha]})
        else:
            atualizacoes.append({"range": f"A{proxima_linha}:P{proxima_linha}", "values": [linha]})
            proxima_linha += 1
    if atualizacoes:
        aba.batch_update(atualizacoes, value_input_option="USER_ENTERED")
    return {"aba": aba_nome, "linhas": len(linhas), "gravadas": len(atualizacoes)}


def coletar_instrumentos_ativos(limite=30, tipo=None, session_factory=None):
    """Atualiza uma classe por vez quando ``tipo`` for ETF ou BDR.

    O limite continua intencionalmente baixo para proteger a fonte e o job;
    classes diferentes não disputam a mesma fila ou relatório de término.
    """
    tipo = str(tipo or "").strip().upper()
    if tipo and tipo not in {"ETF", "BDR"}:
        raise ValueError("tipo deve ser ETF ou BDR")
    from atualizador_documentos import SessionDB
    sessao = session_factory() if session_factory else SessionDB()
    try:
        tickers = [r[0] for r in sessao.execute(text("""
            SELECT ticker FROM instrumentos_internacionais
            WHERE ativo=TRUE AND (:tipo='' OR tipo=:tipo)
            ORDER BY atualizado_em NULLS FIRST, ticker LIMIT :limite
        """), {"limite": max(1, min(int(limite), 60)), "tipo": tipo}).all()]
    finally:
        sessao.close()
    resultado = {"tipo": tipo or "TODOS", "processados": 0, "falhas": [], "ativos": []}
    for ticker in tickers:
        try:
            resultado["ativos"].append(coletar_instrumento(ticker, session_factory=session_factory)); resultado["processados"] += 1
        except Exception as exc:
            resultado["falhas"].append({"ticker": ticker, "erro": type(exc).__name__})
    # A sincronização é feita após a coleta para que cada aba represente uma
    # fotografia coerente da classe, inclusive quando um ativo falhou.
    tipos_planilha = [tipo] if tipo else ["ETF", "BDR"]
    resultado["planilha"] = {}
    for classe in tipos_planilha:
        try:
            resultado["planilha"][classe] = sincronizar_instrumentos_planilha(classe, session_factory=session_factory)
        except Exception as exc:
            resultado["planilha"][classe] = {"erro": type(exc).__name__}
    return resultado


def listar_instrumentos_telegram(limite=20, session_factory=None):
    """Resumo curto para o menu Telegram, sem disparar nova coleta."""
    from atualizador_documentos import SessionDB
    sessao = session_factory() if session_factory else SessionDB()
    try:
        linhas = sessao.execute(text("""
            SELECT i.ticker, i.tipo, i.nome, o.fechamento, o.variacao_percentual, o.referencia_em
            FROM instrumentos_internacionais i
            LEFT JOIN LATERAL (
                SELECT fechamento, variacao_percentual, referencia_em
                FROM observacoes_instrumentos_internacionais
                WHERE instrumento_id=i.id
                ORDER BY referencia_em DESC LIMIT 1
            ) o ON TRUE
            WHERE i.ativo=TRUE
            ORDER BY i.tipo, i.ticker
            LIMIT :limite
        """), {"limite": max(1, min(int(limite), 30))}).mappings().all()
    finally:
        sessao.close()
    if not linhas:
        return "📭 Ainda não há ETFs ou BDRs cadastrados para consulta."
    texto = ["🌐 *ETFs e BDRs acompanhados*"]
    for item in linhas:
        preco = f"R$ {float(item['fechamento']):.2f}" if item["fechamento"] is not None else "sem cotação"
        variacao = f" · {float(item['variacao_percentual']):+.2f}%" if item["variacao_percentual"] is not None else ""
        referencia = str(item["referencia_em"] or "")[:10]
        texto.append(f"• *{item['ticker']}* ({item['tipo']}): {preco}{variacao}{f' · {referencia}' if referencia else ''}")
    texto.append("\nDados de fechamento e indicadores; não há varredura documental para estes ativos.")
    return "\n".join(texto)


def listar_instrumentos_menu(tipo, session_factory=None):
    """Dados curtos para os botões de ETF/BDR do Telegram."""
    tipo = str(tipo or "").upper()
    if tipo not in {"ETF", "BDR"}:
        raise ValueError("tipo inválido")
    from atualizador_documentos import SessionDB
    sessao = session_factory() if session_factory else SessionDB()
    try:
        return [dict(item) for item in sessao.execute(text("""
            SELECT i.ticker, i.tipo, i.nome, o.fechamento
            FROM instrumentos_internacionais i
            LEFT JOIN LATERAL (
                SELECT fechamento FROM observacoes_instrumentos_internacionais
                WHERE instrumento_id=i.id ORDER BY referencia_em DESC LIMIT 1
            ) o ON TRUE
            WHERE i.ativo=TRUE AND i.tipo=:tipo
            ORDER BY i.ticker
        """), {"tipo": tipo}).mappings().all()]
    finally:
        sessao.close()


def detalhe_instrumento_menu(ticker, session_factory=None):
    """Ficha auditável para o Telegram, sem consultar fontes externas."""
    from atualizador_documentos import SessionDB
    sessao = session_factory() if session_factory else SessionDB()
    try:
        item = sessao.execute(text("""
            SELECT i.id,i.ticker,i.tipo,i.nome,o.fechamento,o.variacao_percentual,
                   o.referencia_em,o.fonte,o.qualidade_fonte
            FROM instrumentos_internacionais i
            LEFT JOIN LATERAL (
                SELECT fechamento,variacao_percentual,referencia_em,fonte,qualidade_fonte
                FROM observacoes_instrumentos_internacionais
                WHERE instrumento_id=i.id ORDER BY referencia_em DESC LIMIT 1
            ) o ON TRUE WHERE i.ticker=:ticker AND i.ativo=TRUE
        """), {"ticker": str(ticker or "").upper()}).mappings().first()
        if not item:
            return None, []
        metricas = sessao.execute(text("""
            SELECT chave,valor_numerico,valor_texto,unidade,fonte,qualidade_fonte
            FROM metricas_instrumentos_internacionais
            WHERE instrumento_id=:id ORDER BY chave LIMIT 12
        """), {"id": item["id"]}).mappings().all()
        return dict(item), [dict(metrica) for metrica in metricas]
    finally:
        sessao.close()


def avaliar_oportunidade_instrumento(item):
    """Aplica uma triagem conservadora; nunca equivale a recomendação de compra."""
    tipo = str(item.get("tipo") or "").upper()
    liquidez = _numero(item.get("liquidez_media_30d_brl"))
    distancia = _numero(item.get("distancia_maxima_1a"))
    volatilidade = _numero(item.get("volatilidade_30d"))
    if tipo not in {"ETF", "BDR"} or liquidez is None or distancia is None:
        return None
    piso_liquidez = 100_000 if tipo == "ETF" else 30_000
    queda_minima = -7 if tipo == "ETF" else -12
    teto_volatilidade = 60 if tipo == "ETF" else 75
    if liquidez < piso_liquidez or distancia > queda_minima:
        return None
    if volatilidade is not None and volatilidade > teto_volatilidade:
        return None
    # Mais desconto até a máxima e mais liquidez aumentam a prioridade, mas
    # não substituem análise do índice/empresa e dos riscos específicos.
    pontuacao = min(abs(distancia) / 4, 6) + min(liquidez / 500_000, 3)
    return {"score": round(pontuacao, 2), "motivos": [
        f"{abs(distancia):.1f}% abaixo da máxima do período coletado",
        f"liquidez média de R$ {liquidez:,.0f}/dia",
    ]}


def listar_oportunidades_instrumentos(tipo=None, limite=8, session_factory=None):
    """Lista candidatos com dados suficientes e origem explícita."""
    from atualizador_documentos import SessionDB
    sessao = session_factory() if session_factory else SessionDB()
    try:
        linhas = sessao.execute(text("""
          WITH ultima AS (
            SELECT DISTINCT ON (instrumento_id) instrumento_id, referencia_em, fechamento, variacao_percentual
            FROM observacoes_instrumentos_internacionais
            ORDER BY instrumento_id, referencia_em DESC
          ), metricas AS (
            SELECT instrumento_id,
              MAX(valor_numerico) FILTER (WHERE chave='liquidez_media_30d_brl') AS liquidez_media_30d_brl,
              MAX(valor_numerico) FILTER (WHERE chave='distancia_maxima_1a') AS distancia_maxima_1a,
              MAX(valor_numerico) FILTER (WHERE chave='volatilidade_30d') AS volatilidade_30d
            FROM metricas_instrumentos_internacionais GROUP BY instrumento_id
          )
          SELECT i.ticker,i.tipo,i.nome,i.indice_referencia,u.referencia_em,u.fechamento,u.variacao_percentual,
                 m.liquidez_media_30d_brl,m.distancia_maxima_1a,m.volatilidade_30d
          FROM instrumentos_internacionais i
          JOIN ultima u ON u.instrumento_id=i.id
          LEFT JOIN metricas m ON m.instrumento_id=i.id
          WHERE i.ativo=TRUE AND (:tipo='' OR i.tipo=:tipo)
            AND u.referencia_em >= NOW() - INTERVAL '10 days'
        """), {"tipo": str(tipo or "").upper()}).mappings().all()
        candidatos = []
        for linha in linhas:
            item = dict(linha)
            avaliacao = avaliar_oportunidade_instrumento(item)
            if avaliacao:
                candidatos.append({**item, **avaliacao})
        candidatos.sort(key=lambda x: x["score"], reverse=True)
        return candidatos[:max(1, min(int(limite), 20))]
    finally:
        sessao.close()
