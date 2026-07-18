from bot.loader import bot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
# Importe aqui as funções que você moverá para services/dashboard_service.py
from services.dashboard_service import buscar_oportunidades 

@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    try:
        dados = call.data
        chat_id = call.message.chat.id
        msg_id = call.message.message_id

        # --- NAVEGAÇÃO BÁSICA ---
        if dados == "voltar_menu":
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
                       InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"))
            markup.row(InlineKeyboardButton("🌍 Visão Macro & Notícias", callback_data="menu_macro"))
            markup.row(InlineKeyboardButton("ℹ️ Ajuda / Sobre", callback_data="menu_ajuda"))
            bot.edit_message_text("🤖 *Terminal Institucional* 🤖\nSelecione o módulo de análise abaixo:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        elif dados == "menu_ajuda":
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("⚠️ Histórico de Logs", callback_data="ver_logs"))
            markup.row(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            texto_ajuda = (
                "ℹ️ *Painel de Ajuda / Sobre*\n\n"
                "O robô monitora e processa dados da CVM e B3.\n\n"
                "📌 *Comandos Rápidos:*\n"
                "`/status` - Saúde do BD PostgreSQL\n"
                "`/relatorios` - Últimos PDFs\n"
                "`/adicionar TICKER` - Insere ativos\n\n"
                "📊 *Nova Arquitetura:*\n"
                "- Resumo IA, Indicadores (P/L, P/VP, DY)\n"
                "- Submenus de Documentos e Análise IA."
            )
            bot.edit_message_text(texto_ajuda, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- MENUS DINÂMICOS (Consultam a Planilha) ---
        elif dados == "menu_fiis":
            bot.answer_callback_query(call.id, "Carregando FIIs...")
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("⭐ Meus Favoritos", callback_data="favoritos_fiis"),
                InlineKeyboardButton("🔥 Oportunidades", callback_data="oportunidades_fiis")
            )

            try:
                # ⚠️ PONTO DE ATENÇÃO: Conexão direta com Google Sheets a cada clique.
                planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
                aba = planilha.worksheet("BD_FIIs")
                matriz = aba.get_all_values()

                cabecalhos = [c.lower().strip() for c in matriz[0]]
                idx = next((i for i, c in enumerate(cabecalhos) if c in ["setor", "segmento", "tipo"]), -1)

                # Gera botões automáticos baseados nos setores digitados na planilha
                if idx != -1:
                    setores = sorted(list(set(linha[idx].strip() for linha in matriz[1:] if linha[idx].strip())))
                    for s in setores:
                        markup.add(InlineKeyboardButton(f"📁 {s}", callback_data=f"setor_fii_{s[:12]}"))
            except Exception as e:
                print(f"Erro ao ler setores: {e}")

            markup.add(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("🏢 *Módulo FIIs*\nSelecione uma categoria ou favorito:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # (A Lógica para "menu_acoes" e "setor_acao" segue a exata mesma estrutura descrita acima)
        elif dados == "menu_acoes":
            bot.answer_callback_query(call.id, "Carregando Ações...")
            markup = InlineKeyboardMarkup(row_width=2)

            # Adicionando botões de atalho
            markup.add(
                InlineKeyboardButton("⭐ Minhas Favoritas", callback_data="favoritos_acoes"),
                InlineKeyboardButton("🔥 Oportunidades", callback_data="oportunidades_acoes")
            )

            try:
                # Conecta ao Sheets
                planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
                # Tenta buscar a aba
                try:
                    aba = planilha.worksheet("BD_Acoes")
                except:
                    bot.send_message(chat_id, "❌ Erro: Aba 'BD_Acoes' não encontrada na planilha.")
                    return

                matriz = aba.get_all_values()
                if not matriz:
                    bot.send_message(chat_id, "❌ A aba 'BD_Acoes' está vazia.")
                    return

                # Identifica cabeçalhos e encontra o setor
                cabecalhos = [c.lower().strip() for c in matriz[0]]
                idx = next((i for i, c in enumerate(cabecalhos) if c in ["setor", "segmento", "tipo"]), -1)

                if idx != -1:
                    setores = sorted(list(set(linha[idx].strip() for linha in matriz[1:] if linha[idx].strip())))
                    for s in setores:
                        markup.add(InlineKeyboardButton(f"📁 {s}", callback_data=f"setor_acao_{s[:12]}"))
                else:
                    bot.send_message(chat_id, "⚠️ Cabeçalho 'Setor/Segmento' não localizado na planilha.")

            except Exception as e:
                logger.error(f"Erro fatal no menu_acoes: {e}")
                bot.send_message(chat_id, f"❌ Erro ao acessar planilha: {str(e)}")
                return

            markup.add(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("📈 *Módulo de Ações*\nSelecione um setor ou favorita:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

    # 2. OPORTUNIDADES
    elif dados in ["oportunidades_fiis", "oportunidades_acoes"]:
        bot.answer_callback_query(call.id, "Analisando o mercado...")
        is_fii = (dados == "oportunidades_fiis")
        tipo = "fii" if is_fii else "acao"
        menu_voltar = "menu_fiis" if is_fii else "menu_acoes"

        try:
            oportunidades = buscar_oportunidades(tipo)
            markup = InlineKeyboardMarkup(row_width=3)
            
            if oportunidades:
                top_oportunidades = oportunidades[:15] 
                botoes_ativos = [InlineKeyboardButton(tkr, callback_data=f"{tipo}_{tkr}") for tkr in top_oportunidades]
                markup.add(*botoes_ativos)
                texto = f"🔥 *Top Oportunidades ({'FIIs' if is_fii else 'Ações'})*\n\nEstes ativos passaram na sua peneira."
            else:
                texto = "📭 *Nenhuma oportunidade encontrada.*"

            markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=menu_voltar))
            bot.edit_message_text(texto, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")
        except Exception as e:
            print(f"Erro ao carregar oportunidades: {e}")
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Voltar", callback_data=menu_voltar))
            bot.edit_message_text("❌ Erro ao aplicar os filtros.", chat_id, msg_id, reply_markup=markup)
