import os
import json
import io
import datetime
import PyPDF2
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseUpload
from mercados.fundosnet import FundosNet

# Importamos o arquivo de configuração para pegar o ID da pasta
import config 

# Como o module_ia está na mesma pasta (modules/), importamos direto:
import modules.module_ia as module_ia

# O ID agora vem do seu arquivo de configuração central
DRIVE_FOLDER_ID = config.DRIVE_FOLDER_ID

# ==========================================
# MAPEAMENTO E INTELIGÊNCIA DE NOMES DA CVM
# ==========================================

# Mapeador: Traduz o Ticker (Símbolo da Bolsa) para o Nome Oficial (Linguagem CVM/FundosNet)
MAPA_CVM = {
    "HGLG11": "CGHG LOGISTICA",
    "MXRF11": "MAXI RENDA",
    "VISC11": "VINCI SHOPPINGS",
    "GARE11": "GUARDIAN LOGISTICA", # (Antigo GALG11, usar o nome atual registrado)
    "KNRI11": "KINEA RENDIMENTOS",
    "RZTR11": "RIZA TERRAX",
    "LVBI11": "VBI LOGISTICO",
    "PQDP11": "PARQUE DOM PEDRO",
    # Adicione as ações aqui também, se necessário:
    "PETR4": "PETROLEO BRASILEIRO",
    "VALE3": "VALE S.A."
}

def obter_palavra_chave_cvm(ticker):
    """
    Tenta achar o nome CVM pelo mapa. Se não achar, usa uma técnica de fallback 
    tentando extrair o nome via Yahoo Finance.
    """
    ticker_upper = ticker.upper()
    
    # 1. Tentativa pelo nosso dicionário blindado (O mais rápido e exato)
    if ticker_upper in MAPA_CVM:
        return MAPA_CVM[ticker_upper]
    
    # 2. Fallback: Se for um ativo novo que não está no mapa, tenta adivinhar pelo YFinance
    try:
        nome_longo = yf.Ticker(f"{ticker_upper}.SA").info.get('longName', '').upper()
        # Pega as duas primeiras palavras do nome corporativo (Ex: "ITAU UNIBANCO HOLDING S.A." -> "ITAU UNIBANCO")
        partes = nome_longo.split()
        return f"{partes[0]} {partes[1]}" if len(partes) > 1 else partes[0]
    except:
        return ticker_upper[:4] # Último recurso: usa as 4 letras iniciais

# --- BLOCO 1: INTEGRAÇÃO COM GOOGLE DRIVE E IA ---

def autenticar_drive():
    google_creds = os.environ.get('GOOGLE_CREDS')
    if google_creds:
        creds_dict = json.loads(google_creds)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=['https://www.googleapis.com/auth/drive.file']
        )
        return build('drive', 'v3', credentials=creds)
    return None

def salvar_pdf_no_drive(nome_arquivo, pdf_bytes):
    """Salva um arquivo PDF diretamente na pasta do Google Drive especificada."""
    try:
        drive_service = autenticar_drive()
        if not drive_service:
            return None, "Erro de autenticação com o Google Drive (Credenciais não encontradas)."

        file_metadata = {
            'name': nome_arquivo,
            'parents': [DRIVE_FOLDER_ID]
        }
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf', resumable=True)
        arquivo = drive_service.files().create(
            body=file_metadata, media_body=media, fields='id, webViewLink'
        ).execute()

        return arquivo.get('webViewLink'), None
    except Exception as e:
        return None, str(e)

