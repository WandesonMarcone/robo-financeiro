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
# 🧠 O CÉREBRO FILTRO (LISTA VIP DE FIIs)
# ==========================================
# O robô vai ignorar qualquer fundo que não esteja nesta lista, mantendo o banco leve e rápido.
FII_VIP = [
    'GARE11', 
    'MXRF11', 
    'VISC11', 
    'CVBI11', 
    'HGLG11',
    # Quer acompanhar outros fundos no futuro? É só adicionar aqui!
    'XPML11',
    'KNCR11',
    'BTLG11'
]

class FiisFnetScraper:
    """Motor de captura de Informes e Relatórios Gerenciais via API do sistema FNET da B3/CVM."""

    def __init__(self, db_session: Session):
        self.session = db_session
        # Endpoint oficial (oculto) de onde a B3 puxa a tabela de FIIs
        self.base_url_fnet = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json'
        }

    def atualizar_fiis(self, data_inicio: str = None) -> None:
        """Método principal orquestrador para FIIs."""
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
        limite_por_pagina = 100  # Pegamos 100 de cada vez para ir mais rápido
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

        while True: # O loop só para quando a B3 disser que acabaram os documentos
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
                        # Se a B3 retornar uma lista vazia, significa que chegamos no fim!
                        break

                    todos_documentos.extend(feed_pagina)
                    inicio_pag += limite_por_pagina # "Vira a página" para os próximos 100

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
            ticker_bruto = item.get('nomePregao', '').strip().upper()
            categoria = item.get('descricaoCategoriaDocumento', '').upper()
            tipo_doc = item.get('descricaoTipoDocumento', '').upper()
            assunto = item.get('descricaoAssunto', '')
            id_doc = item.get('id')
            data_entrega_str = item.get('dataEntrega', '') # Ex: '11/07/2026 18:30'

            if not ticker_bruto or not id_doc:
                continue

            # 🛑 TRAVA DE SEGURANÇA E LIMPEZA: 
            # Verifica se algum dos nossos Tickers VIP está no nome que a B3 enviou.
            ticker_limpo = None
            for vip in FII_VIP:
                if vip in ticker_bruto:
                    ticker_limpo = vip # Garante que vai salvar bonitinho (ex: MXRF11) sem sujeira
                    break

            # Se não achou nenhum dos nossos VIPs, pula para o próximo fundo
            if not ticker_limpo:
                continue

            # Filtramos apenas os documentos vitais (Relatórios Gerenciais e Fatos Relevantes)
            if "GERENCIAL" in tipo_doc or "FATO RELEVANTE" in categoria or "FATO RELEVANTE" in tipo_doc:
                try:
                    data_publicacao = datetime.strptime(data_entrega_str.split(' ')[0], '%d/%m/%Y').date()
                except:
                    data_publicacao = datetime.now().date()

                # A MÁGICA: Esta URL pula o site da B3 e vai direto para a tela de impressão do PDF
                url_pdf = f"https://fnet.bmfbovespa.com.br/fnet/publico/exibirDocumento?id={id_doc}"

                documentos_estruturados.append({
                    'ticker_temporario': ticker_limpo, # Agora vai o nome limpo e traduzido
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

            # Busca quem é este FII na nossa tabela 'ativos'
            ativo = self.session.query(Ativo).filter(Ativo.ticker == ticker_alvo).first()

            # Se você ainda não tem esse FII cadastrado na base, ele cadastra automaticamente!
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
                # O banco avisou que este documento já foi guardado. Cancelamos a transação e seguimos.
                self.session.rollback()
                pass