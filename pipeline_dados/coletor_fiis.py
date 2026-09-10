import csv
import io
import logging
import zipfile
from datetime import date, datetime

import requests

from atualizador_documentos import SessionDB
from pipeline_dados.banco_dados import DadosFinanceirosFiis
from pipeline_dados.catalogo_ativos import identificar_ativo_fii, ticker_por_nome_fii
from pipeline_dados.freshness import FONTE_CVM, url_origem_segura
from pipeline_dados.normalizacao import normalizar_cnpj, normalizar_data
from pipeline_dados.numerico import parsear_percentual
from pipeline_dados.qualidade_dados import INVALID, parsear_numero, registrar_diagnostico, validar_registro

logger = logging.getLogger(__name__)

URL_INF_MENSAL = (
    "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip"
)
URL_INF_TRIMESTRAL = (
    "https://dados.cvm.gov.br/dados/FII/DOC/INF_TRIMESTRAL/DADOS/"
    "inf_trimestral_fii_{ano}.zip"
)

# Colunas reais do INF_MENSAL (2021+) e aliases legados (quando existirem).
# Vacância física/financeira NÃO existem nestes CSVs — permanecem ausentes.
# receita_imoveis / despesas_taxas / resultado_ligado_venda vêm do INF_TRIMESTRAL.
_CHAVES_CNPJ = ("CNPJ_Fundo_Classe", "CNPJ_Fundo")
_CHAVES_DATA = ("Data_Referencia", "DT_COMPTC")
_CHAVES_NOME = ("Nome_Fundo_Classe", "DENOM_SOCIAL")
_MAPA_METRICAS = {
    "patrimonio_liquido": ("Patrimonio_Liquido", "VL_PATRIM_LIQ"),
    "ativo_total": ("Valor_Ativo", "Ativo_Total", "VL_TOTAL"),
    "disponibilidades_caixa": ("Disponibilidades",),
    "cotistas": ("Total_Numero_Cotistas", "NR_COTISTAS"),
    "cotas_emitidas": ("Cotas_Emitidas", "Quantidade_Cotas_Emitidas"),
    "valor_patrimonial_cotas": ("Valor_Patrimonial_Cotas",),
    "percentual_dividend_yield_mes": ("Percentual_Dividend_Yield_Mes",),
}

# INF_TRIMESTRAL resultado_contabil_financeiro — visao Contabil (nao mistura
# com Financeiro). Receita de venda nao equivale a resultado_ligado_venda.
_MAPA_TRIMESTRAL = {
    "receita_imoveis": ("Receita_Aluguel_Investimento_Contabil",),
    "despesas_taxas": ("Taxa_Administracao_Contabil",),
}

CAMPOS_CVM_AUSENTES_NO_CSV = (
    "rendimento_por_cota",
    "vacancia_fisica",
    "vacancia_financeira",
    "resultado_ligado_venda",
)

CAMPOS_INF_MENSAL_SEM_DESTINO_ORM = (
    "receita_imoveis",
    "resultado_ligado_venda",
    "despesas_taxas",
)


def _ticker_por_nome_fundo(nome_fundo, session=None):
    """Resolve o ticker monitorado a partir do nome do fundo (CVM/FNET).

    Fase 8.3: casamento por nome é último recurso, com validação de colisão.
    """
    return ticker_por_nome_fii(nome_fundo, session=session)


def _primeiro_presente(row, *chaves):
    for chave in chaves:
        if chave not in row:
            continue
        valor = row.get(chave)
        if valor is None:
            continue
        texto = str(valor).strip()
        if texto:
            return texto
    return None


def extrair_campos_inf_mensal(row: dict) -> dict | None:
    """Extrai CNPJ/data/métricas de uma linha INF_MENSAL. Sem rede.

    Aceita o dicionário vigente (CNPJ_Fundo_Classe / Data_Referencia) e os
    nomes legados. Campo ausente permanece fora do dict — nunca vira 0.
    """
    if not row:
        return None
    cnpj = _primeiro_presente(row, *_CHAVES_CNPJ)
    data_ref = _primeiro_presente(row, *_CHAVES_DATA)
    if not cnpj or not data_ref:
        return None
    extraido = {"cnpj_fundo": cnpj, "data_referencia": data_ref}
    nome = _primeiro_presente(row, *_CHAVES_NOME)
    if nome:
        extraido["nome"] = nome
    for destino, chaves in _MAPA_METRICAS.items():
        valor = _primeiro_presente(row, *chaves)
        if valor is not None:
            extraido[destino] = valor
    return extraido


