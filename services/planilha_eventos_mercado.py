"""Espelho operacional de proventos e eventos já persistidos no Neon."""
from __future__ import annotations

from datetime import datetime


ABAS_EVENTOS = {
    "provento": (
        "BD_Proventos",
        ("IDENTIFICADOR", "TICKER", "CLASSE", "DATA EX", "DATA PAGAMENTO",
         "TIPO", "VALOR UNITÁRIO", "MOEDA", "FONTE", "QUALIDADE", "ATUALIZADO EM"),
    ),
    "evento": (
        "BD_Eventos_Corporativos",
        ("IDENTIFICADOR", "TICKER", "CLASSE", "DATA REFERÊNCIA", "TIPO",
         "FATOR", "DESCRIÇÃO", "FONTE", "QUALIDADE", "ATUALIZADO EM"),
    ),
}


def _abrir(tipo: str, planilha=None):
    nome, colunas = ABAS_EVENTOS[tipo]
    if planilha is None:
        import config
        from modules.utils import conectar_gspread

        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
    try:
        aba = planilha.worksheet(nome)
    except Exception as exc:
        if exc.__class__.__name__ != "WorksheetNotFound":
            raise
        aba = planilha.add_worksheet(title=nome, rows=1000, cols=len(colunas))
        aba.update([list(colunas)], f"A1:{chr(64 + len(colunas))}1", value_input_option="RAW")
        try:
            aba.freeze(rows=1, cols=1)
        except Exception:
            pass
    from modules.resiliencia_planilha import executar_com_retentativa
    linhas = executar_com_retentativa(aba.get_all_values, f"Leitura da aba {nome}")
    if not linhas:
        aba.update([list(colunas)], f"A1:{chr(64 + len(colunas))}1", value_input_option="RAW")
        linhas = [list(colunas)]
    if linhas[0][:len(colunas)] != list(colunas):
        raise RuntimeError(f"cabecalho_invalido:{nome}")
    return aba, linhas


def gravar_eventos_planilha(proventos, eventos, planilha=None):
    """Espelha eventos, ampliando a aba antes de ultrapassar seu limite."""
    from modules.resiliencia_planilha import executar_com_retentativa
    gravados = {"proventos": 0, "eventos": 0}
    agora = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    for tipo, itens, chave_resultado in (
        ("provento", proventos or [], "proventos"),
        ("evento", eventos or [], "eventos"),
    ):
        if not itens:
            continue
        aba, linhas = _abrir(tipo, planilha=planilha)
        existentes = {
            str(linha[0]).strip(): indice + 2
            for indice, linha in enumerate(linhas[1:]) if linha and str(linha[0]).strip()
        }
        proxima = len(linhas) + 1
        atualizacoes = []
        for item in itens:
            identificador = item["identificador"]
            numero = existentes.get(identificador)
            if numero is None:
                numero = proxima
                proxima += 1
            if tipo == "provento":
                valores = [
                    identificador, item["ticker"], item["classe"], str(item["data_ex"]),
                    str(item.get("data_pagamento") or ""), item["tipo"], item["valor_unitario"],
                    item.get("moeda") or "BRL", item["fonte"], item["qualidade_fonte"], agora,
                ]
                fim = "K"
            else:
                valores = [
                    identificador, item["ticker"], item["classe"], str(item["data_referencia"]),
                    item["tipo"], item.get("fator"), item.get("descricao") or "",
                    item["fonte"], item["qualidade_fonte"], agora,
                ]
                fim = "J"
            atualizacoes.append({"range": f"A{numero}:{fim}{numero}", "values": [valores]})
        ultima_linha = max((int(atualizacao["range"].split(":", 1)[0][1:]) for atualizacao in atualizacoes), default=1)
        if ultima_linha > aba.row_count:
            executar_com_retentativa(
                lambda: aba.add_rows(max(1000, ultima_linha - aba.row_count)),
                f"Expansão da aba {ABAS_EVENTOS[tipo][0]}",
            )
        executar_com_retentativa(
            lambda: aba.batch_update(atualizacoes, value_input_option="USER_ENTERED"),
            f"Gravação em lote na aba {ABAS_EVENTOS[tipo][0]}",
        )
        gravados[chave_resultado] += len(atualizacoes)
    return gravados
