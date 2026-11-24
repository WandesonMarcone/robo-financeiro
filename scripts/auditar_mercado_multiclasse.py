"""Confirma que cada classe do mercado tem fechamento recente no Neon."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text


def _idade_dias(valor, agora):
    if valor is None:
        return None
    if getattr(valor, "tzinfo", None) is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return (agora.date() - valor.astimezone(timezone.utc).date()).days


def executar(session_factory=None, agora=None):
    from atualizador_documentos import SessionDB

    agora = agora or datetime.now(timezone.utc)
    sessao = session_factory() if session_factory else SessionDB()
    try:
        instrumentos = sessao.execute(text("""
            SELECT i.ticker, i.tipo, MAX(o.referencia_em) AS ultima_referencia
            FROM instrumentos_internacionais i
            LEFT JOIN observacoes_instrumentos_internacionais o ON o.instrumento_id=i.id
            WHERE i.ativo=TRUE
            GROUP BY i.id, i.ticker, i.tipo
            ORDER BY i.tipo, i.ticker
        """)).mappings().all()
        macro = sessao.execute(text("""
            SELECT s.codigo, MAX(o.referencia_em) AS ultima_referencia
            FROM series_mercado s
            LEFT JOIN observacoes_mercado o ON o.serie_id=s.id
            WHERE s.ativa=TRUE
            GROUP BY s.id, s.codigo ORDER BY s.codigo
        """)).mappings().all()
        tesouro = sessao.execute(text("""
            SELECT MAX(referencia_em) AS ultima_referencia,
                   COUNT(DISTINCT (nome_titulo, vencimento)) AS titulos
            FROM titulos_tesouro_observacoes
        """)).mappings().one()
    finally:
        sessao.close()

    pendentes = []
    cobertura = {}
    for item in instrumentos:
        tipo = item["tipo"]
        idade = _idade_dias(item["ultima_referencia"], agora)
        limite = 2 if tipo == "CRIPTO" else 4
        cobertura.setdefault(tipo, {"total": 0, "recentes": 0, "atrasados": []})
        cobertura[tipo]["total"] += 1
        if idade is not None and idade <= limite:
            cobertura[tipo]["recentes"] += 1
        else:
            cobertura[tipo]["atrasados"].append(item["ticker"])
            pendentes.append(f"{tipo}:{item['ticker']}")

    macro_atrasado = [item["codigo"] for item in macro
                      if (_idade_dias(item["ultima_referencia"], agora) is None
                          or _idade_dias(item["ultima_referencia"], agora) > 10)]
    idade_tesouro = _idade_dias(tesouro["ultima_referencia"], agora)
    tesouro_ok = bool(tesouro["titulos"]) and idade_tesouro is not None and idade_tesouro <= 10
    if macro_atrasado:
        pendentes.extend(f"MACRO:{codigo}" for codigo in macro_atrasado)
    if not tesouro_ok:
        pendentes.append("TESOURO")
    return {
        "ok": not pendentes,
        "instrumentos": cobertura,
        "macro": {"total": len(macro), "atrasados": macro_atrasado},
        "tesouro": {"titulos": int(tesouro["titulos"] or 0), "idade_dias": idade_tesouro, "ok": tesouro_ok},
        "pendentes": pendentes,
    }


def main():
    resultado = executar()
    print(resultado)
    if not resultado["ok"]:
        raise SystemExit("cobertura_multiclasse_incompleta")


if __name__ == "__main__":
    main()
