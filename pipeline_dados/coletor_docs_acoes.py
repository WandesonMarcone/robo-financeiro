import io
import logging

import pandas as pd
import requests

from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos, TipoAtivo
from pipeline_dados.normalizacao import formatar_cnpj, normalizar_data
from pipeline_dados.qualidade_dados import INVALID, registrar_diagnostico, validar_registro

logger = logging.getLogger(__name__)


class RelatoriosAcoesCVM:
    def __init__(self, session):
        self.session = session

    def baixar_dados_ipe(self, ano):
        """Faz o download direto do banco de dados oficial do Governo Federal."""
        url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip"
        print(f"CVM: Baixando arquivo ZIP de documentos do ano {ano}...")

        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=40)

        if response.status_code != 200:
            raise Exception(f"Falha ao conectar com a CVM. Status: {response.status_code}")

        return pd.read_csv(io.BytesIO(response.content), compression='zip', sep=';', encoding='latin1')

    def vasculhar_documentos(self, ano):
        ativos_db = self.session.query(Ativo).filter(Ativo.tipo == TipoAtivo.ACAO).all()
        if not ativos_db:
            return "Nenhuma ação cadastrada no banco de dados."

        mapa_ativos = {formatar_cnpj(a.cnpj): a for a in ativos_db if a.cnpj}
        df_ipe = self.baixar_dados_ipe(ano)

        col_cnpj = next((col for col in df_ipe.columns if 'CNPJ' in col.upper()), 'CNPJ_Companhia')
        col_link = next((col for col in df_ipe.columns if 'LINK' in col.upper()), 'Link_Download')
        col_data = next((col for col in df_ipe.columns if 'DATA' in col.upper()), 'Data_Referencia')
        col_categoria = next((col for col in df_ipe.columns if 'CATEGORIA' in col.upper()), 'Categoria')
        col_assunto = next((col for col in df_ipe.columns if 'ASSUNTO' in col.upper()), 'Assunto')

        tipos_desejados = [
            'Fato Relevante',
            'Aviso aos Acionistas',
            'Comunicado ao Mercado',
            'Apresentação de Resultados',
            'Demonstrações Financeiras',
            'Relatório da Administração',
            'Assembleia',
            'Formulário de Referência'
        ]

        df_filtrado = df_ipe[
            (df_ipe[col_cnpj].isin(mapa_ativos.keys())) &
            (df_ipe[col_categoria].isin(tipos_desejados))
        ]

        docs_salvos = 0
        for _, row in df_filtrado.iterrows():
            cnpj_doc = str(row[col_cnpj]).strip()
            ativo = mapa_ativos.get(cnpj_doc)
            link_pdf = str(row[col_link]).strip()
            data_doc_str = str(row[col_data]).strip()
            categoria = str(row[col_categoria]).strip()
            assunto = str(row[col_assunto]).strip()

            existe = self.session.query(DocumentosQualitativos).filter(
                DocumentosQualitativos.url_pdf == link_pdf
            ).first()

            if not existe:
                # DATA QUALITY (Fase 3, Bloco 3): regras determinísticas antes
                # de persistir. INVALID -> não salva o documento; WARNING ->
                # salva, mas o alerta é registrado para diagnóstico.
                data_pub = normalizar_data(data_doc_str)
                resultado = validar_registro(
                    {
                        "data_publicacao": data_pub,
                        "tipo_documento": categoria,
                        "url_pdf": link_pdf,
                        "ativo": ativo.ticker,
                    },
                    "documento_ipe",
                    origem="CVM/IPE",
                    ativo=ativo.ticker,
                    documento=link_pdf,
                )
                registrar_diagnostico(resultado, logger)
                if resultado.status == INVALID:
                    logger.warning(
                        "Qualidade: documento %s rejeitado; não persistido.", link_pdf
                    )
                    continue

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
