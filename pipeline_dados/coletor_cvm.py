import io
import logging
import zipfile
from datetime import datetime
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
from pipeline_dados.normalizacao import normalizar_cnpj, normalizar_data
from pipeline_dados.qualidade_dados import INVALID, registrar_diagnostico, validar_registro

logger = logging.getLogger(__name__)


def derivar_indicadores_cvm(reg: dict[str, Any]) -> dict[str, Any]:
    """Deriva divida_bruta, divida_liquida e ebitda sem mascarar ausencia com 0.

    Conta ausente permanece None; zero informado e preservado. Resultado
    derivado so e calculado quando as contas necessarias existem.
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

    reg.pop("ebit", None)
    reg.pop("depreciacao", None)
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

    def _processar_itr_dfp(
        self, dfs: dict[str, pd.DataFrame], tipo_doc: str = "ITR"
    ) -> list[dict[str, Any]]:
        registros = {}
        for df in dfs.values():
            df_filtrado = df[(df['ORDEM_EXERC'] == 'ÚLTIMO') & (df['CD_CONTA'].isin(MAPA_CONTAS_CVM.keys()))].copy()
            for _, row in df_filtrado.iterrows():
                cnpj_formatado = str(row['CNPJ_CIA']).strip()
                cnpj_norm = normalizar_cnpj(cnpj_formatado)
                if not cnpj_norm or cnpj_norm not in self.cnpjs_alvo:
                    continue

                data_ref_str = row['DT_REFER']
                conta = row['CD_CONTA']
                valor = row['VL_CONTA'] * 1000

                data_ref = normalizar_data(data_ref_str)
                if data_ref is None:
                    continue

                chave = f"{cnpj_formatado}_{data_ref_str}_{tipo_doc}"
                if chave not in registros:
                    registros[chave] = {
                        'cnpj': cnpj_formatado, 'data_referencia': data_ref, 'tipo_doc': tipo_doc,
                        'ativo_total': None, 'patrimonio_liquido': None, 'caixa': None,
                        'passivo_total': None, 'divida_curto_prazo': None, 'divida_longo_prazo': None,
                        'divida_bruta': None, 'divida_liquida': None, 'receita': None,
                        'lucro_bruto': None, 'resultado_financeiro': None, 'lucro_liquido': None,
                        'ebitda': None, 'fco': None, 'ebit': None, 'depreciacao': None
                    }
                registros[chave][MAPA_CONTAS_CVM[conta]] = float(valor)

        for reg in registros.values():
            derivar_indicadores_cvm(reg)

        return list(registros.values())

    def _salvar_no_banco(self, dados: list[dict[str, Any]], url_origem=None) -> None:
        from pipeline_dados.freshness import FONTE_CVM, url_origem_segura

        coletado_em = datetime.now()
        url_cvm = url_origem_segura(url_origem)
        for dado in dados:
            cnpj_alvo = dado.pop('cnpj')
            ticker_real = MAPA_CNPJ_B3[cnpj_alvo]

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
