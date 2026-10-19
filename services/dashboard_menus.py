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
    obter_file_id_logo,
    obter_link_logo,
    registrar_falha_logo,
    registrar_file_id_logo,
)
from modules.GoogleDriveManager import GoogleDriveManager
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
    """Filtra os ativos da planilha que estão na lista de config.FAVORITOS"""
    is_fii = (tipo == 'fii')
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
    # Acessa a lista configurada no seu arquivo config.py
    lista_favs = config.FAVORITOS.get(tipo, [])

    try:
        matriz = buscar_dados_planilha_com_cache(nome_aba)
        if not matriz: return []

        favoritos_encontrados = []
        for linha in matriz[1:]:
            ticker = linha[0].strip().upper()
            if ticker in lista_favs:
                favoritos_encontrados.append(ticker)
        
        return favoritos_encontrados
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
    """Vasculha a planilha usando o Cache Rápido para não travar o bot"""
    is_fii = (tipo == 'fii')
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"

    FILTROS_FIXOS = {
        "fii": {"pvp_min": 0.50, "pvp_max": 1.15, "dy_min": 0.08},
        "acao": {"pl_min": 2.0, "pl_max": 15.0, "pvp_min": 0.50, "pvp_max": 2.50, "dy_min": 0.06, "roe_min": 0.10}
    }
    filtro_atual = FILTROS_FIXOS[tipo]

    try:
        # Puxa os dados instantaneamente do Cache
        matriz = buscar_dados_planilha_com_cache(nome_aba)
        if not matriz: return []

        oportunidades = []
        for linha in matriz[1:]:
            try:
                ticker = linha[0].strip()
                if not ticker: continue

                if is_fii:
                    pvp = converter_numero(linha[5])
                    dy = converter_numero(linha[6])
                    dy_min = filtro_atual['dy_min']
                    if dy_min < 1 and dy >= 1: dy_min *= 100 

                    if (filtro_atual['pvp_min'] <= pvp <= filtro_atual['pvp_max']) and (dy >= dy_min):
                        oportunidades.append(ticker)
                else:
                    dy = converter_numero(linha[3])
                    pl = converter_numero(linha[5])
                    pvp = converter_numero(linha[6])
                    roe = converter_numero(linha[19])

                    dy_min, roe_min = filtro_atual['dy_min'], filtro_atual['roe_min']
                    if dy_min < 1 and dy >= 1: dy_min *= 100
                    if roe_min < 1 and roe >= 1: roe_min *= 100

                    if (filtro_atual['pl_min'] <= pl <= filtro_atual['pl_max']) and \
                       (filtro_atual['pvp_min'] <= pvp <= filtro_atual['pvp_max']) and \
                       (dy >= dy_min) and (roe >= roe_min):
                        oportunidades.append(ticker)
            except IndexError:
                pass 
        return oportunidades
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


def _enviar_painel_ativo(chat_id, ticker, texto, texto_com_link, markup, media_logo):
    """Envia o painel como foto (com legenda) ou texto, com fallback seguro."""
    if media_logo:
        try:
            mensagem = bot.send_photo(
                chat_id,
                media_logo,
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
            else:
                # O Telegram recusou um file_id; invalida só o cache do
                # Telegram para permitir resolver uma nova imagem.
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
    if media_logo:
        try:
            bot.edit_message_media(
                InputMediaPhoto(
                    media=media_logo, caption=texto, parse_mode="Markdown"
                ),
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
            )
            return
        except Exception as erro:
            # Se o Telegram rejeitou um file_id, ele pode ter expirado ou ser
            # invalido. Invalida o cache (inclusive o persistente) para que a
            # proxima chamada resolva uma nova midia. Falhas em mensagens de
            # texto sao apenas fallback e nao invalidam uma URL valida.
            if not str(media_logo).startswith(("http://", "https://")):
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
    ticker_limpo = sanitizar_markdown(ticker)

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
    link_invisivel = f"[\u200e]({url_logo})" if url_logo else ""
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
