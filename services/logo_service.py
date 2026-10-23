"""Resolução e cache das logos dos ativos.

Ordem: Google Drive (Ícones B3) → Logo.dev → fallback textual. Identidade
visual por empresa (PETR3/PETR4). ``file_id`` do Telegram é persistido.
Falha de logo nunca interrompe o bot. ``LOGO_DEV_TOKEN`` não é logado.
"""

import logging
import os
import re
import threading
import time

import requests

from pipeline_dados.identidade_visual import chave_canonica
from pipeline_dados.repositorio_logos import RepositorioLogos

logger = logging.getLogger("robo.logos")

# Identidade visual compartilhada por classes de ações da mesma empresa. A
# chave é o ticker consultado e o valor é o ticker canônico usado na logo.
# Os dados financeiros NÃO são afetados: apenas a busca da imagem é redirecionada.
IDENTIDADE_VISUAL = {
    "PETR3": "PETR4",
    "PETR4": "PETR4",
}

_HEADERS = {
    "User-Agent": "RoboFinanceiro/1.0 (logo-service)",
    "Accept": "image/png,image/*;q=0.8,*/*;q=0.5",
}

_TIMEOUT_CURTO = 2.5
_TTL_POSITIVO = 24 * 60 * 60
_TTL_NEGATIVO = 60 * 60

_CACHE_LOGOS = {}
_CACHE_EXPIRA = {}
_CACHE_FILE_IDS = {}
_LOCK = threading.RLock()
_REPOSITORIO_LOGOS = None


def _normalizar_ticker(ticker):
    """Normaliza o ticker para comparação com o catálogo (A-Z e 0-9)."""
    if ticker is None:
        return ""
    texto = str(ticker).strip().upper()
    # Callbacks antigos podem trazer sufixos como ``MXRF11_fii``.
    texto = texto.split("_", 1)[0]
    return re.sub(r"[^A-Z0-9]", "", texto)


def _chave_logo(ticker):
    """Chave canonica de identidade visual (empresa quando conhecida).

    Primeiro aplica o grupo visual local (compatibilidade e funcionamento sem
    banco). Se o ticker nao pertence a um grupo fixo, consulta o catalogo para
    usar o ticker canonico da empresa, de modo que tickers irmaos (PETR3/PETR4
    ou quaisquer outros vinculados a mesma empresa) compartilhem a logo.
    """
    normalizado = _normalizar_ticker(ticker)
    if not normalizado:
        return ""
    visual = chave_canonica(normalizado)
    if visual != normalizado:
        return visual
    try:
        canonico = obter_repositorio_logos().chave_canonica(normalizado)
    except Exception:
        logger.debug(
            "Identidade canonica indisponivel para %s", normalizado,
            exc_info=True,
        )
        canonico = None
    return canonico or visual


def _cache_valido(chave):
    expira_em = _CACHE_EXPIRA.get(chave)
    if expira_em is None:
        return False
    if expira_em <= time.monotonic():
        _CACHE_EXPIRA.pop(chave, None)
        _CACHE_LOGOS.pop(chave, None)
        return False
    return True


def _guardar_cache(chave, valor):
    with _LOCK:
        _CACHE_LOGOS[chave] = valor
        _CACHE_EXPIRA[chave] = time.monotonic() + (
            _TTL_POSITIVO if valor else _TTL_NEGATIVO
        )


def limpar_cache_logos():
    """Limpa o cache EM MEMÓRIA de URLs e de ``file_id``.

    Não remove o cache persistente do Telegram (use
    ``RepositorioLogos.limpar`` para uma operação administrativa explícita).
    """
    with _LOCK:
        _CACHE_LOGOS.clear()
        _CACHE_EXPIRA.clear()
        _CACHE_FILE_IDS.clear()


def obter_repositorio_logos():
    """Repositório persistente do cache do Telegram (criado sob demanda)."""
    global _REPOSITORIO_LOGOS
    if _REPOSITORIO_LOGOS is None:
        _REPOSITORIO_LOGOS = RepositorioLogos()
    return _REPOSITORIO_LOGOS


def definir_repositorio_logos(repositorio):
    """Permite injetar um repositório alternativo (testes/administração)."""
    global _REPOSITORIO_LOGOS
    _REPOSITORIO_LOGOS = repositorio
    return _REPOSITORIO_LOGOS


