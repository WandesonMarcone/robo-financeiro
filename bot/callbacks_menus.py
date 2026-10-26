import logging
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Imports base e configurações
from bot.loader import bot
from bot import menu_principal, permissoes
from bot.telegram_utils import (
    TEXTO_ACESSO_NEGADO,
    markup_menu_ajuda,
    montar_guia_comandos,
    editar_texto_ou_caption,
    responder_callback_desconhecido,
)
from config import SPREADSHEET_URL, MAPA_SETORES_B3
from modules.taxonomia_fiis import dados_linha_fii, MACROS_FII

# Banco de Dados
from atualizador_documentos import SessionDB
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos, DadosFinanceirosAcoes, DadosFinanceirosFiis

# Serviços Inteligentes (Planilhas e Painéis)
from services.dashboard_menus import buscar_oportunidades, gerar_painel_ativo, buscar_favoritos, filtrar_ativos_por_setor, extrair_data_real
from services.planilhas import buscar_dados_planilha_com_cache, buscar_ativo_na_planilha
from pipeline_dados.identidade_visual import agrupar_tickers_por_empresa, raiz_ticker
from modules.relatorio_mercado import (
    callback_analise_ou_classes,
    rotulo_empresa,
    rotulo_ticker,
    setor_presente_na_planilha,
    tickers_do_segmento_b3,
)

logger = logging.getLogger(__name__)


def _atualizar_mensagem(call, texto, markup=None, parse_mode="Markdown"):
    """Edita texto ou caption (painel-foto) sem o Telegram recusar."""
    mensagem = getattr(call, "message", None)
    chat = getattr(mensagem, "chat", None) if mensagem is not None else None
    editar_texto_ou_caption(
        bot,
        getattr(chat, "id", None),
        getattr(mensagem, "message_id", None) if mensagem is not None else None,
        texto,
        reply_markup=markup,
        parse_mode=parse_mode,
        message=mensagem,
    )


def _markup_voltar_ativo(ticker, tipo):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            "🔙 Voltar ao Painel", callback_data=f"painel_{ticker}_{tipo}"
        )
    )
    return markup


def _abrir_painel_ativo(call, ticker, tipo, chat_id, msg_id):
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    gerar_painel_ativo(
        ticker, tipo, chat_id, msg_id, message=getattr(call, "message", None)
    )


# ==========================================
# ----- CALLBACKS DO PAINEL PERSONALIZADO -----
# ==========================================
# Registrados ANTES do handler generico (``callback_geral``) para que os botoes
# do painel inicial nao caiam no fluxo "botao invalido". Reutilizam os servicos
# e repositorios ja existentes (favoritos por usuario, documentos, cadastro).

@bot.callback_query_handler(func=lambda call: call.data == "voltar_painel")
def callback_voltar_painel(call):
    """Retorna ao painel personalizado, editando a mensagem atual."""
    autor = getattr(call, "from_user", None)
    menu_principal.responder_callback(call)
    chat_id, message_id = menu_principal.chat_e_message(call)
    menu_principal.editar_painel(
        chat_id,
        message_id,
        getattr(autor, "id", None),
        autor,
        message=getattr(call, "message", None),
    )


