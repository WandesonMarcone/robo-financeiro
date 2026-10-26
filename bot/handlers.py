import config
from bot.loader import bot
from bot import permissoes
from bot.telegram_utils import (
    editar_texto_ou_caption,
    markup_menu_ajuda,
    mensagem_eh_foto,
    montar_guia_comandos,
)
from services.planilhas import buscar_dados_planilha_com_cache
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pipeline_dados.banco_dados import DocumentosQualitativos
from pipeline_dados.identidade_visual import agrupar_tickers_por_empresa, raiz_ticker
from modules.relatorio_mercado import callback_analise_ou_classes, rotulo_empresa
from modules.taxonomia_fiis import dados_linha_fii


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


# ==========================================
# ----- BOTÃO TIPO/SETOR FIIS -----
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('tipo_fii_'))
def callback_selecionar_segmento(call):
    """Lê a planilha, quebra as barras e cria os botões de segmentos únicos"""
    tipo_selecionado = call.data.replace("tipo_fii_", "", 1).strip()
    matriz = buscar_dados_planilha_com_cache("BD_FIIs")

    segmentos_unicos = set()

    for linha in matriz[1:]:
        _ticker, tipo_fundo, segmento = dados_linha_fii(linha)
        if tipo_fundo.lower() == tipo_selecionado.lower() and segmento:
            segmentos_unicos.add(segmento)

    segmentos_ordenados = sorted(list(segmentos_unicos))

    markup = InlineKeyboardMarkup(row_width=1)
    for seg in segmentos_ordenados:
        markup.add(InlineKeyboardButton(f"📂 {seg}", callback_data=f"setor_fii_{seg}"))

    markup.add(InlineKeyboardButton("🔙 Voltar aos FIIs", callback_data="menu_fiis"))
    _atualizar_mensagem(call, f"🏢 *Tipo {tipo_selecionado} - Segmentos:*\n\nSelecione um segmento para ver os ativos:", markup)

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
            
        ticker, tipo_fundo, segmento = dados_linha_fii(linha)
        if not ticker:
            continue
        segmentos_do_fundo = [segmento] if segmento else []

        if nome_setor.lower() == (segmento or "").lower():

            # 🧠 LÓGICA DO AVISO VISUAL (ASTERISCO)

            texto_botao = f"🏢 {ticker}"

            # CENÁRIO 1: Fundo com múltiplos segmentos (Ex: GARE11)
            if len(segmentos_do_fundo) > 1:
                # Futuro: Aqui você puxará a % raspada ou da coluna da planilha
                # Ex: porcentagem = linha[10] 
                texto_botao = f"🏢 {ticker} (*Misto/Múltiplo)"
                # porcentagem = linha[10].strip() # Extrai o valor real da planilha
                # texto_botao = f"{ticker} (*{porcentagem}% {nome_setor})"

            # CENÁRIO 2: Fundo de Papel (CRI)
            elif tipo_fundo.upper() == "PAPEL":
                # Futuro: Puxar IPCA/CDI da planilha. Ex: ipca = linha[11], cdi = linha[12]
                texto_botao = f"🏢 {ticker} (*Indexadores)"
                # porcentagem = linha[10].strip() # Extrai o valor real da planilha
                # texto_botao = f"{ticker} (*{porcentagem}% {nome_setor})"


            # Cria o botão com a formatação decidida
            botoes_ativos.append(InlineKeyboardButton(texto_botao, callback_data=f"painel_{ticker}_fii"))

    # Adiciona todos os ativos na tela (2 por linha por causa do row_width=2)
    markup.add(*botoes_ativos)
    markup.add(InlineKeyboardButton("🔙 Voltar aos Tipos", callback_data="menu_fiis"))

    texto = f"📂 *Ativos no segmento: {nome_setor}*\n\nSelecione um ativo para analisar o painel profundo:"
    _atualizar_mensagem(call, texto, markup)

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
    markup = InlineKeyboardMarkup(row_width=1)
    tickers_setor = []

    for linha in matriz[1:]:
        # SEGURANÇA: Verifica se a linha tem colunas suficientes
        if len(linha) < 1: continue
            
        ticker = linha[0].strip().upper()
        # Lê a coluna de setor (Ajustado para índice 1, como você mencionou no código)
        setor_da_linha = linha[1].strip() 

        if setor_da_linha == nome_setor:
            tickers_setor.append(ticker)

    for raiz, membros in agrupar_tickers_por_empresa(tickers_setor):
        markup.add(InlineKeyboardButton(
            f"🏢 {rotulo_empresa(membros, 'acao')}",
            callback_data=callback_analise_ou_classes(membros, f"emp_sa_{raiz}"),
        ))
    markup.add(InlineKeyboardButton("🔙 Voltar aos Setores", callback_data="menu_acoes"))

    texto = f"📂 *Ações no setor: {nome_setor}*\n\nSelecione a empresa:"
    _atualizar_mensagem(call, texto, markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('emp_sa_'))
