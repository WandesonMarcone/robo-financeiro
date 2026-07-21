import requests
import os
import config

def obter_link_logo(ticker, tipo, drive_manager=None):
    """
    Motor super-rápido de busca de logos.
    Retorna o link DIRETO (GitHub ou Logo.dev) para o Telegram gerar o preview na hora.
    """
    try:
        ticker_upper = ticker.upper()
        pasta_github = "fiis" if tipo == "fii" else "acoes"

        # 1. Tenta o Link Direto do GitHub (Super rápido e o Telegram ama ler direto o .png)
        github_url = f"https://raw.githubusercontent.com/WandesonMarcone/icones-bolsabr/main/{pasta_github}/{ticker_upper}.png"
        
        # Fazemos um "ping" rápido (timeout de 2s) para ver se a imagem existe lá
        resp = requests.head(github_url, timeout=2)
        if resp.status_code == 200:
            return github_url

        # 2. Se não existir no seu GitHub, tenta o Logo.dev como plano B
        logo_dev_token = os.environ.get("LOGO_DEV_TOKEN")
        if logo_dev_token:
            logo_dev_url = f"https://img.logo.dev/ticker:{ticker_upper}.SA?token={logo_dev_token}"
            return logo_dev_url

    except Exception as e:
        print(f"⚠️ Aviso: Erro ao buscar logo de {ticker}: {e}")
        
    # 3. Se falhar, retorna vazio (o painel carrega sem logo, mas não trava)
    return ""