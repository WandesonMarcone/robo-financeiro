import logging
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.loader import bot
from config import SPREADSHEET_URL
from atualizador_documentos import SessionDB
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos, DadosFinanceirosAcoes

# Imports dos nossos serviços inteligentes
from services.dashboard_menus import buscar_oportunidades, gerar_painel_ativo, buscar_favoritos, filtrar_ativos_por_setor
from services.planilhas import buscar_dados_planilha_com_cache, buscar_ativo_na_planilha

logger = logging.getLogger(__name__)

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

        # =======================================================
        # --- MÓDULO FIIs HIERÁRQUICO DINÂMICO (CORRIGIDO) ---
        # =======================================================

        # --- 1ª CAMADA: MACRO CATEGORIAS (Coluna B: Tijolo, Papel, Híbrido...) ---
        elif dados == "menu_fiis":
            bot.answer_callback_query(call.id, "Carregando FIIs...")
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("⭐ Meus Favoritos", callback_data="favoritos_fiis"),
                InlineKeyboardButton("🔥 Oportunidades", callback_data="oportunidades_fiis")
            )

            try:
                matriz = buscar_dados_planilha_com_cache("BD_FIIs")
                if matriz:
                    # Pega as Macro Categorias da Coluna B (índice 1)
                    macro_tipos = sorted(list(set(
                        linha[1].strip() for linha in matriz[1:] 
                        if len(linha) > 1 and linha[1].strip()
                    )))

                    # Cria um botão para cada Macro (Ex: Tijolo, Papel, Híbrido)
                    for macro in macro_tipos:
                        markup.add(InlineKeyboardButton(f"🏢 {macro}", callback_data=f"macro_fii_{macro}"))
            except Exception as e:
                print(f"Erro ao listar macro categorias: {e}")

            markup.add(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("🏢 *Módulo FIIs - Selecione a Categoria:*", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- 2ª CAMADA: SUB-SETORES DA MACRO (Coluna C: Logística, Shopping...) ---
        elif call.data.startswith("macro_fii_"):
            macro_escolhida = call.data.replace("macro_fii_", "").strip()
            bot.answer_callback_query(call.id, f"Abrindo {macro_escolhida}...")

            try:
                matriz = buscar_dados_planilha_com_cache("BD_FIIs")
                markup = InlineKeyboardMarkup(row_width=2)

                # Busca na Coluna C (índice 2) os sub-setores pertencentes à Macro clicada (Coluna B)
                sub_setores = sorted(list(set(
                    linha[2].strip() for linha in matriz[1:] 
                    if len(linha) > 2 and linha[1].strip().lower() == macro_escolhida.lower() and linha[2].strip()
                )))

                # Se houver múltiplos sub-setores (Ex: Tijolo possui Logística, Shoppings, etc)
                if len(sub_setores) > 1:
                    for sub in sub_setores:
                        # Passa a Macro e o Sub-setor juntos via '___' para isolar a busca
                        markup.add(InlineKeyboardButton(f"📁 {sub}", callback_data=f"subsetor_fii_{macro_escolhida}___{sub}"))
                else:
                    # Se não houver sub-divisões (Ex: Papel), lista os ativos diretamente
                    tickers = [
                        linha[0].strip().upper() for linha in matriz[1:] 
                        if len(linha) > 1 and linha[1].strip().lower() == macro_escolhida.lower()
                    ]
                    for tkr in sorted(tickers):
                        markup.add(InlineKeyboardButton(f"🏢 {tkr}", callback_data=f"painel_{tkr}_fii"))

                markup.add(InlineKeyboardButton("🔙 Voltar", callback_data="menu_fiis"))
                bot.edit_message_text(f"📂 **Categoria:** {macro_escolhida}\nSelecione o segmento:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")
            except Exception as e:
                print(f"Erro ao abrir macro: {e}")

        # --- 3ª CAMADA: ATIVOS DO SUB-SETOR (Ex: Tijolo -> Logística -> VILG11) ---
        elif call.data.startswith("subsetor_fii_"):
            partes = call.data.replace("subsetor_fii_", "").split("___")
            macro, sub = partes[0], partes[1]
            bot.answer_callback_query(call.id, f"Buscando {sub}...")

            matriz = buscar_dados_planilha_com_cache("BD_FIIs")

            # Filtra ativos onde Coluna B == Macro E Coluna C == Sub-setor
            tickers = [
                linha[0].strip().upper() for linha in matriz[1:]
                if len(linha) > 2 and linha[1].strip().lower() == macro.lower() and linha[2].strip().lower() == sub.lower()
            ]

            markup = InlineKeyboardMarkup(row_width=3)
            for ticker in sorted(tickers):
                markup.add(InlineKeyboardButton(f"🏢 {ticker}", callback_data=f"painel_{ticker}_fii"))

            # Voltar para a Macro correspondente
            markup.add(InlineKeyboardButton("🔙 Voltar", callback_data=f"macro_fii_{macro}"))
            bot.edit_message_text(f"📂 **Segmento:** {sub}\nEscolha o ativo:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

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
                    setores_acoes = sorted(list(set(linha[1].strip() for linha in matriz[1:] if len(linha) > 1 and linha[1].strip())))

                    for s in setores_acoes:
                        markup.add(InlineKeyboardButton(f"📁 {s}", callback_data=f"setor_acao_{s}"))
            except Exception as e:
                print(f"Erro ao ler setores de ações: {e}")

            markup.add(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("📈 *Módulo de Ações*\nSelecione um Setor ou Favorita:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        elif call.data.startswith("setor_acao_"):
            setor_acao = call.data.replace("setor_acao_", "").strip()
            bot.answer_callback_query(call.id, f"Buscando {setor_acao}...")

            from services.dashboard_menus import filtrar_ativos_por_setor
            lista_de_tickers = filtrar_ativos_por_setor('acao', setor_acao)

            markup = InlineKeyboardMarkup(row_width=3)
            for ticker in lista_de_tickers:
                markup.add(InlineKeyboardButton(f"📈 {ticker}", callback_data=f"painel_{ticker}_acao"))

            markup.add(InlineKeyboardButton("🔙 Voltar", callback_data="menu_acoes"))
            bot.edit_message_text(f"📂 **Setor:** {setor_acao}\nEscolha a ação:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- FAVORITOS ---            
        elif dados in ["favoritos_fiis", "favoritos_acoes"]:
            bot.answer_callback_query(call.id, "Buscando seus favoritos...")
            
            # Identifica contexto baseada nos dados do callback
            is_fii = (dados == "favoritos_fiis")
            tipo = "fii" if is_fii else "acao"
            menu_voltar = "menu_fiis" if is_fii else "menu_acoes"

            # Busca a lista já pronta do seu config via a função que criamos
            favs = buscar_favoritos(tipo)
            
            markup = InlineKeyboardMarkup(row_width=3)
            
            if favs:
                # Cria os botões para cada ticker favorito
                botoes = [InlineKeyboardButton(tkr, callback_data=f"painel_{tkr}_{tipo}") for tkr in favs]
                markup.add(*botoes)
                texto = f"⭐ *Seus Ativos Favoritos ({'FIIs' if is_fii else 'Ações'})*\n\nSelecione um para acessar o painel:"
            else:
                texto = "📭 *Nenhum favorito encontrado.* \nVerifique se o seu config.py contém as listas `FIXAS_FIIS` ou `FIXAS_ACOES` preenchidas."

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
                    botoes_ativos = [InlineKeyboardButton(tkr, callback_data=f"painel_{tkr}_{tipo}") for tkr in top_oportunidades]
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

        # ==========================================
        # --- ROTA DE RETORNO AO PAINEL DO ATIVO ---
        # ==========================================
        elif dados.startswith("painel_"):
            partes = dados.split("_")
            ticker = partes[1]
            tipo_ativo = partes[2] # "fii" ou "acao" 
            gerar_painel_ativo(ticker, tipo_ativo, chat_id, msg_id)

        # ==========================================
        # --- ATALHO: DO PAINEL PARA A REVISÃO ---
        # ==========================================
        elif call.data.startswith("rev_t_"):
            ticker = call.data.replace("rev_t_", "")
            bot.answer_callback_query(call.id, f"Abrindo pendências de {ticker}...")
            
            # Como a lógica completa de exibir os botões de revisão está na sua rota da Central,
            # nós criamos uma ponte que avisa o usuário e cria um botão direto pra lá!
            markup = InlineKeyboardMarkup(row_width=1)
            markup.add(InlineKeyboardButton("⚖️ Ir para a Central de Revisão", callback_data="rev_start"))
            markup.add(InlineKeyboardButton("🔙 Voltar ao Painel", callback_data=f"painel_{ticker}_fii"))
            
            txt = (
                f"⚠️ **Auditoria Necessária: {ticker}**\n\n"
                f"Este fundo possui documentos escaneados ou suspeitos que a IA não conseguiu ler perfeitamente.\n\n"
                f"Por favor, acesse a **Central de Revisão** para categorizá-los e enviá-los ao seu Google Drive."
            )
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # ==========================================
        # --- NÍVEL 1: DADOS (Indicadores e Balanços) ---
        # ==========================================
        elif dados.startswith("dados_"):
            partes = dados.split("_")
            ticker = partes[1]
            tipo_ativo = partes[2]

            markup = InlineKeyboardMarkup(row_width=1)
            session = SessionDB()
            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()

            if ativo and tipo_ativo == "acao":
                balancos = session.query(DadosFinanceirosAcoes).filter(DadosFinanceirosAcoes.ativo_id == ativo.id).all()
                if balancos:
                    datas_unicas = sorted(list(set([b.data_referencia.strftime("%Y-%m-%d") for b in balancos if b.data_referencia])), reverse=True)
                    for dt in datas_unicas[:5]:
                        ano, mes_num, dia = dt.split('-')
                        markup.add(InlineKeyboardButton(f"📊 Balanço CVM ({mes_num}/{ano})", callback_data=f"mes_{ticker}_{tipo_ativo}_{dt}"))
                    txt = f"📈 **Dados Financeiros: {ticker}**\n\nEscolha o balanço que deseja analisar:"
                else:
                    txt = f"📭 **Nenhum balanço CVM encontrado para {ticker}.**"
            else:
                txt = f"📊 **Dados de {ticker}**\n\nIndicadores detalhados e atualizados conforme planilha."

            markup.add(InlineKeyboardButton("🔙 Voltar ao Painel", callback_data=f"painel_{ticker}_{tipo_ativo}"))
            session.close()
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")
        # ==========================================
        # --- NÍVEL 2: EXIBIR BALANÇO DE AÇÃO ---
        # ==========================================
        elif dados.startswith("mes_"):
            partes = dados.split("_")
            ticker = partes[1]
            tipo_ativo = partes[2]
            data_ref = partes[3]

            bot.answer_callback_query(call.id, "Gerando relatório financeiro...")

            session = SessionDB()
            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
            
            if ativo:
                balanco = session.query(DadosFinanceirosAcoes).filter(
                    DadosFinanceirosAcoes.ativo_id == ativo.id,
                    DadosFinanceirosAcoes.data_referencia == data_ref
                ).first()
                
                if balanco:
                    txt = (
                        f"📊 **Balanço CVM: {ticker}**\n"
                        f"📅 **Trimestre:** {data_ref}\n\n"
                        f"💰 **Receita Líquida:** R$ {balanco.receita_liquida or 'Não informado'}\n"
                        f"💵 **Lucro Líquido:** R$ {balanco.lucro_liquido or 'Não informado'}\n"
                        f"🏦 **Patrimônio Líquido:** R$ {balanco.patrimonio_liquido or 'Não informado'}\n"
                        f"📉 **Margem Líquida:** {balanco.margem_liquida or 'N/A'}%\n"
                        f"⚙️ **EBITDA:** R$ {balanco.ebitda or 'Não informado'}"
                    )
                else:
                    txt = f"📭 Nenhum dado detalhado encontrado para o período {data_ref}."
            else:
                txt = f"❌ Ativo **{ticker}** não encontrado no banco de dados."
                
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🔙 Voltar aos Balanços", callback_data=f"dados_{ticker}_{tipo_ativo}"))
            markup.add(InlineKeyboardButton("🔙 Voltar ao Painel", callback_data=f"painel_{ticker}_{tipo_ativo}"))
            
            session.close()
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # ==========================================
        # --- NÍVEL 1: DOCUMENTOS (PDFs do Drive) ---
        # ==========================================
        elif dados.startswith("docs_"):
            partes = dados.split("_")
            ticker = partes[1]
            tipo_ativo = partes[2] 

            markup = InlineKeyboardMarkup(row_width=1)
            session = SessionDB()
            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()

            if ativo:
                # O código já é dinâmico: só puxa o que existe salvo no banco para este fundo!
                tipos_existentes = session.query(DocumentosQualitativos.tipo_documento).filter(
                    DocumentosQualitativos.ativo_id == ativo.id,
                    DocumentosQualitativos.status_processamento.ilike("%SALVO_DRIVE%")
                ).distinct().all()

                if tipos_existentes:
                    for (tipo_doc,) in tipos_existentes:
                        # 🎨 MOTOR DE EMOJIS DINÂMICO
                        t_low = tipo_doc.lower()
                        if "gerencial" in t_low: emoji = "📊"
                        elif "fato" in t_low: emoji = "🚨"
                        elif "aviso" in t_low or "provento" in t_low: emoji = "💰"
                        elif "assembleia" in t_low or "vota" in t_low: emoji = "🗳️"
                        elif "trimestral" in t_low or "informe" in t_low: emoji = "📑"
                        elif "comunicado" in t_low: emoji = "📢"
                        else: emoji = "📄" # Padrão para "Outros"
                        
                        markup.add(InlineKeyboardButton(f"{emoji} {tipo_doc}", callback_data=f"doctipo_{ticker}_{tipo_doc}"))
                    
                    txt = f"📂 **Gaveta de Documentos: {ticker}**\n\nSelecione a categoria que deseja visualizar:"
                else:
                    txt = f"📭 **Ainda não há documentos processados para o fundo {ticker}.**"
            else:
                txt = f"❌ Ativo **{ticker}** não encontrado no banco de dados."

            markup.add(InlineKeyboardButton("🔙 Voltar ao Painel", callback_data=f"painel_{ticker}_{tipo_ativo}"))
            session.close()
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # ==========================================
        # --- NÍVEL 2: SELEÇÃO DE MESES (FIIs) ---
        # ==========================================
        elif dados.startswith("doctipo_"):
            bot.answer_callback_query(call.id, "Vasculhando documentos...")
            partes = dados.split("_", 2)
            ticker = partes[1]
            tipo_doc = partes[2]

            session = SessionDB()
            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
            
            tipo_ativo = "fii"
            if ativo and hasattr(ativo, 'tipo') and ativo.tipo:
                if hasattr(ativo.tipo, 'value'):
                    tipo_ativo = str(ativo.tipo.value).lower()
                else:
                    tipo_ativo = str(ativo.tipo).lower()

            markup = InlineKeyboardMarkup(row_width=2)

            docs = session.query(DocumentosQualitativos).filter(
                DocumentosQualitativos.ativo_id == ativo.id,
                DocumentosQualitativos.tipo_documento == tipo_doc,
                DocumentosQualitativos.status_processamento.ilike("%SALVO_DRIVE%")
            ).all()

            if docs:
                meses_unicos = []
                for d in docs:
                    # 🔴 CORREÇÃO DA DATA: Puxa o mês real direto do nome do arquivo!
                    mes_str = "0000-00"
                    if d.assunto and '-' in d.assunto:
                        p = d.assunto.split(" ")[0].split("-") # Extrai [13, 05, 2026]
                        if len(p) == 3:
                            mes_str = f"{p[2]}-{p[1]}" # Transforma em 2026-05
                    elif d.data_publicacao:
                        mes_str = d.data_publicacao.strftime("%Y-%m")
                    
                    if mes_str not in meses_unicos:
                        meses_unicos.append(mes_str)
                
                meses_unicos.sort(reverse=True)

                for mes in meses_unicos[:10]:
                    if mes == "0000-00":
                        nome_btn = "📅 Diversos (Sem Data)"
                    else:
                        ano, mes_num = mes.split('-')
                        nome_btn = f"📅 {mes_num}/{ano}"
                        
                    markup.add(InlineKeyboardButton(nome_btn, callback_data=f"docmes_{ticker}_{tipo_doc}_{mes}"))

                txt = f"📅 **{tipo_doc} - {ticker}**\n\nSelecione o período:"
            else:
                txt = f"📭 **Opa! Houve uma falha ao abrir a gaveta.**"

            markup.add(InlineKeyboardButton("🔙 Voltar aos Tipos", callback_data=f"docs_{ticker}_{tipo_ativo}"))
            session.close()
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # ==========================================
        # --- NÍVEL 3: EXIBIÇÃO DOS PDFS E RESUMO ---
        # ==========================================
        elif dados.startswith("docmes_"):
            partes = dados.split("_", 3)
            ticker = partes[1]
            tipo_doc = partes[2]
            periodo = partes[3]

            markup = InlineKeyboardMarkup(row_width=1)
            session = SessionDB()

            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
            
            docs = session.query(DocumentosQualitativos).filter(
                DocumentosQualitativos.ativo_id == ativo.id,
                DocumentosQualitativos.tipo_documento == tipo_doc,
                DocumentosQualitativos.status_processamento.ilike("%SALVO_DRIVE%")
            ).all()

            docs_do_mes = []
            for d in docs:
                # 🔴 Alinhando a busca com a nova regra de data real
                mes_str = "0000-00"
                if d.assunto and '-' in d.assunto:
                    p = d.assunto.split(" ")[0].split("-")
                    if len(p) == 3: mes_str = f"{p[2]}-{p[1]}"
                elif d.data_publicacao:
                    mes_str = d.data_publicacao.strftime("%Y-%m")
                    
                if mes_str == periodo:
                    docs_do_mes.append(d)

            if periodo == "0000-00":
                txt = f"📂 **{tipo_doc}: {ticker}**\n\n"
            else:
                ano, mes_num = periodo.split('-')
                txt = f"📂 **{tipo_doc}: {ticker} ({mes_num}/{ano})**\n\n"

            # 🔴 ADIÇÃO DO RESUMO (UX Melhorada)
            for doc in docs_do_mes:
                data_limpa = doc.assunto.split(" ")[0].replace("-", "/") if doc.assunto else "Data N/A"
                
                # Se o seu banco tiver uma coluna "resumo", ele usa. Senão, mostra o Assunto completo da B3
                resumo_texto = getattr(doc, 'resumo', None)
                if not resumo_texto:
                    resumo_texto = doc.assunto if doc.assunto else "Detalhes não informados."

                txt += f"📄 **Data:** `{data_limpa}`\n"
                txt += f"📝 **Resumo:** _{resumo_texto}_\n\n"
                
                url = doc.url_pdf if (doc.url_pdf and str(doc.url_pdf).startswith("http")) else "https://drive.google.com"
                markup.add(InlineKeyboardButton(f"🔗 Abrir PDF ({data_limpa})", url=url))

            markup.add(InlineKeyboardButton("🔙 Voltar aos Meses", callback_data=f"doctipo_{ticker}_{tipo_doc}"))
            session.close()
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- ANÁLISE DE IA ---
        elif dados.startswith("ia_"):
            bot.answer_callback_query(call.id, "Gerando análise avançada...")
            partes = dados.split("_")
            ticker, tipo = partes[1], partes[2]
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"painel_{ticker}_{tipo_ativo}"))
            
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
