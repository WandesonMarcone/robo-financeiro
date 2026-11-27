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


def _formatar_macro(item):
    codigo = item.get("codigo")
    try:
        valor = float(item.get("valor"))
    except (TypeError, ValueError):
        return None
    if codigo == "USD_BRL_PTAX":
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if codigo in {"CDI", "SELIC_EFETIVA"} and abs(valor) < 1:
        valor *= 100
    return f"{valor:.2f}%".replace(".", ",")


def mensagem_mercado():
    """Resumo curto, com unidades corretas e sem preços brutos do Tesouro."""
    dados = resumo_mercado()
    linhas = ["📊 *Mercado — resumo da última coleta*"]
    rotulos = {
        "SELIC_META": "Meta Selic",
        "SELIC_EFETIVA": "Selic efetiva",
        "CDI": "CDI",
        "IPCA": "IPCA mensal",
        "USD_BRL_PTAX": "Dólar PTAX",
    }
    for item in dados["series"]:
        valor = _formatar_macro(item)
        if valor is None:
            continue
        referencia = (item.get("referencia_em") or "")[:10]
        linhas.append(f"• *{rotulos.get(item.get('codigo'), item.get('nome'))}:* {valor} ({referencia})")
    if dados.get("indices"):
        linhas.append("\n📈 *Índices no fechamento*")
        for item in dados["indices"]:
            fechamento = item.get("fechamento")
            if fechamento is None:
                continue
            variacao = item.get("variacao_percentual")
            sufixo = f" · {float(variacao):+.2f}%".replace(".", ",") if variacao is not None else ""
            linhas.append(f"• {item['indice']}: {float(fechamento):,.2f}{sufixo}".replace(",", "X").replace(".", ",").replace("X", "."))
    tesouro = dados.get("treasury") or []
    if tesouro:
        linhas.append(f"\n🏛️ *Tesouro Direto* — {len(tesouro)} títulos atualizados")
        for item in tesouro[:3]:
            taxa = item.get("taxa_compra")
            if taxa is None:
                continue
            venc = item.get("vencimento") or "sem vencimento"
            linhas.append(f"• {item['nome_titulo']} ({venc}): {float(taxa):.2f}% a.a.".replace(".", ","))
        if len(tesouro) > 3:
            linhas.append("Use /mercado para consultar a lista completa.")
    if len(linhas) == 1:
        linhas.append("Ainda não há dados coletados.")
    return "\n".join(linhas)
