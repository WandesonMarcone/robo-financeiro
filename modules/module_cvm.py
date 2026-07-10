import os
import json
import io
import datetime
import PyPDF2
import yfinance as yf
from dateutil.relativedelta import relativedelta
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseUpload
from mercados.fundosnet import FundosNet

# Importamos o arquivo de configuração para pegar o ID da pasta
import config 

# Como o module_ia está na mesma pasta (modules/), 
# você pode importar direto:
import modules.module_ia as module_ia

# O ID agora vem do seu arquivo de configuração central
DRIVE_FOLDER_ID = config.DRIVE_FOLDER_ID

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
        
        # O Radar do Robô: Termos que indicam páginas cruciais
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
    Você é um analista financeiro sênior. O utilizador pediu uma análise sobre o documento '{tipo_documento}' do ativo {ticker}.
    
    Abaixo estão os dados extraídos do servidor oficial:
    {texto_bruto[:10000]}
    
    Forneça de forma clara e resumida:
    1. 📝 Principais destaques e acontecimentos.
    2. 🎯 Veredito final (Impacto positivo, negativo ou neutro) na saúde do ativo.
    """
    resumo = module_ia.analisar_fatos_com_ia(ticker + f" - {tipo_documento}\n\n" + prompt)
    
    if link_drive:
        resumo += f"\n\n📂 **Documento salvo no seu Google Drive:** [Acessar Documento]({link_drive})"
        
    return resumo

# --- BLOCO 2: FERRAMENTAS DE BUSCA E FILTRAGEM ---

def obter_palavra_chave_fundo(ticker):
    """Traduz o Ticker (Ex: GARE11) para o nome base oficial na B3 para otimizar as buscas no FundosNet."""
    try:
        nome_longo = yf.Ticker(f"{ticker}.SA").info.get('longName', '').upper()
        termos_inuteis = ["FUNDO", "DE", "INVESTIMENTO", "IMOBILIARIO", "IMOBILIÁRIO", "FII", "FDO", "INV", "IMOB", "S.A.", "SA", "REAL", "ESTATE", "LOGISTICA", "LOGÍSTICA", "RECEBÍVEIS", "RECEBIVEIS"]
        palavras = [p for p in nome_longo.split() if p not in termos_inuteis and len(p) > 2]
        return palavras[0] if palavras else ticker[:4].upper()
    except Exception:
        return ticker[:4].upper()

def buscar_fatos_relevantes(ticker, is_fii=False):
    """Busca fatos relevantes. Usa FundosNet para FIIs e Yahoo Finance para Ações."""
    if is_fii:
        try:
            hoje = datetime.date.today()
            inicio_ano = datetime.date(hoje.year, 1, 1)
            fnet = FundosNet()
            
            # ATENÇÃO: As buscas dependem da API do pacote 'mercados' e da disponibilidade dos dados da CVM/B3
            docs_gerais = list(fnet.busca(categoria="Fato Relevante", inicio=inicio_ano, fim=hoje))

            palavra_chave = obter_palavra_chave_fundo(ticker)
            docs_fundo = [d for d in docs_gerais if palavra_chave in str(getattr(d, 'nome_fundo', '')).upper() or ticker in str(getattr(d, 'nome_fundo', '')).upper()]

            if not docs_fundo: 
                return f"Nenhum Fato Relevante de {ticker} registrado neste ano (Buscando por: {palavra_chave})."

            contexto = f"Fatos Relevantes Oficiais de {ticker}:\n"
            for d in docs_fundo[:2]:
                data_str = getattr(d, 'datahora_entrega', None)
                data_formatada = data_str.strftime('%d/%m/%Y') if hasattr(data_str, 'strftime') else str(data_str)
                contexto += f"- Data: {data_formatada} | Assunto: {getattr(d, 'assunto', getattr(d, 'tipo', 'N/D'))}\n"
                contexto += f"  Link: {getattr(d, 'url', 'Link indisponível')}\n"

            return extrair_resumo_ia(ticker, "Fatos Relevantes", contexto)
        except Exception as e:
            return f"❌ Erro na extração via FundosNet (CVM/B3): {e}"
    else:
        try:
            asset = yf.Ticker(f"{ticker}.SA")
            news = asset.news
            if not news: return "Nenhum evento corporativo ou notícia recente encontrada no terminal."

            contexto = f"Eventos Corporativos Oficiais de {ticker}:\n"
            for n in news[:2]:
                if 'providerPublishTime' in n:
                    data_pub = datetime.datetime.fromtimestamp(n['providerPublishTime']).strftime('%d/%m/%Y')
                else:
                    data_pub = "Recente"
                contexto += f"- Data: {data_pub} | Título: {n.get('title', '')}\n  Link: {n.get('link', 'Link indisponível')}\n"

            return extrair_resumo_ia(ticker, "Eventos Corporativos (Notícias)", contexto)
        except Exception as e:
            return f"❌ Erro de conexão com o terminal de ações (Yahoo Finance): {e}"

def buscar_relatorios_gerenciais(ticker):
    nome_cvm = obter_palavra_chave_cvm(ticker)
    print(f"Buscando relatórios para: {nome_cvm} (Ticker: {ticker})")
    
    fnet = FundosNet()
    # E aqui a busca acontece usando o NOME, não o ticker!
    # docs = list(fnet.busca(fundo=nome_cvm, categoria="Relatórios", ...))


        docs_gerais = list(fnet.busca(categoria="Relatórios", inicio=tres_meses_atras, fim=hoje))

        palavra_chave = obter_palavra_chave_fundo(ticker)
        docs_fundo = [d for d in docs_gerais if palavra_chave in str(getattr(d, 'nome_fundo', '')).upper() or ticker in str(getattr(d, 'nome_fundo', '')).upper()]

        if not docs_fundo: 
            return f"Nenhum Relatório de {ticker} publicado nos últimos 3 meses (Buscando por: {palavra_chave})."

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