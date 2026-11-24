"""Sinais de contexto para macro e Tesouro, sem tratar taxa como ação barata."""
from sqlalchemy import text


def montar_digest_sinais_macro_tesouro(session_factory=None):
    from atualizador_documentos import SessionDB

    sessao = session_factory() if session_factory else SessionDB()
    try:
        macro = sessao.execute(text("""
            WITH ordenadas AS (
              SELECT s.codigo, s.nome, o.referencia_em, o.valor,
                     LAG(o.valor) OVER (PARTITION BY s.id ORDER BY o.referencia_em) AS anterior,
                     ROW_NUMBER() OVER (PARTITION BY s.id ORDER BY o.referencia_em DESC) AS pos
              FROM series_mercado s JOIN observacoes_mercado o ON o.serie_id=s.id
              WHERE s.ativa=TRUE AND s.codigo IN ('USD_BRL_PTAX','SELIC_META','IPCA')
            ) SELECT * FROM ordenadas WHERE pos=1
        """)).mappings().all()
        tesouro = sessao.execute(text("""
            WITH ordenadas AS (
              SELECT nome_titulo, vencimento, referencia_em, taxa_compra,
                     LAG(taxa_compra) OVER (PARTITION BY nome_titulo,vencimento ORDER BY referencia_em) AS anterior,
                     ROW_NUMBER() OVER (PARTITION BY nome_titulo,vencimento ORDER BY referencia_em DESC) AS pos
              FROM titulos_tesouro_observacoes WHERE taxa_compra IS NOT NULL
            ) SELECT * FROM ordenadas WHERE pos=1 AND anterior IS NOT NULL
              AND taxa_compra - anterior >= 0.10
            ORDER BY taxa_compra - anterior DESC LIMIT 4
        """)).mappings().all()
    finally:
        sessao.close()

    linhas = []
    for item in macro:
        if item["valor"] is None or item["anterior"] in (None, 0):
            continue
        variacao = (float(item["valor"]) / float(item["anterior"]) - 1) * 100
        limite = 0.75 if item["codigo"] == "USD_BRL_PTAX" else 3.0
        if abs(variacao) >= limite:
            linhas.append(f"• *{item['nome']}*: movimento de {variacao:+.2f}% na última referência")
    for item in tesouro:
        aumento = float(item["taxa_compra"]) - float(item["anterior"])
        linhas.append(
            f"• *{item['nome_titulo']} {item['vencimento']}*: taxa subiu {aumento:+.2f} p.p. "
            f"para {float(item['taxa_compra']):.2f}% a.a."
        )
    if not linhas:
        return {"texto": "", "tickers": [], "tipo": "macro_tesouro", "itens": []}
    return {
        "texto": "📈 *Sinais de macro e Tesouro*\n\n" + "\n".join(linhas)
                 + "\n\n_Contexto automático; não é recomendação de investimento._",
        "tickers": [], "tipo": "macro_tesouro", "itens": [],
    }
