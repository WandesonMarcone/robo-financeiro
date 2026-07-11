import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from banco_dados import DadosFinanceirosFiis, DocumentosQualitativos # Importa as tabelas do banco

logger = logging.getLogger(__name__)

class FiisFnetScraper:
    """Motor de captura de Informes e Relatórios Gerenciais via API do sistema FNET da B3/CVM."""
    
    def __init__(self, db_session: Session):
        self.session = db_session
        self.base_url_fnet = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"

    def atualizar_fiis(self, data_inicio: str) -> None:
        """Método principal orquestrador para FIIs."""
        logger.info(f"Iniciando raspagem FNET a partir de {data_inicio}")
        feed_fnet = self._buscar_feed_fnet(data_inicio)
        
        informes = self._extrair_informe_mensal(feed_fnet)
        documentos = self._extrair_relatorios_gerenciais(feed_fnet)
        
        self._salvar_dados_fiis(informes)
        self._salvar_documentos(documentos)
        logger.info("Atualização de FIIs concluída.")

    def _buscar_feed_fnet(self, data_inicio: str) -> List[Dict[str, Any]]:
        """Faz a requisição paginada (JSON) na API pública do FNET."""
        # TODO: Usar requests para bater na URL do FNET, manipulando headers e paginação.
        pass

    def _extrair_informe_mensal(self, feed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filtra o feed procurando 'Informe Mensal' e faz o parse do XML/JSON da CVM."""
        # TODO: Lógica para pegar PL, Caixa, Ativo Total
        pass

    def _extrair_relatorios_gerenciais(self, feed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filtra o feed procurando 'Relatório Gerencial' ou 'Fato Relevante' 
        e constrói a URL oficial de download do PDF no FNET.
        """
        # A URL de download do FNET geralmente tem a estrutura:
        # https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?id={idDocumento}
        pass

    def _salvar_dados_fiis(self, dados: List[Dict[str, Any]]) -> None:
        """Idempotência para os Informes Mensais."""
        pass # Lógica similar ao _salvar_no_banco usando IntegrityError

    def _salvar_documentos(self, documentos: List[Dict[str, Any]]) -> None:
        """Idempotência para PDFs: Só salva se a URL for inédita no banco."""
        for doc in documentos:
            try:
                novo_doc = DocumentosQualitativos(**doc)
                self.session.add(novo_doc)
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                # O PDF gerencial já está mapeado no nosso banco. Ignorar.