@bot.callback_query_handler(func=lambda call: call.data == "novos_documentos")
def callback_novos_documentos(call):
    """Lista os últimos documentos capturados (recurso já existente)."""
    telegram_id, _papel, _dto, erro = menu_principal.usuario_autorizado(call)
    if erro:
        menu_principal.responder_callback(call, erro)
        return
    # Administrador: visão ampla (None). Usuário comum: só favoritos ativos.
    permitidos = permissoes.tickers_permitidos(telegram_id)
    menu_principal.responder_callback(call)
    menu_principal.editar_callback(
        call,
        menu_principal.texto_novos_documentos(tickers_permitidos=permitidos),
        menu_principal.markup_voltar(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "minha_carteira")
def callback_minha_carteira(call):
    """Exibe os ativos acompanhados pelo próprio usuário (sua carteira)."""
    _telegram_id, _papel, dto, erro = menu_principal.usuario_autorizado(call)
    if erro:
        menu_principal.responder_callback(call, erro)
        return
    if dto is None:
        menu_principal.responder_callback(call, menu_principal.TEXTO_SEM_CONTA)
        menu_principal.editar_callback(
            call, menu_principal.TEXTO_SEM_CONTA, menu_principal.markup_voltar()
        )
        return
    try:
        repositorio = menu_principal.RepositorioFavoritos()
        favoritos_fii = repositorio.listar(dto.id, "fii")
        favoritos_acao = repositorio.listar(dto.id, "acao")
    except Exception:
        logger.warning("MENU - falha ao carregar carteira", exc_info=True)
        menu_principal.responder_callback(call, menu_principal.TEXTO_ERRO_BANCO)
        menu_principal.editar_callback(
            call, menu_principal.TEXTO_ERRO_BANCO, menu_principal.markup_voltar()
        )
        return
    menu_principal.responder_callback(call)
    texto, markup = menu_principal.texto_carteira(favoritos_fii, favoritos_acao)
    menu_principal.editar_callback(call, texto, markup)


@bot.callback_query_handler(func=lambda call: call.data == "meus_alertas")
def callback_meus_alertas(call):
    """Lista eventos persistidos dos favoritos do próprio usuário."""
    _telegram_id, _papel, dto, erro = menu_principal.usuario_autorizado(call)
    if erro:
        menu_principal.responder_callback(call, erro)
        return
    if dto is None:
        menu_principal.responder_callback(call, menu_principal.TEXTO_SEM_CONTA)
        menu_principal.editar_callback(
            call, menu_principal.TEXTO_SEM_CONTA, menu_principal.markup_voltar()
        )
        return
    menu_principal.responder_callback(call)
    menu_principal.editar_callback(
        call,
        menu_principal.texto_meus_alertas(dto.id),
        menu_principal.markup_voltar(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "gerenciar_favoritos")
def callback_gerenciar_favoritos(call):
    """Abre o submenu de gerenciamento dos favoritos individuais."""
    _telegram_id, _papel, _dto, erro = menu_principal.usuario_autorizado(call)
    if erro:
        menu_principal.responder_callback(call, erro)
        return
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🏢 FIIs", callback_data="favoritos_fiis"),
        InlineKeyboardButton("📈 Ações", callback_data="favoritos_acoes"),
    )
    markup.row(InlineKeyboardButton("🔙 Voltar ao painel", callback_data="voltar_painel"))
    menu_principal.responder_callback(call)
    menu_principal.editar_callback(call, menu_principal.TEXTO_GERENCIAR_FAVORITOS, markup)


@bot.callback_query_handler(func=lambda call: call.data == "consultar_indicadores")
def callback_consultar_indicadores(call):
    """Abre o submenu de navegação pelos módulos de indicadores existentes."""
    _telegram_id, papel, _dto, erro = menu_principal.usuario_autorizado(call)
    if erro:
        menu_principal.responder_callback(call, erro)
        return
    # Consulta geral de indicadores: exclusiva do administrador (revalidada
    # aqui além de bot.permissoes, independentemente dos botões visíveis).
    if papel != permissoes.PAPEL_ADMIN:
        menu_principal.responder_callback(call, TEXTO_ACESSO_NEGADO)
        return
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🏢 FIIs (Imobiliários)", callback_data="menu_fiis"),
        InlineKeyboardButton("📈 Ações (Empresas)", callback_data="menu_acoes"),
    )
    markup.add(InlineKeyboardButton("🔙 Voltar ao painel", callback_data="voltar_painel"))
    menu_principal.responder_callback(call)
    menu_principal.editar_callback(call, menu_principal.TEXTO_CONSULTAR_INDICADORES, markup)


@bot.callback_query_handler(func=lambda call: call.data == "minha_conta")
def callback_minha_conta(call):
    """Exibe os dados cadastrais do próprio usuário (recurso já existente)."""
    telegram_id, papel, dto, erro = menu_principal.usuario_autorizado(call)
    if erro:
        menu_principal.responder_callback(call, erro)
        return
    menu_principal.responder_callback(call)
    menu_principal.editar_callback(
        call,
        menu_principal.texto_minha_conta(telegram_id, papel, dto),
        menu_principal.markup_voltar(),
    )


