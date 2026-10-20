import os
import time
import json
import logging
import re
import requests
import unicodedata
from datetime import datetime, timedelta
import config
from fnet_scraper import FnetDownloader
from modules.utils import conectar_gspread
from services.logo_service import (
    invalidar_file_id_logo,
    obter_bytes_logo_drive,
    obter_media_logo_rapida,
    registrar_falha_logo,
    registrar_file_id_logo,
)
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
from pipeline_dados.conexao import obter_session_factory
from config import MAPA_ISCAS_MASTER, TIPOS_DOC_FII

logger = logging.getLogger("robo.documentos")

# O cliente Groq NAO e mais instanciado na importacao: sem GROQ_API_KEY o modulo
# carrega normalmente e funcionalidades que nao usam IA continuam disponiveis. O
# erro controlado so surge quando uma operacao de IA e realmente solicitada.
_cliente_groq = None


class IAIndisponivelError(RuntimeError):
    """Erro controlado quando uma operacao exige IA e nao ha credencial."""


def obter_cliente_groq():
    """Cria o cliente Groq sob demanda ou falha com erro controlado.

    A mensagem de erro nunca inclui o valor da chave.
    """
    global _cliente_groq
    if _cliente_groq is None:
        chave = config.GROQ_API_KEY or os.environ.get("GROQ_API_KEY")
        if not chave:
            raise IAIndisponivelError(
                "GROQ_API_KEY ausente: a operacao de IA nao pode ser executada."
            )
        from groq import Groq

        _cliente_groq = Groq(api_key=chave)
    return _cliente_groq


def SessionDB():
    """Fabrica de sessoes do banco, criada apenas quando realmente usada.

    A conexao usa a URL normalizada (ver ``pipeline_dados.conexao``) e nunca faz
    fallback silencioso para SQLite.
    """
    return obter_session_factory()()

def obter_tickers_da_planilha():
    try:
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        aba = planilha.worksheet("BD_FIIs")
        tickers = aba.col_values(1)[1:] 
        return list(set([t.strip().upper() for t in tickers if t.strip()])) 
    except:
        return []

def normalizar_texto(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

# ==========================================
# 🚨 TRAVA 1: CLASSIFICAÇÃO HÍBRIDA COM IA (AUTO-SAVE)
# ==========================================
def classificar_documento_com_ia(nome_original, texto_extraido):
    if not texto_extraido: 
        return nome_original, 0 

    # 🛡️ HIGIENIZADOR: Remove caracteres invisíveis que dão Erro 400
    texto_limpo = re.sub(r'[^\x20-\x7E\u00A0-\u00FF]', ' ', str(texto_extraido)).strip()
    texto_limpo = texto_limpo[:1500] # Aumentei um pouco para a IA ter mais contexto

    if not texto_limpo: 
        return nome_original, 0

    lista_opcoes = ", ".join(TIPOS_DOC_FII.values())
    
    # Prompt de engenharia reversa exigindo JSON
    prompt = (
        f"Você é um analista financeiro sênior avaliando um PDF de Fundo Imobiliário. "
        f"O documento começa assim: '{texto_limpo}'\n\n"
        f"Classifique o documento escolhendo ESTRITAMENTE UMA destas opções: {lista_opcoes}.\n"
        f"Responda EXATAMENTE E APENAS com um objeto JSON válido, contendo as chaves 'tipo' e 'confianca'. "
        f"A chave 'confianca' deve ser um número inteiro de 0 a 100 representando sua certeza."
    )

    try:
        client = obter_cliente_groq()
    except IAIndisponivelError:
        logger.warning(
            "IA indisponivel (GROQ_API_KEY ausente). Classificacao automatica "
            "ignorada e documento mantido como '%s'.",
            nome_original,
        )
        return nome_original, 0

    try:
        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"} # 🚀 Força a Groq a cuspir JSON puro
        )
        resposta_str = chat.choices[0].message.content
        
        # Transforma a resposta da IA em um dicionário Python
        dados_ia = json.loads(resposta_str)
        tipo_ia = dados_ia.get("tipo", nome_original)
        confianca_ia = int(dados_ia.get("confianca", 0))

        # Validação: se a IA inventar uma palavra que não está na lista, zera a confiança
        if tipo_ia not in TIPOS_DOC_FII.values():
            return nome_original, 0

        return tipo_ia, confianca_ia

    except Exception as e:
        # Loga apenas o tipo da excecao: mensagens de SDK podem conter detalhes
        # da requisicao e nunca devem expor credenciais.
        logger.warning(
            "Erro ao consultar IA para classificacao hibrida (%s). "
            "Mantendo classificacao original.",
            type(e).__name__,
        )
        return nome_original, 0