def callback_classes_acao_setor(call):
    """Lista as classes (ON/PN/unit) da empresa agrupada no setor."""
    raiz = call.data.replace('emp_sa_', '').strip().upper()
    bot.answer_callback_query(call.id, f"Classes {raiz}...")

    matriz = buscar_dados_planilha_com_cache("BD_Acoes")
    membros = []
    for linha in matriz[1:]:
        if len(linha) < 1:
            continue
        ticker = linha[0].strip().upper()
        if raiz_ticker(ticker) == raiz:
            membros.append(ticker)
    membros = sorted(dict.fromkeys(membros))

    markup = InlineKeyboardMarkup(row_width=1)
    if len(membros) == 1:
        from services.dashboard_menus import gerar_painel_ativo

        gerar_painel_ativo(
            membros[0],
            "acao",
            call.message.chat.id,
            call.message.message_id,
            message=call.message,
        )
        return
    for ticker in membros:
        markup.add(InlineKeyboardButton(
            f"📈 {ticker}",
            callback_data=f"painel_{ticker}_acao",
        ))
    markup.add(InlineKeyboardButton("🔙 Voltar aos Setores", callback_data="menu_acoes"))

    if membros:
        nome = rotulo_empresa(membros, "acao")
        texto = f"📂 *{nome}*\n\nSelecione o ticker:"
    else:
        texto = f"📭 Nenhuma classe encontrada para **{raiz}**."
    _atualizar_mensagem(call, texto, markup)

# ==========================================
# ----- BOTÃO MENU AJUDA -----
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data == 'ajuda_roadmap')
def callback_ajuda_roadmap(call):
    from bot.telegram_utils import TEXTO_MENU_AJUDA

    texto = TEXTO_MENU_AJUDA
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 Voltar", callback_data="menu_ajuda"))
    _atualizar_mensagem(call, texto, markup)

@bot.callback_query_handler(func=lambda call: call.data == 'ajuda_comandos')
def callback_ajuda_comandos(call):
    """Lista os comandos reais do sistema, restrita ao papel do usuário.

    Reutiliza a mesma fonte de verdade do comando ``/help`` para não citar
    comandos inexistentes nem exibir opções administrativas a usuários comuns.
    """
    autor = getattr(call, "from_user", None)
    papel, status, formulario_ativo = permissoes.contexto_ajuda(
        getattr(autor, "id", None)
    )
    texto_comandos = montar_guia_comandos(
        papel, status=status, formulario_ativo=formulario_ativo
    )
    markup = markup_menu_ajuda(papel)
    _atualizar_mensagem(call, texto_comandos, markup)

