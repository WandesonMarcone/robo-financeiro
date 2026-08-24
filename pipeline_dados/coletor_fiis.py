import csv
import io
import logging
import zipfile

import requests

import config
from atualizador_documentos import SessionDB
from pipeline_dados.banco_dados import Ativo, DadosFinanceirosFiis
from pipeline_dados.normalizacao import formatar_cnpj, normalizar_cnpj, normalizar_data, normalizar_texto
from pipeline_dados.qualidade_dados import INVALID, parsear_numero, registrar_diagnostico, validar_registro

logger = logging.getLogger(__name__)

_MAPA_NOME_TICKER = [
    (normalizar_texto(isca), ticker) for ticker, isca in config.MAPA_ISCAS_MASTER.items()
]


def _ticker_por_nome_fundo(nome_fundo):
    """Resolve o ticker monitorado a partir do nome do fundo (CVM/FNET)."""
    nome_norm = normalizar_texto(nome_fundo)
    if not nome_norm:
        return None
    for isca_norm, ticker in _MAPA_NOME_TICKER:
        if isca_norm in nome_norm:
            return ticker
    return None


def processar_informes_fiis_cvm(ano=2026):
    """
    Baixa o pacote de Informes Mensais de FIIs da CVM (formato CSV),
    extrai os dados e salva na tabela DadosFinanceirosFiis.
    """
    session = SessionDB()
    url = f"https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip"

    print(f"Baixando informes mensais de FIIs (CSV) para o ano de {ano}...")
    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            print(f"Erro ao baixar dados da CVM para FIIs: Status {response.status_code}")
            return False

        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            arquivos_csv = [f for f in z.namelist() if f.endswith(".csv") or f.endswith(".CSV")]

            if not arquivos_csv:
                print("Nenhum arquivo CSV encontrado no pacote da CVM.")
                return False

            print(f"Processando {len(arquivos_csv)} arquivos de tabelas da CVM...")

            dados_consolidados = {}
            denominacoes = {}

            for arquivo_nome in arquivos_csv:
                with z.open(arquivo_nome) as f_csv:
                    reader = csv.DictReader(io.TextIOWrapper(f_csv, encoding="latin1"), delimiter=";")

                    for row in reader:
                        cnpj_fundo = row.get("CNPJ_Fundo")
                        data_ref_str = row.get("DT_COMPTC")

                        if not cnpj_fundo or not data_ref_str:
                            continue

                        chave = (cnpj_fundo, data_ref_str)
                        if chave not in dados_consolidados:
                            dados_consolidados[chave] = {}

                        if "VL_PATRIM_LIQ" in row:
                            dados_consolidados[chave]["patrimonio_liquido"] = row.get("VL_PATRIM_LIQ")
                            dados_consolidados[chave]["cotistas"] = row.get("NR_COTISTAS")
                            denominacoes[chave] = row.get("DENOM_SOCIAL")

                        if "Ativo_Total" in row or "VL_TOTAL" in row:
                            val_ativo = row.get("Ativo_Total") or row.get("VL_TOTAL")
                            if val_ativo:
                                dados_consolidados[chave]["ativo_total"] = val_ativo

                        if "Disponibilidades" in row:
                            dados_consolidados[chave]["disponibilidades_caixa"] = row.get("Disponibilidades")

            print("Tabelas lidas! Inserindo os dados no Banco de Dados...")

            for (cnpj_fundo, data_ref_str), metricas in dados_consolidados.items():
                if not metricas:
                    continue

                if not normalizar_cnpj(cnpj_fundo):
                    continue

                cnpj_mascarado = formatar_cnpj(cnpj_fundo)
                data_referencia = normalizar_data(data_ref_str)
                if data_referencia is None:
                    continue

                ativo = session.query(Ativo).filter(Ativo.cnpj == cnpj_mascarado).first()

                if not ativo:
                    ticker = _ticker_por_nome_fundo(denominacoes.get((cnpj_fundo, data_ref_str)))
                    if ticker:
                        ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
                        if ativo:
                            ativo.cnpj = cnpj_mascarado

                if not ativo:
                    continue

                # DATA QUALITY (Fase 3, Bloco 3): regras determinísticas antes
                # de persistir/atualizar. INVALID -> não persiste; WARNING ->
                # persiste, mas o alerta é registrado para diagnóstico.
                dados_validar = {
                    "cnpj_fundo": cnpj_fundo,
                    "patrimonio_liquido": metricas.get("patrimonio_liquido"),
                    "ativo_total": metricas.get("ativo_total"),
                    "disponibilidades_caixa": metricas.get("disponibilidades_caixa"),
                    "cotistas": metricas.get("cotistas"),
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
                    data_referencia=data_referencia
                ).first()

                if not registro:
                    registro = DadosFinanceirosFiis(ativo_id=ativo.id, data_referencia=data_referencia)
                    session.add(registro)

                def safe_float(val):
                    return parsear_numero(val)

                def safe_int(val):
                    numero = parsear_numero(val)
                    return int(numero) if numero is not None else None

                if "patrimonio_liquido" in metricas:
                    registro.patrimonio_liquido = safe_float(metricas["patrimonio_liquido"])
                if "cotistas" in metricas:
                    registro.cotistas = safe_int(metricas["cotistas"])
                if "ativo_total" in metricas:
                    registro.ativo_total = safe_float(metricas["ativo_total"])
                if "disponibilidades_caixa" in metricas:
                    registro.disponibilidades_caixa = safe_float(metricas["disponibilidades_caixa"])

            session.commit()
            print("Processamento dos Informes de FIIs concluído com sucesso!")
            return True

    except Exception as e:
        print(f"Erro geral ao processar CSV de FIIs: {e}")
        return False
    finally:
        session.close()