def _chat_administrador():
    """Chat do administrador para alertas operacionais (nunca transmissao ampla)."""
    return (
        os.environ.get("TELEGRAM_ADMIN_ID")
        or getattr(config, "TELEGRAM_ADMIN_ID", None)
        or os.environ.get("TELEGRAM_CHAT_ID")
        or getattr(config, "TELEGRAM_CHAT_ID", None)
    )


def _enviar_mensagem_telegram(chat_id, mensagem, teclado=None, parse_mode=None):
    """Envia uma mensagem a UM chat específico. Retorna True em caso de sucesso."""
    if chat_id is None:
        return False
    token = (getattr(config, "TELEGRAM_BOT_TOKEN", None) or "").strip()
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN ausente; mensagem nao enviada.")
        return False
    payload = {"chat_id": chat_id, "text": mensagem}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if teclado:
        payload["reply_markup"] = json.dumps(teclado)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resposta = requests.post(url, data=payload, timeout=15)
        if resposta.status_code != 200:
            logger.warning(
                "Telegram recusou mensagem (status %s).", resposta.status_code
            )
            return False
        return True
    except Exception as e:
        # A URL contem o token do bot; registramos apenas o tipo do erro.
        logger.warning(
            "Falha ao enviar mensagem no Telegram (%s).", type(e).__name__
        )
        return False


def _enviar_foto_telegram(chat_id, ticker, foto, legenda, teclado=None, parse_mode=None):
    """Envia uma foto com legenda a UM chat e memoriza o ``file_id`` retornado."""
    if chat_id is None or not foto:
        return False
    token = (getattr(config, "TELEGRAM_BOT_TOKEN", None) or "").strip()
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN ausente; foto nao enviada.")
        return False
    payload = {"chat_id": chat_id, "caption": legenda}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if teclado:
        payload["reply_markup"] = json.dumps(teclado)
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    arquivos = None
    if str(foto).startswith("drive:"):
        conteudo = obter_bytes_logo_drive(foto)
        if not conteudo:
            return False
        arquivos = {"photo": ("logo.png", conteudo, "image/png")}
    else:
        payload["photo"] = foto
    try:
        resposta = requests.post(
            url, data=payload, files=arquivos, timeout=15
        )
        if resposta.status_code != 200:
            logger.warning(
                "Telegram recusou foto (status %s); usando fallback textual.",
                resposta.status_code,
            )
            if str(foto).startswith(("http://", "https://")):
                registrar_falha_logo(
                    ticker,
                    erro=f"HTTP {resposta.status_code}",
                    url_origem=foto,
                )
            elif not str(foto).startswith("drive:"):
                invalidar_file_id_logo(
                    ticker, erro=f"HTTP {resposta.status_code}"
                )
            return False
        try:
            fotos = resposta.json().get("result", {}).get("photo", [])
            if fotos:
                registrar_file_id_logo(ticker, fotos[-1].get("file_id"))
        except Exception:
            logger.debug("Nao foi possivel ler o file_id da foto enviada.")
        return True
    except Exception as e:
        # A URL contem o token do bot; registramos apenas o tipo do erro.
        logger.warning(
            "Falha ao enviar foto no Telegram (%s).", type(e).__name__
        )
        if str(foto).startswith(("http://", "https://")):
            registrar_falha_logo(ticker, erro=type(e).__name__, url_origem=foto)
        elif not str(foto).startswith("drive:"):
            invalidar_file_id_logo(ticker, erro=type(e).__name__)
        return False


def enviar_alerta_revisao_telegram(ticker, nome_doc, link_pdf, file_id, db_id):
    """Envia ao administrador a mensagem interativa de revisao manual."""
    chat_id = _chat_administrador()
    if not chat_id:
        logger.warning("Administrador nao configurado. Alerta nao enviado.")
        return False

    teclado = {
        "inline_keyboard": [
            [{"text": "✅ Classificar Arquivo", "callback_data": f"rev_app_{db_id}"}],
            [{"text": "🗑️ Apagar Lixo", "callback_data": f"rev_del_{db_id}"}],
        ]
    }

    mensagem = (
        f"🚨 **Documento Suspeito Identificado!**\n\n"
        f"A B3 diz que é de `{ticker}`, mas a IA precisa de sua ajuda para confirmar.\n"
        f"📄 **Leitura Inicial:** `{nome_doc}`\n\n"
        f"🔗 [Clique aqui para ler o PDF]({link_pdf})\n\n"
        f"O que faremos com ele?"
    )
    media = ""
    if (getattr(config, "TELEGRAM_BOT_TOKEN", None) or "").strip():
        media = obter_media_logo_rapida(ticker)
    if media and _enviar_foto_telegram(
        chat_id, ticker, media, mensagem, teclado=teclado, parse_mode="Markdown"
    ):
        return True
    return _enviar_mensagem_telegram(
        chat_id, mensagem, teclado=teclado, parse_mode="Markdown"
    )


