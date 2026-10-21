import json
import logging
import re
import threading
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Imports da nossa nova arquitetura
from bot.loader import bot
from config import TIPOS_DOC_FII, TIPOS_DOC_ACAO
from atualizador_documentos import SessionDB
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
from modules.GoogleDriveManager import GoogleDriveManager

logger = logging.getLogger("robo.revisao")

# O gerenciador do Drive e criado sob demanda para evitar descoberta de rede do
# Google apenas por importar o modulo (reduz efeitos colaterais em testes).
_drive_manager = None
_lote_ia_lock = threading.Lock()


def obter_drive_manager():
    global _drive_manager
    if _drive_manager is None:
        _drive_manager = GoogleDriveManager()
    return _drive_manager

def extrair_file_id(url):
    """Extrai apenas o ID alfanumérico do link longo do Google Drive"""
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', str(url))
    return match.group(1) if match else None


def _texto_dupla_checagem(doc, fallback):
    """Mostra as duas leituras da IA quando persistidas em ``resumo_ia``."""
    bruto = getattr(doc, "resumo_ia", None)
    if not bruto:
        return f"🤖 **Leitura da IA:** `{fallback}`"
    try:
        dados = json.loads(bruto)
    except (TypeError, ValueError):
        return f"🤖 **Leitura da IA:** `{fallback}`"
    c1 = dados.get("checagem_1") or {}
    c2 = dados.get("checagem_2") or {}
    if not c1.get("tipo") or not c2.get("tipo"):
        return f"🤖 **Leitura da IA:** `{fallback}`"
    acordo = "concordaram" if dados.get("acordo") else "discordaram ou ficaram incertas"
    return (
        f"🤖 **Duas checagens da IA** ({acordo})\n"
        f"1️⃣ `{c1.get('tipo')}` ({c1.get('confianca', 0)}%)\n"
        f"2️⃣ `{c2.get('tipo')}` ({c2.get('confianca', 0)}%)"
    )

# O comando e a tela de abertura moram aqui agora, pertinho dos callbacks!
@bot.message_handler(commands=['revisao'])
def comando_painel_revisao(message):
    enviar_painel_tickers(message.chat.id)

def enviar_painel_tickers(chat_id, message_id=None):
    """Busca no banco todos os documentos marcados como suspeitos e agrupa por Ativo (FII/Ação)"""
    session = SessionDB()
    try:
        # Puxa TUDO que está aguardando revisão (sem filtrar por tipo)
        pendentes = session.query(DocumentosQualitativos).filter_by(status_processamento="AGUARDANDO_REVISAO").all()

        markup_voltar = InlineKeyboardMarkup(row_width=1)
        markup_voltar.add(
            InlineKeyboardButton(
                "🤖 Classificar com IA", callback_data="rev_ia_lote"
            )
        )
        markup_voltar.add(
            InlineKeyboardButton("🔙 Voltar", callback_data="adm_home")
        )
        if not pendentes:
            msg = (
                "⚖️ Central de Revisoes\n"
                "Documentos de FIIs em que as duas checagens da IA discordaram "
                "ou ficaram incertas.\n"
                "Nao ha documentos aguardando revisao."
            )
            if message_id:
                bot.edit_message_text(
                    msg, chat_id, message_id, reply_markup=markup_voltar
                )
            else:
                bot.send_message(chat_id, msg, reply_markup=markup_voltar)
            return

        # Agrupa pelos tickers únicos
        tickers_unicos = sorted(list(set([doc.ativo.ticker for doc in pendentes])))
        markup = InlineKeyboardMarkup()

        for t in tickers_unicos:
            docs_do_ativo = [d for d in pendentes if d.ativo.ticker == t]
            qtd = len(docs_do_ativo)
            
            # Descobre se é Ação ou FII só pelo primeiro documento da lista
            primeiro_ativo = docs_do_ativo[0].ativo
            tipo_ativo = getattr(primeiro_ativo.tipo, 'name', str(primeiro_ativo.tipo).replace("TipoAtivo.", "")).upper()
            
            # Coloca um ícone visual para você saber o que está abrindo!
            icone = "🏢" if tipo_ativo == "FII" else "📈"
            
            markup.add(InlineKeyboardButton(text=f"{icone} {t} ({qtd} docs)", callback_data=f"rev_t_{t}"))
        markup.add(
            InlineKeyboardButton(
                "🤖 Classificar com IA", callback_data="rev_ia_lote"
            )
        )
        markup.add(InlineKeyboardButton("🔙 Voltar", callback_data="adm_home"))

        msg = (
            "⚖️ Central de Revisoes\n"
            "Documentos de FIIs em que as duas checagens da IA discordaram "
            "ou ficaram incertas. Selecione um ativo:"
        )
        if message_id:
            bot.edit_message_text(msg, chat_id, message_id, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="Markdown")
    finally:
        session.close()

