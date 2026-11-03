"""Notifica apenas o administrador quando um workflow do GitHub falha por completo."""
from __future__ import annotations

import os
import urllib.parse
import urllib.request

import config


def mensagem():
    workflow = os.environ.get("GITHUB_WORKFLOW", "Workflow")
    repositorio = os.environ.get("GITHUB_REPOSITORY", "repositório")
    url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    link = f"{url}/{repositorio}/actions/runs/{run_id}" if run_id else url
    return (
        f"⚠️ {workflow} falhou no GitHub.\n"
        "Nenhuma atualização posterior foi confirmada.\n"
        f"Log: {link}"
    )


def enviar():
    token = str(getattr(config, "TELEGRAM_BOT_TOKEN", "") or "").strip()
    destino = str(getattr(config, "TELEGRAM_ADMIN_ID", "") or "").strip()
    if not token or not destino:
        print("Aviso Telegram não enviado: configuração administrativa ausente.")
        return False
    corpo = urllib.parse.urlencode(
        {"chat_id": destino, "text": mensagem(), "disable_web_page_preview": "true"}
    ).encode("utf-8")
    requisicao = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=corpo,
        method="POST",
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=10) as resposta:
            if 200 <= resposta.status < 300:
                print("Aviso administrativo enviado.")
                return True
    except Exception as exc:
        print(f"Aviso Telegram não enviado: {type(exc).__name__}")
    return False


if __name__ == "__main__":
    enviar()
