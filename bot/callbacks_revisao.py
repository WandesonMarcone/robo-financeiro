import re
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Imports da nossa nova arquitetura
from bot.loader import bot
from config import TIPOS_DOC
from atualizador_documentos import SessionDB
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
from modules.GoogleDriveManager import GoogleDriveManager

# Instancia o gerenciador do Drive exclusivo para este módulo
drive_manager = GoogleDriveManager()

def extrair_file_id(url):
    """Extrai apenas o ID alfanumérico do link longo do Google Drive"""
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', str(url))
    return match.group(1) if match else None

# O comando e a tela de abertura moram aqui agora, pertinho dos callbacks!
@bot.message_handler(commands=['revisao'])
def comando_painel_revisao(message):
    enviar_painel_tickers(message.chat.id)

def enviar_painel_tickers(chat_id, message_id=None):
    """Busca no banco todos os documentos marcados como suspeitos e agrupa por Fundo"""
    session = SessionDB()
    try:
        pendentes = session.query(DocumentosQualitativos).filter_by(status_processamento="AGUARDANDO_REVISAO").all()

        if not pendentes:
            msg = "🎉 Excelente! A sua mesa está limpa. Não há documentos aguardando revisão."
            if message_id: bot.edit_message_text(msg, chat_id, message_id)
            else: bot.send_message(chat_id, msg)
            return

        tickers = sorted(list(set([doc.ativo.ticker for doc in pendentes])))
        markup = InlineKeyboardMarkup()

        for t in tickers:
            qtd = len([d for d in pendentes if d.ativo.ticker == t])
            markup.add(InlineKeyboardButton(text=f"📁 {t} ({qtd} docs)", callback_data=f"rev_t_{t}"))

        msg = "⚠️ **Central de Revisão**\n\nEstes FIIs possuem documentos suspeitos ou em formato de imagem. Selecione um para analisar:"
        if message_id:
            bot.edit_message_text(msg, chat_id, message_id, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="Markdown")
    finally:
        session.close()

