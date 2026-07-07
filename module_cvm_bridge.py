import datetime
from dateutil.relativedelta import relativedelta
import yfinance as yf
from mercados.fundosnet import FundosNet
import module_ia 

def extrair_resumo_ia(ticker, tipo_documento, texto_bruto):
    prompt = f"""
    Você é um analista financeiro sênior. O utilizador pediu uma análise sobre o {tipo_documento} do ativo {ticker}.
    Dados extraídos do servidor oficial:
    {texto_bruto[:10000]}
    
    Forneça de forma clara e resumida:
    1. 📝 O que aconteceu de importante nos documentos?
    2. 🎯 Veredito final (Impacto positivo, negativo ou neutro) na saúde do ativo.
    """
    return module_ia.analisar_fatos_com_ia(ticker + f" - {tipo_documento}\n\n" + texto_bruto[:10000])

def buscar_fatos_relevantes(ticker, is_fii=False):
    if is_fii:
        try:
            hoje = datetime.date.today()
            inicio_ano = datetime.date(hoje.year, 1, 1)
            fnet = FundosNet()
            
            # Categoria exata conforme o dicionário da B3
            docs_gerais = list(fnet.busca(categoria="Fato Relevante", inicio=inicio_ano, fim=hoje))
            
            # Filtro Laser: Procura apenas os documentos do FII solicitado para poupar memória
            prefixo = ticker[:4].upper()
            docs_fundo = [d for d in docs_gerais if prefixo in str(getattr(d, 'nome_fundo', '')).upper()]
            
            if not docs_fundo: 
                return f"Nenhum Fato Relevante de {ticker} registado neste ano no FundosNet."
            
            contexto = f"Fatos Relevantes Oficiais de {ticker}:\n"
            for d in docs_fundo[:2]:
                contexto += f"- Data: {d.datahora_entrega.strftime('%d/%m/%Y')} | Assunto: {getattr(d, 'assunto', getattr(d, 'tipo', ''))}\n"
                contexto += f"  Link: {getattr(d, 'url', 'Link indisponível')}\n"
                
            return extrair_resumo_ia(ticker, "Fatos Relevantes", contexto)
        except Exception as e:
            return f"❌ Erro na extração B3: {e}"
    else:
        try:
            asset = yf.Ticker(f"{ticker}.SA")
            news = asset.news
            if not news: return "Nenhum evento corporativo recente encontrado no terminal."
            
            contexto = f"Eventos Corporativos Oficiais de {ticker}:\n"
            for n in news[:2]:
                if 'providerPublishTime' in n:
                    data_pub = datetime.datetime.fromtimestamp(n['providerPublishTime']).strftime('%d/%m/%Y')
                else:
                    data_pub = "Recente"
                contexto += f"- Data: {data_pub} | Título: {n.get('title', '')}\n  Link: {n.get('link', '')}\n"
                
            return extrair_resumo_ia(ticker, "Eventos Corporativos", contexto)
        except Exception as e:
            return f"❌ Erro de conexão com o terminal de ações: {e}"

def buscar_relatorios_gerenciais(ticker):
    try:
        hoje = datetime.date.today()
        dois_meses_atras = hoje - relativedelta(months=2)
        fnet = FundosNet()
        
        # 🔥 CORREÇÃO DO ERRO: Alterado para "Relatórios" conforme exigência da B3
        docs_gerais = list(fnet.busca(categoria="Relatórios", inicio=dois_meses_atras, fim=hoje))
        
        prefixo = ticker[:4].upper()
        docs_fundo = [d for d in docs_gerais if prefixo in str(getattr(d, 'nome_fundo', '')).upper()]
        
        if not docs_fundo: 
            return f"Nenhum Relatório de {ticker} publicado nos últimos 2 meses."
            
        contexto = f"Relatórios Recentes de {ticker}:\n"
        for d in docs_fundo[:2]:
            contexto += f"- Data: {d.datahora_entrega.strftime('%d/%m/%Y')} | Tipo: {getattr(d, 'tipo', '')}\n"
            contexto += f"  Link: {getattr(d, 'url', 'Indisponível')}\n"
            
        return extrair_resumo_ia(ticker, "Relatório Gerencial", contexto)
    except Exception as e:
        return f"❌ Erro ao extrair relatórios da B3: {e}"

def buscar_resultados_trimestrais(ticker):
    try:
        asset = yf.Ticker(f"{ticker}.SA")
        dre = asset.quarterly_income_stmt
        if dre.empty: return "Demonstrativos trimestrais indisponíveis."
        
        dre_recente = dre.iloc[:, :2]
        contexto = f"DRE Trimestral Resumida (Fonte dos dados: CVM) de {ticker}:\n{dre_recente.to_string()}"
        return extrair_resumo_ia(ticker, "Resultados Trimestrais (ITR/DFP)", contexto)
    except Exception as e:
        return f"❌ Erro ao extrair balanço financeiro: {e}"

def buscar_noticias_macro():
    return module_ia.analisar_fatos_com_ia("Resuma as 3 notícias macroeconômicas mais importantes do Brasil e Mundo hoje, indicando o impacto direto na Bolsa de Valores e na curva de juros.")