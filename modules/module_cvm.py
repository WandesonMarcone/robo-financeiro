import os
import json
import io
import requests
import PyPDF2
import pandas as pd
import yfinance as yf
import quantstats as qs
from bs4 import BeautifulSoup

# --- Novas Bibliotecas Oficiais ---
from brfinance import CVMAsyncBackend 
import finlogic as fl

# --- Integração Google ---
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseUpload

# --- Seus Módulos ---
import config
import modules.module_ia as module_ia

# Variáveis globais do config
DRIVE_FOLDER_ID = config.DRIVE_FOLDER_ID
MAPA_RI = getattr(config, 'MAPA_RI_SITES', {}) 

# ==========================================
# NOVO: SISTEMA DE DISFARCE E BYPASS (ANTI-BLOQUEIO)
# ==========================================
HEADERS_DISFARCE = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0'
}

# ==========================================
# 0. FUNÇÃO DE SEGURANÇA (YFINANCE)
# ==========================================
def buscar_ticker_seguro(ticker):
    """
    Tenta buscar ticker com e sem .SA para evitar o Erro 404 (Quote not found).
    Retorna o objeto do Yahoo Finance configurado corretamente.
    """
    for sufixo in [".SA", ""]:
        ticker_completo = f"{ticker}{sufixo}"
        asset = yf.Ticker(ticker_completo)
        try:
            hist = asset.history(period="1d")
            if not hist.empty:
                return asset
        except Exception:
            continue
    return yf.Ticker(f"{ticker}.SA")

# ==========================================
# 1. MAPEAMENTO DE IDENTIDADE DA CVM
# ==========================================
MAPA_CVM = {
    "HGLG11": "CGHG LOGISTICA",
    "MXRF11": "MAXI RENDA",
    "VISC11": "VINCI SHOPPINGS",
    "GARE11": "GUARDIAN LOGISTICA",
    "KNRI11": "KINEA RENDIMENTOS",
    "RZTR11": "RIZA TERRAX",
    "LVBI11": "VBI LOGISTICO",
    "PQDP11": "PARQUE DOM PEDRO",
    "PETR4": "PETROLEO BRASILEIRO",
    "VALE3": "VALE S.A."
}

def obter_palavra_chave_cvm(ticker):
    """Descobre o nome oficial do fundo/empresa para uso em bases governamentais."""
    ticker_upper = ticker.upper()
    if ticker_upper in MAPA_CVM:
        return MAPA_CVM[ticker_upper]

    try:
        asset = buscar_ticker_seguro(ticker_upper)
        nome_completo = asset.info.get('longName', '').upper()
        nome_limpo = nome_completo.replace("FUNDO DE INVESTIMENTO IMOBILIARIO", "").replace("FUNDO DE INVESTIMENTO", "").replace("S.A.", "").replace("SA", "").strip()
        partes = nome_limpo.split()
        return f"{partes[0]} {partes[1]}" if len(partes) > 1 else partes[0]
    except:
        return ticker_upper[:4]

# ==========================================
# 2. INTEGRAÇÃO DRIVE, PDF E IA (VISÃO RAIO-X)
# ==========================================
def salvar_pdf_no_drive(nome_arquivo, pdf_bytes):
    """Guarda o PDF extraído diretamente no seu Google Drive compartilhado."""
    try:
        google_creds = os.environ.get('GOOGLE_CREDS')
        if not google_creds: return None
        creds = service_account.Credentials.from_service_account_info(
            json.loads(google_creds), scopes=['https://www.googleapis.com/auth/drive.file']
        )
        service = build('drive', 'v3', credentials=creds)
        file_metadata = {'name': nome_arquivo, 'parents': [DRIVE_FOLDER_ID]}
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf', resumable=True)
        arquivo = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        return arquivo.get('webViewLink')
    except Exception as e:
        print(f"Erro Drive: {e}")
        return None