@bot.callback_query_handler(func=lambda call: call.data == "ver_raiox_docs")
def callback_raiox_docs(call):
    """Gera e exibe a lista completa de documentos e estatísticas sob demanda."""
    try:
        bot.answer_callback_query(call.id, "Carregando Raio-X...")

        from atualizador_documentos import SessionDB
        from pipeline_dados.banco_dados import DocumentosQualitativos
        from sqlalchemy import func
        import re

        session = SessionDB()

        # Agrupamento de Tipos (VERSÃO COM LIMPEZA DE IA)
        tipos_docs_brutos = session.query(
            DocumentosQualitativos.tipo_documento, 
            func.count(DocumentosQualitativos.id)
        ).filter(DocumentosQualitativos.status_processamento.ilike("%SALVO_DRIVE%"))\
         .group_by(DocumentosQualitativos.tipo_documento).all()

        contagem_tipos = {}
        for tipo_bruto, quantidade in tipos_docs_brutos:
            # Pega o nome bruto e remove qualquer número (0-9) usando regex
            tipo_limpo = re.sub(r'\d+', '', str(tipo_bruto)).strip() if tipo_bruto else "Outros"
            # Remove underlines e hífens residuais, e padroniza as maiúsculas
            nome_bonito = tipo_limpo.replace("_", " ").replace("-", "").strip().title()
            
            # Soma no dicionário (agora o Fato Relevante 90 soma no Fato Relevante normal)
            contagem_tipos[nome_bonito] = contagem_tipos.get(nome_bonito, 0) + quantidade

        # Ordena as categorias da que tem mais documentos para a que tem menos
        tipos_ordenados = sorted(contagem_tipos.items(), key=lambda x: x[1], reverse=True)

        # Estatísticas Globais
        total_salvos = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.status_processamento.ilike("%SALVO_DRIVE%")).count()
        total_erros = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.status_processamento.in_(["ERRO_DOWNLOAD", "ERRO_DRIVE"])).count()
        total_revisao = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.status_processamento == "AGUARDANDO_REVISAO").count()
        total_fila = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.status_processamento == "PENDENTE").count()

        # 🛡️ EXTRATOR DE DATAS INVENCÍVEL (REGEX)
        todos_assuntos = session.query(DocumentosQualitativos.assunto).filter(DocumentosQualitativos.assunto != None).all()
        datas_reais = []

        for (assunto,) in todos_assuntos:
            if assunto:
                # Busca padrões como 2026-06-15 ou 2026-06 em QUALQUER lugar do texto
                match = re.search(r'\b(20\d{2})[-/](0[1-9]|1[0-2])(?:[-/](0[1-9]|[12]\d|3[01]))?\b', assunto)
                if match:
                    ano = match.group(1)
                    mes = match.group(2)
                    dia = match.group(3) if match.group(3) else "01"
                    datas_reais.append(f"{ano}-{mes}-{dia}")

        # 👇 COLOQUE O PLANO B AQUI NO HANDLERS.PY TAMBÉM 👇
        if not datas_reais:
            datas_db = session.query(DocumentosQualitativos.data_publicacao).filter(DocumentosQualitativos.data_publicacao != None).all()
            for (dt,) in datas_db:
                if dt:
                    datas_reais.append(dt.strftime("%Y-%m-%d"))
        # 👆 -------------------------------------------- 👆

        datas_reais.sort()

        def formatar_data_br(data_iso):
            try:
                p = data_iso.split('-')
                return f"{p[2]}/{p[1]}/{p[0]}"
            except:
                return data_iso

        data_ini = formatar_data_br(datas_reais[0]) if datas_reais else "N/A"
        data_fim = formatar_data_br(datas_reais[-1]) if datas_reais else "N/A"

        session.close()

        total_processado = total_salvos + total_erros + total_revisao
        taxa_eficacia = (total_salvos / total_processado * 100) if total_processado > 0 else 0

        texto_tipos = (
            f"📊 **RAIO-X GLOBAL DO SISTEMA**\n\n"
            f"📈 **Estatísticas Totais do Banco:**\n"
            f" ├ Documentos Processados (Drive): `{total_salvos}`\n"
            f" ├ Presos na Fila de Leitura: `{total_fila}`\n"
            f" ├ Em Revisão Manual: `{total_revisao}`\n"
            f" ├ Falhas B3 / Links Quebrados: `{total_erros}`\n"
            f" ├ Cobertura Temporal: `{data_ini}` a `{data_fim}`\n"
            f" └ Eficácia Histórica da IA: `{taxa_eficacia:.1f}%`\n\n"
            f"📂 **Distribuição por Categorias Salvas:**\n"
        )

        if tipos_ordenados:
            for nome_bonito, quantidade in tipos_ordenados:
                texto_tipos += f"  ├ `{quantidade}x` {nome_bonito[:25]}\n"
        else:
            texto_tipos += "  ├ Banco de dados vazio."

        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 Fechar Raio-X", callback_data="voltar_menu"))

        _atualizar_mensagem(call, texto_tipos, markup)

    except Exception as e:
        bot.answer_callback_query(call.id, f"Erro ao gerar Raio-X: {str(e)[:50]}", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ia_"))
def callback_menu_inteligencia(call):
    """Gerencia o menu interativo de IA dividindo a análise em botões menores."""
    # Desempacota os dados (Exemplo de call.data: ia_PETR4_acao_dividendos)
    partes = call.data.split("_")
    ticker = partes[1]
    tipo = partes[2]
    # Se clicar no botão principal de IA, o tópico padrão é "resumo"
    topico = partes[3] if len(partes) > 3 else "resumo"

    try:
        bot.answer_callback_query(call.id, "Processando dados com IA...")
    except Exception as e:
        print(f"Aviso: Timeout do botão no Telegram ignorado. {e}")

    markup_voltar = InlineKeyboardMarkup()
    markup_voltar.add(
        InlineKeyboardButton(
            f"🔙 Voltar ao Painel do {ticker}",
            callback_data=f"painel_{ticker}_{tipo}",
        )
    )

    if not mensagem_eh_foto(getattr(call, "message", None)):
        mensagem_espera = (
            f"🧠 **Central de IA: {ticker}**\n\n"
            "⏳ _Analisando relatórios e estruturando dados..._"
        )
        _atualizar_mensagem(call, mensagem_espera)

    session = None
    try:
        from atualizador_documentos import SessionDB
        from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos

        session = SessionDB()
        ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()

        if not ativo:
            _atualizar_mensagem(
                call, f"❌ Ativo `{ticker}` sem registros.", markup_voltar
            )
            return

        from modules.module_ia import (
            analisar_fatos_com_ia,
            construir_prompt_interativo,
            montar_resumo_docs_ia,
            selecionar_docs_ia,
        )
        from services.planilhas import buscar_ativo_na_planilha

        docs_recentes = (
            session.query(DocumentosQualitativos)
            .filter(
                DocumentosQualitativos.ativo_id == ativo.id,
                DocumentosQualitativos.status_processamento == "SALVO_DRIVE",
            )
            .order_by(DocumentosQualitativos.data_publicacao.desc())
            .limit(20)
            .all()
        )
        docs_ia = selecionar_docs_ia(docs_recentes, tipo)
        resumo_docs = montar_resumo_docs_ia(docs_ia)

        indicadores = buscar_ativo_na_planilha(
            ticker, str(tipo or "").lower().startswith("fii")
        ) or {}
        eh_fii = str(tipo or "").lower().startswith("fii")
        ordem_fatos = (
            (
                ("dy", "Dividend Yield"),
                ("div_mensal", "Dividendo mensal"),
                ("preco", "Preco"),
                ("pvp", "P/VP"),
                ("vpa", "VPA"),
            )
            if eh_fii
            else (
                ("preco", "Preco"),
                ("dy", "Dividend Yield"),
                ("div_mensal", "Dividendo mensal"),
                ("pvp", "P/VP"),
                ("vpa", "VPA"),
                ("pl", "P/L"),
                ("roe", "ROE"),
            )
        )
        fatos = []
        for chave, rotulo in ordem_fatos:
            valor = str(indicadores.get(chave) or "").strip()
            if valor and valor.upper() not in ("N/A", "ND", "N/D", "-"):
                fatos.append(f"{rotulo}: {valor}")
        if eh_fii:
            try:
                from pipeline_dados.banco_dados import DadosFinanceirosFiis

                informe = (
                    session.query(DadosFinanceirosFiis)
                    .filter(DadosFinanceirosFiis.ativo_id == ativo.id)
                    .order_by(DadosFinanceirosFiis.data_referencia.desc())
                    .first()
                )
                if informe is not None and informe.rendimento_por_cota is not None:
                    fatos.insert(
                        0 if not fatos else min(2, len(fatos)),
                        f"Rendimento por cota (CVM): {informe.rendimento_por_cota}",
                    )
            except Exception:
                pass

        prompt = construir_prompt_interativo(
            ticker, tipo, topico, resumo_docs, fatos=fatos
        )
        
        # Dispara para a Groq/OpenAI
        resposta_ia = analisar_fatos_com_ia(prompt)

        # Monta os botões do Menu Interativo com base no Tipo (Ação ou FII)
        markup = InlineKeyboardMarkup(row_width=2)
        
        if tipo == "fii":
            markup.add(
                InlineKeyboardButton("🏢 Visão & Ativos", callback_data=f"ia_{ticker}_fii_visao"),
                InlineKeyboardButton("💸 Rendimentos", callback_data=f"ia_{ticker}_fii_proventos"),
                InlineKeyboardButton("⚠️ Fatores de Risco", callback_data=f"ia_{ticker}_fii_riscos"),
                InlineKeyboardButton("🎯 Parecer", callback_data=f"ia_{ticker}_fii_parecer")
            )
        else:
            markup.add(
                InlineKeyboardButton("📈 Negócios", callback_data=f"ia_{ticker}_acao_negocios"),
                InlineKeyboardButton("⚙️ Saúde Fin.", callback_data=f"ia_{ticker}_acao_saude"),
                InlineKeyboardButton("💰 Dividendos", callback_data=f"ia_{ticker}_acao_dividendos"),
                InlineKeyboardButton("🎯 Parecer", callback_data=f"ia_{ticker}_acao_parecer")
            )
            
        markup.add(InlineKeyboardButton(f"🔙 Voltar ao Painel do {ticker}", callback_data=f"painel_{ticker}_{tipo}"))

        # Formatação final da resposta
        titulos = {
            "resumo": "Micro-Resumo", "visao": "Visão Geral & Ativos", "proventos": "Rendimentos e Proventos",
            "riscos": "Fatores de Risco", "negocios": "Modelo de Negócios", "saude": "Saúde Financeira", 
            "dividendos": "Política de Dividendos", "parecer": "Parecer Executivo"
        }
        
        texto_final = f"🧠 **Inteligência Artificial: {ticker}**\n📍 *{titulos.get(topico, 'Análise')}*\n\n{resposta_ia}"
        _atualizar_mensagem(call, texto_final, markup)
                
    except Exception as e:
        _atualizar_mensagem(
            call, f"❌ Erro na IA: `{str(e)[:150]}`", markup_voltar
        )
    finally:
        if session is not None:
            session.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith("ajuda_cvm_"))
