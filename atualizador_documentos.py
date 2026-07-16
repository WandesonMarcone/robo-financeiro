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
# 🗺️ O RADAR DE ISCAS
# ==========================================
MAPA_ISCAS = {
    'XPML11': 'XP MALLS',
    'MXRF11': 'MAXI RENDA',
    'HGLG11': 'CGHG LOG',
    'VISC11': 'VINCI SHOPPING CENTERS',
    'KNCR11': 'KINEA RENDIMENTOS',
    'GARE11': 'GUARDIAN LOG',
    'BTLG11': 'BTG PACTUAL LOG',
    'VILG11': 'VINCI LOG',
    'CPSH11': 'CAPITANIA', 
    'HGCR11': 'CSHG RECEBIVEIS',
    'VGIR11': 'VALORA RENDA IMOBILIÁRIA',
    'RBRY11': 'RBR PRIVATE',
    'CLIN11': 'CLAVE',
    'KNHF11': 'KINEA HEDGE',
    'KNUQ11': 'KINEA UNICO',
    'BTCI11': 'BTG PACTUAL CREDITO',
    'RZTR11': 'RZ TR',
    'GGRC11': 'GGR COVEPI',
    'TRXF11': 'TRX REAL ESTATE FUNDO',
    'CVBI11': 'VBI CRI'
}

def obter_tickers_da_planilha():
    try:
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        aba = planilha.worksheet("BD_FIIs")
        tickers = aba.col_values(1)[1:] 
        return list(set([t.strip().upper() for t in tickers if t.strip()])) 
    except:
        return []

def normalizar_texto(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def rotina_de_atualizacao_em_massa():
    b3 = FnetDownloader()
    drive_manager = GoogleDriveManager()
    lista_de_fiis = obter_tickers_da_planilha()
    
    print(f"🚀 Iniciando OPERAÇÃO DE SUCESSO para {len(lista_de_fiis)} FIIs...")
    session = SessionDB()

    # Janela de 100 dias
    data_busca = (datetime.now() - timedelta(days=100)).strftime("%d/%m/%Y")
    
    # Puxa tudo de uma vez (o que o seu FnetDownloader faz bem)
    todos_documentos = b3.capturar_tudo(data_busca)
    print(f"📦 B3 entregou {len(todos_documentos)} documentos. Analisando...")

    for doc in todos_documentos:
        nome_fundo_b3 = normalizar_texto(doc['nome_fundo'])
        id_doc = doc['id']
        data_ref = doc['data_ref']
        # Usamos o nome original da B3 (o que funcionou no seu teste)
        nome_categoria_real = doc['tipo_doc'] 

        # Loop pelos FIIs para ver se algum é dono desse documento
        for ticker in lista_de_fiis:
            isca = normalizar_texto(MAPA_ISCAS.get(ticker, ticker))
            
            if isca in nome_fundo_b3:
                print(f"🔄 Analisando ID {id_doc} para o fundo {ticker}...")
                # 1. Banco de Dados
                ativo_db = session.query(Ativo).filter(Ativo.ticker == ticker).first()
                if not ativo_db:
                    ativo_db = Ativo(ticker=ticker, cnpj=f"PENDENTE-{ticker}", tipo="FII") 
                    session.add(ativo_db)
                    session.commit()

                if session.query(DocumentosQualitativos).filter(DocumentosQualitativos.assunto.contains(id_doc)).first():
                    continue

                # 2. Download
                pdf_bytes = b3.baixar_pdf(id_doc)
                if pdf_bytes:
                    temp_filename = f"/tmp/{ticker}_{id_doc}.pdf"
                    with open(temp_filename, "wb") as f:
                        f.write(pdf_bytes)

                    # 3. Arrumar Mês do Documento (YYYY-MM)
                    partes = data_ref.split('-')
                    mes_pasta = f"{partes[2]}-{partes[1]}" if len(partes) == 3 else datetime.now().strftime("%Y-%m")

                    # 4. Upload (Forçando a nova pasta para cada Ticker e Mês)
                    link_gerado = drive_manager.upload_pdf_organizado(
                        caminho_arquivo=temp_filename,
                        nome_arquivo=f"{nome_categoria_real}_{data_ref}_{id_doc}.pdf",
                        ticker=ticker,
                        mes_ref=mes_pasta 
                    )

                    if os.path.exists(temp_filename):
                        os.remove(temp_filename)

                        # 5. Salva no Banco de Dados com a Categoria Perfeita
                        if link_gerado:
                            ativo_db = session.query(Ativo).filter(Ativo.ticker == ticker).first()
                            if not ativo_db:
                                ativo_db = Ativo(ticker=ticker, cnpj=f"PENDENTE-{ticker}", tipo="FII") 
                                session.add(ativo_db)
                            
                            # GARANTIA: Forçamos que nome_inteligente seja uma string executando o método
                            # Se por acaso ele estiver armazenando a função, executamos agora:
                            categoria_final = nome_inteligente() if callable(nome_inteligente) else str(nome_inteligente)
                            
                            novo_doc = DocumentosQualitativos(
                                ativo_id=ativo_db.id,
                                tipo_documento=categoria_final.title(), # Garantia de parênteses aqui
                                data_publicacao=datetime.now(),
                                assunto=f"{categoria_final.title()} ref. {data_ref} (ID B3: {id_doc})", # Garantia de parênteses aqui
                                url_pdf=link_gerado
                            )
                            session.add(novo_doc)
                            session.commit()
                            print(f"☁️ ✅ Salvo: {ticker} -> {categoria_final} (Pasta: {mes_pasta})")
                
                break # Sai do loop de tickers, já achamos o dono do doc

    session.close()
    return "Varredura concluída."