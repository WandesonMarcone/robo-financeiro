import os
import json
import io
import datetime
import requests
import PyPDF2
import pandas as pd
import yfinance as yf
import quantstats as qs
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseUpload

# Importamos as novas bibliotecas de dados
from brfinance import CVMAsyncBackend
import finlogic as fl

import config
import modules.module_ia as module_ia

DRIVE_FOLDER_ID = config.DRIVE_FOLDER_ID

# ==========================================
# 1. MAPEAMENTO E INTELIGÊNCIA DE NOMES
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
    """Investigador de Identidade: Tenta mapa fixo, depois Yahoo."""
    ticker_upper = ticker.upper()
    if ticker_upper in MAPA_CVM:
        return MAPA_CVM[ticker_upper]
    try:
        yf_ticker = yf.Ticker(f"{ticker_upper}.SA")
        nome_completo = yf_ticker.info.get('longName', '').upper()
        nome_limpo = nome_completo.replace("FUNDO DE INVESTIMENTO IMOBILIARIO", "").replace("FUNDO DE INVESTIMENTO", "").replace("S.A.", "").replace("SA", "").strip()
        partes = nome_limpo.split()
        return f"{partes[0]} {partes[1]}" if len(partes) > 1 else partes[0]
    except Exception:
        return ticker_upper[:4]

# ==========================================
# 2. INTEGRAÇÃO GOOGLE DRIVE E VISÃO RAIO-X
# ==========================================

def autenticar_drive():
    google_creds = os.environ.get('GOOGLE_CREDS')
    if google_creds:
        creds_dict = json.loads(google_creds)
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/drive.file'])
        return build('drive', 'v3', credentials=creds)
    return None

def salvar_pdf_no_drive(nome_arquivo, pdf_bytes):
    try:
        drive_service = autenticar_drive()
        if not drive_service:
            return None, "Erro de autenticação com o Google Drive."
        file_metadata = {'name': nome_arquivo, 'parents': [DRIVE_FOLDER_ID]}
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf', resumable=True)
        arquivo = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        return arquivo.get('webViewLink'), None
    except Exception as e:
        return None, str(e)

def extrair_texto_pdf(pdf_bytes):
    """Lê apenas as páginas cruciais (Visão Raio-X)."""
    try:
        leitor = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        texto_estrategico = ""
        palavras_chave = ["dre", "demonstração do resultado", "alavancagem", "endividamento", "composição", "portfólio", "vacância", "inadimplência", "dividend yield", "balanço patrimonial"]

        for i, pagina in enumerate(leitor.pages):
            texto_pagina = pagina.extract_text()
            if not texto_pagina: continue
            texto_lower = texto_pagina.lower()
            if i < 3 or i >= len(leitor.pages) - 2 or any(termo in texto_lower for termo in palavras_chave):
                texto_estrategico += f"\n\n--- [PÁGINA {i+1}] ---\n{texto_pagina}"
        return texto_estrategico[:100000]
    except Exception as e:
        return f"Erro ao extrair texto inteligente: {str(e)}"

def extrair_resumo_ia(ticker, tipo_documento, texto_bruto, link_drive=None):
    prompt = f"""
    Atue como um analista financeiro institucional sênior. O utilizador pediu uma análise sobre o documento '{tipo_documento}' do ativo {ticker}.
    Abaixo estão os dados extraídos:
    {texto_bruto[:15000]}
    
    Forneça de forma direta:
    1. 📝 Principais destaques: O que aconteceu de mais importante?
    2. 💰 Impacto Financeiro (Balanço, DRE, Vacância, Caixa, Dividendos).
    3. 🎯 Veredito: Este evento é uma Oportunidade ou Risco? Justifique tecnicamente.
    """
    resumo = module_ia.analisar_fatos_com_ia(ticker + f" - {tipo_documento}\n\n" + prompt)
    if link_drive:
        resumo += f"\n\n📂 **Documento salvo no Google Drive:** [Acessar Documento]({link_drive})"
    return resumo

# ==========================================
# 3. ORQUESTRADOR DE CVM, FATOS E RELATÓRIOS
# ==========================================

def buscar_fatos_relevantes(ticker, is_fii=False):
    """Busca Fatos Relevantes usando cascata de redundância (brFinance -> Fundamentus -> Yahoo)."""
    contexto = ""
    
    # TENTATIVA 1: Fundamentus (Mais rápido e estável para relatórios imediatos)
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
    except Exception as e:
        print(f"Erro Fundamentus FR: {e}")

    # TENTATIVA 2: brFinance (Se o Fundamentus falhar)
    if not contexto and not is_fii:
        try:
            # Integração base do brFinance para buscar cadastros na CVM
            cvm = CVMAsyncBackend()
            # Esta chamada pode ser expandida, mas deixamos preparada a estrutura
            print(f"Tentando CVM direta via brFinance para {ticker}...")
        except Exception as e:
            print(f"Erro brFinance: {e}")

    # TENTATIVA 3: Yahoo Finance (Último recurso)
    if not contexto:
        try:
            news = yf.Ticker(f"{ticker}.SA").news
            if news:
                contexto = f"Eventos Corporativos (Fonte: Yahoo Finance) de {ticker}:\n"
                for n in news[:2]:
                    contexto += f"- Título: {n.get('title', '')}\n  Link: {n.get('link', '')}\n"
        except Exception as e:
            return f"❌ Todas as fontes de Fatos Relevantes falharam para {ticker}."

    if not contexto: return f"Nenhum Fato Relevante encontrado para {ticker}."
    return extrair_resumo_ia(ticker, "Fatos Relevantes", contexto)

