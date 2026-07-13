import os
import sys
import io
import requests
import PyPDF2
import yfinance as yf
import quantstats as qs
from datetime import datetime

# Conecta o módulo à pasta pipeline_dados
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'pipeline_dados'))

# Tentativa de importar o Banco de Dados (Só funcionará após o GitHub criar o .db pela 1ª vez)
try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from banco_dados import Ativo, DocumentosQualitativos, DadosFinanceirosAcoes
    DB_PATH = "sqlite:///pipeline_dados/banco_institucional.db"
    engine = create_engine(DB_PATH)
    SessionDB = sessionmaker(bind=engine)
    BANCO_ATIVO = True
except:
    BANCO_ATIVO = False

import config
import modules.module_ia as module_ia

# ==========================================
# 0. FUNÇÃO DE SEGURANÇA (YFINANCE)
# ==========================================
def buscar_ticker_seguro(ticker):
    """Tenta buscar ticker com e sem .SA para evitar o Erro 404 (Quote not found)."""
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
    "HGLG11": "CGHG LOGISTICA", "MXRF11": "MAXI RENDA", "VISC11": "VINCI SHOPPINGS",
    "GARE11": "GUARDIAN LOGISTICA", "KNRI11": "KINEA RENDIMENTOS", "RZTR11": "RIZA TERRAX",
    "LVBI11": "VBI LOGISTICO", "PQDP11": "PARQUE DOM PEDRO", "PETR4": "PETROLEO BRASILEIRO",
    "VALE3": "VALE S.A."
}

def obter_palavra_chave_cvm(ticker):
    """Descobre o nome oficial do ativo."""
    return MAPA_CVM.get(ticker.upper(), ticker.upper()[:4])

# ==========================================
# 2. MOTOR DE LEITURA DE PDF PARA A IA
# ==========================================
def extrair_texto_pdf(pdf_bytes):
    """Lê apenas as páginas vitais de um PDF em memória para enviar à IA."""
    try:
        leitor = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        texto_estrategico = ""
        palavras_chave = ["dre", "resultado", "alavancagem", "vacância", "dividend"]

        for i, pagina in enumerate(leitor.pages):
            texto_pagina = pagina.extract_text()
            if not texto_pagina: continue
            
            # Limita a leitura para não sobrecarregar o Groq
            if i < 3 or i >= len(leitor.pages) - 2 or any(termo in texto_pagina.lower() for termo in palavras_chave):
                texto_estrategico += f"\n[PÁGINA {i+1}]\n{texto_pagina}"
                if len(texto_estrategico) > 20000: break # Trava de segurança de tamanho

        return texto_estrategico
    except Exception as e:
        return ""

def extrair_resumo_ia(ticker, tipo_documento, texto_bruto, link_direto=None):
    """Envia o texto estruturado para a IA analisar."""
    if not texto_bruto or len(texto_bruto.strip()) < 20:
        return f"❌ Não foi possível extrair texto legível do documento oficial de {ticker}."

    tipo_ativo = "Fundo Imobiliário (FII)" if ticker.endswith("11") else "Ação de Empresa"
    nome_oficial = obter_palavra_chave_cvm(ticker)

    prompt = f"""
    Atue como um analista financeiro institucional sênior. 
    Ativo: {ticker} ({nome_oficial} - {tipo_ativo}). Documento: '{tipo_documento}'.
    
    Dados do documento oficial:
    {texto_bruto[:15000]}
    
    1. 📝 Principais destaques: Resumo claro do evento.
    2. 💰 Impacto Financeiro: Como afeta Caixa, Vacância, Lucro ou Dividendos.
    3. 🎯 Veredito: Gera uma Oportunidade ou Risco? Justifique.
    """

    resumo = module_ia.analisar_fatos_com_ia(prompt)

    if link_direto:
        resumo += f"\n\n📂 **Acessar PDF Oficial (B3/CVM):** [Clique Aqui]({link_direto})"

    return resumo

# ==========================================
# 3. LEITURA DO NOVO BANCO DE DADOS (FIIs)
# ==========================================
def buscar_relatorios_gerenciais(ticker):
    """Busca o link limpo do PDF no Banco SQLite e envia para a IA ler."""
    if not BANCO_ATIVO:
        return "⚠️ O banco de dados CVM/B3 ainda não foi gerado pelo motor noturno."

    session = SessionDB()
    try:
        # Pesquisa no Banco de Dados
        doc = session.query(DocumentosQualitativos).join(Ativo).filter(
            Ativo.ticker == ticker.upper(),
            DocumentosQualitativos.tipo_documento == "Relatório Gerencial"
        ).order_by(DocumentosQualitativos.data_publicacao.desc()).first()

        if not doc:
            return f"Nenhum Relatório Gerencial recente encontrado para {ticker} na base de dados."

        # O Python acessa a URL limpa da B3 e extrai o texto para a IA
        resposta = requests.get(doc.url_pdf, timeout=15)
        texto_pdf = extrair_texto_pdf(resposta.content)
        
        return extrair_resumo_ia(ticker, f"Relatório Gerencial ({doc.data_publicacao})", texto_pdf, doc.url_pdf)
    except Exception as e:
        return f"Erro ao aceder ao banco de dados: {e}"
    finally:
        session.close()

