"""Coleta de ITR de acoes da CVM (CSV em ZIP).

Associa cada demonstracao ao ``Ativo`` pelo CNPJ cadastrado (coluna
``ativos.cnpj``), nunca pelo ticker nem por planilha. O ano vem do chamador;
o padrao, se omitido, e o ano civil corrente.
"""

import csv
import io
import logging
import zipfile
from datetime import datetime

import requests

from config import MAPA_CONTAS_CVM
from pipeline_dados.banco_dados import Ativo, DadosFinanceirosAcoes, TipoAtivo
from pipeline_dados.coletor_fiis import ano_padrao_coleta, normalizar_cnpj

logger = logging.getLogger(__name__)

STATUS_ARQUIVO_INDISPONIVEL = "arquivo_indisponivel"
STATUS_ARQUIVO_INVALIDO = "arquivo_invalido"
STATUS_SEM_INFORMES = "sem_informes"
STATUS_SEM_ATIVOS = "sem_ativos"
STATUS_GRAVADO = "gravado"
STATUS_ERRO = "erro"

URL_ITR = (
    "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/"
    "itr_cia_aberta_{ano}.zip"
)

ARQUIVOS_ITR = (
    "itr_cia_aberta_BPA_con_{ano}.csv",
    "itr_cia_aberta_BPP_con_{ano}.csv",
    "itr_cia_aberta_DRE_con_{ano}.csv",
    "itr_cia_aberta_DFC_MI_con_{ano}.csv",
)

CAMPOS_BANCO = (
    "ativo_total",
    "patrimonio_liquido",
    "caixa",
    "passivo_total",
    "divida_curto_prazo",
    "divida_longo_prazo",
    "divida_bruta",
    "divida_liquida",
    "receita",
    "lucro_bruto",
    "resultado_financeiro",
    "lucro_liquido",
    "ebitda",
    "fco",
)


def _float_cvm(valor):
    if valor is None:
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto or texto in {"-", "--"}:
        return None
    try:
        return float(texto.replace(",", "."))
    except (TypeError, ValueError):
        return None


class ResultadoColetaAcoes:
    """Contagens da coleta ITR. Nao afirma sucesso se nada foi gravado."""

    def __init__(self, ano):
        self.ano = ano
        self.status = STATUS_ERRO
        self.http_status = None
        self.informes_encontrados = 0
        self.gravados = 0
        self.sem_ativo = 0
        self.ignorados_validacao = 0
        self.falhas_persistencia = 0
        self.erro = None

    def mensagem_telegram(self):
        ano = self.ano
        if self.status == STATUS_ARQUIVO_INDISPONIVEL:
            codigo = self.http_status if self.http_status is not None else "—"
            return (
                f"Coleta CVM ITR ({ano}): arquivo nao obtido na CVM "
                f"(HTTP {codigo}). Nenhum registro gravado."
            )
        if self.status == STATUS_ARQUIVO_INVALIDO:
            return (
                f"Coleta CVM ITR ({ano}): arquivo obtido, mas invalido "
                "(ZIP/CSV ilegivel ou sem tabelas ITR). Nenhum registro gravado."
            )
        if self.status == STATUS_SEM_INFORMES:
            return (
                f"Coleta CVM ITR ({ano}): arquivo obtido, porem nenhum informe "
                "valido foi encontrado. Nenhum registro gravado."
            )
        if self.status == STATUS_SEM_ATIVOS:
            return (
                f"Coleta CVM ITR ({ano}): {self.informes_encontrados} informe(s) "
                f"no arquivo; nenhum CNPJ corresponde a uma acao cadastrada. "
                f"Sem ativo: {self.sem_ativo}. Ignorados: {self.ignorados_validacao}. "
                "Nenhum registro gravado."
            )
        if self.status == STATUS_GRAVADO:
            return (
                f"Coleta CVM ITR ({ano}) concluida.\n"
                f"Registros gravados: {self.gravados}\n"
                f"Informes no arquivo: {self.informes_encontrados}\n"
                f"Sem ativo correspondente: {self.sem_ativo}\n"
                f"Ignorados por validacao: {self.ignorados_validacao}\n"
                f"Falhas de persistencia: {self.falhas_persistencia}"
            )
        detalhe = self.erro or "falha de processamento"
        return (
            f"Coleta CVM ITR ({ano}): falha de processamento ou persistencia "
            f"({detalhe}). Gravados: {self.gravados}."
        )


def _mapa_acoes_por_cnpj(session):
    mapa = {}
    consulta = session.query(Ativo).filter(Ativo.tipo == TipoAtivo.ACAO)
    for ativo in consulta:
        chave = normalizar_cnpj(ativo.cnpj)
        if chave is None:
            continue
        if chave not in mapa:
            mapa[chave] = ativo
    return mapa