def consolidar_linhas_inf_mensal(linhas) -> tuple[dict, dict]:
    """Agrupa linhas dos CSVs por (CNPJ, data). Não inventa métrica."""
    dados_consolidados = {}
    denominacoes = {}
    for row in linhas:
        extraido = extrair_campos_inf_mensal(row)
        if extraido is None:
            continue
        chave = (extraido["cnpj_fundo"], extraido["data_referencia"])
        destino = dados_consolidados.setdefault(chave, {})
        for campo, valor in extraido.items():
            if campo in ("cnpj_fundo", "data_referencia", "nome"):
                continue
            if campo not in destino:
                destino[campo] = valor
        if "nome" in extraido and chave not in denominacoes:
            denominacoes[chave] = extraido["nome"]
    return dados_consolidados, denominacoes


def _ler_zip_inf_mensal(conteudo_zip) -> tuple[dict, dict]:
    linhas = []
    with zipfile.ZipFile(io.BytesIO(conteudo_zip)) as z:
        arquivos_csv = [f for f in z.namelist() if f.endswith(".csv") or f.endswith(".CSV")]
        for arquivo_nome in arquivos_csv:
            with z.open(arquivo_nome) as f_csv:
                reader = csv.DictReader(io.TextIOWrapper(f_csv, encoding="latin1"), delimiter=";")
                linhas.extend(reader)
    return consolidar_linhas_inf_mensal(linhas)


def _numero_opcional(val):
    return parsear_numero(val)


def _inteiro_opcional(val):
    numero = parsear_numero(val)
    return int(numero) if numero is not None else None


def _fracao_opcional(val):
    """Percentual CVM ja em fracao (0.004342 = 0,4342%). Nao inventa escala."""
    return parsear_percentual(val)


def extrair_campos_inf_trimestral(row: dict) -> dict | None:
    """Extrai CNPJ/data/metricas do CSV trimestral. Sem rede.

    Campo ausente permanece fora do dict — nunca vira 0.
    """
    if not row:
        return None
    cnpj = _primeiro_presente(row, *_CHAVES_CNPJ)
    data_ref = _primeiro_presente(row, *_CHAVES_DATA)
    if not cnpj or not data_ref:
        return None
    extraido = {"cnpj_fundo": cnpj, "data_referencia": data_ref}
    nome = _primeiro_presente(row, *_CHAVES_NOME)
    if nome:
        extraido["nome"] = nome
    for destino, chaves in _MAPA_TRIMESTRAL.items():
        valor = _primeiro_presente(row, *chaves)
        if valor is not None:
            extraido[destino] = valor
    return extraido


def consolidar_linhas_inf_trimestral(linhas) -> tuple[dict, dict]:
    """Agrupa linhas trimestrais por (CNPJ, data). Nao inventa metrica."""
    dados_consolidados = {}
    denominacoes = {}
    for row in linhas:
        extraido = extrair_campos_inf_trimestral(row)
        if extraido is None:
            continue
        chave = (extraido["cnpj_fundo"], extraido["data_referencia"])
        destino = dados_consolidados.setdefault(chave, {})
        for campo, valor in extraido.items():
            if campo in ("cnpj_fundo", "data_referencia", "nome"):
                continue
            if campo not in destino:
                destino[campo] = valor
        if "nome" in extraido and chave not in denominacoes:
            denominacoes[chave] = extraido["nome"]
    return dados_consolidados, denominacoes


