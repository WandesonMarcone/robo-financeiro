import io
import random
from datetime import datetime

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

import config
from modules.utils import celula_planilha, formatar, get_request_with_retry, precisa_atualizar
from pipeline_dados.numerico import (
    derivar_divisao,
    derivar_produto,
    parsear_numero,
    parsear_percentual,
    primeiro_numero,
)


def interpretar_vacancia_html(valor):
    """Vacância do HTML: só fração com ``%``. Sem ``%``, não inventa escala."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto or texto in ("-", "--", "—"):
        return None
    return parsear_percentual(texto)


def classificar_fii_e_emoji(setor, ticker):
    """
    Classifica automaticamente o FII baseado no setor REAL extraído do JSON.
    """
    s = str(setor).upper()
    t = str(ticker).upper()

    # Exceções blindadas para fundos que os sites classificam errado
    if t in ["MXRF11"]: return "Híbrido", "🧩"
    if t in ["GARE11"]: return "Tijolo", "🧱"

    # Classificação baseada no JSON de portfólio
    if any(x in s for x in ["TÍTULOS", "PAPEL", "RECEBÍVEL", "VALORES MOBILIÁRIOS", "CRI", "LCI", "CRA", "CERTIFICADOS"]):
        return "Papel", "📜"
    if any(x in s for x in ["FUNDO DE FUNDOS", "FOF", "COTAS DE FUNDOS"]):
        return "FOF", "🔄"
    if any(x in s for x in ["HÍBRIDO", "MISTO"]):
        return "Híbrido", "🧩"

    return "Tijolo", "🧱"


def _fmt_num(valor, casas=2):
    if valor is None:
        return "N/D"
    return f"{valor:.{casas}f}"


def _fmt_pct(valor):
    if valor is None:
        return "N/D"
    return f"{valor * 100:.1f}%"


def _bloco_telegram_fii(ticker, tipo, emoji, preco, preco_velho, pvp, dy, txt_vacancia):
    if preco_velho is not None and preco is not None and preco_velho != preco:
        linha_preco = f"   R$ {_fmt_num(preco_velho)} -> R$ {_fmt_num(preco)}"
    else:
        linha_preco = f"   R$ {_fmt_num(preco)}"
    return (
        f"{emoji} *{ticker}* ({tipo})\n"
        f"{linha_preco}\n"
        f"   P/VP: {_fmt_num(pvp)} | DY: {_fmt_pct(dy)}{txt_vacancia}"
    )


def montar_linha_fii(
    ticker, tipo, setor, preco, numero_cotas, pvp, dy, vacancia,
    qtd_imoveis, inquilinos, liquidez, valor_mercado, vpa, lucro_12m,
    media_div_mensal, agora_sp,
):
    """Linha A..R do BD_FIIs. None vira celula vazia; zero real permanece 0.0."""
    return [
        ticker,
        tipo,
        setor,
        celula_planilha(preco),
        celula_planilha(numero_cotas),
        celula_planilha(pvp),
        celula_planilha(dy),
        celula_planilha(vacancia),
        celula_planilha(qtd_imoveis),
        inquilinos,
        "Pendente de IA",
        "Pendente de IA",
        celula_planilha(liquidez),
        celula_planilha(valor_mercado),
        celula_planilha(vpa),
        celula_planilha(lucro_12m),
        celula_planilha(media_div_mensal),
        f"{agora_sp}",
    ]


def buscar_dados_profundos_fii(ticker):
    """
    Busca 1: O Setor e Porcentagem exata via API JSON (StatusInvest)
    Busca 2: A Vacância, Imóveis e Inquilinos via HTML
    """
    resultado = {
        "imoveis_reais": None,
        "vacancia_real": None,
        "principais_inquilinos": "Não informado / Não aplicável",
        "segmento_real": None
    }

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    # ==========================================
    # 1. EXTRAÇÃO DO JSON (A Mágica das Porcentagens)
    # ==========================================
    try:
        url_json = f"https://statusinvest.com.br/fii/portfolio-segment-chart?ticker={ticker.lower()}"
        headers_json = headers.copy()
        headers_json['X-Requested-With'] = 'XMLHttpRequest'

        resp_json = requests.get(url_json, headers=headers_json, timeout=10)
        if resp_json.status_code == 200:
            dados_json = resp_json.json()
            if dados_json and isinstance(dados_json, list):
                # Monta o texto: "CRI (70.5%) / Cotas de FIIs (29.5%)"
                lista_seg = [f"{d.get('name')} ({d.get('value')}%)" for d in dados_json if 'name' in d and d.get('value') > 0]
                if lista_seg:
                    resultado["segmento_real"] = " / ".join(lista_seg)
    except Exception as e:
        print(f"Aviso JSON para {ticker}: {e}")

    # ==========================================
    # 2. EXTRAÇÃO HTML (Vacância, Imóveis, Inquilinos)
    # ==========================================
    try:
        url_html = f"https://statusinvest.com.br/fii/{ticker.lower()}"
        resp_html = requests.get(url_html, headers=headers, timeout=10)

        if resp_html.status_code == 200:
            soup = BeautifulSoup(resp_html.text, 'html.parser')

            # Tenta achar o segmento básico no HTML caso o JSON seja vazio (Fundos muito novos)
            if not resultado["segmento_real"]:
                cards_info = soup.find_all('div', class_='info')
                for card in cards_info:
                    titulo = card.find('h3', class_='title')
                    valor = card.find('strong', class_='value')
                    if titulo and valor and 'segmento' in titulo.text.lower():
                        if valor.text.strip() != '-':
                            resultado["segmento_real"] = valor.text.strip()

            # Busca Vacância e Imóveis
            cards_info = soup.find_all('div', class_='info')
            for card in cards_info:
                titulo_tag = card.find('h3', class_='title')
                valor_tag = card.find('strong', class_='value')
                if titulo_tag and valor_tag:
                    titulo = titulo_tag.text.strip().lower()
                    valor = valor_tag.text.strip()

                    if 'vacância' in titulo:
                        vacancia = interpretar_vacancia_html(valor)
                        if vacancia is not None:
                            resultado["vacancia_real"] = vacancia
                    elif 'imóveis' in titulo or 'ativos' in titulo:
                        imoveis = parsear_numero(valor)
                        if imoveis is not None:
                            resultado["imoveis_reais"] = int(imoveis)

            # Busca Inquilinos
            tabelas = soup.find_all('table')
            for tabela in tabelas:
                header = tabela.find('thead')
                if header:
                    texto_header = header.text.lower()
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
                            resultado["principais_inquilinos"] = ", ".join(lista_inquilinos)
                        break

    except Exception as e:
        print(f"Erro HTML para {ticker}: {e}")

    return resultado

def rodar_garimpo_fiis(planilha, agora_dt, agora_sp, sp_tz):
    print("🏢 [1/5] Iniciando varredura com motor JSON ativado...")
    aba_fiis = planilha.worksheet("BD_FIIs")

    # 1. INICIALIZAÇÃO BLINDADA (Evita o UnboundLocalError)
    fila_total = []
    oportunidades_gerais = []
    novatos_garimpados = []

    try:
        url = "https://www.fundamentus.com.br/fii_resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = get_request_with_retry(url, headers=headers)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        for col in ['Cotação', 'P/VP', 'Dividend Yield', 'Liquidez', 'Vacância Média', 'Valor de Mercado', 'Qtd de imóveis']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].apply(formatar), errors="coerce")
    except Exception:
        df = pd.DataFrame()

    dados_planilha = aba_fiis.get_all_values()
    tickers_planilha = []
    mapa_atualizacao = {}
    precos_antigos = {}

    for row in dados_planilha[1:]:
        if row and row[0].strip():
            t = row[0].strip().upper()
            tickers_planilha.append(t)
            if len(row) > 3:
                precos_antigos[t] = parsear_numero(
                    str(row[3]).replace("R$", "").replace(".", "").replace(",", ".").strip()
                )
            else:
                precos_antigos[t] = None
            mapa_atualizacao[t] = row[17] if len(row) > 17 else ""

    cat_fixas = [f for f in config.FIXAS_FIIS if f in tickers_planilha and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]

    if not df.empty:
        df_cacador = df[
            (df['P/VP'] >= 0.85) & (df['P/VP'] <= 1.01) &
            (df['Dividend Yield'] >= 0.095) & (df['Liquidez'] >= 5000000) &
            (df['Vacância Média'] <= 0.10)
        ]
        oportunidades_gerais = df_cacador.sort_values(by='Dividend Yield', ascending=False).index.tolist()
        novatos_garimpados = [fii for fii in oportunidades_gerais if fii not in tickers_planilha and fii not in cat_fixas][:3]

    usadas = set(cat_fixas + novatos_garimpados)
    precisam_urgente = [t for t in tickers_planilha if t not in usadas and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)]
    cat_desatualizadas = random.sample(precisam_urgente, 2) if len(precisam_urgente) >= 2 else precisam_urgente

    # 2. DEFINIÇÃO DA FILA ANTES DE QUALQUER PRINT
    fila_total = cat_fixas + novatos_garimpados + cat_desatualizadas
    print(f"DEBUG: Tamanho da fila para varredura: {len(fila_total)}")

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
            preco_yf = primeiro_numero(yf_info.get("currentPrice"), yf_info.get("regularMarketPrice"))

            if not df.empty and ticker in df.index:
                f = df.loc[ticker]
                if isinstance(f, pd.DataFrame):
                    f = f.iloc[0]
            else:
                f = {}

            preco_fundamentus = formatar(f.get("Cotação"))
            preco = primeiro_numero(preco_yf, preco_fundamentus)

            pvp = formatar(f.get("P/VP"))
            dy = formatar(f.get("Dividend Yield"))
            liquidez = formatar(f.get("Liquidez"))
            valor_mercado = formatar(f.get("Valor de Mercado"))

            dados_profundos = buscar_dados_profundos_fii(ticker)
            setor = dados_profundos["segmento_real"] or f.get("Segmento", "N/D")
            vacancia = primeiro_numero(dados_profundos["vacancia_real"], formatar(f.get("Vacância Média")))
            qtd_imoveis = primeiro_numero(dados_profundos["imoveis_reais"], formatar(f.get("Qtd de imóveis")))
            if qtd_imoveis is not None:
                qtd_imoveis = int(qtd_imoveis)
            inquilinos_planilha = dados_profundos["principais_inquilinos"]

            tipo, emoji = classificar_fii_e_emoji(setor, ticker)

            vpa = derivar_divisao(preco, pvp)
            numero_cotas = derivar_divisao(valor_mercado, preco)
            media_div_mensal = derivar_divisao(derivar_produto(preco, dy), 12)
            lucro_12m = derivar_produto(valor_mercado, dy)

            row_update_completo = montar_linha_fii(
                ticker, tipo, setor, preco, numero_cotas, pvp, dy, vacancia,
                qtd_imoveis, inquilinos_planilha, liquidez, valor_mercado,
                vpa, lucro_12m, media_div_mensal, agora_sp,
            )

            row_update_parcial = row_update_completo[1:]

            if ticker in tickers_planilha:
                linha_idx = tickers_planilha.index(ticker) + 2
                batch_updates.append({'range': f'B{linha_idx}:R{linha_idx}', 'values': [row_update_parcial]})
            else:
                batch_updates.append({'range': f'A{proxima_linha_vazia}:R{proxima_linha_vazia}', 'values': [row_update_completo]})
                proxima_linha_vazia += 1

            preco_velho = precos_antigos.get(ticker, preco)
            txt_vacancia = (
                f" | Vacancia: {_fmt_pct(vacancia)}" if tipo == "Tijolo" and vacancia is not None else ""
            )
            bloco = _bloco_telegram_fii(ticker, tipo, emoji, preco, preco_velho, pvp, dy, txt_vacancia)

            if ticker in novatos_garimpados:
                relatorio_opps.append(bloco)
            elif ticker in config.FIXAS_FIIS:
                if ticker in oportunidades_gerais:
                    relatorio_fixas_opps.append(f"*ALERTA* {ticker} ENTROU EM DESCONTO!\n   {bloco}")
                else:
                    relatorio_fixas.append(bloco)
            else:
                relatorio_atualizados.append(bloco)

            print(f"   ✅ [OK] {ticker} mapeado e processado.")
        except Exception as e:
            print(f"   ❌ [ERRO] Falha {ticker}: {e}")
            try:
                aba_logs = planilha.worksheet("BD_Logs")
                aba_logs.append_row([str(datetime.now(sp_tz)), f"Ações: {ticker}", str(e)])
            except Exception as log_error:
                print(f"   ⚠️ Não foi possível gravar o log: {log_error}")

    msg_blocos = ["🏢 *MOVIMENTAÇÃO DE FIIs* 🏢"]
    if relatorio_fixas_opps: msg_blocos.append("🏆 *ALERTA VIP:*\n" + "\n\n".join(relatorio_fixas_opps))
    if relatorio_fixas: msg_blocos.append("📌 *SUA CARTEIRA FIXA:*\n" + "\n\n".join(relatorio_fixas))
    if relatorio_opps: msg_blocos.append("🎯 *TOP OPORTUNIDADES:*\n" + "\n\n".join(relatorio_opps))
    if relatorio_atualizados: msg_blocos.append("🔄 *OUTRAS ATUALIZAÇÕES:*\n" + "\n\n".join(relatorio_atualizados))
    msg_out = "\n\n➖➖➖➖➖➖➖➖➖➖\n\n".join(msg_blocos) if batch_updates else ""

    return batch_updates, msg_out, aba_fiis
