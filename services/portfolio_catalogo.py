"""Catálogo somente leitura, a partir do Neon consolidado, sem scraping no GET."""
from __future__ import annotations

import os
import time
import math
import unicodedata
from threading import Lock
from urllib.parse import urlsplit
from sqlalchemy import text

CLASSES = {"stock":"ACAO", "fii":"FII", "etf":"ETF", "bdr":"BDR", "crypto":"CRIPTO"}
_CACHE = {}
_LOCK = Lock()
TTL = 300

def _normalizar(valor):
    return "".join(c for c in unicodedata.normalize("NFKD",str(valor or "")).casefold() if not unicodedata.combining(c)).strip()

def _numero(v):
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None

def _data(v):
    return v.isoformat() if hasattr(v,"isoformat") else v

def _origem_media():
    if os.getenv("PORTFOLIO_PUBLIC_LOGOS_ENABLED","").lower() not in ("true","1"):
        return None
    base = os.getenv("PORTFOLIO_PUBLIC_MEDIA_ORIGIN","").strip().rstrip("/")
    try:
        p = urlsplit(base)
        if p.scheme == "https" and p.hostname and not (p.username or p.password or p.query or p.fragment or p.path):
            return base
    except ValueError:
        pass
    return None

def _url_logo(classe, chave, versao):
    base = _origem_media()
    if not (base and chave and versao):
        return None
    return f"{base}/api/v1/media/logos/{classe}/{chave}/{versao}"

def _ler_neon(classe, session_factory=None):
    tipo = CLASSES[classe]
    if session_factory is None:
        from pipeline_dados.conexao import obter_session_factory
        session_factory = obter_session_factory()
    with session_factory() as s:
        if classe in ("stock","fii"):
            snapshot = "snapshots_acoes" if classe=="stock" else "snapshots_fiis"
            oficial = classe=="stock" and bool(s.execute(text("SELECT to_regclass('public.cadastro_cnpj_acoes')")).scalar())
            # Identificadores SQL são constantes internas, nunca entrada do usuário.
            join_oficial = "LEFT JOIN cadastro_cnpj_acoes co ON co.ticker=u.ticker" if oficial else ""
            nome_oficial = "co.nome_emissor," if oficial else ""
            setor_oficial = "co.setor," if oficial else ""
            sql = f"""
                WITH universo AS (
                    SELECT ticker FROM ativos WHERE tipo::text=:tipo
                    UNION SELECT ticker FROM ativos_catalogo WHERE tipo::text=:tipo
                )
                SELECT u.ticker, COALESCE({nome_oficial}e.nome_comercial,e.nome,c.nome_emissor) AS name,
                       COALESCE(sc.setor,c.setor,{setor_oficial}NULL) AS sector,
                       sc.subsetor AS subsector, obs.preco AS price, obs.data_referencia AS updated_at,
                       obs.fonte AS price_source
                FROM universo u
                LEFT JOIN ativos a ON a.ticker=u.ticker AND a.tipo::text=:tipo
                LEFT JOIN ativos_catalogo c ON c.ticker=u.ticker AND c.tipo::text=:tipo
                {join_oficial}
                LEFT JOIN LATERAL (
                    SELECT em.id,em.nome,em.nome_comercial FROM empresa_ativos ea
                    JOIN empresas em ON em.id=ea.empresa_id WHERE ea.ativo_id=a.id
                    ORDER BY ea.id LIMIT 1
                ) e ON TRUE
                LEFT JOIN LATERAL (
                    SELECT st.nome AS setor,sub.nome AS subsetor
                    FROM empresa_segmentos es JOIN setores st ON st.id=es.setor_id
                    LEFT JOIN subsetores sub ON sub.id=es.subsetor_id
                    WHERE es.empresa_id=e.id AND es.vigente AND es.principal
                    ORDER BY es.id LIMIT 1
                ) sc ON TRUE
                LEFT JOIN LATERAL (
                    SELECT preco,data_referencia,fonte FROM {snapshot}
                    WHERE ativo_id=a.id AND preco IS NOT NULL
                    ORDER BY data_referencia DESC,id DESC LIMIT 1
                ) obs ON TRUE ORDER BY u.ticker
            """
        else:
            sql = """
                SELECT i.ticker,i.nome AS name,NULL AS sector,i.indice_referencia AS subsector,
                       o.fechamento AS price,o.referencia_em AS updated_at,o.fonte AS price_source
                FROM instrumentos_internacionais i
                LEFT JOIN LATERAL (
                    SELECT fechamento,referencia_em,fonte FROM observacoes_instrumentos_internacionais
                    WHERE instrumento_id=i.id AND fechamento IS NOT NULL
                    ORDER BY referencia_em DESC,id DESC LIMIT 1
                ) o ON TRUE WHERE i.ativo AND i.tipo=:tipo ORDER BY i.ticker
            """
        rows = [dict(x) for x in s.execute(text(sql),{"tipo":tipo}).mappings()]
        logos = {}
        if _origem_media() and s.execute(text("SELECT to_regclass('public.portfolio_logo_aliases')")).scalar():
            logos = {r["ticker"]:dict(r) for r in s.execute(text("""
                SELECT a.ticker,a.logo_key,a.versao FROM portfolio_logo_aliases a
                JOIN portfolio_logo_blobs b ON b.asset_type=a.asset_type AND b.logo_key=a.logo_key AND b.versao=a.versao
                WHERE a.asset_type=:classe AND b.aprovado
            """),{"classe":classe}).mappings()}
    resultado = {}
    for r in rows:
        ticker = str(r["ticker"] or "").strip().upper()
        if not ticker:
            continue
        logo = logos.get(ticker,{})
        resultado[ticker] = {
            "ticker":ticker,"asset_type":classe,"name":r.get("name") or None,
            "sector":r.get("sector") or None,"subsector":r.get("subsector") or None,
            "price":_numero(r.get("price")),"updated_at":_data(r.get("updated_at")),
            "price_source":r.get("price_source"),"source":"robo_financeiro",
            "logo_url":_url_logo(classe,logo.get("logo_key"),logo.get("versao")),
        }
    return sorted(resultado.values(),key=lambda x:x["ticker"])

def obter_catalogo(classe):
    agora=time.monotonic()
    with _LOCK:
        cache=_CACHE.get(classe)
        if cache and agora-cache[0]<TTL:
            return cache[1]
    rows=_ler_neon(classe)
    with _LOCK:
        _CACHE[classe]=(agora,rows)
    return rows

def limpar_cache():
    with _LOCK:
        _CACHE.clear()

def obter_item(classe,ticker):
    return next((dict(x) for x in obter_catalogo(classe) if x["ticker"]==ticker),None)

def paginar(rows,page=1,page_size=24,q="",sector=""):
    setores=sorted({r["sector"] for r in rows if r.get("sector")},key=_normalizar)
    termo=_normalizar(q)
    setor=_normalizar(sector)
    filtrados=[r for r in rows if (not setor or _normalizar(r.get("sector"))==setor)
               and (not termo or termo in _normalizar(r["ticker"]) or termo in _normalizar(r.get("name")))]
    filtrados.sort(key=lambda r:r["ticker"])
    inicio=(page-1)*page_size
    return {"data":filtrados[inicio:inicio+page_size],"total":len(filtrados),
            "has_more":inicio+page_size<len(filtrados),"sectors":setores,
            "page":page,"page_size":page_size}
