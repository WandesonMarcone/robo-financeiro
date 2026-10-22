import logging

from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
import re
import config
from bot.loader import bot
from services.planilhas import buscar_dados_planilha_com_cache, buscar_ativo_na_planilha
from services.logo_service import (
    invalidar_file_id_logo,
    obter_bytes_logo_drive,
    obter_file_id_logo,
    obter_link_logo,
    registrar_falha_logo,
    registrar_file_id_logo,
)
from atualizador_documentos import SessionDB
from pipeline_dados.banco_dados import DocumentosQualitativos, Ativo

# O gerenciador do Drive e criado sob demanda: instancia-lo na importacao
# disparava a descoberta de rede do Google apenas por carregar o modulo. A
# criacao preguicosa reduz efeitos colaterais em importacoes e testes.
logger = logging.getLogger("robo.paineis")

_drive_manager = None


def obter_drive_manager():
    global _drive_manager
    if _drive_manager is None:
        from modules.GoogleDriveManager import GoogleDriveManager

        _drive_manager = GoogleDriveManager()
    return _drive_manager

def sanitizar_markdown(texto: str) -> str:
    """Escapa caracteres do Markdown para não quebrar a API do Telegram."""
    if not texto:
        return ""
    texto = str(texto)
    for char in ['_', '*', '`', '[']:
        texto = texto.replace(char, f"\\{char}")
    return texto

def buscar_favoritos(tipo):
    """Tickers da planilha que estao no ranking real de favoritos."""
    is_fii = (tipo == 'fii')
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
    from modules.relatorio_mercado import obter_carteira_popular

    lista_favs = obter_carteira_popular("fii" if is_fii else "acao")
    if not lista_favs:
        return []

    try:
        matriz = buscar_dados_planilha_com_cache(nome_aba)
        if not matriz: return []

        na_planilha = set()
        for linha in matriz[1:]:
            ticker = linha[0].strip().upper()
            if ticker:
                na_planilha.add(ticker)
        return [t for t in lista_favs if t in na_planilha]
    except Exception as e:
        print(f"Erro ao buscar favoritos: {e}")
        return []

def converter_numero(valor_string):
    """Limpa textos da planilha e transforma em número puro"""
    try:
        texto = str(valor_string).replace('R$', '').replace('%', '').strip()
        if not texto or texto == '-': return 0.0
        if ',' in texto and '.' in texto:
            texto = texto.replace('.', '')
        texto = texto.replace(',', '.')
        return float(texto)
    except:
        return 0.0

def buscar_oportunidades(tipo):
    """Filtra a planilha com liquidez e, nas acoes, ticker mapeado na B3."""
    is_fii = (tipo == 'fii')
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
    from modules.relatorio_mercado import eh_oportunidade_acao, eh_oportunidade_fii

    filtro_atual = (getattr(config, "FILTROS_FIXOS", {}) or {}).get(tipo) or {}
    limite = getattr(config, "OPORTUNIDADES_LIMITE", 8)

    try:
        matriz = buscar_dados_planilha_com_cache(nome_aba)
        if not matriz: return []

        ranqueadas = []
        for linha in matriz[1:]:
            try:
                ticker = linha[0].strip().upper()
                if not ticker: continue

                if is_fii:
                    pvp = converter_numero(linha[5])
                    dy = converter_numero(linha[6])
                    vacancia = converter_numero(linha[7]) if len(linha) > 7 else None
                    liquidez = converter_numero(linha[12]) if len(linha) > 12 else None
                    if eh_oportunidade_fii(pvp, dy, liquidez, vacancia, filtro_atual):
                        ranqueadas.append((liquidez or 0, ticker))
                else:
                    dy = converter_numero(linha[3])
                    pl = converter_numero(linha[5])
                    pvp = converter_numero(linha[6])
                    roe = converter_numero(linha[19]) if len(linha) > 19 else 0
                    liquidez = converter_numero(linha[27]) if len(linha) > 27 else None
                    if eh_oportunidade_acao(pl, pvp, dy, roe, liquidez, ticker, filtro_atual):
                        ranqueadas.append((liquidez or 0, ticker))
            except IndexError:
                pass
        ranqueadas.sort(reverse=True)
        return [ticker for _liq, ticker in ranqueadas[:limite]]
    except Exception as e:
        print(f"Erro no filtro de oportunidades: {e}")
        return []

def _registrar_file_id_do_painel(mensagem, ticker):
    """Guarda o ``file_id`` devolvido pelo Telegram para reutilizar depois."""
    fotos = getattr(mensagem, "photo", None)
    if not fotos:
        return
    try:
        registrar_file_id_logo(ticker, fotos[-1].file_id)
    except Exception:
        logger.debug("Falha ao registrar file_id da logo de %s", ticker, exc_info=True)


def _midia_telegram(media_logo):
    """Converte ``drive:<id>`` em bytes; URLs e file_id seguem como estão."""
    if not media_logo:
        return None
    if str(media_logo).startswith("drive:"):
        return obter_bytes_logo_drive(media_logo)
    return media_logo