def _ler_zip_inf_trimestral(conteudo_zip) -> tuple[dict, dict]:
    linhas = []
    with zipfile.ZipFile(io.BytesIO(conteudo_zip)) as z:
        arquivos_csv = [
            f for f in z.namelist()
            if "resultado_contabil_financeiro" in f.lower()
            and (f.endswith(".csv") or f.endswith(".CSV"))
        ]
        for arquivo_nome in arquivos_csv:
            with z.open(arquivo_nome) as f_csv:
                reader = csv.DictReader(io.TextIOWrapper(f_csv, encoding="latin1"), delimiter=";")
                linhas.extend(reader)
    return consolidar_linhas_inf_trimestral(linhas)


def persistir_informes_fiis(session, dados_consolidados, denominacoes, url) -> int:
    """Grava informes já consolidados. Retorna quantos registros passaram."""
    gravados = 0
    for (cnpj_fundo, data_ref_str), metricas in dados_consolidados.items():
        if not metricas:
            continue
        if not normalizar_cnpj(cnpj_fundo):
            continue
        data_referencia = normalizar_data(data_ref_str)
        if data_referencia is None:
            continue
        ativo = identificar_ativo_fii(
            session,
            cnpj=cnpj_fundo,
            nome=denominacoes.get((cnpj_fundo, data_ref_str)),
        )
        if not ativo:
            continue

        dados_validar = {
            "cnpj_fundo": cnpj_fundo,
            "patrimonio_liquido": metricas.get("patrimonio_liquido"),
            "ativo_total": metricas.get("ativo_total"),
            "disponibilidades_caixa": metricas.get("disponibilidades_caixa"),
            "cotistas": metricas.get("cotistas"),
            "cotas_emitidas": metricas.get("cotas_emitidas"),
            "valor_patrimonial_cotas": metricas.get("valor_patrimonial_cotas"),
            "percentual_dividend_yield_mes": metricas.get("percentual_dividend_yield_mes"),
        }
        resultado = validar_registro(
            dados_validar,
            "fii_informe_cvm",
            origem="CVM/INF_MENSAL_FII",
            ativo=ativo.ticker,
            documento=str(data_referencia),
        )
        registrar_diagnostico(resultado, logger)
        if resultado.status == INVALID:
            print(
                f"Qualidade: registro rejeitado para {ativo.ticker} em {data_referencia}. "
                "Dados não persistidos."
            )
            continue

        registro = session.query(DadosFinanceirosFiis).filter_by(
            ativo_id=ativo.id,
            data_referencia=data_referencia,
        ).first()
        if not registro:
            registro = DadosFinanceirosFiis(ativo_id=ativo.id, data_referencia=data_referencia)
            session.add(registro)

        registro.data_coleta = datetime.now()
        registro.fonte = FONTE_CVM
        registro.fonte_primaria = "CVM/INF_MENSAL"
        registro.url_origem = url_origem_segura(url)

        if "patrimonio_liquido" in metricas:
            registro.patrimonio_liquido = _numero_opcional(metricas["patrimonio_liquido"])
        if "cotistas" in metricas:
            registro.cotistas = _inteiro_opcional(metricas["cotistas"])
        if "ativo_total" in metricas:
            registro.ativo_total = _numero_opcional(metricas["ativo_total"])
        if "disponibilidades_caixa" in metricas:
            registro.disponibilidades_caixa = _numero_opcional(metricas["disponibilidades_caixa"])
        if "cotas_emitidas" in metricas:
            registro.cotas_emitidas = _numero_opcional(metricas["cotas_emitidas"])
        if "valor_patrimonial_cotas" in metricas:
            registro.valor_patrimonial_cotas = _numero_opcional(
                metricas["valor_patrimonial_cotas"]
            )
        if "percentual_dividend_yield_mes" in metricas:
            registro.percentual_dividend_yield_mes = _fracao_opcional(
                metricas["percentual_dividend_yield_mes"]
            )
        gravados += 1
    return gravados


