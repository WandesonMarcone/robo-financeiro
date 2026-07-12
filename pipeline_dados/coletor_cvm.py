import logging
import requests
import zipfile
import io
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from banco_dados import DadosFinanceirosAcoes, Ativo # Importa as tabelas do banco

logger = logging.getLogger(__name__)

class AcoesCVMReader:
    """Motor de captura de dados contábeis de Ações via Arquivos Abertos CVM (ITR/DFP)."""
    
    def __init__(self, db_session: Session):
        self.session = db_session
        # URL oficial do Portal de Dados Abertos da CVM (ITR)
        self.base_url_itr = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{}.zip"

    def atualizar_acoes(self, ano: int) -> None:
        """Método principal orquestrador para Ações."""
        logger.info(f"Iniciando atualização de Ações (ITR) para o ano {ano}")
        
        # 1. Baixa e descompacta os arquivos do governo
        dataframes = self._baixar_arquivos_cvm(ano)
        if not dataframes:
            logger.error("Falha ao baixar ou processar os arquivos da CVM.")
            return
            
        # 2. Cruza os dados do Balanço e DRE
        dados_estruturados = self._processar_itr_dfp(dataframes)
        
        # 3. Salva no banco de dados de forma segura (Idempotência)
        self._salvar_no_banco(dados_estruturados)
        logger.info(f"Atualização de Ações concluída. {len(dados_estruturados)} registros processados.")

    def _baixar_arquivos_cvm(self, ano: int) -> Dict[str, pd.DataFrame]:
        """Faz o download dos ZIPs e lê os CSVs em memória usando Pandas."""
        url = self.base_url_itr.format(ano)
        logger.info(f"Baixando dados oficiais: {url}")
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status() # Verifica se o download foi bem sucedido
            
            # A MÁGICA DO RAPINA: Extrai o ZIP em memória (não lota o disco do servidor Render)
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                dfs = {}
                # Precisamos do Ativo (Caixa), Passivo (Dívida) e DRE (Receita/Lucro) Consolidados
                arquivos_alvo = [f'itr_cia_aberta_BPA_con_{ano}.csv', 
                                 f'itr_cia_aberta_BPP_con_{ano}.csv', 
                                 f'itr_cia_aberta_DRE_con_{ano}.csv']
                
                for arquivo in arquivos_alvo:
                    if arquivo in z.namelist():
                        with z.open(arquivo) as f:
                            # A CVM usa enconding 'latin1' e separador ';'
                            dfs[arquivo] = pd.read_csv(f, sep=';', encoding='latin1')
                return dfs
        except Exception as e:
            logger.error(f"Erro ao baixar/extrair CVM: {e}")
            return {}

    def _processar_itr_dfp(self, dfs: Dict[str, pd.DataFrame]) -> List[Dict[str, Any]]:
        """Filtra as contas contábeis padronizadas e estrutura os dados num dicionário."""
        registros = {}
        
        # Dicionário de Códigos Oficiais de Contabilidade da CVM
        MAPA_CONTAS = {
            '1.01': 'caixa',               # Conta: Caixa e Equivalentes de Caixa
            '2': 'passivo_total',          # Conta: Passivo Total
            '3.01': 'receita',             # Conta: Receita de Venda
            '3.11': 'lucro_liquido'        # Conta: Lucro/Prejuízo Consolidado do Período
        }

        for nome_arquivo, df in dfs.items():
            # Filtra apenas o trimestre atual (descarta histórico passado do mesmo arquivo) e as contas que queremos
            df_filtrado = df[(df['ORDEM_EXERC'] == 'ÚLTIMO') & (df['CD_CONTA'].isin(MAPA_CONTAS.keys()))].copy()
            
            for _, row in df_filtrado.iterrows():
                cnpj = row['CNPJ_CIA']
                data_ref_str = row['DT_REFER']
                conta = row['CD_CONTA']
                valor = row['VL_CONTA'] * 1000  # Os dados da CVM vêm cortados em milhares. Multiplicamos para ter o valor real.
                
                try:
                    data_ref = datetime.strptime(data_ref_str, '%Y-%m-%d').date()
                except:
                    continue
                    
                # Criamos uma chave única para agrupar os dados da mesma empresa no mesmo trimestre
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
                        'ebitda': None # Requer cruzamento avançado de depreciação, podemos deixar nulo por enquanto
                    }
                
                # Preenche a gaveta correta (ex: se for 3.11, joga o valor na chave 'lucro_liquido')
                campo = MAPA_CONTAS[conta]
                registros[chave][campo] = float(valor)

        return list(registros.values())

    def _salvar_no_banco(self, dados: List[Dict[str, Any]]) -> None:
        """Salva os balanços no banco de dados com lógica de idempotência."""
        for dado in dados:
            cnpj_alvo = dado.pop('cnpj')
            
            # Busca a empresa pelo CNPJ na tabela de Ativos
            ativo = self.session.query(Ativo).filter(Ativo.cnpj == cnpj_alvo).first()
            
            # Se a empresa não existir no nosso banco, cadastra provisoriamente
            if not ativo:
                ticker_prov = f"CVM_{cnpj_alvo[:8]}"
                ativo = Ativo(ticker=ticker_prov, cnpj=cnpj_alvo, tipo="ACAO")
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
                # Idempotência: O banco avisou que este trimestre já está salvo para esta empresa. Pula e segue a vida.
                self.session.rollback()
                pass