def buscar_relatorios_gerenciais(ticker):
    """Foco em FIIs. Tenta Fundamentus, contornando a B3/FundosNet."""
    try:
        url_fr = f"https://www.fundamentus.com.br/fr.php?papel={ticker}"
        response = requests.get(url_fr, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        contexto = ""
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            tabela = soup.find('table')
            if tabela:
                linhas = tabela.find_all('tr')[1:] 
                relatorios = []
                for linha in linhas:
                    colunas = linha.find_all('td')
                    if len(colunas) >= 2:
                        assunto = colunas[1].text.strip()
                        if "Gerencial" in assunto or "Relatório" in assunto:
                            relatorios.append(f"- {colunas[0].text.strip()}: {assunto}")
                            if len(relatorios) >= 3: break
                if relatorios:
                    contexto = f"Relatórios Gerenciais Recentes de {ticker} (Fonte: Fundamentus):\n" + "\n".join(relatorios)
        
        if not contexto: return f"Nenhum Relatório Gerencial recente encontrado para {ticker}."
        return extrair_resumo_ia(ticker, "Relatório Gerencial", contexto)
    except Exception as e:
        return f"❌ Erro na extração de Relatórios: {e}"

# ==========================================
# 4. FINLOGIC: ANÁLISE DE BALANÇOS E DRE
# ==========================================

def buscar_resultados_trimestrais(ticker):
    """Utiliza FinLogic para DRE contábil, com fallback seguro para Yahoo Finance."""
    contexto = f"Demonstrativos Financeiros e DRE de {ticker}:\n\n"
    try:
        # TENTATIVA 1: FinLogic (Profundo, mas consome memória no Render)
        print("Iniciando motor FinLogic (DRE)...")
        # Para evitar que o fl.update_database() crashe o seu servidor em nuvem
        # tentamos acessar a empresa diretamente.
        empresa = fl.Company(ticker)
        dre_df = empresa.report(report_type='dre', acc_method='consolidated')
        contexto += "Fonte: FinLogic (Base CVM)\n" + dre_df.head(10).to_string()
    except Exception as e_fl:
        print(f"⚠️ FinLogic não tem base local/falhou ({e_fl}). Usando Yahoo Finance...")
        # TENTATIVA 2: Yahoo Finance (Leve, rápido, sempre funciona)
        try:
            asset = yf.Ticker(f"{ticker}.SA")
            dre_yf = asset.quarterly_income_stmt
            if dre_yf.empty:
                return f"Demonstrativos trimestrais indisponíveis para {ticker}."
            dre_recente = dre_yf.iloc[:, :2] # Pega apenas os últimos 2 trimestres
            contexto += "Fonte: Yahoo Finance (ITR)\n" + dre_recente.to_string()
        except Exception as e_yf:
            return f"❌ Erro duplo (FinLogic e YF) ao extrair DRE: {e_yf}"

    return extrair_resumo_ia(ticker, "Resultados Trimestrais (ITR/DFP)", contexto)

# ==========================================
# 5. QUANTSTATS: ANÁLISE DE PERFORMANCE E RISCO
# ==========================================

def analisar_performance_quantstats(ticker):
    """Calcula Sharpe, Volatilidade e Drawdown da carteira/ativo."""
    try:
        asset = yf.Ticker(f"{ticker}.SA")
        hist = asset.history(period="1y")
        if hist.empty: return f"Sem dados históricos para calcular risco de {ticker}."
        
        # Calcula o retorno diário percentual (Obrigatório para o QuantStats)
        returns = hist['Close'].pct_change().dropna()
        
        # Extração de métricas institucionais via QuantStats
        sharpe = qs.stats.sharpe(returns)
        volatilidade = qs.stats.volatility(returns) * 100 # Anualizada
        max_drawdown = qs.stats.max_drawdown(returns) * 100
        
        contexto = f"""
        Métricas de Risco e Performance (Últimos 12 meses) geradas via QuantStats para {ticker}:
        - Índice de Sharpe: {sharpe:.2f} (Retorno ajustado ao risco)
        - Volatilidade Anualizada: {volatilidade:.2f}%
        - Máximo Drawdown (Pior queda): {max_drawdown:.2f}%
        """
        
        prompt = f"""
        Atue como um gestor de risco de portfólio. Avalie os dados estatísticos abaixo para o ativo {ticker}:
        {contexto}
        
        Forneça um laudo de 3 tópicos:
        1. 📊 Risco vs Retorno (Avalie o Sharpe).
        2. 📉 Risco de Ruína (Avalie o Drawdown).
        3. 🎯 Conclusão: É um ativo defensivo ou agressivo para manter na carteira?
        """
        return module_ia.analisar_fatos_com_ia(f"{ticker} - Relatório de Risco QuantStats\n\n" + prompt)
    except Exception as e:
        return f"❌ Erro na análise quantitativa (QuantStats): {e}"

# ==========================================
# 6. MACROECONOMIA
# ==========================================

def buscar_noticias_macro():
    """Gera um resumo macroeconômico utilizando a IA."""
    return module_ia.analisar_fatos_com_ia("Resuma as 3 notícias macroeconômicas mais importantes do Brasil e Mundo hoje, indicando o impacto direto na Bolsa de Valores, FIIs e na curva de juros.")