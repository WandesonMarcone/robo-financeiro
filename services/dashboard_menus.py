from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import config
from bot.loader import bot
from services.planilhas import buscar_dados_planilha_com_cache, buscar_ativo_na_planilha
from services.logo_service import obter_link_logo
from modules.GoogleDriveManager import GoogleDriveManager
from database.models import SessionDB, DocumentosQualitativos, Ativo # Garanta que os imports estejam aqui

# Instancia o gerenciador de arquivos uma vez
drive_manager = GoogleDriveManager()

def buscar_favoritos(tipo):
    """Filtra os ativos da planilha que estão na lista de config.FAVORITOS"""
    is_fii = (tipo == 'fii')
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
    # Acessa a lista configurada no seu arquivo config.py
    lista_favs = config.FAVORITOS.get(tipo, [])

    try:
        matriz = buscar_dados_planilha_com_cache(nome_aba)
        if not matriz: return []

        favoritos_encontrados = []
        for linha in matriz[1:]:
            ticker = linha[0].strip().upper()
            if ticker in lista_favs:
                favoritos_encontrados.append(ticker)
        
        return favoritos_encontrados
    except Exception as e:
        print(f"Erro ao buscar favoritos: {e}")
        return []

def converter_numero(valor_string):
    """Limpa textos da planilha e transforma em número puro"""
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
    """Vasculha a planilha usando o Cache Rápido para não travar o bot"""
    is_fii = (tipo == 'fii')
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"

    FILTROS_FIXOS = {
        "fii": {"pvp_min": 0.50, "pvp_max": 1.15, "dy_min": 0.08},
        "acao": {"pl_min": 2.0, "pl_max": 15.0, "pvp_min": 0.50, "pvp_max": 2.50, "dy_min": 0.06, "roe_min": 0.10}
    }
    filtro_atual = FILTROS_FIXOS[tipo]

    try:
        # Puxa os dados instantaneamente do Cache
        matriz = buscar_dados_planilha_com_cache(nome_aba)
        if not matriz: return []

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

                    dy_min, roe_min = filtro_atual['dy_min'], filtro_atual['roe_min']
                    if dy_min < 1 and dy >= 1: dy_min *= 100
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
    is_fii = (tipo == 'fii')
    icone = "🏢 Fundo" if is_fii else "📈 Ação"
    voltar_cmd = "menu_fiis" if is_fii else "menu_acoes"

    url_logo = obter_link_logo(ticker, tipo, drive_manager)
    indicadores = buscar_ativo_na_planilha(ticker, is_fii)

    if not indicadores:
        msg_erro = f"❌ Erro: Não encontrei dados para **{ticker}** na planilha."
        if message_id: bot.edit_message_text(msg_erro, chat_id, message_id, parse_mode="Markdown")
        else: bot.send_message(chat_id, msg_erro, parse_mode="Markdown")
        return

    # --- MELHORIA DA IA: Resumo Dinâmico ---
    # Aqui você pode chamar uma função que consulta o banco ou uma mini lógica de resumo
    resumo_ia = f"Ativo do setor {indicadores.get('setor', 'Geral')}. Rentabilidade atual: {indicadores.get('dy', 'N/A')}."
    
    # --- FIX LOGO: O Telegram só exibe links diretos de imagem (.png, .jpg) ---
    # Se url_logo for um link de pasta do Drive, o Telegram NÃO vai mostrar.
    # O link precisa ser um link direto da imagem.
    link_invisivel = f"[\u200c]({url_logo})" if url_logo else ""

    texto = (
        f"{link_invisivel}{icone}: **{ticker}**\n"
        f"📝 **Resumo:** _{resumo_ia}_\n\n"
        f"💰 **Preço:** R$ {indicadores.get('preco', 'N/A')}\n"
        f"💸 **Dividend Yield:** {indicadores.get('dy', 'N/A')}\n"
        f"⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n"
        f"💵 **VPA/PL:** {indicadores.get('vpa', indicadores.get('pl', 'N/A'))}"
    )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📎 Dados", callback_data=f"dados_{ticker}_{tipo}"),
        InlineKeyboardButton("📑 Docs", callback_data=f"docs_{ticker}_{tipo}")
    )
    
    # --- NOVA LÓGICA DE REVISÃO (Dinâmica) ---
    if is_fii:
        session = SessionDB()
        pendentes = session.query(DocumentosQualitativos).join(Ativo).filter(
            Ativo.ticker == ticker, 
            DocumentosQualitativos.status_processamento == "AGUARDANDO_REVISAO"
        ).count()
        session.close()

        if pendentes > 0:
            markup.add(InlineKeyboardButton(f"⚠️ {pendentes} Doc(s) para Revisão", callback_data=f"rev_t_{ticker}"))

    markup.add(InlineKeyboardButton("⚠️ Análise IA", callback_data=f"ia_{ticker}_{tipo}"))
    markup.add(InlineKeyboardButton(f"🔙 Voltar", callback_data=voltar_cmd))

    if message_id: 
        bot.edit_message_text(texto, chat_id, message_id, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=False)
    else: 
        bot.send_message(chat_id, texto, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=False)