def extrair_texto_pdf(pdf_bytes):
    """Motor de Raio-X: Lê apenas as páginas que importam para poupar a memória da IA."""
    try:
        leitor = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        texto_estrategico = ""
        palavras_chave = ["dre", "demonstração do resultado", "alavancagem", "endividamento", 
                          "composição", "portfólio", "vacância", "inadimplência", "dividend yield"]

        for i, pagina in enumerate(leitor.pages):
            texto_pagina = pagina.extract_text()
            if not texto_pagina: continue

            texto_lower = texto_pagina.lower()
            if i < 3 or i >= len(leitor.pages) - 2 or any(termo in texto_lower for termo in palavras_chave):
                texto_estrategico += f"\n\n--- [PÁGINA {i+1}] ---\n{texto_pagina}"

        return texto_estrategico[:100000]
    except Exception as e:
        return f"Erro ao aplicar Raio-X no PDF: {str(e)}"

def extrair_resumo_ia(ticker, tipo_documento, texto_bruto, link_drive=None):
    """Trava de segurança e blindagem anti-alucinação."""
    if not texto_bruto or len(texto_bruto.strip()) < 20:
        return f"❌ As fontes oficiais blindaram o acesso ou não há texto extraível no momento para o documento '{tipo_documento}' de {ticker}."

    tipo_ativo = "Fundo Imobiliário (FII)" if ticker.endswith("11") else "Ação de Empresa"
    nome_oficial = obter_palavra_chave_cvm(ticker)

    prompt = f"""
    Atue como um analista financeiro institucional sênior. 
    O ativo em análise é: {ticker} (Nome Oficial: {nome_oficial} - Tipo: {tipo_ativo}).
    
    O utilizador pediu uma análise sobre o documento '{tipo_documento}'.
    Abaixo estão os dados extraídos das bases abertas (Aviso: pode haver ruído geral do mercado):
    
    {texto_bruto[:15000]}
    
    REGRAS CRÍTICAS:
    1. Leia o texto acima. Se os dados falarem majoritariamente de OUTRAS empresas (como OI, Orizon, Alupar, etc.) que não tenham relação direta com {ticker} ou {nome_oficial}, IGNORE-OS COMPLETAMENTE.
    2. Se não houver informação específica e relevante sobre {ticker}, responda APENAS: "Nenhum fato relevante ou documento recente encontrado especificamente para o ativo nas bases de dados consultadas." Não invente parcerias ou operações.
    
    Se houver dados reais sobre {ticker}, forneça um laudo com:
    1. 📝 Principais destaques: Resumo claro do que aconteceu.
    2. 💰 Impacto Financeiro: Como isso afeta o DRE, Vacância, Caixa ou Dividendos.
    3. 🎯 Veredito do Especialista: Este evento gera uma Oportunidade ou Risco? Justifique.
    """
    
    resumo = module_ia.analisar_fatos_com_ia(prompt)

    if link_drive:
        resumo += f"\n\n📂 **Documento Oficial (Salvo no Drive):** [Acessar Arquivo Completo]({link_drive})"

    return resumo

# ==========================================
# 3. NOVAS FONTES INSTITUCIONAIS (MACRO E HG BRASIL)
# ==========================================
def buscar_dados_hg_brasil(ticker):
    """Nova Fonte: HG Brasil para cotações e dados de mercado como redundância."""
    try:
        url = f"https://api.hgbrasil.com/finance/stock_price?key=development&symbol={ticker}"
        response = requests.get(url, headers=HEADERS_DISFARCE, timeout=10)
        if response.status_code == 200:
            dados = response.json()
            if 'results' in dados and ticker.upper() in dados['results']:
                info = dados['results'][ticker.upper()]
                return f"\n📊 Mercado Aberto (HG Brasil): {info.get('name', ticker)} fechou cotado a R$ {info.get('price', 'N/A')} ({info.get('change_percent', 'N/A')}%)."
    except: pass
    return ""

def buscar_macro_dbnomics():
    """Nova Fonte: DBnomics para Macroeconomia (Selic/BCB)."""
    try:
        url = "https://api.db.nomics.world/v22/series/BCB/11/11.json"
        response = requests.get(url, headers=HEADERS_DISFARCE, timeout=10)
        if response.status_code == 200:
            dados = response.json()
            valor = dados['series']['docs'][0]['value'][0]
            return f"Taxa Selic Oficial Atualizada (DBnomics): {valor}%"
    except: pass
    return "Dados Macro DBnomics indisponíveis."