def _destinatarios_do_ativo(ativo_id):
    """Usuarios aprovados e ativos que acompanham o ativo (vinculo confiavel)."""
    from pipeline_dados.repositorio_favoritos import RepositorioFavoritos

    return RepositorioFavoritos().usuarios_que_acompanham(ativo_id)


def notificar_documento_disponivel(
    ativo_id, ticker, nome_doc, data_publicacao=None, url_pdf=None
):
    """Notifica INDIVIDUALMENTE os seguidores de um ativo sobre um novo documento.

    A lista de destinatarios vem de ``usuarios_que_acompanham`` (vinculo
    persistente e aprovado); nao existe transmissao ampla. Sem associacao
    confiavel (ativo ausente ou nenhum seguidor), nada e enviado. Retorna a
    quantidade de mensagens entregues.
    """
    if ativo_id is None or not ticker:
        return 0
    try:
        destinatarios = _destinatarios_do_ativo(ativo_id)
    except Exception:
        logger.warning(
            "Falha ao resolver seguidores do ativo; documento nao distribuido",
            exc_info=True,
        )
        return 0

    data = None
    try:
        data = data_publicacao.strftime("%d/%m/%Y")
    except (AttributeError, ValueError):
        data = None

    linhas = [
        "📄 Novo documento disponível",
        "",
        f"🏢 Ativo: {ticker}",
        f"🏷️ Tipo: {nome_doc or 'Não informado'}",
    ]
    if data:
        linhas.append(f"🗓️ Publicação: {data}")
    if url_pdf:
        linhas.extend(["", f"🔗 {url_pdf}"])
    mensagem = "\n".join(linhas)
    teclado = {
        "inline_keyboard": [
            [
                {
                    "text": "📄 Ver novos documentos",
                    "callback_data": "novos_documentos",
                }
            ]
        ]
    }

    media = ""
    if (getattr(config, "TELEGRAM_BOT_TOKEN", None) or "").strip():
        media = obter_media_logo_rapida(ticker)

    enviados = 0
    for usuario in destinatarios:
        destino = getattr(usuario, "telegram_chat_id", None) or getattr(
            usuario, "telegram_user_id", None
        )
        if destino is None:
            continue
        entregue = False
        if media:
            entregue = _enviar_foto_telegram(
                destino, ticker, media, mensagem, teclado=teclado
            )
        if not entregue:
            entregue = _enviar_mensagem_telegram(destino, mensagem, teclado=teclado)
        if entregue:
            enviados += 1
    return enviados

# ==========================================
# CAMADA 1: COLETA
# ==========================================
def rotina_de_coleta_b3(dias=60, session=None, capturar_tudo=None):
    from pipeline_dados.coletor_fnet import ColetorFnet

    return ColetorFnet(session=session, capturar_tudo=capturar_tudo).coletar(dias=dias)

# ==========================================
# CAMADA 2 E 3: PROCESSAMENTO E REVISÃO
# ==========================================
class ResultadoProcessamento:
    """Contagens da esteira Drive/IA. Nao afirma sucesso se a fila estiver vazia."""

    def __init__(self, status_fila="PENDENTE"):
        self.status_fila = status_fila
        self.fila = 0
        self.processados = 0
        self.salvo_drive = 0
        self.revisao = 0
        self.erros = 0
        self.notificados = 0
        self.erro = None

    def mensagem_telegram(self):
        etiqueta = self.status_fila
        if self.erro:
            return (
                f"Processamento da fila ({etiqueta}): falha de processamento "
                f"({self.erro}). Processados: {self.processados}."
            )
        if self.fila == 0:
            return (
                f"Processamento da fila ({etiqueta}): nenhum documento "
                f"{etiqueta}. Nada processado."
            )
        return (
            f"Processamento da fila ({etiqueta}).\n"
            f"Na fila: {self.fila}\n"
            f"Processados: {self.processados}\n"
            f"Salvos no Drive: {self.salvo_drive}\n"
            f"Enviados para revisao: {self.revisao}\n"
            f"Erros: {self.erros}\n"
            f"Seguidores notificados: {self.notificados}"
        )


