"""Espelho auditável de fundamentos e cobertura, sempre antes do Neon."""
from __future__ import annotations

from datetime import datetime


ABAS = {
    "fundamentos": (
        "BD_Fundamentos_Periodos",
        ("CHAVE","TICKER","CLASSE","PERÍODO FIM","EXERCÍCIO","PERIODICIDADE","DOCUMENTO","MÉTRICAS E FONTES (JSON)","ATUALIZADO EM"),
    ),
    "indicadores": (
        "BD_Indicadores_Periodos",
        ("CHAVE","TICKER","CLASSE","PERÍODO FIM","EXERCÍCIO","PERIODICIDADE","DOCUMENTO","INDICADORES (JSON)","ATUALIZADO EM"),
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
    "fundamentos": 2000,
    "indicadores": 2000,
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
    linhas = aba.get("A1:" + _coluna(len(colunas)) + "1")
    chaves = aba.col_values(1)
    linhas = [linhas[0]] + [[chave] for chave in chaves[1:]] if linhas else []
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
    if proxima - 1 > aba.row_count:
        aba.add_rows(max(1000, proxima - 1 - aba.row_count))
    for inicio in range(0, len(atualizacoes), 500):
        aba.batch_update(atualizacoes[inicio:inicio + 500], value_input_option="RAW" if tipo != "cobertura" else "USER_ENTERED")
    return len(atualizacoes)


def gravar_fundamentos_planilha(fundamentos, indicadores, coberturas, planilha=None):
    """Persiste as três camadas no Sheets; falha impede o commit no Neon."""
    from services.fundamentos_consolidados import agrupar, chave_planilha, json_itens
    def gravar_periodos(tipo, registros):
        grupos = agrupar(registros, tipo)
        for g in grupos:
            g["identificador"] = chave_planilha(g)
        # Merge por identificador preserva métricas não retornadas numa coleta parcial.
        if grupos:
            aba, linhas, _ = _abrir(tipo, planilha=planilha)
            existentes = {str(l[0]): n+2 for n,l in enumerate(linhas[1:]) if l and l[0]}
            por_ler = [(g, existentes[g["identificador"]]) for g in grupos if g["identificador"] in existentes]
            if por_ler:
                import json
                respostas = aba.batch_get([f"H{n}" for _,n in por_ler])
                for (g,_), resposta in zip(por_ler,respostas):
                    if resposta and resposta[0] and resposta[0][0]:
                        anterior = json.loads(resposta[0][0])
                        g["itens"] = {**anterior, **g["itens"]}
        return _upsert(tipo,grupos,lambda g,agora:[
            g["identificador"],g["ticker"],g["classe"],str(g["periodo_fim"]),
            g["exercicio"],g["periodicidade"],g["documento"],json_itens(g["itens"]),agora
        ],planilha=planilha)
    fundamentos_gravados = gravar_periodos("fundamentos",fundamentos)
    indicadores_gravados = gravar_periodos("indicadores",indicadores)
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

def limpar_trimestres_antigos(planilha=None, ano_corrente=None):
    """Remove somente as linhas de ações trimestrais antigas nas abas ativas."""
    from datetime import date
    ano = ano_corrente or date.today().year
    planilha = planilha or _planilha_padrao()
    removidas = 0
    for tipo in ("fundamentos","indicadores"):
        aba, linhas, _ = _abrir(tipo, planilha)
        numeros = []
        for numero, linha in enumerate(linhas[1:],2):
            partes = str(linha[0]).split("|") if linha else []
            if len(partes)==6 and partes[1]=="ACAO" and partes[4]=="TRIMESTRAL" and partes[3].isdigit() and int(partes[3])<ano:
                numeros.append(numero)
        # Descendente; não desloca as posições que ainda serão removidas.
        blocos = []
        for n in numeros:
            if blocos and n==blocos[-1][1]+1:
                blocos[-1][1]=n
            else:
                blocos.append([n,n])
        for inicio,fim in reversed(blocos):
            aba.delete_rows(inicio,fim)
            removidas += fim-inicio+1
    return removidas