# 🧠 O CÉREBRO DA REVISÃO (Lida com todos os cliques dos botões)
@bot.callback_query_handler(func=lambda call: call.data.startswith('rev_'))
def processar_revisao(call):
    partes = call.data.split('_')
    acao = partes[1]
    session = SessionDB()

    try:
        # AÇÃO: Voltar ao menu inicial de revisão
        if acao == 'start':
            enviar_painel_tickers(call.message.chat.id, call.message.message_id)

        # AÇÃO: Mostrar lista de documentos suspeitos de um fundo específico
        elif acao == 't':
            ticker = partes[2]
            pendentes = session.query(DocumentosQualitativos).join(Ativo).filter(
                Ativo.ticker == ticker, 
                DocumentosQualitativos.status_processamento == "AGUARDANDO_REVISAO"
            ).all()

            markup = InlineKeyboardMarkup()
            for doc in pendentes:
                btn_text = f"📄 {doc.assunto} | ID: {doc.id_b3}"
                markup.add(InlineKeyboardButton(text=btn_text, callback_data=f"rev_d_{doc.id}"))
                
            # O botão de voltar TEM que ficar fora do loop, e usar apenas a variável 'ticker'
            markup.add(InlineKeyboardButton(text="🔙 Voltar à Central de Revisão", callback_data="rev_start"))

            bot.edit_message_text(f"📑 **Análise: {ticker}**\n\nQual documento você quer olhar?", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

        # AÇÃO: Abrir as opções (Visualizar, Salvar, Apagar) de um documento específico
        elif acao == 'd':
            doc_id = partes[2]
            doc = session.query(DocumentosQualitativos).get(doc_id)

            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="🔗 Visualizar PDF (Google Drive)", url=doc.url_pdf))
            markup.add(
                InlineKeyboardButton(text="✅ Classificar e Salvar", callback_data=f"rev_app_{doc.id}"),
                InlineKeyboardButton(text="🗑️ Jogar no Lixo", callback_data=f"rev_del_{doc.id}")
            )
            markup.add(InlineKeyboardButton(text="🔙 Voltar", callback_data=f"rev_t_{doc.ativo.ticker}"))

            txt = f"🔍 **Inspecionando Documento**\n\n**Fundo:** {doc.ativo.ticker}\n**Data:** {doc.assunto}\n**Leitura da B3:** {doc.tipo_documento}\n\nO que deseja fazer?"
            bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

        # AÇÃO: Usuário decidiu salvar, abre o catálogo de tipos de documento
        elif acao == 'app':
            doc_id = partes[2]
            doc = session.query(DocumentosQualitativos).get(doc_id)

            markup = InlineKeyboardMarkup()
            for id_tipo, nome_tipo in TIPOS_DOC.items():
                markup.add(InlineKeyboardButton(text=f"📂 {nome_tipo}", callback_data=f"rev_typ_{doc.id}_{id_tipo}"))
            markup.add(InlineKeyboardButton(text="🔙 Cancelar", callback_data=f"rev_d_{doc.id}"))

            bot.edit_message_text(f"**Renomear Arquivo**\n\nO que é este documento do `{doc.ativo.ticker}` na verdade?", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

        # AÇÃO: A MÁGICA - Renomeia no Drive, move de pasta e atualiza o Banco de Dados
        elif acao == 'typ':
            doc_id = partes[2]
            tipo_id = partes[3]
            tipo_nome_limpo = TIPOS_DOC[tipo_id]

            bot.answer_callback_query(call.id, "Organizando no Drive...")

            doc = session.query(DocumentosQualitativos).get(doc_id)
            file_id = extrair_file_id(doc.url_pdf)

            mes_ref = datetime.now().strftime("%Y-%m")
            if doc.assunto and '-' in doc.assunto:
                p = doc.assunto.split('-')
                if len(p) == 3: mes_ref = f"{p[2]}-{p[1]}"

            novo_nome_pdf = f"{tipo_nome_limpo}_{doc.assunto}_{doc.id_b3}.pdf"

            novo_link = drive_manager.mover_e_renomear_arquivo(file_id, doc.ativo.ticker, mes_ref, novo_nome_pdf)

            if novo_link:
                doc.status_processamento = "SALVO_DRIVE"
                doc.tipo_documento = tipo_nome_limpo
                doc.url_pdf = novo_link
                session.commit()

                # Pega o ticker do ativo atual
                ticker_atual = doc.ativo.ticker

                # Conta quantos documentos AINDA restam pendentes para ESTE fundo específico
                pendentes_restantes = session.query(DocumentosQualitativos).join(Ativo).filter(
                    Ativo.ticker == ticker_atual, 
                    DocumentosQualitativos.status_processamento == "AGUARDANDO_REVISAO"
                ).count()

                markup = InlineKeyboardMarkup(row_width=1)

                if pendentes_restantes > 0:
                    # Se ainda tem documentos para este fundo, oferece o botão de continuar nele
                    markup.add(
                        InlineKeyboardButton(text=f"👉 Continuar Revisando ({ticker_atual})", callback_data=f"rev_ticker_{ticker_atual}"),
                        InlineKeyboardButton(text="🔙 Voltar à Central de Revisão", callback_data="rev_start")
                    )
                    
                    texto_resposta = (
                        f"✅ **Arquivo Guardado com Sucesso!**\n\n"
                        f"📁 **Ticker:** `{ticker_atual}`\n"
                        f"📑 **Tipo:** `{tipo_nome_limpo}`\n\n"
                        f"⚠️ _Ainda restam {pendentes_restantes} documento(s) para revisar neste fundo._"
                    )
                else:
                    # 🎯 AQUI ENTRA A SUA REGRA PERSONALIZADA!
                    # Se acabaram os documentos deste fundo, mostra os dois botões de escolha:
                    markup.add(
                        InlineKeyboardButton(text=f"🏢 Ir para o Painel do {ticker_atual}", callback_data=f"painel_{ticker_atual}_fii"),
                        InlineKeyboardButton(text="🔙 Voltar para a Central de Revisão", callback_data="rev_start")
                    )
                    
                    texto_resposta = (
                        f"🎉 **Fila do {ticker_atual} Concluída!**\n\n"
                        f"Não há mais nenhum documento pendente de revisão para este fundo.\n\n"
                        f"O que você deseja fazer agora?"
                    )

                bot.edit_message_text(texto_resposta, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            else:
                bot.answer_callback_query(call.id, "❌ Erro ao mover no Drive!")

        # AÇÃO: Usuário decidiu que o documento era lixo
        elif acao == 'del':
            doc_id = partes[2]
            bot.answer_callback_query(call.id, "Apagando do Drive...")
            doc = session.query(DocumentosQualitativos).get(doc_id)
            file_id = extrair_file_id(doc.url_pdf)

            if drive_manager.deletar_arquivo(file_id):
                doc.status_processamento = "REJEITADO_MANUAL"
                session.commit()
                m = InlineKeyboardMarkup().add(InlineKeyboardButton(text="🔙 Voltar ao Painel", callback_data="rev_start"))
                bot.edit_message_text(f"🗑️ Documento apagado com sucesso.", call.message.chat.id, call.message.message_id, reply_markup=m)
            else:
                bot.answer_callback_query(call.id, "❌ Erro ao apagar no Drive!")

    except Exception as e:
        print(f"Erro no painel de revisão: {e}")
    finally:
        session.close()