def _enviar_painel_ativo(chat_id, ticker, texto, texto_com_link, markup, media_logo):
    """Envia o painel como foto (com legenda) ou texto, com fallback seguro."""
    foto = _midia_telegram(media_logo)
    if foto:
        try:
            mensagem = bot.send_photo(
                chat_id,
                foto,
                caption=texto,
                reply_markup=markup,
                parse_mode="Markdown",
            )
            _registrar_file_id_do_painel(mensagem, ticker)
            return
        except Exception as erro:
            logger.warning(
                "Painel de %s: envio da logo falhou; usando texto", ticker,
                exc_info=True,
            )
            if str(media_logo).startswith(("http://", "https://")):
                registrar_falha_logo(
                    ticker, erro=type(erro).__name__, url_origem=media_logo
                )
            elif not str(media_logo).startswith("drive:"):
                invalidar_file_id_logo(ticker, erro=type(erro).__name__)
    bot.send_message(
        chat_id,
        texto_com_link,
        reply_markup=markup,
        parse_mode="Markdown",
        disable_web_page_preview=False,
    )


def _editar_painel_ativo(chat_id, message_id, ticker, texto, texto_com_link, markup, media_logo):
    """Edita o painel preservando a logo quando a mensagem atual é uma foto."""
    foto = _midia_telegram(media_logo)
    if foto:
        try:
            bot.edit_message_media(
                InputMediaPhoto(
                    media=foto, caption=texto, parse_mode="Markdown"
                ),
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
            )
            return
        except Exception as erro:
            if (
                not str(media_logo).startswith(("http://", "https://", "drive:"))
            ):
                invalidar_file_id_logo(ticker, erro=type(erro).__name__)
            # Mensagens de texto (menu anterior) não aceitam edit_message_media.
            logger.debug(
                "Painel de %s: edição de mídia indisponível; usando texto",
                ticker,
                exc_info=True,
            )
    try:
        bot.edit_message_text(
            texto_com_link,
            chat_id,
            message_id,
            reply_markup=markup,
            parse_mode="Markdown",
            disable_web_page_preview=False,
        )
    except Exception:
        # Se a mensagem atual é uma foto, o Telegram recusa convertê-la em
        # texto. Envia um novo painel textual em vez de interromper o bot.
        logger.debug(
            "Painel de %s: não foi possível editar a mensagem; enviando nova",
            ticker,
            exc_info=True,
        )
        try:
            bot.send_message(
                chat_id,
                texto_com_link,
                reply_markup=markup,
                parse_mode="Markdown",
                disable_web_page_preview=False,
            )
        except Exception:
            logger.warning(
                "Painel de %s: fallback textual também falhou", ticker,
                exc_info=True,
            )