def buscar_fatos_relevantes(ticker, is_fii=False):
    """Busca comunicados urgentes no Banco de Dados."""
    if not BANCO_ATIVO:
        return "⚠️ O banco de dados CVM/B3 ainda não foi gerado."

    session = SessionDB()
    try:
        doc = session.query(DocumentosQualitativos).join(Ativo).filter(
            Ativo.ticker == ticker.upper(),
            DocumentosQualitativos.tipo_documento == "Fato Relevante"
        ).order_by(DocumentosQualitativos.data_publicacao.desc()).first()

        if not doc:
            return f"Nenhum Fato Relevante encontrado para {ticker} na base de dados."

        resposta = requests.get(doc.url_pdf, timeout=15)
        texto_pdf = extrair_texto_pdf(resposta.content)
        
        return extrair_resumo_ia(ticker, f"Fato Relevante ({doc.data_publicacao})", texto_pdf, doc.url_pdf)
    except Exception as e:
        return f"Erro ao aceder ao banco de dados: {e}"
    finally:
        session.close()

# ==========================================
# 4. LEITURA DO NOVO BANCO DE DADOS (AÇÕES)
# ==========================================
def buscar_resultados_trimestrais(ticker):
    """Busca o Caixa e Lucro das Ações direto no Banco SQLite (ITR/DFP)."""
    if not BANCO_ATIVO:
        return "⚠️ O banco de dados CVM/B3 ainda não foi gerado."

    session = SessionDB()
    try:
        dados_acao = session.query(DadosFinanceirosAcoes).join(Ativo).filter(
            Ativo.ticker.like(f"%{ticker[:4]}%") # Busca aproximação (ex: PETR)
        ).order_by(DadosFinanceirosAcoes.data_referencia.desc()).first()

        if not dados_acao:
            # Fallback (Plano B): Se o banco ainda não tiver a ação, tenta o Yahoo Finance
            asset = buscar_ticker_seguro(ticker)
            dre_yf = asset.quarterly_income_stmt
            if dre_yf.empty:
                return f"Balanços indisponíveis para {ticker}."
            contexto = "Fonte: Yahoo Finance\n" + dre_yf.iloc[:, :2].to_string()
            return extrair_resumo_ia(ticker, "Resultados Trimestrais", contexto)

        contexto = f"""
        Balanço Oficial (Fonte: CVM / DFP-ITR):
        - Data de Referência: {dados_acao.data_referencia}
        - Lucro Líquido: R$ {dados_acao.lucro_liquido:,.2f}
        - Receita: R$ {dados_acao.receita:,.2f}
        - Caixa Disponível: R$ {dados_acao.caixa:,.2f}
        - Passivo (Dívida): R$ {dados_acao.passivo_total:,.2f}
        """
        return extrair_resumo_ia(ticker, "Resultados Trimestrais CVM", contexto)
    except Exception as e:
        return f"Erro ao ler balanço: {e}"
    finally:
        session.close()

# ==========================================
# 5. QUANTSTATS (RISCO E DESEMPENHO)
# ==========================================
def analisar_performance_quantstats(ticker):
    """Mantém-se igual: Usa YFinance para calcular o risco matemático (Volatilidade/Drawdown)."""
    try:
        asset = buscar_ticker_seguro(ticker)
        hist = asset.history(period="1y")
        if hist.empty: return "Sem dados históricos suficientes."

        returns = hist['Close'].pct_change().dropna()
        sharpe = qs.stats.sharpe(returns)
        volatilidade = qs.stats.volatility(returns) * 100 
        max_drawdown = qs.stats.max_drawdown(returns) * 100

        contexto = f"""
        Métricas de Risco (12 Meses):
        - Índice de Sharpe: {sharpe:.2f}
        - Volatilidade: {volatilidade:.2f}%
        - Máximo Drawdown: {max_drawdown:.2f}%
        """
        prompt = f"Atue como gestor de risco. Avalie os dados do {ticker}:\n{contexto}\nLaudo: 1. Risco/Retorno. 2. Risco de Ruína. 3. Conclusão."
        return module_ia.analisar_fatos_com_ia(prompt)
    except Exception as e:
        return f"Erro quantitativo: {e}"
