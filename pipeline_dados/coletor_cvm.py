import io
import logging
import math
import zipfile
from datetime import date, datetime
from typing import Any

import pandas as pd
import requests
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import config
from config import MAPA_CNPJ_B3, MAPA_CONTAS_CVM
from modules.utils import conectar_gspread
from pipeline_dados.banco_dados import DadosFinanceirosAcoes, TipoAtivo
from pipeline_dados.catalogo_ativos import cnpj_real, garantir_ativo, obter_tickers_com_fallback
from pipeline_dados.normalizacao import formatar_cnpj, normalizar_cnpj, normalizar_data
from pipeline_dados.numerico import parsear_numero
from pipeline_dados.qualidade_dados import (
    INVALID,
    registrar_diagnostico,
    regra_coerencia_dfp_itr,
    validar_registro,
)

logger = logging.getLogger(__name__)

_URL_DFP_ZIP = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{}.zip"


def _dfp_zip_existe(ano: int, url_template: str | None = None) -> bool:
    """True se o ZIP DFP do exercicio anual existir. Nao inventa dados."""
    url = (url_template or _URL_DFP_ZIP).format(ano)
    response = None
    try:
        response = requests.head(url, timeout=15, allow_redirects=True)
        if response.status_code == 200:
            return True
        if response.status_code not in (403, 405, 501):
            return False
        response.close()
        response = requests.get(url, timeout=15, stream=True)
        return response.status_code == 200
    except Exception as e:
        logger.warning("Falha ao verificar DFP %s: %s", ano, e)
        return False
    finally:
        if response is not None:
            response.close()


def ano_dfp_cagr_producao(
    hoje: date | None = None,
    *,
    verificar=None,
    recuo_max: int = 5,
) -> int | None:
    """Ultimo exercicio DFP anual consolidado disponivel.

    Nao usa ``datetime.now().year`` cegamente: se o exercicio corrente ainda
    nao foi publicado, recua ate o ultimo ZIP DFP valido.
    """
    referencia = hoje or date.today()
    checar = verificar or _dfp_zip_existe
    for ano in range(referencia.year, referencia.year - recuo_max - 1, -1):
        if ano < 2000:
            break
        try:
            if checar(ano):
                return ano
        except Exception as e:
            logger.warning("Falha ao verificar DFP %s: %s", ano, e)
    return None


def coletar_cvm_acoes_producao(
    session: Session | None = None,
    *,
    hoje: date | None = None,
    verificar_dfp=None,
) -> int | None:
    """Coleta CVM DFP/ITR + T-5 e persiste indicadores. Idempotente.

    Retorna o ano T usado no CAGR, ou None se nao houver DFP anual disponivel.
    """
    from services.db import sessao_db

    ano = ano_dfp_cagr_producao(hoje=hoje, verificar=verificar_dfp)
    if ano is None:
        logger.warning("Nenhum DFP anual CVM disponivel; producao segue com fallback.")
        return None
    with sessao_db(session) as sess:
        coletor = AcoesCVMReader(sess)
        coletor.atualizar_acoes(ano)
    logger.info("Coleta CVM de producao concluida para DFP %s (T-5=%s).", ano, ano - 5)
    return ano

_CAMPOS_CONTABEIS = (
    "ativo_total", "patrimonio_liquido", "caixa", "passivo_total",
    "divida_curto_prazo", "divida_longo_prazo", "divida_bruta", "divida_liquida",
    "receita", "lucro_bruto", "resultado_financeiro", "lucro_liquido",
    "ebitda", "fco", "ebit", "depreciacao", "ativo_circulante", "passivo_circulante",
)


def _ticker_por_cnpj(cnpj) -> str | None:
    formatado = formatar_cnpj(cnpj)
    if formatado in MAPA_CNPJ_B3:
        return MAPA_CNPJ_B3[formatado]
    bruto = str(cnpj).strip() if cnpj is not None else ""
    return MAPA_CNPJ_B3.get(bruto)


def _versao_linha(row) -> int:
    if "VERSAO" not in getattr(row, "index", []):
        valor = row.get("VERSAO") if hasattr(row, "get") else None
    else:
        valor = row["VERSAO"]
    numero = parsear_numero(valor)
    if numero is None:
        return 0
    return int(numero)


def _valor_conta(valor) -> float | None:
    numero = parsear_numero(valor)
    if numero is None:
        return None
    if not math.isfinite(numero):
        return None
    return float(numero) * 1000.0


