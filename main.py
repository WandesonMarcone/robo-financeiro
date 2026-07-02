import gspread
import pandas as pd
import yfinance as yf
import requests
import json
import pytz
import urllib.parse
from datetime import datetime

# --- CONFIGURAÇÕES E API ---
TOLERANCIA = 0.05
TELEFONE_WHATSAPP = "553491503895" 
API_KEY_WHATSAPP = "5116767"

def get_horario_brasilia():
    tz = pytz.timezone('America/Sao_Paulo')
    return datetime.now(tz)

def get_celula_float(valor):
    try:
        if isinstance(valor, (int, float)): return float(valor)
        if not valor: return 0.0
        valor = str(valor).replace('R$', '').replace('%', '').strip()
        if '.' in valor and ',' in valor: valor = valor.replace('.', '').replace(',', '.')
        elif ',' in valor: valor = valor.replace(',', '.')
        return float(valor)
    except: return 0.0

def calcular_discrepancia(v1, v2):
    v1, v2 = abs(float(v1 or 0)), abs(float(v2 or 0))
    if v1 == 0 and v2 == 0: return 0.0
    if v1 == 0 or v2 == 0: return 1.0 
    return abs(v1 - v2) / max(v1, v2)

def enviar_relatorio_whatsapp(sincronizados, alertas):
    msg = "📊 *Relatório Diário B3* 📊\n\n"
    if sincronizados:
        msg += "✅ *Consenso / Média Aplicada:*\n" + ", ".join(sincronizados) + "\n\n"
    if alertas:
        msg += "🔴 *Aguardando Revisão no Painel:*\n"
        for alerta in alertas:
            msg += f"• {alerta}\n"
    
    # Formata a mensagem para a URL (converte quebras de linha e espaços)
    texto_formatado = urllib.parse.quote(msg)
    url = f"https://api.callmebot.com/whatsapp.php?phone={TELEFONE_WHATSAPP}&text={texto_formatado}&apikey={API_KEY_WHATSAPP}"
    try: requests.get(url, timeout=5)
    except Exception as e: print(f"Falha no WhatsApp: {e}")