def extrair_texto_pdf(pdf_bytes):
    try:
        leitor = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        texto_estrategico = ""

        # O Radar do Robô: Termos que indicam páginas cruciais (Visão de Raio-X)
        palavras_chave = [
            "dre", "demonstração do resultado", "alavancagem", "endividamento", 
            "composição", "portfólio", "vacância", "inadimplência", "inadiplência",
            "cronograma de obras", "dividend yield", "balanço patrimonial"
        ]

        for i, pagina in enumerate(leitor.pages):
            texto_pagina = pagina.extract_text()
            if not texto_pagina: 
                continue

            texto_lower = texto_pagina.lower()

            # REGRA DE OURO:
            # 1. Sempre lê as 3 primeiras páginas (Mensagem do Gestor / Resumo)
            # 2. Sempre lê as 2 últimas (Avisos Legais / Conclusão)
            # 3. Lê qualquer página no meio que contenha os termos do radar
            if i < 3 or i >= len(leitor.pages) - 2 or any(termo in texto_lower for termo in palavras_chave):
                texto_estrategico += f"\n\n--- [PÁGINA {i+1}] ---\n{texto_pagina}"

        # Limite de segurança: se o texto ficar gigantesco, corta para caber no limite da IA (aprox. 100 mil caracteres)
        return texto_estrategico[:100000]
    except Exception as e:
        return f"Erro ao extrair texto inteligente: {str(e)}"

def extrair_resumo_ia(ticker, tipo_documento, texto_bruto, link_drive=None):
    """Gera um resumo do documento usando a IA configurada."""
    prompt = f"""
    Você é um analista financeiro sênior e atua em um fundo de investimentos institucional. O utilizador pediu uma análise sobre o documento '{tipo_documento}' do ativo {ticker}.
    
    Abaixo estão os dados extraídos do servidor oficial:
    {texto_bruto[:10000]}
    
    Forneça de forma clara, direta e objetiva:
    1. 📝 Principais destaques e acontecimentos. O que aconteceu?
    2. 💰 Impacto Financeiro (DRE, Caixa, Pagamentos de Dividendos).
    3. 🎯 Veredito final do Especialista: Este evento gera uma Janela de Oportunidade ou um Sinal Vermelho (Risco)? Justifique o impacto positivo, negativo ou neutro na saúde do ativo em 2 linhas.
    """
    resumo = module_ia.analisar_fatos_com_ia(ticker + f" - {tipo_documento}\n\n" + prompt)

    if link_drive:
        resumo += f"\n\n📂 **Documento salvo no seu Google Drive:** [Acessar Documento]({link_drive})"

    return resumo

# --- BLOCO 2: FERRAMENTAS DE BUSCA E FILTRAGEM ---

def buscar_fatos_relevantes(ticker, is_fii=False):
    """Busca fatos relevantes. Tenta acessar a página fr.php do Fundamentus como fallback."""
    try:
        # 1. Tentativa via site Fundamentus (Ideia FR.php)
        url_fr = f"https://www.fundamentus.com.br/fr.php?papel={ticker}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url_fr, headers=headers, timeout=10)
        
        contexto = ""
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            tabela = soup.find('table')
            if tabela:
                linhas = tabela.find_all('tr')[1:4] # Pega as 3 notícias mais recentes
                if linhas:
                    contexto = f"Últimos Fatos Relevantes de {ticker} (Fonte: Fundamentus):\n"
                    for linha in linhas:
                        colunas = linha.find_all('td')
                        if len(colunas) >= 2:
                            data = colunas[0].text.strip()
                            assunto = colunas[1].text.strip()
                            contexto += f"- {data}: {assunto}\n"
        
        # 2. Fallback para FundosNet (se a tabela estiver vazia ou for FII)
        if not contexto and is_fii:
             hoje = datetime.date.today()
             inicio_ano = datetime.date(hoje.year, 1, 1)
             fnet = FundosNet()
             
             nome_cvm = obter_palavra_chave_cvm(ticker)
             docs_gerais = list(fnet.busca(categoria="Fato Relevante", inicio=inicio_ano, fim=hoje))
             docs_fundo = [d for d in docs_gerais if nome_cvm in str(getattr(d, 'nome_fundo', '')).upper() or ticker in str(getattr(d, 'nome_fundo', '')).upper()]
             
             if docs_fundo:
                 contexto = f"Fatos Relevantes Oficiais de {ticker} (Fonte: CVM):\n"
                 for d in docs_fundo[:2]:
                     data_str = getattr(d, 'datahora_entrega', None)
                     data_formatada = data_str.strftime('%d/%m/%Y') if hasattr(data_str, 'strftime') else str(data_str)
                     contexto += f"- Data: {data_formatada} | Assunto: {getattr(d, 'assunto', getattr(d, 'tipo', 'N/D'))}\n  Link: {getattr(d, 'url', 'Link indisponível')}\n"
        
        # 3. Fallback para Ações via YFinance
        if not contexto and not is_fii:
             asset = yf.Ticker(f"{ticker}.SA")
             news = asset.news
             if news:
                 contexto = f"Eventos Corporativos Oficiais de {ticker} (Fonte: Yahoo Finance):\n"
                 for n in news[:2]:
                     if 'providerPublishTime' in n:
                         data_pub = datetime.datetime.fromtimestamp(n['providerPublishTime']).strftime('%d/%m/%Y')
                     else:
                         data_pub = "Recente"
                     contexto += f"- Data: {data_pub} | Título: {n.get('title', '')}\n  Link: {n.get('link', 'Link indisponível')}\n"
        
        if not contexto:
            return f"Nenhum Fato Relevante ou notícia recente encontrada para {ticker}."
            
        return extrair_resumo_ia(ticker, "Fatos Relevantes", contexto)
        
    except Exception as e:
        return f"❌ Erro na extração de Fatos Relevantes: {e}"

