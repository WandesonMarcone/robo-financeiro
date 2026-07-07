import datetime
from dateutil.relativedelta import relativedelta
import module_ia 
import yfinance as yf

# Mantemos apenas o FundosNet, que costuma permitir robôs
from mercados.fundosnet import FundosNet

def extrair_resumo_ia(ticker, tipo_documento, texto_bruto):
    prompt = f"""
    Você é um analista financeiro sênior. O utilizador pediu uma análise sobre o {tipo_documento} do ativo {ticker}.
    Baseado nos dados brutos abaixo, forneça:
    1. 📝 **Resumo Completo:** O que aconteceu de importante? (Lucros, vacância, dividendos, impactos).
    2. ⚖️ **A Situação:** A empresa/fundo está saudável?
    3. 🎯 **Veredito Final:** (Positivo, Negativo ou Neutro) e o porquê.
    
    Dados brutos:
    {texto_bruto[:15000]} 
    """
    return module_ia.consultar_gemini(prompt)

def buscar_fatos_relevantes(ticker, is_fii=False):
    """
    FIIs usam FundosNet. Ações usam a API Global (Anti-Bloqueio).
    """
    if is_fii:
        try:
            hoje = datetime.date.today()
            inicio_ano = datetime.date(hoje.year, 1, 1)
            fnet = FundosNet()
            docs = list(fnet.busca(categoria="Fato Relevante", inicio=inicio_ano, fim=hoje, itens_por_pagina=2))
            
            if not docs: return "Nenhum Fato Relevante encontrado para este FII no sistema oficial."
            
            contexto = f"Fatos Relevantes CVM de {ticker}:\n"
            for d in docs[:2]:
                contexto += f"- Data: {d.datahora_entrega.strftime('%d/%m/%Y')} | Assunto: {d.assunto or d.tipo}\n"
                contexto += f"  Link: {getattr(d, 'url', 'Link indisponível')}\n"
            return extrair_resumo_ia(ticker, "Últimos 2 Fatos Relevantes (CVM)", contexto)
        except Exception as e:
            return f"❌ A CVM bloqueou o acesso ao FII: {e}"
    else:
        # Rota de Ações (YFinance)
        try:
            asset = yf.Ticker(f"{ticker}.SA")
            news = asset.news
            if not news: return "Nenhum evento corporativo recente encontrado no terminal."
            
            contexto = f"Últimos Eventos Corporativos para {ticker}:\n"
            for n in news[:2]:
                # Tenta formatar a data, se houver
                try: 
                    data_pub = datetime.datetime.fromtimestamp(n['providerPublishTime']).strftime('%d/%m/%Y')
                except: 
                    data_pub = "Recente"
                contexto += f"- Data: {data_pub} | Título: {n['title']}\n"
                contexto += f"  Link: {n['link']}\n"
                
            return extrair_resumo_ia(ticker, "Eventos Corporativos Recentes", contexto)
        except Exception as e:
            return f"❌ Erro ao consultar terminal da Ação: {e}"

def buscar_relatorios_gerenciais(ticker):
    """ Exclusivo para FIIs """
    try:
        hoje = datetime.date.today()
        dois_meses_atras = hoje - relativedelta(months=2)
        fnet = FundosNet()
        docs = list(fnet.busca(categoria="Relatório Gerencial", inicio=dois_meses_atras, fim=hoje, itens_por_pagina=2))
        
        if not docs: return "Nenhum Relatório Gerencial publicado nos últimos 2 meses."
            
        contexto = f"Relatórios Gerenciais recentes de {ticker}:\n"
        for d in docs:
            contexto += f"- Data: {d.datahora_entrega.strftime('%d/%m/%Y')} | Tipo: {d.tipo}\n"
            contexto += f"  Link: {getattr(d, 'url', 'Indisponível')}\n"
        return extrair_resumo_ia(ticker, "Relatório Gerencial (Últimos 2 meses)", contexto)
    except Exception as e:
        return f"❌ Erro de conexão com a B3/CVM: {e}"

def buscar_resultados_trimestrais(ticker):
    """ Exclusivo para Ações (Puxa DRE direto da API) """
    try:
        asset = yf.Ticker(f"{ticker}.SA")
        dre = asset.quarterly_income_stmt
        if dre.empty: return "Demonstrativos trimestrais (ITR/DFP) não disponíveis via API."
        
        # Pega os 2 últimos trimestres
        dre_recente = dre.iloc[:, :2] 
        contexto = f"DRE Trimestral Resumida de {ticker} (Últimos 2 Trimestres):\n{dre_recente.to_string()}"
        return extrair_resumo_ia(ticker, "Resultados Trimestrais (DRE Institucional)", contexto)
    except Exception as e:
        return f"❌ Erro ao extrair DRE: {e}"

def buscar_noticias_macro():
    prompt = """Aja como um terminal Bloomberg. Liste as 3 notícias macroeconômicas mais importantes do Brasil e do Mundo hoje. Resuma o impacto de cada uma delas na bolsa de valores e juros."""
    return module_ia.consultar_gemini(prompt)