def derivar_indicadores_cvm(reg: dict[str, Any]) -> dict[str, Any]:
    """Deriva divida_bruta, divida_liquida e ebitda sem mascarar ausencia com 0.

    Conta ausente permanece None; zero informado e preservado. Resultado
    derivado so e calculado quando as contas necessarias existem.
    ebit e depreciacao permanecem no registro (contas-fonte persistidas).
    """
    cp = reg.get("divida_curto_prazo")
    lp = reg.get("divida_longo_prazo")
    if cp is not None and lp is not None:
        reg["divida_bruta"] = cp + lp
        caixa = reg.get("caixa")
        if caixa is not None:
            reg["divida_liquida"] = reg["divida_bruta"] - caixa
        else:
            reg["divida_liquida"] = None
    elif cp is not None or lp is not None:
        reg["divida_bruta"] = None
        reg["divida_liquida"] = None

    ebit = reg.get("ebit")
    dep = reg.get("depreciacao")
    if ebit is not None and dep is not None:
        reg["ebitda"] = ebit + abs(dep)
    else:
        reg["ebitda"] = None
    return reg


class AcoesCVMReader:
    """Motor de captura de dados contábeis de Ações com métodos encapsulados."""

    def __init__(self, db_session: Session):
        self.session = db_session
        self.base_url_itr = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{}.zip"
        self.base_url_dfp = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{}.zip"

        # 1. Busca os tickers usando o método interno (agora impossível de dar erro de 'not defined')
        self.meus_tickers = self._obter_tickers()
        logger.info(f"Tickers de ações identificados na planilha: {self.meus_tickers}")

        # 2. O FILTRO VIP (CNPJs normalizados dos tickers monitorados)
        self.cnpjs_alvo = {
            normalizar_cnpj(cnpj)
            for cnpj, ticker in MAPA_CNPJ_B3.items()
            if ticker in self.meus_tickers
        }
        self.cnpjs_alvo.discard(None)

        logger.info(f"O robô monitorará {len(self.cnpjs_alvo)} CNPJs.")

    def _obter_tickers(self) -> list[str]:
        """Tickers de ações: catálogo PostgreSQL primeiro; Sheets como fallback.

        Fase 7, Etapa 7.2: o catálogo (``ativos_catalogo``) passa a ser a fonte
        ativa em transição. Quando o catálogo ainda não possui o tipo, recai na
        planilha legada BD_Acoes.
        """
        return obter_tickers_com_fallback(
            self.session, TipoAtivo.ACAO, self._obter_tickers_sheets
        )

    def _obter_tickers_sheets(self) -> list[str]:
        """Fallback legado: lê a aba BD_Acoes do Google Sheets."""
        try:
            planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
            aba = planilha.worksheet("BD_Acoes")
            tickers = aba.col_values(1)[1:]
            return list(set([t.strip().upper() for t in tickers if t.strip()]))
        except Exception as e:
            logger.error(f"Erro ao conectar na planilha BD_Acoes: {e}")
            return []

    def atualizar_acoes(self, ano: int) -> None:
        """Método principal orquestrador para Ações."""
        if not self.cnpjs_alvo:
            logger.warning("Nenhum CNPJ alvo identificado na planilha. Cancelando.")
            return

        logger.info(f"Iniciando atualização de Ações (ITR/DFP) para o ano {ano}")
        self._atualizar_documento(ano, tipo_doc="ITR", url_template=self.base_url_itr, prefixo="itr")
        self._atualizar_documento(ano, tipo_doc="DFP", url_template=self.base_url_dfp, prefixo="dfp")
        self._garantir_dfp_cagr_5a(ano)
        self._persistir_indicadores_calculados()
        logger.info("Atualização de Ações concluída.")

    def _atualizar_documento(self, ano: int, tipo_doc: str, url_template: str, prefixo: str) -> None:
        dataframes = self._baixar_arquivos_cvm(ano, url_template=url_template, prefixo=prefixo)
        if not dataframes:
            return
        dados_estruturados = self._processar_itr_dfp(dataframes, tipo_doc=tipo_doc)
        self._salvar_no_banco(dados_estruturados, url_origem=url_template.format(ano))

    def _baixar_arquivos_cvm(
        self, ano: int, url_template=None, prefixo="itr"
    ) -> dict[str, pd.DataFrame]:
        url = (url_template or self.base_url_itr).format(ano)
        response = None
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                dfs = {}
                arquivos_alvo = [
                    f'{prefixo}_cia_aberta_BPA_con_{ano}.csv',
                    f'{prefixo}_cia_aberta_BPP_con_{ano}.csv',
                    f'{prefixo}_cia_aberta_DRE_con_{ano}.csv',
                    f'{prefixo}_cia_aberta_DFC_MI_con_{ano}.csv',
                ]
                for arquivo in arquivos_alvo:
                    if arquivo in z.namelist():
                        with z.open(arquivo) as f:
                            dfs[arquivo] = pd.read_csv(f, sep=';', encoding='latin1')
                return dfs
        except Exception as e:
            logger.error(f"Erro ao baixar/extrair CVM: {e}")
            return {}
        finally:
            if response is not None:
                response.close()

    def _registro_vazio(self, cnpj_formatado, data_ref, tipo_doc, versao=0, dt_ini=None) -> dict[str, Any]:
        registro = {
            "cnpj": cnpj_formatado,
            "data_referencia": data_ref,
            "tipo_doc": tipo_doc,
            "versao": versao,
            "dt_ini_exerc": dt_ini,
        }
        for campo in _CAMPOS_CONTABEIS:
            registro[campo] = None
        return registro

    def _processar_itr_dfp(
        self, dfs: dict[str, pd.DataFrame], tipo_doc: str = "ITR"
    ) -> list[dict[str, Any]]:
        por_chave: dict[str, dict[int, dict[str, Any]]] = {}
        for df in dfs.values():
            if "ORDEM_EXERC" not in df.columns or "CD_CONTA" not in df.columns:
                continue
            df_filtrado = df[(df['ORDEM_EXERC'] == 'ÚLTIMO') & (df['CD_CONTA'].isin(MAPA_CONTAS_CVM.keys()))].copy()
            for _, row in df_filtrado.iterrows():
                cnpj_formatado = str(row['CNPJ_CIA']).strip()
                cnpj_norm = normalizar_cnpj(cnpj_formatado)
                if not cnpj_norm or cnpj_norm not in self.cnpjs_alvo:
                    continue

                conta = row['CD_CONTA']
                valor = _valor_conta(row['VL_CONTA'])
                if valor is None:
                    continue

                data_ref = normalizar_data(row['DT_REFER'])
                if data_ref is None:
                    continue

                versao = _versao_linha(row)
                dt_ini = None
                if "DT_INI_EXERC" in row.index:
                    dt_ini = normalizar_data(row["DT_INI_EXERC"])
                chave = f"{cnpj_norm}_{data_ref.isoformat()}_{tipo_doc}"
                bucket = por_chave.setdefault(chave, {})
                if versao not in bucket:
                    bucket[versao] = self._registro_vazio(
                        formatar_cnpj(cnpj_formatado), data_ref, tipo_doc, versao, dt_ini
                    )
                bucket[versao][MAPA_CONTAS_CVM[conta]] = valor
                if dt_ini is not None and bucket[versao].get("dt_ini_exerc") is None:
                    bucket[versao]["dt_ini_exerc"] = dt_ini

        registros = []
        for bucket in por_chave.values():
            melhor = bucket[max(bucket)]
            derivar_indicadores_cvm(melhor)
            registros.append(melhor)
        return registros

    def _salvar_no_banco(self, dados: list[dict[str, Any]], url_origem=None) -> None:
        from pipeline_dados.freshness import FONTE_CVM, url_origem_segura

        coletado_em = datetime.now()
        url_cvm = url_origem_segura(url_origem)
        for dado in dados:
            cnpj_alvo = dado.pop('cnpj')
            ticker_real = _ticker_por_cnpj(cnpj_alvo)
            if not ticker_real:
                logger.warning("CNPJ %s fora do catalogo MAPA_CNPJ_B3; registro ignorado.", cnpj_alvo)
                continue

            # DATA QUALITY (Fase 3, Bloco 3): regras determinísticas antes de
            # persistir/atualizar. INVALID -> não persiste; WARNING -> persiste,
            # mas o alerta é registrado para diagnóstico.
            data_ref = dado.get('data_referencia')
            tipo_doc = dado.get('tipo_doc') or 'ITR'
            resultado = validar_registro(
                dado,
                "acao_itr_cvm",
                origem=f"CVM/{tipo_doc}",
                ativo=ticker_real,
                documento=str(data_ref),
            )
            registrar_diagnostico(resultado, logger)
            if resultado.status == INVALID:
                logger.warning(
                    "Qualidade: registro de %s (%s) rejeitado; dados não persistidos.",
                    ticker_real,
                    data_ref,
                )
                continue

            try:
                ativo = garantir_ativo(
                    self.session, ticker_real, TipoAtivo.ACAO, cnpj=cnpj_real(cnpj_alvo)
                )
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                continue

            dado['ativo_id'] = ativo.id
            dado['data_coleta'] = coletado_em
            dado['fonte'] = FONTE_CVM
            dado['fonte_primaria'] = f"CVM/{tipo_doc}"
            dado['url_origem'] = url_cvm

            outro_tipo = "DFP" if tipo_doc == "ITR" else "ITR"
            par = self.session.query(DadosFinanceirosAcoes).filter_by(
                ativo_id=ativo.id,
                data_referencia=dado['data_referencia'],
                tipo_doc=outro_tipo,
            ).first()
            if par is not None:
                par_dict = {
                    "ativo_total": par.ativo_total,
                    "patrimonio_liquido": par.patrimonio_liquido,
                    "receita": par.receita,
                    "lucro_liquido": par.lucro_liquido,
                }
                itr_dict, dfp_dict = (dado, par_dict) if tipo_doc == "ITR" else (par_dict, dado)
                for achado in regra_coerencia_dfp_itr(itr_dict, dfp_dict):
                    logger.warning(
                        "QUALIDADE origem=CVM/%s ativo=%s documento=%s campo=%s regra=%s mensagem=%s",
                        tipo_doc, ticker_real, data_ref, achado.campo, achado.regra, achado.mensagem,
                    )

            registro_existente = self.session.query(DadosFinanceirosAcoes).filter_by(
                ativo_id=ativo.id,
                data_referencia=dado['data_referencia'],
                tipo_doc=dado['tipo_doc']
            ).first()

            try:
                if registro_existente:
                    for chave, valor in dado.items():
                        if valor is None:
                            atual = getattr(registro_existente, chave, None)
                            if atual is not None:
                                continue
                        setattr(registro_existente, chave, valor)
                else:
                    novo_registro = DadosFinanceirosAcoes(**dado)
                    self.session.add(novo_registro)

                self.session.commit()
            except Exception as e:
                self.session.rollback()
                logger.error(f"Erro ao salvar/atualizar CVM de {ticker_real}: {e}")

    def _precisa_dfp_ano(self, ano: int) -> bool:
        """True se algum ticker monitorado ainda nao tem DFP anual daquele ano."""
        from sqlalchemy import or_

        from pipeline_dados.banco_dados import Ativo

        tickers = {str(t).strip().upper() for t in self.meus_tickers if t}
        if not tickers:
            return False
        data_ref = date(ano, 12, 31)
        presentes = {
            ticker
            for (ticker,) in (
                self.session.query(Ativo.ticker)
                .join(DadosFinanceirosAcoes, DadosFinanceirosAcoes.ativo_id == Ativo.id)
                .filter(
                    Ativo.ticker.in_(tickers),
                    DadosFinanceirosAcoes.tipo_doc == "DFP",
                    DadosFinanceirosAcoes.data_referencia == data_ref,
                    or_(
                        DadosFinanceirosAcoes.receita.isnot(None),
                        DadosFinanceirosAcoes.lucro_liquido.isnot(None),
                    ),
                )
                .all()
            )
        }
        return len(presentes) < len(tickers)

    def _garantir_dfp_cagr_5a(self, ano: int) -> None:
        """Baixa so o DFP de T-5 se ainda nao estiver persistido. Reutiliza o resto."""
        ano_ini = ano - 5
        if ano_ini < 2000:
            return
        if not self._precisa_dfp_ano(ano_ini):
            logger.info("DFP %s ja persistido; CAGR 5a reutiliza historico CVM.", ano_ini)
            return
        logger.info("DFP %s ausente para CAGR 5a; baixando somente esse ano.", ano_ini)
        self._atualizar_documento(
            ano_ini, tipo_doc="DFP", url_template=self.base_url_dfp, prefixo="dfp"
        )

    def _persistir_indicadores_calculados(self) -> None:
        try:
            from pipeline_dados.indicadores_cvm_acoes import persistir_indicadores_cvm

            gravados = persistir_indicadores_cvm(self.session, self.meus_tickers)
            logger.info("Indicadores CVM calculados persistidos: %s.", gravados)
        except Exception as e:
            logger.error("Falha ao persistir indicadores CVM calculados: %s", e)
