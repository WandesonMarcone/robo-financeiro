"""BD_Acoes autoriza a coleta; Neon mantém o histórico do universo."""
import re
from sqlalchemy import text

PADRAO = re.compile(r"[A-Z][A-Z0-9]{3}[0-9]{1,2}")
DDL = """CREATE TABLE IF NOT EXISTS universo_acoes_autorizadas (
ticker varchar(20) PRIMARY KEY,
sincronizado_em timestamptz NOT NULL DEFAULT now(),
ativo boolean NOT NULL DEFAULT true,
desativado_em timestamptz)"""

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
    sessao.execute(text("""
        INSERT INTO universo_acoes_autorizadas(ticker,ativo,desativado_em)
        VALUES (:ticker,TRUE,NULL)
        ON CONFLICT(ticker) DO UPDATE SET
          sincronizado_em=now(),ativo=TRUE,desativado_em=NULL
    """),
                   [{"ticker":t} for t in sorted(tickers)])
    # A saída da lista oficial nunca apaga a identidade, cotações ou
    # documentos: somente encerra a autorização corrente de coleta.
    sessao.execute(text("""
        UPDATE universo_acoes_autorizadas
           SET ativo=FALSE,desativado_em=COALESCE(desativado_em,NOW())
         WHERE ativo=TRUE AND NOT (ticker = ANY(:tickers))
    """),{"tickers":sorted(tickers)})
    sessao.execute(text("""
        INSERT INTO ativos(ticker,cnpj,tipo)
        SELECT ticker,NULL,'ACAO' FROM universo_acoes_autorizadas WHERE ativo=TRUE
        ON CONFLICT(ticker) DO NOTHING
    """))

def ler_universo_neon(sessao):
    if not sessao.execute(text("SELECT to_regclass('public.universo_acoes_autorizadas')")).scalar():
        return None
    return set(sessao.execute(text("SELECT ticker FROM universo_acoes_autorizadas WHERE ativo=TRUE")).scalars())
