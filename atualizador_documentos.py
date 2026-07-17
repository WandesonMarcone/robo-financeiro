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

# 🎯 IMPORTANDO O MAPA MASTER EXTERNO
from mapa_fiis import MAPA_ISCAS_MASTER

# Importações para a IA e Leitura de PDF
import PyPDF2
from groq import Groq

# Configuração do Groq
client = Groq(api_key=config.GROQ_API_KEY)

engine = create_engine("sqlite:///pipeline_dados/banco_institucional.db")
SessionDB = sessionmaker(bind=engine)

def classificar_documento_com_ia(nome_original, texto_extraido):
    """Pergunta ao Groq qual o tipo real do documento baseado no conteúdo"""
    if not texto_extraido: 
        return nome_original
    
    prompt = f"O arquivo se chama '{nome_original}'. O texto inicial é: {texto_extraido[:800]}. " \
             "Classifique estritamente como: 'Relatorio Gerencial', 'Fato Relevante', 'Informe Mensal', 'Demonstracoes Financeiras', 'Aviso aos Cotistas', 'Rendimentos e Amortizacoes', 'Outros'. " \
             "Responda APENAS com o nome da categoria."

    try:
        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama3-8b-8192"
        )
        return chat.choices[0].message.content.strip()
    except:
        return nome_original

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

    print(f"🚀 Iniciando OPERAÇÃO DE ALTA PRECISÃO para {len(lista_de_fiis)} FIIs...")
    session = SessionDB()

    # Janela de 100 dias
    data_busca = (datetime.now() - timedelta(days=100)).strftime("%d/%m/%Y")

    # Puxa tudo de uma vez (o que o seu FnetDownloader faz bem)
    todos_documentos = b3.capturar_tudo(data_busca)
    print(f"📦 B3 entregou {len(todos_documentos)} documentos. Iniciando Validação de Duplo Fator...")

    for doc in todos_documentos:
        try: # 🛡️ Try/Except para o robô não morrer se um PDF der erro
            nome_fundo_b3 = normalizar_texto(doc['nome_fundo'])
            id_doc = doc['id']
            data_ref = doc['data_ref']
            tipo_original = doc['tipo_doc'] 

            for ticker in lista_de_fiis:
                isca = normalizar_texto(MAPA_ISCAS_MASTER.get(ticker, ticker))

                # PASSO 1: A PENEIRA (Match inicial pelo Mapa)
                if isca in nome_fundo_b3:
                    
                    # Trava Anti-Duplicata
                    if session.query(DocumentosQualitativos).filter(DocumentosQualitativos.assunto.contains(id_doc)).first():
                        break # Já temos, pula para o próximo doc da B3

                    print(f"🔄 Analisando ID {id_doc} para {ticker}...")
                    
                    # PASSO 2: DOWNLOAD TEMPORÁRIO DE AUDITORIA
                    pdf_bytes = b3.baixar_pdf(id_doc)
                    if pdf_bytes:
                        temp_filename = f"/tmp/{ticker}_{id_doc}.pdf"
                        with open(temp_filename, "wb") as f:
                            f.write(pdf_bytes)

                        # PASSO 3: A ASSINATURA (Extração de texto para IA e Validação)
                        texto_pdf = ""
                        try:
                            reader = PyPDF2.PdfReader(temp_filename)
                            if len(reader.pages) > 0:
                                # Lemos as duas primeiras páginas para garantir cobertura
                                texto_pdf = reader.pages[0].extract_text() or ""
                                if len(reader.pages) > 1:
                                    texto_pdf += " " + (reader.pages[1].extract_text() or "")
                        except Exception as e:
                            print(f"⚠️ Não foi possível ler o PDF do ID {id_doc}: {e}")

                        # PASSO 4: VALIDAÇÃO DETERMINÍSTICA (Duplo Fator)
                        if ticker.upper() in texto_pdf.upper():
                            print(f"✅ Duplo Fator aprovado! O ticker {ticker} foi encontrado no PDF.")

                            # 🎯 A CHAMADA CORRETA DA IA
                            classificacao = classificar_documento_com_ia(tipo_original, texto_pdf)
                            nome_limpo = str(classificacao).strip().title() 
                            # Remove caracteres que não podem ir em nomes de arquivos
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
                                # Garantimos que o FII existe no banco antes de salvar o documento
                                ativo_db = session.query(Ativo).filter(Ativo.ticker == ticker).first()
                                if not ativo_db:
                                    ativo_db = Ativo(ticker=ticker, cnpj=f"PENDENTE-{ticker}", tipo="FII") 
                                    session.add(ativo_db)
                                    session.commit()

                                novo_doc = DocumentosQualitativos(
                                    ativo_id=ativo_db.id,
                                    tipo_documento=nome_inteligente, 
                                    data_publicacao=datetime.now(),
                                    assunto=f"{nome_inteligente} ref. {data_ref} (ID B3: {id_doc})",
                                    url_pdf=link_gerado
                                )
                                session.add(novo_doc)
                                session.commit()
                                print(f"☁️ ✅ Salvo no Drive e Banco: {ticker} -> {nome_inteligente}")
                        
                        else:
                            # Se a peneira (Mapa) achou, mas o documento não tem o Ticker: Rejeita!
                            print(f"❌ Rejeitado: O Ticker {ticker} não consta no texto do PDF (ID {id_doc}).")
                            if os.path.exists(temp_filename):
                                os.remove(temp_filename)

                    break # O doc já encontrou seu dono na peneira, segue pro próximo da B3

        except Exception as e:
            print(f"❌ Erro crítico ao processar ID {doc.get('id', 'Desconhecido')}: {e}")
            continue # O loop continua firme e forte

    session.close()
    return "Varredura concluída com sucesso."