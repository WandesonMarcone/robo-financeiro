import io
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz
import config
import json
from modules.utils import (
    precisa_atualizar,
    get_request_with_retry,
    converter_numero,
    eh_valido,
    formatar_pct,
)
from modules.relatorio_mercado import (
    eh_oportunidade_fii,
    montar_digest,
    obter_carteira_popular,
    rotulo_ticker,
    tickers_do_digest,
)
from bs4 import BeautifulSoup
from modules.taxonomia_fiis import classificar_fii

def buscar_dados_profundos_fii(ticker):
    """StatusInvest: segmento (JSON) e vacância/imóveis/inquilinos (HTML).

    HTTP 403 (Cloudflare) e demais não-200 são indisponibilidade: nenhum
    indicador é inventado. Ausência fica em ``None``/NaN, não em zero.
    """
    resultado = {
        "imoveis_reais": None,
        "vacancia_real": float("nan"),
        "principais_inquilinos": None,
        "segmento_real": None,
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
        elif resp_json.status_code == 403:
            print(f"StatusInvest JSON 403 (Cloudflare) para {ticker}: fonte indisponível")
        else:
            print(f"StatusInvest JSON HTTP {resp_json.status_code} para {ticker}: fonte indisponível")
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
                        valor_limpo = valor.replace('%', '').replace(',', '.').strip()
                        if valor_limpo and valor_limpo != '-':
                            resultado["vacancia_real"] = float(valor_limpo) / 100
                    elif 'imóveis' in titulo or 'ativos' in titulo:
                        if valor != '-':
                            try:
                                resultado["imoveis_reais"] = int(valor)
                            except ValueError:
                                pass

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

        elif resp_html.status_code == 403:
            print(f"StatusInvest HTML 403 (Cloudflare) para {ticker}: fonte indisponível")
        else:
            print(f"StatusInvest HTML HTTP {resp_html.status_code} para {ticker}: fonte indisponível")

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
    cat_opps = []
    
    try:
        # Sem "www": o certificado TLS do Fundamentus só cobre o domínio raiz
        # (fundamentus.com.br). Usar "www" causa SSLCertVerificationError por
        # hostname mismatch. Ver correção segura sem desativar a validação SSL.
        url = "https://fundamentus.com.br/fii_resultado.php"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = get_request_with_retry(url, headers=headers)
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]
        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')
        # converter_numero preserva o zero legítimo e transforma sentinelas ("-")
        # em NaN, permitindo distinguir ausência de dado de um valor real.
        for col in ['Cotação', 'P/VP', 'Dividend Yield', 'Liquidez', 'Vacância Média', 'Valor de Mercado', 'Qtd de imóveis']:
            if col in df.columns: df[col] = df[col].map(converter_numero)
    except Exception as e:
        print(f"⚠️ Fundamentus indisponível para FIIs: {e}")
        df = pd.DataFrame()

    dados_planilha = aba_fiis.get_all_values()
    tickers_planilha = []
    mapa_atualizacao = {}
    precos_antigos = {}
    indicadores_antigos = {}

    for row in dados_planilha[1:]: 
        if row and row[0].strip():
            t = row[0].strip().upper()
            tickers_planilha.append(t)
            try:
                if len(row) > 3 and str(row[3]).strip():
                    raw_val = str(row[3]).replace('R$', '').replace('.', '').replace(',', '.').strip()
                    precos_antigos[t] = float(raw_val) if raw_val else 0.0
                else: precos_antigos[t] = 0.0
            except: precos_antigos[t] = 0.0
            mapa_atualizacao[t] = row[17] if len(row) > 17 else ""
            indicadores_antigos[t] = {
                "pvp": converter_numero(row[5] if len(row) > 5 else None),
                "dy": converter_numero(row[6] if len(row) > 6 else None),
                "vacancia": converter_numero(row[7] if len(row) > 7 else None),
                "liquidez": converter_numero(row[12] if len(row) > 12 else None),
            } 

    carteira_popular = obter_carteira_popular("fii")
    cat_populares = [
        f for f in carteira_popular
        if f in tickers_planilha and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)
    ]
    filtro_fii = (getattr(config, "FILTROS_FIXOS", {}) or {}).get("fii") or {}
    oportunidades_gerais = []
    novatos_garimpados = []

    if not df.empty:
        oportunidades_gerais = [
            papel for papel, linha in df.iterrows()
            if eh_oportunidade_fii(
                linha.get("P/VP"),
                linha.get("Dividend Yield"),
                linha.get("Liquidez"),
                linha.get("Vacância Média"),
                filtro_fii,
            )
        ]
        oportunidades_gerais = df.loc[oportunidades_gerais].sort_values(
            by="Liquidez", ascending=False
        ).index.tolist() if oportunidades_gerais else []
        limite_opp = getattr(config, "OPORTUNIDADES_LIMITE", 8)
        cat_opps = [
            o for o in oportunidades_gerais
            if o in tickers_planilha and o not in cat_populares
            and precisa_atualizar(o, mapa_atualizacao, agora_dt, sp_tz)
        ][:limite_opp]
        novatos_garimpados = [
            fii for fii in oportunidades_gerais
            if fii not in tickers_planilha and fii not in cat_populares
        ][:3]
    else:
        cat_opps = []

    fila_total = cat_populares + cat_opps + novatos_garimpados
    print(f"DEBUG: Tamanho da fila para varredura: {len(fila_total)}")
    
    if not fila_total: 
        return [], montar_digest("", [], "fii"), aba_fiis

    batch_updates = []
    relatorio_fixas = []
    relatorio_opps = []
    relatorio_fixas_opps = []
    itens_individuais = []
    proxima_linha_vazia = len(dados_planilha) + 1 

    for ticker in fila_total:
        try:
            yf_info = yf.Ticker(f"{ticker}.SA").info or {}
            preco_yf = converter_numero(yf_info.get('currentPrice'))
            if not eh_valido(preco_yf):
                preco_yf = converter_numero(yf_info.get('regularMarketPrice'))
            # Preço zero não é cota válida: trata como ausência.
            if not (eh_valido(preco_yf) and preco_yf > 0):
                preco_yf = None

            fundamentus_ok = (not df.empty) and (ticker in df.index)
            f = {}
            if fundamentus_ok:
                f = df.loc[ticker]
                if isinstance(f, pd.DataFrame): f = f.iloc[0]

            def _fund(col):
                # Só confia no Fundamentus quando a linha do ticker existe; caso
                # contrário devolve NaN para que o valor anterior seja preservado.
                return converter_numero(f.get(col)) if fundamentus_ok else float('nan')

            preco_fundamentus = _fund('Cotação')
            if not (eh_valido(preco_fundamentus) and preco_fundamentus > 0):
                preco_fundamentus = None
            preco = preco_yf if preco_yf is not None else preco_fundamentus

            pvp = _fund('P/VP')
            if not (eh_valido(pvp) and pvp > 0):
                pvp = float('nan')  # P/VP zero/nulo indica ausência, não um valor.
            dy = _fund('Dividend Yield')            # DY 0 é legítimo (fundo sem distribuição)
            liquidez = _fund('Liquidez')            # Liquidez 0 é legítima
            valor_mercado = _fund('Valor de Mercado')
            qtd_imoveis = _fund('Qtd de imóveis')   # 0 imóveis é legítimo
            vacancia_fund = _fund('Vacância Média') # Vacância 0 é legítima
            segmento_fund = f.get('Segmento') if fundamentus_ok else None

            # API JSON / HTML (StatusInvest)
            dados_profundos = buscar_dados_profundos_fii(ticker)
            segmento_status = dados_profundos.get("segmento_real")
            vacancia_status = dados_profundos.get("vacancia_real")
            imoveis_status = dados_profundos.get("imoveis_reais")
            inquilinos_status = dados_profundos.get("principais_inquilinos")

            if segmento_status:
                setor = segmento_status
            elif isinstance(segmento_fund, str) and segmento_fund.strip() not in ('', '-'):
                setor = segmento_fund.strip()
            else:
                setor = None

            ticker_novo = ticker not in tickers_planilha
            if setor or ticker_novo:
                tipo, segmento, emoji = classificar_fii(setor or "", ticker)
            else:
                tipo, segmento, emoji = None, None, "🏢"

            if eh_valido(vacancia_status):
                vacancia = vacancia_status
            else:
                vacancia = vacancia_fund

            if eh_valido(imoveis_status):
                qtd_imoveis = imoveis_status

            if (isinstance(inquilinos_status, str) and inquilinos_status.strip()):
                inquilinos_planilha = inquilinos_status
            else:
                inquilinos_planilha = None

            # Indicadores derivados: só calculados quando as entradas são válidas,
            # evitando gravar zeros/lixos provenientes de falha de fonte.
            vpa = (preco / pvp) if (eh_valido(preco) and eh_valido(pvp) and pvp > 0) else float('nan')
            numero_cotas = (valor_mercado / preco) if (eh_valido(valor_mercado) and eh_valido(preco) and preco > 0) else float('nan')
            media_div_mensal = (preco * dy) / 12 if (eh_valido(preco) and eh_valido(dy)) else float('nan')
            lucro_12m = valor_mercado * dy if (eh_valido(valor_mercado) and eh_valido(dy)) else float('nan')

            if ticker in tickers_planilha:
                linha_idx = tickers_planilha.index(ticker) + 2
            else:
                linha_idx = proxima_linha_vazia

            # =========================================================================
            # 🗺️ GRAVAÇÃO CÉLULA A CÉLULA (A até R): somente indicadores válidos são
            # enviados. Campos inválidos são OMITIDOS, preservando o dado já existente.
            # =========================================================================
            valores = {}
            if ticker_novo:
                valores['A'] = ticker                 # Cria a linha do novo fundo
            if tipo is not None: valores['B'] = tipo
            if segmento is not None:
                valores['C'] = segmento
            elif setor is not None:
                valores['C'] = setor
            if eh_valido(preco): valores['D'] = preco
            if eh_valido(numero_cotas): valores['E'] = numero_cotas
            if eh_valido(pvp): valores['F'] = pvp
            if eh_valido(dy): valores['G'] = dy
            if eh_valido(vacancia): valores['H'] = vacancia
            if eh_valido(qtd_imoveis): valores['I'] = qtd_imoveis
            if inquilinos_planilha: valores['J'] = inquilinos_planilha
            if ticker_novo:
                valores['K'] = "Pendente de IA"
                valores['L'] = "Pendente de IA"
            if eh_valido(liquidez): valores['M'] = liquidez
            if eh_valido(valor_mercado): valores['N'] = valor_mercado
            if eh_valido(vpa): valores['O'] = vpa
            if eh_valido(lucro_12m): valores['P'] = lucro_12m
            if eh_valido(media_div_mensal): valores['Q'] = media_div_mensal
            # Só carimba a atualização quando o Fundamentus respondeu de fato.
            # Assim uma falha parcial não marca dados antigos como recentes.
            if fundamentus_ok: valores['R'] = f"OK {agora_sp}"

            for coluna, valor in valores.items():
                batch_updates.append({'range': f'{coluna}{linha_idx}', 'values': [[valor]]})

            if ticker_novo:
                proxima_linha_vazia += 1

            preco_velho = precos_antigos.get(ticker, 0.0)
            preco_exib = preco if eh_valido(preco) else preco_velho
            tipo_exib = tipo if tipo else "N/D"
            pvp_txt = f"{pvp:.2f}" if eh_valido(pvp) else "N/D"
            dy_txt = formatar_pct(dy)
            icone_variacao = "📈" if preco_exib > preco_velho else ("📉" if preco_exib < preco_velho else "➖")
            txt_vacancia = f" | 🏚️ Vacância: {formatar_pct(vacancia)}" if (tipo == "Tijolo" and eh_valido(vacancia)) else ""

            rotulo = rotulo_ticker(ticker, "fii")
            texto_ind = (
                f"{emoji} *{rotulo}* ({tipo_exib})\n"
                f"   R$ {preco_velho:.2f} ➔ R$ {preco_exib:.2f} {icone_variacao}\n"
                f"   P/VP: {pvp_txt} | DY: {dy_txt}{txt_vacancia}"
            )
            itens_individuais.append(
                {
                    "ticker": ticker,
                    "texto": f"📌 *{ticker}*\nEsta e a situacao atual:\n{texto_ind}",
                }
            )
            if ticker in novatos_garimpados:
                relatorio_opps.append(f"{emoji} *{rotulo}* ({tipo_exib})\n   R$ {preco_exib:.2f}\n   P/VP: {pvp_txt} | DY: {dy_txt}{txt_vacancia}")
            elif ticker in carteira_popular:
                texto_ativo = f"{emoji} *{rotulo}* ({tipo_exib})\n   R$ {preco_velho:.2f} ➔ R$ {preco_exib:.2f} {icone_variacao}\n   P/VP: {pvp_txt} | DY: {dy_txt}{txt_vacancia}"
                ant = indicadores_antigos.get(ticker) or {}
                ja_estava_barato = eh_oportunidade_fii(
                    ant.get("pvp"),
                    ant.get("dy"),
                    ant.get("liquidez"),
                    ant.get("vacancia"),
                    filtro_fii,
                )
                if ticker in oportunidades_gerais and not ja_estava_barato:
                    relatorio_fixas_opps.append(f"🚨 *{rotulo} ENTROU EM DESCONTO!* 🚨\n   {texto_ativo}")
                else:
                    relatorio_fixas.append(texto_ativo)
            elif ticker in oportunidades_gerais:
                relatorio_opps.append(f"{emoji} *{rotulo}* ({tipo_exib})\n   R$ {preco_exib:.2f}\n   P/VP: {pvp_txt} | DY: {dy_txt}{txt_vacancia}")

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
    if relatorio_fixas: msg_blocos.append("📌 *CARTEIRA POPULAR:*\n" + "\n\n".join(relatorio_fixas))
    if relatorio_opps: msg_blocos.append("🎯 *TOP OPORTUNIDADES:*\n" + "\n\n".join(relatorio_opps))
    tickers_digest = tickers_do_digest(fila_total)
    msg_out = "\n\n➖➖➖➖➖➖➖➖➖➖\n\n".join(msg_blocos) if batch_updates else ""

    return batch_updates, montar_digest(msg_out, tickers_digest, "fii", itens_individuais), aba_fiis
