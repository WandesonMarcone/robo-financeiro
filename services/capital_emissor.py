"""Capital por emissor/CNPJ, não por ticker. Valores não conciliados não viram quantidade oficial."""
from datetime import date
from decimal import Decimal, InvalidOperation
from sqlalchemy import text

DDL = """
CREATE TABLE IF NOT EXISTS capital_social_emissores (
    cnpj varchar(14) NOT NULL, referencia date NOT NULL, fonte text NOT NULL,
    url_origem text NOT NULL, qualidade text NOT NULL,
    ordinarias bigint NOT NULL, preferenciais bigint NOT NULL, emitidas bigint NOT NULL,
    tesouraria bigint, classes jsonb NOT NULL DEFAULT '{}'::jsonb,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(cnpj,referencia,fonte),
    CHECK(ordinarias>=0 AND preferenciais>=0 AND emitidas>0 AND ordinarias+preferenciais=emitidas),
    CHECK(tesouraria IS NULL OR tesouraria BETWEEN 0 AND emitidas)
)
"""
METRICAS={"acoes_ordinarias","acoes_preferenciais","acoes_emitidas","acoes_tesouraria","acoes_circulacao_ex_tesouraria"}

def inteiro(v):
    try:
        d=Decimal(str(v))
        return int(d) if d.is_finite() and d>=0 and d==d.to_integral_value() else None
    except (InvalidOperation,ValueError,TypeError,OverflowError):
        return None

def reconciliar(ordinarias,preferenciais,total,tesouraria):
    o,p,t,tr=map(inteiro,(ordinarias,preferenciais,total,tesouraria))
    if None in (o,p,t) or t<=0 or o+p!=t or (tr is not None and tr>t):
        return None
    return {"ordinarias":o,"preferenciais":p,"emitidas":t,"tesouraria":tr}

def escala_suspeita(quantidade, lucro, lpa):
    """Triagem, não conversão automática: LPA é média ponderada, não saldo final."""
    try:
        q, l, a=map(Decimal,map(str,(quantidade,lucro,lpa)))
        if not all(x.is_finite() for x in (q,l,a)) or min(q,abs(l),abs(a))<=0:
            return True
        razao=abs(l/a)/q
        return not (Decimal("0.2")<=razao<=Decimal("5"))
    except (InvalidOperation,ValueError,TypeError,ZeroDivisionError):
        return True

def persistir_observacoes(sessao,fundamentos):
    """Preserva o dado CVM bruto consolidado; a unidade precisa de conciliação independente."""
    grupos={}
    for f in fundamentos:
        if f.get("classe")=="ACAO" and f.get("metrica") in METRICAS and f.get("cnpj"):
            g=grupos.setdefault((f["cnpj"],f["periodo_fim"]),{})
            g[f["metrica"]]=f
    if not grupos:
        return
    sessao.execute(text(DDL))
    for (cnpj,ref),g in grupos.items():
        def v(m):return g.get(m,{}).get("valor")
        dados=reconciliar(v("acoes_ordinarias"),v("acoes_preferenciais"),v("acoes_emitidas"),v("acoes_tesouraria"))
        if not dados:continue
        sessao.execute(text("""
            INSERT INTO capital_social_emissores(cnpj,referencia,fonte,url_origem,qualidade,ordinarias,preferenciais,emitidas,tesouraria)
            VALUES (:cnpj,:ref,'CVM_DADOS_ABERTOS',:url,'UNIDADE_PENDENTE',:ordinarias,:preferenciais,:emitidas,:tesouraria)
            ON CONFLICT(cnpj,referencia,fonte) DO UPDATE SET ordinarias=EXCLUDED.ordinarias,
                preferenciais=EXCLUDED.preferenciais,emitidas=EXCLUDED.emitidas,tesouraria=EXCLUDED.tesouraria,
                atualizado_em=now() WHERE capital_social_emissores.qualidade='UNIDADE_PENDENTE'
        """),dict(dados,cnpj=cnpj,ref=ref,url=g["acoes_emitidas"]["url_origem"]))

def obter_capital(ticker,session_factory=None):
    if session_factory is None:
        from pipeline_dados.conexao import obter_session_factory
        session_factory=obter_session_factory()
    with session_factory() as s:
        ident=s.execute(text("SELECT cnpj,nome_emissor FROM cadastro_cnpj_acoes WHERE ticker=:t"),{"t":ticker}).mappings().first()
        if not ident:return None
        cnpj=ident["cnpj"]
        tickers=list(s.execute(text("SELECT ticker FROM cadastro_cnpj_acoes WHERE cnpj=:c ORDER BY ticker"),{"c":cnpj}).scalars())
        resposta={"cnpj":cnpj,"name":ident["nome_emissor"],"tickers":tickers,"capital":None,"status":"PENDENTE_CONCILIACAO"}
        if not s.execute(text("SELECT to_regclass('public.capital_social_emissores')")).scalar():return resposta
        r=s.execute(text("""SELECT * FROM capital_social_emissores WHERE cnpj=:c AND qualidade='CONCILIADO_OFICIAL'
            ORDER BY referencia DESC,atualizado_em DESC LIMIT 1"""),{"c":cnpj}).mappings().first()
        if not r:return resposta
        capital={k:r[k] for k in ("ordinarias","preferenciais","emitidas","tesouraria","fonte","url_origem","qualidade","classes")}
        capital["referencia"]=r["referencia"].isoformat()
        capital["fora_tesouraria"]=r["emitidas"]-r["tesouraria"] if r["tesouraria"] is not None else None
        resposta.update(capital=capital,status="CONCILIADO_OFICIAL")
        return resposta
