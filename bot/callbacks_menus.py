import logging
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.loader import bot
from config import SPREADSHEET_URL
from atualizador_documentos import SessionDB
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos, DadosFinanceirosAcoes

# Imports dos nossos serviços inteligentes
from services.dashboard_menus import buscar_oportunidades, gerar_painel_ativo, buscar_favoritos
from services.planilhas import buscar_dados_planilha_com_cache, buscar_ativo_na_planilha

logger = logging.getLogger(__name__)

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
    nome_setor = "_".join(call.data.split('_')[2:])
    bot.answer_callback_query(call.id, f"Buscando ativos de {nome_setor}...")

    matriz = buscar_dados_planilha_com_cache("BD_FIIs")
    markup = InlineKeyboardMarkup(row_width=2)
    botoes_ativos = []

    for linha in matriz[1:]:
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
    nome_setor = "_".join(call.data.split('_')[2:])
    bot.answer_callback_query(call.id, f"Buscando ações de {nome_setor}...")

    matriz = buscar_dados_planilha_com_cache("BD_Acoes")
    markup = InlineKeyboardMarkup(row_width=3) # 3 botões por linha para ações fica legal
    botoes_ativos = []

    for linha in matriz[1:]:
        ticker = linha[0].strip()
        # Lê a coluna de setor da ação (Assumindo Coluna C -> índice 2)
        setor_da_linha = linha[2].strip() 

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

