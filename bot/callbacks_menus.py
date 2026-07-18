from bot.loader import bot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
# Importe aqui as funções que você moverá para services/dashboard_service.py
from services.dashboard_service import buscar_oportunidades 

@bot.callback_query_handler(func=lambda call: call.data.startswith(('menu_', 'oportunidades_', 'voltar_menu')))
def callback_geral(call):
    dados = call.data
    chat_id = call.message.chat.id
    msg_id = call.message.message_id

    # 1. NAVEGAÇÃO BÁSICA
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