# --- FUNÇÃO PRINCIPAL ---
def atualizar_financeiro(request):
    print("Executando: Consenso, Médias e Relatório Consolidado...")
    JSON_KEY = 'credenciais.json' 
    SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 

    gc = gspread.service_account(filename=JSON_KEY)
    planilha = gc.open_by_url(SPREADSHEET_URL)
    aba_base = planilha.worksheet("Base de Dados")
    aba_metodo = planilha.worksheet("Metodologia Projetiva")
    aba_disc = planilha.worksheet("Discrepâncias")

    comando = str(aba_metodo.acell('C3').value).strip().upper()
    if not comando or comando == "CONCLUÍDO": return "Aguardando."

    ativos_core = ["ITUB4", "BBAS3", "PSSA3", "CMIG4", "VALE3", "SANB11", "SBSP3", "BBSE3", "BBDC3", "PETR4", "BBDC4", "B3SA3"]
    fund_data_dict = {}
    
    todas_linhas = aba_base.get_all_values()
    coluna_a = [linha[0].strip().upper() if len(linha) > 0 else "" for linha in todas_linhas]

    # 1. RASPAGEM
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get("https://www.fundamentus.com.br/resultado.php", headers=headers, timeout=10)
        df = pd.read_html(response.text, decimal=',', thousands='.')[0]
        df.columns = df.columns.str.strip()
        df['Papel'] = df['Papel'].str.strip().str.upper()

        if 'Div.Yield' in df.columns:
            df['Div.Yield'] = pd.to_numeric(df['Div.Yield'].astype(str).str.replace('%', '', regex=False).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), errors='coerce') / 100
        if 'P/L' in df.columns: df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce')
        if 'P/VP' in df.columns: df['P/VP'] = pd.to_numeric(df['P/VP'], errors='coerce')
        fund_data_dict = df.set_index('Papel').to_dict('index')
    except Exception as e: print(f"Erro Raspagem: {e}")

    ativos_finais = [comando] if comando != "PESQUISAR" else ativos_core # Simplificado para teste

    lote_updates = []
    try: dados_json_global = json.loads(aba_base.acell('AG1').value).get("DADOS", {})
    except: dados_json_global = {}

    agora_str = get_horario_brasilia().strftime('%d/%m/%Y %H:%M:%S')
    
    # Listas para o Relatório do WhatsApp
    relatorio_sincronizados = []
    relatorio_alertas = []

    for ticker in ativos_finais:
        try:
            linha_busca = coluna_a.index(ticker) + 1 if ticker in coluna_a else len(coluna_a) + 1
            if linha_busca <= len(todas_linhas):
                linha_atual = todas_linhas[linha_busca - 1]
                while len(linha_atual) < 32: linha_atual.append("")
                atual_preco = get_celula_float(linha_atual[1])
            else: atual_preco = 0.0

            # DADOS YAHOO
            acao = yf.Ticker(f"{ticker}.SA")
            info = acao.info
            y_preco = info.get('currentPrice', info.get('regularMarketPrice', 0)) or 0
            y_pl = info.get('trailingPE', 0) or 0
            y_pvp = info.get('priceToBook', 0) or 0
            
            # Vacina contra o Bug do DY do Yahoo (> 100% vira decimal)
            y_dy = info.get('dividendYield', 0) or 0
            if y_dy > 1: y_dy = y_dy / 100 

            # DADOS FUNDAMENTUS
            f_pl, f_pvp, f_dy, f_preco = 0.0, 0.0, 0.0, 0.0
            if ticker in fund_data_dict:
                d = fund_data_dict[ticker]
                f_pl, f_pvp = d.get('P/L', 0), d.get('P/VP', 0)
                f_dy, f_preco = d.get('Div.Yield', 0), d.get('Cotação', 0)
            
            if y_pvp < 0.5: y_pvp = f_pvp 

            # AUDITORIA
            lista_disc = []
            if calcular_discrepancia(y_pl, f_pl) > TOLERANCIA: lista_disc.append("P/L")
            if calcular_discrepancia(y_pvp, f_pvp) > TOLERANCIA: lista_disc.append("P/VP")
            if calcular_discrepancia(y_dy, f_dy) > TOLERANCIA: lista_disc.append("DY")

            if len(lista_disc) == 0:
                # É seguro! Vamos tirar a média dos valores para garantir precisão
                media_pl = round((y_pl + f_pl) / 2, 2) if f_pl > 0 else y_pl
                media_pvp = round((y_pvp + f_pvp) / 2, 2) if f_pvp > 0 else y_pvp
                media_dy = round((y_dy + f_dy) / 2, 4) if f_dy > 0 else y_dy
                
                lote_updates.append({'range': f'AF{linha_busca}', 'values': [[agora_str]]})
                lote_updates.append({'range': f'B{linha_busca}', 'values': [[y_preco]]}) # Preço de mercado (Y)
                lote_updates.append({'range': f'C{linha_busca}', 'values': [[media_dy]]})
                lote_updates.append({'range': f'E{linha_busca}', 'values': [[media_pl]]})
                lote_updates.append({'range': f'F{linha_busca}', 'values': [[media_pvp]]})
                lote_updates.append({'range': f'AH{linha_busca}', 'values': [[f"[{agora_str}] 🟢 Média Aplicada"]]})
                
                relatorio_sincronizados.append(ticker)
                # Se foi resolvido, remove da fila do painel (se estivesse lá)
                if ticker in dados_json_global: del dados_json_global[ticker]
            else:
                motivo = ", ".join(lista_disc)
                relatorio_alertas.append(f"{ticker} (Problema no: {motivo})")
                aba_disc.append_row([agora_str, ticker, f"Disc: {motivo}", f"Y:{y_pl}|F:{f_pl}"])
                
                dados_json_global[ticker] = {
                    "linha": linha_busca,
                    "status": f"🔴 Discrepância em: {motivo}",
                    "atual": {"preco": atual_preco, "pl": 0, "pvp": 0, "dy": 0},
                    "y": {"preco": y_preco, "pl": y_pl, "pvp": y_pvp, "dy": y_dy},
                    "f": {"preco": f_preco, "pl": f_pl, "pvp": f_pvp, "dy": f_dy}
                }

        except Exception as e: print(f"Erro em {ticker}: {e}")

    # Atualizações Finais
    if lote_updates: aba_base.batch_update(lote_updates)
    
    if dados_json_global: aba_base.update_acell('AG1', json.dumps({"DADOS": dados_json_global}))
    else: aba_base.update_acell('AG1', '')
    
    # Envia O WhatsApp Bonito
    if relatorio_sincronizados or relatorio_alertas:
        enviar_relatorio_whatsapp(relatorio_sincronizados, relatorio_alertas)

    return "Sucesso."

if __name__ == "__main__":
    atualizar_financeiro(None)
