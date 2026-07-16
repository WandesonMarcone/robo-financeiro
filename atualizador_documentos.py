import os
import time
import unicodedata
from datetime import datetime, timedelta
import config
from fnet_scraper import FnetDownloader
from modules.GoogleDriveManager import GoogleDriveManager
from modules.utils import conectar_gspread
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine("sqlite:///pipeline_dados/banco_institucional.db")
SessionDB = sessionmaker(bind=engine)

# ==========================================
# 🗺️ O RADAR DE ISCAS CURTAS
# ==========================================
MAPA_ISCAS = {
    'XPML11': 'XP MALLS',
    'MXRF11': 'MAXI RENDA',
    'HGLG11': 'CGHG LOG',
    'VISC11': 'VINCI SHOPPING',
    'KNCR11': 'KINEA RENDIMENTOS',
    'GARE11': 'GUARDIAN LOG',
    'BTLG11': 'BTG PACTUAL LOG',
    'VILG11': 'VINCI LOG',
    'CPSH11': 'CAPITANIA', 
    'HGCR11': 'CSHG RECEBIVEIS',
    'VGIR11': 'VALORA', 
    'RBRY11': 'RBR PRIVATE',
    'CLIN11': 'CLAVE',
    'KNHF11': 'KINEA HEDGE',
    'KNUQ11': 'KINEA UNICO',
    'BTCI11': 'BTG PACTUAL CREDITO',
    'RZTR11': 'RZ TR',
    'GGRC11': 'GGR COVEPI',
    'TRXF11': 'TRX REAL',
    'CVBI11': 'VBI CRI'
}

def obter_tickers_da_planilha():
    try:
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        aba = planilha.worksheet("BD_FIIs")
        tickers = aba.col_values(1)[1:] 
        return list(set([t.strip().upper() for t in tickers if t.strip()])) 
    except Exception:
        return []

def normalizar_texto(texto):
    """Remove acentos e caracteres especiais para a busca ser infalível"""
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def rotina_de_atualizacao_em_massa():
    MAPA_TIPOS = {
        "14": "Relatório Gerencial",
        "10": "Relatório Trimestral",
        "15": "Fato Relevante",
        "12": "Informe Mensal",
        "3": "Demonstrações Financeiras",
        "17": "Carta ao Cotista",
        "23": "Aviso aos Cotistas"
    }

    b3 = FnetDownloader()
    drive_manager = GoogleDriveManager()
    lista_de_fiis = obter_tickers_da_planilha()
    
    print(f"🚀 Iniciando OPERAÇÃO ARRASTÃO para {len(lista_de_fiis)} FIIs...")
    relatorios_salvos = 0
    session = SessionDB()

    # Janela agressiva de 100 dias
    data_busca = (datetime.now() - timedelta(days=100)).strftime("%d/%m/%Y")

    # Em vez de buscar fundo por fundo, buscamos tudo de uma Categoria!
    for id_categoria, nome_categoria in MAPA_TIPOS.items():
        print(f"\n📡 Puxando TODOS os documentos de '{nome_categoria}' do Brasil na B3...")
        
        todos_documentos = b3.capturar_tudo(data_busca, id_categoria)
        print(f"📦 B3 entregou {len(todos_documentos)} documentos no total. Filtrando os nossos {len(lista_de_fiis)}...")

        for doc in todos_documentos:
            nome_fundo_b3 = normalizar_texto(doc['nome_fundo'])
            id_doc = doc['id']
            data_ref = doc['data_ref']

            # Verifica se algum dos nossos fundos está dentro desse documento da B3
            for ticker in lista_de_fiis:
                isca = normalizar_texto(MAPA_ISCAS.get(ticker, ticker))
                
                # Se a nossa isca (Ex: MAXI RENDA) estiver no nome do fundo da B3: MATCH!
                if isca in nome_fundo_b3:
                    
                    ativo_db = session.query(Ativo).filter(Ativo.ticker == ticker).first()
                    if not ativo_db:
                        ativo_db = Ativo(ticker=ticker, cnpj=f"PENDENTE-{ticker}", tipo="FII") 
                        session.add(ativo_db)
                        session.commit()

                    doc_existente = session.query(DocumentosQualitativos).filter(
                        DocumentosQualitativos.ativo_id == ativo_db.id,
                        DocumentosQualitativos.assunto.contains(id_doc) 
                    ).first()

                    if doc_existente:
                        continue

                    print(f"🎯 MATCH ENCONTRADO! {ticker} publicou: {nome_categoria} (ID: {id_doc})")
                    pdf_bytes = b3.baixar_pdf(id_doc)

                    if pdf_bytes:
                        temp_filename = f"/tmp/{ticker}_{id_doc}.pdf"
                        with open(temp_filename, "wb") as f:
                            f.write(pdf_bytes)

                        mes_atual = datetime.now().strftime("%Y-%m")
                        link_gerado = drive_manager.upload_pdf_organizado(
                            caminho_arquivo=temp_filename,
                            nome_arquivo=f"{nome_categoria}_{data_ref}_{id_doc}.pdf",
                            ticker=ticker,
                            mes_ref=mes_atual 
                        )

                        if os.path.exists(temp_filename):
                            os.remove(temp_filename)

                        if link_gerado:
                            novo_doc = DocumentosQualitativos(
                                ativo_id=ativo_db.id,
                                tipo_documento=nome_categoria,
                                data_publicacao=datetime.now(),
                                assunto=f"{nome_categoria} ref. {data_ref} (ID B3: {id_doc})",
                                url_pdf=link_gerado
                            )
                            session.add(novo_doc)
                            session.commit()
                            relatorios_salvos += 1
                            print(f"☁️ ✅ Salvo no Drive: {ticker} -> {nome_categoria}")
                    
                    break # Como já achamos o dono do documento, pulamos pro próximo PDF

    session.close()
    return relatorios_salvos