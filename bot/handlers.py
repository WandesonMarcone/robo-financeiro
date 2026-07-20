import config
from bot.loader import bot
from services.planilhas import buscar_dados_planilha_com_cache
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
# ----- BOTÃO TIPO/SETOR FIIS -----
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('tipo_fii_'))
def callback_selecionar_segmento(call):
    """Lê a planilha, quebra as barras e cria os botões de segmentos únicos"""
    tipo_selecionado = call.data.split('_')[2]
    matriz = buscar_dados_planilha_com_cache("BD_FIIs")

    segmentos_unicos = set()

    for linha in matriz[1:]:
        tipo_fundo = linha[1].strip()
        if tipo_fundo == tipo_selecionado:
            # A MÁGICA DA LIMPEZA: Corta pela '/' e limpa os espaços invisíveis
            segmentos_brutos = linha[2].split('/')
            for seg in segmentos_brutos:
                seg_limpo = seg.strip()
                if seg_limpo: # Só adiciona se não for vazio
                    segmentos_unicos.add(seg_limpo)

    segmentos_ordenados = sorted(list(segmentos_unicos))

    markup = InlineKeyboardMarkup(row_width=1)
    for seg in segmentos_ordenados:
        markup.add(InlineKeyboardButton(f"📂 {seg}", callback_data=f"setor_fii_{seg}"))

    markup.add(InlineKeyboardButton("🔙 Voltar aos FIIs", callback_data="menu_fiis"))
    bot.edit_message_text(f"🏢 *Tipo {tipo_selecionado} - Segmentos:*\n\nSelecione um segmento para ver os ativos:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('setor_fii_'))
def callback_listar_ativos_fii(call):
    """Lista os FIIs do segmento e adiciona os marcadores visuais avançados"""
    
    # CORREÇÃO: Extração segura do nome do setor, garantindo que espaços (como "Renda Urbana") não quebrem a string
    nome_setor = call.data.replace('setor_fii_', '').strip()
    
    bot.answer_callback_query(call.id, f"Buscando ativos de {nome_setor}...")

    matriz = buscar_dados_planilha_com_cache("BD_FIIs")
    markup = InlineKeyboardMarkup(row_width=2)
    botoes_ativos = []

    for linha in matriz[1:]:
        # TRAVA DE SEGURANÇA: Se a linha estiver vazia, o bot pula para a próxima sem travar
        if len(linha) < 3:
            continue
            
        ticker = linha[0].strip()
        tipo_fundo = linha[1].strip()
        
        # Corta a barra e limpa espaços novamente para comparar corretamente
        segmentos_do_fundo = [s.strip() for s in linha[2].split('/')]

        # Verifica se a pasta clicada está dentro dos segmentos deste fundo
        if nome_setor in segmentos_do_fundo:

            # 🧠 LÓGICA DO AVISO VISUAL (ASTERISCO)

            texto_botao = ticker

            # CENÁRIO 1: Fundo com múltiplos segmentos (Ex: GARE11)
            if len(segmentos_do_fundo) > 1:
                # Futuro: Aqui você puxará a % raspada ou da coluna da planilha
                # Ex: porcentagem = linha[10] 
                texto_botao = f"{ticker} (*Misto/Múltiplo)"
                # porcentagem = linha[10].strip() # Extrai o valor real da planilha
                # texto_botao = f"{ticker} (*{porcentagem}% {nome_setor})"

            # CENÁRIO 2: Fundo de Papel (CRI)
            elif tipo_fundo.upper() == "PAPEL":
                # Futuro: Puxar IPCA/CDI da planilha. Ex: ipca = linha[11], cdi = linha[12]
                texto_botao = f"{ticker} (*Indexadores)"
                # porcentagem = linha[10].strip() # Extrai o valor real da planilha
                # texto_botao = f"{ticker} (*{porcentagem}% {nome_setor})"


            # Cria o botão com a formatação decidida
            botoes_ativos.append(InlineKeyboardButton(texto_botao, callback_data=f"fii_{ticker}"))

    # Adiciona todos os ativos na tela (2 por linha por causa do row_width=2)
    markup.add(*botoes_ativos)
    markup.add(InlineKeyboardButton("🔙 Voltar aos Tipos", callback_data="menu_fiis"))

    texto = f"📂 *Ativos no segmento: {nome_setor}*\n\nSelecione um ativo para analisar o painel profundo:"
    bot.edit_message_text(texto, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

# ==========================================
# ----- BOTÃO TIPO/SETOR AÇÕES -----
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('setor_acao_'))
def callback_listar_ativos_acao(call):
    """Lê a aba BD_Acoes e lista as empresas que pertencem ao setor clicado"""
    
    # CORREÇÃO: Extração segura do setor (idêntica à lógica que corrigimos para os FIIs)
    nome_setor = call.data.replace('setor_acao_', '').strip()
    
    bot.answer_callback_query(call.id, f"Buscando ações de {nome_setor}...")

    matriz = buscar_dados_planilha_com_cache("BD_Acoes")
    markup = InlineKeyboardMarkup(row_width=3) 
    botoes_ativos = []

    for linha in matriz[1:]:
        # SEGURANÇA: Verifica se a linha tem colunas suficientes
        if len(linha) < 2: continue
            
        ticker = linha[0].strip()
        # Lê a coluna de setor (Ajustado para índice 1, como você mencionou no código)
        setor_da_linha = linha[1].strip() 

        if setor_da_linha == nome_setor:
            # Adiciona o botão da ação na lista
            botoes_ativos.append(InlineKeyboardButton(f"📈 {ticker}", callback_data=f"acao_{ticker}"))

    # Injeta todos os botões no markup de uma vez
    markup.add(*botoes_ativos)
    markup.add(InlineKeyboardButton("🔙 Voltar aos Setores", callback_data="menu_acoes"))

    texto = f"📂 *Ações no setor: {nome_setor}*\n\nSelecione um ativo para analisar:"
    bot.edit_message_text(texto, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

# ==========================================
# ----- BOTÃO MENU AJUDA -----
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data == 'ajuda_roadmap')
def callback_ajuda_roadmap(call):
    texto = (
        "🗺️ *Roadmap de Desenvolvimento*\n\n"
        "✅ *Concluído:* Scraper FIIs, Cache, Menu Hierárquico.\n\n"
        "🚧 *Próximos Passos (Backlog):*\n"
        "1. *Hash SHA256:* Garantir integridade máxima contra duplicidade.\n"
        "2. *Validação Pós-Download:* Verificar PDF corrompido antes de salvar.\n"
        "3. *IA Analítica (Groq):* Ler PDFs para detectar riscos e vacância.\n"
        "4. *Retry Complexo:* Lógica de 3 tentativas com *backoff* de 15min.\n"
        "5. *CVM Ações:* Integrar download e backup dos PDFs originais no Google Drive.\n"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 Voltar", callback_data="menu_ajuda"))
    bot.edit_message_text(texto, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == 'ajuda_comandos')
def callback_ajuda_comandos(call):
    """Lista detalhada de todos os comandos do sistema"""
    texto_comandos = (
        "📖 *Guia de Comandos*\n\n"
        "🔹 */status* - Verifica a saúde do banco de dados.\n"
        "🔹 */relatorios* - Acesso direto aos últimos PDFs de Fatos Relevantes.\n"
        "🔹 */adicionar [TICKER]* - Adiciona um ativo manualmente ao seu monitoramento.\n"
        "🔹 */analisar [TICKER]* - Força uma análise profunda do ativo via IA.\n\n"
        "Dica: Utilize os menus dinâmicos para navegar pelos setores sem precisar digitar comandos."
    )

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 Voltar à Ajuda", callback_data="menu_ajuda"))

    bot.edit_message_text(texto_comandos, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")