def menu_duvidas_cvm(call):
    """Sistema de dicionário financeiro interativo para o painel da CVM."""
    partes = call.data.split("_")
    ticker = partes[2]
    tela = partes[3] # Pode ser: menu, bp, dre, fco

    markup = InlineKeyboardMarkup(row_width=2)
    
    if tela == "menu":
        texto = "📖 *Dicionário Financeiro CVM*\n\nEscolha qual grupo de indicadores você deseja entender:"
        markup.add(
            InlineKeyboardButton("⚖️ Balanço Patrimonial", callback_data=f"ajuda_cvm_{ticker}_bp"),
            InlineKeyboardButton("⚙️ D.R.E (Resultados)", callback_data=f"ajuda_cvm_{ticker}_dre"),
            InlineKeyboardButton("💸 Fluxo de Caixa", callback_data=f"ajuda_cvm_{ticker}_fco")
        )
    elif tela == "bp":
        texto = (
            "⚖️ *Balanço Patrimonial*\n\n"
            "• *Ativo Total:* Tudo o que a empresa possui (dinheiro, imóveis, estoques).\n"
            "• *Patrimônio Líquido:* A riqueza real dos acionistas (Ativos menos Passivos).\n"
            "• *Caixa:* Dinheiro vivo ou investimentos de curtíssimo prazo disponíveis.\n"
            "• *Dívida Líquida:* O total de dívidas da empresa MENOS o dinheiro que ela tem em caixa. Se for negativa, ela tem mais caixa que dívida!"
        )
        markup.add(InlineKeyboardButton("🔙 Voltar ao Menu de Dúvidas", callback_data=f"ajuda_cvm_{ticker}_menu"))
    elif tela == "dre":
        texto = (
            "⚙️ *D.R.E. (Resultados)*\n\n"
            "• *Receita Líquida:* Todo o dinheiro que entrou pelas vendas, descontados os impostos diretos.\n"
            "• *EBITDA:* Geração de caixa operacional pura (Lucro antes de juros, impostos, depreciação e amortização).\n"
            "• *Resultado Financeiro:* A diferença entre o que a empresa ganha com juros e o que ela paga de juros de dívidas.\n"
            "• *Lucro Líquido:* O dinheiro que sobra no bolso no fim do trimestre."
        )
        markup.add(InlineKeyboardButton("🔙 Voltar ao Menu de Dúvidas", callback_data=f"ajuda_cvm_{ticker}_menu"))
    elif tela == "fco":
        texto = (
            "💸 *Fluxo de Caixa Operacional (FCO)*\n\n"
            "Mostra o dinheiro real que entrou na conta bancária da empresa apenas com a sua operação principal.\n\n"
            "⚠️ *Dica:* Uma empresa pode ter Lucro na DRE, mas FCO negativo (lucro contábil que ainda não virou dinheiro no banco)."
        )
        markup.add(InlineKeyboardButton("🔙 Voltar ao Menu de Dúvidas", callback_data=f"ajuda_cvm_{ticker}_menu"))

    # O botão mais importante: Voltar para a análise da ação!
    markup.add(InlineKeyboardButton(f"🔙 Voltar ao Painel ({ticker})", callback_data=f"painel_{ticker}_acao"))

    _atualizar_mensagem(call, texto, markup)


