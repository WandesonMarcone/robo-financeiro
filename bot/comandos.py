import threading
import time
import requests
import config
import fitz
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import func, or_
from bot.loader import bot
from bot import menu_principal, permissoes
from bot.telegram_utils import montar_guia_comandos
from atualizador_documentos import SessionDB 
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
from pipeline_dados.coletor_fiis import ano_padrao_coleta, processar_informes_fiis_cvm
from modules.utils import conectar_gspread

from modules.scraper_fiis import rodar_garimpo_fiis # <--- Importe o arquivo que corrigimos


def _ano_do_comando(message):
    texto = (message.text or "").split()
    if len(texto) > 1 and texto[1].isdigit():
        return int(texto[1])
    return ano_padrao_coleta()

# ==========================================
# 🔒 UTILITÁRIOS DE SEGURANÇA
# ==========================================
def sanitizar_valor_planilha(valor):
    """Neutraliza formula injection (ex.: =SUM, +cmd, -x, @x) antes de gravar no Google Sheets."""
    texto = str(valor or "").strip()
    if texto.startswith(("=", "+", "-", "@")):
        return "'" + texto
    return texto

# ==========================================
# 🧭 MENUS DE NAVEGAÇÃO E INTERFACE (UI)
# ==========================================
@bot.message_handler(commands=['menu'])
def enviar_menu(message):
    autor = getattr(message, "from_user", None)
    autor_id = getattr(autor, "id", None)
    menu_principal.enviar_painel(message.chat.id, autor_id, autor)

@bot.message_handler(commands=['help'])
def enviar_ajuda(message):
    """Guia de comandos sob demanda, restrito ao papel do usuário.

    A permissão do comando é validada pelo controle central (``bot.permissoes``
    via ``bot.loader``); ainda assim o conteúdo é montado a partir do papel
    resolvido no servidor, para nunca exibir opções administrativas a um usuário
    comum.
    """
    autor = getattr(message, "from_user", None)
    autor_id = getattr(autor, "id", None)
    papel, status, formulario_ativo = permissoes.contexto_ajuda(autor_id)
    markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton("🏠 Abrir o menu", callback_data="voltar_menu")
    )
    bot.send_message(
        message.chat.id,
        montar_guia_comandos(
            papel, status=status, formulario_ativo=formulario_ativo
        ),
        parse_mode="Markdown",
        reply_markup=markup,
    )

@bot.message_handler(commands=['status'])
def status_banco(message):
    session = SessionDB() 
    try:
        total_ativos = session.query(Ativo).count()
        total_docs = session.query(DocumentosQualitativos).count()
        ultimos = session.query(Ativo.ticker).order_by(Ativo.id.desc()).limit(5).all()
        lista_tickers = ", ".join([a[0] for a in ultimos])
        ultima_data = session.query(func.max(DocumentosQualitativos.data_publicacao)).scalar()

        resposta = (
            f"📊 **Painel de Controle do Motor de Dados**\n\n"
            f"🏢 **Ativos monitorados:** {total_ativos}\n"
            f"📄 **Documentos salvos:** {total_docs}\n"
            f"📅 **Última atualização:** {ultima_data}\n\n"
            f"🚀 **Últimos ativos:**\n{lista_tickers}"
        )
        bot.reply_to(message, resposta)
    except Exception as e:
        bot.reply_to(message, f"❌ Erro ao consultar banco: {e}")
    finally:
        session.close() 

@bot.message_handler(commands=['relatorios', 'docs'])
def enviar_ultimos_relatorios(message):
    # Usuario comum ve somente documentos dos proprios favoritos ativos; o admin
    # mantem a visao ampla (``None`` = sem filtro). Falha segura: sem conta
    # aprovada/favoritos, nada e listado.
    autor = getattr(message, "from_user", None)
    permitidos = permissoes.tickers_permitidos(getattr(autor, "id", None))
    if permitidos is not None and not permitidos:
        bot.reply_to(
            message,
            "📭 Você ainda não acompanha nenhum ativo. "
            "Use ⭐ Gerenciar favoritos no /menu para escolher.",
        )
        return

    bot.reply_to(message, "🔎 Buscando os últimos documentos no cofre...")
    session = SessionDB()
    try:
        consulta = session.query(DocumentosQualitativos, Ativo)\
            .join(Ativo, DocumentosQualitativos.ativo_id == Ativo.id)
        if permitidos is not None:
            consulta = consulta.filter(Ativo.ticker.in_(sorted(permitidos)))
        ultimos_docs = consulta\
            .order_by(DocumentosQualitativos.data_publicacao.desc())\
            .limit(10).all()

        if not ultimos_docs:
            bot.send_message(message.chat.id, "📭 Nenhum documento encontrado no banco ainda.")
            return

        resposta = "📄 **Últimos Relatórios Capturados:**\n\n"
        for doc, ativo in ultimos_docs:
            data_formatada = doc.data_publicacao.strftime('%d/%m/%Y')
            resposta += f"🏢 **{ativo.ticker}** - {data_formatada}\n"
            resposta += f"🏷️ Tipo: {doc.tipo_documento}\n"
            if doc.assunto and doc.assunto.strip():
                resposta += f"📌 Assunto: {doc.assunto}\n"
            resposta += f"🔗 [Acessar PDF]({doc.url_pdf})\n"
            resposta += "➖➖➖➖➖➖➖➖➖➖\n"

        bot.send_message(message.chat.id, resposta, parse_mode='Markdown', disable_web_page_preview=True)
    except Exception as e:
        bot.send_message(message.chat.id, "❌ Ops! Deu um erro ao tentar ler o banco de dados.")
    finally:
        session.close()

