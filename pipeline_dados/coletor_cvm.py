import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from banco_dados import DadosFinanceirosAcoes # Importa a tabela do banco

logger = logging.getLogger(__name__)

class AcoesCVMReader:
    """Motor de captura de dados contábeis de Ações via Arquivos Abertos CVM (ITR/DFP)."""
    
    def __init__(self, db_session: Session):
        self.session = db_session

    def atualizar_acoes(self, ano: int) -> None:
        """Método principal orquestrador para Ações."""
        logger.info(f"Iniciando atualização de Ações para o ano {ano}")
        arquivos_csv = self._baixar_arquivos_cvm(ano)
        dados_estruturados = self._processar_itr_dfp(arquivos_csv)
        self._salvar_no_banco(dados_estruturados)
        logger.info("Atualização de Ações concluída.")

    def _baixar_arquivos_cvm(self, ano: int) -> List[str]:
        """Faz o download dos ZIPs do Portal de Dados Abertos da CVM e descompacta os CSVs."""
        # TODO: Lógica de download com requests/wget (ex: http://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/)
        pass

    def _processar_itr_dfp(self, caminhos_csv: List[str]) -> List[Dict[str, Any]]:
        """Lê os CSVs com Pandas, filtra as contas contábeis e estrutura os dados."""
        # TODO: Lógica do projeto Rapina (Pandas) para cruzar DRE e Balanço
        pass

    def _salvar_no_banco(self, dados: List[Dict[str, Any]]) -> None:
        """Salva os dados de Ações com lógica de idempotência."""
        for dado in dados:
            try:
                # Instanciar DadosFinanceirosAcoes e adicionar
                novo_registro = DadosFinanceirosAcoes(**dado)
                self.session.add(novo_registro)
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                # Idempotência: Se o UniqueConstraint reclamar, o dado já existe. Pulamos.