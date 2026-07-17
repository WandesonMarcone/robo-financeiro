import logging
import requests
import zipfile
import io
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pipeline_dados.banco_dados import DadosFinanceirosAcoes, Ativo 

# 1. IMPORTANDO AS VARIÁVEIS GLOBAIS DO SEU SISTEMA
from config import MAPA_CNPJ_B3, MAPA_CONTAS_CVM 

logger = logging.getLogger(__name__)

class AcoesCVMReader:
    """Motor de captura de dados contábeis de Ações conectado ao Google Sheets."""

    def __init__(self, db_session: Session):
        self.session = db_session
        self.base_url_itr = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{}.zip"
        
        # 2. INTELIGÊNCIA DE PLANILHA: Descobre quais ações o usuário realmente tem
        try:
            # Pegando a aba exata 'BD_Acoes'
            self.meus_tickers = obter_tickers_da_planilha(nome_aba="BD_Acoes") 
            logger.info(f"Tickers de ações identificados na planilha: {self.meus_tickers}")
        except Exception as e:
            logger.error(f"Erro ao ler a planilha BD_Acoes. Erro: {e}")
            self.meus_tickers = []

        # 3. O FILTRO VIP: Mapeia apenas os CNPJs das ações que você tem na carteira
        self.cnpjs_alvo = []
        for cnpj, ticker in MAPA_CNPJ_B3.items():
            if ticker in self.meus_tickers:
                self.cnpjs_alvo.append(cnpj)
                
        logger.info(f"O robô monitorará {len(self.cnpjs_alvo)} CNPJs com base na sua planilha.")

    def atualizar_acoes(self, ano: int) -> None:
        """Método principal orquestrador para Ações."""
        if not self.cnpjs_alvo:
            logger.warning("Nenhum CNPJ alvo identificado na planilha. Cancelando atualização da CVM.")
            return

        logger.info(f"Iniciando atualização de Ações (ITR) para o ano {ano}")

        dataframes = self._baixar_arquivos_cvm(ano)
        if not dataframes:
            logger.error("Falha ao baixar ou processar os arquivos da CVM.")
            return

        dados_estruturados = self._processar_itr_dfp(dataframes)
        self._salvar_no_banco(dados_estruturados)
        logger.info(f"Atualização de Ações concluída com sucesso.")

    def _baixar_arquivos_cvm(self, ano: int) -> Dict[str, pd.DataFrame]:
        """Faz o download dos ZIPs e lê os CSVs em memória."""
        url = self.base_url_itr.format(ano)
        logger.info(f"Baixando pacote massivo da CVM: {url}")
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status() 

            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                dfs = {}
                arquivos_alvo = [f'itr_cia_aberta_BPA_con_{ano}.csv', 
                                 f'itr_cia_aberta_BPP_con_{ano}.csv', 
                                 f'itr_cia_aberta_DRE_con_{ano}.csv']

                for arquivo in arquivos_alvo:
                    if arquivo in z.namelist():
                        with z.open(arquivo) as f:
                            dfs[arquivo] = pd.read_csv(f, sep=';', encoding='latin1')
                return dfs
        except Exception as e:
            logger.error(f"Erro ao baixar/extrair CVM: {e}")
            return {}

    def _processar_itr_dfp(self, dfs: Dict[str, pd.DataFrame]) -> List[Dict[str, Any]]:
        """Filtra as contas contábeis apenas dos CNPJs autorizados na planilha."""
        registros = {}

        for nome_arquivo, df in dfs.items():
            df_filtrado = df[(df['ORDEM_EXERC'] == 'ÚLTIMO') & (df['CD_CONTA'].isin(MAPA_CONTAS_CVM.keys()))].copy()

            for _, row in df_filtrado.iterrows():
                cnpj = row['CNPJ_CIA']

                # 🛑 A BARREIRA INTRANSPONÍVEL: Se o CNPJ não é de uma ação da sua planilha, é bloqueado.
                if cnpj not in self.cnpjs_alvo:
                    continue

                data_ref_str = row['DT_REFER']
                conta = row['CD_CONTA']
                valor = row['VL_CONTA'] * 1000  

                try:
                    data_ref = datetime.strptime(data_ref_str, '%Y-%m-%d').date()
                except:
                    continue

                chave = f"{cnpj}_{data_ref_str}"

                if chave not in registros:
                    registros[chave] = {
                        'cnpj': cnpj,
                        'data_referencia': data_ref,
                        'tipo_doc': 'ITR',
                        'caixa': None,
                        'passivo_total': None,
                        'receita': None,
                        'lucro_liquido': None,
                        'ebitda': None 
                    }

                campo = MAPA_CONTAS_CVM[conta]
                registros[chave][campo] = float(valor)

        return list(registros.values())

    def _salvar_no_banco(self, dados: List[Dict[str, Any]]) -> None:
        """Salva os balanços na fonte da verdade (PostgreSQL)."""
        for dado in dados:
            cnpj_alvo = dado.pop('cnpj')
            ticker_real = MAPA_CNPJ_B3[cnpj_alvo]

            ativo = self.session.query(Ativo).filter(Ativo.ticker == ticker_real).first()

            if not ativo:
                ativo = Ativo(ticker=ticker_real, cnpj=cnpj_alvo, tipo="ACAO")
                self.session.add(ativo)
                try:
                    self.session.commit()
                except:
                    self.session.rollback()
                    continue

            dado['ativo_id'] = ativo.id

            try:
                novo_registro = DadosFinanceirosAcoes(**dado)
                self.session.add(novo_registro)
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                pass