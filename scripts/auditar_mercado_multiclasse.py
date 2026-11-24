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
            SELECT i.ticker, i.tipo,
                   MAX(o.referencia_em) AS ultima_referencia,
                   MAX(o.coletado_em) AS ultima_coleta
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
        limite_referencia = 2 if tipo == "CRIPTO" else 4
        idade_coleta = _idade_dias(item.get("ultima_coleta"), agora)
        cobertura.setdefault(tipo, {
            "total": 0, "recentes": 0, "atrasados": [],
            "referencia_atrasada": [],
        })
        cobertura[tipo]["total"] += 1
        # A referência é a última sessão realmente negociada. ETF/BDR pouco
        # líquido pode não formar preço por dias, mas o ON CONFLICT renova
        # coletado_em quando o robô consulta o ativo. Falha operacional é não
        # haver coleta recente, e não a bolsa manter o mesmo fechamento.
        if idade_coleta is not None and idade_coleta <= 2:
            cobertura[tipo]["recentes"] += 1
        else:
            cobertura[tipo]["atrasados"].append(item["ticker"])
            pendentes.append(f"{tipo}:{item['ticker']}")
        if idade is None or idade > limite_referencia:
            cobertura[tipo]["referencia_atrasada"].append(item["ticker"])

    # IPCA é mensal e possui defasagem de divulgação; as demais séries são
    # diárias. Uma janela única de dez dias gerava falha falsa todo mês.
    macro_atrasado = []
    for item in macro:
        limite_macro = 75 if item["codigo"] == "IPCA" else 10
        idade_macro = _idade_dias(item["ultima_referencia"], agora)
        if idade_macro is None or idade_macro > limite_macro:
            macro_atrasado.append(item["codigo"])
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
