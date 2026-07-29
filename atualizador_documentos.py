import os
import time
import json
import re
import requests
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
from config import DATABASE_URL, MAPA_ISCAS_MASTER, TIPOS_DOC_FII

client = Groq(api_key=config.GROQ_API_KEY)

# Pega o banco das variáveis do sistema 
url_banco = os.environ.get('DATABASE_URL', 'sqlite:///pipeline_dados/banco_institucional.db')

# Corrige o prefixo caso o Render mande postgres:// em vez de postgresql://
if url_banco.startswith("postgres://"):
    url_banco = url_banco.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,            # Se no seu código estiver config.DATABASE_URL, mantenha config.DATABASE_URL
    pool_pre_ping=True,      # Testa se a conexão com o Neon caiu antes de fazer a query
    pool_recycle=1800,       # Renova a conexão a cada 30 minutos (evita o fechamento forçado)
    pool_size=5,             # Mantém um limite seguro de conexões para não estourar a memória
    max_overflow=10
)
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

# ==========================================
# 🚨 TRAVA 1: CLASSIFICAÇÃO HÍBRIDA COM IA (AUTO-SAVE)
# ==========================================
def classificar_documento_com_ia(nome_original, texto_extraido):
    if not texto_extraido: 
        return nome_original, 0 

    # 🛡️ HIGIENIZADOR: Remove caracteres invisíveis que dão Erro 400
    texto_limpo = re.sub(r'[^\x20-\x7E\u00A0-\u00FF]', ' ', str(texto_extraido)).strip()
    texto_limpo = texto_limpo[:1500] # Aumentei um pouco para a IA ter mais contexto

    if not texto_limpo: 
        return nome_original, 0

    lista_opcoes = ", ".join(TIPOS_DOC_FII.values())
    
    # Prompt de engenharia reversa exigindo JSON
    prompt = (
        f"Você é um analista financeiro sênior avaliando um PDF de Fundo Imobiliário. "
        f"O documento começa assim: '{texto_limpo}'\n\n"
        f"Classifique o documento escolhendo ESTRITAMENTE UMA destas opções: {lista_opcoes}.\n"
        f"Responda EXATAMENTE E APENAS com um objeto JSON válido, contendo as chaves 'tipo' e 'confianca'. "
        f"A chave 'confianca' deve ser um número inteiro de 0 a 100 representando sua certeza."
    )

    try:
        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"} # 🚀 Força a Groq a cuspir JSON puro
        )
        resposta_str = chat.choices[0].message.content
        
        # Transforma a resposta da IA em um dicionário Python
        dados_ia = json.loads(resposta_str)
        tipo_ia = dados_ia.get("tipo", nome_original)
        confianca_ia = int(dados_ia.get("confianca", 0))

        # Validação: se a IA inventar uma palavra que não está na lista, zera a confiança
        if tipo_ia not in TIPOS_DOC_FII.values():
            return nome_original, 0

        return tipo_ia, confianca_ia

    except Exception as e:
        print(f"⚠️ Erro ao consultar IA para classificação híbrida: {e}")
        return nome_original, 0

def enviar_alerta_revisao_telegram(ticker, nome_doc, link_pdf, file_id, db_id):
    """Envia a mensagem interativa com botões para o seu Telegram"""
    chat_id = os.environ.get('TELEGRAM_CHAT_ID') 
    if not chat_id:
        print("⚠️ TELEGRAM_CHAT_ID não configurado. Alerta não enviado.")
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"

    teclado = {
        "inline_keyboard": [
            [{"text": f"✅ Confirmar como {ticker}", "callback_data": f"rev_C_{db_id}_{file_id}"}],
            [{"text": "🗑️ Apagar / Lixo", "callback_data": f"rev_A_{db_id}_{file_id}"}]
        ]
    }

    mensagem = (
        f"🚨 **Novo documento suspeito!**\n\n"
        f"A B3 diz que é do **{ticker}**, mas o robô não conseguiu confirmar no texto (pode ser imagem/scan).\n"
        f"📄 **Tipo:** {nome_doc}\n\n"
        f"🔗 [Clique aqui para abrir o PDF]({link_pdf})\n\n"
        f"O que eu faço?"
    )

    payload = {
        "chat_id": chat_id,
        "text": mensagem,
        "parse_mode": "Markdown",
        "reply_markup": json.dumps(teclado)
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"⚠️ Erro ao enviar alerta Telegram: {e}")

