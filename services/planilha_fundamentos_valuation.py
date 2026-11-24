"""Espelho auditável de fundamentos e cobertura, sempre antes do Neon."""
from __future__ import annotations

from datetime import datetime


ABAS = {
    "fundamentos": (
        "BD_Fundamentos",
        (
            "IDENTIFICADOR", "TICKER", "CNPJ", "CLASSE", "PERÍODO INÍCIO",
            "PERÍODO FIM", "EXERCÍCIO", "PERIODICIDADE", "DOCUMENTO", "ESCOPO",
            "DEMONSTRAÇÃO", "CONTA", "MÉTRICA", "VALOR", "UNIDADE", "MOEDA",
            "FONTE", "QUALIDADE", "URL ORIGEM", "ATUALIZADO EM",
        ),
    ),
    "indicadores": (
        "BD_Indicadores_Valuation",
        (
            "IDENTIFICADOR", "TICKER", "CLASSE", "PERÍODO FIM", "EXERCÍCIO",
            "PERIODICIDADE", "INDICADOR", "VALOR", "UNIDADE", "FÓRMULA",
            "QUALIDADE", "ATUALIZADO EM",
        ),
    ),
    "cobertura": (
        "BD_Cobertura_Valuation",
        (
            "CHAVE", "TICKER", "CLASSE", "MÉTODO", "STATUS", "ANOS DISPONÍVEIS",
            "PERÍODO INICIAL", "PERÍODO FINAL", "CAMPOS PRESENTES",
            "CAMPOS AUSENTES", "OBSERVAÇÃO", "ATUALIZADO EM",
        ),
    ),
}

LINHAS_POR_ABA = {
    "fundamentos": 50000,
    "indicadores": 20000,
    "cobertura": 10000,
}


def _coluna(numero: int) -> str:
    resultado = ""
    while numero:
        numero, resto = divmod(numero - 1, 26)
        resultado = chr(65 + resto) + resultado
    return resultado


def _planilha_padrao():
    import config
    from modules.utils import conectar_gspread

    return conectar_gspread().open_by_url(config.SPREADSHEET_URL)


def _abrir(tipo: str, planilha=None):
    nome, colunas = ABAS[tipo]
    planilha = planilha or _planilha_padrao()
    try:
        aba = planilha.worksheet(nome)
    except Exception as exc:
        if exc.__class__.__name__ != "WorksheetNotFound":
            raise
        aba = planilha.add_worksheet(
            title=nome,
            rows=LINHAS_POR_ABA[tipo],
            cols=len(colunas),
        )
        aba.update([list(colunas)], f"A1:{_coluna(len(colunas))}1", value_input_option="RAW")
        try:
            aba.freeze(rows=1, cols=1)
        except Exception:
            pass
    linhas = aba.get_all_values()
    if not linhas:
        aba.update([list(colunas)], f"A1:{_coluna(len(colunas))}1", value_input_option="RAW")
        linhas = [list(colunas)]
    if linhas[0][:len(colunas)] != list(colunas):
        raise RuntimeError(f"cabecalho_invalido:{nome}")
    return aba, linhas, len(colunas)


def _upsert(tipo: str, registros, linha_factory, planilha=None) -> int:
    if not registros:
        return 0
    aba, linhas, quantidade_colunas = _abrir(tipo, planilha=planilha)
    existentes = {
        str(linha[0]).strip(): indice + 2
        for indice, linha in enumerate(linhas[1:])
        if linha and str(linha[0]).strip()
    }
    proxima = len(linhas) + 1
    agora = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    atualizacoes = []
    for registro in registros:
        chave = str(registro["identificador"] if tipo != "cobertura" else registro["chave"])
        numero = existentes.get(chave)
        if numero is None:
            numero = proxima
            proxima += 1
        valores = linha_factory(registro, agora)
        atualizacoes.append({
            "range": f"A{numero}:{_coluna(quantidade_colunas)}{numero}",
            "values": [valores],
        })
    aba.batch_update(atualizacoes, value_input_option="USER_ENTERED")
    return len(atualizacoes)


def gravar_fundamentos_planilha(fundamentos, indicadores, coberturas, planilha=None):
    """Persiste as três camadas no Sheets; falha impede o commit no Neon."""
    fundamentos_gravados = _upsert(
        "fundamentos", fundamentos,
        lambda x, agora: [
            x["identificador"], x["ticker"], x.get("cnpj") or "", x["classe"],
            str(x.get("periodo_inicio") or ""), str(x["periodo_fim"]), x["exercicio"],
            x["periodicidade"], x["documento"], x.get("escopo") or "CONSOLIDADO",
            x.get("demonstracao") or "", x.get("conta_codigo") or "", x["metrica"],
            x["valor"], x.get("unidade") or "BRL", x.get("moeda") or "BRL",
            x["fonte"], x["qualidade_fonte"], x.get("url_origem") or "", agora,
        ], planilha=planilha,
    )
    indicadores_gravados = _upsert(
        "indicadores", indicadores,
        lambda x, agora: [
            x["identificador"], x["ticker"], x["classe"], str(x["periodo_fim"]),
            x["exercicio"], x["periodicidade"], x["indicador"], x["valor"],
            x["unidade"], x["formula_versao"], x.get("qualidade") or "DERIVADO", agora,
        ], planilha=planilha,
    )
    cobertura_gravada = _upsert(
        "cobertura", coberturas,
        lambda x, agora: [
            x["chave"], x["ticker"], x["classe"], x["metodo"], x["status"],
            x.get("anos_disponiveis") or 0, str(x.get("periodo_inicial") or ""),
            str(x.get("periodo_final") or ""), ", ".join(x.get("campos_presentes") or []),
            ", ".join(x.get("campos_ausentes") or []), x.get("observacao") or "", agora,
        ], planilha=planilha,
    )
    return {
        "fundamentos": fundamentos_gravados,
        "indicadores": indicadores_gravados,
        "coberturas": cobertura_gravada,
    }