# Atalho administrativo "📥 Iniciar Revisão Manual" do relatório pós-varredura
# (``bot/comandos.py``). Reutiliza exatamente a mesma tela do comando
# ``/revisao``; a autorização é administrativa e já foi revalidada pelo controle
# central (``bot.permissoes``) antes do despacho. Sem este handler específico, o
# callback cairia no handler genérico de ``bot.callbacks_menus`` e responderia
# "botão inválido". Registrado neste módulo, que é importado antes do genérico.
@bot.callback_query_handler(func=lambda call: call.data == "iniciar_revisao_pendencias")
def abrir_revisao_pelo_relatorio(call):
    bot.answer_callback_query(call.id)
    enviar_painel_tickers(call.message.chat.id, call.message.message_id)


def _responder_callback(call, texto=None):
    """Responde o clique sem derrubar o handler se o query ja expirou."""
    try:
        bot.answer_callback_query(call.id, texto)
    except Exception:
        logger.debug("Callback expirado ou invalido; seguindo sem answer.", exc_info=True)


def _markup_lote_ia(resumo=None):
    markup = InlineKeyboardMarkup(row_width=1)
    if int((resumo or {}).get("sem_texto", 0) or 0) > 0:
        markup.add(
            InlineKeyboardButton(
                "📄 IA ler paginas 2 e 3", callback_data="rev_ia_pags"
            )
        )
    markup.add(
        InlineKeyboardButton("🔄 Atualizar lista", callback_data="rev_start")
    )
    markup.add(InlineKeyboardButton("🔙 Voltar", callback_data="adm_home"))
    return markup


def _linhas_tipos(tipos, limite=4):
    itens = sorted(
        (tipos or {}).items(),
        key=lambda par: (-int(par[1] or 0), par[0]),
    )
    saida = []
    for nome, qtd in itens[:limite]:
        saida.append(f"{int(qtd or 0)} {nome}")
    resto = len(itens) - limite
    if resto > 0:
        saida.append(f"+{resto} tipo(s)")
    return saida


def _linhas_por_fundo(por_fundo, limite=25):
    itens = sorted(
        (por_fundo or {}).items(),
        key=lambda par: (-int((par[1] or {}).get("examinados", 0) or 0), par[0]),
    )
    if not itens:
        return []
    linhas = ["", f"Fundos examinados: {len(itens)}"]
    for ticker, dados in itens[:limite]:
        exam = int((dados or {}).get("examinados", 0) or 0)
        rev = int((dados or {}).get("revisao", 0) or 0)
        sem = int((dados or {}).get("sem_texto", 0) or 0)
        partes = [f"{exam} exam."]
        partes.extend(_linhas_tipos((dados or {}).get("tipos")))
        if rev:
            partes.append(f"{rev} rev.")
        if sem:
            partes.append(f"{sem} sem texto")
        linhas.append(f"{ticker}: " + " | ".join(partes))
    resto = len(itens) - limite
    if resto > 0:
        linhas.append(f"... e mais {resto} fundo(s)")
    return linhas


def _texto_resumo_lote(resumo, andamento=False):
    if resumo.get("ia_indisponivel") and not resumo.get("lotes"):
        return (
            "⚖️ Central de Revisoes\n"
            "IA indisponivel (GROQ_API_KEY ausente). Nada foi classificado."
        )
    if resumo.get("fila", 0) == 0 and not resumo.get("lotes"):
        return (
            "⚖️ Central de Revisoes\n"
            "Nenhum documento generico ou incerto para a IA classificar agora."
        )
    titulo = (
        "🤖 Classificando de 3 em 3 (um clique esvazia a fila)..."
        if andamento
        else "🤖 Classificacao concluida (de 3 em 3, catalogo fixo)."
    )
    extra_ia = ""
    if resumo.get("ia_indisponivel"):
        extra_ia = "\nIA indisponivel no meio do lote; o restante ficou na fila."
    linhas = [
        "⚖️ Central de Revisoes",
        titulo,
        f"Lotes: {resumo.get('lotes', 0)}",
        f"Examinados: {resumo.get('fila', 0)}",
        f"Identificados: {resumo.get('classificados', 0)}",
        f"Organizados no Drive: {resumo.get('drive', 0)}",
        f"Ainda em revisao: {resumo.get('revisao', 0)}",
        f"Sem texto no PDF: {resumo.get('sem_texto', 0)}",
        f"Erros: {resumo.get('erros', 0)}",
    ]
    if extra_ia:
        linhas.append(extra_ia.strip())
    if not andamento:
        linhas.extend(_linhas_por_fundo(resumo.get("por_fundo")))
    return "\n".join(linhas)