def buscar_relatorios_gerenciais(ticker):
    """Busca relatórios gerenciais recentes de FIIs via FundosNet, usando a técnica do MAPA_CVM."""
    try:
        nome_cvm = obter_palavra_chave_cvm(ticker)
        print(f"Buscando relatórios para: {nome_cvm} (Ticker: {ticker})")

        fnet = FundosNet()
        hoje = datetime.date.today()
        tres_meses_atras = hoje - relativedelta(months=3)
        
        docs_gerais = list(fnet.busca(categoria="Relatórios", inicio=tres_meses_atras, fim=hoje))

        # Filtra os documentos buscando pelo nome da CVM que descobrimos
        docs_fundo = [d for d in docs_gerais if nome_cvm in str(getattr(d, 'nome_fundo', '')).upper() or ticker in str(getattr(d, 'nome_fundo', '')).upper()]

        if not docs_fundo: 
            return f"Nenhum Relatório de {ticker} publicado nos últimos 3 meses (Buscando por: {nome_cvm})."

        contexto = f"Relatórios Recentes de {ticker}:\n"
        for d in docs_fundo[:2]:
            data_str = getattr(d, 'datahora_entrega', None)
            data_formatada = data_str.strftime('%d/%m/%Y') if hasattr(data_str, 'strftime') else str(data_str)
            contexto += f"- Data: {data_formatada} | Tipo: {getattr(d, 'tipo', 'N/D')}\n"
            contexto += f"  Link: {getattr(d, 'url', 'Indisponível')}\n"

        return extrair_resumo_ia(ticker, "Relatório Gerencial", contexto)
    except Exception as e:
        return f"❌ Erro ao extrair relatórios via FundosNet: {e}"

def buscar_resultados_trimestrais(ticker):
    """Busca resultados trimestrais (ITR/DFP) de ações via Yahoo Finance."""
    try:
        asset = yf.Ticker(f"{ticker}.SA")
        dre = asset.quarterly_income_stmt
        if dre.empty: return "Demonstrativos trimestrais indisponíveis no Yahoo Finance."

        dre_recente = dre.iloc[:, :2]
        contexto = f"DRE Trimestral Resumida (Fonte dos dados: Yahoo Finance) de {ticker}:\n{dre_recente.to_string()}"
        return extrair_resumo_ia(ticker, "Resultados Trimestrais (ITR/DFP)", contexto)
    except Exception as e:
        return f"❌ Erro ao extrair balanço financeiro trimestral: {e}"

def buscar_noticias_macro():
    """Gera um resumo macroeconômico utilizando a IA configurada."""
    return module_ia.analisar_fatos_com_ia("Resuma as 3 notícias macroeconômicas mais importantes do Brasil e Mundo hoje, indicando o impacto direto na Bolsa de Valores e na curva de juros.")