def _ler_zip_itr(conteudo, ano):
    nomes_alvo = {nome.format(ano=ano) for nome in ARQUIVOS_ITR}
    with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
        presentes = [n for n in pacote.namelist() if n in nomes_alvo]
        if not presentes:
            return None
        registros = {}
        for nome in presentes:
            with pacote.open(nome) as arquivo:
                leitor = csv.DictReader(
                    io.TextIOWrapper(arquivo, encoding="latin1"),
                    delimiter=";",
                )
                for linha in leitor:
                    ordem = str(linha.get("ORDEM_EXERC") or "").strip()
                    if ordem != "ÚLTIMO":
                        continue
                    conta = str(linha.get("CD_CONTA") or "").strip()
                    if conta not in MAPA_CONTAS_CVM:
                        continue
                    cnpj_cia = linha.get("CNPJ_CIA")
                    data_ref_str = linha.get("DT_REFER")
                    if not cnpj_cia or not data_ref_str:
                        continue
                    valor = _float_cvm(linha.get("VL_CONTA"))
                    if valor is None:
                        continue
                    chave = (cnpj_cia, str(data_ref_str)[:10])
                    if chave not in registros:
                        registros[chave] = {}
                    registros[chave][MAPA_CONTAS_CVM[conta]] = valor * 1000
        return registros


def _fechar_metricas(metricas):
    cp = metricas.get("divida_curto_prazo")
    lp = metricas.get("divida_longo_prazo")
    if cp is not None or lp is not None:
        bruta = (0 if cp is None else cp) + (0 if lp is None else lp)
        metricas["divida_bruta"] = bruta
        caixa = metricas.get("caixa")
        if caixa is not None:
            metricas["divida_liquida"] = bruta - caixa
    ebit = metricas.get("ebit")
    if ebit is not None:
        dep = metricas.get("depreciacao")
        extra = abs(dep) if dep is not None else 0
        metricas["ebitda"] = ebit + extra
    metricas.pop("ebit", None)
    metricas.pop("depreciacao", None)


class AcoesCVMReader:
    """Motor de captura de ITR. Nao acessa Google Sheets nem Telegram."""

    def __init__(self, db_session=None, http_get=None):
        self.session = db_session
        self.http_get = http_get

    def atualizar_acoes(self, ano=None):
        if ano is None:
            ano = ano_padrao_coleta()
        resultado = ResultadoColetaAcoes(ano)
        session_propria = self.session is None
        obter = self.http_get if self.http_get is not None else requests.get
        session = self.session

        if session_propria:
            from atualizador_documentos import SessionDB

            session = SessionDB()

        url = URL_ITR.format(ano=ano)
        logger.info("Baixando ITR de acoes da CVM para o ano de %s", ano)
        try:
            resposta = obter(url, timeout=30)
            resultado.http_status = getattr(resposta, "status_code", None)
            if resultado.http_status != 200:
                logger.error(
                    "Erro ao baixar ITR da CVM: Status %s", resultado.http_status
                )
                resultado.status = STATUS_ARQUIVO_INDISPONIVEL
                return resultado

            try:
                consolidados = _ler_zip_itr(resposta.content, ano)
            except zipfile.BadZipFile:
                resultado.status = STATUS_ARQUIVO_INVALIDO
                return resultado
            except Exception as erro:
                resultado.status = STATUS_ARQUIVO_INVALIDO
                resultado.erro = type(erro).__name__
                return resultado

            if consolidados is None:
                resultado.status = STATUS_ARQUIVO_INVALIDO
                return resultado

            mapa_cnpj = _mapa_acoes_por_cnpj(session)
            informes_com_metrica = 0

            for (cnpj_cia, data_ref_str), metricas in consolidados.items():
                if not metricas:
                    resultado.ignorados_validacao += 1
                    continue

                cnpj_limpo = normalizar_cnpj(cnpj_cia)
                if cnpj_limpo is None:
                    resultado.ignorados_validacao += 1
                    continue

                try:
                    data_referencia = datetime.strptime(
                        str(data_ref_str)[:10], "%Y-%m-%d"
                    ).date()
                except (TypeError, ValueError):
                    resultado.ignorados_validacao += 1
                    continue

                informes_com_metrica += 1
                ativo = mapa_cnpj.get(cnpj_limpo)
                if ativo is None:
                    resultado.sem_ativo += 1
                    continue

                _fechar_metricas(metricas)

                try:
                    registro = (
                        session.query(DadosFinanceirosAcoes)
                        .filter_by(
                            ativo_id=ativo.id,
                            data_referencia=data_referencia,
                            tipo_doc="ITR",
                        )
                        .first()
                    )
                    if not registro:
                        registro = DadosFinanceirosAcoes(
                            ativo_id=ativo.id,
                            data_referencia=data_referencia,
                            tipo_doc="ITR",
                        )
                        session.add(registro)
                    for campo in CAMPOS_BANCO:
                        if campo in metricas and metricas[campo] is not None:
                            setattr(registro, campo, metricas[campo])
                    session.commit()
                    resultado.gravados += 1
                except Exception as erro:
                    session.rollback()
                    resultado.falhas_persistencia += 1
                    logger.error(
                        "Falha ao gravar ITR %s %s: %s",
                        cnpj_limpo,
                        data_referencia,
                        type(erro).__name__,
                    )

            resultado.informes_encontrados = informes_com_metrica
            if resultado.gravados > 0:
                resultado.status = STATUS_GRAVADO
            elif informes_com_metrica == 0:
                resultado.status = STATUS_SEM_INFORMES
            else:
                resultado.status = STATUS_SEM_ATIVOS
            return resultado
        except Exception as erro:
            logger.error("Erro geral ao processar ITR: %s", erro)
            resultado.status = STATUS_ERRO
            resultado.erro = type(erro).__name__
            return resultado
        finally:
            if session_propria and session is not None:
                session.close()
