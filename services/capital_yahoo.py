"""Observações Yahoo: ações informadas e total implícito, não capital emitido."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from sqlalchemy import text

DDL = """
CREATE TABLE IF NOT EXISTS capital_yahoo_tickers (
    ticker varchar(20) PRIMARY KEY, cnpj varchar(14) NOT NULL,
    shares_outstanding bigint, implied_shares_outstanding bigint, float_shares bigint,
    coletado_em timestamptz NOT NULL,
    CHECK(shares_outstanding IS NULL OR shares_outstanding>0),
    CHECK(implied_shares_outstanding IS NULL OR implied_shares_outstanding>0),
    CHECK(float_shares IS NULL OR float_shares>=0)
)
"""

def _quantidade(v, zero=False):
    try:
        d=Decimal(str(v))
        if d.is_finite() and d==d.to_integral_value() and (d>0 or (zero and d==0)) and d<=2**53-1:
            return int(d)
    except (InvalidOperation,ValueError,TypeError,OverflowError):
        pass
    return None

def observar(ticker, info):
    info=info or {}
    if info.get("symbol") and str(info["symbol"]).upper()!=f"{ticker}.SA":
        return None
    s=_quantidade(info.get("sharesOutstanding"))
    i=_quantidade(info.get("impliedSharesOutstanding"))
    fl=_quantidade(info.get("floatShares"),zero=True)
    if s is None and i is None and fl is None:
        return None
    return {"ticker":ticker,"shares_outstanding":s,"implied_shares_outstanding":i,
            "float_shares":fl,"coletado_em":datetime.now(timezone.utc)}

def persistir(observacoes,session_factory=None):
    if not observacoes:return 0
    if session_factory is None:
        from pipeline_dados.conexao import obter_session_factory
        session_factory=obter_session_factory()
    with session_factory() as s:
        s.execute(text(DDL))
        if not s.execute(text("SELECT to_regclass('public.cadastro_cnpj_acoes')")).scalar():
            return 0
        ids=dict(s.execute(text("SELECT ticker,cnpj FROM cadastro_cnpj_acoes")).all())
        registros=[dict(obs,cnpj=ids[obs["ticker"]]) for obs in observacoes if ids.get(obs["ticker"])]
        if registros:
            s.execute(text("""
                INSERT INTO capital_yahoo_tickers(ticker,cnpj,shares_outstanding,implied_shares_outstanding,float_shares,coletado_em)
                VALUES (:ticker,:cnpj,:shares_outstanding,:implied_shares_outstanding,:float_shares,:coletado_em)
                ON CONFLICT(ticker) DO UPDATE SET cnpj=EXCLUDED.cnpj,shares_outstanding=EXCLUDED.shares_outstanding,
                    implied_shares_outstanding=EXCLUDED.implied_shares_outstanding,float_shares=EXCLUDED.float_shares,
                    coletado_em=EXCLUDED.coletado_em
                WHERE capital_yahoo_tickers.coletado_em<=EXCLUDED.coletado_em
            """),registros)
        s.commit()
    return len(registros)

def ler(sessao, cnpj=None):
    if not sessao.execute(text("SELECT to_regclass('public.capital_yahoo_tickers')")).scalar():return []
    sql="""SELECT y.* FROM capital_yahoo_tickers y
        JOIN cadastro_cnpj_acoes c ON c.ticker=y.ticker AND c.cnpj=y.cnpj
        WHERE y.coletado_em>=NOW()-INTERVAL '7 days'"""
    if cnpj:sql+=" AND y.cnpj=:cnpj"
    return [dict(r) for r in sessao.execute(text(sql),{"cnpj":cnpj} if cnpj else {}).mappings()]

def resumir(ticker,cnpj,observacoes):
    grupo=[r for r in observacoes if cnpj and r["cnpj"]==cnpj]
    atual=next((r for r in grupo if r["ticker"]==ticker),{})
    simples=[r for r in grupo if not r["ticker"].endswith("11")]
    candidatos={r["implied_shares_outstanding"] for r in simples
                if r.get("implied_shares_outstanding") is not None}
    estimativa=next(iter(candidatos)) if len(candidatos)==1 else None
    if estimativa is not None and any((r.get("shares_outstanding") or 0)>estimativa for r in simples):
        estimativa=None
    quantidade=atual.get("shares_outstanding") if not ticker.endswith("11") else None
    datas=[r["coletado_em"] for r in simples if estimativa is not None and r.get("implied_shares_outstanding")==estimativa]
    if atual.get("coletado_em"):datas.append(atual["coletado_em"])
    return {"ticker_shares":quantidade,"company_shares":estimativa,
            "reference_date":min(datas).isoformat() if datas else None,
            "source":"YAHOO_FINANCE","status":"ESTIMATIVA_YAHOO" if quantidade is not None or estimativa is not None else "PENDENTE_CONCILIACAO",
            "ticker_basis":"SHARES_OUTSTANDING_NAO_CONCILIADO",
            "company_basis":"IMPLIED_SHARES_OUTSTANDING_ESTIMATIVA",
            "yahoo_conflict":len(candidatos)>1,
            "yahoo_shares_outstanding":atual.get("shares_outstanding"),
            "yahoo_implied_shares_outstanding":atual.get("implied_shares_outstanding"),
            "yahoo_float_shares":atual.get("float_shares")}
