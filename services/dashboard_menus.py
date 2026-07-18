from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.loader import bot
from services.planilhas import buscar_dados_planilha_com_cache, buscar_ativo_na_planilha
from services.logo_service import obter_link_logo
from modules.GoogleDriveManager import GoogleDriveManager

# Instancia o gerenciador de arquivos uma vez
drive_manager = GoogleDriveManager()

def converter_numero(valor_string):
    """Limpa textos como 'R$ 1.050,50' ou '8,5%' da planilha e transforma em número puro"""
    try:
        texto = str(valor_string).replace('R$', '').replace('%', '').strip()
        if not texto or texto == '-': return 0.0
        if ',' in texto and '.' in texto:
            texto = texto.replace('.', '')
        texto = texto.replace(',', '.')
        return float(texto)
    except:
        return 0.0

def buscar_oportunidades(tipo):
    """Vasculha a planilha usando regras fixas hardcoded"""
    is_fii = (tipo == 'fii')
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"

    # 🚨 REGRAS FIXAS DEFINIDAS AQUI 🚨
    FILTROS_FIXOS = {
        "fii": {"pvp_min": 0.50, "pvp_max": 1.15, "dy_min": 0.08},
        "acao": {"pl_min": 2.0, "pl_max": 15.0, "pvp_min": 0.50, "pvp_max": 2.50, "dy_min": 0.06, "roe_min": 0.10}
    }

    filtro_atual = FILTROS_FIXOS[tipo]

    try:
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        aba = planilha.worksheet(nome_aba)
        matriz = aba.get_all_values()

        oportunidades = []

        for linha in matriz[1:]:
            try:
                ticker = linha[0].strip()
                if not ticker: continue

                if is_fii:
                    pvp = converter_numero(linha[5])
                    dy = converter_numero(linha[6])

                    dy_min = filtro_atual['dy_min']
                    if dy_min < 1 and dy >= 1: dy_min *= 100 

                    if (filtro_atual['pvp_min'] <= pvp <= filtro_atual['pvp_max']) and (dy >= dy_min):
                        oportunidades.append(ticker)
                else:
                    dy = converter_numero(linha[3])
                    pl = converter_numero(linha[5])
                    pvp = converter_numero(linha[6])
                    roe = converter_numero(linha[19])

                    dy_min = filtro_atual['dy_min']
                    if dy_min < 1 and dy >= 1: dy_min *= 100
                    roe_min = filtro_atual['roe_min']
                    if roe_min < 1 and roe >= 1: roe_min *= 100

                    if (filtro_atual['pl_min'] <= pl <= filtro_atual['pl_max']) and \
                       (filtro_atual['pvp_min'] <= pvp <= filtro_atual['pvp_max']) and \
                       (dy >= dy_min) and (roe >= roe_min):
                        oportunidades.append(ticker)

            except IndexError:
                pass 

        return oportunidades
    except Exception as e:
        print(f"Erro no filtro de oportunidades: {e}")
        return []

def gerar_painel_ativo(ticker, tipo, chat_id, message_id=None):
    """Gera a mensagem principal com os botões interativos e dados em tempo real"""
    is_fii = (tipo == 'fii')
    icone = "🏢 Fundo" if is_fii else "📈 Ação"
    voltar_cmd = "menu_fiis" if is_fii else "menu_acoes"

    # 1. Puxar as Logos e Dados Reais da Planilha

    url_logo = obter_link_logo(ticker, tipo, driver_manager)
    indicadores = buscar_dados_planilha(ticker, is_fii)
    # Tratamento de erro caso o ativo não esteja na planilha
    if not indicadores:
        msg_erro = f"❌ Erro: Não encontrei dados para **{ticker}** na planilha."
        if message_id:
            bot.edit_message_text(msg_erro, chat_id, message_id, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, msg_erro, parse_mode="Markdown")
        return

    # 2. Resumo da IA (Placeholder - futuramente puxar de module_ia)

    resumo_ia = f"Ativo monitorado do setor {indicadores.get('setor', 'Geral')}. Focado na geração de valor no mercado brasileiro."

    # 3. Montar a tela exata da sua arquitetura

    link_invisivel = f"[\u200c]({url_logo})" if url_logo else ""
    # Formatação condicional baseada no tipo de ativo
    if is_fii:
        texto = (
            f"{link_invisivel}{icone}: **{ticker}**\n"
            f"📝 **Resumo:** _{resumo_ia}_\n\n"
            f"💰 **Preço:** R$ {indicadores.get('preco', 'N/A')}\n"
            f"💸 **Dividend Yield:** {indicadores.get('dy', 'N/A')}\n"
            f"⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n"
            f"💵 **VPA:** {indicadores.get('vpa', 'N/A')}"
        )
    else:
        texto = (
            f"{link_invisivel}{icone}: **{ticker}**\n"
            f"📝 **Resumo:** _{resumo_ia}_\n\n"
            f"💰 **Preço:** R$ {indicadores.get('preco', 'N/A')}\n"
            f"💸 **Dividend Yield:** {indicadores.get('dy', 'N/A')}\n"
            f"📊 **P/L:** {indicadores.get('pl', 'N/A')} | ⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n"
            f"📈 **ROE:** {indicadores.get('roe', 'N/A')}"
        )

    # 4. Criar os Botões (Submenus)

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📎 Dados Importantes", callback_data=f"dados_{ticker}_{tipo}"),
        InlineKeyboardButton("📑 Documentos", callback_data=f"docs_{ticker}_{tipo}")
    )
    markup.add(InlineKeyboardButton("⚠️ Análise de IA", callback_data=f"ia_{ticker}_{tipo}"))
    markup.add(InlineKeyboardButton(f"🔙 Voltar aos {icone.split()[1]}s", callback_data=voltar_cmd))

    # 5. Enviar ou Editar

    if message_id:
        bot.edit_message_text(texto, chat_id, message_id, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=False)
    else:
        bot.send_message(chat_id, texto, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=False)
