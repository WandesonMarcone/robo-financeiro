import os
import time
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
# 🗺️ MAPA DE PALAVRAS CURTAS (ISCA)
# ==========================================
MAPA_FNET_B3 = {
    'XPML11': 'XP MALLS',
    'MXRF11': 'MAXI RENDA',
    'HGLG11': 'CGHG LOG', 
    'VISC11': 'VINCI SHOPPING',
    'KNCR11': 'KINEA RENDIMENTOS',
    'GARE11': 'GUARDIAN LOG',
    'BTLG11': 'BTG PACTUAL LOGISTICA', # Isca curta
    'VILG11': 'VINCI LOGÍSTICA',
    'CPSH11': 'CAPITÂNIA SHOPPING', 
    'HGCR11': 'CSHG RECEBÍVEIS',
    'VGIR11': 'VALORA', # Isca curta
    'RBRY11': 'RBR PRIVATE',
    'CLIN11': 'CLAVE ÍNDICES',
    'KNHF11': 'KINEA HEDGE',
    'KNUQ11': 'KINEA ÚNICO',
    'BTCI11': 'BTG PACTUAL CRÉDITO',
    'RZTR11': 'RZ TR', # Isca curta
    'GGRC11': 'GGR COVEPI',
    'TRXF11': 'TRX REAL', # Isca curta
    'CVBI11': 'VBI CRI'
}

def obter_tickers_da_planilha():
    try:
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        aba = planilha.worksheet("BD_FIIs")
        tickers = aba.col_values(1)[1:] 
        return list(set([t.strip().upper() for t in tickers if t.strip()])) 
    except Exception as e:
        print(f"Erro ao ler planilha: {e}")
        return []

def rotina_de_atualizacao_em_massa():
    # Aqui usamos os números exatos para fugir dos bugs de texto da B3
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
    print(f"🚀 Iniciando varredura ESPIÃ para {len(lista_de_fiis)} FIIs...")

    relatorios_salvos = 0
    session = SessionDB()

    # ⏪ Janela agressiva de 90 dias para volume máximo
    data_busca = (datetime.now() - timedelta(days=90)).strftime("%d/%m/%Y")

    for ticker in lista_de_fiis:
        nome_pesquisa = MAPA_FNET_B3.get(ticker, ticker)
        print(f"\n🏢 Analisando: {ticker} (Buscando na B3 por: {nome_pesquisa})")

        ativo_db = session.query(Ativo).filter(Ativo.ticker == ticker).first()
        if not ativo_db:
            ativo_db = Ativo(ticker=ticker, cnpj=f"PENDENTE-{ticker}", tipo="FII") 
            session.add(ativo_db)
            session.commit()

        for id_categoria, nome_categoria in MAPA_TIPOS.items():
            documentos = b3.pesquisar_documentos(nome_pesquisa, data_inicio=data_busca, id_categoria=id_categoria)
            time.sleep(1) # Pausa para a B3 não nos derrubar

            for id_doc, data_ref, tipo_doc_id in documentos: 
                doc_existente = session.query(DocumentosQualitativos).filter(
                    DocumentosQualitativos.ativo_id == ativo_db.id,
                    DocumentosQualitativos.assunto.contains(id_doc) 
                ).first()

                if doc_existente:
                    continue

                print(f"⬇️ Baixando: {nome_categoria} (ID B3: {id_doc})")
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

    session.close()
    return relatorios_salvos