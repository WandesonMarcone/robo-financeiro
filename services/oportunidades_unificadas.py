"""Consolida sinais de todas as classes cotadas para o alerta de mercado.

Os critérios e a leitura do banco continuam em ``coletor_etfs_bdrs``. Este
módulo apenas transforma candidatos já calculados em uma mensagem curta e
auditável para a rodada unificada; não constitui recomendação de investimento.
"""

from __future__ import annotations

from services.coletor_etfs_bdrs import listar_oportunidades_instrumentos


_ICONE = {"ETF": "🌐", "BDR": "🌍", "CRIPTO": "₿", "MOEDA": "💱"}


def _numero(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _linha(item):
    ticker = str(item.get("ticker") or "").strip().upper()
    distancia = _numero(item.get("distancia_maxima_1a"))
    liquidez = _numero(item.get("liquidez_media_30d_brl"))
    tipo = str(item.get("tipo") or "").upper()
    variacao = _numero(item.get("variacao_percentual"))
    if not ticker:
        return None
    if tipo == "CRIPTO" and distancia is not None:
        movimento = f" | {'alta' if variacao > 0 else 'queda'} {variacao:+.2f}%" if variacao is not None else ""
        return f"• *{ticker}* — {abs(distancia):.1f}% abaixo da máxima do período{movimento}"
    if tipo == "MOEDA" and variacao is not None:
        return f"• *{ticker}* — {'alta' if variacao > 0 else 'queda'} cambial de {variacao:+.2f}%"
    if distancia is None or liquidez is None:
        return None
    return (
        f"• *{ticker}* — {abs(distancia):.1f}% abaixo da máxima do período "
        f"| liquidez média R$ {liquidez:,.0f}/dia"
    )


def montar_digest_oportunidades_instrumentos(
    limite_por_tipo=4,
    listar=None,
):
    """Retorna pacote compatível com o emissor de alertas do robô.

    A consulta só traz observações recentes e que já passaram pela triagem de
    liquidez, distância da máxima e volatilidade. Se não houver candidatos, a
    mensagem fica vazia e nada é enviado ao Telegram.
    """
    buscar = listar or listar_oportunidades_instrumentos
    try:
        limite = max(1, min(int(limite_por_tipo), 8))
    except (TypeError, ValueError):
        limite = 4

    grupos = []
    itens = []
    for tipo in ("ETF", "BDR", "CRIPTO", "MOEDA"):
        candidatos = buscar(tipo=tipo, limite=limite) or []
        linhas = []
        for candidato in candidatos:
            candidato = {"tipo": tipo, **candidato}
            linha = _linha(candidato)
            if not linha:
                continue
            linhas.append(linha)
            ticker = str(candidato.get("ticker") or "").strip().upper()
            if ticker:
                itens.append({
                    "ticker": ticker,
                    "texto": (
                        f"{_ICONE[tipo]} *Candidato monitorado — {tipo}*\n\n"
                        f"{linha.removeprefix('• ')}\n\n"
                        "Triagem automática; analise riscos e fundamentos antes de decidir."
                    ),
                })
        if linhas:
            grupos.append(f"{_ICONE[tipo]} *{tipo}s*\n" + "\n".join(linhas))

    if not grupos:
        return {"texto": "", "tickers": [], "tipo": "instrumento", "itens": []}

    texto = (
        "🔎 *Sinais monitorados — mercado multiclasse*\n\n"
        + "\n\n".join(grupos)
        + "\n\n_É uma triagem automática, não uma recomendação de investimento._"
    )
    return {
        "texto": texto,
        "tickers": [item["ticker"] for item in itens],
        "tipo": "instrumento",
        "itens": itens,
    }