def _editar_mensagem_lote(chat_id, message_id, texto, resumo=None):
    try:
        bot.edit_message_text(
            texto, chat_id, message_id, reply_markup=_markup_lote_ia(resumo)
        )
    except Exception:
        logger.debug("Falha ao editar mensagem do lote de IA.", exc_info=True)


def _rodar_lote_ia(chat_id, message_id, somente_sem_texto=False, pagina_inicial=0):
    resumo = {
        "fila": 0,
        "classificados": 0,
        "revisao": 0,
        "sem_texto": 0,
        "erros": 1,
        "drive": 0,
        "ia_indisponivel": False,
        "lotes": 0,
        "ids": [],
        "por_fundo": {},
    }
    try:
        from atualizador_documentos import reclassificar_documentos_genericos_em_lotes

        def _progresso(total, _lote):
            _editar_mensagem_lote(
                chat_id,
                message_id,
                _texto_resumo_lote(total, andamento=True),
                resumo=total,
            )

        drive = None
        try:
            drive = obter_drive_manager()
        except Exception:
            logger.warning("Drive indisponivel no lote de IA", exc_info=True)

        resumo = reclassificar_documentos_genericos_em_lotes(
            on_lote=_progresso,
            somente_sem_texto=somente_sem_texto,
            pagina_inicial=pagina_inicial,
            drive_manager=drive,
        )
    except Exception:
        logger.warning("Falha no lote de classificacao IA", exc_info=True)
    finally:
        try:
            _lote_ia_lock.release()
        except RuntimeError:
            pass
    _editar_mensagem_lote(
        chat_id, message_id, _texto_resumo_lote(resumo), resumo=resumo
    )


@bot.callback_query_handler(func=lambda call: call.data == "rev_ia_lote")
def classificar_lote_com_ia(call):
    """Duas checagens da IA em segundo plano (catalogo fixo, sem estourar o webhook)."""
    _responder_callback(call, "Classificando com as duas checagens da IA...")
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    if not _lote_ia_lock.acquire(blocking=False):
        _editar_mensagem_lote(
            chat_id,
            message_id,
            "⚖️ Central de Revisoes\n"
            "🤖 Ja ha uma classificacao em andamento. Aguarde o resultado.",
        )
        return
    _editar_mensagem_lote(
        chat_id,
        message_id,
        "⚖️ Central de Revisoes\n"
        "🤖 Classificando em segundo plano, de 3 em 3.\n"
        "Um clique esvazia a fila. Aguarde; a lista sera atualizada ao terminar.",
    )
    threading.Thread(
        target=_rodar_lote_ia, args=(chat_id, message_id), daemon=True
    ).start()


@bot.callback_query_handler(func=lambda call: call.data == "rev_ia_pags")
def classificar_paginas_sem_texto(call):
    """Rele paginas 2 e 3 so dos PDFs que ficaram sem texto."""
    _responder_callback(call, "Lendo paginas 2 e 3 dos PDFs sem texto...")
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    if not _lote_ia_lock.acquire(blocking=False):
        _editar_mensagem_lote(
            chat_id,
            message_id,
            "⚖️ Central de Revisoes\n"
            "🤖 Ja ha uma classificacao em andamento. Aguarde o resultado.",
        )
        return
    _editar_mensagem_lote(
        chat_id,
        message_id,
        "⚖️ Central de Revisoes\n"
        "📄 Relendo paginas 2 e 3 dos PDFs sem texto, de 3 em 3.\n"
        "Aguarde; o resumo sera atualizado ao terminar.",
    )
    threading.Thread(
        target=_rodar_lote_ia,
        args=(chat_id, message_id),
        kwargs={"somente_sem_texto": True, "pagina_inicial": 1},
        daemon=True,
    ).start()