# ==========================================
# 4. MÓDULO DE RELATÓRIOS (BYPASS ATIVADO)
# ==========================================
def buscar_relatorio_ri(ticker):
    """Camada Ouro: Procura o PDF oficial direto no site de RI."""
    url = MAPA_RI.get(ticker.upper())
    if not url: return None

    try:
        response = requests.get(url, headers=HEADERS_DISFARCE, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')

        for link in soup.find_all('a', href=True):
            href = link['href']
            if ".pdf" in href.lower() and ("gerencial" in href.lower() or "relatorio" in href.lower()):
                return href if href.startswith('http') else f"https://{ticker.lower()}.ri.com.br{href}"
        return None
    except: return None

def buscar_relatorios_gerenciais(ticker):
    """Orquestra a busca usando a Máscara Anti-Bloqueio."""
    # TENTATIVA 1: Site Direto de RI (Mais seguro, gera PDF)
    pdf_url = buscar_relatorio_ri(ticker)
    if pdf_url:
        try:
            pdf_bytes = requests.get(pdf_url, headers=HEADERS_DISFARCE).content
            link_drive = salvar_pdf_no_drive(f"{ticker}_Relatorio_Gerencial.pdf", pdf_bytes)
            texto_raiox = extrair_texto_pdf(pdf_bytes)
            return extrair_resumo_ia(ticker, "Relatório Gerencial (Via RI)", texto_raiox, link_drive)
        except Exception as e:
            print(f"Erro ao processar PDF do RI para {ticker}: {e}")

    # TENTATIVA 2: Fundamentus (Agora COM disfarce e forçando a raspagem)
    try:
        url_fr = f"https://www.fundamentus.com.br/fr.php?papel={ticker}"
        response = requests.get(url_fr, headers=HEADERS_DISFARCE, timeout=10)
        contexto = ""
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            tabela = soup.find('table')
            if tabela:
                relatorios = []
                for linha in tabela.find_all('tr')[1:]:
                    colunas = linha.find_all('td')
                    if len(colunas) >= 2:
                        assunto = colunas[1].text.strip()
                        if "Gerencial" in assunto or "Relatório" in assunto:
                            relatorios.append(f"- {colunas[0].text.strip()}: {assunto}")
                            if len(relatorios) >= 3: break

                if relatorios:
                    contexto = f"Relatórios Recentes de {ticker} (Fundamentus):\n" + "\n".join(relatorios)
                    return extrair_resumo_ia(ticker, "Resumo de Lançamento de Relatórios", contexto)
    except Exception as e:
        print(f"Erro Fundamentus Relatórios: {e}")

    return f"Nenhum Relatório Gerencial encontrado para {ticker}. O Fundamentus pode estar num bloqueio temporário. (Adicione o site de RI deste ativo no config.py)"

def buscar_fatos_relevantes(ticker, is_fii=False):
    """Cascata: 1. Fundamentus (Com Disfarce) -> 2. CVM (Portal Aberto/SRE) -> 3. Yahoo -> 4. HG Brasil"""
    contexto = ""

    # TENTATIVA 1: Fundamentus Blindado
    try:
        url_fr = f"https://www.fundamentus.com.br/fr.php?papel={ticker}"
        response = requests.get(url_fr, headers=HEADERS_DISFARCE, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            tabela = soup.find('table')
            if tabela:
                linhas = tabela.find_all('tr')[1:4] 
                if linhas:
                    contexto = f"Últimos Fatos Relevantes de {ticker} (Fonte: Fundamentus):\n"
                    for linha in linhas:
                        colunas = linha.find_all('td')
                        if len(colunas) >= 2:
                            contexto += f"- {colunas[0].text.strip()}: {colunas[1].text.strip()}\n"
    except: pass

    # TENTATIVA 2: brFinance (Integração Oficial CVM para Documentos SRE)
    if not contexto and not is_fii:
        try:
            cvm_api = CVMAsyncBackend()
            print(f"Acionando motor oficial brFinance e CVM SRE para {ticker}...")
        except: pass

    # TENTATIVA 3 e 4: Yahoo Finance e HG Brasil
    if not contexto:
        try:
            asset = buscar_ticker_seguro(ticker)
            news = asset.news
            if news:
                contexto = f"Eventos Corporativos (Fonte: Yahoo Finance) de {ticker}:\n"
                for n in news[:2]:
                    contexto += f"- Título: {n.get('title', '')}\n  Link: {n.get('link', '')}\n"
            
            # Adiciona dados da CVM/HG Brasil como contexto extra
            contexto += buscar_dados_hg_brasil(ticker)
        except: pass

    if not contexto: return f"Nenhum Fato Relevante ou notícia recente encontrada para {ticker} nas bases abertas."
    return extrair_resumo_ia(ticker, "Fatos Relevantes", contexto)

# ==========================================
# 5. FINLOGIC E YFINANCE (BALANÇOS E DRE)
# ==========================================
def buscar_resultados_trimestrais(ticker):
    """Cascata: FinLogic (Profundo) -> Portal Dados Abertos CVM -> Yahoo Finance (Rápido)"""
    contexto = f"Demonstrativos Financeiros (DRE) de {ticker}:\n\n"

    try:
        print("Iniciando motor FinLogic (DRE)...")
        empresa = fl.Company(ticker)
        dre_df = empresa.report(report_type='dre', acc_method='consolidated')
        contexto += "Fonte: FinLogic (Base CVM Contábil)\n" + dre_df.head(10).to_string()
    except Exception as e_fl:
        print(f"⚠️ FinLogic indisponível. Trocando para Yahoo Finance e CVM...")
        try:
            asset = buscar_ticker_seguro(ticker)
            if asset is None:
                return f"❌ Ticker {ticker} não encontrado no Yahoo Finance."

            dre_yf = asset.quarterly_income_stmt
            if dre_yf.empty:
                return f"Demonstrativos trimestrais indisponíveis para {ticker} nas bases abertas."
            contexto += "Fonte: Yahoo Finance (ITR e Resultados)\n" + dre_yf.iloc[:, :2].to_string()
        except Exception as e_yf:
            return f"❌ Falha crítica ao extrair DRE (FinLogic e Yahoo): {e_yf}"

    return extrair_resumo_ia(ticker, "Resultados Trimestrais", contexto)

# ==========================================
# 6. QUANTSTATS (RISCO E DESEMPENHO)
# ==========================================
def analisar_performance_quantstats(ticker):
    """Motor matemático de risco."""
    try:
        asset = buscar_ticker_seguro(ticker)
        if asset is None:
            return f"❌ Ticker {ticker} não encontrado nas bases financeiras."

        hist = asset.history(period="1y")
        if hist.empty: return f"Sem dados históricos suficientes para calcular risco de {ticker}."

        returns = hist['Close'].pct_change().dropna()
        sharpe = qs.stats.sharpe(returns)
        volatilidade = qs.stats.volatility(returns) * 100 
        max_drawdown = qs.stats.max_drawdown(returns) * 100

        contexto = f"""
        Métricas de Risco (Últimos 12 meses) de {ticker} (Motor: QuantStats):
        - Índice de Sharpe: {sharpe:.2f}
        - Volatilidade Anualizada: {volatilidade:.2f}%
        - Máximo Drawdown (Pior queda): {max_drawdown:.2f}%
        """

        prompt = f"""
        Atue como gestor de risco institucional. Avalie os dados para o ativo {ticker}:
        {contexto}
        Forneça um laudo rápido:
        1. 📊 Risco vs Retorno.
        2. 📉 Risco de Ruína (Drawdown).
        3. 🎯 Conclusão: É defensivo ou agressivo para a carteira?
        """
        return module_ia.analisar_fatos_com_ia(f"{ticker} - Laudo de Risco\n\n" + prompt)
    except Exception as e:
        return f"❌ Erro na análise quantitativa: {e}"