# ---------------------------------------------------------------------------
# Cache do Telegram (file_id)
# ---------------------------------------------------------------------------


def obter_file_id_logo(ticker):
    """Retorna o ``file_id`` conhecido em memória ou no banco (ou ``None``)."""
    chave = _chave_logo(ticker)
    with _LOCK:
        em_memoria = _CACHE_FILE_IDS.get(chave)
    if em_memoria:
        return em_memoria

    try:
        file_id = obter_repositorio_logos().obter_file_id(ticker)
    except Exception:
        logger.debug(
            "Cache persistente de logo indisponível para %s", chave, exc_info=True
        )
        return None
    if file_id:
        with _LOCK:
            _CACHE_FILE_IDS[chave] = str(file_id)
    return file_id


def registrar_file_id_logo(ticker, file_id, url_origem=None):
    """Memoriza o ``file_id`` em memória e no banco para reutilização."""
    chave = _chave_logo(ticker)
    if not chave or not file_id:
        return None
    with _LOCK:
        _CACHE_FILE_IDS[chave] = str(file_id)
    try:
        obter_repositorio_logos().registrar_file_id(
            ticker, file_id, url_origem=url_origem
        )
    except Exception:
        # O envio já foi bem-sucedido; falhar a persistência não pode quebrar
        # o fluxo do bot. A próxima execução simplesmente tenta de novo.
        logger.warning(
            "Não foi possível persistir o file_id da logo de %s",
            chave,
            exc_info=True,
        )
    return str(file_id)


def invalidar_file_id_logo(ticker, erro=None):
    """Invalida apenas o ``file_id`` rejeitado pelo Telegram.

    Não grava cache negativo da URL: a próxima chamada deve poder resolver uma
    nova imagem ou reutilizar a URL já validada. Isso é diferente de
    ``registrar_falha_logo``, usado quando a própria imagem falhou.
    """
    chave = _chave_logo(ticker)
    if not chave:
        return None
    with _LOCK:
        _CACHE_FILE_IDS.pop(chave, None)
    try:
        # ttl=0 libera uma nova tentativa imediatamente; o file_id antigo é
        # limpo pelo repositório.
        return obter_repositorio_logos().registrar_falha(
            ticker, erro=erro, url_origem=None, ttl_segundos=0
        )
    except Exception:
        logger.warning(
            "Não foi possível invalidar o file_id da logo de %s",
            chave,
            exc_info=True,
        )
        return None


def registrar_falha_logo(ticker, erro=None, url_origem=None, ttl_segundos=None):
    """Invalida o ``file_id`` e grava cache negativo persistente com expiração."""
    chave = _chave_logo(ticker)
    if not chave:
        return None
    with _LOCK:
        _CACHE_FILE_IDS.pop(chave, None)
        # Também evita reutilizar a URL local imediatamente; o TTL negativo do
        # cache de imagens é separado do cache do Telegram.
        _CACHE_LOGOS[chave] = ""
        _CACHE_EXPIRA[chave] = time.monotonic() + _TTL_NEGATIVO
    try:
        return obter_repositorio_logos().registrar_falha(
            ticker,
            erro=erro,
            url_origem=url_origem,
            ttl_segundos=ttl_segundos,
        )
    except Exception:
        logger.warning(
            "Não foi possível registrar falha de logo de %s", chave, exc_info=True
        )
        return None


# ---------------------------------------------------------------------------
# Drive (Ícones B3) → Logo.dev
# ---------------------------------------------------------------------------

_PNG_ASSINATURA = b"\x89PNG\r\n\x1a\n"
_JPEG_ASSINATURA = b"\xff\xd8\xff"
_WEBP_RIFF = b"RIFF"
_WEBP_WEBP = b"WEBP"
_GIF_ASSINATURA = b"GIF8"


def _token_cdn():
    """Publishable key (pk_) da CDN. ``sk_`` nao autentica em img.logo.dev."""
    token = (os.environ.get("LOGO_DEV_TOKEN") or "").strip()
    if not token or token.startswith("sk_"):
        return None
    return token


