import pandas as pd
import requests
import io
from datetime import datetime
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos, TipoAtivo
from atualizador_documentos import SessionDB

class RelatoriosAcoesCVM:
    def __init__(self, session):
        self.session = session

    def formatar_cnpj(self, cnpj_puro):
        """Padroniza o CNPJ (XX.XXX.XXX/XXXX-XX) para bater com a CVM"""
        cnpj = "".join(filter(str.isdigit, str(cnpj_puro)))
        if len(cnpj) != 14: return cnpj_puro
        return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"

    def baixar_dados_ipe(self, ano):
        """Faz o download direto do banco de dados oficial do Governo Federal"""
        
        # 🔴 CORREÇÃO CVM: O arquivo verdadeiro é entregue em formato ZIP compactado!
        url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip"
        print(f"📡 CVM: Baixando arquivo ZIP de documentos do ano {ano}...")
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=40)
        
        if response.status_code != 200:
            raise Exception(f"Falha ao conectar com a CVM. Status: {response.status_code}")
            
        # O Pandas é tão inteligente que descompacta o ZIP nativamente na memória e lê o CSV de dentro dele!
        import io
        return pd.read_csv(io.BytesIO(response.content), compression='zip', sep=';', encoding='latin1')

    def vasculhar_documentos(self, ano):
        # 1. Pega as Ações cadastradas no seu banco de dados
        ativos_db = self.session.query(Ativo).filter(Ativo.tipo == TipoAtivo.ACAO).all()
        if not ativos_db:
            return "Nenhuma ação cadastrada no banco de dados."
            
        mapa_ativos = {self.formatar_cnpj(a.cnpj): a for a in ativos_db if a.cnpj}
        
        # 2. Baixa o CSV da CVM
        df_ipe = self.baixar_dados_ipe(ano)
        
        # 3. Filtra apenas empresas do seu banco e os documentos que importam
        tipos_desejados = ['Fato Relevante', 'Aviso aos Acionistas', 'Comunicado ao Mercado']
        df_filtrado = df_ipe[
            (df_ipe['CNPJ_CIA'].isin(mapa_ativos.keys())) & 
            (df_ipe['CATEGORIA'].isin(tipos_desejados))
        ]
        
        docs_salvos = 0
        
        for index, row in df_filtrado.iterrows():
            cnpj_doc = str(row['CNPJ_CIA']).strip()
            ativo = mapa_ativos.get(cnpj_doc)
            
            link_pdf = str(row['LINK_ARQ']).strip()
            data_doc_str = str(row['DATA_REFERENCIA']).strip()
            categoria = str(row['CATEGORIA']).strip()
            assunto = str(row['ASSUNTO']).strip()
            
            try:
                data_pub = datetime.strptime(data_doc_str, "%Y-%m-%d").date()
            except:
                continue 
                
            # Evita duplicidade usando o link do documento
            existe = self.session.query(DocumentosQualitativos).filter(
                DocumentosQualitativos.url_pdf == link_pdf
            ).first()
            
            if not existe:
                novo_doc = DocumentosQualitativos(
                    ativo_id=ativo.id,
                    data_publicacao=data_pub,
                    tipo_documento=categoria,
                    url_pdf=link_pdf,
                    assunto=assunto,
                    # 🔴 O PULO DO GATO: Marcamos como AGUARDANDO_REVISAO para o Google Drive capturar!
                    status_processamento="AGUARDANDO_REVISAO" 
                )
                self.session.add(novo_doc)
                docs_salvos += 1
                
        self.session.commit()
        return docs_salvos