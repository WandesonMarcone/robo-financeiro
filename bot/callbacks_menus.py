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

        # --- MÓDULO FIIs HIERÁRQUICO DINÂMICO ---
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
                    # LÓGICA DINÂMICA:
                    # 1. Pega a coluna 1 (Tipo) de todas as linhas
                    # 2. .strip() para limpar espaços em branco
                    # 3. set() para remover duplicatas
                    # 4. sorted() para deixar em ordem alfabética
                    tipos_unicos = sorted(list(set(
                        linha[1].strip() for linha in matriz[1:] 
                        if len(linha) > 1 and linha[1].strip()
                    )))

                    # Cria um botão para cada tipo encontrado
                    for t in tipos_unicos:
                        markup.add(InlineKeyboardButton(f"🏢 {t}", callback_data=f"tipo_fii_{t}"))
            except Exception as e:
                print(f"Erro ao listar tipos dinâmicos: {e}")

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
                    setores_acoes = sorted(list(set(linha[1].strip() for linha in matriz[1:] if linha[1].strip())))
                    
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
            
            # Identifica contexto baseada nos dados do callback
            is_fii = (dados == "favoritos_fiis")
            tipo = "fii" if is_fii else "acao"
            menu_voltar = "menu_fiis" if is_fii else "menu_acoes"

            # Busca a lista já pronta do seu config via a função que criamos
            favs = buscar_favoritos(tipo)
            
            markup = InlineKeyboardMarkup(row_width=3)
            
            if favs:
                # Cria os botões para cada ticker favorito
                botoes = [InlineKeyboardButton(tkr, callback_data=f"{tipo}_{tkr}") for tkr in favs]
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

        # --- NÍVEL 1: MENU DE TIPOS DINÂMICOS (FIIs e Ações) ---
        elif dados.startswith("docs_"):
            partes = dados.split("_")
            ticker = partes[1]
            tipo_ativo = partes[2]  # "fii" ou "acao"

            markup = InlineKeyboardMarkup(row_width=1)
            session = SessionDB()
            
            # Inicialização de variáveis de controle
            encontrou_dados = False
            txt = ""
            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()

            if ativo:
                # --- LÓGICA DE FIIs ---
                if tipo_ativo == "fii":
                    tipos_existentes = session.query(DocumentosQualitativos.tipo_documento).filter(
                        DocumentosQualitativos.ativo_id == ativo.id,
                        DocumentosQualitativos.status_processamento == "SALVO_DRIVE"
                    ).distinct().all()

                    if tipos_existentes:
                        encontrou_dados = True
                        for (tipo_doc,) in tipos_existentes:
                            emoji = "📊" if "Gerencial" in tipo_doc else "🚨" if "Fato" in tipo_doc else "📄"
                            markup.add(InlineKeyboardButton(f"{emoji} {tipo_doc}", callback_data=f"doctipo_{ticker}_{tipo_doc}"))
                        txt = f"📂 **Gaveta de Documentos: {ticker}**\n\nO que você deseja acessar?"
                    else:
                        txt = f"📭 **A gaveta de {ticker} está vazia!**"

                # --- LÓGICA DE AÇÕES ---
                elif tipo_ativo == "acao":
                    balancos = session.query(DadosFinanceirosAcoes).filter(DadosFinanceirosAcoes.ativo_id == ativo.id).all()
                    if balancos:
                        encontrou_dados = True
                        datas_unicas = sorted(list(set([b.data_referencia.strftime("%Y-%m-%d") for b in balancos if b.data_referencia])), reverse=True)
                        
                        for dt in datas_unicas[:5]:
                            ano, mes_num, dia = dt.split('-')
                            markup.add(InlineKeyboardButton(f"📊 Balanço CVM ({mes_num}/{ano})", callback_data=f"mes_{ticker}_{tipo_ativo}_{dt}"))
                        
                        txt = f"📅 **Histórico de {ticker}**\n\nEscolha o balanço que você deseja analisar:"
                    else:
                        txt = f"📭 **Nenhum balanço encontrado para {ticker}.**"
            else:
                txt = "❌ Ativo não encontrado no sistema."

            # Finalização comum (Botão Voltar)
            markup.add(InlineKeyboardButton(f"🔙 Voltar para {ticker}", callback_data=f"{tipo_ativo}_{ticker}"))
            
            session.close() # Fechamos a sessão apenas uma vez aqui
            
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- NÍVEL 2: MENU DE MESES (Baseado no Tipo Escolhido) ---
        elif dados.startswith("doctipo_"):
            partes = dados.split("_")
            ticker = partes[1]
            tipo_doc = partes[2]
            tipo_ativo = "fii" if "fii" in dados else "acao" 

            markup = InlineKeyboardMarkup(row_width=2)
            session = SessionDB()
            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
            txt = "" # Inicializamos a variável de texto

            if tipo_ativo == "fii":
                docs = session.query(DocumentosQualitativos).filter(
                    DocumentosQualitativos.ativo_id == ativo.id,
                    DocumentosQualitativos.tipo_documento == tipo_doc,
                    DocumentosQualitativos.status_processamento == "SALVO_DRIVE"
                ).order_by(DocumentosQualitativos.data_publicacao.desc()).all()

                if docs:
                    meses_unicos = []
                    for d in docs:
                        if d.data_publicacao:
                            mes_str = d.data_publicacao.strftime("%Y-%m")
                            if mes_str not in meses_unicos:
                                meses_unicos.append(mes_str)

                    for mes in meses_unicos[:10]:
                        ano, mes_num = mes.split('-')
                        markup.add(InlineKeyboardButton(f"📅 {mes_num}/{ano}", callback_data=f"docmes_{ticker}_{tipo_doc}_{mes}"))
                
                txt = f"📅 **{tipo_doc} - {ticker}**\n\nSelecione o período:"
                markup.add(InlineKeyboardButton("🔙 Voltar aos Tipos", callback_data=f"docs_{ticker}_fii"))

            elif tipo_ativo == "acao":
                # --- Lógica futura para PDFs de Ações ---
                txt = f"📂 **Documentos de Ações: {ticker}**\n\nEm breve, o robô suportará PDFs de ações aqui!"
                markup.add(InlineKeyboardButton("🔙 Voltar", callback_data=f"docs_{ticker}_acao"))

            # Fechamos a sessão e editamos a mensagem apenas uma vez, após decidir o que mostrar
            session.close()
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- NÍVEL 3: MOSTRANDO OS ARQUIVOS FINAIS (PDF) ---
        elif dados.startswith("docmes_"):
            partes = dados.split("_")
            ticker = partes[1]
            tipo_doc = partes[2]
            periodo = partes[3]

            markup = InlineKeyboardMarkup(row_width=1)
            session = SessionDB()

            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
            docs = session.query(DocumentosQualitativos).filter(
                DocumentosQualitativos.ativo_id == ativo.id,
                DocumentosQualitativos.tipo_documento == tipo_doc
            ).all()

            docs_do_mes = [d for d in docs if d.data_publicacao and d.data_publicacao.strftime("%Y-%m") == periodo]

            ano, mes_num = periodo.split('-')
            txt = f"📂 **{tipo_doc}: {ticker} ({mes_num}/{ano})**\n\nEstes são os documentos salvos no Drive:"

            for doc in docs_do_mes:
                markup.add(InlineKeyboardButton(f"🔗 Abrir PDF ({doc.assunto})", url=doc.url_pdf))

            session.close()
            markup.add(InlineKeyboardButton("🔙 Voltar aos Meses", callback_data=f"doctipo_{ticker}_{tipo_doc}"))
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

        # --- NÍVEL 4: DETALHE DO BALANÇO (Ações) ---
        elif dados.startswith("mes_"):
            partes = dados.split("_")
            ticker = partes[1]
            tipo = partes[2] # 'acao'
            periodo = partes[3]
            
            markup = InlineKeyboardMarkup()
            session = SessionDB()
            
            ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
            txt = ""

            if tipo == "acao":
                balanco = session.query(DadosFinanceirosAcoes).filter(
                    DadosFinanceirosAcoes.ativo_id == ativo.id, 
                    DadosFinanceirosAcoes.data_referencia == periodo
                ).first()

                if balanco:
                    # Extrai ano/mes para o título
                    ano, mes_num, dia = periodo.split('-')
                    
                    # Função auxiliar local (mantida dentro para encapsulamento)
                    def formata_rs(valor):
                        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if valor else "Não divulgado"

                    txt = (
                        f"📊 **Relatório Financeiro: {ticker}**\n"
                        f"📅 **Referência:** {mes_num}/{ano}\n"
                        f"_Dados oficiais extraídos da CVM_\n\n"
                        f"💰 **Receita:** {formata_rs(balanco.receita)}\n"
                        f"💸 **Lucro Líquido:** {formata_rs(balanco.lucro_liquido)}\n"
                        f"🏦 **Caixa:** {formata_rs(balanco.caixa)}\n"
                        f"📉 **Passivo Total:** {formata_rs(balanco.passivo_total)}"
                    )
                else:
                    txt = f"⚠️ **Ops!** Dados financeiros não encontrados para {ticker} ({periodo})."
            
            # Botão de voltar padronizado (Igual ao Nível 3 de FIIs)
            markup.add(InlineKeyboardButton("🔙 Voltar aos Meses", callback_data=f"docs_{ticker}_{tipo}"))

            session.close()
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