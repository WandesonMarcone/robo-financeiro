import io
import random
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz
import config
from modules.utils import formatar, precisa_atualizar, get_request_with_retry
from bs4 import BeautifulSoup

def buscar_dados_json_statusinvest(ticker):
    """
    Consome a API interna do StatusInvest. 
    Este JSON é a fonte oficial dos dados que alimentam os gráficos.
    """
    # Esta URL é o endpoint da API que o gráfico de portfólio consulta
    url_api = f"https://statusinvest.com.br/fii/portfolio-segment-chart?ticker={ticker.lower()}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'X-Requested-With': 'XMLHttpRequest' # Importante: identifica a requisição como API
    }
    
    try:
        response = requests.get(url_api, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json() # Retorna o objeto puro
    except Exception as e:
        print(f"Erro ao capturar JSON de {ticker}: {e}")
    return None

def classificar_fii_e_emoji(setor):
    """
    Classifica automaticamente o FII baseado no setor.
    """
    s = str(setor).upper()
    if any(x in s for x in ["TÍTULOS", "PAPEL", "RECEBÍVEL", "VALORES MOBILIÁRIOS"]): 
        return "Papel", "📜"
    if any(x in s for x in ["FUNDO DE FUNDOS", "FOF"]): 
        return "FOF", "🔄"
    if any(x in s for x in ["HÍBRIDO", "MISTO"]): 
        return "Híbrido", "🧩"
    return "Tijolo", "🧱"

def buscar_dados_profundos_fii(ticker):
    """
    Consome a página do StatusInvest para extrair Vacância, Imóveis, 
    Inquilinos e o Segmento Real.
    """
    try:
        url = f"https://statusinvest.com.br/fii/{ticker.lower()}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, 'html.parser')

        vacancia_real = 0.0
        imoveis_reais = 0
        principais_inquilinos = "Não informado / Não aplicável"
        segmento_real = None

        cards_info = soup.find_all('div', class_='info')

        for card in cards_info:
            titulo_tag = card.find('h3', class_='title')
            valor_tag = card.find('strong', class_='value')

            if titulo_tag and valor_tag:
                titulo = titulo_tag.text.strip().lower()
                valor = valor_tag.text.strip()

                if 'vacância' in titulo:
                    valor_limpo = valor.replace('%', '').replace(',', '.').strip()
                    if valor_limpo and valor_limpo != '-':
                        vacancia_real = float(valor_limpo) / 100
                elif 'imóveis' in titulo or 'ativos' in titulo:
                    if valor != '-':
                        try:
                            imoveis_reais = int(valor)
                        except ValueError:
                            pass
                # EXTRAÇÃO DO SETOR REAL (Para corrigir o 'Outros' do Fundamentus)
                elif 'segmento' in titulo:
                    if valor != '-':
                        segmento_real = valor

        # CORREÇÃO INQUILINOS (GARE11 e afins)
        tabelas = soup.find_all('table')
        for tabela in tabelas:
            header = tabela.find('thead')
            if header:
                texto_header = header.text.lower()
                # Agora o robô procura por Inquilino, Locatário ou Cliente
                if any(palavra in texto_header for palavra in ['inquilino', 'locatário', 'locatario', 'cliente']):
                    linhas = tabela.find('tbody').find_all('tr')
                    lista_inquilinos = []

                    for linha in linhas[:3]:
                        colunas = linha.find_all('td')
                        if len(colunas) >= 2:
                            nome_inquilino = colunas[0].text.strip()
                            porcentagem = colunas[-1].text.strip() 
                            lista_inquilinos.append(f"{nome_inquilino} ({porcentagem})")

                    if lista_inquilinos:
                        principais_inquilinos = ", ".join(lista_inquilinos)
                    break 

        return {
            "imoveis_reais": imoveis_reais,
            "vacancia_real": vacancia_real,
            "principais_inquilinos": principais_inquilinos,
            "segmento_real": segmento_real
        }

    except Exception as e:
        print(f"Erro ao raspar dados profundos de {ticker}: {e}")
        return None

def rodar_garimpo_fiis(planilha, agora_dt, agora_sp, sp_tz):
    print("🏢 [1/5] Iniciando varredura e auditoria completa do mercado de FIIs...")
    aba_fiis = planilha.worksheet("BD_FIIs")

    try:
        url = "https://www.fundamentus.com.br/fii_resultado.php"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        response = get_request_with_retry(url, headers=headers)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')

        for col in ['Cotação', 'P/VP', 'Dividend Yield', 'Liquidez', 'Vacância Média', 'Valor de Mercado', 'Qtd de imóveis']:
            if col in df.columns:
                df[col] = df[col].apply(formatar)
    except Exception as e:
        print(f"⚠️ [AVISO] Erro no Fundamentus: {e}. Contingência (Yahoo Finance).")
        df = pd.DataFrame()

    oportunidades_gerais = []
    novatos_garimpados = []
    dados_planilha = aba_fiis.get_all_values()
    tickers_planilha = []
    mapa_atualizacao = {}
    precos_antigos = {}

    for row in dados_planilha[1:]: 
        if row and row[0].strip():
            t = row[0].strip().upper()
            tickers_planilha.append(t)
            try:
                if len(row) > 3 and str(row[3]).strip():
                    raw_val = str(row[3]).replace('R$', '').replace('.', '').replace(',', '.').strip()
                    precos_antigos[t] = float(raw_val) if raw_val else 0.0
                else:
                    precos_antigos[t] = 0.0
            except:
                precos_antigos[t] = 0.0
            mapa_atualizacao[t] = row[15] if len(row) > 15 else "" 

    cat_fixas = [f for f in config.FIXAS_FIIS if f in tickers_planilha and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]

    if not df.empty:
        df_cacador = df[
            (df['P/VP'] >= 0.85) &
            (df['P/VP'] <= 1.01) &
            (df['Dividend Yield'] >= 0.095) &
            (df['Liquidez'] >= 5000000) &  
            (df['Vacância Média'] <= 0.10)                 
        ]
        oportunidades_gerais = df_cacador.sort_values(by='Dividend Yield', ascending=False).index.tolist()
        novatos_garimpados = [fii for fii in oportunidades_gerais if fii not in tickers_planilha and fii not in cat_fixas][:3]

    usadas = set(cat_fixas + novatos_garimpados)
    precisam_urgente = [t for t in tickers_planilha if t not in usadas and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)]
    cat_desatualizadas = random.sample(precisam_urgente, 2) if len(precisam_urgente) >= 2 else precisam_urgente

    fila_total = cat_fixas + novatos_garimpados + cat_desatualizadas
    if not fila_total: 
        return [], "", aba_fiis

    batch_updates = []
    relatorio_fixas = []
    relatorio_opps = []
    relatorio_atualizados = []
    relatorio_fixas_opps = []
    proxima_linha_vazia = len(dados_planilha) + 1 

    for ticker in fila_total:
        try:
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco_yf = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice') or 0)

            # TRAVA DE SEGURANÇA: Previne que um erro no Pandas crie vazamento de dados
            if not df.empty and ticker in df.index:
                f = df.loc[ticker]
                if isinstance(f, pd.DataFrame):
                    f = f.iloc[0] 
            else:
                f = {}

            preco_fundamentus = formatar(f.get('Cotação', 0))
            preco = preco_yf if preco_yf > 0 else preco_fundamentus
            setor = f.get('Segmento', 'N/D') if isinstance(f.get('Segmento'), str) else 'N/D'

            tipo, emoji = classificar_fii_e_emoji(setor)

            pvp = formatar(f.get('P/VP', 0))
            dy = formatar(f.get('Dividend Yield', 0))
            liquidez = formatar(f.get('Liquidez', 0))
            valor_mercado = formatar(f.get('Valor de Mercado', 0))
            
            # Variáveis resetadas rigorosamente a cada loop
            vacancia = formatar(f.get('Vacância Média', 0))
            qtd_imoveis = formatar(f.get('Qtd de imóveis', 0)) 
            inquilinos_planilha = "N/D"

            if tipo in ["Tijolo", "Híbrido", "FOF", "Papel"]: # Liberei a busca profunda para Papel também para corrigir os erros antigos
                dados_profundos = buscar_dados_profundos_fii(ticker)

                if dados_profundos:
                    if dados_profundos["vacancia_real"] is not None:
                        vacancia = dados_profundos["vacancia_real"]
                    if dados_profundos["imoveis_reais"] is not None:
                        qtd_imoveis = dados_profundos["imoveis_reais"]
                        
                    inquilinos_planilha = dados_profundos["principais_inquilinos"]
                    
                    # Se o StatusInvest tiver o setor real, sobrescreve o Fundamentus
                    if dados_profundos["segmento_real"]:
                        setor = dados_profundos["segmento_real"]
                        tipo, emoji = classificar_fii_e_emoji(setor) # Reclassifica com o setor real

            vpa = (preco / pvp) if pvp > 0 else 0
            numero_cotas = (valor_mercado / preco) if preco > 0 else 0
            media_div_mensal = (preco * dy) / 12
            lucro_12m = valor_mercado * dy 

            # =========================================================================
            # 🗺️ MAPEAMENTO COMPLETO (Agora com 18 Colunas: Distribuição de A até R)
            # =========================================================================
            row_update_completo = [
                ticker,                 # 00 | Coluna A: Ticker do Fundo
                tipo,                   # 01 | Coluna B: Tipo de FII (Ex: Tijolo, Papel)
                setor,                  # 02 | Coluna C: Segmento Específico
                preco,                  # 03 | Coluna D: Cotação Atualizada
                numero_cotas,           # 04 | Coluna E: Quantidade Total de Cotas
                pvp,                    # 05 | Coluna F: P/VP
                dy,                     # 06 | Coluna G: Dividend Yield
                vacancia,               # 07 | Coluna H: Vacância Física/Financeira Média
                qtd_imoveis,            # 08 | Coluna I: Quantidade Física de Imóveis
                inquilinos_planilha,     # 09 | Coluna J: LISTA DE INQUILINOS (Nova Coluna!)
                "Pendente de IA",       # 10 | Coluna K: WALT 
                "Pendente de IA",       # 11 | Coluna L: Alavancagem / Dívida
                liquidez,               # 12 | Coluna M: Liquidez Média Diária Negociada
                valor_mercado,          # 13 | Coluna N: Patrimônio Líquido Total
                vpa,                    # 14 | Coluna O: Valor Patrimonial Justo da Cota
                lucro_12m,              # 15 | Coluna P: Montante de Lucro Distribuído (12M)
                media_div_mensal,       # 16 | Coluna Q: Projeção de Dividendo Mensal
                f"{agora_sp} OK"       # 17 | Coluna R: Carimbo de Conclusão da Carga
                ]
            row_update_parcial = row_update_completo[1:] 

            if ticker in tickers_planilha:
                linha_idx = tickers_planilha.index(ticker) + 2
                batch_updates.append({'range': f'B{linha_idx}:R{linha_idx}', 'values': [row_update_parcial]})
            else:
                batch_updates.append({'range': f'A{proxima_linha_vazia}:R{proxima_linha_vazia}', 'values': [row_update_completo]})
                proxima_linha_vazia += 1

            preco_velho = precos_antigos.get(ticker, preco)
            icone_variacao = "📈" if preco > preco_velho else ("📉" if preco < preco_velho else "➖")
            txt_vacancia = f" | 🏚️ Vacância: {vacancia*100:.1f}%" if tipo == "Tijolo" else ""

            if ticker in novatos_garimpados:
                relatorio_opps.append(f"{emoji} *{ticker}* ({tipo})\n   R$ {preco:.2f}\n   P/VP: {pvp:.2f} | DY: {dy*100:.1f}%{txt_vacancia}")
            elif ticker in config.FIXAS_FIIS:
                texto_ativo = f"{emoji} *{ticker}* ({tipo})\n   R$ {preco_velho:.2f} ➔ R$ {preco:.2f} {icone_variacao}\n   P/VP: {pvp:.2f} | DY: {dy*100:.1f}%{txt_vacancia}"
                if ticker in oportunidades_gerais:
                    relatorio_fixas_opps.append(f"🚨 *{ticker} ENTROU EM DESCONTO!* 🚨\n   {texto_ativo}")
                else:
                    relatorio_fixas.append(texto_ativo)
            else:
                relatorio_atualizados.append(f"{emoji} *{ticker}* ({tipo})\n   R$ {preco_velho:.2f} ➔ R$ {preco:.2f} {icone_variacao}\n   P/VP: {pvp:.2f} | DY: {dy*100:.1f}%{txt_vacancia}")

            print(f"   ✅ [LOG GITHUB] FII {ticker} integrado à memória de atualização com sucesso.")

        except Exception as e:
            try:
                aba_logs = planilha.worksheet("BD_Logs")
                aba_logs.append_row([str(datetime.now(sp_tz)), f"FIIs: {ticker}", str(e)])
            except: pass

    msg_blocos = ["🏢 *MOVIMENTAÇÃO DE FIIs* 🏢"]
    if relatorio_fixas_opps: msg_blocos.append("🏆 *ALERTA VIP (Fixas em Oportunidade):*\n" + "\n\n".join(relatorio_fixas_opps))
    if relatorio_fixas: msg_blocos.append("📌 *SUA CARTEIRA FIXA:*\n" + "\n\n".join(relatorio_fixas))
    if relatorio_opps: msg_blocos.append("🎯 *TOP OPORTUNIDADES (Desconto + DY):*\n" + "\n\n".join(relatorio_opps))
    if relatorio_atualizados: msg_blocos.append("🔄 *OUTRAS ATUALIZAÇÕES:*\n" + "\n\n".join(relatorio_atualizados))
    msg_out = "\n\n➖➖➖➖➖➖➖➖➖➖\n\n".join(msg_blocos) if batch_updates else ""

    return batch_updates, msg_out, aba_fiis