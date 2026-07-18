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

        elif dados.startswith("fii_") or dados.startswith("acao_"):
            partes = dados.split("_")
            tipo = partes[0] 
            ticker = partes[1]
            bot.answer_callback_query(call.id, f"Carregando terminal de {ticker}...")
            # Envia a requisição para gerar o "Dashboard" do ativo com Logo e Indicadores
            gerar_painel_ativo(ticker, tipo, chat_id, msg_id)

        # =======================================================
        # 2. SUBMENU: DADOS COMPLETOS (Puxa da sua Planilha)
        # =======================================================
        elif dados.startswith("dados_"):
            bot.answer_callback_query(call.id, "Buscando indicadores...")
            partes = dados.split("_")
            ticker, tipo = partes[1], partes[2]
            is_fii = (tipo == "fii")
            
            # Puxa os dados reais da sua função recém-criada
            indicadores = buscar_dados_planilha(ticker, is_fii)
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))
            
            if not indicadores:
                bot.edit_message_text(f"❌ Não encontrei os dados detalhados de **{ticker}** na planilha.", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")
            else:
                # Monta um relatório robusto baseado no tipo do ativo
                if is_fii:
                    texto = (
                        f"📎 **Dados Completos: {ticker}**\n\n"
                        f"🏢 **Setor:** {indicadores.get('setor', 'N/A')}\n"
                        f"💰 **Preço:** R$ {indicadores.get('preco', 'N/A')}\n"
                        f"⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n"
                        f"💸 **DY (12m):** {indicadores.get('dy', 'N/A')}\n"
                        f"💵 **Valor Patrimonial (VPA):** {indicadores.get('vpa', 'N/A')}\n\n"
                        f"_(Você pode mapear mais colunas lá no dicionário da função buscar_dados_planilha)_"
                    )
                else:
                    texto = (
                        f"📎 **Dados Completos: {ticker}**\n\n"
                        f"📈 **Setor:** {indicadores.get('setor', 'N/A')}\n"
                        f"💰 **Preço:** R$ {indicadores.get('preco', 'N/A')}\n"
                        f"📊 **P/L:** {indicadores.get('pl', 'N/A')}\n"
                        f"⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n"
                        f"💸 **DY (12m):** {indicadores.get('dy', 'N/A')}\n"
                        f"🚀 **ROE:** {indicadores.get('roe', 'N/A')}\n\n"
                        f"_(Você pode mapear mais colunas lá no dicionário da função buscar_dados_planilha)_"
                    )
                bot.edit_message_text(texto, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # ==============================================================
        # NÍVEL 1: MENU DE MESES (Quando clica em "Documentos")
        # ==============================================================
        elif dados.startswith("docs_"):
            # CORREÇÃO 1: Ordem exata -> docs_TICKER_TIPO
            partes = dados.split("_")
            ticker = partes[1]
            tipo = partes[2]
            
            markup = InlineKeyboardMarkup()
            session = SessionDB()

            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
            encontrou_dados = False

            if ativo:
                if tipo == "fii":
                    # Puxa todos os documentos do FII
                    docs = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.ativo_id == ativo.id).all()
                    if docs:
                        encontrou_dados = True
                        # Pega apenas os meses únicos (Ex: '2026-04') e ordena do mais novo pro mais velho
                        meses_unicos = sorted(list(set([d.data_publicacao.strftime("%Y-%m") for d in docs if d.data_publicacao])), reverse=True)

                        for mes in meses_unicos[:10]:
                            qtd = len([d for d in docs if d.data_publicacao and d.data_publicacao.strftime("%Y-%m") == mes])
                            ano, mes_num = mes.split('-')
                            # CORREÇÃO 2: Botão do Mês padronizado (mes_TICKER_TIPO_PERIODO)
                            markup.add(InlineKeyboardButton(f"📁 {mes_num}/{ano} ({qtd} arquivos)", callback_data=f"mes_{ticker}_{tipo}_{mes}"))

                elif tipo == "acao":
                    from pipeline_dados.banco_dados import DadosFinanceirosAcoes
                    # Puxa todos os balanços processados pelo módulo CVM
                    balancos = session.query(DadosFinanceirosAcoes).filter(DadosFinanceirosAcoes.ativo_id == ativo.id).all()
                    if balancos:
                        encontrou_dados = True
                        # Pega as datas de referência únicas
                        datas_unicas = sorted(list(set([b.data_referencia.strftime("%Y-%m-%d") for b in balancos if b.data_referencia])), reverse=True)

                        for dt in datas_unicas[:5]:
                            ano, mes_num, dia = dt.split('-')
                            markup.add(InlineKeyboardButton(f"📊 Balanço CVM ({mes_num}/{ano})", callback_data=f"mes_{ticker}_{tipo}_{dt}"))

            session.close()

            # Botões padrão de fundo
            cat_status = "fundos-imobiliarios" if tipo == "fii" else "acoes"
            markup.row(InlineKeyboardButton("📈 Ver no StatusInvest", url=f"https://statusinvest.com.br/{cat_status}/{ticker.lower()}"))
            
            # CORREÇÃO 3: Botão de voltar consertado (Aponta direto para fii_MXRF11 ou acao_PETR4)
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))

            if encontrou_dados:
                txt = f"📅 **Histórico de {ticker}**\n\nEscolha o período que você deseja analisar:"
            else:
                txt = f"📭 **Nenhum dado encontrado para {ticker}**\nO robô ainda não processou arquivos ou balanços para este ativo."

            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # ==============================================================
        # NÍVEL 2: MOSTRANDO OS ARQUIVOS OU RELATÓRIO CVM
        # ==============================================================
        elif dados.startswith("mes_"):
            # CORREÇÃO 4: Lendo na nova ordem padronizada
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
                from pipeline_dados.banco_dados import DadosFinanceirosAcoes
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

            # CORREÇÃO 5: O Botão de voltar consertado para retornar ao menu de meses
            markup.add(InlineKeyboardButton("🔙 Voltar aos Meses", callback_data=f"docs_{ticker}_{tipo}"))

            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # =======================================================
        # 4. SUBMENU: ANÁLISE DE IA (Placeholder de Luxo)
        # =======================================================
        elif dados.startswith("ia_"):
            bot.answer_callback_query(call.id, "Gerando análise avançada...")
            partes = dados.split("_")
            ticker, tipo = partes[1], partes[2]
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo}_{ticker}"))
            
            # Um aviso profissional até você conectar a API do Gemini/OpenAI
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
        print(f"Erro no callback: {e}")
