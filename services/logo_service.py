"""Resolução e cache das logos dos ativos.

O catálogo oficial usado pelo projeto é o repositório público
``WandesonMarcone/icones-bolsabr`` (fork do catálogo ``icones-b3``), que expõe
mais de três mil PNGs em uma pasta plana (``icones/<TICKER>.png``).

Decisões importantes deste módulo:

* **Sem listagem pela API do GitHub.** A API de conteúdos/trees é limitada
  (60 requisições por hora sem autenticação) e ficaria inviável para cada
  ticker. A resolução usa apenas URLs ``raw.githubusercontent.com``, que não
  consomem a cota da API;
* **Mesmo catálogo, sem duplicação.** Nenhuma imagem é copiada para dentro do
  repositório. PETR3 e PETR4 compartilham a identidade visual da Petrobras
  (arquivo canônico ``PETR4.png``), mas continuam sendo ativos distintos nos
  dados financeiros;
* **Logo.dev é alternativa, não a fonte principal.** Só é consultado quando o
  repositório não tem a imagem e existe ``LOGO_DEV_TOKEN`` configurado;
* **Cache em dois níveis.** URLs/imagens (inclusive resultados negativos de
  rede) ficam em memória. O ``file_id`` devolvido pelo Telegram é persistido no
  banco (``cache_logos_telegram``) e reutilizado inclusive depois de
  reinicializações do bot;
* **Empresa, não ticker, para a logo.** Quando o catálogo central já vinculou
  PETR3 e PETR4 à mesma empresa, os dois compartilham o ``file_id``. Os dados
  financeiros continuam separados em ``ativos``;
* **Falha segura.** Qualquer erro de rede, timeout ou resposta inesperada
  resulta em ``""`` (sem logo) e nunca interrompe o fluxo do bot. Falhas de
  envio alimentam um cache negativo com expiração, sem apagar o cache local de
  URLs.
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

# Catálogo existente. Pode ser sobrescrito por ambiente sem alterar o código.
REPO_PADRAO = "WandesonMarcone/icones-bolsabr"
BRANCH_PADRAO = "main"
PASTA_PADRAO = "icones"

# Identidade visual compartilhada por classes de ações da mesma empresa. A
# chave é o ticker consultado e o valor é o arquivo canônico usado para a logo.
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
# Catálogo GitHub / Logo.dev
# ---------------------------------------------------------------------------


def _configuracao_github():
    repo = os.environ.get("LOGO_GITHUB_REPO", REPO_PADRAO).strip().strip("/")
    branch = os.environ.get("LOGO_GITHUB_BRANCH", BRANCH_PADRAO).strip()
    pasta = os.environ.get("LOGO_GITHUB_DIR", PASTA_PADRAO).strip().strip("/")
    return repo or REPO_PADRAO, branch or BRANCH_PADRAO, pasta


def _candidatos_arquivo(ticker):
    """Nomes de arquivo candidatos, do mais específico ao mais genérico.

    O primeiro candidato é a identidade visual canônica (PETR3 -> PETR4). Em
    seguida tenta-se o próprio ticker e, por último, a raiz sem dígitos
    (``KNCR11`` -> ``KNCR``), que existe para alguns ativos no catálogo.
    """
    chave = _chave_logo(ticker)
    candidatos = [chave]

    normalizado = _normalizar_ticker(ticker)
    if normalizado and normalizado not in candidatos:
        candidatos.append(normalizado)

    raiz = re.sub(r"\d+$", "", normalizado)
    if raiz and len(raiz) >= 3 and raiz not in candidatos:
        candidatos.append(raiz)
    return candidatos


def _urls_github(ticker):
    repo, branch, pasta = _configuracao_github()
    base = f"https://raw.githubusercontent.com/{repo}/{branch}"
    if pasta:
        base = f"{base}/{pasta}"
    return [f"{base}/{arquivo}.png" for arquivo in _candidatos_arquivo(ticker)]


def _url_logo_dev(ticker):
    token = (os.environ.get("LOGO_DEV_TOKEN") or "").strip()
    if not token:
        return None
    chave = _chave_logo(ticker)
    if not chave:
        return None
    return (
        f"https://img.logo.dev/ticker:{chave}.SA"
        f"?token={token}&size=200&format=png"
    )


def _url_disponivel(url, timeout=_TIMEOUT_CURTO):
    """Confere se a URL devolve uma imagem, sem baixar o conteúdo inteiro."""
    try:
        resposta = requests.head(
            url, headers=_HEADERS, timeout=timeout, allow_redirects=True
        )
        if resposta.status_code == 200:
            content_type = (resposta.headers.get("Content-Type") or "").lower()
            # O raw.githubusercontent.com responde image/png; se o servidor não
            # informar o tipo, aceitamos o 200 para não descartar imagens boas.
            return not content_type or content_type.startswith("image/")
        if resposta.status_code in (403, 405):
            # Alguns proxies/CDNs rejeitam HEAD; faz um GET curto e fecha.
            resposta = requests.get(
                url,
                headers=_HEADERS,
                timeout=timeout,
                stream=True,
                allow_redirects=True,
            )
            try:
                if resposta.status_code == 200:
                    content_type = (
                        resposta.headers.get("Content-Type") or ""
                    ).lower()
                    return not content_type or content_type.startswith("image/")
            finally:
                resposta.close()
    except requests.RequestException:
        logger.debug("Logo indisponivel (erro de rede): %s", url)
    except Exception:
        logger.debug("Falha inesperada ao testar logo: %s", url, exc_info=True)
    return False


def _primeira_url_valida(urls):
    for url in urls:
        if _url_disponivel(url):
            return url
    return ""


def _tentar_cache_drive(ticker, url_origem, drive_manager):
    """Copia opcional para o Drive (mantido por compatibilidade).

    Só é executado quando o chamador passa explicitamente um ``drive_manager``.
    O painel do bot não usa esse caminho por padrão: o cache preferencial é o
    ``file_id`` do Telegram.
    """
    if drive_manager is None or not url_origem:
        return None
    try:
        imagem = requests.get(url_origem, headers=_HEADERS, timeout=5)
        if imagem.status_code != 200:
            return None
        return drive_manager.salvar_logo_drive(
            ticker=_normalizar_ticker(ticker),
            conteudo_bytes=imagem.content,
        )
    except Exception:
        logger.warning(
            "Falha no cache opt-in de logo no Drive (%s)",
            _normalizar_ticker(ticker),
            exc_info=True,
        )
        return None


def obter_link_logo(ticker: str, tipo: str = "", drive_manager=None) -> str:
    """Retorna a URL da logo do ativo (ou ``""`` quando não existe).

    ``tipo`` é aceito por compatibilidade com os chamadores atuais, mas o
    catálogo é plano e não separa FIIs de ações. O parâmetro ``drive_manager`` é
    opcional e só ativa a cópia para o Drive quando fornecido explicitamente.
    """
    chave = _chave_logo(ticker)
    if not chave:
        return ""

    with _LOCK:
        if _cache_valido(chave):
            return _CACHE_LOGOS.get(chave, "")

    url = _primeira_url_valida(_urls_github(ticker))

    if not url:
        url_logo_dev = _url_logo_dev(ticker)
        if url_logo_dev and _url_disponivel(url_logo_dev):
            url = url_logo_dev

    if url and drive_manager is not None:
        link_drive = _tentar_cache_drive(ticker, url, drive_manager)
        if link_drive:
            url = link_drive

    _guardar_cache(chave, url)
    if url:
        logger.debug("Logo resolvida para %s: %s", chave, url)
    else:
        logger.debug("Sem logo para %s; usando fallback textual", chave)
    return url


def obter_media_logo(ticker: str, tipo: str = "", drive_manager=None) -> str:
    """Mídia pronta para o Telegram: ``file_id`` em cache ou URL da logo.

    O retorno vazio significa "sem logo" e deve ser tratado pelo chamador com
    um painel/mensagem apenas textual.
    """
    file_id = obter_file_id_logo(ticker)
    if file_id:
        return file_id
    return obter_link_logo(ticker, tipo, drive_manager=drive_manager)


def obter_media_logo_rapida(ticker: str) -> str:
    """Mídia para mensagens operacionais sem pré-verificação de rede.

    Usa o ``file_id`` persistido ou a primeira URL do catálogo. Se houver cache
    negativo válido, retorna vazio para o chamador cair imediatamente na
    mensagem textual. Se a imagem não existir, o envio falha e o chamador
    registra a falha (``registrar_falha_logo``) para expirar a tentativa.
    """
    file_id = obter_file_id_logo(ticker)
    if file_id:
        return file_id
    chave = _chave_logo(ticker)
    with _LOCK:
        if _cache_valido(chave) and not _CACHE_LOGOS.get(chave):
            return ""
    urls = _urls_github(ticker)
    return urls[0] if urls else ""
