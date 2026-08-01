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
        if len(linha) < 1: continue
            
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

@bot.callback_query_handler(func=lambda call: call.data == "ver_raiox_docs")
def callback_raiox_docs(call):
    """Gera e exibe a lista completa de documentos e estatísticas sob demanda."""
    try:
        from atualizador_documentos import SessionDB
        from pipeline_dados.banco_dados import DocumentosQualitativos
        from sqlalchemy import func

        session = SessionDB()

        # Agrupamento de Tipos
        tipos_docs = session.query(
            DocumentosQualitativos.tipo_documento, 
            func.count(DocumentosQualitativos.id)
        ).filter(DocumentosQualitativos.status_processamento.ilike("%SALVO_DRIVE%"))\
         .group_by(DocumentosQualitativos.tipo_documento)\
         .order_by(func.count(DocumentosQualitativos.id).desc()).all()

        # Estatísticas Globais
        total_banco = session.query(DocumentosQualitativos).count()
        total_salvos = sum([qtd for tipo, qtd in tipos_docs])
        total_erros = session.query(DocumentosQualitativos).filter(DocumentosQualitativos.status_processamento.in_(["ERRO_DOWNLOAD", "ERRO_DRIVE"])).count()
        
        # Datas do Sistema (Fatiador Blindado)
        todos_assuntos = session.query(DocumentosQualitativos.assunto).filter(DocumentosQualitativos.assunto != None).all()
        datas_reais = []
        
        for (assunto,) in todos_assuntos:
            primeira_palavra = assunto.split(" ")[0] if assunto else ""
            if '-' in primeira_palavra:
                partes = primeira_palavra.split('-')
                # 🛡️ A MÁGICA AQUI: Além de ter tamanho 4, TEM QUE SER NÚMERO
                if len(partes[0]) == 4 and partes[0].isdigit():
                    datas_reais.append(primeira_palavra)
        
        datas_reais.sort()

        def formatar_data_br(data_iso):
            p = data_iso.split('-')
            if len(p) == 3: return f"{p[2]}/{p[1]}/{p[0]}"
            if len(p) == 2: return f"{p[1]}/{p[0]}"
            return data_iso

        data_ini = formatar_data_br(datas_reais[0]) if datas_reais else "N/A"
        data_fim = formatar_data_br(datas_reais[-1]) if datas_reais else "N/A"

        session.close()

        taxa_eficacia = (total_salvos / (total_salvos + total_erros) * 100) if (total_salvos + total_erros) > 0 else 0

        texto_tipos = (
            f"📊 **RAIO-X GLOBAL DO SISTEMA**\n\n"
            f"📈 **Estatísticas de Acervo:**\n"
            f" ├ Total no Banco de Dados: `{total_banco}`\n"
            f" ├ Documentos Processados (Drive): `{total_salvos}`\n"
            f" ├ Cobertura Temporal: `{data_ini}` a `{data_fim}`\n"
            f" └ Eficácia Histórica: `{taxa_eficacia:.1f}%`\n\n"
            f"📂 **Distribuição por Categorias Salvas:**\n"
        )
        
        if tipos_docs:
            for tipo, quantidade in tipos_docs:
                nome_bonito = str(tipo).replace("_", " ").title() if tipo else "Outros"
                texto_tipos += f"  ├ `{quantidade}x` {nome_bonito[:25]}\n"
        else:
            texto_tipos += "  ├ Banco de dados vazio."

        bot.send_message(call.message.chat.id, texto_tipos, parse_mode="Markdown")
        bot.answer_callback_query(call.id)

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

    # Avisa o usuário que a IA está pensando (Evita que ele ache que travou)
    try:
        bot.answer_callback_query(call.id, "🧠 Processando dados com IA...")
    except Exception as e:
        print(f"Aviso: Timeout do botão no Telegram ignorado. {e}")

    
    mensagem_espera = f"🧠 **Central de IA: {ticker}**\n\n⏳ _Analisando relatórios e estruturando dados..._"
    bot.edit_message_text(mensagem_espera, call.message.chat.id, call.message.message_id, parse_mode="Markdown")

    try:
        from atualizador_documentos import SessionDB
        from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
        from modules.module_ia import analisar_fatos_com_ia, construir_prompt_interativo
        
        session = SessionDB()
        ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()

        if not ativo:
            bot.edit_message_text(f"❌ Ativo `{ticker}` sem registros.", call.message.chat.id, call.message.message_id)
            return

        # Puxa os documentos para contexto
        docs_recentes = session.query(DocumentosQualitativos)\
            .filter(DocumentosQualitativos.ativo_id == ativo.id, DocumentosQualitativos.status_processamento == "SALVO_DRIVE")\
            .order_by(DocumentosQualitativos.data_publicacao.desc()).limit(5).all()

        # O ELO PERDIDO: Injetando o texto profundo do PDF na memória da IA
        resumo_docs = ""
        for d in docs_recentes:
            data_str = d.data_publicacao.strftime('%d/%m/%Y') if d.data_publicacao else "Sem Data"
            
            # Se o documento tiver texto extraído (RAG), usa os primeiros 3000 caracteres. Senão, usa o assunto.
            if d.texto_extraido:
                conteudo = str(d.texto_extraido)[:3000] + "..."
            else:
                conteudo = str(d.assunto) if d.assunto else "Sem informações detalhadas."
                
            resumo_docs += f"--- {d.tipo_documento} ({data_str}) ---\n{conteudo}\n\n"

        if not resumo_docs.strip():
            resumo_docs = "Nenhum documento detalhado no banco de dados para este ativo."

        # Pede para o novo módulo de IA montar a pergunta exata
        prompt = construir_prompt_interativo(ticker, tipo, topico, resumo_docs)
        
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
        try:
            bot.edit_message_text(texto_final, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
        except Exception as e:
            if "can't parse entities" in str(e).lower() or "bad request" in str(e).lower():
                bot.edit_message_text(texto_final, call.message.chat.id, call.message.message_id, reply_markup=markup)
            else:
                bot.edit_message_text(f"❌ Erro na IA: `{str(e)[:100]}`", call.message.chat.id, call.message.message_id)
                
    except Exception as e:
        bot.edit_message_text(f"❌ Erro na IA: `{str(e)[:150]}`", call.message.chat.id, call.message.message_id)
    finally:
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

    bot.edit_message_text(texto, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")


