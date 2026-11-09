"""Leituras curtas e seguras para Telegram e Central administrativa."""
from sqlalchemy import text


def resumo_mercado(limite_historico=45):
    from atualizador_documentos import SessionDB
    sessao = SessionDB()
    try:
        series = sessao.execute(text("""
            WITH ultimas AS (
                SELECT DISTINCT ON (o.serie_id) o.serie_id, o.referencia_em, o.valor,
                       o.coletado_em
                FROM observacoes_mercado o
                ORDER BY o.serie_id, o.referencia_em DESC
            )
            SELECT s.codigo, s.nome, s.classe, s.fonte, s.periodicidade,
                   u.referencia_em, u.valor, u.coletado_em
            FROM series_mercado s LEFT JOIN ultimas u ON u.serie_id=s.id
            WHERE s.ativa=TRUE
            ORDER BY CASE s.codigo
              WHEN 'SELIC_META' THEN 1 WHEN 'SELIC_EFETIVA' THEN 2
              WHEN 'CDI' THEN 3 WHEN 'IPCA' THEN 4 WHEN 'USD_BRL_PTAX' THEN 5
              ELSE 99 END, s.codigo
        """)).mappings().all()
        historico = sessao.execute(text("""
            SELECT s.codigo, o.referencia_em, o.valor
            FROM observacoes_mercado o JOIN series_mercado s ON s.id=o.serie_id
            WHERE s.codigo IN ('SELIC_META','SELIC_EFETIVA','CDI','IPCA','USD_BRL_PTAX')
              AND o.referencia_em >= NOW() - INTERVAL '90 days'
            ORDER BY s.codigo, o.referencia_em ASC
        """)).mappings().all()
        tesouro = sessao.execute(text("""
            SELECT DISTINCT ON (nome_titulo, vencimento) nome_titulo, vencimento,
                   referencia_em, taxa_compra, taxa_venda, preco_compra, preco_venda,
                   fonte, coletado_em
            FROM titulos_tesouro_observacoes
            ORDER BY nome_titulo, vencimento, referencia_em DESC
            LIMIT 80
        """)).mappings().all()
        indices = sessao.execute(text("""
            SELECT DISTINCT ON (indice) indice, data_pregao, abertura, maxima, minima,
                   fechamento, fechamento_anterior, variacao_percentual
            FROM indices_mercado_diario
            WHERE indice IN ('Ibovespa', 'IFIX')
            ORDER BY indice, data_pregao DESC
        """)).mappings().all()
        return {
            "series": [{**dict(r), "referencia_em": r["referencia_em"].isoformat() if r["referencia_em"] else None,
                        "coletado_em": r["coletado_em"].isoformat() if r["coletado_em"] else None} for r in series],
            "history": [{**dict(r), "referencia_em": r["referencia_em"].isoformat()} for r in historico],
            "treasury": [{**dict(r), "vencimento": r["vencimento"].isoformat() if r["vencimento"] else None,
                          "referencia_em": r["referencia_em"].isoformat(),
                          "coletado_em": r["coletado_em"].isoformat()} for r in tesouro],
            "indices": [{**dict(r), "data_pregao": r["data_pregao"].isoformat() if r["data_pregao"] else None}
                        for r in indices],
        }
    finally:
        sessao.close()


def mensagem_mercado():
    dados = resumo_mercado()
    linhas = ["📊 *Mercado e macroeconomia*"]
    rotulos = {"SELIC_META": "Meta Selic", "SELIC_EFETIVA": "Selic efetiva", "CDI": "CDI", "IPCA": "IPCA", "USD_BRL_PTAX": "Dólar PTAX"}
    for item in dados["series"]:
        valor = item.get("valor")
        if valor is None:
            continue
        codigo = item.get("codigo")
        casas = 4 if codigo == "USD_BRL_PTAX" else 4
        referencia = item.get("referencia_em") or "sem referência"
        linhas.append(f"• *{rotulos.get(codigo, item['nome'])}:* {float(valor):.{casas}f} — {referencia[:10]}")
    for item in dados.get("indices") or []:
        fechamento = item.get("fechamento")
        if fechamento is None:
            continue
        variacao = item.get("variacao_percentual")
        sufixo = f" · {float(variacao):+.2f}%" if variacao is not None else ""
        linhas.append(f"• *{item['indice']}:* {float(fechamento):,.2f}{sufixo} — {(item.get('data_pregao') or '')[:10]}")
    if dados["treasury"]:
        linhas.append("\n🏛️ *Tesouro Direto* — última tabela oficial disponível")
        for item in dados["treasury"][:6]:
            taxa = item.get("taxa_compra")
            venc = item.get("vencimento") or "—"
            linhas.append(f"• {item['nome_titulo']} {venc}: {float(taxa):.3f}% a.a." if taxa is not None else f"• {item['nome_titulo']} {venc}")
    if len(linhas) == 1:
        linhas.append("Ainda não há dados coletados. Use /atualizar_macro ou aguarde o próximo ciclo.")
    return "\n".join(linhas)