def rotina_processar_pendentes():
    resultado = ResultadoProcessamento("PENDENTE")
    session_fila = SessionDB()
    try:
        pendentes_ids = [
            doc.id
            for doc in session_fila.query(DocumentosQualitativos.id).filter(
                DocumentosQualitativos.status_processamento == "PENDENTE"
            ).all()
        ]
    finally:
        session_fila.close()

    resultado.fila = len(pendentes_ids)
    logger.info("Fila PENDENTE: %s documento(s)", resultado.fila)
    if not pendentes_ids:
        return resultado

    from modules.GoogleDriveManager import GoogleDriveManager

    b3 = FnetDownloader()
    drive_manager = GoogleDriveManager()

    print(f"⚙️ Processando {len(pendentes_ids)} documentos na fila...")

    for doc_id in pendentes_ids:
        # 2. 🟢 ABRE UMA NOVA SESSÃO EXCLUSIVA PARA ESTE ARQUIVO
        session = SessionDB()
        notificacao = None
        try:
            doc_db = session.query(DocumentosQualitativos).filter_by(id=doc_id).first()
            if not doc_db:
                continue

            ticker = doc_db.ativo.ticker
            id_doc = doc_db.id_b3
            data_ref = doc_db.assunto 

            print(f"🔄 Processando fila: {ticker} (ID {id_doc})...")

            pdf_bytes = b3.baixar_pdf(id_doc)
            if not pdf_bytes:
                doc_db.status_processamento = "ERRO_DOWNLOAD"
                session.commit()
                resultado.erros += 1
                resultado.processados += 1
                continue

            temp_filename = f"/tmp/{ticker}_{id_doc}.pdf"
            with open(temp_filename, "wb") as f: f.write(pdf_bytes)

            texto_pdf = ""
            try:
                import PyPDF2

                reader = PyPDF2.PdfReader(temp_filename)
                if len(reader.pages) > 0: 
                    texto_pdf = reader.pages[0].extract_text() or ""
            except: pass

            # ==========================================
            # 🤖 CAMADA HÍBRIDA DE IA E AUTO-SAVE
            # ==========================================
            texto_pdf = texto_pdf.strip()
            nome_ia, confianca = classificar_documento_com_ia(doc_db.tipo_documento, texto_pdf)

            nome_limpo = "".join([c for c in str(nome_ia).title() if c.isalnum() or c in (' ', '_', '-')]).strip()
            if len(nome_limpo) < 3:
                nome_limpo = "Documento_FII"

            partes_data = data_ref.split('-')
            mes_pasta = f"{partes_data[2]}-{partes_data[1]}" if len(partes_data) == 3 else datetime.now().strftime("%Y-%m")

            if confianca >= 80 and texto_pdf:
                print(f"🤖 IA tem {confianca}% de certeza. Auto-salvando '{nome_limpo}' para {ticker}...")
                link_gerado = drive_manager.upload_pdf_organizado(
                    caminho_arquivo=temp_filename,
                    nome_arquivo=f"{nome_limpo}_{data_ref}_{id_doc}.pdf",
                    ticker=ticker,
                    mes_ref=mes_pasta,
                    tipo_ativo=doc_db.ativo.tipo 
                )

                if link_gerado:
                    doc_db.url_pdf = link_gerado
                    doc_db.tipo_documento = nome_limpo
                    doc_db.status_processamento = "SALVO_DRIVE"
                    resultado.salvo_drive += 1
                    print(f"✅ Sucesso (Auto-save): {ticker} -> {nome_limpo}")

                    if "gerencial" in nome_limpo.lower() or "fato" in nome_limpo.lower():
                        print(f"🧠 Sugando texto profundo do PDF para a IA...")
                        try:
                            import fitz
                            doc_fitz = fitz.open(temp_filename)
                            texto_completo = "".join([pagina.get_text("text") + "\n" for pagina in doc_fitz[:12]])
                            doc_db.texto_extraido = " ".join(texto_completo.split())[:15000]
                            doc_fitz.close()
                        except Exception as e:
                            print(f"⚠️ Erro ao extrair RAG ({type(e).__name__}). Plano B (PyPDF2)...")
                            doc_db.texto_extraido = texto_pdf[:15000] if texto_pdf else None
                    else:
                        doc_db.texto_extraido = None
                    notificacao = {
                        "ativo_id": doc_db.ativo_id,
                        "ticker": ticker,
                        "nome_doc": nome_limpo,
                        "data_publicacao": doc_db.data_publicacao,
                        "url_pdf": link_gerado,
                    }
                else:
                    doc_db.status_processamento = "ERRO_DRIVE"
                    resultado.erros += 1

            else:
                print(f"⚠️ IA incerta ({confianca}%). Enviando para revisão manual...")
                file_id, link_gerado = drive_manager.upload_pdf_revisao(
                    caminho_arquivo=temp_filename,
                    nome_arquivo=f"REVISAR_{ticker}_{nome_limpo}_{data_ref}.pdf"
                )

                if file_id:
                    doc_db.status_processamento = "AGUARDANDO_REVISAO"
                    doc_db.url_pdf = link_gerado
                    resultado.revisao += 1
                    enviar_alerta_revisao_telegram(ticker, nome_limpo, link_gerado, file_id, doc_db.id)
                else:
                    doc_db.status_processamento = "ERRO_DRIVE"
                    resultado.erros += 1

            # 3. 💾 SALVA O PROGRESSO DESTE ARQUIVO E DELETA O TEMPORÁRIO
            session.commit()
            resultado.processados += 1
            if notificacao:
                resultado.notificados += notificar_documento_disponivel(**notificacao)
            if os.path.exists(temp_filename): os.remove(temp_filename)
            time.sleep(6) 

        except Exception as e:
            # Se der um erro bizarro, cancela SÓ este documento e continua vivo!
            print(f"❌ Erro crítico ao processar o documento {doc_id}: {e}")
            session.rollback()
            resultado.erros += 1
        finally:
            # 4. 🔴 FECHA A SESSÃO DO ARQUIVO PARA NÃO DAR TIMEOUT
            session.close()
    logger.info(
        "Fila PENDENTE encerrada: processados=%s salvo_drive=%s revisao=%s erros=%s notificados=%s",
        resultado.processados,
        resultado.salvo_drive,
        resultado.revisao,
        resultado.erros,
        resultado.notificados,
    )
    return resultado