# ==========================================
# ----- BOTÕES PRINCIPAIS -----
# ==========================================
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
            markup = InlineKeyboardMarkup(row_width=1)
            markup.add(
                InlineKeyboardButton("🧠 Entenda os Comandos", callback_data="ajuda_comandos"),
                InlineKeyboardButton("🚀 Roadmap de Desenvolvimento", callback_data="ajuda_roadmap"),
                InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu")
            )
            texto = "ℹ️ *Painel de Ajuda*\n\nProjeto iniciado em Setembro/2025. O sistema está em fase de evolução para um ecossistema completo de análise de ativos."
            bot.edit_message_text(texto, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- MÓDULO FIIs HIERÁRQUICO ---
        elif dados == "menu_fiis":
            bot.answer_callback_query(call.id, "Carregando FIIs...")
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("⭐ Meus Favoritos", callback_data="favoritos_fiis"),
                InlineKeyboardButton("🔥 Oportunidades", callback_data="oportunidades_fiis")
            )

            try:
                # Busca os dados via cache conforme estruturado no seu sistema[span_1](start_span)[span_1](end_span)
                matriz = buscar_dados_planilha_com_cache("BD_FIIs")
                if matriz:
                    # Assumindo: 0:Ticker, 1:Tipo (Tijolo/Papel/Híbrido), 2:Segmento
                    tipos = sorted(list(set(linha[1].strip() for linha in matriz[1:] if linha[1].strip())))
                    for t in tipos:
                        markup.add(InlineKeyboardButton(f"🏢 {t}", callback_data=f"tipo_fii_{t}"))
            except Exception as e:
                print(f"Erro ao listar tipos: {e}")

            markup.add(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("🏢 *Módulo FIIs - Selecione o Tipo:*", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- MÓDULO AÇÕES ---
        elif dados == "menu_acoes":
            bot.answer_callback_query(call.id, "Carregando Ações...")
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("⭐ Minhas Favoritas", callback_data="favoritos_acoes"),
                InlineKeyboardButton("🔥 Oportunidades", callback_data="oportunidades_acoes")
            )

            try:
                matriz = buscar_dados_planilha_com_cache("BD_Acoes")
                if matriz:
                    # Assumindo que o Setor fica na Coluna C (índice 2). 
                    # Se for outra coluna, basta mudar o linha[2] para o número correto!
                    setores_acoes = sorted(list(set(linha[2].strip() for linha in matriz[1:] if linha[2].strip())))
                    
                    for s in setores_acoes:
                        # Criando o botão com o nome completo do setor (sem o [:12])
                        markup.add(InlineKeyboardButton(f"📁 {s}", callback_data=f"setor_acao_{s}"))
            except Exception as e:
                print(f"Erro ao ler setores de ações: {e}")

            markup.add(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("📈 *Módulo de Ações*\nSelecione um Setor ou Favorita:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- FAVORITOS ---            
        elif dados in ["favoritos_fiis", "favoritos_acoes"]:
            bot.answer_callback_query(call.id, "Buscando seus favoritos...")
            if favs:
                botoes = [InlineKeyboardButton(tkr, callback_data=f"{tipo}_{tkr}") for tkr in favs]
                markup.add(*botoes)
                texto = f"⭐ *Seus Ativos Favoritos ({'FIIs' if is_fii else 'Ações'})*\n\nSelecione um para acessar o painel:"
            else:
                texto = "📭 *Nenhum favorito encontrado.* \nVerifique se o seu config.py contém a lista `FAVORITOS` preenchida."

            markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=menu_voltar))
            bot.edit_message_text(texto, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- OPORTUNIDADES ---
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

        # --- ABRIR ATIVO (Dashboard) ---
        elif dados.startswith("fii_") or dados.startswith("acao_"):
            partes = dados.split("_")
            tipo = partes[0] 
            ticker = partes[1]
            bot.answer_callback_query(call.id, f"Carregando terminal de {ticker}...")
            gerar_painel_ativo(ticker, tipo, chat_id, msg_id)

        # --- DADOS COMPLETOS ---
        elif dados.startswith("dados_"):
            bot.answer_callback_query(call.id, "Buscando indicadores...")
            partes = dados.split("_")
            ticker, tipo = partes[1], partes[2]
            is_fii = (tipo == "fii")
            
            # CORREÇÃO: Nome correto da função que busca apenas 1 ativo no cache
            indicadores = buscar_ativo_na_planilha(ticker, is_fii)
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))
            
            if not indicadores:
                bot.edit_message_text(f"❌ Não encontrei os dados detalhados de **{ticker}** na planilha.", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")
            else:
                if is_fii:
                    texto = (
                        f"📎 **Dados Completos: {ticker}**\n\n"
                        f"🏢 **Setor:** {indicadores.get('setor', 'N/A')}\n"
                        f"💰 **Preço:** R$ {indicadores.get('preco', 'N/A')}\n"
                        f"⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n"
                        f"💸 **DY (12m):** {indicadores.get('dy', 'N/A')}\n"
                        f"💵 **Valor Patrimonial (VPA):** {indicadores.get('vpa', 'N/A')}"
                    )
                else:
                    texto = (
                        f"📎 **Dados Completos: {ticker}**\n\n"
                        f"📈 **Setor:** {indicadores.get('setor', 'N/A')}\n"
                        f"💰 **Preço:** R$ {indicadores.get('preco', 'N/A')}\n"
                        f"📊 **P/L:** {indicadores.get('pl', 'N/A')}\n"
                        f"⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n"
                        f"💸 **DY (12m):** {indicadores.get('dy', 'N/A')}\n"
                        f"🚀 **ROE:** {indicadores.get('roe', 'N/A')}"
                    )
                bot.edit_message_text(texto, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- NÍVEL 1: MENU DE MESES (Docs) ---
        elif dados.startswith("docs_"):
            partes = dados.split("_")
            ticker = partes[1]
            tipo = partes[2]
            
            markup = InlineKeyboardMarkup()
            session = SessionDB()

            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
            encontrou_dados = False

            if ativo:
                if tipo == "fii":
                    docs = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.ativo_id == ativo.id).all()
                    if docs:
                        encontrou_dados = True
                        meses_unicos = sorted(list(set([d.data_publicacao.strftime("%Y-%m") for d in docs if d.data_publicacao])), reverse=True)

                        for mes in meses_unicos[:10]:
                            qtd = len([d for d in docs if d.data_publicacao and d.data_publicacao.strftime("%Y-%m") == mes])
                            ano, mes_num = mes.split('-')
                            markup.add(InlineKeyboardButton(f"📁 {mes_num}/{ano} ({qtd} arquivos)", callback_data=f"mes_{ticker}_{tipo}_{mes}"))

                elif tipo == "acao":
                    balancos = session.query(DadosFinanceirosAcoes).filter(DadosFinanceirosAcoes.ativo_id == ativo.id).all()
                    if balancos:
                        encontrou_dados = True
                        datas_unicas = sorted(list(set([b.data_referencia.strftime("%Y-%m-%d") for b in balancos if b.data_referencia])), reverse=True)

                        for dt in datas_unicas[:5]:
                            ano, mes_num, dia = dt.split('-')
                            markup.add(InlineKeyboardButton(f"📊 Balanço CVM ({mes_num}/{ano})", callback_data=f"mes_{ticker}_{tipo}_{dt}"))

            session.close()

            cat_status = "fundos-imobiliarios" if tipo == "fii" else "acoes"
            markup.row(InlineKeyboardButton("📈 Ver no StatusInvest", url=f"https://statusinvest.com.br/{cat_status}/{ticker.lower()}"))
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))

            if encontrou_dados:
                txt = f"📅 **Histórico de {ticker}**\n\nEscolha o período que você deseja analisar:"
            else:
                txt = f"📭 **Nenhum dado encontrado para {ticker}**\nO robô ainda não processou arquivos ou balanços para este ativo."

            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- NÍVEL 2: MOSTRANDO OS ARQUIVOS OU RELATÓRIO CVM ---
        elif dados.startswith("mes_"):
            partes = dados.split("_")
            ticker = partes[1]
            tipo = partes[2]
            periodo = partes[3]
            
            markup = InlineKeyboardMarkup()
            session = SessionDB()

            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()

            if tipo == "fii":
                docs = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.ativo_id == ativo.id).all()
                docs_do_mes = [d for d in docs if d.data_publicacao and d.data_publicacao.strftime("%Y-%m") == periodo]

                ano, mes_num = periodo.split('-')
                txt = f"📂 **Arquivos de {ticker} ({mes_num}/{ano})**\n\nEstes são os documentos salvos no Drive:"

                for doc in docs_do_mes:
                    markup.add(InlineKeyboardButton(f"📄 {doc.tipo_documento}", url=doc.url_pdf))

            elif tipo == "acao":
                balanco = session.query(DadosFinanceirosAcoes).filter(
                    DadosFinanceirosAcoes.ativo_id == ativo.id, 
                    DadosFinanceirosAcoes.data_referencia == periodo
                ).first()

                ano, mes_num, dia = periodo.split('-')
                txt = f"📊 **Relatório Financeiro: {ticker} ({mes_num}/{ano})**\n_Dados oficiais extraídos da CVM_\n\n"

                def formata_rs(valor):
                    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if valor else "Não divulgado"

                txt += f"💰 **Receita:** {formata_rs(balanco.receita)}\n"
                txt += f"💸 **Lucro Líquido:** {formata_rs(balanco.lucro_liquido)}\n"
                txt += f"🏦 **Caixa:** {formata_rs(balanco.caixa)}\n"
                txt += f"📉 **Passivo Total:** {formata_rs(balanco.passivo_total)}\n"

            session.close()
            markup.add(InlineKeyboardButton("🔙 Voltar aos Meses", callback_data=f"docs_{ticker}_{tipo}"))
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- ANÁLISE DE IA ---
        elif dados.startswith("ia_"):
            bot.answer_callback_query(call.id, "Gerando análise avançada...")
            partes = dados.split("_")
            ticker, tipo = partes[1], partes[2]
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))
            
            texto_ia = (
                f"⚠️ **Análise de Inteligência Artificial: {ticker}**\n\n"
                f"🤖 _Módulo IA em Fase de Treinamento._\n\n"
                f"Em breve, o bot fará o cruzamento autônomo de:\n"
                f"🔹 Histórico de Dividendos vs Inflação\n"
                f"🔹 Vacância e Qualidade Física dos Imóveis\n"
                f"🔹 Notícias recentes e fatos relevantes\n"
                f"🔹 Risco de Alavancagem da Dívida\n\n"
                f"*(Aguardando integração final)*"
            )
            bot.edit_message_text(texto_ia, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")
            
    except Exception as e:
        print(f"Erro no callback geral: {e}")