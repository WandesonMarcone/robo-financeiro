import logging
import requests
import zipfile
import io
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from banco_dados import DadosFinanceirosAcoes, Ativo 

logger = logging.getLogger(__name__)

# ==========================================
# 🧠 O CÉREBRO TRADUTOR (O FILTRO VIP B3)
# ==========================================
# Coloque aqui os CNPJs das ações que você quer que o robô monitore.
# O que não estiver nesta lista será ignorado para manter o banco leve e rápido.
MAPA_CNPJ_B3 = {
    # --- Bancos e Financeiros ---
    '00.000.000/0001-91': 'BBAS3',  # Banco do Brasil
    '60.872.504/0001-23': 'ITUB4',  # Itaú Unibanco
    '60.746.948/0001-12': 'BBDC4',  # Bradesco
    '90.400.888/0001-42': 'SANB11', # Santander Brasil
    '09.346.601/0001-25': 'B3SA3',  # B3
    '00.360.305/0001-04': 'BBSE3',  # BB Seguridade
    
    # --- Petróleo, Gás e Mineração ---
    '33.000.167/0001-01': 'PETR4',  # Petrobras
    '33.592.510/0001-54': 'VALE3',  # Vale
    '06.082.980/0001-03': 'PRIO3',  # Prio (PetroRio)
    '01.838.723/0001-27': 'BRKM5',  # Braskem
    '02.351.877/0001-52': 'CSNA3',  # Siderúrgica Nacional
    '60.940.145/0001-14': 'GGBR4',  # Gerdau
    
    # --- Energia e Utilidades Públicas ---
    '00.001.180/0001-26': 'ELET3',  # Eletrobras
    '84.683.601/0001-74': 'WEGE3',  # WEG
    '02.932.971/0001-15': 'EGIE3',  # Engie Brasil
    '01.206.065/0001-46': 'SBSP3',  # Sabesp
    '06.981.180/0001-16': 'CMIG4',  # Cemig
    '39.381.153/0001-08': 'CPLE6',  # Copel
    '03.256.096/0001-40': 'ENEV3',  # Eneva
    
    # --- Varejo e Consumo ---
    '47.960.950/0001-21': 'MGLU3',  # Magazine Luiza
    '07.526.557/0001-00': 'ABEV3',  # Ambev
    '00.001.180/0001-26': 'LREN3',  # Lojas Renner (CNPJ matriz freq. na CVM)
    '16.670.085/0001-55': 'RENT3',  # Localiza
    '06.164.253/0001-87': 'CRFB3',  # Carrefour Brasil
    '08.582.208/0001-08': 'NTCO3',  # Natura
    '47.508.411/0001-56': 'PCAR3',  # Grupo Pão de Açúcar
    '33.014.556/0001-96': 'ASAI3',  # Assaí
    
    # --- Carnes e Proteínas ---
    '02.916.265/0001-60': 'JBSS3',  # JBS
    '01.838.723/0001-27': 'BEEF3',  # Minerva
    '01.017.595/0001-38': 'MRFG3',  # Marfrig
    
    # --- Papel, Celulose e Indústria ---
    '16.404.287/0001-55': 'SUZB3',  # Suzano
    '89.637.490/0001-45': 'KLBN11', # Klabin
    '02.497.801/0001-24': 'EMBR3',  # Embraer
    '50.282.735/0001-83': 'VIVA3',  # Vivara
    
    # --- Saúde e Educação ---
    '43.181.368/0001-22': 'RADL3',  # Raia Drogasil
    '60.933.603/0001-78': 'HAPV3',  # Hapvida
    '02.800.026/0001-40': 'YDUQ3',  # Yduqs
    
    # --- Telecom e Tecnologia ---
    '02.558.157/0001-62': 'VIVT3',  # Vivo (Telefônica)
    '02.421.421/0001-11': 'TIMS3',  # TIM
    '01.246.689/0001-36': 'TOTS3'   # Totvs
}

class AcoesCVMReader:
    """Motor de captura de dados contábeis de Ações via Arquivos Abertos CVM (ITR/DFP)."""

    def __init__(self, db_session: Session):
        self.session = db_session
        self.base_url_itr = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{}.zip"

    def atualizar_acoes(self, ano: int) -> None:
        """Método principal orquestrador para Ações."""
        logger.info(f"Iniciando atualização de Ações (ITR) para o ano {ano}")

        dataframes = self._baixar_arquivos_cvm(ano)
        if not dataframes:
            logger.error("Falha ao baixar ou processar os arquivos da CVM.")
            return

        dados_estruturados = self._processar_itr_dfp(dataframes)
        self._salvar_no_banco(dados_estruturados)
        logger.info(f"Atualização de Ações concluída. Registros filtrados e processados com sucesso.")

    def _baixar_arquivos_cvm(self, ano: int) -> Dict[str, pd.DataFrame]:
        """Faz o download dos ZIPs e lê os CSVs em memória usando Pandas."""
        url = self.base_url_itr.format(ano)
        logger.info(f"Baixando dados oficiais: {url}")
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
        """Filtra as contas contábeis padronizadas e estrutura os dados num dicionário."""
        registros = {}

        MAPA_CONTAS = {
            '1.01': 'caixa',               
            '2': 'passivo_total',          
            '3.01': 'receita',             
            '3.11': 'lucro_liquido'        
        }

        for nome_arquivo, df in dfs.items():
            df_filtrado = df[(df['ORDEM_EXERC'] == 'ÚLTIMO') & (df['CD_CONTA'].isin(MAPA_CONTAS.keys()))].copy()

            for _, row in df_filtrado.iterrows():
                cnpj = row['CNPJ_CIA']
                
                # 🛑 TRAVA DE SEGURANÇA: Se o CNPJ não estiver no nosso Dicionário VIP, joga fora!
                if cnpj not in MAPA_CNPJ_B3:
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

                campo = MAPA_CONTAS[conta]
                registros[chave][campo] = float(valor)

        return list(registros.values())

    def _salvar_no_banco(self, dados: List[Dict[str, Any]]) -> None:
        """Salva os balanços no banco de dados com lógica de idempotência."""
        for dado in dados:
            cnpj_alvo = dado.pop('cnpj')
            ticker_real = MAPA_CNPJ_B3[cnpj_alvo]

            # Busca a empresa pelo Ticker Real (PETR4) em vez do CNPJ
            ativo = self.session.query(Ativo).filter(Ativo.ticker == ticker_real).first()

            # Se a empresa não existir no nosso banco, cadastra com o Ticker bonito!
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