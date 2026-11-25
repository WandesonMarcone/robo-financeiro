"""Coleta manual e auditável dos insumos de valuation.

O motor é deliberadamente separado das rotinas noturnas e de oportunidades.
Para ações, usa DFP anual (cinco anos por padrão) e ITR corrente da CVM. Para
FIIs, usa informes mensais estruturados. Proventos e desdobramentos são
complementados pelo Yahoo até que a fonte oficial estruturada esteja disponível.

A ordem é invariável: fonte -> Google Sheets -> Neon. Uma falha no espelho da
planilha impede qualquer commit SQL.
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from hashlib import sha256

import requests
from sqlalchemy import text

from pipeline_dados.coletor_fiis import normalizar_cnpj


URL_CVM = {
    "DFP": "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip",
    "ITR": "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{ano}.zip",
    "FII_MENSAL": "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip",
}

# Contas comuns das demonstrações consolidadas. Descrições são usadas como
# contingência porque instituições financeiras e reapresentações podem adotar
# elencos analíticos diferentes.
CONTAS_EXATAS = {
    "1": "ativo_total",
    "1.01": "ativo_circulante",
    "1.01.01": "caixa_equivalentes",
    "2": "passivo_total",
    "2.01": "passivo_circulante",
    "2.01.04": "divida_curto_prazo",
    "2.02.01": "divida_longo_prazo",
    "2.03": "patrimonio_liquido",
    "3.01": "receita_liquida",
    "3.03": "lucro_bruto",
    "3.05": "ebit",
    "3.06": "resultado_financeiro",
    "3.07": "lucro_antes_impostos",
    "3.08": "impostos_sobre_lucro",
    "3.11": "lucro_liquido",
    "6.01": "fluxo_caixa_operacional",
    "6.02": "fluxo_caixa_investimentos",
    "6.03": "fluxo_caixa_financiamentos",
}

DESCRICOES = (
    (("patrimonio", "liquido", "atribuido", "controlador"), "patrimonio_liquido"),
    (("patrimonio", "liquido", "consolidado"), "patrimonio_liquido"),
    (("atribuido", "socios", "empresa", "controladora"), "lucro_liquido"),
    (("lucro", "prejuizo", "periodo"), "lucro_liquido"),
    (("resultado", "liquido", "periodo"), "lucro_liquido"),
    (("lucro", "acao", "basico"), "lpa_basico"),
    (("lucro", "acao", "diluido"), "lpa_diluido"),
    (("lucro", "acao"), "lpa_diluido"),
    (("depreciacao", "amortizacao"), "depreciacao_amortizacao"),
    (("depreciacoes", "amortizacoes"), "depreciacao_amortizacao"),
    (("depreciacao", "exaustao"), "depreciacao_amortizacao"),
    (("investimentos", "imobilizado"), "capex"),
    (("compra", "imobilizado"), "capex"),
    (("aquisicao", "intangivel"), "capex_intangivel"),
    (("captacao", "emprestimos"), "captacao_divida"),
    (("pagamento", "emprestimos"), "amortizacao_divida"),
    (("amortizacao", "emprestimos"), "amortizacao_divida"),
    (("aquisicao", "imobilizado"), "capex"),
    (("aquisicoes", "imobilizado"), "capex"),
    (("adicao", "imobilizado"), "capex"),
    (("dividendos", "pagos"), "dividendos_pagos"),
    (("juros", "capital", "proprio", "pagos"), "jcp_pago"),
)

METODOS_ACAO = {
    "GRAHAM": {"lpa", "vpa"},
    "BAZIN": {"dpa", "lpa", "payout"},
    "DIVIDENDOS_PRECO_TETO": {"dpa", "lpa", "payout"},
    "GORDON_DDM": {"dpa", "payout", "crescimento_lpa_5a"},
    "PETER_LYNCH_PEG": {"lpa", "crescimento_lpa_5a"},
    "LUCRO_PROJETADO": {"lpa", "crescimento_lpa_5a", "payout"},
    "DCF_FCFF": {
        "receita_liquida", "ebit", "taxa_imposto_efetiva",
        "depreciacao_amortizacao", "capex", "variacao_capital_giro",
        "divida_liquida", "acoes_media_diluida",
    },
    "DCF_FCFE": {
        "fluxo_caixa_operacional", "capex", "captacao_liquida_divida",
        "acoes_media_diluida",
    },
    "LUCRO_RESIDUAL": {"patrimonio_liquido", "lucro_liquido", "acoes_media_diluida", "roe"},
    "MULTIPLOS_PARES": {"receita_liquida", "ebit", "lucro_liquido", "patrimonio_liquido", "divida_liquida"},
}

METODOS_FII = {
    "FII_RENDA": {"rendimento_por_cota", "patrimonio_liquido", "cotas_emitidas"},
    "FII_TIJOLO": {"rendimento_por_cota", "patrimonio_liquido", "cotas_emitidas", "vacancia_fisica", "walt", "noi"},
    "FII_PAPEL_CRI": {"rendimento_por_cota", "patrimonio_liquido", "cotas_emitidas", "ltv", "inadimplencia", "indexadores_carteira"},
}


def _id(*partes) -> str:
    return sha256("|".join(str(p) for p in partes).encode("utf-8")).hexdigest()


def _texto(valor) -> str:
    bruto = str(valor or "").strip().upper()
    return " ".join(
        "".join(c for c in unicodedata.normalize("NFD", bruto) if unicodedata.category(c) != "Mn").split()
    )


def _numero(valor):
    if valor is None or isinstance(valor, bool):
        return None
    texto_numero = str(valor).strip().replace(" ", "")
    if not texto_numero or texto_numero in {"-", "--"}:
        return None
    if "," in texto_numero and "." in texto_numero:
        texto_numero = texto_numero.replace(".", "").replace(",", ".")
    else:
        texto_numero = texto_numero.replace(",", ".")
    try:
        return float(texto_numero)
    except (TypeError, ValueError):
        return None


def _data(valor):
    try:
        return date.fromisoformat(str(valor or "")[:10])
    except ValueError:
        return None


def _metrica(conta: str, descricao: str):
    texto_desc = _texto(descricao).lower()
    # O plano de contas de instituições financeiras não usa sempre os mesmos
    # códigos das companhias industriais. No BPP de bancos, por exemplo, 2.03
    # é "Provisões" e o patrimônio aparece em 2.07. A descrição oficial deve
    # prevalecer nesses conceitos para impedir um VPA/ROE materialmente errado.
    for termos, metrica in DESCRICOES:
        if all(termo in texto_desc for termo in termos):
            return metrica
    if conta == "2.03" and "patrimonio liquido" not in texto_desc:
        return None
    if conta in CONTAS_EXATAS:
        return CONTAS_EXATAS[conta]
    if conta.startswith("3.99.01"):
        return "lpa_basico"
    if conta.startswith("3.99.02"):
        return "lpa_diluido"
    return None


def _escala(linha, metrica):
    escala = _texto(linha.get("ESCALA_MOEDA"))
    if metrica in {"lpa_basico", "lpa_diluido"}:
        return 1.0
    if "MILHAO" in escala or "MILHOES" in escala:
        return 1_000_000.0
    if "MIL" in escala:
        return 1000.0
    return 1.0


def _arquivos_demonstracoes(pacote, documento, ano):
    prefixo = documento.lower() + "_cia_aberta_"
    demonstracoes = ("BPA_con", "BPP_con", "DRE_con", "DFC_MI_con", "DFC_MD_con")
    alvos = {f"{prefixo}{dem}_{ano}.csv".lower() for dem in demonstracoes}
    return [nome for nome in pacote.namelist() if nome.lower() in alvos]


def extrair_demonstracoes_cvm(conteudo, ticker, cnpj, documento, ano):
    """Extrai fatos oficiais de um único emissor a partir de um ZIP CVM."""
    cnpj_alvo = normalizar_cnpj(cnpj)
    fatos_por_chave = {}
    with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
        arquivos = _arquivos_demonstracoes(pacote, documento, ano)
        if not arquivos:
            raise ValueError("zip_sem_demonstracoes_consolidadas")
        for nome in arquivos:
            demonstracao = re.search(r"_(BPA|BPP|DRE|DFC_MI|DFC_MD)_con_", nome, re.I)
            demonstracao = demonstracao.group(1).upper() if demonstracao else "OUTRA"
            with pacote.open(nome) as arquivo:
                leitor = csv.DictReader(io.TextIOWrapper(arquivo, encoding="latin1"), delimiter=";")
                for linha in leitor:
                    if normalizar_cnpj(linha.get("CNPJ_CIA")) != cnpj_alvo:
                        continue
                    if _texto(linha.get("ORDEM_EXERC")) not in {"ULTIMO", ""}:
                        continue
                    fim = _data(linha.get("DT_FIM_EXERC") or linha.get("DT_REFER"))
                    inicio = _data(linha.get("DT_INI_EXERC"))
                    if not fim:
                        continue
                    conta = str(linha.get("CD_CONTA") or "").strip()
                    descricao = linha.get("DS_CONTA") or ""
                    metrica = _metrica(conta, descricao)
                    valor = _numero(linha.get("VL_CONTA"))
                    if not metrica or valor is None:
                        continue
                    valor *= _escala(linha, metrica)
                    if metrica in {"capex", "depreciacao_amortizacao"}:
                        valor = abs(valor)
                    periodicidade = "ANUAL" if documento == "DFP" else "TRIMESTRAL"
                    chave = (fim, metrica)
                    descricao_normalizada = _texto(descricao)
                    prioridade = 2 if conta in CONTAS_EXATAS or conta.startswith("3.99") else 1
                    if valor != 0:
                        prioridade += 10
                    if metrica == "patrimonio_liquido" and "ATRIBUIDO AO CONTROLADOR" in descricao_normalizada:
                        prioridade += 20
                    if metrica == "lucro_liquido" and conta.startswith("3.11.01"):
                        # O LPA pertence aos acionistas da controladora. Usar o
                        # lucro consolidado (3.11) inclui não controladores e
                        # distorce ações médias, VPA, ROE e múltiplos.
                        prioridade += 20
                    anterior = fatos_por_chave.get(chave)
                    prioridade_anterior = anterior.get("_prioridade", 0) if anterior else 0
                    if anterior and prioridade_anterior > prioridade:
                        anterior["_prioridade"] = prioridade_anterior
                        fatos_por_chave[chave] = anterior
                        continue
                    fatos_por_chave[chave] = {
                        "identificador": _id(ticker, documento, fim, metrica, "CVM"),
                        "ticker": ticker, "cnpj": cnpj_alvo, "classe": "ACAO",
                        "periodo_inicio": inicio, "periodo_fim": fim, "exercicio": fim.year,
                        "periodicidade": periodicidade, "documento": documento,
                        "escopo": "CONSOLIDADO", "demonstracao": demonstracao,
                        "conta_codigo": conta, "metrica": metrica, "valor": valor,
                        "unidade": "BRL_ACAO" if metrica.startswith("lpa_") else "BRL",
                        "moeda": "BRL", "fonte": "CVM_DADOS_ABERTOS",
                        "qualidade_fonte": "OFICIAL", "url_origem": URL_CVM[documento].format(ano=ano),
                        "_prioridade": prioridade,
                    }
        # Composição de capital é uma fonte oficial separada da DRE.
        nome_capital = f"{documento.lower()}_cia_aberta_composicao_capital_{ano}.csv"
        nomes = {nome.lower(): nome for nome in pacote.namelist()}
        if nome_capital in nomes:
            with pacote.open(nomes[nome_capital]) as arquivo:
                leitor = csv.DictReader(io.TextIOWrapper(arquivo, encoding="latin1"), delimiter=";")
                for linha in leitor:
                    if normalizar_cnpj(linha.get("CNPJ_CIA")) != cnpj_alvo:
                        continue
                    fim = _data(linha.get("DT_REFER"))
                    if not fim:
                        continue
                    campos = {
                        "acoes_ordinarias": "QT_ACAO_ORDIN_CAP_INTEGR",
                        "acoes_preferenciais": "QT_ACAO_PREF_CAP_INTEGR",
                        "acoes_emitidas": "QT_ACAO_TOTAL_CAP_INTEGR",
                        "acoes_tesouraria": "QT_ACAO_TOTAL_TESOURO",
                    }
                    valores = {k: _numero(linha.get(v)) for k, v in campos.items()}
                    total, tesouraria = valores["acoes_emitidas"], valores["acoes_tesouraria"]
                    if total is not None and tesouraria is not None and total >= tesouraria:
                        valores["acoes_circulacao_ex_tesouraria"] = total - tesouraria
                    for metrica, valor in valores.items():
                        if valor is None or valor < 0:
                            continue
                        chave = (fim, metrica)
                        versao = _numero(linha.get("VERSAO")) or 0
                        if fatos_por_chave.get(chave, {}).get("_prioridade", -1) > versao:
                            continue
                        fatos_por_chave[chave] = {
                            "identificador": _id(ticker, documento, fim, metrica, "CVM"),
                            "ticker": ticker, "cnpj": cnpj_alvo, "classe": "ACAO",
                            "periodo_inicio": None, "periodo_fim": fim, "exercicio": fim.year,
                            "periodicidade": "ANUAL" if documento == "DFP" else "TRIMESTRAL",
                            "documento": documento, "escopo": "CONSOLIDADO",
                            "demonstracao": "COMPOSICAO_CAPITAL", "conta_codigo": campos.get(metrica),
                            "metrica": metrica, "valor": valor, "unidade": "QUANTIDADE",
                            "moeda": "BRL", "fonte": "CVM_DADOS_ABERTOS",
                            "qualidade_fonte": "DERIVADO" if metrica == "acoes_circulacao_ex_tesouraria" else "OFICIAL",
                            "url_origem": URL_CVM[documento].format(ano=ano), "_prioridade": versao,
                        }
    fatos = []
    for fato in fatos_por_chave.values():
        fato.pop("_prioridade", None)
        fatos.append(fato)
    return fatos


def _fato(ticker, classe, periodo, metrica, valor, unidade, entradas, periodicidade="ANUAL"):
    return {
        "identificador": _id(ticker, periodo, metrica, "formula-v1"),
        "ticker": ticker, "classe": classe, "periodo_fim": periodo,
        "exercicio": periodo.year, "periodicidade": periodicidade,
        "indicador": metrica, "valor": valor, "unidade": unidade,
        "formula_versao": "fundamentos-v1", "entradas": entradas,
        "qualidade": "DERIVADO",
    }


def derivar_indicadores(ticker, classe, fundamentos, proventos=None, eventos=None):
    por_periodo = defaultdict(dict)
    for item in fundamentos:
        if item["periodicidade"] == "ANUAL":
            por_periodo[item["periodo_fim"]][item["metrica"]] = float(item["valor"])
    proventos_ano = defaultdict(float)
    for evento in proventos or []:
        proventos_ano[evento["data_ex"].year] += float(evento["valor_unitario"])
    indicadores = []
    periodos = sorted(por_periodo)
    capitais = {}
    lpas = []
    desdobramentos = sorted(
        (evento["data_referencia"], float(evento["fator"]))
        for evento in (eventos or [])
        if evento.get("tipo") == "DESDOBRAMENTO_OU_GRUPAMENTO"
        and float(evento.get("fator") or 0) > 0
    )
    for periodo in periodos:
        m = por_periodo[periodo]
        lucro = m.get("lucro_liquido")
        lpa = m.get("lpa_diluido") or m.get("lpa_basico")
        if lpa is not None:
            fator_posterior = 1.0
            for data_evento, fator in desdobramentos:
                if data_evento > periodo:
                    fator_posterior *= fator
            if fator_posterior != 1.0:
                lpa /= fator_posterior
        if lpa is not None:
            indicadores.append(_fato(ticker, classe, periodo, "lpa", lpa, "BRL_ACAO", {"origem": "DRE_CVM"}))
            lpas.append((periodo, lpa))
        acoes = (lucro / lpa) if lucro is not None and lpa not in {None, 0} else None
        if acoes and acoes > 0:
            indicadores.append(_fato(ticker, classe, periodo, "acoes_media_diluida", acoes, "ACOES", {"lucro_liquido": lucro, "lpa": lpa}))
        patrimonio = m.get("patrimonio_liquido")
        quantidade = m.get("acoes_circulacao_ex_tesouraria")
        if patrimonio is not None and quantidade and quantidade > 0:
            fator_posterior = 1.0
            for data_evento, fator in desdobramentos:
                if data_evento > periodo:
                    fator_posterior *= fator
            quantidade *= fator_posterior
            indicadores.append(_fato(ticker, classe, periodo, "vpa", patrimonio / quantidade, "BRL_ACAO", {"patrimonio_liquido": patrimonio, "acoes": quantidade, "origem": "COMPOSICAO_CAPITAL"}))
        elif patrimonio is not None and acoes:
            indicadores.append(_fato(ticker, classe, periodo, "vpa", patrimonio / acoes, "BRL_ACAO", {"patrimonio_liquido": patrimonio, "acoes": acoes, "origem": "ESTIMATIVA_ACOES_MEDIA_DILUIDA"}))
        if patrimonio not in {None, 0} and lucro is not None:
            indicadores.append(_fato(ticker, classe, periodo, "roe", lucro / patrimonio, "FRACAO", {"lucro_liquido": lucro, "patrimonio_liquido": patrimonio}))
        imposto, antes = m.get("impostos_sobre_lucro"), m.get("lucro_antes_impostos")
        if imposto is not None and antes not in {None, 0}:
            taxa = min(1.0, max(0.0, abs(imposto / antes)))
            indicadores.append(_fato(ticker, classe, periodo, "taxa_imposto_efetiva", taxa, "FRACAO", {"impostos": imposto, "lucro_antes_impostos": antes}))
        curto, longo = m.get("divida_curto_prazo"), m.get("divida_longo_prazo")
        caixa = m.get("caixa_equivalentes")
        if curto is not None and longo is not None and caixa is not None:
            divida = curto + longo
            indicadores.append(_fato(ticker, classe, periodo, "divida_liquida", divida - caixa, "BRL", {"divida_bruta": divida, "caixa": caixa}))
        if m.get("captacao_divida") is not None and m.get("amortizacao_divida") is not None:
            indicadores.append(_fato(ticker, classe, periodo, "captacao_liquida_divida", abs(m["captacao_divida"]) - abs(m["amortizacao_divida"]), "BRL", {"origem": "DFC"}))
        if m.get("ebit") is not None and m.get("depreciacao_amortizacao") is not None:
            indicadores.append(_fato(ticker, classe, periodo, "ebitda", m["ebit"] + m["depreciacao_amortizacao"], "BRL", {"origem": "EBIT_DA"}))
        if all(m.get(k) is not None for k in ("fluxo_caixa_operacional", "capex", "capex_intangivel")):
            indicadores.append(_fato(ticker, classe, periodo, "fluxo_caixa_livre", m["fluxo_caixa_operacional"] - m["capex"] - abs(m["capex_intangivel"]), "BRL", {"origem": "FCO_CAPEX_IMOBILIZADO_INTANGIVEL"}))
        ac, pc = m.get("ativo_circulante"), m.get("passivo_circulante")
        if ac is not None and pc is not None:
            capitais[periodo] = ac - pc
        dpa = proventos_ano.get(periodo.year)
        if dpa:
            indicadores.append(_fato(ticker, classe, periodo, "dpa", dpa, "BRL_ACAO", {"proventos_eventos": "soma_ano"}))
            if lpa not in {None, 0}:
                indicadores.append(_fato(ticker, classe, periodo, "payout", dpa / lpa, "FRACAO", {"dpa": dpa, "lpa": lpa}))
    for anterior, atual in zip(periodos, periodos[1:]):
        if anterior in capitais and atual in capitais and atual.year == anterior.year + 1:
            indicadores.append(_fato(ticker, classe, atual, "variacao_capital_giro", capitais[atual] - capitais[anterior], "BRL", {"capital_giro_atual": capitais[atual], "capital_giro_anterior": capitais[anterior]}))
    if len(lpas) >= 5 and all(b[0].year == a[0].year + 1 for a, b in zip(lpas, lpas[1:])) and all(v > 0 for _, v in lpas):
        anos = max(1, lpas[-1][0].year - lpas[0][0].year)
        crescimento = (lpas[-1][1] / lpas[0][1]) ** (1 / anos) - 1
        indicadores.append(_fato(ticker, classe, lpas[-1][0], "crescimento_lpa_5a", crescimento, "FRACAO", {"lpa_inicial": lpas[0][1], "lpa_final": lpas[-1][1], "anos": anos}, "PONTUAL"))
    return indicadores


def avaliar_cobertura(ticker, classe, fundamentos, indicadores, setor=None):
    metodos = METODOS_FII if classe == "FII" else METODOS_ACAO
    por_ano = defaultdict(set)
    for item in [*fundamentos, *indicadores]:
        por_ano[item["periodo_fim"].year].add(item.get("metrica") or item.get("indicador"))
    anos = sorted(por_ano)
    anuais = defaultdict(set)
    for item in [*fundamentos, *indicadores]:
        if item.get("periodicidade") == "ANUAL":
            anuais[item["periodo_fim"].year].add(item.get("metrica") or item.get("indicador"))
    if classe == "ACAO":
        anos = sorted(anuais)
    presentes = set().union(*por_ano.values()) if por_ano else set()
    crescimento = next((i.get("valor") for i in reversed(indicadores) if i.get("indicador") == "crescimento_lpa_5a"), None)
    coberturas = []
    setor_financeiro = any(palavra in _texto(setor) for palavra in ("BANCO", "FINANCEIR", "SEGURO"))
    for metodo, necessarios in metodos.items():
        ausentes = sorted(necessarios - presentes)
        if classe == "ACAO":
            for campo in sorted(necessarios & presentes):
                if campo == "crescimento_lpa_5a":
                    if crescimento is None:
                        ausentes.append(campo)
                    continue
                minimo = 4 if campo == "variacao_capital_giro" else 5
                if sum(campo in anuais[ano] for ano in anos[-5:]) < minimo:
                    ausentes.append(campo + "_historico")
            if anos and (len(anos) < 5 or anos[-1] - anos[-5] != 4):
                ausentes.append("cinco_exercicios_consecutivos")
        status = "PRONTO" if not ausentes and len(anos) >= 5 else "PARCIAL" if presentes & necessarios else "INSUFICIENTE"
        observacao = "Dados observados; premissas futuras continuam sendo definidas na Carteira."
        if status == "PRONTO" and metodo in {"GORDON_DDM", "LUCRO_PROJETADO", "DCF_FCFF", "DCF_FCFE", "LUCRO_RESIDUAL"}:
            status = "PREMISSAS_NECESSARIAS"
        if metodo == "PETER_LYNCH_PEG" and crescimento is not None and crescimento <= 0:
            status = "NAO_APLICAVEL"
            observacao = "PEG não interpretável com crescimento não positivo."
        if metodo in {"BAZIN", "DIVIDENDOS_PRECO_TETO", "GORDON_DDM"} and status in {"PRONTO", "PREMISSAS_NECESSARIAS"}:
            status = "PARCIAL"
            ausentes.append("conciliacao_oficial_proventos")
        if setor_financeiro and metodo == "DCF_FCFF":
            status = "NAO_APLICAVEL"
            observacao = "FCFF tradicional não é recomendado para instituições financeiras; usar FCFE, lucro residual ou dividendos."
        if metodo == "MULTIPLOS_PARES":
            if status == "PRONTO":
                status = "PARCIAL"
            ausentes.append("universo_pares_setoriais")
        coberturas.append({
            "identificador": _id(ticker, classe, metodo), "chave": f"{ticker}|{classe}|{metodo}",
            "ticker": ticker, "classe": classe, "metodo": metodo, "status": status,
            "anos_disponiveis": len(anos), "periodo_inicial": date(min(anos), 1, 1) if anos else None,
            "periodo_final": date(max(anos), 12, 31) if anos else None,
            "campos_presentes": sorted(necessarios & presentes), "campos_ausentes": ausentes,
            "observacao": observacao,
        })
    return coberturas


def _persistir(sessao, fundamentos, indicadores, coberturas):
    from services.fundamentos_consolidados import persistir_grupos
    persistir_grupos(sessao, fundamentos, indicadores)
    for item in coberturas:
        parametros = {
            **item,
            "presentes_json": json.dumps(item.get("campos_presentes") or [], ensure_ascii=False),
            "ausentes_json": json.dumps(item.get("campos_ausentes") or [], ensure_ascii=False),
        }
        sessao.execute(text("""
            INSERT INTO cobertura_valuation_ativos
              (ticker,classe,metodo,status,anos_disponiveis,periodo_inicial,periodo_final,campos_presentes,campos_ausentes,observacao)
            VALUES
              (:ticker,:classe,:metodo,:status,:anos_disponiveis,:periodo_inicial,:periodo_final,
               CAST(:presentes_json AS JSONB),CAST(:ausentes_json AS JSONB),:observacao)
            ON CONFLICT (ticker,classe,metodo) DO UPDATE SET status=EXCLUDED.status,
              anos_disponiveis=EXCLUDED.anos_disponiveis,periodo_inicial=EXCLUDED.periodo_inicial,
              periodo_final=EXCLUDED.periodo_final,campos_presentes=EXCLUDED.campos_presentes,
              campos_ausentes=EXCLUDED.campos_ausentes,observacao=EXCLUDED.observacao,atualizado_em=NOW()
        """), parametros)


def _cadastro_ativo(sessao, ticker):
    from services.cadastro_cnpj_oficial import consultar_ticker
    oficial = consultar_ticker(sessao, ticker)
    if oficial:
        return dict(oficial, classe="ACAO")
    # Catálogo oficial também cobre ativos ainda não presentes na tabela legada.
    linha = sessao.execute(text("""
        SELECT ticker, cnpj, classe, setor FROM (
            SELECT ticker, regexp_replace(cnpj,'[^0-9]','','g') AS cnpj,
                   CASE WHEN tipo::text ILIKE '%FII%' THEN 'FII' ELSE 'ACAO' END AS classe,
                   setor, 0 AS prioridade
            FROM ativos_catalogo WHERE UPPER(ticker)=:ticker
            UNION ALL
            SELECT ticker, regexp_replace(cnpj,'[^0-9]','','g'),
                   CASE WHEN tipo::text ILIKE '%FII%' THEN 'FII' ELSE 'ACAO' END,
                   NULL, 1
            FROM ativos WHERE UPPER(ticker)=:ticker
        ) cadastro WHERE length(cnpj)=14 ORDER BY prioridade LIMIT 1
    """), {"ticker": ticker}).mappings().first()
    if not linha:
        raise ValueError("ativo_sem_cnpj_cadastrado")
    return dict(linha)


def coletar_fundamentos_valuation(ticker, anos=5, planilha=None, session_factory=None,
                                  http_get=None, ticker_factory=None, hoje=None, identidade_resolver=None):
    ticker = str(ticker or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{4,10}", ticker):
        raise ValueError("ticker_invalido")
    anos = max(3, min(int(anos), 5))
    hoje = hoje or date.today()
    obter = http_get or requests.get
    if session_factory is None:
        from atualizador_documentos import SessionDB
        session_factory = SessionDB
    sessao = session_factory()
    try:
        try:
            cadastro = _cadastro_ativo(sessao, ticker)
        except ValueError:
            cadastro = None
    finally:
        sessao.close()

    fundamentos = []
    falhas = []
    if cadastro is None or cadastro["classe"] == "ACAO":
        if identidade_resolver is None:
            from services.identidade_fundamentos_acoes import IdentidadeFCA
            identidade_resolver = IdentidadeFCA(http_get=obter, ano=hoje.year)
        oficial = identidade_resolver(ticker)
        if oficial:
            if cadastro and cadastro["cnpj"] != oficial["cnpj"]:
                print(f"Identidade {ticker}: divergência cadastral; FCA oficial selecionado")
            cadastro = oficial
        elif getattr(identidade_resolver, "falha", None):
            falhas.append({"fonte": "FCA", "ano": hoje.year, "erro": identidade_resolver.falha})
    if cadastro is None:
        raise ValueError("ativo_sem_cnpj_confirmado")
    if cadastro["classe"] == "ACAO":
        from services.cadastro_cnpj_oficial import cnpj_valido
        if not cnpj_valido(cadastro["cnpj"]):
            raise ValueError("cnpj_invalido_aguardando_confirmacao_oficial")
    if cadastro["classe"] == "ACAO":
        anos_dfp = list(range(hoje.year - anos, hoje.year))
        for ano in anos_dfp:
            url = URL_CVM["DFP"].format(ano=ano)
            try:
                resposta = obter(url, timeout=90)
                if getattr(resposta, "status_code", None) != 200:
                    raise RuntimeError(f"HTTP_{getattr(resposta, 'status_code', 'SEM_STATUS')}")
                fundamentos.extend(extrair_demonstracoes_cvm(resposta.content, ticker, cadastro["cnpj"], "DFP", ano))
            except Exception as exc:
                falhas.append({"fonte": "DFP", "ano": ano, "erro": type(exc).__name__})
        for ano in (hoje.year,):
            try:
                url = URL_CVM["ITR"].format(ano=ano)
                resposta = obter(url, timeout=90)
                if getattr(resposta, "status_code", None) != 200:
                    raise RuntimeError(f"HTTP_{getattr(resposta, 'status_code', 'SEM_STATUS')}")
                fundamentos.extend(f for f in extrair_demonstracoes_cvm(resposta.content, ticker, cadastro["cnpj"], "ITR", ano) if f["periodo_fim"].year == hoje.year)
            except Exception as exc:
                falhas.append({"fonte": "ITR", "ano": ano, "erro": type(exc).__name__})
    else:
        # O coletor legado já conhece as mudanças de cabeçalhos dos informes.
        from pipeline_dados.coletor_fiis import _ler_zip_informes, _float_cvm
        for ano in range(hoje.year - anos + 1, hoje.year + 1):
            try:
                resposta = obter(URL_CVM["FII_MENSAL"].format(ano=ano), timeout=90)
                if getattr(resposta, "status_code", None) != 200:
                    raise RuntimeError(f"HTTP_{getattr(resposta, 'status_code', 'SEM_STATUS')}")
                dados = _ler_zip_informes(resposta.content) or {}
                for (cnpj, referencia), metricas in dados.items():
                    if normalizar_cnpj(cnpj) != cadastro["cnpj"]:
                        continue
                    periodo = _data(referencia)
                    if not periodo:
                        continue
                    for metrica in ("patrimonio_liquido", "ativo_total", "disponibilidades_caixa", "rendimento_por_cota", "cotas_emitidas", "cotistas"):
                        valor = _float_cvm(metricas.get(metrica))
                        if valor is None:
                            continue
                        fundamentos.append({
                            "identificador": _id(ticker, "FII_MENSAL", periodo, metrica, "CVM"),
                            "ticker": ticker, "cnpj": cadastro["cnpj"], "classe": "FII",
                            "periodo_inicio": None, "periodo_fim": periodo, "exercicio": periodo.year,
                            "periodicidade": "MENSAL", "documento": "INFORME_MENSAL",
                            "escopo": "FUNDO", "demonstracao": "INFORME_MENSAL", "conta_codigo": None,
                            "metrica": metrica, "valor": valor,
                            "unidade": "BRL_COTA" if metrica == "rendimento_por_cota" else ("QUANTIDADE" if metrica in {"cotas_emitidas", "cotistas"} else "BRL"),
                            "moeda": "BRL", "fonte": "CVM_DADOS_ABERTOS", "qualidade_fonte": "OFICIAL",
                            "url_origem": URL_CVM["FII_MENSAL"].format(ano=ano),
                        })
            except Exception as exc:
                falhas.append({"fonte": "FII_MENSAL", "ano": ano, "erro": type(exc).__name__})

    if not fundamentos:
        falhas.append({"fonte": "CVM", "ano": None, "erro": "SEM_DEMONSTRACOES_PARA_CNPJ"})

    proventos, eventos = [], []
    try:
        if ticker_factory is None:
            import yfinance as yf
            ticker_factory = yf.Ticker
        from services.proventos_eventos import extrair_eventos_yahoo
        proventos, eventos = extrair_eventos_yahoo(
            ticker, cadastro["classe"], ticker_factory(f"{ticker}.SA"),
            date(hoje.year - anos, 1, 1), hoje,
        )
    except Exception as exc:
        falhas.append({"fonte": "YAHOO_EVENTOS", "ano": None, "erro": type(exc).__name__})

    indicadores = derivar_indicadores(
        ticker, cadastro["classe"], fundamentos,
        proventos=proventos, eventos=eventos,
    )
    setor = cadastro.get("setor")
    if cadastro["classe"] == "ACAO" and not setor:
        try:
            from services.planilhas import buscar_ativo_na_planilha
            dados_planilha = buscar_ativo_na_planilha(ticker, False) or {}
            setor = dados_planilha.get("setor") or dados_planilha.get("subsetor")
        except Exception:
            setor = None
    coberturas = avaliar_cobertura(ticker, cadastro["classe"], fundamentos, indicadores, setor=setor)

    from services.planilha_fundamentos_valuation import gravar_fundamentos_planilha
    from services.planilha_eventos_mercado import gravar_eventos_planilha
    planilha_resultado = gravar_fundamentos_planilha(fundamentos, indicadores, coberturas, planilha=planilha)
    gravar_eventos_planilha(proventos, eventos, planilha=planilha)

    sessao = session_factory()
    try:
        _persistir(sessao, fundamentos, indicadores, coberturas)
        from services.fundamentos_consolidados import podar_trimestres
        podar_trimestres(sessao, fundamentos, hoje.year)
        from services.proventos_eventos import _persistir as persistir_eventos
        persistir_eventos(sessao, proventos, eventos)
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao.close()

    return {
        "status": "ok" if fundamentos else "falha",
        "ticker": ticker, "classe": cadastro["classe"], "anos_solicitados": anos,
        "fundamentos": len(fundamentos), "indicadores": len(indicadores),
        "periodos_anuais": len({f["exercicio"] for f in fundamentos if f["periodicidade"] == "ANUAL"}),
        "periodos_trimestrais": len({f["periodo_fim"] for f in fundamentos if f["periodicidade"] == "TRIMESTRAL"}),
        "metodos_total": sum(1 for item in coberturas if item["status"] != "NAO_APLICAVEL"),
        "proventos": len(proventos), "eventos": len(eventos),
        "metodos_prontos": sum(1 for item in coberturas if item["status"] in {"PRONTO", "PREMISSAS_NECESSARIAS"}),
        "falhas": falhas, "planilha": planilha_resultado,
        "ordem_persistencia": "FONTE_PLANILHA_NEON",
    }
