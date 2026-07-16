import os
import time
from datetime import datetime, timedelta
import config
from fnet_scraper import FnetDownloader
from modules.GoogleDriveManager import GoogleDriveManager
from modules.utils import conectar_gspread

# ==========================================
# IMPORTAÇÕES DO BANCO DE DADOS
# ==========================================
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Configura a conexão com a sua memória SQLite
engine = create_engine("sqlite:///pipeline_dados/banco_institucional.db")
SessionDB = sessionmaker(bind=engine)

# ==========================================
# 🗺️ O MAPA OFICIAL DA B3 (FORÇA BRUTA)
# ==========================================
# Aqui nós ensinamos ao robô qual é a palavra exata que destrava cada fundo na B3
MAPA_FNET_B3 = {
    'XPML11': 'XP MALLS',
    'MXRF11': 'MAXI RENDA',
    'HGLG11': 'CGHG LOG', # A B3 usa CGHG e não CSHG na maioria dos casos antigos
    'VISC11': 'VINCI SHOPPING',
    'KNCR11': 'KINEA RENDIMENTOS',
    'GARE11': 'GUARDIAN LOG',
    'BTLG11': 'BTG PACTUAL LOGÍSTICA',
    'VILG11': 'VINCI LOGÍSTICA',
    'CPSH11': 'CAPITÂNIA SHOPPING', 
    'HGCR11': 'CSHG RECEBÍVEIS',
    'VGIR11': 'VALORA RE III',
    'RBRY11': 'RBR PRIVATE',
    'CLIN11': 'CLAVE ÍNDICES',
    'KNHF11': 'KINEA HEDGE',
    'KNUQ11': 'KINEA ÚNICO',
    'BTCI11': 'BTG PACTUAL CRÉDITO',
    'RZTR11': 'RZ TR P',
    'GGRC11': 'GGR COVEPI',
    'TRXF11': 'TRX REAL ESTATE',
    'CVBI11': 'VBI CRI'
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
    print(f"🚀 Iniciando varredura BLINDADA (Modo Dicionário) para {len(lista_de_fiis)} FIIs...")

    relatorios_salvos = 0
    session = SessionDB()

    # ⏪ Busca retroativa de 40 dias
    data_busca = (datetime.now() - timedelta(days=40)).strftime("%d/%m/%Y")

    # 1º LOOP: Passa FII por FII 
    for ticker in lista_de_fiis:

        # Pega a palavra-chave do dicionário (se não achar, tenta usar o próprio ticker)
        nome_pesquisa = MAPA_FNET_B3.get(ticker, ticker)
        
        print(f"\n🏢 Analisando: {ticker} (Buscando na B3 por: {nome_pesquisa})")

        ativo_db = session.query(Ativo).filter(Ativo.ticker == ticker).first()
        if not ativo_db:
            ativo_db = Ativo(ticker=ticker, cnpj=f"PENDENTE-{ticker}", tipo="FII") 
            session.add(ativo_db)
            session.commit()

        # 2º LOOP: Categoria por Categoria
        for id_categoria, nome_categoria in MAPA_TIPOS.items():

            documentos = b3.pesquisar_documentos(nome_pesquisa, data_inicio=data_busca, id_categoria=id_categoria)

            # Pausa educada para a B3 não nos bloquear
            time.sleep(1)

            for id_doc, data_ref, tipo_doc_id in documentos: 

                # Trava Anti-Duplicata
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

                    # UPLOAD NO DRIVE NA ESTRUTURA CERTA
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