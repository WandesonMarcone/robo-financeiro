import time
from modules.utils import conectar_gspread
import config

# Variável global para armazenar os dados por 5 minutos
CACHE_PLANILHA = {
    "BD_FIIs": {"dados": None, "timestamp": 0},
    "BD_Acoes": {"dados": None, "timestamp": 0}
}

TEMPO_CACHE_SEGUNDOS = 300 # 5 minutos

def buscar_dados_planilha_com_cache(nome_aba):
    """Retorna os dados da planilha. Se tiver consultado nos últimos 5 min, não vai na internet."""
    agora = time.time()
    
    # 1. Verifica se o cache ainda é válido
    if CACHE_PLANILHA[nome_aba]["dados"] is not None:
        if (agora - CACHE_PLANILHA[nome_aba]["timestamp"]) < TEMPO_CACHE_SEGUNDOS:
            return CACHE_PLANILHA[nome_aba]["dados"]
    
    # 2. Se o cache expirou ou está vazio, vai ao Google
    planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
    aba = planilha.worksheet(nome_aba)
    matriz = aba.get_all_values()
    
    # 3. Salva no cache
    CACHE_PLANILHA[nome_aba]["dados"] = matriz
    CACHE_PLANILHA[nome_aba]["timestamp"] = agora
    
    return matriz
  
def buscar_ativo_na_planilha(ticker, is_fii):
    """
    Substitui a antiga _buscar_dados_planilha.
    Busca o ativo no cache da planilha e retorna o dicionário com os dados.
    """
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
    matriz = buscar_dados_planilha_com_cache(nome_aba)
    
    if not matriz:
        return None

    # Procura a linha do ticker na matriz carregada (a primeira coluna é o ticker)
    for row in matriz[1:]:  # Pula o cabeçalho
        if row[0].strip().upper() == ticker.upper():
            
            # Mapeamento de colunas (Mantendo a lógica original)
            if is_fii:
            return {
                "tipo": row[1],    # Coluna B
                "setor": row[2],   # Coluna C
                "preco": row[3],   # Coluna D
                "pvp": row[5],     # Coluna F
                "dy": row[6],      # Coluna G
                "vpa": row[14],    # Coluna N
                "raw": row         # Guarda a linha toda caso precise de detalhes
            }
            else:
            return {
                "setor": row[1],   # Coluna B
                "preco": row[2],   # Coluna C
                "dy": row[3],      # Coluna D
                "pl": row[5],      # Coluna F
                "pvp": row[6],     # Coluna G
                "roe": row[19],    # Coluna T
                "raw": row         # Guarda a linha toda
            }
    return None

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
    # O [\u200c] é o link invisível para renderizar a logo no topo
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
