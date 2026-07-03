import gspread
import pandas as pd
import yfinance as yf
import requests
import io
import random
import pytz
import urllib.parse
from datetime import datetime

# --- CONFIGURAÇÕES ---
FIXAS = ["PETR4", "VALE3", "ITUB4", "BBDC4"] 
JSON_KEY = 'credenciais.json' 
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

# --- WHATSAPP CONFIG ---
TELEFONE_WHATSAPP = "553491503895" 
API_KEY_WHATSAPP = "5116767"

def formatar(val):
    """Garante float e conserta o bug do % exorbitante."""
    try: 
        if isinstance(val, str):
            is_percent = '%' in val # Verifica se é uma porcentagem
            val = val.replace('%', '').replace('.', '').replace(',', '.')
            numero = float(val)
            # Se for porcentagem, divide por 100 para o Sheets exibir corretamente
            return numero / 100 if is_percent else numero
            
        return float(val) if val is not None and not pd.isna(val) else 0.0
    except: return 0.0

def enviar_whatsapp(msg):
    try:
        url = f"https://api.callmebot.com/whatsapp.php?phone={TELEFONE_WHATSAPP}&text={urllib.parse.quote(msg)}&apikey={API_KEY_WHATSAPP}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            print("📲 Notificação enviada com sucesso no WhatsApp!")
        else:
            print(f"⚠️ Erro ao enviar WhatsApp. Código: {res.status_code}")
    except Exception as e:
        print(f"⚠️ Falha de conexão com CallMeBot: {e}")

