"""Disparo seguro de workflows do GitHub para operações administrativas."""

import os

import requests


def disparar_atualizacao_isolada(ticker, timeout=20):
    """Enfileira uma atualização de um único ativo no workflow cíclico.

    Retorna ``(True, mensagem)`` em sucesso. A credencial nunca é incluída em
    logs ou na mensagem devolvida ao usuário.
    """
    token = (os.environ.get("GITHUB_ACTIONS_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    repositorio = (os.environ.get("GITHUB_REPOSITORY") or "WandesonMarcone/robo-financeiro").strip()
    ticker = str(ticker or "").strip().upper()
    if not token:
        return False, "GITHUB_ACTIONS_TOKEN não configurado no Render."
    if not ticker:
        return False, "Ticker não informado."

    url = f"https://api.github.com/repos/{repositorio}/actions/workflows/atualizacao-ciclica.yml/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        resposta = requests.post(
            url,
            headers=headers,
            json={"ref": "main", "inputs": {"ticker": ticker, "limite_total": "1"}},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return False, f"Falha de rede ao enfileirar: {exc.__class__.__name__}."
    if resposta.status_code == 204:
        return True, "Busca isolada enfileirada no GitHub Actions."
    return False, f"GitHub recusou o disparo (HTTP {resposta.status_code})."
