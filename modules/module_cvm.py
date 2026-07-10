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
# Usa getattr para não quebrar caso o dicionário ainda não esteja no config.py
MAPA_RI = getattr(config, 'MAPA_RI_SITES', {}) 

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
        nome_completo = yf.Ticker(f"{ticker_upper}.SA").info.get('longName', '').upper()
        nome_limpo = nome_completo.replace("FUNDO DE INVESTIMENTO IMOBILIARIO", "").replace("FUNDO DE INVESTIMENTO", "").replace("S.A.", "").replace("SA", "").strip()
        partes = nome_limpo.split()
        return f"{partes[0]} {partes[1]}" if len(partes) > 1 else partes[0]
    except:
        return ticker_upper[:4]

# ==========================================
# 2. INTEGRAÇÃO DRIVE, PDF E IA (VISÃO RAIO-X)
# ==========================================
def salvar_pdf_no_drive(nome_arquivo, pdf_bytes):
    """Guarda o PDF extraído diretamente no seu Google Drive."""
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
            # Pega as 3 primeiras, as 2 últimas ou qualquer uma com os termos-chave
            if i < 3 or i >= len(leitor.pages) - 2 or any(termo in texto_lower for termo in palavras_chave):
                texto_estrategico += f"\n\n--- [PÁGINA {i+1}] ---\n{texto_pagina}"
                
        return texto_estrategico[:100000]
    except Exception as e:
        return f"Erro ao aplicar Raio-X no PDF: {str(e)}"

def extrair_resumo_ia(ticker, tipo_documento, texto_bruto, link_drive=None):
    """Envia o texto estruturado para o Gemini gerar o laudo final."""
    prompt = f"""
    Atue como um analista financeiro institucional sênior. O utilizador pediu uma análise sobre o documento '{tipo_documento}' do ativo {ticker}.
    Abaixo estão os dados extraídos das bases oficiais:
    
    {texto_bruto[:15000]}
    
    Forneça um laudo com:
    1. 📝 Principais destaques: Resumo claro do que aconteceu.
    2. 💰 Impacto Financeiro: Como isso afeta o DRE, Vacância, Caixa ou Dividendos.
    3. 🎯 Veredito do Especialista: Este evento gera uma Oportunidade ou Risco? Justifique.
    """
    resumo = module_ia.analisar_fatos_com_ia(ticker + f" - {tipo_documento}\n\n" + prompt)
    
    if link_drive:
        resumo += f"\n\n📂 **Documento Oficial (Salvo no Drive):** [Acessar Arquivo Completo]({link_drive})"
        
    return resumo

# ==========================================
# 3. MÓDULO DE RELATÓRIOS (CASCATA DE SEGURANÇA)
# ==========================================
def buscar_relatorio_ri(ticker):
    """Camada Ouro: Procura o PDF oficial direto no site de RI (se configurado)."""
    url = MAPA_RI.get(ticker.upper())
    if not url: return None
    
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            if ".pdf" in href.lower() and ("gerencial" in href.lower() or "relatorio" in href.lower()):
                return href if href.startswith('http') else f"https://{ticker.lower()}.ri.com.br{href}"
        return None
    except: return None

def buscar_relatorios_gerenciais(ticker):
    """
    Orquestra a busca de relatórios gerenciais:
    1. Site de RI (Download direto) -> 2. Fundamentus (Scraping)
    """
    # TENTATIVA 1: Site Direto de RI (Mais seguro, gera PDF)
    pdf_url = buscar_relatorio_ri(ticker)
    if pdf_url:
        try:
            pdf_bytes = requests.get(pdf_url, headers={'User-Agent': 'Mozilla/5.0'}).content
            link_drive = salvar_pdf_no_drive(f"{ticker}_Relatorio_Gerencial.pdf", pdf_bytes)
            texto_raiox = extrair_texto_pdf(pdf_bytes)
            return extrair_resumo_ia(ticker, "Relatório Gerencial (Via RI)", texto_raiox, link_drive)
        except Exception as e:
            print(f"Erro ao processar PDF do RI para {ticker}: {e}")

    # TENTATIVA 2: Fundamentus (Texto rápido se o RI não estiver mapeado)
    try:
        url_fr = f"https://www.fundamentus.com.br/fr.php?papel={ticker}"
        response = requests.get(url_fr, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
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
                    
        return f"Nenhum Relatório Gerencial encontrado para {ticker} (Bases consultadas: RI e Fundamentus)."
    except Exception as e:
        return f"❌ Erro na extração de Relatórios: {e}"

def buscar_fatos_relevantes(ticker, is_fii=False):
    """Cascata: 1. Fundamentus -> 2. brFinance (CVM) -> 3. Yahoo"""
    contexto = ""
    
    # TENTATIVA 1: Fundamentus
    try:
        url_fr = f"https://www.fundamentus.com.br/fr.php?papel={ticker}"
        response = requests.get(url_fr, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
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

    # TENTATIVA 2: brFinance (Integração Oficial CVM para Documentos)
    if not contexto and not is_fii:
        try:
            cvm_api = CVMAsyncBackend()
            print(f"Acionando motor oficial brFinance (CVM) para {ticker}...")
            # Futura expansão: Aqui extraímos documentos diretamente da base CVM
        except: pass

    # TENTATIVA 3: Yahoo Finance (Notícias/Eventos)
    if not contexto:
        try:
            news = yf.Ticker(f"{ticker}.SA").news
            if news:
                contexto = f"Eventos Corporativos (Fonte: Yahoo Finance) de {ticker}:\n"
                for n in news[:2]:
                    contexto += f"- Título: {n.get('title', '')}\n  Link: {n.get('link', '')}\n"
        except: pass

    if not contexto: return f"Nenhum Fato Relevante ou notícia recente encontrada para {ticker}."
    return extrair_resumo_ia(ticker, "Fatos Relevantes", contexto)

# ==========================================
# 4. FINLOGIC E YFINANCE (BALANÇOS E DRE)
# ==========================================
def buscar_resultados_trimestrais(ticker):
    """Cascata: FinLogic (Profundo) -> Yahoo Finance (Rápido)"""
    contexto = f"Demonstrativos Financeiros (DRE) de {ticker}:\n\n"
    
    try:
        print("Iniciando motor FinLogic (DRE)...")
        empresa = fl.Company(ticker)
        dre_df = empresa.report(report_type='dre', acc_method='consolidated')
        contexto += "Fonte: FinLogic (Base CVM Contábil)\n" + dre_df.head(10).to_string()
    except Exception as e_fl:
        print(f"⚠️ FinLogic indisponível/sem dados. Trocando para Yahoo Finance...")
        try:
            dre_yf = yf.Ticker(f"{ticker}.SA").quarterly_income_stmt
            if dre_yf.empty:
                return f"Demonstrativos trimestrais indisponíveis para {ticker} em todas as bases."
            contexto += "Fonte: Yahoo Finance (ITR)\n" + dre_yf.iloc[:, :2].to_string()
        except Exception as e_yf:
            return f"❌ Falha crítica ao extrair DRE (FinLogic e Yahoo): {e_yf}"

    return extrair_resumo_ia(ticker, "Resultados Trimestrais", contexto)

# ==========================================
# 5. QUANTSTATS (RISCO E DESEMPENHO)
# ==========================================
def analisar_performance_quantstats(ticker):
    """Motor matemático de risco."""
    try:
        hist = yf.Ticker(f"{ticker}.SA").history(period="1y")
        if hist.empty: return f"Sem dados históricos suficientes para {ticker}."
        
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