def _segredo_logo_dev():
    """Secret key (sk_) da Brand API, so no servidor."""
    for nome in ("LOGO_DEV_SECRET_KEY", "LOGO_DEV_TOKEN"):
        valor = (os.environ.get(nome) or "").strip()
        if valor.startswith("sk_"):
            return valor
    return (os.environ.get("LOGO_DEV_SECRET_KEY") or "").strip() or None


def _url_logo_dev(ticker):
    """CDN Logo.dev: ``/ticker/{TICKER}.SA`` (B3). Nao usar ``ticker:``."""
    token = _token_cdn()
    if not token:
        return None
    chave = _chave_logo(ticker)
    if not chave:
        return None
    return (
        f"https://img.logo.dev/ticker/{chave}.SA"
        f"?token={token}&size=200&format=png&fallback=404"
    )


def _url_para_log(url):
    """Remove querystring (token) antes de qualquer log."""
    if not url:
        return ""
    return str(url).split("?", 1)[0]


def _mime_imagem(conteudo, content_type=""):
    if not conteudo or len(conteudo) < 12:
        return None
    if conteudo.startswith(_PNG_ASSINATURA):
        return "image/png"
    if conteudo.startswith(_JPEG_ASSINATURA):
        return "image/jpeg"
    if conteudo.startswith(_WEBP_RIFF) and conteudo[8:12] == _WEBP_WEBP:
        return "image/webp"
    if conteudo.startswith(_GIF_ASSINATURA):
        return "image/gif"
    tipo = (content_type or "").split(";", 1)[0].strip().lower()
    if tipo.startswith("image/") and tipo != "image/svg+xml":
        return tipo
    return None


def _baixar_imagem_logo_dev(url):
    try:
        resposta = requests.get(
            url, headers=_HEADERS, timeout=5, allow_redirects=True
        )
        if resposta.status_code != 200:
            logger.debug(
                "Logo.dev HTTP %s para %s",
                resposta.status_code,
                _url_para_log(url),
            )
            return None, None
        mime = _mime_imagem(resposta.content, resposta.headers.get("Content-Type"))
        if not mime:
            logger.debug("Logo.dev devolveu conteudo nao-imagem")
            return None, None
        return resposta.content, mime
    except requests.RequestException:
        logger.debug("Logo.dev indisponivel (rede): %s", _url_para_log(url))
    except Exception:
        logger.debug("Falha inesperada no Logo.dev", exc_info=True)
    return None, None


def _baixar_via_brand_api(ticker):
    """Arquivo oficial via GET /v2/brands/logo (self-host). Nao usa a CDN."""
    segredo = _segredo_logo_dev()
    chave = _chave_logo(ticker)
    if not segredo or not chave:
        return None, None
    consulta = f"https://api.logo.dev/v2/brands/logo?ticker={chave}.SA"
    try:
        resposta = requests.get(
            consulta,
            headers={"Authorization": f"Bearer {segredo}", "Accept": "application/json"},
            timeout=15,
        )
        if resposta.status_code != 200:
            logger.debug("Brand API HTTP %s para %s", resposta.status_code, chave)
            return None, None
        dados = (resposta.json() or {}).get("data") or {}
        download = str(dados.get("url") or "").strip()
        if not download:
            return None, None
        separador = "&" if "?" in download else "?"
        arquivo = requests.get(
            f"{download}{separador}format=png&size=200",
            timeout=15,
            allow_redirects=True,
        )
        if arquivo.status_code != 200:
            logger.debug("Download Brand API HTTP %s para %s", arquivo.status_code, chave)
            return None, None
        mime = _mime_imagem(arquivo.content, arquivo.headers.get("Content-Type"))
        if not mime:
            return None, None
        return arquivo.content, mime
    except requests.RequestException:
        logger.debug("Brand API indisponivel (rede) para %s", chave)
    except Exception:
        logger.debug("Falha inesperada na Brand API", exc_info=True)
    return None, None


def _obter_bytes_logo_dev(ticker):
    """Bytes para Drive/Telegram: Brand API (sk_) e, se faltar, CDN (pk_)."""
    conteudo, mime = _baixar_via_brand_api(ticker)
    if conteudo:
        return conteudo, mime
    url = _url_logo_dev(ticker)
    if not url:
        return None, None
    return _baixar_imagem_logo_dev(url)


