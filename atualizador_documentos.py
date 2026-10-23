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
    obter_bytes_logo_url,
    obter_media_logo_rapida,
    registrar_falha_logo,
    registrar_file_id_logo,
)
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
from pipeline_dados.conexao import obter_session_factory
from config import MAPA_ISCAS_MASTER, TIPOS_DOC_FII
from pipeline_dados.tipos_documento import manter_tipo_catalogo

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

    lista_opcoes = ", ".join(dict.fromkeys(TIPOS_DOC_FII.values()))
    
    # Prompt de engenharia reversa exigindo JSON
    prompt = (
        f"Você é um analista financeiro sênior avaliando um PDF de Fundo Imobiliário. "
        f"O documento começa assim: '{texto_limpo}'\n\n"
        f"Classifique o documento escolhendo ESTRITAMENTE UMA destas opções: {lista_opcoes}.\n"
        f"Equivalencias obrigatorias: carta/aviso/comunicado ao cotista = Aviso aos Cotistas; "
        f"inicio ou encerramento de emissao/distribuicao de cotas = Nova Emissao de Cotas.\n"
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


def _dupla_checagem_fii(nome_original, texto_extraido):
    """Duas classificacoes independentes, com o detalhe de cada leitura."""
    tipo1, conf1 = classificar_documento_com_ia(nome_original, texto_extraido)
    tipo2, conf2 = classificar_documento_com_ia(nome_original, texto_extraido)
    conf1 = int(conf1 or 0)
    conf2 = int(conf2 or 0)
    confianca = min(conf1, conf2)
    validos = set(TIPOS_DOC_FII.values())
    acordo = tipo1 == tipo2 and tipo1 in validos and confianca > 0
    return {
        "tipo": tipo1 if acordo else nome_original,
        "confianca": confianca,
        "acordo": acordo,
        "checagem_1": (tipo1, conf1),
        "checagem_2": (tipo2, conf2),
    }


def classificar_documento_fii_dupla(nome_original, texto_extraido):
    """Duas classificacoes independentes. Auto-save so se ambas concordarem.

    Retorna ``(tipo, confianca, acordo)``. Sem texto, sem chave ou tipos
    diferentes: ``acordo=False`` e o documento vai para revisao.
    """
    detalhes = _dupla_checagem_fii(nome_original, texto_extraido)
    return detalhes["tipo"], detalhes["confianca"], detalhes["acordo"]


def _resumo_dupla_checagem(detalhes):
    """JSON persistido em ``resumo_ia`` so para a Central de Revisoes."""
    c1_tipo, c1_conf = detalhes["checagem_1"]
    c2_tipo, c2_conf = detalhes["checagem_2"]
    return json.dumps(
        {
            "checagem_1": {"tipo": c1_tipo, "confianca": c1_conf},
            "checagem_2": {"tipo": c2_tipo, "confianca": c2_conf},
            "acordo": bool(detalhes["acordo"]),
        },
        ensure_ascii=False,
    )

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
    elif "img.logo.dev" in str(foto):
        conteudo = obter_bytes_logo_url(foto)
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


def enviar_alerta_revisao_telegram(
    ticker, nome_doc, link_pdf, file_id, db_id, checagens=None
):
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

    leituras = f"📄 **Leitura Inicial:** `{nome_doc}`"
    if checagens and len(checagens) == 2:
        leituras = (
            "🤖 **Duas checagens da IA**\n"
            f"1️⃣ `{checagens[0][0]}` ({checagens[0][1]}%)\n"
            f"2️⃣ `{checagens[1][0]}` ({checagens[1][1]}%)"
        )

    mensagem = (
        f"🚨 **Documento Suspeito Identificado!**\n\n"
        f"A B3 diz que é de `{ticker}`, mas as duas checagens da IA "
        f"discordaram ou ficaram incertas.\n"
        f"{leituras}\n\n"
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
            detalhes = _dupla_checagem_fii(doc_db.tipo_documento, texto_pdf)
            nome_ia = detalhes["tipo"]
            confianca = detalhes["confianca"]
            acordo = detalhes["acordo"]

            oficial = manter_tipo_catalogo(nome_ia, doc_db.tipo_documento, "FII")
            nome_limpo = oficial or "Outros"

            partes_data = data_ref.split('-')
            mes_pasta = f"{partes_data[2]}-{partes_data[1]}" if len(partes_data) == 3 else datetime.now().strftime("%Y-%m")

            if acordo and confianca >= 80 and texto_pdf:
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
                    doc_db.resumo_ia = _resumo_dupla_checagem(detalhes)
                    resultado.revisao += 1
                    enviar_alerta_revisao_telegram(
                        ticker,
                        nome_limpo,
                        link_gerado,
                        file_id,
                        doc_db.id,
                        checagens=(detalhes["checagem_1"], detalhes["checagem_2"]),
                    )
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


LIMITE_RECLASSIFICACAO = 3
MAX_LOTES_RECLASSIFICACAO = 40
TAMANHO_MAX_PDF_CLASSIFICACAO = 1_500_000
TEXTO_MAX_CLASSIFICACAO = 1500
PAGINAS_MAX_CLASSIFICACAO = 3


def _eh_pdf(conteudo):
    return bool(conteudo) and conteudo.lstrip().startswith(b"%PDF")


def _juntar_paginas(partes):
    return "\n".join(partes).strip()[:TEXTO_MAX_CLASSIFICACAO]


def _extrair_texto_pypdf2(pdf_bytes, max_paginas, pagina_inicial):
    import io
    import PyPDF2

    reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
    if not reader.pages:
        return ""
    inicio = max(0, int(pagina_inicial or 0))
    teto = min(len(reader.pages), inicio + max(1, int(max_paginas or 1)))
    partes = []
    tamanho = 0
    for i in range(inicio, teto):
        trecho = (reader.pages[i].extract_text() or "").strip()
        if not trecho:
            continue
        partes.append(trecho)
        tamanho += len(trecho)
        if tamanho >= TEXTO_MAX_CLASSIFICACAO:
            break
    return _juntar_paginas(partes)


def _extrair_texto_fitz(pdf_bytes, max_paginas, pagina_inicial):
    import fitz

    documento = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        inicio = max(0, int(pagina_inicial or 0))
        teto = min(len(documento), inicio + max(1, int(max_paginas or 1)))
        partes = []
        tamanho = 0
        for i in range(inicio, teto):
            trecho = (documento.load_page(i).get_text("text") or "").strip()
            if not trecho:
                continue
            partes.append(trecho)
            tamanho += len(trecho)
            if tamanho >= TEXTO_MAX_CLASSIFICACAO:
                break
        return _juntar_paginas(partes)
    finally:
        documento.close()


def _extrair_texto_paginas(
    pdf_bytes, max_paginas=PAGINAS_MAX_CLASSIFICACAO, pagina_inicial=0
):
    if not pdf_bytes:
        return ""
    try:
        texto = _extrair_texto_pypdf2(pdf_bytes, max_paginas, pagina_inicial)
        if texto:
            return texto
    except Exception:
        pass
    try:
        return _extrair_texto_fitz(pdf_bytes, max_paginas, pagina_inicial)
    except Exception:
        return ""


def _baixar_pdf_fnet(doc, downloader=None):
    id_doc = str(getattr(doc, "id_b3", None) or "").strip()
    if not id_doc:
        return None
    try:
        b3 = downloader or FnetDownloader()
        return b3.baixar_pdf(id_doc, max_bytes=TAMANHO_MAX_PDF_CLASSIFICACAO)
    except Exception:
        return None


def _baixar_pdf_drive(doc, drive_manager=None):
    file_id = _file_id_drive(getattr(doc, "url_pdf", None))
    if not file_id:
        return None
    try:
        drive = drive_manager
        if drive is None:
            from modules.GoogleDriveManager import GoogleDriveManager

            drive = GoogleDriveManager()
        return drive.baixar_arquivo(file_id, max_bytes=TAMANHO_MAX_PDF_CLASSIFICACAO)
    except Exception:
        return None


def _obter_pdf_classificacao(doc, downloader=None, drive_manager=None):
    tem_fnet = bool(str(getattr(doc, "id_b3", None) or "").strip())
    tem_drive = bool(_file_id_drive(getattr(doc, "url_pdf", None)))
    if not tem_fnet and not tem_drive:
        return None, "sem_fonte"
    lixo = None
    if tem_drive:
        pdf = _baixar_pdf_drive(doc, drive_manager=drive_manager)
        if _eh_pdf(pdf):
            return pdf, None
        lixo = pdf
    if tem_fnet:
        pdf = _baixar_pdf_fnet(doc, downloader=downloader)
        if _eh_pdf(pdf):
            return pdf, None
        lixo = lixo or pdf
    if lixo:
        return None, "corrompido"
    return None, "falha_download"


def _texto_para_classificacao(
    doc, downloader=None, pagina_inicial=0, drive_manager=None
):
    texto = (getattr(doc, "texto_extraido", None) or "").strip()
    if texto and int(pagina_inicial or 0) <= 0:
        return texto[:TEXTO_MAX_CLASSIFICACAO]
    pdf_bytes, _motivo = _obter_pdf_classificacao(
        doc, downloader=downloader, drive_manager=drive_manager
    )
    paginas = 2 if int(pagina_inicial or 0) > 0 else PAGINAS_MAX_CLASSIFICACAO
    return _extrair_texto_paginas(
        pdf_bytes, max_paginas=paginas, pagina_inicial=pagina_inicial
    )


def _ja_tem_dupla_checagem(doc):
    bruto = getattr(doc, "resumo_ia", None)
    if not bruto:
        return False
    try:
        dados = json.loads(bruto)
    except (TypeError, ValueError):
        return False
    c1 = dados.get("checagem_1") or {}
    c2 = dados.get("checagem_2") or {}
    return bool(c1.get("tipo") and c2.get("tipo"))


def _precisa_reclassificar(doc):
    from pipeline_dados.tipos_documento import (
        e_tipo_generico,
        normalizar_tipo_documento,
    )

    oficial = normalizar_tipo_documento(doc.tipo_documento, "FII")
    if oficial and oficial != doc.tipo_documento:
        return True
    if _ja_tem_dupla_checagem(doc):
        return False
    return (
        doc.status_processamento == "AGUARDANDO_REVISAO"
        or e_tipo_generico(doc.tipo_documento)
        or oficial is None
    )


def _ticker_doc(doc):
    ativo = getattr(doc, "ativo", None)
    ticker = getattr(ativo, "ticker", None) if ativo is not None else None
    return str(ticker or "").strip().upper() or "?"


def _tipo_ativo_doc(doc):
    ativo = getattr(doc, "ativo", None)
    tipo = getattr(ativo, "tipo", None) if ativo is not None else None
    valor = getattr(tipo, "value", tipo)
    return "ACAO" if str(valor or "").strip().upper() == "ACAO" else "FII"


def _file_id_drive(url):
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", str(url or ""))
    return match.group(1) if match else None


def _mes_ref_do_doc(doc):
    bruto = str(getattr(doc, "assunto", None) or "").strip().split(" ")[0]
    bruto = bruto.replace("/", "-")
    partes = bruto.split("-")
    if len(partes) == 3:
        if len(partes[0]) == 4:
            return f"{partes[0]}-{partes[1].zfill(2)}"
        if len(partes[2]) == 4:
            return f"{partes[2]}-{partes[1].zfill(2)}"
    data = getattr(doc, "data_publicacao", None)
    if data is not None:
        try:
            return data.strftime("%Y-%m")
        except Exception:
            pass
    return datetime.now().strftime("%Y-%m")


def _nome_arquivo_drive(tipo, doc):
    nome = str(tipo or "Outros").replace(" ", "_").replace("/", "-")
    assunto = str(getattr(doc, "assunto", None) or "").strip().split(" ")[0]
    assunto = assunto.replace("/", "-") or "Doc"
    sufixo = f"_{doc.id_b3}" if getattr(doc, "id_b3", None) else ""
    return f"{nome}_{assunto}{sufixo}.pdf"


def _organizar_identificado_no_drive(doc, tipo, drive_manager=None):
    file_id = _file_id_drive(getattr(doc, "url_pdf", None))
    if not file_id:
        return None
    ticker = _ticker_doc(doc)
    if ticker == "?":
        return None
    try:
        drive = drive_manager
        if drive is None:
            from modules.GoogleDriveManager import GoogleDriveManager

            drive = GoogleDriveManager()
        return drive.mover_arquivo_da_revisao_por_id(
            file_id=file_id,
            ticker=ticker,
            mes_ref=_mes_ref_do_doc(doc),
            novo_nome=_nome_arquivo_drive(tipo, doc),
            tipo_ativo=_tipo_ativo_doc(doc),
        )
    except Exception:
        logger.warning(
            "Falha ao organizar doc %s no Drive", getattr(doc, "id", None), exc_info=True
        )
        return None


def _confirmar_identificacao(doc, tipo, resumo, ticker, drive_manager=None):
    doc.tipo_documento = tipo
    doc.resumo_ia = None
    if doc.status_processamento == "AGUARDANDO_REVISAO":
        doc.status_processamento = "SALVO_DRIVE"
    link = _organizar_identificado_no_drive(doc, tipo, drive_manager=drive_manager)
    if link:
        doc.url_pdf = link
        doc.status_processamento = "SALVO_DRIVE"
        resumo["drive"] = int(resumo.get("drive", 0) or 0) + 1
    resumo["classificados"] += 1
    _registrar_fundo(resumo, ticker, "identificados", tipo=tipo)
    return doc


def _marcar_descartado(doc, resumo, ticker, motivo):
    doc.status_processamento = "ERRO_DOWNLOAD"
    doc.resumo_ia = None
    resumo["descartados"] = int(resumo.get("descartados", 0) or 0) + 1
    _registrar_fundo(resumo, ticker, "descartados")
    logger.info(
        "Doc %s retirado da revisao (%s)", getattr(doc, "id", None), motivo
    )
    return doc


def _fundo_vazio():
    return {
        "examinados": 0,
        "identificados": 0,
        "revisao": 0,
        "sem_texto": 0,
        "erros": 0,
        "descartados": 0,
        "tipos": {},
    }


def _registrar_fundo(resumo, ticker, campo, tipo=None):
    fundo = resumo.setdefault("por_fundo", {}).setdefault(ticker, _fundo_vazio())
    fundo["examinados"] += 1
    if campo and campo != "examinados":
        fundo[campo] = int(fundo.get(campo, 0) or 0) + 1
    if tipo:
        tipos = fundo.setdefault("tipos", {})
        tipos[tipo] = int(tipos.get(tipo, 0) or 0) + 1
    return fundo


def _resumo_lote_vazio():
    return {
        "fila": 0,
        "classificados": 0,
        "revisao": 0,
        "sem_texto": 0,
        "erros": 0,
        "drive": 0,
        "descartados": 0,
        "ia_indisponivel": False,
        "ids": [],
        "lotes": 0,
        "por_fundo": {},
    }


def reclassificar_documentos_genericos(
    limite=LIMITE_RECLASSIFICACAO,
    downloader=None,
    excluir_ids=None,
    somente_sem_texto=False,
    pagina_inicial=0,
    drive_manager=None,
):
    """Duas checagens da IA nos docs genericos/incertos, sem inventar nomes.

    Aliases conhecidos (Ago, Age, Aviso Ao Mercado) sao mapeados ao catalogo
    sem IA. O restante so atualiza ``tipo_documento`` se as duas leituras
    concordarem, o tipo estiver no catalogo e a confianca for >= 80.
    Ao identificar, renomeia e move no Drive pela data de ``assunto``.
    """
    from pipeline_dados.tipos_documento import normalizar_tipo_documento

    limite = max(1, min(int(limite or LIMITE_RECLASSIFICACAO), 5))
    ignorados = {int(i) for i in (excluir_ids or []) if i is not None}
    resumo = _resumo_lote_vazio()
    session = SessionDB()
    try:
        candidatos = (
            session.query(DocumentosQualitativos)
            .filter(
                DocumentosQualitativos.status_processamento.in_(
                    ("AGUARDANDO_REVISAO", "PENDENTE", "SALVO_DRIVE", "SALVO")
                )
            )
            .order_by(DocumentosQualitativos.data_publicacao.desc())
            .limit(120)
            .all()
        )
        escolhidos = []
        for doc in candidatos:
            if doc.id in ignorados:
                continue
            if somente_sem_texto and (doc.texto_extraido or "").strip():
                continue
            if _precisa_reclassificar(doc):
                escolhidos.append(doc)
            if len(escolhidos) >= limite:
                break
        resumo["fila"] = len(escolhidos)
        if not escolhidos:
            return resumo

        for doc in escolhidos:
            resumo["ids"].append(doc.id)
            ticker = _ticker_doc(doc)
            alias = normalizar_tipo_documento(doc.tipo_documento, "FII")
            if alias and alias != doc.tipo_documento:
                _confirmar_identificacao(
                    doc, alias, resumo, ticker, drive_manager=drive_manager
                )
                continue
            texto = ""
            if int(pagina_inicial or 0) <= 0:
                texto = (doc.texto_extraido or "").strip()[:TEXTO_MAX_CLASSIFICACAO]
            if not texto:
                pdf_bytes, motivo = _obter_pdf_classificacao(
                    doc, downloader=downloader, drive_manager=drive_manager
                )
                if motivo:
                    _marcar_descartado(doc, resumo, ticker, motivo)
                    continue
                paginas = (
                    2 if int(pagina_inicial or 0) > 0 else PAGINAS_MAX_CLASSIFICACAO
                )
                texto = _extrair_texto_paginas(
                    pdf_bytes, max_paginas=paginas, pagina_inicial=pagina_inicial
                )
            if texto and not (doc.texto_extraido or "").strip():
                doc.texto_extraido = texto[:TEXTO_MAX_CLASSIFICACAO]
            if not texto:
                resumo["sem_texto"] += 1
                doc.status_processamento = "AGUARDANDO_REVISAO"
                _registrar_fundo(resumo, ticker, "sem_texto")
                continue
            try:
                detalhes = _dupla_checagem_fii(doc.tipo_documento, texto)
            except IAIndisponivelError:
                resumo["ia_indisponivel"] = True
                resumo["erros"] += 1
                _registrar_fundo(resumo, ticker, "erros")
                break
            except Exception:
                logger.warning("Falha na dupla checagem do doc %s", doc.id, exc_info=True)
                resumo["erros"] += 1
                _registrar_fundo(resumo, ticker, "erros")
                continue
            oficial = manter_tipo_catalogo(detalhes["tipo"], doc.tipo_documento, "FII")
            if detalhes["acordo"] and detalhes["confianca"] >= 80 and oficial:
                _confirmar_identificacao(
                    doc, oficial, resumo, ticker, drive_manager=drive_manager
                )
            else:
                doc.status_processamento = "AGUARDANDO_REVISAO"
                doc.resumo_ia = _resumo_dupla_checagem(detalhes)
                resumo["revisao"] += 1
                _registrar_fundo(resumo, ticker, "revisao")
        session.commit()
        resumo["lotes"] = 1
        return resumo
    except Exception:
        session.rollback()
        logger.warning("Falha ao reclassificar documentos genericos", exc_info=True)
        resumo["erros"] += 1
        return resumo
    finally:
        session.close()


def _somar_resumo(total, lote):
    for chave in (
        "fila",
        "classificados",
        "revisao",
        "sem_texto",
        "erros",
        "drive",
        "descartados",
    ):
        total[chave] = int(total.get(chave, 0) or 0) + int(lote.get(chave, 0) or 0)
    total["ia_indisponivel"] = bool(total.get("ia_indisponivel") or lote.get("ia_indisponivel"))
    total.setdefault("ids", [])
    total["ids"].extend(lote.get("ids") or [])
    total["lotes"] = int(total.get("lotes", 0) or 0) + 1
    destinos = total.setdefault("por_fundo", {})
    for ticker, dados in (lote.get("por_fundo") or {}).items():
        dest = destinos.setdefault(ticker, _fundo_vazio())
        for chave in (
            "examinados",
            "identificados",
            "revisao",
            "sem_texto",
            "erros",
            "descartados",
        ):
            dest[chave] = int(dest.get(chave, 0) or 0) + int(
                (dados or {}).get(chave, 0) or 0
            )
        tipos_dest = dest.setdefault("tipos", {})
        for nome, qtd in ((dados or {}).get("tipos") or {}).items():
            tipos_dest[nome] = int(tipos_dest.get(nome, 0) or 0) + int(qtd or 0)
    return total


def reclassificar_documentos_genericos_em_lotes(
    limite=LIMITE_RECLASSIFICACAO,
    max_lotes=MAX_LOTES_RECLASSIFICACAO,
    downloader=None,
    on_lote=None,
    somente_sem_texto=False,
    pagina_inicial=0,
    drive_manager=None,
):
    """Um clique: esvazia a fila em fatias de ``limite`` docs, sem repetir ids."""
    total = _resumo_lote_vazio()
    vistos = set()
    teto = max(1, min(int(max_lotes or MAX_LOTES_RECLASSIFICACAO), 80))
    for _ in range(teto):
        lote = reclassificar_documentos_genericos(
            limite=limite,
            downloader=downloader,
            excluir_ids=vistos,
            somente_sem_texto=somente_sem_texto,
            pagina_inicial=pagina_inicial,
            drive_manager=drive_manager,
        )
        ids = [i for i in (lote.get("ids") or []) if i is not None]
        if lote.get("fila", 0) == 0 and not ids:
            break
        vistos.update(ids)
        _somar_resumo(total, lote)
        if on_lote:
            on_lote(dict(total), dict(lote))
        if lote.get("ia_indisponivel"):
            break
        if lote.get("fila", 0) < max(1, int(limite or LIMITE_RECLASSIFICACAO)):
            break
        if not ids:
            break
    return total