# ==========================================
# ----- BOTÕES PRINCIPAIS -----
# ==========================================
@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    try:
        dados = call.data
        chat_id = call.message.chat.id
        msg_id = call.message.message_id

        # --- BARREIRA DE AUTORIZAÇÃO (defesa em profundidade) ---
        # bot.permissoes já filtra antes do despacho; aqui revalida, com o
        # Telegram ID do próprio update, os callbacks que dependem de ativo ou
        # de papel administrativo, para que o controle não dependa só do menu.
        autor_id = getattr(getattr(call, "from_user", None), "id", None)
        sensivel, ticker_cb = permissoes.ticker_do_callback(dados)
        if sensivel and not permissoes.pode_acessar_ativo(autor_id, ticker_cb):
            bot.answer_callback_query(call.id, TEXTO_ACESSO_NEGADO)
            return
        if (
            dados in permissoes.CALLBACKS_ADMIN_EXATOS
            or dados.startswith(permissoes.CALLBACKS_ADMIN_PREFIXOS)
        ) and permissoes.obter_papel(autor_id) != permissoes.PAPEL_ADMIN:
            bot.answer_callback_query(call.id, TEXTO_ACESSO_NEGADO)
            return

        # --- NAVEGAÇÃO BÁSICA ---
        if dados == "voltar_menu":
            # Substitui o menu generico pelo painel personalizado do usuario,
            # editando a mensagem atual (sem duplicar). O botao administrativo e
            # anexado apenas para o admin autorizado.
            autor = getattr(call, "from_user", None)
            menu_principal.editar_painel(
                chat_id,
                msg_id,
                getattr(autor, "id", None),
                autor,
                message=getattr(call, "message", None),
            )

        elif dados == "menu_ajuda":
            autor = getattr(call, "from_user", None)
            papel, status, formulario_ativo = permissoes.contexto_ajuda(
                getattr(autor, "id", None)
            )
            texto = montar_guia_comandos(
                papel, status=status, formulario_ativo=formulario_ativo
            )
            _atualizar_mensagem(call, texto, markup_menu_ajuda(papel))

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
                matriz = buscar_dados_planilha_com_cache("BD_FIIs")
                if matriz:
                    vistos = set()
                    for linha in matriz[1:]:
                        _ticker, macro, _seg = dados_linha_fii(linha)
                        if macro:
                            vistos.add(macro)
                    for macro in list(MACROS_FII) + sorted(vistos - set(MACROS_FII)):
                        if macro in vistos:
                            markup.add(InlineKeyboardButton(f"🏢 {macro}", callback_data=f"macro_fii_{macro}"))
            except Exception as e:
                print(f"Erro ao listar macro categorias FII: {e}")

            markup.add(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            _atualizar_mensagem(call, "🏢 *Módulo FIIs - Selecione a Categoria:*", markup)

        # --- 2ª CAMADA: SUB-SETORES DA MACRO (Coluna C: Logística, Shopping...) ---
        elif call.data.startswith("macro_fii_"):
            macro_escolhida = call.data.replace("macro_fii_", "").strip()
            bot.answer_callback_query(call.id, f"Abrindo {macro_escolhida}...")

            try:
                matriz = buscar_dados_planilha_com_cache("BD_FIIs")
                markup = InlineKeyboardMarkup(row_width=2)

                linhas_macro = []
                for linha in matriz[1:]:
                    tkr, tipo, seg = dados_linha_fii(linha)
                    if tipo.lower() == macro_escolhida.lower():
                        linhas_macro.append((tkr, tipo, seg))
                sub_setores = sorted(list(dict.fromkeys(
                    seg for _tkr, _macro, seg in linhas_macro if seg
                )))

                if len(sub_setores) > 1:
                    for sub in sub_setores:
                        markup.add(InlineKeyboardButton(f"📁 {sub}", callback_data=f"subsetor_fii_{macro_escolhida}___{sub}"))
                else:
                    tickers = [tkr for tkr, _macro, _seg in linhas_macro if tkr]
                    for tkr in sorted(tickers):
                        markup.add(InlineKeyboardButton(f"🏢 {tkr}", callback_data=f"painel_{tkr}_fii"))

                markup.add(InlineKeyboardButton("🔙 Voltar", callback_data="menu_fiis"))
                _atualizar_mensagem(call, f"📂 **Categoria:** {macro_escolhida}\nSelecione o segmento:", markup)
            except Exception as e:
                print(f"Erro ao abrir macro: {e}")

        # --- 3ª CAMADA: ATIVOS DO SUB-SETOR (Ex: Tijolo -> Logística -> VILG11) ---
        elif call.data.startswith("subsetor_fii_"):
            partes = call.data.replace("subsetor_fii_", "").split("___")
            macro, sub = partes[0], partes[1]
            bot.answer_callback_query(call.id, f"Buscando {sub}...")

            matriz = buscar_dados_planilha_com_cache("BD_FIIs")

            tickers = [
                tkr for tkr, tipo, seg in (dados_linha_fii(linha) for linha in matriz[1:])
                if tkr and tipo.lower() == macro.lower() and seg.lower() == sub.lower()
            ]

            markup = InlineKeyboardMarkup(row_width=3)
            for ticker in sorted(tickers):
                markup.add(InlineKeyboardButton(f"🏢 {ticker}", callback_data=f"painel_{ticker}_fii"))

            # Voltar para a Macro correspondente
            markup.add(InlineKeyboardButton("🔙 Voltar", callback_data=f"macro_fii_{macro}"))
            _atualizar_mensagem(call, f"📂 **Segmento:** {sub}\nEscolha o ativo:", markup)

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
                "Tecnologia e Telecom": "💻",
                "Agronegócio": "🌱"
            }

            lista_macros = list(MAPA_SETORES_B3.keys())
            for idx, macro in enumerate(lista_macros):
                if setor_presente_na_planilha(macro, tickers_planilha, matriz):
                    icone = emojis.get(macro, "📁")
                    markup.add(InlineKeyboardButton(f"{icone} {macro}", callback_data=f"macro_ac_{idx}"))

            markup.add(InlineKeyboardButton("🔙 Voltar ao Início", callback_data="voltar_menu"))
            _atualizar_mensagem(call, "📈 *Módulo Ações - Selecione o Setor:*", markup)

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
                ativos_do_sub = tickers_do_segmento_b3(nome_macro, sub, matriz)
                if any(t in tickers_planilha for t in ativos_do_sub):
                    markup.add(InlineKeyboardButton(f"📂 {sub}", callback_data=f"sub_ac_{idx_macro}_{idx_sub}"))
                
            markup.add(InlineKeyboardButton("🔙 Voltar aos Setores", callback_data="menu_acoes"))
            _atualizar_mensagem(call, f"🏭 **Setor:** {nome_macro}\nSelecione o segmento de atuação:", markup)

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
            
            tickers_do_subsetor = tickers_do_segmento_b3(nome_macro, nome_sub, matriz)
            tickers_validos = [t for t in tickers_do_subsetor if t in tickers_planilha]
            
            markup = InlineKeyboardMarkup(row_width=1)
            
            if tickers_validos:
                for raiz, membros in agrupar_tickers_por_empresa(tickers_validos):
                    markup.add(InlineKeyboardButton(
                        f"🏢 {rotulo_empresa(membros, 'acao')}",
                        callback_data=callback_analise_ou_classes(
                            membros, f"emp_ac_{idx_macro}_{idx_sub}_{raiz}"
                        ),
                    ))
                txt = f"📂 **Segmento:** {nome_sub}\nEscolha a empresa:"
            else:
                txt = f"📭 Nenhuma empresa encontrada na planilha para o segmento **{nome_sub}**."
                
            markup.add(InlineKeyboardButton("🔙 Voltar", callback_data=f"macro_ac_{idx_macro}"))
            _atualizar_mensagem(call, txt, markup)

        # --- 4ª CAMADA: CLASSES DA MESMA EMPRESA (PETR3/PETR4) ---
        elif dados.startswith("emp_ac_"):
            partes = dados.split("_")
            if len(partes) != 5:
                responder_callback_desconhecido(bot, call.id)
                return
            try:
                idx_macro = int(partes[2])
                idx_sub = int(partes[3])
            except ValueError:
                responder_callback_desconhecido(bot, call.id)
                return
            raiz = partes[4].strip().upper()
            if not raiz:
                responder_callback_desconhecido(bot, call.id)
                return

            lista_macros = list(MAPA_SETORES_B3.keys())
            if idx_macro < 0 or idx_macro >= len(lista_macros):
                responder_callback_desconhecido(bot, call.id)
                return
            nome_macro = lista_macros[idx_macro]
            subsetores = list(MAPA_SETORES_B3[nome_macro].keys())
            if idx_sub < 0 or idx_sub >= len(subsetores):
                responder_callback_desconhecido(bot, call.id)
                return
            nome_sub = subsetores[idx_sub]

            matriz = buscar_dados_planilha_com_cache("BD_Acoes")
            tickers_planilha = [linha[0].strip().upper() for linha in matriz[1:] if len(linha) > 0 and linha[0].strip()] if matriz else []
            tickers_do_subsetor = tickers_do_segmento_b3(nome_macro, nome_sub, matriz)
            membros = sorted(
                t for t in tickers_do_subsetor
                if t in tickers_planilha and raiz_ticker(t) == raiz
            )

            bot.answer_callback_query(call.id, f"Classes {raiz}...")
            markup = InlineKeyboardMarkup(row_width=1)
            if len(membros) == 1:
                _abrir_painel_ativo(call, membros[0], "acao", chat_id, msg_id)
                return
            for ticker in membros:
                markup.add(InlineKeyboardButton(
                    f"📈 {ticker}",
                    callback_data=f"painel_{ticker}_acao",
                ))
            markup.add(InlineKeyboardButton("🔙 Voltar", callback_data=f"sub_ac_{idx_macro}_{idx_sub}"))
            if membros:
                nome = rotulo_empresa(membros, "acao")
                txt = f"📂 **{nome}**\nSelecione o ticker:"
            else:
                txt = f"📭 Nenhuma classe encontrada para **{raiz}**."
            _atualizar_mensagem(call, txt, markup)

        # --- FAVORITOS ---
        # Os callbacks ``favoritos_fiis`` / ``favoritos_acoes`` passaram a ser
        # tratados por ``bot/favoritos.py`` (favoritos individuais por usuario,
        # persistidos em ``ativos_acompanhados``). Aquele modulo e importado
        # antes deste handler generico, portanto os callbacks chegam la primeiro.
        # A carteira destacada nas varreduras vem do ranking real de
        # ``ativos_acompanhados`` (``obter_carteira_popular``).

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
                    icone = "🏢" if is_fii else "📈"
                    botoes_ativos = [
                        InlineKeyboardButton(
                            f"{icone} {rotulo_ticker(tkr, tipo)}",
                            callback_data=f"painel_{tkr}_{tipo}",
                        )
                        for tkr in top_oportunidades
                    ]
                    markup.add(*botoes_ativos)
                    texto = f"🔥 *Top Oportunidades ({'FIIs' if is_fii else 'Ações'})*\n\nEstes ativos passaram na sua peneira."
                else:
                    texto = "📭 *Nenhuma oportunidade encontrada.*"

                markup.row(InlineKeyboardButton("🔙 Voltar", callback_data=menu_voltar))
                _atualizar_mensagem(call, texto, markup)
            except Exception as e:
                print(f"Erro ao carregar oportunidades: {e}")
                markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Voltar", callback_data=menu_voltar))
                _atualizar_mensagem(call, "❌ Erro ao aplicar os filtros.", markup, parse_mode=None)

        # ==========================================
        # --- ROTA DE RETORNO AO PAINEL DO ATIVO ---
        # ==========================================
        elif dados.startswith("painel_"):
            partes = dados.split("_")
            ticker = partes[1]
            tipo_ativo = partes[2] # "fii" ou "acao"
            _abrir_painel_ativo(call, ticker, tipo_ativo, chat_id, msg_id)

        elif dados.startswith("fii_"):
            ticker = dados.split("_", 1)[1].strip().upper()
            _abrir_painel_ativo(call, ticker, "fii", chat_id, msg_id)

        elif dados.startswith("acao_"):
            ticker = dados.split("_", 1)[1].strip().upper()
            _abrir_painel_ativo(call, ticker, "acao", chat_id, msg_id)

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
            _atualizar_mensagem(call, txt, markup)

        # ==========================================
        # --- DADOS NÍVEL 1: ESCOLHER O ANO ---
        # ==========================================
        elif dados.startswith("dados_"):
            bot.answer_callback_query(call.id, "Buscando base de dados...")

            partes = dados.split("_")
            ticker = partes[1]
            tipo_ativo = partes[2]
            markup_voltar = _markup_voltar_ativo(ticker, tipo_ativo)

            session = SessionDB()
            try:
                ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
                if not ativo:
                    _atualizar_mensagem(
                        call,
                        f"Ativo {ticker} nao encontrado no banco de dados local.",
                        markup_voltar,
                        parse_mode=None,
                    )
                    return

                if tipo_ativo == "acao":
                    markup = InlineKeyboardMarkup(row_width=3)
                    txt = f"Historico Financeiro: {ticker}\n\nSelecione o ano para analise:"
                    balancos = session.query(DadosFinanceirosAcoes).filter(
                        DadosFinanceirosAcoes.ativo_id == ativo.id
                    ).all()
                    if balancos:
                        anos = sorted(
                            list(set(
                                b.data_referencia.strftime("%Y")
                                for b in balancos if b.data_referencia
                            )),
                            reverse=True,
                        )
                        for ano in anos:
                            markup.add(
                                InlineKeyboardButton(
                                    f"📅 {ano}",
                                    callback_data=f"ano_{ticker}_{tipo_ativo}_{ano}",
                                )
                            )
                    else:
                        txt = (
                            f"Os balancos CVM (ITR/DFP) de {ticker} "
                            "ainda nao foram processados."
                        )
                    markup.add(
                        InlineKeyboardButton(
                            "🔙 Voltar ao Painel",
                            callback_data=f"painel_{ticker}_{tipo_ativo}",
                        )
                    )
                    _atualizar_mensagem(call, txt, markup, parse_mode=None)
                    return

                informes = session.query(DadosFinanceirosFiis).filter(
                    DadosFinanceirosFiis.ativo_id == ativo.id
                ).order_by(DadosFinanceirosFiis.data_referencia.desc()).limit(4).all()

                if not informes:
                    cnpj_ativo = str(getattr(ativo, "cnpj", "") or "")
                    if cnpj_ativo.upper().startswith("PENDENTE-"):
                        detalhe = (
                            "CNPJ do fundo ainda nao conciliado com a CVM "
                            "(cadastro PENDENTE). Rode /forcar_fiis depois de "
                            "vincular o CNPJ real."
                        )
                    else:
                        detalhe = (
                            "Nenhum dado contabil encontrado na CVM para este fundo ainda."
                        )
                    _atualizar_mensagem(
                        call,
                        f"Dados Estruturais: {ticker}\n\n{detalhe}",
                        markup_voltar,
                        parse_mode=None,
                    )
                    return

                txt = f"Raio-X Contabil: {ticker}\nIndicadores oficiais da CVM\n\n"
                for inf in informes:
                    mes_ano = inf.data_referencia.strftime("%m/%Y")
                    if inf.patrimonio_liquido:
                        pl_fmt = (
                            f"R$ {inf.patrimonio_liquido/1000000000:.2f} Bi"
                            if inf.patrimonio_liquido >= 1000000000
                            else f"R$ {inf.patrimonio_liquido/1000000:.2f} Mi"
                        )
                    else:
                        pl_fmt = "N/A"
                    caixa_fmt = (
                        f"R$ {inf.disponibilidades_caixa/1000000:.2f} Mi"
                        if inf.disponibilidades_caixa else "N/A"
                    )
                    cotistas = (
                        f"{inf.cotistas:,}".replace(",", ".")
                        if inf.cotistas else "N/A"
                    )
                    if inf.rendimento_por_cota is not None:
                        rend_fmt = (
                            f"R$ {inf.rendimento_por_cota:.4f}"
                            .replace(".", ",")
                        )
                    else:
                        rend_fmt = "N/A"
                    txt += f"Referencia: {mes_ano}\n"
                    txt += f"Patrimonio Liquido: {pl_fmt}\n"
                    txt += f"Total de Cotistas: {cotistas}\n"
                    txt += f"Caixa / Disponivel: {caixa_fmt}\n"
                    txt += f"Rendimento por cota: {rend_fmt}\n"
                    txt += "--------------------\n"
                _atualizar_mensagem(call, txt, markup_voltar, parse_mode=None)
            finally:
                session.close()

        # ==========================================
        # --- DADOS NÍVEL 2: ESCOLHER O TRIMESTRE ---
        # ==========================================
        elif dados.startswith("ano_"):
            bot.answer_callback_query(call.id, "Carregando trimestres...")

            partes = dados.split("_")
            ticker = partes[1]
            tipo_ativo = partes[2]
            ano_escolhido = partes[3]
            markup_voltar = _markup_voltar_ativo(ticker, tipo_ativo)

            session = SessionDB()
            try:
                ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
                if not ativo:
                    _atualizar_mensagem(
                        call,
                        f"Ativo {ticker} nao encontrado no banco de dados local.",
                        markup_voltar,
                        parse_mode=None,
                    )
                    return

                markup = InlineKeyboardMarkup(row_width=1)
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
                txt_ano = f"📅 **Exercício {ano_escolhido}: {ticker}**\n\nSelecione o período desejado:"
                _atualizar_mensagem(call, txt_ano, markup)
            finally:
                session.close()

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
                if not ativo:
                    _atualizar_mensagem(
                        call,
                        f"Ativo {ticker} nao encontrado no banco de dados local.",
                        _markup_voltar_ativo(ticker, tipo_ativo),
                        parse_mode=None,
                    )
                    return
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
                    _atualizar_mensagem(call, txt, markup)
                    return

                ano_escolhido = data_ref.split('-')[0]
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("❓ Entender os Indicadores", callback_data=f"ajuda_cvm_{ticker}_menu"))
                markup.add(
                    InlineKeyboardButton("🔙 Voltar aos Trimestres", callback_data=f"ano_{ticker}_{tipo_ativo}_{ano_escolhido}"),
                    InlineKeyboardButton("🔙 Voltar ao Painel", callback_data=f"painel_{ticker}_{tipo_ativo}")
                )

                _atualizar_mensagem(call, txt, markup)
            
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
            try:
                ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()

                if ativo:
                    tem_docs = session.query(DocumentosQualitativos).filter(
                        DocumentosQualitativos.ativo_id == ativo.id,
                        DocumentosQualitativos.status_processamento.ilike("%SALVO_DRIVE%")
                    ).first()

                    if tem_docs:
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
                _atualizar_mensagem(call, txt, markup)
            finally:
                session.close()

        # ==========================================
        # --- NÍVEL 2: NAVEGAÇÃO (TIPOS OU MESES) ---
        # ==========================================
        elif dados.startswith("dnav_"):
            bot.answer_callback_query(call.id, "Listando opções...")
            partes = dados.split("_")
            ticker = partes[1]
            modo = partes[2] # 't' para Tipo, 'm' para Mês
            tipo_voltar = "fii" if ticker.endswith("11") else "acao"

            session = SessionDB()
            try:
                ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
                if ativo:
                    tipo_voltar = getattr(ativo.tipo, 'name', str(ativo.tipo)).replace("TipoAtivo.", "").lower()
                markup_arquivo = InlineKeyboardMarkup()
                markup_arquivo.add(
                    InlineKeyboardButton(
                        "🔙 Voltar ao Arquivo",
                        callback_data=f"docs_{ticker}_{tipo_voltar}",
                    )
                )
                if not ativo:
                    _atualizar_mensagem(
                        call,
                        f"❌ Ativo **{ticker}** não encontrado no banco de dados.",
                        markup_arquivo,
                    )
                    return

                docs = session.query(DocumentosQualitativos).filter(
                    DocumentosQualitativos.ativo_id == ativo.id,
                    DocumentosQualitativos.status_processamento.ilike("%SALVO_DRIVE%")
                ).all()

                markup = InlineKeyboardMarkup(row_width=1)
                txt = f"📭 Nenhum documento processado para {ticker}."

                if docs:
                    if modo == 't':
                        tipos_unicos = sorted(list(set([d.tipo_documento for d in docs if d.tipo_documento])))
                        for tipo_doc in tipos_unicos:
                            t_low = tipo_doc.lower()
                            if "gerencial" in t_low: emoji = "📊"
                            elif "fato" in t_low: emoji = "🚨"
                            elif "aviso" in t_low or "provento" in t_low: emoji = "💰"
                            elif "assembleia" in t_low or "vota" in t_low: emoji = "🗳️"
                            elif "trimestral" in t_low or "informe" in t_low: emoji = "📑"
                            else: emoji = "📄"

                            callback_seguro = f"dl_{ticker}_t_{tipo_doc[:25]}"
                            markup.add(InlineKeyboardButton(f"{emoji} {tipo_doc}", callback_data=callback_seguro))
                        txt = f"📂 **Filtro por Tipo: {ticker}**\n\nSelecione a categoria:"

                    elif modo == 'm':
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

                        markup = InlineKeyboardMarkup(row_width=2)
                        botoes_meses = []
                        for mes in meses_unicos[:14]:
                            if mes == "0000-00": nome_btn = "📅 Sem Data"
                            else: nome_btn = f"📅 {mes.split('-')[1]}/{mes.split('-')[0]}"
                            botoes_meses.append(InlineKeyboardButton(nome_btn, callback_data=f"dl_{ticker}_m_{mes}"))

                        markup.add(*botoes_meses)
                        txt = f"📅 **Filtro por Mês: {ticker}**\n\nSelecione o período (Ano/Mês):"

                markup.row(InlineKeyboardButton("🔙 Voltar ao Arquivo", callback_data=f"docs_{ticker}_{tipo_voltar}"))
                _atualizar_mensagem(call, txt, markup)
            finally:
                session.close()

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
            try:
                ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
                if not ativo:
                    markup.add(InlineKeyboardButton("🔙 Voltar aos Filtros", callback_data=f"dnav_{ticker}_{modo}"))
                    _atualizar_mensagem(
                        call,
                        f"❌ Ativo **{ticker}** não encontrado no banco de dados.",
                        markup,
                    )
                    return

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

                resumos_genericos = {
                    "fato relevante": "Comunicado oficial sobre decisões estratégicas da gestão.",
                    "demonstrações financeiras": "Balanço contábil auditado com receitas, custos e lucro.",
                    "relatório gerencial": "Relatório de acompanhamento do fundo e seus ativos.",
                    "aviso aos acionistas": "Informativo sobre proventos (dividendos/JCP) e subscrições.",
                    "aviso aos cotistas": "Informativo oficial aos cotistas sobre rendimentos.",
                    "apresentação": "Apresentação em slides detalhando os resultados corporativos."
                }

                if not docs_finais:
                    txt += "Nenhum documento neste filtro."

                for doc in sorted(docs_finais, key=lambda x: x.id, reverse=True):
                    data_limpa = extrair_data_real(doc)

                    resumo_texto = getattr(doc, 'resumo_ia', None)
                    if not resumo_texto or resumo_texto.strip() == "":
                        tipo_low = doc.tipo_documento.lower() if doc.tipo_documento else ""
                        for chave, desc in resumos_genericos.items():
                            if chave in tipo_low:
                                resumo_texto = desc
                                break
                        if not resumo_texto:
                            resumo_texto = "Documento oficial arquivado na nuvem."

                    if modo == 'm':
                        txt += f"📄 **{doc.tipo_documento}**\n"
                    txt += f"📅 **Data:** `{data_limpa}`\n"
                    txt += f"📝 _{resumo_texto}_\n\n"

                    url = doc.url_pdf if (doc.url_pdf and str(doc.url_pdf).startswith("http")) else "https://drive.google.com"
                    markup.add(InlineKeyboardButton(f"🔗 Abrir PDF ({data_limpa})", url=url))

                markup.add(InlineKeyboardButton("🔙 Voltar aos Filtros", callback_data=f"dnav_{ticker}_{modo}"))
                _atualizar_mensagem(call, txt, markup)
            finally:
                session.close()

        else:
            # Callback desconhecido (botão antigo/removido): responder em vez de ficar em silêncio
            logger.warning("TELEGRAM - callback nao reconhecido: %r", dados)
            responder_callback_desconhecido(bot, call.id, logger=logger)

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
