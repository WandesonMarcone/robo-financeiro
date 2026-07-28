import re
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Imports da nossa nova arquitetura
from bot.loader import bot
from config import TIPOS_DOC_FII, TIPOS_DOC_ACAO
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
    """Busca no banco todos os documentos marcados como suspeitos e agrupa por Ativo (FII/Ação)"""
    session = SessionDB()
    try:
        # Puxa TUDO que está aguardando revisão (sem filtrar por tipo)
        pendentes = session.query(DocumentosQualitativos).filter_by(status_processamento="AGUARDANDO_REVISAO").all()

        if not pendentes:
            msg = "🎉 Excelente! A sua mesa está limpa. Não há documentos aguardando revisão."
            if message_id: bot.edit_message_text(msg, chat_id, message_id)
            else: bot.send_message(chat_id, msg)
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

        msg = "⚠️ **Central de Revisão Híbrida**\n\nEstes FIIs e Ações possuem documentos pendentes. Selecione um para analisar:"
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
            
            # 🛡️ Trava de Segurança do Telegram: Só cria o botão se o link existir e for válido!
            if doc.url_pdf and doc.url_pdf.startswith("http"):
                markup.add(InlineKeyboardButton(text="🔗 Abrir PDF no Drive", url=doc.url_pdf))
            
            # Usamos row() em vez de add() para os botões ficarem lado a lado
            markup.row(
                InlineKeyboardButton(text="✅ Classificar", callback_data=f"rev_app_{doc.id}"),
                InlineKeyboardButton(text="🗑️ Apagar", callback_data=f"rev_del_{doc.id}")
            )
            markup.add(InlineKeyboardButton(text="🔙 Voltar", callback_data=f"rev_t_{doc.ativo.ticker}"))

            # 🎨 Embelezamento do texto do painel
            data_limpa = doc.assunto.split(" ")[0].replace("-", "/") if doc.assunto else "Desconhecida"
            tipo_leitura = doc.tipo_documento if doc.tipo_documento else "Não identificado"

            txt = (
                f"🔍 **Inspecionando Documento**\n\n"
                f"🏢 **Ativo:** `{doc.ativo.ticker}`\n"
                f"📅 **Data:** `{data_limpa}`\n"
                f"🤖 **Leitura Inicial:** `{tipo_leitura}`\n\n"
            )
            
            # Se o link estiver quebrado no banco de dados, o bot te avisa
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
            novo_link = drive_manager.mover_arquivo_da_revisao_por_id(
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
                session.commit()

                # 3. 🔥 APAGA O ARQUIVO DA PASTA REVISÃO PARA SUMIR DE LÁ
                if file_id:
                    drive_manager.deletar_arquivo(file_id)

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
                deletou_drive = drive_manager.deletar_arquivo(file_id)
            else:
                deletou_drive = True # Se não tem link, considera deletado para podermos apagar do banco

            if deletou_drive:
                doc.status_processamento = "REJEITADO_MANUAL"
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