# ==========================================
# CAMADA 1: COLETA
# ==========================================
def rotina_de_coleta_b3():
    b3 = FnetDownloader()
    lista_de_fiis = obter_tickers_da_planilha()
    session = SessionDB()

    data_busca = (datetime.now() - timedelta(days=40)).strftime("%d/%m/%Y")
    todos_documentos = b3.capturar_tudo(data_busca)

    novos = 0
    for doc in todos_documentos:
        nome_fundo_b3 = normalizar_texto(doc['nome_fundo'])
        id_doc = str(doc['id'])

        for ticker in lista_de_fiis:
            isca = normalizar_texto(MAPA_ISCAS_MASTER.get(ticker, ticker))
            if isca in nome_fundo_b3:
                existe = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.id_b3 == id_doc).first()
                if not existe:
                    ativo_db = session.query(Ativo).filter(Ativo.ticker == ticker).first()
                    if not ativo_db:
                        ativo_db = Ativo(ticker=ticker, cnpj=f"PENDENTE-{ticker}", tipo="FII") 
                        session.add(ativo_db)
                        session.commit()

                    novo_doc = DocumentosQualitativos(
                        ativo_id=ativo_db.id,
                        id_b3=id_doc,
                        data_publicacao=datetime.now(),
                        tipo_documento=doc['tipo_doc'], 
                        assunto=doc['data_ref'], 
                        status_processamento="PENDENTE"
                    )
                    session.add(novo_doc)
                    session.commit()
                    novos += 1
                break
    session.close()
    return novos

# ==========================================
# CAMADA 2 E 3: PROCESSAMENTO E REVISÃO
# ==========================================
def rotina_processar_pendentes():
    b3 = FnetDownloader()
    drive_manager = GoogleDriveManager()
    session = SessionDB()

    pendentes = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.status_processamento == "PENDENTE").all()
    print(f"⚙️ Processando {len(pendentes)} documentos na fila...")

    for doc_db in pendentes:
        ticker = doc_db.ativo.ticker
        id_doc = doc_db.id_b3
        data_ref = doc_db.assunto 

        print(f"🔄 Processando fila: {ticker} (ID {id_doc})...")

        pdf_bytes = b3.baixar_pdf(id_doc)
        if not pdf_bytes:
            doc_db.status_processamento = "ERRO_DOWNLOAD"
            session.commit()
            continue

        temp_filename = f"/tmp/{ticker}_{id_doc}.pdf"
        with open(temp_filename, "wb") as f: f.write(pdf_bytes)

        texto_pdf = ""
        try:
            reader = PyPDF2.PdfReader(temp_filename)
            if len(reader.pages) > 0: 
                texto_pdf = reader.pages[0].extract_text() or ""
        except: pass

        # ==========================================
        # 🤖 CAMADA HÍBRIDA DE IA E AUTO-SAVE (>= 80%)
        # ==========================================
        texto_pdf = texto_pdf.strip()

        # 1. Pede à IA o tipo e a nota de confiança (retorna duas variáveis agora)
        nome_ia, confianca = classificar_documento_com_ia(doc_db.tipo_documento, texto_pdf)

        # Higieniza o nome retornado pela IA para virar uma string limpa de arquivo
        nome_limpo = "".join([c for c in str(nome_ia).title() if c.isalnum() or c in (' ', '_', '-')]).strip()
        if len(nome_limpo) < 3:
            nome_limpo = "Documento_FII"

        partes_data = data_ref.split('-')
        mes_pasta = f"{partes_data[2]}-{partes_data[1]}" if len(partes_data) == 3 else datetime.now().strftime("%Y-%m")

        # 2. ENCRUZILHADA DO AUTO-SAVE (Threshold de Confiança >= 80%)
        if confianca >= 80 and texto_pdf:
            print(f"🤖 IA tem {confianca}% de certeza. Auto-salvando '{nome_limpo}' para {ticker}...")
            
            # Salva direto na pasta oficial do Google Drive
            link_gerado = drive_manager.upload_pdf_organizado(
                caminho_arquivo=temp_filename,
                nome_arquivo=f"{nome_limpo}_{data_ref}_{id_doc}.pdf",
                ticker=ticker,
                mes_ref=mes_pasta,
                tipo_ativo=doc_db.ativo.tipo 
            )
            
            if link_gerado:
                doc_db.url_pdf = link_gerado
                doc_db.tipo_documento = nome_limpo
                doc_db.status_processamento = "SALVO_DRIVE"
                print(f"✅ Sucesso (Auto-save): {ticker} -> {nome_limpo}")
            else:
                doc_db.status_processamento = "ERRO_DRIVE"

        else:
            # 3. CONFIANÇA BAIXA OU PDF ESCaneado: Manda para a Pasta de Revisão + Alerta Telegram
            print(f"⚠️ IA incerta ({confianca}%). Enviando para revisão manual e alerta Telegram...")
            
            file_id, link_gerado = drive_manager.upload_pdf_revisao(
                caminho_arquivo=temp_filename,
                nome_arquivo=f"REVISAR_{ticker}_{nome_limpo}_{data_ref}.pdf"
            )
            
            if file_id:
                doc_db.status_processamento = "AGUARDANDO_REVISAO"
                doc_db.url_pdf = link_gerado
                session.commit()
                
                # 📲 Dispara o alerta interativo no seu Telegram com os botões
                enviar_alerta_revisao_telegram(
                    ticker=ticker,
                    nome_doc=nome_limpo,
                    link_pdf=link_gerado,
                    file_id=file_id,
                    db_id=doc_db.id
                )
            else:
                doc_db.status_processamento = "ERRO_DRIVE"

        session.commit()
        if os.path.exists(temp_filename): os.remove(temp_filename)

        time.sleep(6) 

    session.close()

