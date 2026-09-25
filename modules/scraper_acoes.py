import io
import random
from datetime import datetime

import pandas as pd
import yfinance as yf

import config
from config import MAPA_SETORES_B3
from modules.utils import celula_planilha, formatar, get_request_with_retry, precisa_atualizar
from pipeline_dados.matriz_aplicabilidade import blank_se_nao_aplicavel
from pipeline_dados.numerico import derivar_divisao, parsear_numero, parsear_percentual, primeiro_numero

LIMIAR_ROE_OPORTUNIDADE = 0.08


def classificar_setor_por_mapa(ticker):
    """
    Varre o mapa fixo do config.py e devolve (Macro_Setor, Sub_Setor).
    Se a ação não estiver no mapa, devolve "Outros".
    """
    ticker_limpo = ticker.strip().upper()

    for macro, subsetores in MAPA_SETORES_B3.items():
        for sub, lista_tickers in subsetores.items():
            if ticker_limpo in lista_tickers:
                return macro, sub

    # Se a ação não estiver mapeada no config.py
    return "Outros", "Não Classificado"


def limpar_porcentagem_df(val):
    """Percentual do Fundamentus → fração só com ``%``. Erro/ausência → None; 0% → 0.0."""
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(val, str) and "%" in val:
        return parsear_percentual(val)
    return parsear_numero(val)


def _fmt_num(valor, casas=2):
    if valor is None:
        return "N/D"
    return f"{valor:.{casas}f}"


def _fmt_pct(valor):
    if valor is None:
        return "N/D"
    return f"{valor * 100:.1f}%"


def priorizar_cagr_cvm(valor_cvm, valor_fallback):
    """CVM valido tem prioridade; ausencia/invalido recai no fallback (Fundamentus)."""
    numero = parsear_numero(valor_cvm)
    if numero is None:
        return parsear_numero(valor_fallback)
    return numero


def cagr_cvm_para_tickers(tickers):
    """Le CAGR CVM ja persistido. Falha de banco nao interrompe o fluxo legado."""
    try:
        from pipeline_dados.indicadores_cvm_acoes import mapa_cagr_cvm_producao
        from services.db import sessao_db

        with sessao_db() as session:
            return mapa_cagr_cvm_producao(session, tickers)
    except Exception:
        return {}


def montar_linha_acao(
    setor, preco, dy, qtd_acoes, pl, pvp, p_ativo, marg_bruta, marg_ebit,
    marg_liquida, p_ebit, ev_ebit, div_liq_ebit, div_liq_patrimonio, psr,
    p_cap_giro, p_at_circ_liq, liq_corrente, roe, roa, roic, cagr_rec_5a,
    liq_media, vpa, lpa, peg_ratio, valor_mercado, agora_sp,
    cagr_lucro_5a=None,
    ticker=None,
):
    """Linha B..AG do BD_Acoes. None vira celula vazia; slots reservados ficam vazios.

    NAO_APLICAVEL (matriz F.1) vira celula vazia, nunca 0.
    """
    vazio = ""

    def _cel(indicador, valor):
        return celula_planilha(blank_se_nao_aplicavel(indicador, valor, ticker=ticker))

    return [
        setor,
        _cel("preco", preco),
        _cel("dy", dy),
        celula_planilha(qtd_acoes),
        _cel("pl", pl),
        _cel("pvp", pvp),
        _cel("p_ativo", p_ativo),
        _cel("marg_bruta", marg_bruta),
        _cel("marg_ebit", marg_ebit),
        _cel("marg_liquida", marg_liquida),
        _cel("p_ebit", p_ebit),
        _cel("ev_ebit", ev_ebit),
        _cel("div_liq_ebit", div_liq_ebit),
        _cel("div_liq_patrimonio", div_liq_patrimonio),
        _cel("psr", psr),
        _cel("p_cap_giro", p_cap_giro),
        _cel("p_at_circ_liq", p_at_circ_liq),
        _cel("liq_corrente", liq_corrente),
        _cel("roe", roe),
        _cel("roa", roa),
        _cel("roic", roic),
        vazio,
        vazio,
        vazio,
        _cel("cagr_rec_5a", cagr_rec_5a),
        _cel("cagr_lucro_5a", cagr_lucro_5a),
        _cel("liq_media", liq_media),
        _cel("vpa", vpa),
        _cel("lpa", lpa),
        _cel("peg_ratio", peg_ratio),
        _cel("valor_mercado", valor_mercado),
        f"{agora_sp}",
    ]


def derivar_pl(pl_fonte, preco, lpa):
    """P/L da fonte; se ausente, preco/lpa. Dependência ausente ou lpa=0 → None."""
    pl = parsear_numero(pl_fonte)
    if pl is not None:
        return pl
    return derivar_divisao(preco, lpa)


def derivar_pvp(pvp_fonte, preco, vpa):
    """P/VP da fonte; se ausente, preco/vpa. Dependência ausente ou vpa=0 → None."""
    pvp = parsear_numero(pvp_fonte)
    if pvp is not None:
        return pvp
    return derivar_divisao(preco, vpa)