def obter_bytes_logo_url(url):
    """Baixa bytes de uma URL da CDN para o bot enviar (Telegram nao puxa img.logo.dev)."""
    if "img.logo.dev" not in str(url or ""):
        return None
    conteudo, _mime = _baixar_imagem_logo_dev(url)
    return conteudo


def _resolver_drive_manager(drive_manager):
    if drive_manager is not None:
        return drive_manager
    if not all(
        (os.environ.get(nome) or "").strip()
        for nome in ("CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN")
    ):
        return None
    try:
        from services.dashboard_menus import obter_drive_manager

        return obter_drive_manager()
    except Exception:
        logger.debug("Drive manager indisponivel para logos", exc_info=True)
        return None


def _media_drive(arquivo):
    file_id = (arquivo or {}).get("id")
    if not file_id:
        return ""
    return f"drive:{file_id}"


def _consultar_drive(ticker, tipo, drive_manager):
    if drive_manager is None:
        return ""
    try:
        arquivo = drive_manager.buscar_logo_catalogo(ticker, tipo)
    except Exception:
        logger.warning(
            "Falha ao consultar catalogo de logos no Drive (%s)",
            ticker,
            exc_info=True,
        )
        return ""
    return _media_drive(arquivo)


def _salvar_no_drive(ticker, tipo, conteudo, mime, drive_manager):
    if drive_manager is None or not conteudo:
        return ""
    try:
        salvo = drive_manager.salvar_logo_catalogo(
            ticker, conteudo, tipo=tipo, mime_type=mime or "image/png"
        )
        return _media_drive(salvo)
    except Exception:
        logger.warning(
            "Falha ao gravar logo de %s no Drive", ticker, exc_info=True
        )
        return ""


def obter_bytes_logo_drive(media, drive_manager=None):
    """Baixa bytes de uma mídia ``drive:<id>`` para envio no Telegram."""
    if not str(media or "").startswith("drive:"):
        return None
    file_id = str(media)[6:]
    gerente = _resolver_drive_manager(drive_manager)
    if gerente is None or not file_id:
        return None
    try:
        return gerente.baixar_logo_catalogo(file_id)
    except Exception:
        logger.warning("Falha ao baixar logo do Drive", exc_info=True)
        return None


def obter_link_logo(ticker: str, tipo: str = "", drive_manager=None) -> str:
    """Resolve a mídia da logo (Drive, Logo.dev ou ``""``).

    Prioridade: catálogo Ícones B3 no Drive; se ausente, Logo.dev (e grava no
    Drive sem sobrescrever). Sem imagem válida, devolve vazio (texto).
    """
    chave = _chave_logo(ticker)
    if not chave:
        return ""

    with _LOCK:
        if _cache_valido(chave):
            return _CACHE_LOGOS.get(chave, "")

    gerente = drive_manager if drive_manager is not None else _resolver_drive_manager(None)
    url = _consultar_drive(chave, tipo, gerente)

    if not url:
        conteudo, mime = _obter_bytes_logo_dev(ticker)
        if conteudo:
            gravado = _salvar_no_drive(chave, tipo, conteudo, mime, gerente)
            url = gravado or _url_logo_dev(ticker) or ""

    _guardar_cache(chave, url)
    if url:
        logger.debug("Logo resolvida para %s", chave)
    else:
        logger.debug("Sem logo para %s; usando fallback textual", chave)
    return url


def obter_media_logo(ticker: str, tipo: str = "", drive_manager=None) -> str:
    """Mídia pronta para o Telegram: ``file_id`` em cache ou URL/Drive da logo."""
    file_id = obter_file_id_logo(ticker)
    if file_id:
        return file_id
    return obter_link_logo(ticker, tipo, drive_manager=drive_manager)


def obter_media_logo_rapida(ticker: str, tipo: str = "") -> str:
    """Mídia operacional: ``file_id``, cache Drive ou URL Logo.dev sem GET extra."""
    file_id = obter_file_id_logo(ticker)
    if file_id:
        return file_id
    chave = _chave_logo(ticker)
    with _LOCK:
        if _cache_valido(chave):
            return _CACHE_LOGOS.get(chave, "")
    gerente = _resolver_drive_manager(None)
    no_drive = _consultar_drive(chave, tipo, gerente)
    if no_drive:
        _guardar_cache(chave, no_drive)
        return no_drive
    return _url_logo_dev(ticker) or ""
