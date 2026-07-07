import datetime
from dateutil.relativedelta import relativedelta
import yfinance as yf
from mercados.fundosnet import FundosNet
import module_ia 

def extrair_resumo_ia(ticker, tipo_documento, texto_bruto):
    prompt = f"""
    Você é um analista financeiro sênior. O utilizador pediu uma análise sobre o {tipo_documento} do ativo {ticker}.
    
    Dados extraídos do servidor oficial:
    {texto_bruto[:8000]}
    
    Forneça:
    1. 📝 Resumo (O que aconteceu de importante?)
    2. 🎯 Veredito (Impacto positivo, negativo ou neutro)
    """
    
    # Estratégia de segurança para invocar o seu Gemini independentemente de como o seu module_ia está escrito
    try:
        # Se o seu modelo estiver exposto diretamente
        return module_ia.model.generate_content(prompt).text
    except:
        try:
            # Se usar a função genérica que já tínhamos
            return module_ia.analisar_fatos_com_ia(ticker + "\nDados: " + texto_bruto[:1000])
        except Exception as e:
            return f"⚠️ Resumo IA indisponível. Seguem os dados originais:\n\n{texto_bruto[:1000]}"

def buscar_fatos_relevantes(ticker, is_fii=False):
    if is_fii:
        try:
            hoje = datetime.date.today()
            inicio_ano = datetime.date(hoje.year, 1, 1)
            fnet = FundosNet()
            
            # Busca sem parâmetros restritos para não causar TypeError
            docs_gerais = list(fnet.busca(categoria="Fato Relevante", inicio=inicio_ano, fim=hoje))
            
            # Filtro Laser: Separa apenas os documentos do seu FII
            prefixo = ticker[:4].upper()
            docs_fundo = [d for d in docs_gerais if prefixo in str(getattr(d, 'nome_fundo', '')).upper()]
            
            if not docs_fundo: 
                return f"Nenhum Fato Relevante de {ticker} registado neste ano na CVM."
            
            contexto = f"Fatos Relevantes de {ticker}:\n"
            for d in docs_fundo[:2]:
                contexto += f"- Data: {d.datahora_entrega.strftime('%d/%m/%Y')} | Assunto: {getattr(d, 'assunto', getattr(d, 'tipo', ''))}\n"
                contexto += f"  Link: {getattr(d, 'url', 'Link indisponível')}\n"
                
            return extrair_resumo_ia(ticker, "Últimos 2 Fatos Relevantes", contexto)
        except Exception as e:
            return f"❌ Erro na extração CVM: {e}"
    else:
        try:
            asset = yf.Ticker(f"{ticker}.SA")
            news = asset.news
            if not news: return "Nenhum evento corporativo recente encontrado."
            
            contexto = f"Eventos Corporativos de {ticker}:\n"
            for n in news[:2]:
                data_pub = datetime.datetime.fromtimestamp(n.get('providerPublishTime', 0)).strftime('%d/%m/%Y') if 'providerPublishTime' in n else "Recente"
                contexto += f"- Data: {data_pub} | Título: {n.get('title', '')}\n  Link: {n.get('link', '')}\n"
                
            return extrair_resumo_ia(ticker, "Eventos Corporativos", contexto)
        except Exception as e:
            return f"❌ Erro no terminal: {e}"

def buscar_relatorios_gerenciais(ticker):
    try:
        hoje = datetime.date.today()
        dois_meses_atras = hoje - relativedelta(months=2)
        fnet = FundosNet()
        
        docs_gerais = list(fnet.busca(categoria="Relatório Gerencial", inicio=dois_meses_atras, fim=hoje))
        
        prefixo = ticker[:4].upper()
        docs_fundo = [d for d in docs_gerais if prefixo in str(getattr(d, 'nome_fundo', '')).upper()]
        
        if not docs_fundo: 
            return f"Nenhum Relatório Gerencial de {ticker} nos últimos 2 meses."
            
        contexto = f"Relatórios Gerenciais de {ticker}:\n"
        for d in docs_fundo[:2]:
            contexto += f"- Data: {d.datahora_entrega.strftime('%d/%m/%Y')} | Tipo: {getattr(d, 'tipo', '')}\n"
            contexto += f"  Link: {getattr(d, 'url', 'Indisponível')}\n"
            
        return extrair_resumo_ia(ticker, "Relatório Gerencial", contexto)
    except Exception as e:
        return f"❌ Erro ao extrair relatório da B3: {e}"

def buscar_resultados_trimestrais(ticker):
    try:
        asset = yf.Ticker(f"{ticker}.SA")
        dre = asset.quarterly_income_stmt
        if dre.empty: return "Demonstrativos trimestrais indisponíveis."
        
        dre_recente = dre.iloc[:, :2]
        contexto = f"DRE Trimestral Resumida de {ticker}:\n{dre_recente.to_string()}"
        return extrair_resumo_ia(ticker, "Resultados Trimestrais", contexto)
    except Exception as e:
        return f"❌ Erro ao extrair balanço: {e}"

def buscar_noticias_macro():
    prompt = "Liste as 3 notícias macroeconômicas mais importantes do Brasil e Mundo hoje. Resuma o impacto."
    return module_ia.consultar_gemini(prompt)