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
            try: # 🛡️ Try/Except para o robô não morrer se um PDF der erro
                nome_fundo_b3 = normalizar_texto(doc['nome_fundo'])
                id_doc = doc['id']
                data_ref = doc['data_ref']
                tipo_original = doc['tipo_doc'] 

                for ticker in lista_de_fiis:
                    isca = normalizar_texto(MAPA_ISCAS.get(ticker, ticker))
                    
                    if isca in nome_fundo_b3:
                        # Trava Anti-Duplicata
                        if session.query(DocumentosQualitativos).filter(DocumentosQualitativos.assunto.contains(id_doc)).first():
                            continue

                        print(f"🔄 Analisando ID {id_doc} para {ticker}...")
                        pdf_bytes = b3.baixar_pdf(id_doc)

                        if pdf_bytes:
                            temp_filename = f"/tmp/{ticker}_{id_doc}.pdf"
                            with open(temp_filename, "wb") as f:
                                f.write(pdf_bytes)

                            # Extração de texto para IA
                            texto_pdf = ""
                            try:
                                reader = PyPDF2.PdfReader(temp_filename)
                                if len(reader.pages) > 0:
                                    texto_pdf = reader.pages[0].extract_text()
                            except: pass
                            
                            # 🎯 A CHAMADA CORRETA DA IA
                            # Forçamos o resultado ser string e usamos .title() com parênteses!
                            classificacao = classificar_documento_com_ia(tipo_original, texto_pdf)
                            nome_limpo = str(classificacao).strip().title() 
                            # Remove caracteres que não podem ir em nomes de arquivos (ex: / ou :)
                            nome_inteligente = "".join([c for c in nome_limpo if c.isalnum() or c in (' ', '_', '-')]).strip()

                            # Arruma pasta
                            partes_data = data_ref.split('-')
                            mes_pasta = f"{partes_data[2]}-{partes_data[1]}" if len(partes_data) == 3 else datetime.now().strftime("%Y-%m")

                            # Upload
                            link_gerado = drive_manager.upload_pdf_organizado(
                                caminho_arquivo=temp_filename,
                                nome_arquivo=f"{nome_inteligente}_{data_ref}_{id_doc}.pdf",
                                ticker=ticker,
                                mes_ref=mes_pasta 
                            )

                            if os.path.exists(temp_filename): os.remove(temp_filename)

                            # Salva no Banco
                            if link_gerado:
                                novo_doc = DocumentosQualitativos(
                                    ativo_id=session.query(Ativo).filter(Ativo.ticker == ticker).first().id,
                                    tipo_documento=nome_inteligente, 
                                    data_publicacao=datetime.now(),
                                    assunto=f"{nome_inteligente} ref. {data_ref} (ID B3: {id_doc})",
                                    url_pdf=link_gerado
                                )
                                session.add(novo_doc)
                                session.commit()
                                print(f"☁️ ✅ Salvo: {ticker} -> {nome_inteligente}")
                        
                        break # Próximo doc

            except Exception as e:
                print(f"❌ Erro ao processar ID {id_doc}: {e}")
                continue # Continua o loop principal mesmo se der erro

    session.close()
    return "Varredura concluída."