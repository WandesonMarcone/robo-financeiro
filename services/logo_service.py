import os
import requests

_CACHE_LOGOS = {}

def obter_link_logo(ticker: str, tipo: str, drive_manager=None) -> str:
    """
    Busca a logo do ativo. Se encontrar via Logo.dev ou GitHub,
    baixa automaticamente e salva no Google Drive.
    """
    ticker_upper = ticker.upper().strip()

    # Cache local em memória para respostas instantâneas
    if ticker_upper in _CACHE_LOGOS:
        return _CACHE_LOGOS[ticker_upper]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    url_origem = None

    # 1. Tenta o Logo.dev primeiro
    logo_dev_token = os.environ.get("LOGO_DEV_TOKEN")
    if logo_dev_token:
        test_url = f"https://img.logo.dev/ticker:{ticker_upper}.SA?token={logo_dev_token}"
        try:
            resp = requests.head(test_url, headers=headers, timeout=2.0)
            if resp.status_code == 200:
                url_origem = test_url
        except Exception:
            pass

    # 2. Se não achou no Logo.dev, tenta o repositório do GitHub como Plano B
    if not url_origem:
        pasta_github = "fiis" if tipo.lower() == "fii" else "acoes"
        urls_github = [
            f"https://raw.githubusercontent.com/WandesonMarcone/icones-bolsabr/main/{pasta_github}/{ticker_upper}.png",
            f"https://raw.githubusercontent.com/WandesonMarcone/icones-bolsabr/main/{pasta_github}/{ticker_upper.lower()}.png"
        ]
        for url in urls_github:
            try:
                resp = requests.head(url, headers=headers, timeout=1.5)
                if resp.status_code == 200:
                    url_origem = url
                    break
            except Exception:
                continue

    # 3. Se não achou a foto em lugar nenhum
    if not url_origem:
        _CACHE_LOGOS[ticker_upper] = ""
        return ""

    # 4. 🔥 BAIXA A IMAGEM E SALVA NO GOOGLE DRIVE AUTOMATICAMENTE
    if drive_manager:
        try:
            img_resp = requests.get(url_origem, headers=headers, timeout=5)
            if img_resp.status_code == 200:
                # Salva no Drive e pega o link do Drive
                link_drive = drive_manager.salvar_logo_drive(
                    ticker=ticker_upper,
                    conteudo_bytes=img_resp.content
                )
                if link_drive:
                    _CACHE_LOGOS[ticker_upper] = link_drive
                    return link_drive
        except Exception as e:
            print(f"⚠️ Falha no download/upload da logo para o Drive ({ticker_upper}): {e}")

    # Fallback: Se o Drive não responder, usa o link direto encontrado
    _CACHE_LOGOS[ticker_upper] = url_origem
    return url_origem
