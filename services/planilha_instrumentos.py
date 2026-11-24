"""Fonte operacional dos instrumentos de mercado.

Toda inclusão ou atualização de ativo não documental passa primeiro pela
planilha. O Neon recebe a mesma informação somente depois de a gravação na
planilha ter sido confirmada. Isso evita que painel, Telegram e banco tenham
catálogos diferentes.
"""
from __future__ import annotations

from datetime import datetime


COLUNAS_PLANILHA_INSTRUMENTOS = (
    "TICKER", "NOME", "PREÇO", "VAR. DIA", "ÍNDICE / REFERÊNCIA",
    "LIQUIDEZ MÉDIA 30D", "VOLUME MÉDIO 30D", "DISTÂNCIA MÁXIMA 12M",
    "VOLATILIDADE 30D", "RETORNO COLETADO", "DY", "P/L", "P/VP",
    "FONTE", "DATA REFERÊNCIA", "ATUALIZADO EM",
)


ABAS_POR_TIPO = {
    "ETF": "BD_ETFs",
    "BDR": "BD_BDRs",
    "CRIPTO": "BD_Criptos",
    "MOEDA": "BD_Moedas",
    "INDICE": "BD_Indices",
    "COMMODITY": "BD_Commodities",
}


def _numero(valor):
    try:
        numero = float(valor)
        return numero if numero == numero else None
    except (TypeError, ValueError):
        return None


def abrir_planilha_instrumentos(tipo, planilha=None):
    tipo = str(tipo or "").strip().upper()
    aba_nome = ABAS_POR_TIPO.get(tipo)
    if not aba_nome:
        raise ValueError("tipo sem planilha operacional")
    if planilha is None:
        import config
        from modules.utils import conectar_gspread

        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
    try:
        aba = planilha.worksheet(aba_nome)
    except Exception as exc:
        # Só cria a aba quando ela realmente não existe. Erros de autenticação
        # ou rede não podem ser confundidos com ausência da aba.
        if exc.__class__.__name__ != "WorksheetNotFound":
            raise
        aba = planilha.add_worksheet(
            title=aba_nome, rows=500, cols=len(COLUNAS_PLANILHA_INSTRUMENTOS)
        )
        aba.update(
            [list(COLUNAS_PLANILHA_INSTRUMENTOS)], "A1:P1",
            value_input_option="RAW",
        )
        try:
            aba.freeze(rows=1, cols=1)
        except Exception:
            pass
    linhas = aba.get_all_values()
    if not linhas:
        aba.update(
            [list(COLUNAS_PLANILHA_INSTRUMENTOS)], "A1:P1",
            value_input_option="RAW",
        )
        linhas = [list(COLUNAS_PLANILHA_INSTRUMENTOS)]
    if linhas[0][:len(COLUNAS_PLANILHA_INSTRUMENTOS)] != list(COLUNAS_PLANILHA_INSTRUMENTOS):
        raise RuntimeError(f"cabecalho_invalido:{aba_nome}")
    return aba, linhas


def listar_tickers_planilha(tipo, planilha=None):
    _aba, linhas = abrir_planilha_instrumentos(tipo, planilha=planilha)
    return {
        str(linha[0]).strip().upper()
        for linha in linhas[1:]
        if linha and str(linha[0]).strip()
    }


def gravar_instrumento_planilha(tipo, dados, planilha=None):
    """Faz upsert de uma linha e só retorna depois da confirmação do Sheets."""
    tipo = str(tipo or "").strip().upper()
    ticker = str((dados or {}).get("ticker") or "").strip().upper()
    if not ticker:
        raise ValueError("ticker obrigatório")
    aba, existentes = abrir_planilha_instrumentos(tipo, planilha=planilha)
    por_ticker = {
        str(linha[0]).strip().upper(): indice + 2
        for indice, linha in enumerate(existentes[1:])
        if linha and str(linha[0]).strip()
    }
    numero_linha = por_ticker.get(ticker, len(existentes) + 1)
    referencia = dados.get("referencia_em")
    if hasattr(referencia, "date"):
        referencia = referencia.date().isoformat()
    elif referencia:
        referencia = str(referencia)[:10]
    else:
        referencia = "—"

    def valor(chave, padrao="—"):
        bruto = dados.get(chave)
        numero = _numero(bruto)
        return numero if numero is not None else (bruto if bruto not in (None, "") else padrao)

    linha = [[
        ticker,
        valor("nome"),
        valor("fechamento"),
        valor("variacao_percentual"),
        valor("indice_referencia"),
        valor("liquidez"),
        valor("volume"),
        valor("distancia"),
        valor("volatilidade"),
        valor("retorno"),
        valor("dy"),
        valor("pl"),
        valor("pvp"),
        valor("fonte", "DESCOBERTA_AUTOMATICA"),
        referencia,
        datetime.now().astimezone().strftime("%d/%m/%Y %H:%M"),
    ]]
    aba.update(
        linha, f"A{numero_linha}:P{numero_linha}",
        value_input_option="USER_ENTERED",
    )
    return {"aba": ABAS_POR_TIPO[tipo], "ticker": ticker, "linha": numero_linha}

