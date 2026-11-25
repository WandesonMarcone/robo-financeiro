"""BD_Acoes autoriza a coleta; Neon espelha a lista sem apagar históricos."""
import re
from sqlalchemy import text

PADRAO = re.compile(r"[A-Z][A-Z0-9]{3}[0-9]{1,2}")
DDL = """CREATE TABLE IF NOT EXISTS universo_acoes_autorizadas (
ticker varchar(20) PRIMARY KEY, sincronizado_em timestamptz NOT NULL DEFAULT now())"""

def normalizar_ticker_acao(v):
    t = str(v or "").strip().upper()
    return t if PADRAO.fullmatch(t) else None

def ler_planilha(planilha):
    tickers = {normalizar_ticker_acao(v) for v in planilha.worksheet("BD_Acoes").col_values(1)[1:]}
    tickers.discard(None)
    if not tickers:
        raise ValueError("BD_Acoes_vazia_ou_indisponivel")
    return tickers

def sincronizar_universo(sessao, tickers):
    if not tickers:
        raise ValueError("universo_vazio")
    sessao.execute(text(DDL))
    sessao.execute(text("INSERT INTO universo_acoes_autorizadas(ticker) VALUES (:ticker) ON CONFLICT(ticker) DO UPDATE SET sincronizado_em=now()"),
                   [{"ticker":t} for t in sorted(tickers)])
    sessao.execute(text("DELETE FROM universo_acoes_autorizadas WHERE NOT (ticker = ANY(:tickers))"),{"tickers":sorted(tickers)})
    sessao.execute(text("INSERT INTO ativos(ticker,cnpj,tipo) SELECT ticker,NULL,'ACAO' FROM universo_acoes_autorizadas ON CONFLICT(ticker) DO NOTHING"))

def ler_universo_neon(sessao):
    if not sessao.execute(text("SELECT to_regclass('public.universo_acoes_autorizadas')")).scalar():
        return None
    return set(sessao.execute(text("SELECT ticker FROM universo_acoes_autorizadas")).scalars())
