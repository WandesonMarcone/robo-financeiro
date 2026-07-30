import logging
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Imports base e configurações
from bot.loader import bot
from config import SPREADSHEET_URL, MAPA_SETORES_B3

# Banco de Dados
from atualizador_documentos import SessionDB
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos, DadosFinanceirosAcoes, DadosFinanceirosFiis

# Serviços Inteligentes (Planilhas e Painéis)
from services.dashboard_menus import buscar_oportunidades, gerar_painel_ativo, buscar_favoritos, filtrar_ativos_por_setor, extrair_data_real
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
        # --- MÓDULO FIIs HIERÁRQUICO DINÂMICO ---
        # =======================================================
        elif dados == "menu_fiis":
            bot.answer_callback_query(call.id, "Carregando FIIs...")
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("⭐ Meus Favoritos", callback_data="favoritos_fiis"),
                InlineKeyboardButton("🔥 Oportunidades", callback_data="oportunidades_fiis")
            )

            try:
                # Agora ele vai achar a função porque ela está importada corretamente no topo!
                matriz = buscar_dados_planilha_com_cache("BD_FIIs")
                if matriz:
                    # Pega as Macro Categorias da Coluna B
                    macro_tipos = sorted(list(set(linha[1].strip() for linha in matriz[1:] if len(linha) > 1 and linha[1].strip())))
                    for macro in macro_tipos:
                        markup.add(InlineKeyboardButton(f"🏢 {macro}", callback_data=f"macro_fii_{macro}"))
            except Exception as e:
                print(f"Erro ao listar macro categorias FII: {e}")

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

         # --- 1ª CAMADA: MACRO-SETORES DAS AÇÕES (DINÂMICO + FIXO) ---
        elif dados == "menu_acoes":
            bot.answer_callback_query(call.id, "Carregando Ações...")
            
            # 🔴 LÊ A PLANILHA PRIMEIRO
            matriz = buscar_dados_planilha_com_cache("BD_Acoes")
            tickers_planilha = [linha[0].strip().upper() for linha in matriz[1:] if len(linha) > 0 and linha[0].strip()] if matriz else []

            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("⭐ Minhas Favoritas", callback_data="favoritos_acoes"),
                InlineKeyboardButton("🔥 Oportunidades", callback_data="oportunidades_acoes")
            )

            # 🎨 Emojis exclusivos por setor
            emojis = {
                "Petróleo, Gás & Biocombustíveis": "🛢️",
                "Financeiro": "🏦",
                "Utilidade Pública": "⚡",
                "Materiais Básicos": "🧱",
                "Consumo Cíclico": "🛍️",
                "Consumo Não-Cíclico": "🛒",
                "Saúde": "🏥",
                "Bens Industriais": "🚜",
                "Tecnologia & Telecom": "💻",
                "Agronegócio": "🌱"
            }

            lista_macros = list(MAPA_SETORES_B3.keys())
            for idx, macro in enumerate(lista_macros):
                # 🔴 O PULO DO GATO: Só cria o botão se o setor tiver alguma ação que você possui na planilha!
                tem_acao = False
                for subsetor, ativos in MAPA_SETORES_B3[macro].items():
                    if any(t in tickers_planilha for t in ativos):
                        tem_acao = True
                        break
                
                if tem_acao:
                    icone = emojis.get(macro, "📁")
                    markup.add(InlineKeyboardButton(f"{icone} {macro}", callback_data=f"macro_ac_{idx}"))

            markup.add(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            bot.edit_message_text("📈 *Módulo Ações - Selecione o Setor:*", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- 2ª CAMADA: SUB-SETORES (Ocultando vazios) ---
        elif dados.startswith("macro_ac_"):
            
            matriz = buscar_dados_planilha_com_cache("BD_Acoes")
            tickers_planilha = [linha[0].strip().upper() for linha in matriz[1:] if len(linha) > 0 and linha[0].strip()] if matriz else []

            idx_macro = int(dados.replace("macro_ac_", ""))
            lista_macros = list(MAPA_SETORES_B3.keys())
            nome_macro = lista_macros[idx_macro]
            
            bot.answer_callback_query(call.id, f"Abrindo {nome_macro}...")
            markup = InlineKeyboardMarkup(row_width=1)
            
            subsetores = list(MAPA_SETORES_B3[nome_macro].keys())
            for idx_sub, sub in enumerate(subsetores):
                ativos_do_sub = MAPA_SETORES_B3[nome_macro][sub]
                
                # 🔴 Só cria o botão do subsetor se você tiver alguma empresa dele
                if any(t in tickers_planilha for t in ativos_do_sub):
                    markup.add(InlineKeyboardButton(f"📂 {sub}", callback_data=f"sub_ac_{idx_macro}_{idx_sub}"))
                
            markup.add(InlineKeyboardButton("🔙 Voltar aos Setores", callback_data="menu_acoes"))
            bot.edit_message_text(f"🏭 **Setor:** {nome_macro}\nSelecione o segmento de atuação:", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- 3ª CAMADA: LISTA DE EMPRESAS (Filtro final) ---
        elif dados.startswith("sub_ac_"):
            matriz = buscar_dados_planilha_com_cache("BD_Acoes")
            tickers_planilha = [linha[0].strip().upper() for linha in matriz[1:] if len(linha) > 0 and linha[0].strip()] if matriz else []

            partes = dados.split("_")
            idx_macro = int(partes[2])
            idx_sub = int(partes[3])
            
            lista_macros = list(MAPA_SETORES_B3.keys())
            nome_macro = lista_macros[idx_macro]
            nome_sub = list(MAPA_SETORES_B3[nome_macro].keys())[idx_sub]
            
            bot.answer_callback_query(call.id, f"Buscando empresas...")
            
            tickers_do_subsetor = MAPA_SETORES_B3[nome_macro][nome_sub]
            
            # 🔴 Filtra a lista fina: só mostra a empresa se ela existir na planilha
            tickers_validos = [t for t in tickers_do_subsetor if t in tickers_planilha]
            
            markup = InlineKeyboardMarkup(row_width=3)
            
            if tickers_validos:
                for ticker in sorted(tickers_validos):
                    markup.add(InlineKeyboardButton(f"📈 {ticker}", callback_data=f"painel_{ticker}_acao"))
                txt = f"📂 **Segmento:** {nome_sub}\nEscolha a empresa para análise:"
            else:
                txt = f"📭 Nenhuma empresa encontrada na planilha para o segmento **{nome_sub}**."
                
            markup.add(InlineKeyboardButton("🔙 Voltar", callback_data=f"macro_ac_{idx_macro}"))
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

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

            # Faz uma consulta rápida para descobrir se é FII ou Ação
            session = SessionDB()
            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
            
            tipo_ativo = "fii" # Padrão de segurança
            if ativo:
                if hasattr(ativo.tipo, 'name'):
                    tipo_ativo = ativo.tipo.name.lower()
                else:
                    tipo_ativo = str(ativo.tipo).replace("TipoAtivo.", "").lower()
            session.close()

            markup = InlineKeyboardMarkup(row_width=1)
            markup.add(InlineKeyboardButton("⚖️ Ir para a Central de Revisão", callback_data="rev_start"))
            
            # 🔴 AGORA O BOTÃO DE VOLTAR É DINÂMICO!
            markup.add(InlineKeyboardButton("🔙 Voltar ao Painel", callback_data=f"painel_{ticker}_{tipo_ativo}"))

            txt = (
                f"⚠️ **Auditoria Necessária: {ticker}**\n\n"
                f"Este ativo possui documentos escaneados ou suspeitos que a IA não conseguiu ler perfeitamente.\n\n"
                f"Por favor, acesse a **Central de Revisão** para categorizá-los e enviá-los ao seu Google Drive."
            )
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # ==========================================
        # --- DADOS NÍVEL 1: ESCOLHER O ANO ---
        # ==========================================
        elif dados.startswith("dados_"):
            bot.answer_callback_query(call.id, "Buscando base de dados...")

            partes = dados.split("_")
            ticker = partes[1]
            tipo_ativo = partes[2]

            markup = InlineKeyboardMarkup(row_width=3)
            session = SessionDB()
            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()

            if tipo_ativo == "acao":
                txt = f"📈 **Histórico Financeiro: {ticker}**\n\nSelecione o ano para análise:"
                if ativo:
                    balancos = session.query(DadosFinanceirosAcoes).filter(DadosFinanceirosAcoes.ativo_id == ativo.id).all()
                    if balancos:
                        anos = sorted(list(set([b.data_referencia.strftime("%Y") for b in balancos if b.data_referencia])), reverse=True)
                        for ano in anos:
                            markup.add(InlineKeyboardButton(f"📅 {ano}", callback_data=f"ano_{ticker}_{tipo_ativo}_{ano}"))
                    else:
                        txt = f"📭 _Os balanços CVM (ITR/DFP) de {ticker} ainda não foram processados._"
                else:
                    txt = f"📭 _Ativo não encontrado no banco de dados local._"
            else:
                informes = session.query(DadosFinanceirosFiis).filter(
                    DadosFinanceirosFiis.ativo_id == ativo.id
                ).order_by(DadosFinanceirosFiis.data_referencia.desc()).limit(4).all()

                if not informes:
                    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Voltar ao Painel", callback_data=f"painel_{ticker}_fii"))
                    bot.edit_message_text(f"📊 Dados Estruturais: {ticker}\n\nNenhum dado contábil encontrado na CVM para este fundo ainda.\n\n👉 Execute o comando /forcar_fiis para atualizar os dados.", chat_id, msg_id, reply_markup=markup)
                    session.close()
                    return

                # 🛡️ TEXTO 100% PLANO (Sem Markdown, zero risco de Erro 400 do Telegram)
                txt = f"Raio-X Contábil: {ticker}\nIndicadores oficiais da CVM\n\n"

                for inf in informes:
                    mes_ano = inf.data_referencia.strftime("%m/%Y")

                    if inf.patrimonio_liquido:
                        pl_fmt = f"R$ {inf.patrimonio_liquido/1000000000:.2f} Bi" if inf.patrimonio_liquido >= 1000000000 else f"R$ {inf.patrimonio_liquido/1000000:.2f} Mi"
                    else:
                        pl_fmt = "N/A"

                    caixa_fmt = f"R$ {inf.disponibilidades_caixa/1000000:.2f} Mi" if inf.disponibilidades_caixa else "N/A"
                    cotistas = f"{inf.cotistas:,}".replace(",", ".") if inf.cotistas else "N/A"

                    txt += f"Referência: {mes_ano}\n"
                    txt += f"Patrimônio Líquido: {pl_fmt}\n"
                    txt += f"Total de Cotistas: {cotistas}\n"
                    txt += f"Caixa / Disponível: {caixa_fmt}\n"
                    txt += "--------------------\n"

                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("🔙 Voltar ao Painel", callback_data=f"painel_{ticker}_fii"))

            session.close()

            # Envia sem parse_mode para garantir que NUNCA mais dê erro 400
            try:
                bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup)
            except Exception as e:
                bot.edit_message_text(f"❌ Erro ao exibir dados: {str(e)[:100]}", chat_id, msg_id, reply_markup=markup)

        # ==========================================
        # --- DADOS NÍVEL 2: ESCOLHER O TRIMESTRE ---
        # ==========================================
        elif dados.startswith("ano_"):
            bot.answer_callback_query(call.id, "Carregando trimestres...")

            partes = dados.split("_")
            ticker = partes[1]
            tipo_ativo = partes[2]
            ano_escolhido = partes[3]

            markup = InlineKeyboardMarkup(row_width=1)
            session = SessionDB()
            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()

            balancos = session.query(DadosFinanceirosAcoes).filter(
                DadosFinanceirosAcoes.ativo_id == ativo.id,
                DadosFinanceirosAcoes.data_referencia >= f"{ano_escolhido}-01-01",
                DadosFinanceirosAcoes.data_referencia <= f"{ano_escolhido}-12-31"
            ).all()

            datas = sorted(list(set([b.data_referencia.strftime("%Y-%m-%d") for b in balancos if b.data_referencia])), reverse=True)

            for dt in datas:
                ano, mes_num, dia = dt.split('-')
                if mes_num == '03': tri = '1º Trimestre (ITR)'
                elif mes_num == '06': tri = '2º Trimestre (ITR)'
                elif mes_num == '09': tri = '3º Trimestre (ITR)'
                elif mes_num == '12': tri = '4º Tri / Consolidado Anual (DFP)'
                else: tri = f'Mês {mes_num}'

                markup.add(InlineKeyboardButton(f"📊 {tri}", callback_data=f"mes_{ticker}_{tipo_ativo}_{dt}"))

            markup.add(InlineKeyboardButton("🔙 Voltar aos Anos", callback_data=f"dados_{ticker}_{tipo_ativo}"))
            session.close()
            txt_ano = f"📅 **Exercício {ano_escolhido}: {ticker}**\n\nSelecione o período desejado:"

            # 🛡️ PARAQUEDAS ANTI-ERRO 400
            try:
                bot.edit_message_text(txt_ano, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")
            except Exception as e:
                if "can't parse entities" in str(e).lower() or "bad request" in str(e).lower():
                    # Tira o Markdown e manda puro
                    bot.edit_message_text(txt_ano, chat_id, msg_id, reply_markup=markup)
                else:
                    bot.edit_message_text(f"❌ Erro ao exibir anos: {str(e)[:100]}", chat_id, msg_id, reply_markup=markup)

        # ==========================================
        # --- DADOS NÍVEL 3: EXIBIR RAIO-X COMPLETO ---
        # ==========================================
        elif dados.startswith("mes_"):
            bot.answer_callback_query(call.id, "Gerando Raio-X...")
            partes = dados.split("_", 3)
            ticker = partes[1]
            tipo_ativo = partes[2]
            data_ref = partes[3]

            session = SessionDB()
            try:
                ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
                from datetime import datetime
                data_formatada = datetime.strptime(data_ref, "%Y-%m-%d").date()

                balanco = session.query(DadosFinanceirosAcoes).filter(
                    DadosFinanceirosAcoes.ativo_id == ativo.id,
                    DadosFinanceirosAcoes.data_referencia == data_formatada
                ).first()

                if balanco:
                    def formata_rs(valor):
                        if valor is None or valor == "N/A": return "N/A"
                        try:
                            return f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                        except:
                            return "N/A"

                    divida_liquida_str = "N/A"
                    if balanco.divida_bruta is not None and balanco.caixa is not None:
                        divida_liquida_str = formata_rs(balanco.divida_bruta - balanco.caixa)

                    margem_ebitda = "N/A"
                    if balanco.ebitda is not None and balanco.receita and balanco.receita > 0:
                        margem_ebitda = f"{((balanco.ebitda / balanco.receita) * 100):.1f}%"

                    margem_liquida = "N/A"
                    if balanco.lucro_liquido is not None and balanco.receita and balanco.receita > 0:
                        margem_liquida = f"{((balanco.lucro_liquido / balanco.receita) * 100):.1f}%"

                    ano, mes_num, dia = data_ref.split('-')
                    if mes_num == '03': tri_str = '1º Trimestre'
                    elif mes_num == '06': tri_str = '2º Trimestre'
                    elif mes_num == '09': tri_str = '3º Trimestre'
                    elif mes_num == '12': tri_str = '4º Trimestre (Anual)'
                    else: tri_str = f'Mês {mes_num}'

                    txt = (
                        f"📊 **Balanço CVM: {ticker}**\n"
                        f"📅 **Período:** {tri_str} de {ano}\n\n"
                        f"⚖️ **BALANÇO PATRIMONIAL**\n"
                        f"🏦 **Ativo Total:** R$ {formata_rs(balanco.ativo_total)}\n"
                        f"🏢 **Patrimônio Líquido:** R$ {formata_rs(balanco.patrimonio_liquido)}\n"
                        f"💵 **Caixa:** R$ {formata_rs(balanco.caixa)}\n"
                        f"📉 **Dívida Líquida:** R$ {divida_liquida_str}\n\n"
                        f"⚙️ **D.R.E. (RESULTADOS)**\n"
                        f"💰 **Receita Líquida:** R$ {formata_rs(balanco.receita)}\n"
                        f"🏭 **EBITDA:** R$ {formata_rs(balanco.ebitda)} *(Margem: {margem_ebitda})*\n"
                        f"📉 **Resultado Financeiro:** R$ {formata_rs(balanco.resultado_financeiro)}\n"
                        f"💵 **Lucro Líquido:** R$ {formata_rs(balanco.lucro_liquido)} *(Margem: {margem_liquida})*\n\n"
                        f"💸 **FLUXO DE CAIXA**\n"
                        f"🔄 **FCO (Operacional):** R$ {formata_rs(balanco.fco)}"
                    )
                else:
                    ano_escolhido = data_ref.split('-')[0]
                    txt = f"📭 Os dados não foram encontrados no banco."
                    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Voltar", callback_data=f"ano_{ticker}_{tipo_ativo}_{ano_escolhido}"))
                    bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")
                    return

                ano_escolhido = data_ref.split('-')[0]
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("❓ Entender os Indicadores", callback_data=f"ajuda_cvm_{ticker}_menu"))
                markup.add(
                    InlineKeyboardButton("🔙 Voltar aos Trimestres", callback_data=f"ano_{ticker}_{tipo_ativo}_{ano_escolhido}"),
                    InlineKeyboardButton("🔙 Voltar ao Painel", callback_data=f"painel_{ticker}_{tipo_ativo}")
                )

                # 🛡️ PARAQUEDAS ANTI-ERRO 400 OBRIGATÓRIO AQUI TAMBÉM:
                try:
                    bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")
                except Exception as e:
                    if "can't parse entities" in str(e).lower() or "bad request" in str(e).lower():
                        bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup)
                    else:
                        bot.edit_message_text(f"❌ Erro ao exibir: {str(e)[:100]}", chat_id, msg_id, reply_markup=markup)
            
            except Exception as e:
                print(f"Erro ao buscar balanço da ação: {e}")
                bot.answer_callback_query(call.id, "❌ Erro ao abrir balanço!")
            finally:
                session.close()

        # ==========================================
        # --- NÍVEL 1: DOCUMENTOS (BIFURCAÇÃO) ---
        # ==========================================
        elif dados.startswith("docs_"):
            bot.answer_callback_query(call.id, "Acessando o arquivo...")
            
            partes = dados.split("_")
            ticker = partes[1]
            tipo_ativo = partes[2] 

            markup = InlineKeyboardMarkup(row_width=2)
            session = SessionDB()
            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()

            if ativo:
                # Checa se existe QUALQUER documento salvo para esse ativo
                tem_docs = session.query(DocumentosQualitativos).filter(
                    DocumentosQualitativos.ativo_id == ativo.id,
                    DocumentosQualitativos.status_processamento.ilike("%SALVO_DRIVE%")
                ).first()

                if tem_docs:
                    # 🔀 A BIFURCAÇÃO MÁGICA
                    markup.add(
                        InlineKeyboardButton("📂 Filtrar por Tipo", callback_data=f"dnav_{ticker}_t"),
                        InlineKeyboardButton("📅 Filtrar por Mês", callback_data=f"dnav_{ticker}_m")
                    )
                    txt = f"🗄️ **Arquivo Central: {ticker}**\n\nComo você deseja procurar os documentos?"
                else:
                    termo = "o fundo" if tipo_ativo == "fii" else "a empresa"
                    txt = f"📭 **Ainda não há documentos processados para {termo} {ticker}.**"
            else:
                txt = f"❌ Ativo **{ticker}** não encontrado no banco de dados."

            markup.add(InlineKeyboardButton("🔙 Voltar ao Painel", callback_data=f"painel_{ticker}_{tipo_ativo}"))
            session.close()
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # ==========================================
        # --- NÍVEL 2: NAVEGAÇÃO (TIPOS OU MESES) ---
        # ==========================================
        elif dados.startswith("dnav_"):
            bot.answer_callback_query(call.id, "Listando opções...")
            partes = dados.split("_")
            ticker = partes[1]
            modo = partes[2] # 't' para Tipo, 'm' para Mês

            session = SessionDB()
            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
            tipo_ativo = getattr(ativo.tipo, 'name', str(ativo.tipo)).replace("TipoAtivo.", "").lower() if ativo else "acao"

            docs = session.query(DocumentosQualitativos).filter(
                DocumentosQualitativos.ativo_id == ativo.id,
                DocumentosQualitativos.status_processamento.ilike("%SALVO_DRIVE%")
            ).all()

            markup = InlineKeyboardMarkup(row_width=1)

            if docs:
                if modo == 't':
                    # --- NAVEGAÇÃO POR TIPO ---
                    tipos_unicos = sorted(list(set([d.tipo_documento for d in docs if d.tipo_documento])))
                    for tipo_doc in tipos_unicos:
                        t_low = tipo_doc.lower()
                        if "gerencial" in t_low: emoji = "📊"
                        elif "fato" in t_low: emoji = "🚨"
                        elif "aviso" in t_low or "provento" in t_low: emoji = "💰"
                        elif "assembleia" in t_low or "vota" in t_low: emoji = "🗳️"
                        elif "trimestral" in t_low or "informe" in t_low: emoji = "📑"
                        else: emoji = "📄" 
                        
                        # Usa o nome cortado para não estourar o limite de 64 bytes do Telegram
                        callback_seguro = f"dl_{ticker}_t_{tipo_doc[:25]}"
                        markup.add(InlineKeyboardButton(f"{emoji} {tipo_doc}", callback_data=callback_seguro))
                    txt = f"📂 **Filtro por Tipo: {ticker}**\n\nSelecione a categoria:"

                elif modo == 'm':
                    # --- NAVEGAÇÃO POR MÊS ---
                    meses_unicos = []
                    for d in docs:
                        mes_str = "0000-00"
                        if d.assunto and '-' in d.assunto:
                            p = d.assunto.split(" ")[0].split("-") 
                            if len(p) == 3: mes_str = f"{p[2]}-{p[1]}" 
                        elif d.data_publicacao:
                            mes_str = d.data_publicacao.strftime("%Y-%m")
                        if mes_str not in meses_unicos: meses_unicos.append(mes_str)
                    
                    meses_unicos.sort(reverse=True)
                    
                    # Cria a tela com 2 botões por linha para os meses (fica mais bonito)
                    markup = InlineKeyboardMarkup(row_width=2)
                    botoes_meses = []
                    for mes in meses_unicos[:14]: # Mostra até 14 meses
                        if mes == "0000-00": nome_btn = "📅 Sem Data"
                        else: nome_btn = f"📅 {mes.split('-')[1]}/{mes.split('-')[0]}"
                        botoes_meses.append(InlineKeyboardButton(nome_btn, callback_data=f"dl_{ticker}_m_{mes}"))
                    
                    markup.add(*botoes_meses)
                    txt = f"📅 **Filtro por Mês: {ticker}**\n\nSelecione o período (Ano/Mês):"

            markup.row(InlineKeyboardButton("🔙 Voltar ao Arquivo", callback_data=f"docs_{ticker}_{tipo_ativo}"))
            session.close()
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # ==========================================
        # --- NÍVEL 3: LISTAGEM FINAL DE PDFS ---
        # ==========================================
        elif dados.startswith("dl_"):
            bot.answer_callback_query(call.id, "Puxando documentos...")
            partes = dados.split("_", 3)
            ticker = partes[1]
            modo = partes[2] # 't' (tipo) ou 'm' (mês)
            valor = partes[3]

            markup = InlineKeyboardMarkup(row_width=1)
            session = SessionDB()
            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()

            todos_docs = session.query(DocumentosQualitativos).filter(
                DocumentosQualitativos.ativo_id == ativo.id,
                DocumentosQualitativos.status_processamento.ilike("%SALVO_DRIVE%")
            ).all()

            docs_finais = []
            if modo == 't':
                docs_finais = [d for d in todos_docs if d.tipo_documento and d.tipo_documento.startswith(valor)]
                txt = f"📂 **{valor} ({ticker})**\n\n"
            else:
                for d in todos_docs:
                    mes_str = "0000-00"
                    if d.assunto and '-' in d.assunto:
                        p = d.assunto.split(" ")[0].split("-")
                        if len(p) == 3 and len(p[2]) == 4: mes_str = f"{p[2]}-{p[1]}"
                        elif len(p) == 3 and len(p[0]) == 4: mes_str = f"{p[0]}-{p[1]}"
                    elif d.data_publicacao:
                        mes_str = d.data_publicacao.strftime("%Y-%m")
                    if mes_str == valor: docs_finais.append(d)
                
                txt = f"📅 **Documentos de {valor.split('-')[1]}/{valor.split('-')[0]} ({ticker})**\n\n" if valor != "0000-00" else f"📅 **Documentos Diversos ({ticker})**\n\n"

            # Dicionário de Resumos Explicativos
            resumos_genericos = {
                "fato relevante": "Comunicado oficial sobre decisões estratégicas da gestão.",
                "demonstrações financeiras": "Balanço contábil auditado com receitas, custos e lucro.",
                "relatório gerencial": "Relatório de acompanhamento do fundo e seus ativos.",
                "aviso aos acionistas": "Informativo sobre proventos (dividendos/JCP) e subscrições.",
                "aviso aos cotistas": "Informativo oficial aos cotistas sobre rendimentos.",
                "apresentação": "Apresentação em slides detalhando os resultados corporativos."
            }

            for doc in sorted(docs_finais, key=lambda x: x.id, reverse=True):
                # 🔴 APLICAÇÃO DA NOVA DATA REAL
                data_limpa = extrair_data_real(doc)

                # Extrai o resumo da IA ou aplica o fallback genérico
                resumo_texto = getattr(doc, 'resumo_ia', None)
                if not resumo_texto or resumo_texto.strip() == "":
                    tipo_low = doc.tipo_documento.lower() if doc.tipo_documento else ""
                    for chave, desc in resumos_genericos.items():
                        if chave in tipo_low:
                            resumo_texto = desc
                            break
                    if not resumo_texto:
                        resumo_texto = "Documento oficial arquivado na nuvem."

                # Monta a estrutura limpa e profissional
                if modo == 'm':
                    txt += f"📄 **{doc.tipo_documento}**\n"
                txt += f"📅 **Data:** `{data_limpa}`\n"
                txt += f"📝 _{resumo_texto}_\n\n"

                url = doc.url_pdf if (doc.url_pdf and str(doc.url_pdf).startswith("http")) else "https://drive.google.com"
                markup.add(InlineKeyboardButton(f"🔗 Abrir PDF ({data_limpa})", url=url))

            markup.add(InlineKeyboardButton("🔙 Voltar aos Filtros", callback_data=f"dnav_{ticker}_{modo}"))
            session.close()
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")
            
    except Exception as e:
        # 🛡️ Se o erro for apenas o clique duplo idêntico do Telegram, ignora silenciosamente
        if "message is not modified" in str(e):
            pass
        else:
            print(f"Erro no callback geral: {e}")
            try:
                bot.answer_callback_query(call.id, f"⚠️ Erro interno. Tente novamente.")
            except:
                pass
