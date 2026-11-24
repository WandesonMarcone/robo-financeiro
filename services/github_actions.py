"""Disparo seguro de workflows do GitHub para operações administrativas."""

import os

import requests


def _disparar_workflow(nome, inputs, timeout=20):
    token = (os.environ.get("GITHUB_ACTIONS_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    repositorio = (os.environ.get("GITHUB_REPOSITORY") or "WandesonMarcone/robo-financeiro").strip()
    if not token:
        return False, "GITHUB_ACTIONS_TOKEN não configurado no Render."
    url = f"https://api.github.com/repos/{repositorio}/actions/workflows/{nome}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        resposta = requests.post(
            url, headers=headers, json={"ref": "main", "inputs": inputs}, timeout=timeout,
        )
    except requests.RequestException as exc:
        return False, f"Falha de rede ao enfileirar: {exc.__class__.__name__}."
    if resposta.status_code == 204:
        return True, "Workflow enfileirado no GitHub Actions."
    detalhe = (resposta.text or "").strip().replace("\n", " ")[:240]
    return False, f"GitHub recusou o disparo (HTTP {resposta.status_code}){': ' + detalhe if detalhe else '.'}"


def disparar_atualizacao_isolada(ticker, timeout=20):
    """Enfileira uma atualização de um único ativo no workflow cíclico.

    Retorna ``(True, mensagem)`` em sucesso. A credencial nunca é incluída em
    logs ou na mensagem devolvida ao usuário.
    """
    ticker = str(ticker or "").strip().upper()
    if not ticker:
        return False, "Ticker não informado."
    ok, mensagem = _disparar_workflow(
        "atualizacao-isolada.yml", {"ticker": ticker}, timeout=timeout,
    )
    return ok, "Busca isolada enfileirada no GitHub Actions." if ok else mensagem


def disparar_fundamentos_valuation(ticker, anos=5, timeout=20):
    """Enfileira a coleta pesada, sem ocupar a instância web do Render."""
    ticker = str(ticker or "").strip().upper()
    if not ticker:
        return False, "Ticker não informado."
    try:
        anos = max(3, min(int(anos), 5))
    except (TypeError, ValueError):
        return False, "Período deve ser de 3, 4 ou 5 anos."
    ok, mensagem = _disparar_workflow(
        "fundamentos-valuation.yml", {"ticker": ticker, "anos": str(anos)}, timeout=timeout,
    )
    return ok, "Coleta de fundamentos enfileirada no GitHub Actions." if ok else mensagem
