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
# 🧠 CÉREBRO TRADUTOR FNET (BLINDADO)
# ==========================================
# Adicionamos os nomes corporativos porque a B3 não usa a sigla nova!
MAPA_FNET_B3 = {
    'MAXI REN': 'MXRF11',
    'MXRF': 'MXRF11',
    
    'GUARDIAN': 'GARE11', 
    'GARE': 'GARE11',
    
    'CSHG LOG': 'HGLG11',
    'HGLG': 'HGLG11',
    
    'VINCI SC': 'VISC11',
    'VISC': 'VISC11',
    
    'VBI CRI': 'CVBI11',
    'CVBI': 'CVBI11',
    
    'XP MALLS': 'XPML11',
    'KINEA RI': 'KNCR11',
    'BTLG': 'BTLG11'
}

class FiisFnetScraper:
    def __init__(self, db_session: Session):
        self.session = db_session
        self.base_url_fnet = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }

    def atualizar_fiis(self, data_inicio: str = None) -> None:
        logger.info(f"Iniciando raspagem FNET (FIIs)...")
        feed_fnet = self._buscar_feed_fnet(data_inicio)

        if not feed_fnet:
            return

        documentos = self._extrair_relatorios_gerenciais(feed_fnet)
        self._salvar_documentos(documentos)
        logger.info(f"Atualização concluída. Encontrados {len(documentos)} documentos estratégicos recentes.")

    def _buscar_feed_fnet(self, data_inicio: str = None) -> List[Dict[str, Any]]:
        todos_documentos = []
        limite_por_pagina = 100
        inicio_pag = 0

        session = requests.Session()
        retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)

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
                    break
            except Exception as e:
                break
        return todos_documentos

    def _extrair_relatorios_gerenciais(self, feed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        documentos_estruturados = []
        
        # 🕸️ A REDE DE ARRASTÃO: Pegamos todos os tipos importantes para o investidor
        tipos_desejados = ["GERENCIAL", "FATO", "INFORME", "AVISO", "COMUNICADO", "MERCADO"]

        for item in feed:
            ticker_bruto = (item.get('nomePregao') or '').strip().upper()
            nome_fundo = (item.get('descricaoFundo') or '').strip().upper()
            categoria = (item.get('categoriaDocumento') or '').upper()
            tipo_doc = (item.get('tipoDocumento') or '').upper()
            assunto = (item.get('informacoesAdicionais') or '')
            id_doc = item.get('id')
            data_entrega_str = item.get('dataEntrega') or ''

            if not id_doc:
                continue

            ticker_limpo = None
            for chave_b3, ticker_oficial in MAPA_FNET_B3.items():
                if chave_b3 in ticker_bruto or chave_b3 in nome_fundo:
                    ticker_limpo = ticker_oficial
                    break
            
            if not ticker_limpo:
                continue

            # O FILTRO AMPLIADO: Se a categoria ou tipo tiver qualquer palavra da nossa rede, ele salva!
            documento_valido = False
            for palavra in tipos_desejados:
                if palavra in tipo_doc or palavra in categoria:
                    documento_valido = True
                    break

            if documento_valido:
                try:
                    data_publicacao = datetime.strptime(data_entrega_str.split(' ')[0], '%d/%m/%Y').date()
                except:
                    data_publicacao = datetime.now().date()

                url_pdf = f"https://fnet.bmfbovespa.com.br/fnet/publico/exibirDocumento?id={id_doc}"

                # Salva o nome real do documento que a B3 enviou
                nome_oficial_doc = tipo_doc if tipo_doc else categoria

                documentos_estruturados.append({
                    'ticker_temporario': ticker_limpo, 
                    'data_publicacao': data_publicacao,
                    'tipo_documento': nome_oficial_doc.title(),
                    'url_pdf': url_pdf,
                    'assunto': assunto[:250]
                })

        return documentos_estruturados

    def _salvar_documentos(self, documentos: List[Dict[str, Any]]) -> None:
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