def gerar_painel_ativo(ticker, tipo, chat_id, message_id=None):
    """Gera o painel do ativo com logo, indicadores e botões existentes.

    A logo nunca é obrigatória: quando o catálogo não tem a imagem (ou o
    Telegram recusa o envio), o painel é entregue apenas com texto, sem
    interromper o fluxo. Os botões continuam usando emojis, pois teclados do
    Telegram não suportam imagens personalizadas.
    """

    is_fii = (tipo == 'fii')
    icone = "🏢 Fundo" if is_fii else "📈 Ação"
    voltar_cmd = "menu_fiis" if is_fii else "menu_acoes"

    # O file_id do Telegram evita novo download; a URL só é resolvida quando
    # ainda não há cache do envio anterior.
    file_id_logo = obter_file_id_logo(ticker)
    url_logo = "" if file_id_logo else obter_link_logo(ticker, tipo)
    media_logo = file_id_logo or url_logo

    indicadores = buscar_ativo_na_planilha(ticker, is_fii)

    if not indicadores:
        msg_erro = f"❌ Erro: Não encontrei dados para **{ticker}** na planilha."
        if message_id: bot.edit_message_text(msg_erro, chat_id, message_id, parse_mode="Markdown")
        else: bot.send_message(chat_id, msg_erro, parse_mode="Markdown")
        return

    resumo_ia = f"Ativo monitorado do setor {indicadores.get('setor', 'Geral')}."

    resumo_limpo = sanitizar_markdown(resumo_ia)
    setor_limpo = sanitizar_markdown(indicadores.get('setor', 'Geral'))
    
    # Se o ticker vier sujo com algum caractere (ex: MXRF11_fii), limpa ele também
    from modules.relatorio_mercado import rotulo_ticker as _rotulo_ativo
    ticker_limpo = sanitizar_markdown(_rotulo_ativo(ticker, tipo))

    texto = (
        f"{icone}: **{ticker_limpo}**\n"
        f"📝 **Resumo:** _{resumo_limpo}_ (Setor: {setor_limpo})\n\n"
        f"💰 **Preço:** R$ {indicadores.get('preco', 'N/A')}\n"
        f"💸 **Dividend Yield:** {indicadores.get('dy', 'N/A')}\n"
    )

    if is_fii:
        texto += f"⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n💵 **VPA:** {indicadores.get('vpa', 'N/A')}"
    else:
        texto += f"📊 **P/L:** {indicadores.get('pl', 'N/A')} | ⚖️ **P/VP:** {indicadores.get('pvp', 'N/A')}\n📈 **ROE:** {indicadores.get('roe', 'N/A')}"

    # No modo texto, mantém o link invisível já usado pelo projeto para forçar
    # a prévia da imagem sem alterar o conteúdo visível.
    link_invisivel = (
        f"[\u200e]({url_logo})"
        if str(url_logo).startswith(("http://", "https://"))
        else ""
    )
    texto_com_link = f"{link_invisivel}{texto}"

    markup = InlineKeyboardMarkup(row_width=2)

    # 1. VERIFICAÇÃO DE AUDITORIA (Agora funciona para FIIs e Ações!)
    pendentes = 0
    try:
        session = SessionDB()
        pendentes = session.query(DocumentosQualitativos).join(Ativo).filter(
            Ativo.ticker == ticker,
            DocumentosQualitativos.status_processamento == "AGUARDANDO_REVISAO"
        ).count()
        session.close()
    except Exception as e:
        logger.debug("Revisão temporariamente indisponível: %s", e)

    # 2. SE TIVER PENDÊNCIA, COLOCA O BOTÃO DE ALERTA NO TOPO
    if pendentes > 0:
        markup.add(InlineKeyboardButton(f"⚠️ Requer Auditoria ({pendentes} docs)", callback_data=f"rev_t_{ticker}"))

    # 3. ADICIONA OS BOTÕES PADRÕES LADO A LADO
    markup.row(
        InlineKeyboardButton("📎 Dados", callback_data=f"dados_{ticker}_{tipo}"),
        InlineKeyboardButton("📁 Docs", callback_data=f"docs_{ticker}_{tipo}")
    )

    # 4. BOTÕES INFERIORES
    markup.add(InlineKeyboardButton("⚠️ Análise IA", callback_data=f"ia_{ticker}_{tipo}"))
    markup.add(InlineKeyboardButton(f"🔙 Voltar", callback_data=voltar_cmd))

    if message_id:
        _editar_painel_ativo(
            chat_id, message_id, ticker, texto, texto_com_link, markup, media_logo
        )
    else:
        _enviar_painel_ativo(
            chat_id, ticker, texto, texto_com_link, markup, media_logo
        )

def extrair_data_real(doc):
    """Garante que datas reais sejam exibidas, priorizando o Mês/Ano no Assunto do documento."""
    if doc.assunto:
        assunto_str = str(doc.assunto)
        
        # 1. Tenta achar formato completo com dia (DD/MM/YYYY ou YYYY-MM-DD)
        match_full = re.search(r'(\d{2}[-/\.]\d{2}[-/\.]\d{4})|(\d{4}[-/\.]\d{2}[-/\.]\d{2})', assunto_str)
        if match_full:
            data_crua = match_full.group(0).replace(".", "-").replace("/", "-")
            p = data_crua.split("-")
            if len(p[0]) == 4: return f"{p[2]}/{p[1]}/{p[0]}"
            return f"{p[0]}/{p[1]}/{p[2]}"
        
        # 2. Tenta achar formato apenas Mês/Ano (MM/YYYY ou YYYY-MM) - Muito comum em FIIs
        match_mes = re.search(r'(\d{2}[-/\.]\d{4})|(\d{4}[-/\.]\d{2})', assunto_str)
        if match_mes:
            data_crua = match_mes.group(0).replace(".", "-").replace("/", "-")
            p = data_crua.split("-")
            if len(p[0]) == 4: return f"{p[1]}/{p[0]}" # YYYY-MM vira MM/YYYY
            return f"{p[0]}/{p[1]}" # MM-YYYY vira MM/YYYY

    # 3. Fallback: Se não achar nenhuma data no texto, usa a data oficial de publicação
    if hasattr(doc, 'data_publicacao') and doc.data_publicacao:
        return doc.data_publicacao.strftime("%d/%m/%Y")
    
    return "Data N/A"

def filtrar_ativos_por_setor(tipo, setor_clicado):
    """
    Filtra os ativos pela correspondência EXATA.
    Se clicar em "Híbrido - Logístico", trará APENAS "Híbrido - Logístico".
    """
    is_fii = (tipo == 'fii')
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
    resultados = []

    try:
        matriz = buscar_dados_planilha_com_cache(nome_aba)
        if not matriz: return []

        setor_alvo = setor_clicado.strip().lower()

        for linha in matriz[1:]: 
            try:
                ticker = linha[0].strip().upper()
                indice_setor = 2 if is_fii else 1
                setor_planilha = linha[indice_setor].strip().lower() 

                # REGRA BLINDADA: Só aceita se for 100% igual! Acabou a mistura!
                if setor_planilha == setor_alvo:
                    resultados.append(ticker)
            except IndexError:
                continue 

        return resultados
    except Exception as e:
        print(f"Erro no filtro de setor: {e}")
        return []
