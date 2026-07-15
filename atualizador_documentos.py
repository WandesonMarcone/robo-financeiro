from fnet_scraper import FnetDownloader
from modules.GoogleDriveManager import GoogleDriveManager
from modules.utils import conectar_gspread
import config
from datetime import datetime
import os # Adicione este import no topo do arquivo
from modules.GoogleDriveManager import GoogleDriveManager

# ==========================================
# IMPORTAÇÕES DO BANCO DE DADOS
# ==========================================
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Configura a conexão com a sua memória SQLite
engine = create_engine("sqlite:///pipeline_dados/banco_institucional.db")
SessionDB = sessionmaker(bind=engine)
drive_manager = GoogleDriveManager()

# O seu mapa para corrigir os nomes da B3
MAPA_FNET_B3 = {
    'MAXI REN': 'MXRF11', 'MXRF': 'MXRF11',
    'GUARDIAN': 'GARE11', 'GARE': 'GARE11',
    'CSHG LOG': 'HGLG11', 'HGLG': 'HGLG11',
    'VINCI SC': 'VISC11', 'VISC': 'VISC11',
    'VBI CRI': 'CVBI11', 'CVBI': 'CVBI11',
    'XP MALLS': 'XPML11',
    'KINEA RI': 'KNCR11',
    'BTLG': 'BTLG11'
}

def obter_tickers_da_planilha():
    """Conecta no Google Sheets e puxa todos os FIIs cadastrados na Coluna A."""
    try:
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        aba = planilha.worksheet("BD_FIIs")
        tickers = aba.col_values(1)[1:] 
        tickers = [t.strip().upper() for t in tickers if t.strip()]
        return list(set(tickers)) 
    except Exception as e:
        print(f"Erro ao ler planilha: {e}")
        return []

def rotina_de_atualizacao_em_massa():
    """Função Mestra para capturar TODOS os tipos de documentos e organizar no Drive"""
    b3 = FnetDownloader()
    drive_manager = GoogleDriveManager()
    lista_de_fiis = obter_tickers_da_planilha()
    print(f"🚀 Iniciando varredura TOTAL para {len(lista_de_fiis)} FIIs...")

    relatorios_salvos = 0
    session = SessionDB()
    data_hoje = datetime.now().strftime("%d/%m/%Y")

    for ticker in lista_de_fiis:
        nome_pesquisa = ticker
        for chave, valor in MAPA_FNET_B3.items():
            if valor == ticker:
                nome_pesquisa = chave
                break 

        ativo_db = session.query(Ativo).filter(Ativo.ticker == ticker).first()
        if not ativo_db:
            ativo_db = Ativo(ticker=ticker)
            session.add(ativo_db)
            session.commit()

        # REMOVIDO O FILTRO DE TIPO AQUI (Assumindo que o FnetDownloader retorna tudo se não filtrar)
        # Se o seu FnetDownloader exigir um tipo, verifique se existe um valor que signifique "Todos"
        documentos = b3.pesquisar_documentos(nome_pesquisa, data_inicio=data_hoje)

        # Ajuste aqui: verifique se o seu scraper retorna uma tupla com (id, data, tipo)
        # Se retornar apenas (id, data), você precisará usar uma função interna para descobrir o tipo.
        for id_doc, data_ref, tipo_doc in documentos: 

            # Trava Anti-Duplicata
            doc_existente = session.query(DocumentosQualitativos).filter(
                DocumentosQualitativos.ativo_id == ativo_db.id,
                DocumentosQualitativos.assunto.contains(id_doc) 
            ).first()

            if doc_existente:
                continue

            print(f"⬇️ Baixando {tipo_doc} de {ticker} (ID: {id_doc})...")
            pdf_bytes = b3.baixar_pdf(id_doc)

            if pdf_bytes:
                # 1. SALVAR TEMPORÁRIO
                temp_filename = f"/tmp/{ticker}_{id_doc}.pdf"
                with open(temp_filename, "wb") as f:
                    f.write(pdf_bytes)

                # 2. UPLOAD DINÂMICO (Usa o tipo_doc como categoria da pasta!)
                link_gerado = drive_manager.upload_pdf_organizado(
                    caminho_arquivo=temp_filename,
                    nome_arquivo=f"{tipo_doc}_{data_ref}_{id_doc}.pdf",
                    ticker=ticker,
                    categoria=tipo_doc  # <-- Agora o Drive cria pastas automáticas por categoria (Ex: Fato Relevante, Comunicado)
                )

                if os.path.exists(temp_filename):
                    os.remove(temp_filename)

                if link_gerado:
                    novo_doc = DocumentosQualitativos(
                        ativo_id=ativo_db.id,
                        tipo_documento=tipo_doc, # <-- Salva o tipo correto no banco
                        data_publicacao=datetime.now(),
                        assunto=f"{tipo_doc} ref. {data_ref} (ID B3: {id_doc})",
                        url_pdf=link_gerado
                    )
                    session.add(novo_doc)
                    session.commit()
                    relatorios_salvos += 1

    session.close()
    return relatorios_salvos