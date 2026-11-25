"""Entrega somente imagens raster aprovadas e previamente armazenadas."""
from __future__ import annotations
from io import BytesIO
from hashlib import sha256
from PIL import Image
from sqlalchemy import text
import re

DDL_BLOBS = """
CREATE TABLE IF NOT EXISTS portfolio_logo_blobs (
    asset_type varchar(12) NOT NULL, logo_key varchar(32) NOT NULL,
    versao char(64) NOT NULL, conteudo bytea NOT NULL,
    aprovado boolean NOT NULL DEFAULT false, criado_em timestamptz NOT NULL DEFAULT NOW(),
    PRIMARY KEY(asset_type,logo_key,versao),
    CHECK(octet_length(conteudo)<=65536)
)
"""
DDL_ALIASES = """
CREATE TABLE IF NOT EXISTS portfolio_logo_aliases (
    asset_type varchar(12) NOT NULL, ticker varchar(20) NOT NULL,
    logo_key varchar(32) NOT NULL, versao char(64) NOT NULL,
    PRIMARY KEY(asset_type,ticker),
    FOREIGN KEY(asset_type,logo_key,versao) REFERENCES portfolio_logo_blobs(asset_type,logo_key,versao)
)
"""

def converter(conteudo):
    if not conteudo or len(conteudo)>512*1024:
        raise ValueError("imagem_ausente_ou_grande")
    with Image.open(BytesIO(conteudo)) as im:
        if im.format not in {"PNG","JPEG","WEBP"} or im.width*im.height>4_000_000:
            raise ValueError("formato_ou_dimensao_invalida")
        im.thumbnail((160,160))
        saida=BytesIO()
        im.convert("RGBA").save(saida,format="WEBP",quality=80,method=4)
    dados=saida.getvalue()
    if len(dados)>65536:
        raise ValueError("logo_web_muito_grande")
    return dados

def chave_valida(classe,chave,versao):
    return classe in {"stock","fii","etf","bdr","crypto"} and bool(re.fullmatch(r"[A-Z0-9._-]{1,32}",chave)) and bool(re.fullmatch(r"[0-9a-f]{64}",versao))

def ler_logo(classe,chave,versao,session_factory=None):
    from services.portfolio_catalogo import _origem_media
    if not _origem_media() or not chave_valida(classe,chave,versao):
        return None
    if session_factory is None:
        from pipeline_dados.conexao import obter_session_factory
        session_factory=obter_session_factory()
    with session_factory() as s:
        if not s.execute(text("SELECT to_regclass('public.portfolio_logo_blobs')")).scalar():
            return None
        dados=s.execute(text("""
            SELECT conteudo FROM portfolio_logo_blobs
            WHERE asset_type=:classe AND logo_key=:chave AND versao=:versao AND aprovado
        """),{"classe":classe,"chave":chave,"versao":versao}).scalar()
        return bytes(dados) if dados is not None else None

def cadastrar_logo(sessao,classe,chave,tickers,conteudo):
    dados=converter(conteudo)
    versao=sha256(dados).hexdigest()
    if not chave_valida(classe,chave,versao):
        raise ValueError("identidade_invalida")
    sessao.execute(text(DDL_BLOBS))
    sessao.execute(text(DDL_ALIASES))
    sessao.execute(text("""
        INSERT INTO portfolio_logo_blobs(asset_type,logo_key,versao,conteudo,aprovado)
        VALUES (:classe,:chave,:versao,:dados,true)
        ON CONFLICT(asset_type,logo_key,versao) DO UPDATE SET aprovado=true
    """),{"classe":classe,"chave":chave,"versao":versao,"dados":dados})
    sessao.execute(text("""
        INSERT INTO portfolio_logo_aliases(asset_type,ticker,logo_key,versao)
        VALUES (:classe,:ticker,:chave,:versao)
        ON CONFLICT(asset_type,ticker) DO UPDATE SET logo_key=EXCLUDED.logo_key,versao=EXCLUDED.versao
    """),[{"classe":classe,"ticker":t,"chave":chave,"versao":versao} for t in sorted(set(tickers))])
    return versao
