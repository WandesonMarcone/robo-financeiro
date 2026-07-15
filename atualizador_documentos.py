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
    """Função Mestra com Memória Anti-Duplicata e Google Drive"""
    b3 = FnetDownloader()
    drive_manager = GoogleDriveManager() # Iniciamos o Gerenciador aqui
    lista_de_fiis = obter_tickers_da_planilha()
    print(f"🚀 Iniciando atualização diária para {len(lista_de_fiis)} FIIs...")

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

        documentos = b3.pesquisar_documentos(nome_pesquisa, data_inicio=data_hoje)

        for id_doc, data_ref in documentos:
            doc_existente = session.query(DocumentosQualitativos).filter(
                DocumentosQualitativos.ativo_id == ativo_db.id,
                DocumentosQualitativos.assunto.contains(id_doc) 
            ).first()

            if doc_existente:
                continue

            print(f"⬇️ Baixando documento inédito: {ticker} (ID: {id_doc})...")
            pdf_bytes = b3.baixar_pdf(id_doc)

            if pdf_bytes:
                # 1. SALVAR EM ARQUIVO TEMPORÁRIO (O Drive precisa de um caminho de arquivo)
                temp_filename = f"/tmp/{ticker}_{id_doc}.pdf"
                with open(temp_filename, "wb") as f:
                    f.write(pdf_bytes)

                # 2. FAZER O UPLOAD NO GOOGLE DRIVE
                link_gerado = drive_manager.upload_pdf_organizado(
                    caminho_arquivo=temp_filename,
                    nome_arquivo=f"Relatorio_{data_ref}_{id_doc}.pdf",
                    ticker=ticker,
                    categoria="Relatórios Gerenciais"
                )

                # 3. LIMPEZA (Apaga o arquivo temporário)
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)

                if link_gerado:
                    novo_doc = DocumentosQualitativos(
                        ativo_id=ativo_db.id,
                        tipo_documento="Relatório Gerencial",
                        data_publicacao=datetime.now(),
                        assunto=f"Relatório ref. {data_ref} (ID B3: {id_doc})",
                        url_pdf=link_gerado
                    )
                    session.add(novo_doc)
                    session.commit()
                    relatorios_salvos += 1

    session.close()
    return relatorios_salvos