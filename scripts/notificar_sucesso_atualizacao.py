"""Notifica o administrador ao concluir uma busca isolada."""

import os

import requests


def main():
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_ADMIN_ID") or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    ticker = (os.environ.get("TICKER_ISOLADO") or "ativo").strip().upper()
    if not token or not chat_id:
        return
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": f"✅ Busca isolada de {ticker} concluída no GitHub Actions."},
        timeout=20,
    ).raise_for_status()


if __name__ == "__main__":
    main()