# ==========================================
# 📊 COMANDOS DE PLANILHA DO GOOGLE E GESTÃO
# ==========================================
@bot.message_handler(commands=['adicionar'])
def comando_adicionar(message):
    try:
        partes = message.text.split()
        if len(partes) < 2:
            bot.reply_to(message, "⚠️ Uso correto: `/adicionar TICKER` (ex: /adicionar BBAS3)", parse_mode="Markdown")
            return

        ticker = partes[1].strip().upper()
        ticker = sanitizar_valor_planilha(ticker)

        if not ticker or not ticker.isalnum() or len(ticker) > 10:
            bot.reply_to(message, "❌ Ticker inválido. Use apenas letras e números (ex: BBAS3, MXRF11).")
            return

        bot.reply_to(message, f"A procurar {ticker} e a injetar na Planilha do Google...")

        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        is_fii = True if ticker.endswith('11') else False
        nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
        aba = planilha.worksheet(nome_aba)

        dados = aba.get_all_values()
        proxima_linha = len(dados) + 1
        aba.update(f'A{proxima_linha}', [[ticker]])

        bot.send_message(message.chat.id, f"✅ *{ticker}* adicionado com sucesso na aba `{nome_aba}`!", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Erro ao adicionar ativo: {e}")

@bot.message_handler(commands=['forcar_varredura'])
def acionar_varredura_manual(message):
    chat_id = message.chat.id
    texto = (message.text or "").split()
    dias = 60
    if len(texto) > 1 and texto[1].isdigit():
        dias = int(texto[1])
    bot.reply_to(
        message,
        f"Varredura FNET de FIIs (ultimos {dias} dia(s)) em segundo plano. "
        "Aguarde o aviso de conclusao!",
    )

    def tarefa_pesada_background(janela):
        import logging

        log_thread = logging.getLogger("robo.varredura")
        log_thread.info(
            "Thread FNET iniciada chat_id=%s dias=%s", chat_id, janela
        )
        try:
            from pipeline_dados.coletor_fnet import ColetorFnet
            from atualizador_documentos import rotina_processar_pendentes

            session = SessionDB()
            try:
                resultado = ColetorFnet(session).coletar(dias=janela)
            finally:
                session.close()
            bot.send_message(chat_id, resultado.mensagem_telegram())
            bot.send_message(
                chat_id,
                "Processando fila PENDENTE (Drive/IA), inclusive residual.",
            )
            processamento = rotina_processar_pendentes()
            bot.send_message(chat_id, processamento.mensagem_telegram())
            log_thread.info(
                "Thread FNET concluida chat_id=%s gravados=%s fila=%s processados=%s",
                chat_id,
                resultado.gravados,
                processamento.fila,
                processamento.processados,
            )
        except Exception as e:
            log_thread.exception("Thread FNET falhou chat_id=%s", chat_id)
            bot.send_message(
                chat_id,
                f"Varredura FNET de FIIs: falha de processamento ou persistencia ({e}).",
            )

    threading.Thread(target=tarefa_pesada_background, args=(dias,)).start()

@bot.message_handler(commands=['forcar_docs_acoes'])
def rodar_docs_acoes(message):
    chat_id = message.chat.id
    ano_escolhido = _ano_do_comando(message)
    bot.reply_to(
        message,
        f"Varredura de PDFs de acoes na CVM ({ano_escolhido}) em segundo plano. "
        "Aguarde o aviso de conclusao!",
    )

    def tarefa_docs_background(ano):
        try:
            from pipeline_dados.coletor_docs_acoes import RelatoriosAcoesCVM
            from pipeline_dados.coletor_docs_acoes import STATUS_GRAVADO as DOCS_GRAVADO

            session = SessionDB()
            try:
                resultado = RelatoriosAcoesCVM(session).vasculhar_documentos(ano)
            finally:
                session.close()
            bot.send_message(chat_id, resultado.mensagem_telegram())
            if resultado.status == DOCS_GRAVADO and resultado.gravados > 0:
                bot.send_message(
                    chat_id,
                    "Documentos novos gravados; iniciando classificacao por IA.",
                )
                rodar_ia_acoes(message)
        except Exception as e:
            bot.send_message(
                chat_id,
                f"Varredura de PDFs de acoes ({ano}): falha de processamento "
                f"ou persistencia ({e}).",
            )

    threading.Thread(target=tarefa_docs_background, args=(ano_escolhido,)).start()

@bot.message_handler(commands=['processar_acoes_ia'])
def rodar_ia_acoes(message):
    bot.send_message(message.chat.id, "🧠 *Iniciando motor de IA para Ações...*\nLendo PDFs da CVM, classificando e enviando ao Drive em segundo plano. Isso pode levar alguns minutos.", parse_mode="Markdown")
    
    def tarefa_ia_background():
        try:
            from atualizador_documentos import rotina_processar_acoes

            resultado = rotina_processar_acoes()
            bot.send_message(message.chat.id, resultado.mensagem_telegram())
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Erro fatal no processamento da IA: {str(e)}")
            
    threading.Thread(target=tarefa_ia_background).start()


@bot.message_handler(commands=['forcar_cvm'])
def rodar_cvm(message):
    chat_id = message.chat.id
    ano_escolhido = _ano_do_comando(message)
    bot.reply_to(
        message,
        f"Baixando ITR de acoes da CVM ({ano_escolhido}) em segundo plano. "
        "Aguarde o aviso de conclusao!",
    )

    def tarefa_cvm_background(ano):
        try:
            from pipeline_dados.coletor_cvm import AcoesCVMReader

            session = SessionDB()
            try:
                resultado = AcoesCVMReader(session).atualizar_acoes(ano)
            finally:
                session.close()
            bot.send_message(chat_id, resultado.mensagem_telegram())
        except Exception as e:
            bot.send_message(
                chat_id,
                f"Coleta CVM ITR ({ano}): falha de processamento ou persistencia ({e}).",
            )

    threading.Thread(target=tarefa_cvm_background, args=(ano_escolhido,)).start()


@bot.message_handler(commands=['forcar_fiis'])
def cmd_forcar_fiis(message):
    chat_id = message.chat.id
    ano_escolhido = _ano_do_comando(message)
    bot.reply_to(
        message,
        f"Baixando informes mensais de FIIs ({ano_escolhido}) em segundo plano. "
        "Aguarde o aviso de conclusao!",
    )

    def background_coleta(ano):
        try:
            resultado = processar_informes_fiis_cvm(ano=ano)
            bot.send_message(chat_id, resultado.mensagem_telegram())
        except Exception as e:
            bot.send_message(
                chat_id,
                f"Coleta de FIIs ({ano}): falha de processamento ou persistencia ({e}).",
            )

    threading.Thread(target=background_coleta, args=(ano_escolhido,)).start()

@bot.message_handler(commands=['alimentar_ia'])
def alimentar_ia_passado(message):
    bot.send_message(message.chat.id, "⏳ *Iniciando a Varredura Profunda!* Procurando PDFs antigos...", parse_mode="Markdown")

    def tarefa_leitura():
        try:
            from pipeline_dados.banco_dados import DocumentosQualitativos
            from atualizador_documentos import SessionDB
            from sqlalchemy import or_
            import requests
            import fitz
            import io

            session = SessionDB()
            
            # 🔴 CORREÇÃO 1: Pega documentos com coluna Nula (None) OU Vazia ("")
            docs = session.query(DocumentosQualitativos).filter(
                or_(DocumentosQualitativos.texto_extraido == None, DocumentosQualitativos.texto_extraido == ""),
                DocumentosQualitativos.url_pdf != None
            ).all()

            lidos = 0
            ignorados = 0
            erros = 0
            
            for doc in docs:
                nome_low = str(doc.tipo_documento).lower()
                
                # 🔴 CORREÇÃO 2: Inclusão de "apresenta" (MXRF11) e "informe"
                if "gerencial" in nome_low or "fato" in nome_low or "release" in nome_low or "apresenta" in nome_low or "informe" in nome_low:
                    try:
                        resp = requests.get(doc.url_pdf, timeout=15)
                        if resp.status_code == 200:
                            pdf_mem = io.BytesIO(resp.content)
                            doc_fitz = fitz.open(stream=pdf_mem, filetype="pdf")
                            
                            # Sugando o texto
                            texto = "".join([pagina.get_text("text") + "\n" for pagina in doc_fitz[:12]])
                            texto_limpo = " ".join(texto.split())[:15000]
                            
                            if texto_limpo:
                                doc.texto_extraido = texto_limpo
                                lidos += 1
                                session.commit()
                            else:
                                erros += 1
                            doc_fitz.close()
                        else:
                            erros += 1
                    except Exception as e:
                        erros += 1
                        pass
                else:
                    ignorados += 1
                    
            session.close()
            
            if lidos == 0:
                txt_final = (
                    f"Alimentacao de IA: nenhum texto extraido.\n"
                    f"PDFs sem texto: {len(docs)}\n"
                    f"Ignorados (nao sao relatorios): {ignorados}\n"
                    f"Falhas (link quebrado/scan): {erros}"
                )
            else:
                txt_final = (
                    f"Alimentacao de IA concluida.\n"
                    f"PDFs sem texto: {len(docs)}\n"
                    f"Textos extraidos: {lidos}\n"
                    f"Ignorados (nao sao relatorios): {ignorados}\n"
                    f"Falhas (link quebrado/scan): {erros}"
                )
            bot.send_message(message.chat.id, txt_final)
            
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Erro fatal na tarefa: {e}")

    import threading
    threading.Thread(target=tarefa_leitura).start()

@bot.message_handler(commands=['mapear_nomes'])
def comando_mapear_nomes_b3(message):
    bot.send_message(message.chat.id, "🕵️‍♂️ Comando recebido! Como a B3 é lenta, enviei essa tarefa para o segundo plano. Pode continuar usando o Telegram normalmente, te enviarei o arquivo TXT assim que estiver pronto.")

    def tarefa_pesada():
        url = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
        nomes_unicos = set()

        try:
            for start in range(0, 5000, 50):
                params = {'d': '1', 's': str(start), 'l': '50', 'tipoFundo': '1'}
                sucesso = False
                for tentativa in range(3): 
                    try:
                        res = requests.get(url, params=params, headers=headers, timeout=45)
                        res.raise_for_status() 
                        data = res.json().get('data', [])
                        sucesso = True
                        break 
                    except Exception as e:
                        time.sleep(2) 

                if not sucesso:
                    bot.send_message(message.chat.id, f"⚠️ Aviso: A B3 travou na página {start}. O arquivo será gerado com o que consegui até agora.")
                    break

                if not data:
                    break 

                for item in data:
                    descricao = item.get('descricaoFundo', '').upper().strip()
                    if descricao:
                        nomes_unicos.add(descricao)

                time.sleep(1.5) 

            lista_ordenada = sorted(list(nomes_unicos))
            texto_final = "\n".join(lista_ordenada)
            caminho_arquivo = "/tmp/nomes_b3_auditoria.txt"

            with open(caminho_arquivo, "w", encoding="utf-8") as f:
                f.write(f"--- CATÁLOGO DE NOMES DA B3 ({len(lista_ordenada)} fundos encontrados) ---\n\n")
                f.write(texto_final)

            with open(caminho_arquivo, "rb") as f:
                bot.send_document(message.chat.id, f, caption="🎯 Auditoria concluída em segundo plano! Aqui está a lista exata da B3.")

        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Erro crítico na thread de mapeamento: {str(e)}")

    thread = threading.Thread(target=tarefa_pesada)
    thread.start()

@bot.message_handler(commands=['resetar_docs'])
def limpar_banco_documentos(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("💥 SIM, apagar tudo", callback_data="confirmar_reset"),
               InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_reset"))
    bot.send_message(
        message.chat.id,
        "💥 *ATENÇÃO:* isso apagará TODOS os registros de documentos do banco de dados. Essa ação é irreversível. Deseja continuar?",
        parse_mode="Markdown",
        reply_markup=markup,
    )

@bot.callback_query_handler(func=lambda call: call.data in ("confirmar_reset", "cancelar_reset"))
def tratar_reset_docs(call):
    chat_id = call.message.chat.id
    mensagem_id = call.message.message_id

    if call.data == "cancelar_reset":
        bot.answer_callback_query(call.id, "Operação cancelada.")
        bot.edit_message_text("✅ Operação cancelada. Nenhum dado foi alterado.", chat_id, mensagem_id)
        return

    try:
        from atualizador_documentos import SessionDB
        from pipeline_dados.banco_dados import DocumentosQualitativos

        session = SessionDB()
        apagados = session.query(DocumentosQualitativos).delete()
        session.commit()
        session.close()

        bot.answer_callback_query(call.id, "Limpeza concluída.")
        bot.edit_message_text(
            f"✅ **Limpeza Concluída!**\n`{apagados}` registros de PDFs antigos foram apagados.",
            chat_id,
            mensagem_id,
            parse_mode="Markdown",
        )
    except Exception as e:
        bot.answer_callback_query(call.id, "Erro ao apagar.")
        bot.edit_message_text(f"❌ Erro ao apagar: {e}", chat_id, mensagem_id)
