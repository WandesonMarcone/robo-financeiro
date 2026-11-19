"""Formatadores de retorno documental para Telegram e Central de Controle.

A coleta guarda a lista estruturada no evento operacional; este módulo apenas a
apresenta. Nenhuma mensagem afirma que um PDF foi salvo no Drive: ela relata
documentos novos que foram encontrados e registrados na etapa de coleta.
"""

from __future__ import annotations

LIMITE_TEXTO_TELEGRAM = 3500


def _detalhes(resultado) -> dict:
    funcao = getattr(resultado, "detalhes_painel", None)
    if not callable(funcao):
        return {}
    try:
        dados = funcao() or {}
        return dados if isinstance(dados, dict) else {}
    except Exception:
        return {}


def mensagens_telegram_documentais(resultado, *, titulo: str | None = None) -> list[str]:
    """Monta resumo e itens por ativo sem ultrapassar o limite do Telegram."""
    resumo = str(resultado.mensagem_telegram())
    dados = _detalhes(resultado)
    documentos = list(dados.get("documentos") or [])
    if not documentos:
        return [resumo]

    cabecalho = titulo or "📄 Documentos processados nesta execução"
    linhas = [
        cabecalho,
        f"Total de documentos novos: {len(documentos)}",
        "Detalhamento (ativo — tipo — referência):",
    ]
    for item in documentos:
        ticker = str(item.get("ticker") or "ATIVO NÃO IDENTIFICADO").upper()
        tipo = str(item.get("tipo") or "Tipo não informado")
        data = str(item.get("data") or "Data não informada")
        linhas.append(f"• {ticker} — {tipo} — {data}")

    mensagens = [resumo]
    atual = ""
    for linha in linhas:
        candidata = f"{atual}\n{linha}".strip()
        if atual and len(candidata) > LIMITE_TEXTO_TELEGRAM:
            mensagens.append(atual)
            atual = linha
        else:
            atual = candidata
    if atual:
        mensagens.append(atual)
    return mensagens
