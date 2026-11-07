"""Coleta diária auditável de preços e taxas do Tesouro Direto.

Usa o CSV público do Tesouro Transparente, e não uma API comercial. O arquivo
é histórico e é atualizado diariamente; por isso o robô grava somente a última
data-base disponível, de forma idempotente.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime

import requests
from sqlalchemy import text

URL_TESOURO = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv"
)


def _normalizar(chave: str) -> str:
    return "".join(ch for ch in str(chave or "").lower() if ch.isalnum())


def _numero(valor):
    texto = str(valor or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(texto) if texto else None
    except ValueError:
        return None


def _data(valor):
    texto = str(valor or "").strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    return None


def _campo(linha, *nomes):
    mapa = {_normalizar(k): v for k, v in linha.items()}
    for nome in nomes:
        valor = mapa.get(_normalizar(nome))
        if valor not in (None, ""):
            return valor
    return None


def coletar_tesouro_direto(session_factory=None):
    """Baixa o CSV oficial e grava a última data-base por título/vencimento."""
    from atualizador_documentos import SessionDB

    resposta = requests.get(URL_TESOURO, timeout=90)
    resposta.raise_for_status()
    conteudo = resposta.content.decode("utf-8-sig", errors="replace")
    leitor = csv.DictReader(io.StringIO(conteudo), delimiter=";")
    linhas = list(leitor)
    if not linhas:
        return {"fonte": "Tesouro Transparente", "gravadas": 0, "referencia": None}

    parsed = []
    for linha in linhas:
        referencia = _data(_campo(linha, "Data Base", "DataBase"))
        titulo = _campo(linha, "Tipo Titulo", "TipoTitulo", "Titulo")
        vencimento = _data(_campo(linha, "Data Vencimento", "DataVencimento"))
        if referencia and titulo:
            parsed.append((referencia, str(titulo).strip(), vencimento, linha))
    if not parsed:
        raise ValueError("TESOURO_CSV_SEM_COLUNAS_ESPERADAS")
    ultima = max(item[0] for item in parsed)
    lote = [item for item in parsed if item[0].date() == ultima.date()]

    sessao = session_factory() if session_factory else SessionDB()
    try:
        gravadas = 0
        for referencia, titulo, vencimento, linha in lote:
            sessao.execute(text("""
                INSERT INTO titulos_tesouro_observacoes
                    (nome_titulo, vencimento, referencia_em, taxa_compra, taxa_venda,
                     preco_compra, preco_venda, fonte)
                VALUES (:titulo, :vencimento, :referencia, :taxa_compra, :taxa_venda,
                        :preco_compra, :preco_venda, 'TESOURO_TRANSPARENTE')
                ON CONFLICT (nome_titulo, vencimento, referencia_em) DO UPDATE SET
                    taxa_compra=EXCLUDED.taxa_compra, taxa_venda=EXCLUDED.taxa_venda,
                    preco_compra=EXCLUDED.preco_compra, preco_venda=EXCLUDED.preco_venda,
                    fonte=EXCLUDED.fonte, coletado_em=NOW()
            """), {
                "titulo": titulo,
                "vencimento": vencimento.date() if vencimento else None,
                "referencia": referencia,
                "taxa_compra": _numero(_campo(linha, "Taxa Compra Manha", "TaxaCompraManha")),
                "taxa_venda": _numero(_campo(linha, "Taxa Venda Manha", "TaxaVendaManha")),
                "preco_compra": _numero(_campo(linha, "PU Compra Manha", "PUCompraManha")),
                "preco_venda": _numero(_campo(linha, "PU Venda Manha", "PUVendaManha")),
            })
            gravadas += 1
        sessao.commit()
        return {"fonte": "Tesouro Transparente", "gravadas": gravadas,
                "referencia": ultima.date().isoformat()}
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao.close()
