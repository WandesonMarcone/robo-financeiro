import io
import random
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz
import config
from modules.utils import formatar, precisa_atualizar, get_request_with_retry

def classificar_fii_e_emoji(setor):
    """
    Classifica automaticamente o FII baseado no setor do Fundamentus 
    e atribui um Emoji visual de fácil identificação para o Telegram.
    """
    s = str(setor).upper()
    if any(x in s for x in ["TÍTULOS", "PAPEL", "RECEBÍVEL", "VALORES MOBILIÁRIOS"]): 
        return "Papel", "📜"
    if any(x in s for x in ["FUNDO DE FUNDOS", "FOF"]): 
        return "FOF", "🔄"
    if any(x in s for x in ["HÍBRIDO", "MISTO"]): 
        return "Híbrido", "🧩"
    return "Tijolo", "🧱"

def rodar_garimpo_fiis(planilha, agora_dt, agora_sp, sp_tz):
    print("🏢 [1/5] Iniciando varredura e auditoria completa do mercado de FIIs...")
    aba_fiis = planilha.worksheet("BD_FIIs")

    # 🛡️ Extração da tabela geral do Fundamentus (O Arrastão)
    try:
        url = "https://www.fundamentus.com.br/fii_resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = get_request_with_retry(url, headers=headers)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        
        # Formatação numérica preventiva para as colunas vitais
        for col in ['Cotação', 'P/VP', 'Dividend Yield', 'Liquidez', 'Vacância Média', 'Valor de Mercado', 'Qtd de imóveis']:
            if col in df.columns:
                df[col] = df[col].apply(formatar)
        print("   ✅ Base de dados do Fundamentus carregada com sucesso.")
    except Exception as e:
        print(f"⚠️ [AVISO] Erro no Fundamentus (Timeout ou Queda): {e}. Operando em modo de contingência (Yahoo Finance).")
        df = pd.DataFrame() 

    print("\n🏢 [2/5] Organizando a fila de processamento e verificando travas de tempo...")
    dados_planilha = aba_fiis.get_all_values()
    tickers_planilha = []
    mapa_atualizacao = {}
    precos_antigos = {}

    # Varredura inicial da planilha para mapear o estado atual
    # Varredura inicial da planilha para mapear o estado atual
    for row in dados_planilha[1:]: 
        if row and row[0].strip():
            t = row[0].strip().upper()
            tickers_planilha.append(t)
            
            # --- Lógica de Limpeza de Preço para FIIs (Coluna D / Índice 3) ---
            try:
                if len(row) > 3 and str(row[3]).strip():
                    # Remove R$, remove ponto de milhar, troca vírgula por ponto
                    raw_val = str(row[3]).replace('R$', '').replace('.', '').replace(',', '.').strip()
                    precos_antigos[t] = float(raw_val) if raw_val else 0.0
                else:
                    precos_antigos[t] = 0.0
            except:
                precos_antigos[t] = 0.0
            
            # O carimbo de validação (Coluna Q / Índice 16)
            mapa_atualizacao[t] = row[15] if len(row) > 15 else "" 
 
    # Filtro de ativos fixos definidos nas configurações
    cat_fixas = [f for f in config.FIXAS_FIIS if f in tickers_planilha and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]

    novatos_garimpados = []
    
    # Processamento do rastreamento de oportunidades em memória (Caçador)
    if not df.empty:
        # Filtragem Blindada (Ajuste dos requisitos)
        df_cacador = df[
            (df['P/VP'] >= 0.85) &
            (df['P/VP'] <= 1.05) &
            (df['Dividend Yield'] >= 0.08) &
            (df['Liquidez'] >= 3000000) &  # <--- Aumentado para 3 milhões
            (df['Vacância Média'] <= 0.10)                 
        ]
        oportunidades_gerais = df_cacador.sort_values(by='Dividend Yield', ascending=False).index.tolist()
        novatos_garimpados = [fii for fii in oportunidades_gerais if fii not in tickers_planilha and fii not in cat_fixas][:3]

    # Coleta de ativos desatualizados de forma aleatória para girar a base de dados
    usadas = set(cat_fixas + novatos_garimpados)
    precisam_urgente = [t for t in tickers_planilha if t not in usadas and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)]
    cat_desatualizadas = random.sample(precisam_urgente, 2) if len(precisam_urgente) >= 2 else precisam_urgente

    fila_total = cat_fixas + novatos_garimpados + cat_desatualizadas
    if not fila_total: 
        print("✅ [FIIs] Nenhuma atualização necessária. Todos os FIIs atualizados nas últimas 2 horas.")
        return [], "", aba_fiis

    print(f"   📋 Ativos selecionados para a rodada: {fila_total}")

    print("\n🏢 [3/5] Cruzando dados das APIs e montando estrutura de atualização...")
    batch_updates = []
    relatorio_fixas = []
    relatorio_opps = []
    relatorio_atualizados = []
    relatorio_fixas_opps = []
    proxima_linha_vazia = len(dados_planilha) + 1 

    # Laço principal de execução por ativo
    for ticker in fila_total:
        try:
            # 🌐 Consulta direcionada ao Yahoo Finance
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco_yf = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice') or 0)

            # Consulta direcionada ao dataframe local do Fundamentus
            f = df.loc[ticker] if (not df.empty and ticker in df.index) else {}
            preco_fundamentus = formatar(f.get('Cotação', 0))

            # Escolha inteligente do preço ativo válido (Fallback Inteligente)
            preco = preco_yf if preco_yf > 0 else preco_fundamentus

            setor = f.get('Segmento', 'N/D') if isinstance(f.get('Segmento'), str) else 'N/D'

            # Correção Cirúrgica Anti-Fundamentus para classificações erradas na origem
            if ticker == "GARE11": setor, tipo, emoji = "Galpões/Renda Urbana", "Tijolo", "🧱"
            elif ticker == "VISC11": setor, tipo, emoji = "Shoppings", "Tijolo", "🧱"
            elif ticker == "MXRF11": setor, tipo, emoji = "Papel/Múltiplo", "Papel", "📜"
            else: tipo, emoji = classificar_fii_e_emoji(setor)

            # Captura de indicadores de saúde do fundo
            pvp = formatar(f.get('P/VP', 0))
            dy = formatar(f.get('Dividend Yield', 0))
            vacancia = formatar(f.get('Vacância Média', 0))
            liquidez = formatar(f.get('Liquidez', 0))
            valor_mercado = formatar(f.get('Valor de Mercado', 0))
            qtd_imoveis = formatar(f.get('Qtd de imóveis', 0)) 

            # Tratamento de segurança contra divisão por zero para cálculos derivados
            vpa = (preco / pvp) if pvp > 0 else 0
            numero_cotas = (valor_mercado / preco) if preco > 0 else 0
            media_div_mensal = (preco * dy) / 12
            lucro_12m = valor_mercado * dy 

            # =========================================================================
            # 🗺️ MAPEAMENTO COMPLETO (16 Colunas: Distribuição de A até Q)
            # =========================================================================
            row_update_completo = [
                ticker,                 # 00 | Coluna A: Ticker do Fundo
                tipo,                   # 01 | Coluna B: Tipo de FII (Ex: Tijolo, Papel)
                setor,                  # 02 | Coluna C: Segmento Específico (Fundamentus)
                preco,                  # 03 | Coluna D: Cotação Atualizada
                numero_cotas,           # 04 | Coluna E: Quantidade Total de Cotas (Cálculo)
                pvp,                    # 05 | Coluna F: Múltiplo Preço / Valor Patrimonial
                dy,                     # 06 | Coluna G: Dividend Yield (12 Meses)
                vacancia,               # 07 | Coluna H: Vacância Física/Financeira Média
                qtd_imoveis,            # 08 | Coluna I: Quantidade Física de Imóveis
                "Mapeamento em Curso",  # 09 | Coluna J: WALT (Pendente de IA/CVM)
                "Pendente",             # 10 | Coluna K: Alavancagem / Dívida (Pendente)
                liquidez,               # 11 | Coluna L: Liquidez Média Diária Negociada
                valor_mercado,          # 12 | Coluna M: Patrimônio Líquido Total / Valor de Mercado
                vpa,                    # 13 | Coluna N: Valor Patrimonial Justo da Cota
                lucro_12m,              # 14 | Coluna O: Montante de Lucro Distribuído (12 Meses)
                media_div_mensal,       # 15 | Coluna P: Projeção de Dividendo Mensal por Cota
                f"{agora_sp} OK"        # 16 | Coluna Q: Carimbo de Conclusão da Carga
            ]
            
            # Sub-seleção para atualização (Ignora a coluna A se o fundo já existir)
            row_update_parcial = row_update_completo[1:] 

            # Verificação estrutural para determinar o posicionamento do range de escrita
            if ticker in tickers_planilha:
                linha_idx = tickers_planilha.index(ticker) + 2
                batch_updates.append({'range': f'B{linha_idx}:Q{linha_idx}', 'values': [row_update_parcial]})
            else:
                batch_updates.append({'range': f'A{proxima_linha_vazia}:Q{proxima_linha_vazia}', 'values': [row_update_completo]})
                proxima_linha_vazia += 1

            # --- CONSTRUÇÃO DOS BLOCOS DO TELEGRAM ---
            preco_velho = precos_antigos.get(ticker, preco)
            icone_variacao = "📈" if preco > preco_velho else ("📉" if preco < preco_velho else "➖")
            
            # Filtro visual: Oculta vacância irrelevante (ex: fundos de papel)
            txt_vacancia = f" | 🏚️ Vacância: {vacancia*100:.1f}%" if tipo == "Tijolo" else ""

            # Estruturação e direcionamento lógico dos relatórios
            if ticker in novatos_garimpados:
                # Oculta o preço velho para ativos recém chegados
                texto_ativo = f"{emoji} *{ticker}* ({tipo})\n   R$ {preco:.2f}\n   P/VP: {pvp:.2f} | DY: {dy*100:.1f}%{txt_vacancia}"
                relatorio_opps.append(texto_ativo)
            
            elif ticker in config.FIXAS_FIIS:
                texto_ativo = f"{emoji} *{ticker}* ({tipo})\n   R$ {preco_velho:.2f} ➔ R$ {preco:.2f} {icone_variacao}\n   P/VP: {pvp:.2f} | DY: {dy*100:.1f}%{txt_vacancia}"
                
                # Regra de Alerta Máximo (VIP): Fixo que obedece às regras de barganha do Caçador
                if ticker in oportunidades_gerais:
                    relatorio_fixas_opps.append(f"🚨 *{ticker} ENTROU EM DESCONTO!* 🚨\n   {texto_ativo}")
                else:
                    relatorio_fixas.append(texto_ativo)
            
            else:
                # Atualização de rotina para base desatualizada
                texto_ativo = f"{emoji} *{ticker}* ({tipo})\n   R$ {preco_velho:.2f} ➔ R$ {preco:.2f} {icone_variacao}\n   P/VP: {pvp:.2f} | DY: {dy*100:.1f}%{txt_vacancia}"
                relatorio_atualizados.append(texto_ativo)

            print(f"   ✅ [LOG GITHUB] FII {ticker} integrado à memória de atualização com sucesso.")

        except Exception as e:
            print(f"   ❌ [ERRO CRÍTICO] Falha no processamento do FII {ticker}: {e}")
            # Desvio preventivo para gravação do erro na base de monitoramento de logs
            try:
                aba_logs = planilha.worksheet("BD_Logs")
                aba_logs.append_row([str(datetime.now(sp_tz)), f"FIIs: {ticker}", str(e)])
            except Exception as log_error:
                print(f"   ⚠️ Falha crítica ao tentar registrar a ocorrência no BD_Logs: {log_error}")

    print("\n🏢 [4/5] Estruturando e limpando mensagens modulares para o Telegram...")
    msg_blocos = ["🏢 *MOVIMENTAÇÃO DE FIIs* 🏢"]
    
    if relatorio_fixas_opps: 
        msg_blocos.append("🏆 *ALERTA VIP (Fixas em Oportunidade):*\n" + "\n\n".join(relatorio_fixas_opps))
    if relatorio_fixas: 
        msg_blocos.append("📌 *SUA CARTEIRA FIXA:*\n" + "\n\n".join(relatorio_fixas))
    if relatorio_opps: 
        msg_blocos.append("🎯 *TOP OPORTUNIDADES (Desconto + DY):*\n" + "\n\n".join(relatorio_opps))
    if relatorio_atualizados: 
        msg_blocos.append("🔄 *OUTRAS ATUALIZAÇÕES:*\n" + "\n\n".join(relatorio_atualizados))
    
    # Junção controlada por divisórias estruturadas para legibilidade Mobile
    msg_out = "\n\n➖➖➖➖➖➖➖➖➖➖\n\n".join(msg_blocos) if batch_updates else ""

    print("🏢 [5/5] Finalização dos pacotes de dados de FIIs. Pronto para envio.")
    return batch_updates, msg_out, aba_fiis
