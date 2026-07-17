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
import PyPDF2
from groq import Groq
from config import MAPA_ISCAS_MASTER

client = Groq(api_key=config.GROQ_API_KEY)
engine = create_engine("sqlite:///pipeline_dados/banco_institucional.db")
SessionDB = sessionmaker(bind=engine)

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

def classificar_documento_com_ia(nome_original, texto_extraido):
    if not texto_extraido: return nome_original
    prompt = f"Classifique este documento FII que começa assim: {texto_extraido[:800]}\n" \
             "Escolha ESTRITAMENTE UMA opção: Relatorio Gerencial, Fato Relevante, Informe Mensal, Demonstracoes Financeiras, Aviso aos Cotistas, Rendimentos, Outros. Responda APENAS o nome."
    try:
        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama3-8b-8192"
        )
        return chat.choices[0].message.content.strip()
    except Exception as e:
        return "Documento_FII" # Fallback de segurança mais limpo

# ==========================================
# CAMADA 1: COLETA (Rápida e sem travar)
# ==========================================
def rotina_de_coleta_b3():
    b3 = FnetDownloader()
    lista_de_fiis = obter_tickers_da_planilha()
    session = SessionDB()

    # Ajustado para os últimos 85 dias - (14/04/26) (Pega os atuais)
    data_busca = (datetime.now() - timedelta(days=85)).strftime("%d/%m/%Y")
    todos_documentos = b3.capturar_tudo(data_busca)
    
    novos = 0
    for doc in todos_documentos:
        nome_fundo_b3 = normalizar_texto(doc['nome_fundo'])
        id_doc = str(doc['id'])
        
        for ticker in lista_de_fiis:
            isca = normalizar_texto(MAPA_ISCAS_MASTER.get(ticker, ticker))
            if isca in nome_fundo_b3:
                # Verifica se já temos ESSE id_b3 no banco
                existe = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.id_b3 == id_doc).first()
                if not existe:
                    ativo_db = session.query(Ativo).filter(Ativo.ticker == ticker).first()
                    if not ativo_db:
                        ativo_db = Ativo(ticker=ticker, cnpj=f"PENDENTE-{ticker}", tipo="FII") 
                        session.add(ativo_db)
                        session.commit()
                        
                    # 🚀 A MÁQUINA DE ESTADOS COMEÇA AQUI
                    novo_doc = DocumentosQualitativos(
                        ativo_id=ativo_db.id,
                        id_b3=id_doc,
                        data_publicacao=datetime.now(),
                        tipo_documento=doc['tipo_doc'], # Tipo bruto da B3
                        assunto=doc['data_ref'], # Usando provisoriamente para guardar a data de ref
                        status_processamento="PENDENTE"
                    )
                    session.add(novo_doc)
                    session.commit()
                    novos += 1
                break
    session.close()
    return novos

# ==========================================
# CAMADA 2 E 3: PROCESSAMENTO, VALIDAÇÃO E DRIVE
# ==========================================
def rotina_processar_pendentes():
    b3 = FnetDownloader()
    drive_manager = GoogleDriveManager()
    session = SessionDB()
    
    # Busca apenas quem está PENDENTE no banco
    pendentes = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.status_processamento == "PENDENTE").all()
    
    print(f"⚙️ Processando {len(pendentes)} documentos na fila...")
    
    for doc_db in pendentes:
        ticker = doc_db.ativo.ticker
        id_doc = doc_db.id_b3
        data_ref = doc_db.assunto # Resgatando a data de ref
        
        print(f"🔄 Processando fila: {ticker} (ID {id_doc})...")
        
        pdf_bytes = b3.baixar_pdf(id_doc)
        if not pdf_bytes:
            doc_db.status_processamento = "ERRO_DOWNLOAD"
            session.commit()
            continue
            
        temp_filename = f"/tmp/{ticker}_{id_doc}.pdf"
        with open(temp_filename, "wb") as f: f.write(pdf_bytes)
            
        # VALIDAÇÃO DUPLO FATOR
        texto_pdf = ""
        try:
            reader = PyPDF2.PdfReader(temp_filename)
            if len(reader.pages) > 0: texto_pdf = reader.pages[0].extract_text() or ""
        except: pass
        
        if ticker.upper() in texto_pdf.upper():
            # 🎯 INTELIGÊNCIA ARTIFICIAL (Camada 4)
            nome_ia = classificar_documento_com_ia(doc_db.tipo_documento, texto_pdf)
            nome_limpo = "".join([c for c in str(nome_ia).title() if c.isalnum() or c in (' ', '_', '-')]).strip()
            
            # 🔥 Correção do BUG do nome vazio:
            if len(nome_limpo) < 3: 
                nome_limpo = "Documento_FII"
                
            # UPLOAD
            partes_data = data_ref.split('-')
            mes_pasta = f"{partes_data[2]}-{partes_data[1]}" if len(partes_data) == 3 else datetime.now().strftime("%Y-%m")
            
            link_gerado = drive_manager.upload_pdf_organizado(
                caminho_arquivo=temp_filename,
                nome_arquivo=f"{nome_limpo}_{data_ref}_{id_doc}.pdf",
                ticker=ticker,
                mes_ref=mes_pasta 
            )
            
            if link_gerado:
                doc_db.url_pdf = link_gerado
                doc_db.tipo_documento = nome_limpo
                doc_db.status_processamento = "SALVO_DRIVE"
                print(f"✅ Sucesso: {ticker} -> {nome_limpo}")
            else:
                doc_db.status_processamento = "ERRO_DRIVE"
        else:
            doc_db.status_processamento = "REJEITADO_DUPLO_FATOR"
            print(f"❌ Rejeitado: {ticker} não encontrado no texto.")
            
        session.commit()
        if os.path.exists(temp_filename): os.remove(temp_filename)
        
        time.sleep(2) # Pausa pra IA respirar e não dar rate limit!

    session.close()

# ORQUESTRADOR PRINCIPAL
def rotina_de_atualizacao_em_massa():
    novos_encontrados = rotina_de_coleta_b3()
    rotina_processar_pendentes()
    return f"Varredura concluída. Novos encontrados: {novos_encontrados}"