def rotina_de_atualizacao_em_massa():
    novos_encontrados = rotina_de_coleta_b3()
    rotina_processar_pendentes()
    return f"Varredura concluída. Novos encontrados: {novos_encontrados}"

def rotina_processar_acoes():
    """Esteira exclusiva da Inteligência Artificial para documentos da CVM"""
    drive_manager = GoogleDriveManager()
    session = SessionDB()

    # Puxa apenas a fila de empresas
    pendentes = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.status_processamento == "PENDENTE_ACAO").all()
    print(f"⚙️ Processando {len(pendentes)} documentos de AÇÕES na fila...")

    for doc_db in pendentes:
        ticker = doc_db.ativo.ticker
        url_pdf = doc_db.url_pdf
        
        # Garante o formato da pasta: Ex: 2026-07
        mes_pasta = doc_db.data_publicacao.strftime("%Y-%m") if doc_db.data_publicacao else datetime.now().strftime("%Y-%m")
        data_str = doc_db.data_publicacao.strftime("%Y-%m-%d") if doc_db.data_publicacao else "SEM_DATA"

        print(f"🔄 IA Lendo: {ticker} (Data: {data_str})...")

        # 1. Download direto do link da CVM
        try:
            # Baixa o arquivo direto do link da B3/CVM salvo no banco
            resposta = requests.get(url_pdf, timeout=15)
            if resposta.status_code != 200:
                doc_db.status_processamento = "ERRO_DOWNLOAD"
                session.commit()
                continue
            pdf_bytes = resposta.content
        except Exception as e:
            print(f"⚠️ Erro ao baixar PDF CVM: {e}")
            doc_db.status_processamento = "ERRO_DOWNLOAD"
            session.commit()
            continue

        temp_filename = f"/tmp/{ticker}_cvm_temp.pdf"
        with open(temp_filename, "wb") as f: f.write(pdf_bytes)

        # 2. Extração de Texto para a IA
        texto_pdf = ""
        try:
            reader = PyPDF2.PdfReader(temp_filename)
            if len(reader.pages) > 0: 
                texto_pdf = reader.pages[0].extract_text() or ""
        except: pass

        texto_pdf = texto_pdf.strip()
        
        # Chama o mesmo cérebro Groq que você já usa nos FIIs!
        nome_ia = classificar_documento_com_ia(doc_db.tipo_documento, texto_pdf)
        nome_limpo = "".join([c for c in str(nome_ia).title() if c.isalnum() or c in (' ', '_', '-')]).strip()

        if len(nome_limpo) < 3: 
            nome_limpo = "".join([c for c in str(doc_db.tipo_documento).title() if c.isalnum() or c in (' ', '_', '-')]).strip()
            if len(nome_limpo) < 3: nome_limpo = "Documento_Acao"

        # 3. Decisão de Roteamento
        # Ao contrário dos FIIs, a CVM nem sempre coloca o Ticker no texto do PDF, então tiramos essa trava, 
        # mas mantemos a trava de "PDF em branco/Imagem" para mandar pra revisão.
        if not texto_pdf:
            # 🚧 Suspeito/Scan: Manda pra pasta REVISÃO
            file_id, link_gerado = drive_manager.upload_pdf_revisao(
                caminho_arquivo=temp_filename,
                nome_arquivo=f"REVISAR_{ticker}_{nome_limpo}_{data_str}.pdf"
            )
            if file_id:
                doc_db.status_processamento = "AGUARDANDO_REVISAO"
                doc_db.url_pdf = link_gerado
                session.commit()
                print(f"🚧 {ticker} enviado para revisão manual.")
        else:
            # ✅ Seguro: O Roteador Dinâmico envia para a pasta 'Ações'
            link_gerado = drive_manager.upload_pdf_organizado(
                caminho_arquivo=temp_filename,
                nome_arquivo=f"{nome_limpo}_{data_str}.pdf",
                ticker=ticker,
                mes_ref=mes_pasta,
                tipo_ativo="ACAO" # 🔴 AVISANDO O CARTEIRO!
            )
            if link_gerado:
                doc_db.url_pdf = link_gerado
                doc_db.tipo_documento = nome_limpo
                doc_db.status_processamento = "SALVO_DRIVE" # 🟢 Libera o botão no Telegram!
                print(f"✅ Sucesso: Drive Atualizado -> {nome_limpo}")
            else:
                doc_db.status_processamento = "ERRO_DRIVE"

        session.commit()
        if os.path.exists(temp_filename): os.remove(temp_filename)
        
        time.sleep(3) # Respiro para não tomar bloqueio da API do Google

    session.close()