def persistir_informes_trimestrais_fiis(session, dados_consolidados, denominacoes, url) -> int:
    """Grava receita/taxas do INF_TRIMESTRAL. Nao inventa vacancia nem WALT."""
    gravados = 0
    for (cnpj_fundo, data_ref_str), metricas in dados_consolidados.items():
        if not metricas:
            continue
        if not normalizar_cnpj(cnpj_fundo):
            continue
        data_referencia = normalizar_data(data_ref_str)
        if data_referencia is None:
            continue
        ativo = identificar_ativo_fii(
            session,
            cnpj=cnpj_fundo,
            nome=denominacoes.get((cnpj_fundo, data_ref_str)),
        )
        if not ativo:
            continue

        dados_validar = {
            "cnpj_fundo": cnpj_fundo,
            "receita_imoveis": metricas.get("receita_imoveis"),
            "despesas_taxas": metricas.get("despesas_taxas"),
        }
        resultado = validar_registro(
            dados_validar,
            "fii_informe_cvm",
            origem="CVM/INF_TRIMESTRAL_FII",
            ativo=ativo.ticker,
            documento=str(data_referencia),
        )
        registrar_diagnostico(resultado, logger)
        if resultado.status == INVALID:
            print(
                f"Qualidade: trimestre rejeitado para {ativo.ticker} em {data_referencia}. "
                "Dados não persistidos."
            )
            continue

        registro = session.query(DadosFinanceirosFiis).filter_by(
            ativo_id=ativo.id,
            data_referencia=data_referencia,
        ).first()
        if not registro:
            registro = DadosFinanceirosFiis(ativo_id=ativo.id, data_referencia=data_referencia)
            session.add(registro)

        registro.data_coleta = datetime.now()
        registro.fonte = FONTE_CVM
        registro.fonte_primaria = "CVM/INF_TRIMESTRAL"
        registro.url_origem = url_origem_segura(url)

        if "receita_imoveis" in metricas:
            registro.receita_imoveis = _numero_opcional(metricas["receita_imoveis"])
        if "despesas_taxas" in metricas:
            registro.despesas_taxas = _numero_opcional(metricas["despesas_taxas"])
        gravados += 1
    return gravados


def processar_informes_fiis_cvm(ano=None):
    """
    Baixa o pacote de Informes Mensais de FIIs da CVM (formato CSV),
    extrai os dados e salva na tabela DadosFinanceirosFiis.
    """
    if ano is None:
        ano = date.today().year
    session = SessionDB()
    url = URL_INF_MENSAL.format(ano=ano)

    print(f"Baixando informes mensais de FIIs (CSV) para o ano de {ano}...")
    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            print(f"Erro ao baixar dados da CVM para FIIs: Status {response.status_code}")
            return False

        dados_consolidados, denominacoes = _ler_zip_inf_mensal(response.content)
        if not dados_consolidados:
            print("Nenhum informe mensal utilizável encontrado no pacote da CVM.")
            return False

        print("Tabelas lidas! Inserindo os dados no Banco de Dados...")
        persistir_informes_fiis(session, dados_consolidados, denominacoes, url)
        session.commit()
        print("Processamento dos Informes Mensais de FIIs concluído com sucesso!")
        processar_informes_trimestrais_fiis_cvm(ano=ano, session=session)
        return True

    except Exception as e:
        print(f"Erro geral ao processar CSV de FIIs: {e}")
        return False
    finally:
        session.close()


def processar_informes_trimestrais_fiis_cvm(ano=None, session=None):
    """Baixa o INF_TRIMESTRAL e persiste receita_imoveis e despesas_taxas."""
    if ano is None:
        ano = date.today().year
    url = URL_INF_TRIMESTRAL.format(ano=ano)
    fechar = False
    if session is None:
        session = SessionDB()
        fechar = True

    print(f"Baixando informes trimestrais de FIIs (CSV) para o ano de {ano}...")
    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            print(f"Erro ao baixar INF_TRIMESTRAL: Status {response.status_code}")
            return False

        dados_consolidados, denominacoes = _ler_zip_inf_trimestral(response.content)
        if not dados_consolidados:
            print("Nenhum informe trimestral utilizável encontrado no pacote da CVM.")
            return False

        persistir_informes_trimestrais_fiis(session, dados_consolidados, denominacoes, url)
        session.commit()
        print("Processamento dos Informes Trimestrais de FIIs concluído com sucesso!")
        return True
    except Exception as e:
        print(f"Erro geral ao processar CSV trimestral de FIIs: {e}")
        return False
    finally:
        if fechar:
            session.close()
