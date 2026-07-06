import datetime
from dateutil.relativedelta import relativedelta
import module_ia # Importamos a sua IA
from lib_mercado.cvm import RAD
from lib_mercado.fundosnet import FundosNet

def extrair_resumo_ia(ticker, tipo_documento, texto_bruto):
    """
    Envia o texto extraído para o Gemini resumir e dar o veredito.
    """
    prompt = f"""
    Você é um analista financeiro sênior. O utilizador pediu uma análise sobre o {tipo_documento} do ativo {ticker}.
    Baseado no texto bruto extraído do documento oficial abaixo, forneça:
    1. 📝 **Resumo Completo:** O que aconteceu de importante? (Lucros, vacância, dividendos, etc.)
    2. ⚖️ **A Situação:** A empresa/fundo está saudável?
    3. 🎯 **Veredito Final:** (Positivo, Negativo ou Neutro) e o porquê.
    
    Texto bruto:
    {texto_bruto[:15000]} # Limitamos para não estourar os tokens
    """
    
    # Chama a mesma IA que você já tem configurada no seu module_ia
    resposta = module_ia.consultar_gemini(prompt)
    return resposta

def buscar_fatos_relevantes(ticker, is_fii=False):
    """
    Busca os últimos 2 Fatos Relevantes do ano atual.
    """
    hoje = datetime.date.today()
    inicio_ano = datetime.date(hoje.year, 1, 1)
    
    # Aqui a magia acontece usando a sua pasta lib_mercado
    if is_fii:
        fnet = FundosNet()
        # Categoria 2 é Fato Relevante no FundosNet
        docs = list(fnet.busca(categoria="Fato Relevante", inicio=inicio_ano, fim=hoje, itens_por_pagina=2))
    else:
        rad = RAD()
        # Busca Fatos Relevantes (Categoria IPE_3)
        docs = list(rad.busca(data_inicio=inicio_ano, data_fim=hoje, empresas=[ticker]))
        
    if not docs:
        return "Nenhum Fato Relevante encontrado neste ano até o momento."
    
    # Pega apenas os últimos 2
    ultimos_docs = docs[:2]
    
    # Para simplificar a ponte, enviamos os metadados (títulos) para a IA criar o contexto
    contexto = f"Documentos encontrados para {ticker}:\n"
    for d in ultimos_docs:
        contexto += f"- Data: {d.datahora_entrega.strftime('%d/%m/%Y')} | Assunto: {d.assunto or d.tipo}\n"
        contexto += f"  Link Original: {d.url_download if hasattr(d, 'url_download') else getattr(d, 'url', 'Link indisponível')}\n"

    resumo = extrair_resumo_ia(ticker, "Últimos 2 Fatos Relevantes", contexto)
    return resumo

def buscar_relatorios_gerenciais(ticker):
    """
    Busca relatórios dos últimos 2 meses. Exclusivo para FIIs.
    """
    hoje = datetime.date.today()
    dois_meses_atras = hoje - relativedelta(months=2)
    
    fnet = FundosNet()
    docs = list(fnet.busca(categoria="Relatório Gerencial", inicio=dois_meses_atras, fim=hoje, itens_por_pagina=2))
    
    if not docs:
        return "Nenhum Relatório Gerencial publicado nos últimos 2 meses."
        
    contexto = f"Relatórios Gerenciais recentes de {ticker}:\n"
    for d in docs:
        contexto += f"- Data: {d.datahora_entrega.strftime('%d/%m/%Y')} | Tipo: {d.tipo}\n"
        contexto += f"  Link: {getattr(d, 'url', 'Indisponível')}\n"

    return extrair_resumo_ia(ticker, "Relatório Gerencial (Últimos 2 meses)", contexto)

def buscar_resultados_trimestrais(ticker):
    """
    Busca DFP / ITR (Lucros e 1º Trimestre) dos últimos 3 meses para Ações.
    """
    hoje = datetime.date.today()
    tres_meses_atras = hoje - relativedelta(months=3)
    
    rad = RAD()
    # Categoria IPE e DFP
    docs = list(rad.busca(data_inicio=tres_meses_atras, data_fim=hoje, empresas=[ticker]))
    
    # Filtra apenas Balanços/Resultados
    docs_balanco = [d for d in docs if d.categoria in ['ITR', 'DFP', 'Demonstrações Financeiras']]
    
    if not docs_balanco:
        return "Ainda não foram divulgados resultados trimestrais recentes (ITR/DFP)."
        
    ultimos = docs_balanco[:2]
    contexto = f"Resultados Trimestrais de {ticker}:\n"
    for d in ultimos:
        contexto += f"- Data: {d.datahora_entrega.strftime('%d/%m/%Y')} | Ref: {d.datahora_referencia}\n"
        contexto += f"  Download: {d.url_download}\n"

    return extrair_resumo_ia(ticker, "Resultados Trimestrais (ITR/DFP)", contexto)

def buscar_noticias_macro():
    """
    Usa a IA para buscar e resumir as principais manchetes macroeconômicas.
    """
    prompt = """
    Aja como um terminal Bloomberg. Liste as 3 notícias macroeconômicas mais importantes do Brasil e do Mundo hoje.
    Resuma o impacto de cada uma delas na bolsa de valores (B3) e na taxa Selic.
    """
    return module_ia.consultar_gemini(prompt)