# 🧠 O CÉREBRO DA REVISÃO (Lida com todos os cliques dos botões)
@bot.callback_query_handler(func=lambda call: call.data.startswith('rev_'))
def processar_revisao(call):
    partes = call.data.split('_')
    acao = partes[1]
    if acao == 'ia':
        return
    session = SessionDB()

    try:
        # AÇÃO: Voltar ao menu inicial de revisão
        if acao == 'start':
            bot.answer_callback_query(call.id)
            enviar_painel_tickers(call.message.chat.id, call.message.message_id)

        # AÇÃO: Mostrar lista de documentos suspeitos de um ativo específico
        elif acao == 't':
            ticker = partes[2] 
            pendentes = session.query(DocumentosQualitativos).join(Ativo).filter(
                Ativo.ticker == ticker, 
                DocumentosQualitativos.status_processamento == "AGUARDANDO_REVISAO"
            ).all()

            if not pendentes:
                bot.answer_callback_query(call.id, "Nenhum documento pendente para este ativo.")
                enviar_painel_tickers(call.message.chat.id, call.message.message_id)
                return
            
            bot.answer_callback_query(call.id, f"Carregando documentos de {ticker}...")

            markup = InlineKeyboardMarkup()
            for doc in pendentes:
                # 🎨 NOVA INTELIGÊNCIA VISUAL DOS BOTÕES
                # 1. Tenta formatar a data
                if doc.assunto and '-' in doc.assunto.split(" ")[0]:
                    data_limpa = doc.assunto.split(" ")[0].replace("-", "/")
                    resumo_cru = " ".join(doc.assunto.split(" ")[1:])
                else:
                    data_limpa = doc.data_publicacao.strftime("%d/%m/%y") if doc.data_publicacao else "Data N/A"
                    resumo_cru = doc.assunto
                
                # 2. Se não tem assunto preenchido, usa o tipo_documento
                if not resumo_cru or resumo_cru.strip() == "":
                    resumo_cru = doc.tipo_documento if doc.tipo_documento else "Doc sem título"
                    
                # 3. Corta para não estourar a tela do celular (25 caracteres no máximo)
                resumo_curto = (resumo_cru[:25] + "..").strip() if len(resumo_cru) > 25 else resumo_cru.strip()
                
                # Botão final perfeito e limpo!
                btn_text = f"📄 {data_limpa} | {resumo_curto}"
                markup.add(InlineKeyboardButton(text=btn_text, callback_data=f"rev_d_{doc.id}"))

            # Descobre o tipo para criar o botão de "Voltar ao Painel" certo
            primeiro_ativo = pendentes[0].ativo
            tipo_ativo = getattr(primeiro_ativo.tipo, 'name', str(primeiro_ativo.tipo).replace("TipoAtivo.", "")).lower()

            markup.add(
                 InlineKeyboardButton(text=f"🏢 Ir para o Painel de {ticker}", callback_data=f"painel_{ticker}_{tipo_ativo}"),
                 InlineKeyboardButton(text="🔙 Voltar à Central", callback_data="rev_start")
            )

            bot.edit_message_text(f"📑 **Análise: {ticker}**\n\nSelecione o documento para inspecionar:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

        # AÇÃO: Abrir as opções (Visualizar, Salvar, Apagar) de um documento específico
        elif acao == 'd':
            bot.answer_callback_query(call.id)
            doc_id = partes[2]
            doc = session.query(DocumentosQualitativos).get(doc_id)

            markup = InlineKeyboardMarkup()

            # 🛡️ Trava de Segurança
            if doc.url_pdf and doc.url_pdf.startswith("http"):
                markup.add(InlineKeyboardButton(text="🔗 Abrir PDF no Drive", url=doc.url_pdf))

            markup.row(
                InlineKeyboardButton(text="✅ Classificar", callback_data=f"rev_app_{doc.id}"),
                InlineKeyboardButton(text="🗑️ Apagar", callback_data=f"rev_del_{doc.id}")
            )
            markup.add(InlineKeyboardButton(text="🔙 Voltar", callback_data=f"rev_t_{doc.ativo.ticker}"))

            # 🔴 O SEU FATIADOR DE DATA (A MÁGICA AQUI!)
            nome_original = str(doc.tipo_documento)
            data_exibicao = "Data N/A"
            nome_limpo_exibicao = nome_original

            # Se for um nome sujo de revisão, ele fatia e acha a data
            if "REVISAR_" in nome_original:
                pedacos = nome_original.replace(".pdf", "").split("_")
                for p in pedacos:
                    # Acha o formato de data (ex: 2026-06-15)
                    if len(p) == 10 and p.count('-') == 2:
                        ano, mes, dia = p.split('-')
                        data_exibicao = f"{dia}/{mes}/{ano}"
                        # Limpa o nome para ficar bonito na tela
                        nome_limpo_exibicao = nome_original.replace(f"REVISAR_{doc.ativo.ticker}_", "").replace(f"_{p}", "")
                        break
            else:
                # Se não tiver REVISAR no nome (caso antigo), pega a data do assunto
                data_limpa = doc.assunto.split(" ")[0] if doc.assunto else None
                if data_limpa and '-' in data_limpa:
                    try:
                        ano, mes, dia = data_limpa.split('-')
                        data_exibicao = f"{dia}/{mes}/{ano}"
                    except: pass

            txt = (
                f"🔍 **Inspecionando Documento**\n\n"
                f"🏢 **Ativo:** `{doc.ativo.ticker}`\n"
                f"📅 **Data da Publicação:** `{data_exibicao}`\n"
                f"{_texto_dupla_checagem(doc, nome_limpo_exibicao.replace('_', ' '))}\n\n"
            )

            if not (doc.url_pdf and doc.url_pdf.startswith("http")):
                txt += "⚠️ *O link do Google Drive para este documento está ausente ou corrompido.*\n\n"

            txt += "O que deseja fazer?"
            bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

        # AÇÃO: Usuário decidiu salvar, abre o catálogo de tipos de documento dinâmico
        elif acao == 'app':
            bot.answer_callback_query(call.id)
            doc_id = partes[2]
            doc = session.query(DocumentosQualitativos).get(doc_id)
            tipo_ativo = getattr(doc.ativo.tipo, 'name', str(doc.ativo.tipo).replace("TipoAtivo.", "")).upper()

            markup = InlineKeyboardMarkup()

            # 🔴 NOVA LÓGICA: Carrega os catálogos direto do config.py
            if tipo_ativo == "ACAO":
                for id_tipo, nome_tipo in TIPOS_DOC_ACAO.items():
                    markup.add(InlineKeyboardButton(text=f"📂 {nome_tipo}", callback_data=f"rev_typ_{doc.id}_ACAO_{id_tipo}"))
            else:
                for id_tipo, nome_tipo in TIPOS_DOC_FII.items():
                    markup.add(InlineKeyboardButton(text=f"📂 {nome_tipo}", callback_data=f"rev_typ_{doc.id}_FII_{id_tipo}"))

            markup.add(InlineKeyboardButton(text="🔙 Cancelar", callback_data=f"rev_d_{doc.id}"))

            bot.edit_message_text(f"**Renomear Arquivo**\n\nO que é este documento do `{doc.ativo.ticker}` na verdade?", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

        # AÇÃO: A MÁGICA - Renomeia no Drive, move de pasta e atualiza o Banco de Dados
        elif acao == 'typ':
            doc_id = partes[2]
            tipo_cat = partes[3] # 'ACAO' ou 'FII'
            tipo_id = partes[4]

            bot.answer_callback_query(call.id, "Organizando no Drive...")

            doc = session.query(DocumentosQualitativos).get(doc_id)
            file_id = extrair_file_id(doc.url_pdf)

            # Puxa o nome exato dos dicionários do config.py
            if tipo_cat == "ACAO":
                tipo_nome_limpo = TIPOS_DOC_ACAO.get(tipo_id, "Documento_Acao")
            else:
                tipo_nome_limpo = TIPOS_DOC_FII.get(tipo_id, "Outros")

            mes_ref = datetime.now().strftime("%Y-%m")
            if doc.assunto and '-' in doc.assunto:
                assunto_limpo = doc.assunto.split(" ")[0] 
                p = assunto_limpo.split('-')
                if len(p) == 3: 
                    if len(p[2]) == 4: mes_ref = f"{p[2]}-{p[1]}" 
                    elif len(p[0]) == 4: mes_ref = f"{p[0]}-{p[1]}" 

            assunto_limpo_pdf = doc.assunto.split(" ")[0] if doc.assunto else "Doc"
            sufixo = f"_{doc.id_b3}" if doc.id_b3 else ""

            nome_drive = tipo_nome_limpo.replace(' ', '_').replace('/', '')
            novo_nome_pdf = f"{nome_drive}_{assunto_limpo_pdf}{sufixo}.pdf"

            tipo_ativo_str = "ACAO" if tipo_cat == "ACAO" else "FII"

            # 1. MOVER CORRETAMENTE DA REVISÃO PARA A PASTA OFICIAL DO ATIVO NO DRIVE
            novo_link = obter_drive_manager().mover_arquivo_da_revisao_por_id(
                file_id=file_id,
                ticker=doc.ativo.ticker,
                mes_ref=mes_ref,
                novo_nome=novo_nome_pdf,
                tipo_ativo=tipo_ativo_str
            )

            if novo_link:
                # 2. ATUALIZA O BANCO
                doc.status_processamento = "SALVO_DRIVE"
                doc.tipo_documento = tipo_nome_limpo
                doc.url_pdf = novo_link
                doc.resumo_ia = None
                session.commit()

                # 3. 🔥 APAGA O ARQUIVO DA PASTA REVISÃO PARA SUMIR DE LÁ
                if file_id:
                    obter_drive_manager().deletar_arquivo(file_id)

                # --- DAQUI PARA BAIXO SEGUE O SEU CÓDIGO DA CONTAGEM DE PENDENTES QUE JÁ ESTÁ PERFEITO ---
                ticker = doc.ativo.ticker
                pendentes_restantes = session.query(DocumentosQualitativos).join(Ativo).filter(
                    Ativo.ticker == ticker, 
                    DocumentosQualitativos.status_processamento == "AGUARDANDO_REVISAO"
                ).count()

                markup = InlineKeyboardMarkup(row_width=1)
                tipo_retorno = tipo_cat.lower() if tipo_cat == "FII" else "acao"

                if pendentes_restantes > 0:
                    markup.add(
                        InlineKeyboardButton(text=f"👉 Continuar Revisando ({ticker})", callback_data=f"rev_t_{ticker}"),
                        InlineKeyboardButton(text="🔙 Voltar à Central de Revisão", callback_data="rev_start")
                    )
                    texto_resposta = (
                        f"✅ **Arquivo Guardado com Sucesso!**\n\n📁 **Ticker:** `{ticker}`\n📑 **Tipo:** `{tipo_nome_limpo}`\n\n⚠️ _Ainda restam {pendentes_restantes} documento(s) para revisar neste ativo._"
                    )
                else:
                    markup.add(
                        InlineKeyboardButton(text=f"🏢 Ir para o Painel de {ticker}", callback_data=f"painel_{ticker}_{tipo_retorno}"),
                        InlineKeyboardButton(text="🔙 Voltar para a Central de Revisão", callback_data="rev_start")
                    )
                    texto_resposta = f"🎉 **Fila de {ticker} Concluída!**\n\nNão há mais nenhum documento pendente para este ativo."

                bot.edit_message_text(texto_resposta, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            else:
                bot.answer_callback_query(call.id, "❌ Erro ao mover no Drive!")

        # AÇÃO: Usuário decidiu que o documento era lixo
        elif acao == 'del':
            bot.answer_callback_query(call.id, "Apagando do Drive...")
            doc_id = partes[2]
            doc = session.query(DocumentosQualitativos).get(doc_id)
            
            # Guardamos o ticker ANTES de deletar para o botão de voltar não quebrar
            ticker_atual = doc.ativo.ticker 
            
            file_id = extrair_file_id(doc.url_pdf)

            # Só tenta deletar no drive se tiver um link válido
            deletou_drive = False
            if file_id:
                deletou_drive = obter_drive_manager().deletar_arquivo(file_id)
            else:
                deletou_drive = True # Se não tem link, considera deletado para podermos apagar do banco

            if deletou_drive:
                doc.status_processamento = "REJEITADO_MANUAL"
                doc.resumo_ia = None
                session.commit()
                
                m = InlineKeyboardMarkup().add(InlineKeyboardButton(text="🔙 Voltar aos Pendentes", callback_data=f"rev_t_{ticker_atual}"))
                bot.edit_message_text(f"🗑️ Documento ignorado e apagado com sucesso.", call.message.chat.id, call.message.message_id, reply_markup=m)
            else:
                bot.answer_callback_query(call.id, "❌ Erro ao apagar no Drive!")

    except Exception as e:
        print(f"Erro no painel de revisão: {e}")
        try:
            bot.answer_callback_query(call.id, "⚠️ Erro interno. Tente novamente.")
        except:
            pass
    finally:
        session.close()
