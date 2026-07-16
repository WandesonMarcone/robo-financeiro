import os
import time
from datetime import datetime
import config
from fnet_scraper import FnetDownloader
from modules.GoogleDriveManager import GoogleDriveManager
from modules.utils import conectar_gspread
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import re

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

def descobrir_nome_oficial_b3(ticker):
    """
    Acessa o StatusInvest, pega a Razão Social do FII e limpa o texto
    para descobrir a palavra-chave exata que a B3 exige, de forma 100% automática.
    """
    try:
        url = f"https://statusinvest.com.br/fundos-imobiliarios/{ticker.lower()}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/115.0.0.0 Safari/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code != 200:
            return ticker # Se o site falhar, devolve o ticker como plano B
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        razao_social = ""
        
        # 1. Procura o campo exato de Razão Social no site
        h3_razao = soup.find('h3', string=re.compile(r'Razão Social', re.IGNORECASE))
        if h3_razao:
            valor_tag = h3_razao.find_next('strong', class_='value')
            if valor_tag:
                razao_social = valor_tag.text.strip().upper()
        
        # 2. Fallback: Se não achar, pega o subtítulo do cabeçalho
        if not razao_social:
            h1_tag = soup.find('h1')
            if h1_tag and h1_tag.find('small'):
                razao_social = h1_tag.find('small').text.strip().upper()

        if not razao_social:
            return ticker 

        # ==============================================================
        # 🧹 O FILTRO MÁGICO DE LIMPEZA DE DADOS
        # ==============================================================
        # Tiramos todas as palavras genéricas institucionais
        palavras_inuteis = [
            "FUNDO", "DE", "INVESTIMENTO", "IMOBILIÁRIO", "IMOBILIARIO", 
            "FII", "FDO", "INV", "IMOB", "RESPONSABILIDADE", "LIMITADA", 
            "S.A.", "S/A", "-", "MULTIESTRATÉGIA", "LOGÍSTICA", "SHOPPING"
        ]
        
        # Quebra a frase em palavras soltas
        palavras_soltas = razao_social.replace('-', ' ').split()
        
        # Guarda só as palavras importantes (Ex: Sobra "XP" e "MALLS")
        palavras_uteis = [p for p in palavras_soltas if p not in palavras_inuteis]
        
        # Junta as 2 primeiras palavras úteis. É o suficiente para a B3 achar.
        nome_limpo = " ".join(palavras_uteis[:2])
        
        return nome_limpo

    except Exception as e:
        print(f"⚠️ Erro ao descobrir nome do {ticker}: {e}")
        return ticker

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

import os
import time # Adicionado para dar uma pausa e a B3 não nos bloquear

def rotina_de_atualizacao_em_massa():
    # A NOSSA PRANCHETA: A lista de tudo que queremos buscar
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
    print(f"🚀 Iniciando varredura BLINDADA para {len(lista_de_fiis)} FIIs...")

    relatorios_salvos = 0
    session = SessionDB()
    
    # ⏪ TESTE DE FOGO: Busca tudo dos últimos 15 dias para popular o Drive
    data_busca = (datetime.now() - timedelta(days=40)).strftime("%d/%m/%Y")

    # 1º LOOP: Passa FII por FII (ex: XPML11, HGLG11...)
    for ticker in lista_de_fiis:
        
        # 🧠 A MÁGICA ACONTECE AQUI: O robô descobre sozinho o nome de busca
        nome_pesquisa = descobrir_nome_oficial_b3(ticker)
        print(f"\n🏢 Analisando: {ticker} (Nome na B3: {nome_pesquisa})")

        ativo_db = session.query(Ativo).filter(Ativo.ticker == ticker).first()
        if not ativo_db:
            ativo_db = Ativo(ticker=ticker, cnpj=f"PENDENTE-{ticker}", tipo="FII") 
            session.add(ativo_db)
            session.commit()

        # 2º LOOP (A TRAVA DE SEGURANÇA): Pergunta à B3 categoria por categoria
        for id_categoria, nome_categoria in MAPA_TIPOS.items():

            # ⚠️ Troque data_inicio=data_hoje por data_inicio=data_busca
            documentos = b3.pesquisar_documentos(nome_pesquisa, data_inicio=data_busca, id_categoria=id_categoria)

            # Dá uma pausa de 1 segundo para a B3 não achar que somos um ataque hacker e bloquear nosso IP
            time.sleep(1)

            for id_doc, data_ref, tipo_doc_id in documentos: 

                # Trava Anti-Duplicata
                doc_existente = session.query(DocumentosQualitativos).filter(
                    DocumentosQualitativos.ativo_id == ativo_db.id,
                    DocumentosQualitativos.assunto.contains(id_doc) 
                ).first()

                if doc_existente:
                    continue

                print(f"⬇️ Encontrado: {nome_categoria} (ID B3: {id_doc})")
                pdf_bytes = b3.baixar_pdf(id_doc)

                if pdf_bytes:
                    temp_filename = f"/tmp/{ticker}_{id_doc}.pdf"
                    with open(temp_filename, "wb") as f:
                        f.write(pdf_bytes)

                    # Cria a variável com o Mês atual (ex: 2026-07)
                    mes_atual = datetime.now().strftime("%Y-%m")

                    # UPLOAD: Cria a arquitetura DadosFinanceiros -> Fundos Imobiliários -> Ticker -> Mês
                    link_gerado = drive_manager.upload_pdf_organizado(
                        caminho_arquivo=temp_filename,
                        nome_arquivo=f"{nome_categoria}_{data_ref}_{id_doc}.pdf",
                        ticker=ticker,
                        mes_ref=mes_atual # <--- Aqui nós mandamos o Mês em vez da Categoria!
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
                        print(f"✅ Salvo no Drive: {ticker} -> {nome_categoria}")

    session.close()
    return relatorios_salvos