def rotina_de_atualizacao_em_massa(dias=60, session=None, capturar_tudo=None):
    resultado = rotina_de_coleta_b3(
        dias=dias, session=session, capturar_tudo=capturar_tudo
    )
    resultado.processamento = rotina_processar_pendentes()
    return resultado

def rotina_processar_acoes():
    """Esteira exclusiva da Inteligência Artificial para documentos da CVM"""
    resultado = ResultadoProcessamento("PENDENTE_ACAO")
    session_fila = SessionDB()
    try:
        pendentes_ids = [
            doc.id
            for doc in session_fila.query(DocumentosQualitativos.id).filter(
                DocumentosQualitativos.status_processamento == "PENDENTE_ACAO"
            ).all()
        ]
    finally:
        session_fila.close()

    resultado.fila = len(pendentes_ids)
    logger.info("Fila PENDENTE_ACAO: %s documento(s)", resultado.fila)
    if not pendentes_ids:
        return resultado

    from modules.GoogleDriveManager import GoogleDriveManager

    drive_manager = GoogleDriveManager()

    print(f"⚙️ Processando {len(pendentes_ids)} documentos de AÇÕES na fila...")

    for doc_id in pendentes_ids:
        # 2. 🟢 SESSÃO EXCLUSIVA POR AÇÃO
        session = SessionDB()
        notificacao = None
        try:
            doc_db = session.query(DocumentosQualitativos).filter_by(id=doc_id).first()
            if not doc_db:
                continue

            ticker = doc_db.ativo.ticker
            url_pdf = doc_db.url_pdf

            mes_pasta = doc_db.data_publicacao.strftime("%Y-%m") if doc_db.data_publicacao else datetime.now().strftime("%Y-%m")
            data_str = doc_db.data_publicacao.strftime("%Y-%m-%d") if doc_db.data_publicacao else "SEM_DATA"

            print(f"🔄 IA Lendo: {ticker} (Data: {data_str})...")

            try:
                resposta = requests.get(url_pdf, timeout=15)
                if resposta.status_code != 200:
                    doc_db.status_processamento = "ERRO_DOWNLOAD"
                    session.commit()
                    resultado.erros += 1
                    resultado.processados += 1
                    continue
                pdf_bytes = resposta.content
            except Exception as e:
                print(f"⚠️ Erro ao baixar PDF CVM: {e}")
                doc_db.status_processamento = "ERRO_DOWNLOAD"
                session.commit()
                resultado.erros += 1
                resultado.processados += 1
                continue

            temp_filename = f"/tmp/{ticker}_cvm_temp.pdf"
            with open(temp_filename, "wb") as f: f.write(pdf_bytes)

            texto_pdf = ""
            try:
                import PyPDF2

                reader = PyPDF2.PdfReader(temp_filename)
                if len(reader.pages) > 0: 
                    texto_pdf = reader.pages[0].extract_text() or ""
            except: pass

            texto_pdf = texto_pdf.strip()

            nome_ia = classificar_documento_com_ia(doc_db.tipo_documento, texto_pdf)
            
            # Corrige a tupla de retorno caso a IA das ações não retorne a confiança
            if isinstance(nome_ia, tuple):
                nome_ia = nome_ia[0]

            nome_limpo = "".join([c for c in str(nome_ia).title() if c.isalnum() or c in (' ', '_', '-')]).strip()

            if len(nome_limpo) < 3: 
                nome_limpo = "".join([c for c in str(doc_db.tipo_documento).title() if c.isalnum() or c in (' ', '_', '-')]).strip()
                if len(nome_limpo) < 3: nome_limpo = "Documento_Acao"

            if not texto_pdf:
                file_id, link_gerado = drive_manager.upload_pdf_revisao(
                    caminho_arquivo=temp_filename,
                    nome_arquivo=f"REVISAR_{ticker}_{nome_limpo}_{data_str}.pdf"
                )
                if file_id:
                    doc_db.status_processamento = "AGUARDANDO_REVISAO"
                    doc_db.url_pdf = link_gerado
                    resultado.revisao += 1
                    print(f"🚧 {ticker} enviado para revisão manual.")
                else:
                    doc_db.status_processamento = "ERRO_DRIVE"
                    resultado.erros += 1
            else:
                link_gerado = drive_manager.upload_pdf_organizado(
                    caminho_arquivo=temp_filename,
                    nome_arquivo=f"{nome_limpo}_{data_str}.pdf",
                    ticker=ticker,
                    mes_ref=mes_pasta,
                    tipo_ativo="ACAO" 
                )

                if link_gerado:
                    doc_db.url_pdf = link_gerado
                    doc_db.tipo_documento = nome_limpo
                    doc_db.status_processamento = "SALVO_DRIVE"
                    resultado.salvo_drive += 1
                    print(f"✅ Sucesso: Drive Atualizado -> {nome_limpo}")

                    if "gerencial" in nome_limpo.lower() or "fato" in nome_limpo.lower() or "release" in nome_limpo.lower():
                        print(f"🧠 Sugando texto profundo do PDF para a IA...")
                        try:
                            import fitz
                            doc_fitz = fitz.open(temp_filename)
                            texto_completo = "".join([pagina.get_text("text") + "\n" for pagina in doc_fitz[:15]])
                            doc_db.texto_extraido = " ".join(texto_completo.split())[:15000]
                            doc_fitz.close()
                        except Exception as e:
                            print(f"⚠️ Erro ao extrair RAG ({type(e).__name__}). Plano B...")
                            doc_db.texto_extraido = texto_pdf[:15000] if texto_pdf else None
                    else:
                        doc_db.texto_extraido = None
                    notificacao = {
                        "ativo_id": doc_db.ativo_id,
                        "ticker": ticker,
                        "nome_doc": nome_limpo,
                        "data_publicacao": doc_db.data_publicacao,
                        "url_pdf": link_gerado,
                    }
                else:
                    doc_db.status_processamento = "ERRO_DRIVE"
                    resultado.erros += 1

            # 3. 💾 SALVA O PROGRESSO
            session.commit()
            resultado.processados += 1
            if notificacao:
                resultado.notificados += notificar_documento_disponivel(**notificacao)
            if os.path.exists(temp_filename): os.remove(temp_filename)
            time.sleep(3) 
            
        except Exception as e:
            print(f"❌ Erro crítico na ação {doc_id}: {e}")
            session.rollback()
            resultado.erros += 1
        finally:
            # 4. 🔴 FECHA SESSÃO
            session.close()
    logger.info(
        "Fila PENDENTE_ACAO encerrada: processados=%s salvo_drive=%s revisao=%s erros=%s notificados=%s",
        resultado.processados,
        resultado.salvo_drive,
        resultado.revisao,
        resultado.erros,
        resultado.notificados,
    )
    return resultado