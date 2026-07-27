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
        ativos_db = self.session.query(Ativo).filter(Ativo.tipo == TipoAtivo.ACAO).all()
        if not ativos_db:
            return "Nenhuma ação cadastrada no banco de dados."
            
        mapa_ativos = {self.formatar_cnpj(a.cnpj): a for a in ativos_db if a.cnpj}
        df_ipe = self.baixar_dados_ipe(ano)
        
        # 🔴 MAPEADOR INTELIGENTE CVM: Encontra as colunas independente do nome exato!
        col_cnpj = next((col for col in df_ipe.columns if 'CNPJ' in col.upper()), 'CNPJ_Companhia')
        col_link = next((col for col in df_ipe.columns if 'LINK' in col.upper()), 'Link_Download')
        col_data = next((col for col in df_ipe.columns if 'DATA' in col.upper()), 'Data_Referencia')
        col_categoria = next((col for col in df_ipe.columns if 'CATEGORIA' in col.upper()), 'Categoria')
        col_assunto = next((col for col in df_ipe.columns if 'ASSUNTO' in col.upper()), 'Assunto')

        tipos_desejados = [
            'Fato Relevante', 
            'Aviso aos Acionistas', 
            'Comunicado ao Mercado',
            'Apresentação de Resultados',     # Os slides bonitos que a diretoria apresenta
            'Demonstrações Financeiras',      # O balanço completo em PDF
            'Relatório da Administração',     # Carta do CEO explicando o trimestre
            'Assembleia',                     # Votações importantes
            'Formulário de Referência'        # O raio-x completo da empresa (anual)
]

        
        # Filtra a planilha do governo
        df_filtrado = df_ipe[
            (df_ipe[col_cnpj].isin(mapa_ativos.keys())) & 
            (df_ipe[col_categoria].isin(tipos_desejados))
        ]
        
        docs_salvos = 0
        for index, row in df_filtrado.iterrows():
            cnpj_doc = str(row[col_cnpj]).strip()
            ativo = mapa_ativos.get(cnpj_doc)
            link_pdf = str(row[col_link]).strip()
            data_doc_str = str(row[col_data]).strip()
            categoria = str(row[col_categoria]).strip()
            assunto = str(row[col_assunto]).strip()
            
            try:
                # Alguns arquivos da CVM vêm com hora junto com a data, o split resolve isso
                data_limpa = data_doc_str.split(" ")[0]
                data_pub = datetime.strptime(data_limpa, "%Y-%m-%d").date()
            except:
                continue 
                
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
                    status_processamento="PENDENTE_ACAO" 
                )
                self.session.add(novo_doc)
                docs_salvos += 1
                
        self.session.commit()
        return docs_salvos