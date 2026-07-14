import logging
import requests
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from banco_dados import DadosFinanceirosFiis, DocumentosQualitativos, Ativo
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ==========================================
# 🧠 O CÉREBRO TRADUTOR FNET (MAPA DE NOME PARA TICKER)
# ==========================================
# O FNET não envia o "11". Ele envia nomes de pregão quebrados (ex: "FII MAXI REN").
# Este dicionário traduz o nome esquisito da B3 para o seu Ticker real (VIP).
MAPA_FNET_B3 = {
    'MAXI REN': 'MXRF11',
    'CSHG LOG': 'HGLG11',
    'VINCI SC': 'VISC11',
    'VBI CRI': 'CVBI11',
    'GARE': 'GARE11',
    
    # Futuros FIIs que você quiser acompanhar
    'XP MALLS': 'XPML11',
    'KINEA RI': 'KNCR11',
    'BTLG': 'BTLG11'
}

class FiisFnetScraper:
    """Motor de captura de Informes e Relatórios Gerenciais via API do sistema FNET da B3/CVM."""

    def __init__(self, db_session: Session):
        self.session = db_session
        self.base_url_fnet = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json'
        }

    def atualizar_fiis(self, data_inicio: str = None) -> None:
        logger.info(f"Iniciando raspagem FNET (FIIs)...")
        feed_fnet = self._buscar_feed_fnet(data_inicio)

        if not feed_fnet:
            logger.warning("Nenhum dado retornado do FNET.")
            return

        documentos = self._extrair_relatorios_gerenciais(feed_fnet)
        self._salvar_documentos(documentos)
        logger.info(f"Atualização concluída. Encontrados {len(documentos)} documentos estratégicos recentes.")

    def _buscar_feed_fnet(self, data_inicio: str = None) -> List[Dict[str, Any]]:
        """Faz a requisição com paginação para varrer TODOS os documentos do ano."""
        todos_documentos = []
        limite_por_pagina = 100
        inicio_pag = 0

        session = requests.Session()
        retry_strategy = Retry(
            total=3,                
            backoff_factor=1,       
            status_forcelist=[500, 502, 503, 504] 
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)

        logger.info("Iniciando leitura das páginas do FNET...")

        while True: 
            params = {
                'd': 1, 's': inicio_pag, 'l': limite_por_pagina,
                'tipoFundo': 1, 'idCategoriaDocumento': 0,
                'idTipoDocumento': 0, 'idEspecieDocumento': 0
            }
            if data_inicio:
                params['dataInicial'] = data_inicio

            try:
                response = session.get(self.base_url_fnet, headers=self.headers, params=params, timeout=60)

                if response.status_code == 200:
                    dados = response.json()
                    feed_pagina = dados.get('data', [])
                    
                    if not feed_pagina:
                        break
                    
                    todos_documentos.extend(feed_pagina)
                    inicio_pag += limite_por_pagina 
                    
                    print(f"📖 Varrendo B3... {len(todos_documentos)} documentos analisados até agora.")
                else:
                    print(f"Erro no FNET na página {inicio_pag}: HTTP {response.status_code}")
                    break
            except Exception as e:
                print(f"Falha ao conectar no FNET na página {inicio_pag}: {e}")
                break
        
        return todos_documentos

    def _extrair_relatorios_gerenciais(self, feed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filtra o feed procurando 'Relatório Gerencial' ou 'Fato Relevante' e constrói a URL oficial."""
        documentos_estruturados = []

        for item in feed:
            # O nomePregao vem quebrado, ex: "FII MAXI REN"
            ticker_bruto = item.get('nomePregao', '').strip().upper()
            categoria = item.get('descricaoCategoriaDocumento', '').upper()
            tipo_doc = item.get('descricaoTipoDocumento', '').upper()
            assunto = item.get('descricaoAssunto', '')
            id_doc = item.get('id')
            data_entrega_str = item.get('dataEntrega', '') 

            if not ticker_bruto or not id_doc:
                continue
            
            # 🛑 TRAVA DE SEGURANÇA E TRADUÇÃO: 
            # Checamos se a chave (ex: "MAXI REN") está no nome que a B3 enviou. Se tiver, vira MXRF11!
            ticker_limpo = None
            for chave_b3, ticker_oficial in MAPA_FNET_B3.items():
                if chave_b3 in ticker_bruto:
                    ticker_limpo = ticker_oficial
                    break
            
            if not ticker_limpo:
                continue

            if "GERENCIAL" in tipo_doc or "FATO RELEVANTE" in categoria or "FATO RELEVANTE" in tipo_doc:
                try:
                    data_publicacao = datetime.strptime(data_entrega_str.split(' ')[0], '%d/%m/%Y').date()
                except:
                    data_publicacao = datetime.now().date()

                url_pdf = f"https://fnet.bmfbovespa.com.br/fnet/publico/exibirDocumento?id={id_doc}"

                documentos_estruturados.append({
                    'ticker_temporario': ticker_limpo, 
                    'data_publicacao': data_publicacao,
                    'tipo_documento': "Relatório Gerencial" if "GERENCIAL" in tipo_doc else "Fato Relevante",
                    'url_pdf': url_pdf,
                    'assunto': assunto[:250]
                })

        return documentos_estruturados

    def _salvar_documentos(self, documentos: List[Dict[str, Any]]) -> None:
        """Idempotência para PDFs: Relaciona o ticker com o banco e salva sem duplicar."""
        for doc in documentos:
            ticker_alvo = doc.pop('ticker_temporario')

            ativo = self.session.query(Ativo).filter(Ativo.ticker == ticker_alvo).first()

            if not ativo:
                ativo = Ativo(ticker=ticker_alvo, cnpj="00.000.000/0000-00", tipo="FII")
                self.session.add(ativo)
                try:
                    self.session.commit()
                except:
                    self.session.rollback()
                    continue

            doc['ativo_id'] = ativo.id

            try:
                novo_doc = DocumentosQualitativos(**doc)
                self.session.add(novo_doc)
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                pass