def _bloco_telegram_acao(ticker, preco, preco_velho, pl, pvp, roe):
    if preco_velho is not None and preco is not None and preco_velho != preco:
        linha_preco = f"   R$ {_fmt_num(preco_velho)} -> R$ {_fmt_num(preco)}"
    else:
        linha_preco = f"   R$ {_fmt_num(preco)}"
    return (
        f"*{ticker}*\n"
        f"{linha_preco}\n"
        f"   P/L: {_fmt_num(pl, 1)} | P/VP: {_fmt_num(pvp)} | ROE: {_fmt_pct(roe)}"
    )


def rodar_garimpo_acoes(planilha, agora_dt, agora_sp, sp_tz):
    print("📈 [1/5] Iniciando auditoria completa de Ações...")
    aba_base = planilha.worksheet("BD_Acoes")

    try:
        url = "https://www.fundamentus.com.br/resultado.php"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
        }
        response = get_request_with_retry(url, headers=headers)

        # 🟢 ALTERAÇÃO 1: Adicionado decimal e thousands para ler formato BR
        df = pd.read_html(io.StringIO(response.text), decimal=',', thousands='.')[0]

        df['Papel'] = df['Papel'].str.strip().str.upper()
        df = df.set_index('Papel')

        for col_perc in ['Div.Yield', 'ROE', 'Mrg Bruta', 'Mrg Ebit', 'Mrg. Líq.', 'Cresc. Rec.5a', 'ROIC']:
            if col_perc in df.columns:
                df[col_perc] = pd.to_numeric(df[col_perc].apply(limpar_porcentagem_df), errors="coerce")

        for col in ['P/L', 'P/VP', 'Liq.2meses']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].apply(formatar), errors="coerce")

    except Exception as e:
        print(f"⚠️ Fundamentus indisponível: {e}. Alternando para Yahoo.")
        df = pd.DataFrame()

    dados_planilha = aba_base.get_all_values()
    # Linha duplicada no original removida (dados_planilha = aba_base.get_all_values())
    todas_originais, mapa_atualizacao, precos_antigos = [], {}, {}

    for row in dados_planilha[1:]:
        if row and row[0].strip() and not row[0].replace(',', '').replace('.', '').isnumeric():
            t = row[0].strip().upper()
            todas_originais.append(t)

            if len(row) > 2:
                precos_antigos[t] = parsear_numero(
                    str(row[2]).replace("R$", "").replace(".", "").replace(",", ".").strip()
                )
            else:
                precos_antigos[t] = None

            # Mapeamento da Coluna AG (índice 32)
            mapa_atualizacao[t] = row[32] if len(row) > 32 else ""

    todas = list(todas_originais)
    cat_fixas = [f for f in config.FIXAS_ACOES if f in todas and precisa_atualizar(f, mapa_atualizacao, agora_dt, sp_tz)]

    opps_brutas, cat_novatas = [], []
    if not df.empty:
        opps_brutas = df[(df['P/L'] > 0) & (df['P/L'] < 12) & (df['P/VP'] < 1.5) & (df['ROE'] >= LIMIAR_ROE_OPORTUNIDADE)].index.tolist()
        cat_opps = [o for o in opps_brutas if o in todas_originais and o not in cat_fixas and precisa_atualizar(o, mapa_atualizacao, agora_dt, sp_tz)][:5]
        # Adequação dos filtros matemáticos pois as porcentagens viraram decimais puros (Ex: 6.0% agora é 0.06)
        candidatas = df[(df['P/L']>=2)&(df['P/L']<=15)&(df['P/VP']>=0.2)&(df['P/VP']<=1.5)&(df['Div.Yield']>=0.06)&(df['ROE']>=0.10)].index.tolist()
        cat_novatas = [c for c in candidatas if c not in todas][:2]
        todas.extend(cat_novatas)
    else:
        cat_opps = []

    usadas = set(cat_fixas + cat_opps + cat_novatas)
    precisam_urgente = [t for t in todas_originais if t not in usadas and precisa_atualizar(t, mapa_atualizacao, agora_dt, sp_tz)]
    cat_aleatorias = random.sample(precisam_urgente, 3) if len(precisam_urgente) >= 3 else precisam_urgente

    fila = cat_fixas + cat_opps + cat_aleatorias + cat_novatas
    if not fila: return [], "", aba_base

    print(f"-> Fila de Ações: {fila}")
    cagr_cvm_por_ticker = cagr_cvm_para_tickers(fila)

    batch_updates = []
    relatorio_fixas = []
    relatorio_opps = []
    relatorio_novatas = []
    relatorio_atualizados = []
    relatorio_fixas_opps = []

    for ticker in fila:
        linha_idx = todas.index(ticker) + 2
        try:
            # 🟢 ALTERAÇÃO 3: Inserção do Sufixo da B3 para o Yahoo Finance (.SA)
            yf_info = yf.Ticker(f"{ticker}.SA").info

            # 🔴 A MÁGICA ACONTECE AQUI: Ignoramos o Yahoo Finance e usamos o nosso Mapa Fixo!
            macro_setor, sub_setor = classificar_setor_por_mapa(ticker)

            # A variável 'setor' agora recebe o nome perfeito e em português (Ex: "Materiais Básicos")
            setor = macro_setor

            # Se a sua planilha também tiver uma coluna para Subsetor no futuro,
            # a variável 'sub_setor' já está pronta para ser enviada (Ex: "Mineração").

            preco_yf = primeiro_numero(yf_info.get("currentPrice"), yf_info.get("regularMarketPrice"))
            f = df.loc[ticker] if (not df.empty and ticker in df.index) else {}
            preco = primeiro_numero(preco_yf, formatar(f.get("Cotação")))

            lpa_yf = formatar(yf_info.get("trailingEps"))
            vpa_yf = formatar(yf_info.get("bookValue"))

            pl = derivar_pl(f.get("P/L"), preco, lpa_yf)
            pvp = derivar_pvp(f.get("P/VP"), preco, vpa_yf)
            roe = formatar(f.get("ROE"))
            dy = formatar(f.get("Div.Yield"))
            div_liq_patrimonio = formatar(f.get("Dív.Líq/ Patrim."))
            cagr_cvm = cagr_cvm_por_ticker.get(ticker, {})
            cagr_rec_5a = priorizar_cagr_cvm(
                cagr_cvm.get("cagr_rec_5a"), formatar(f.get("Cresc. Rec.5a")),
            )
            cagr_lucro_5a = parsear_numero(cagr_cvm.get("cagr_lucro_5a"))

            row_base = montar_linha_acao(
                setor, preco, dy, formatar(yf_info.get("sharesOutstanding")),
                pl, pvp, formatar(f.get("P/Ativo")), formatar(f.get("Mrg Bruta")),
                formatar(f.get("Mrg Ebit")), formatar(f.get("Mrg. Líq.")),
                formatar(f.get("P/EBIT")), formatar(f.get("EV/EBIT")),
                None, div_liq_patrimonio, formatar(f.get("PSR")),
                formatar(f.get("P/Cap.Giro")), formatar(f.get("P/Ativ Circ.Liq")),
                formatar(f.get("Liq. Corr.")), roe, formatar(yf_info.get("returnOnAssets")),
                formatar(f.get("ROIC")), cagr_rec_5a,
                formatar(f.get("Liq.2meses")), vpa_yf, lpa_yf,
                formatar(yf_info.get("trailingPegRatio")), formatar(yf_info.get("marketCap")),
                agora_sp, cagr_lucro_5a=cagr_lucro_5a, ticker=ticker,
            )

            if ticker in cat_novatas:
                batch_updates.append({"range": f"A{linha_idx}:AG{linha_idx}", "values": [[ticker] + row_base]})
            else:
                batch_updates.append({"range": f"B{linha_idx}:AG{linha_idx}", "values": [row_base]})

            p_v = precos_antigos.get(ticker, preco)
            txt = _bloco_telegram_acao(ticker, preco, p_v, pl, pvp, roe)
            if ticker in config.FIXAS_ACOES:
                if ticker in opps_brutas:
                    relatorio_fixas_opps.append(f"*ALERTA* {ticker} EM OPORTUNIDADE!\n{txt}")
                else:
                    relatorio_fixas.append(txt)
            elif ticker in opps_brutas:
                relatorio_opps.append(txt)
            elif ticker in cat_novatas:
                relatorio_novatas.append(txt)
            else:
                relatorio_atualizados.append(txt)

            print(f"   ✅ [OK] {ticker} mapeado e processado.")
        except Exception as e:
            print(f"   ❌ [ERRO] Falha {ticker}: {e}")
            try:
                aba_logs = planilha.worksheet("BD_Logs")
                aba_logs.append_row([str(datetime.now(sp_tz)), f"Ações: {ticker}", str(e)])
            except Exception as log_error:
                print(f"   ⚠️ Não foi possível gravar o log: {log_error}")

            # --------------------------

    # --- MONTAGEM MODULAR COM SEPARADOR ---
    msg_blocos = ["🤖 *MOVIMENTAÇÃO DE AÇÕES* 🤖"]
    if relatorio_fixas_opps: msg_blocos.append("🏆 *ALERTA VIP (Fixas em Oportunidade):*\n" + "\n\n".join(relatorio_fixas_opps))
    if relatorio_fixas: msg_blocos.append("📌 *CARTEIRA FIXA:*\n" + "\n\n".join(relatorio_fixas))
    if relatorio_opps: msg_blocos.append("🎯 *OPORTUNIDADES:*\n" + "\n\n".join(relatorio_opps))
    if relatorio_novatas: msg_blocos.append("🌟 *GARIMPADAS:*\n" + "\n\n".join(relatorio_novatas))
    if relatorio_atualizados: msg_blocos.append("🔄 *OUTRAS ATUALIZADAS:*\n" + "\n\n".join(relatorio_atualizados))

    msg_out = "\n\n➖➖➖➖➖➖➖➖➖➖\n\n".join(msg_blocos) if batch_updates else ""

    return batch_updates, msg_out, aba_base
