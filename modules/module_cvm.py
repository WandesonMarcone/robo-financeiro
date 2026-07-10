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

# Import para o teste hardcore anti-bloqueio (Requer playwright no requirements.txt)
from playwright.sync_api import sync_playwright

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
    INVESTIGADOR DE IDENTIDADE:
    1. Tenta pelo mapa fixo (Rápido).
    2. Se não achar, busca o nome real no Yahoo Finance e extrai a identidade CVM (Inteligente).
    """
    ticker_upper = ticker.upper()

    # 1. Tenta pelo mapa fixo
    if ticker_upper in MAPA_CVM:
        return MAPA_CVM[ticker_upper]

    # 2. Investigação Automática (Se não estiver no mapa)
    try:
        print(f"🔍 Investigando identidade do ativo {ticker_upper}...")
        yf_ticker = yf.Ticker(f"{ticker_upper}.SA")
        # O 'longName' costuma trazer o nome legal (ex: 'CSHG RENDA URBANA FUNDO DE INVESTIMENTO IMOBILIARIO')
        nome_completo = yf_ticker.info.get('longName', '').upper()

        # Limpeza para pegar a essência do nome (Removemos sufixos comuns de busca)
        nome_limpo = nome_completo.replace("FUNDO DE INVESTIMENTO IMOBILIARIO", "") \
                                 .replace("FUNDO DE INVESTIMENTO", "") \
                                 .replace("S.A.", "").replace("SA", "").strip()

        # Pegamos as duas primeiras palavras importantes que restaram
        partes = nome_limpo.split()
        nome_cvm = f"{partes[0]} {partes[1]}" if len(partes) > 1 else partes[0]

        print(f"✅ Identidade descoberta: {nome_cvm}")
        return nome_cvm
    except Exception as e:
        print(f"⚠️ Não foi possível investigar. Usando fallback simples: {e}")
        return ticker_upper[:4]

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
    """Busca relatórios gerenciais recentes contornando a B3 (Via Fundamentus)."""
    try:
        url_fr = f"https://www.fundamentus.com.br/fr.php?papel={ticker}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url_fr, headers=headers, timeout=10)

        contexto = ""
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            tabela = soup.find('table')

            if tabela:
                # Pula o cabeçalho e pega as linhas
                linhas = tabela.find_all('tr')[1:] 
                relatorios = []

                for linha in linhas:
                    colunas = linha.find_all('td')
                    if len(colunas) >= 2:
                        data = colunas[0].text.strip()
                        assunto = colunas[1].text.strip()

                        # Filtra apenas os relatórios gerenciais
                        if "Gerencial" in assunto or "Relatório" in assunto:
                            relatorios.append(f"- {data}: {assunto}")
                            if len(relatorios) >= 3: # Pega apenas os 3 mais recentes
                                break

                if relatorios:
                    contexto = f"Relatórios Gerenciais Recentes de {ticker} (Fonte: Fundamentus):\n" + "\n".join(relatorios)

        if not contexto:
            return f"Nenhum Relatório Gerencial recente encontrado para {ticker} no radar."

        return extrair_resumo_ia(ticker, "Relatório Gerencial", contexto)

    except Exception as e:
        return f"❌ Erro na extração de Relatórios: {e}"

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

# ==========================================
# BLOCO DE TESTE: PLAYWRIGHT (A Invasão)
# ==========================================

def testar_playwright_statusinvest(ticker):
    """
    Simula um humano acessando o StatusInvest para burlar o Cloudflare/JS.
    """
    try:
        print(f"🚀 Iniciando motor Playwright para {ticker}...")
        
        with sync_playwright() as p:
            # Lança o navegador Chromium no modo invisível (headless)
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Finge ser um utilizador comum (User-Agent)
            page.set_extra_http_headers({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            
            url = f"https://statusinvest.com.br/fundos-imobiliarios/{ticker.lower()}"
            print(f"🌐 Acessando: {url}")
            
            # Vai para a página e espera até que o JavaScript carregue tudo
            page.goto(url, timeout=30000)
            page.wait_for_load_state("networkidle") 
            
            # Extrai o HTML depois que a página já processou tudo
            html_bruto = page.content()
            browser.close()
            
            # Agora usamos o BeautifulSoup para ler a página "desbloqueada"
            soup = BeautifulSoup(html_bruto, 'html.parser')
            
            # Exemplo prático: vamos tentar extrair o último rendimento (DY) da página
            # O StatusInvest guarda o DY numa div com a classe 'value'
            dy_element = soup.find('div', title='Dividend Yield com base nos últimos 12 meses')
            if dy_element:
                dy_valor = dy_element.find('strong', class_='value').text
                return f"✅ **Sucesso Playwright!**\n\nConsegui acessar o StatusInvest sem ser bloqueado!\nO Dividend Yield de {ticker} extraído da tela agora é: **{dy_valor}%**"
            else:
                return "⚠️ Acessei a página com sucesso, mas não encontrei o campo do DY (O layout deles pode ter mudado)."

    except Exception as e:
        return f"❌ Erro na execução do Playwright: {str(e)}"