def atualizar_financeiro():
    print("🚀 INICIANDO AUDITORIA E ATUALIZAÇÃO DO SISTEMA 🚀")
    
    # Conexão
    print("[1/5] Conectando ao Google Sheets...")
    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")
    
    # Horário de São Paulo
    sp_tz = pytz.timezone('America/Sao_Paulo')
    agora_sp = datetime.now(sp_tz).strftime('%d/%m %H:%M')
    
    # 1. BUSCA DADOS FUNDAMENTUS
    print("[2/5] Baixando dados globais do Fundamentus...")
    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        df = pd.read_html(io.StringIO(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        print(f"✅ Sucesso: {len(df)} ativos mapeados do Fundamentus.")
    except Exception as e:
        print(f"❌ Erro crítico ao buscar Fundamentus: {e}")
        return

    # 2. DEFINIÇÃO DA FILA (A Mecânica 4-em-1)
    print("\n[3/5] Organizando a Fila de Prioridades (Inteligência 4-em-1)...")
    
    todas = aba_base.col_values(1)[1:]
    
    # 2.1 - C3 (Metodologia)
    ticker_c3 = str(aba_metodo.acell('C3').value).strip().upper()
    cat_metodologia = [ticker_c3] if ticker_c3 and ticker_c3 in todas else []
    
    # 2.2 - Oportunidades (Parâmetros: P/L abaixo de 12 e P/VP abaixo de 1.5)
    opps_brutas = df[(df['P/L'].astype(float) > 0.1) & (df['P/L'].astype(float) < 12) & (df['P/VP'].astype(float) < 1.5)].index.tolist()
    cat_opps = [o for o in opps_brutas if o in todas and o not in FIXAS and o != ticker_c3][:5]
    
    # 2.3 - Fixas
    cat_fixas = [f for f in FIXAS if f in todas]
    
    # 2.4 - Aleatórias da Planilha (evitando as que já estão na fila)
    usadas = set(cat_fixas + cat_metodologia + cat_opps)
    disponiveis = [t for t in todas if t not in usadas]
    cat_aleatorias = random.sample(disponiveis, min(len(disponiveis), 3))
    
    # Junta todas
    fila = cat_fixas + cat_metodologia + cat_opps + cat_aleatorias
    
    # --- NOVO LOG DETALHADO DO GITHUB ---
    print(f"-> Ações Fixas: {cat_fixas}")
    if cat_metodologia:
        print(f"-> Metodologia (C3): {cat_metodologia}")
    if cat_opps:
        print(f"-> Oportunidades garimpadas: {cat_opps}")
    print(f"-> Sorteio aleatório de manutenção: {cat_aleatorias}")
    print(f"-> TOTAL NA FILA: {len(fila)} ações.\n")

    # 3. PROCESSAMENTO E CAPTURA YAHOO FINANCE
    print("[4/5] Processando cruzamento de dados linha a linha...")
    batch_updates = []
    
    # Preparando variáveis para o WhatsApp
    relatorio_opps = []
    
    for ticker in fila:
        linha_idx = todas.index(ticker) + 2
        try:
            # 3.1 - YFINANCE (Preenchendo as falhas do Fundamentus + VPA/LPA)
            yf_info = yf.Ticker(f"{ticker}.SA").info
            preco = formatar(yf_info.get('currentPrice') or yf_info.get('regularMarketPrice'))
            n_acoes = formatar(yf_info.get('sharesOutstanding')) # Coluna D
            roa = formatar(yf_info.get('returnOnAssets'))        # Coluna T
            peg_ratio = formatar(yf_info.get('trailingPegRatio') or yf_info.get('pegRatio')) # Coluna AD
            valor_mercado = formatar(yf_info.get('marketCap'))   # Coluna AE
            vpa = formatar(yf_info.get('bookValue'))             # Coluna AB
            lpa = formatar(yf_info.get('trailingEps'))           # Coluna AC
            
            # 3.2 - FUNDAMENTUS (Base primária)
            f = df.loc[ticker]
            
            # 3.3 - MAPEAMENTO COMPLETO (B até AF)
            row = [
                preco,                                    # B: Preço (YF)
                formatar(f.get('Div.Yield', 0)),          # C: DY
                n_acoes,                                  # D: Nº Ações (YF)
                formatar(f.get('P/L', 0)),                # E: P/L
                formatar(f.get('P/VP', 0)),               # F: P/VP
                formatar(f.get('P/Ativo', 0)),            # G: P/Ativo
                formatar(f.get('Mrg Bruta', 0)),          # H: Marg. Bruta
                formatar(f.get('Mrg Ebit', 0)),           # I: Marg. EBIT
                formatar(f.get('Mrg. Líq.', 0)),          # J: Marg. Líq.
                formatar(f.get('P/EBIT', 0)),             # K: P/EBIT
                formatar(f.get('EV/EBIT', 0)),            # L: EV/EBIT
                formatar(f.get('Dív.Líq/ Patrim.', 0)),   # M: Div.Liq/Ebit (Mapeado via Patrimônio)
                formatar(f.get('Dív.Líq/ Patrim.', 0)),   # N: Div.Liq/Patri
                formatar(f.get('PSR', 0)),                # O: PSR
                formatar(f.get('P/Cap.Giro', 0)),         # P: P/Cap.Giro
                formatar(f.get('P/Ativ Circ.Liq', 0)),    # Q: P.At.Circ.Liq
                formatar(f.get('Liq. Corr.', 0)),         # R: Liq. Corr
                formatar(f.get('ROE', 0)),                # S: ROE
                roa,                                      # T: ROA (YF)
                formatar(f.get('ROIC', 0)),               # U: ROIC
                0, 0, 0,                                  # V, W, X (Vazios Intencionais)
                formatar(f.get('Cresc. Rec.5a', 0)),      # Y: CAGR Rec
                0,                                        # Z: CAGR Lucros (Vazio Intencional)
                formatar(f.get('Liq.2meses', 0)),         # AA: Liq. Media
                vpa,                                      # AB: VPA (YF)
                lpa,                                      # AC: LPA (YF)
                peg_ratio,                                # AD: PEG Ratio (YF)
                valor_mercado,                            # AE: Valor Mercado (YF)
                f"{agora_sp} OK"                          # AF: Atualização
            ]
            batch_updates.append({'range': f'B{linha_idx}:AF{linha_idx}', 'values': [row]})
            
            # 3.4 - Formatação do Log do GitHub (Filosofia "Silêncio é Ouro")
            cat_atual = "Fixa" if ticker in cat_fixas else "Metodologia" if ticker in cat_metodologia else "Oportunidade" if ticker in cat_opps else "Aleatória"
            
            # Verifica apenas dados essenciais para alertar caso falhem
            verificacao = {
                "Preço": preco, "Nº Ações": n_acoes, "VPA": vpa, "LPA": lpa, 
                "Valor Mercado": valor_mercado, "P/L": formatar(f.get('P/L', 0))
            }
            dados_zerados = [k for k, v in verificacao.items() if v == 0.0]
            
            if dados_zerados:
                print(f"   ✅ [OK] {ticker} ({cat_atual}) | Concluída. ⚠️ Não capturados: {', '.join(dados_zerados)}")
            else:
                print(f"   ✅ [OK] {ticker} ({cat_atual}) | Concluída com sucesso.")
            
            # Guardar os dados extras para o WhatsApp se for Oportunidade
            if ticker in cat_opps:
                roe_fmt = formatar(f.get('ROE', 0)) * 100 # Multiplica por 100 pra ficar legível na msg
                pl_fmt = formatar(f.get('P/L', 0))
                pvp_fmt = formatar(f.get('P/VP', 0))
                relatorio_opps.append(f"• *{ticker}*: R$ {preco} (P/L: {pl_fmt} | P/VP: {pvp_fmt} | ROE: {roe_fmt:.1f}%)")
                
        except Exception as e:
            print(f"   ❌ [ERRO] Falha ao processar {ticker}: {e}")

    # 4. ESCRITA EM LOTE E NOTIFICAÇÃO
    print("\n[5/5] Escrevendo lote no Google Sheets e Notificando...")
    if batch_updates:
        aba_base.batch_update(batch_updates)
        print(f"💾 Planilha atualizada perfeitamente ({len(batch_updates)} ações).")
        
        # Montar a mensagem do WhatsApp
        msg_wpp = "🤖 *Relatório de Atualização Mestre* 🤖\n\n"
        
        if cat_fixas: 
            msg_wpp += f"📌 *Ações Fixas:*\n{', '.join(cat_fixas)}\n\n"
        
        if cat_metodologia: 
            msg_wpp += f"🔍 *Metodologia (C3):*\n{', '.join(cat_metodologia)}\n\n"
            
        if cat_aleatorias: 
            msg_wpp += f"🎲 *Atualização Aleatória:*\n{', '.join(cat_aleatorias)}\n\n"
            
        if relatorio_opps:
            msg_wpp += "🎯 *Ações em Oportunidade:*\n"
            msg_wpp += "\n".join(relatorio_opps)
        else:
            msg_wpp += "🎯 *Oportunidades:* Nenhuma nova nesta rodada."
            
        # Enviar WhatsApp
        enviar_whatsapp(msg_wpp)
        
    else:
        print("⚠️ Nenhum dado para atualizar nesta rodada.")

    print("\n🏁 --- PROCESSO FINALIZADO --- 🏁")

if __name__ == "__main__":
    atualizar_financeiro()