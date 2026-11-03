"""Registra no Neon o resultado final de uma execução cíclica do GitHub."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from pipeline_dados.repositorio_execucoes import RepositorioExecucoesCiclicas


STATUS_VALIDOS = {"sucesso", "falha", "cancelado"}


def _inteiro(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _numero(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _resultado(caminho):
    if not caminho:
        return {}
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def registrar(status, limite_total, resultado=None):
    if status not in STATUS_VALIDOS:
        raise ValueError("status_invalido")
    dados = _resultado(resultado)
    run_id = str(os.environ.get("GITHUB_RUN_ID") or "").strip()
    if not run_id:
        raise ValueError("github_run_id_ausente")
    repositorio = str(os.environ.get("GITHUB_REPOSITORY") or "").strip()
    servidor = str(os.environ.get("GITHUB_SERVER_URL") or "https://github.com").rstrip("/")
    url = f"{servidor}/{repositorio}/actions/runs/{run_id}" if repositorio else None
    erro = None if status == "sucesso" else "Consulte o log seguro do GitHub para o detalhe técnico."
    RepositorioExecucoesCiclicas().registrar(
        run_id=run_id,
        status=status,
        limite_total=limite_total,
        acoes_solicitadas=_inteiro(dados.get("acoes_solicitadas")),
        fiis_solicitados=_inteiro(dados.get("fiis_solicitados")),
        acoes_gravadas=dados.get("acoes_avancaram") if dados else None,
        fiis_gravados=dados.get("fiis_avancaram") if dados else None,
        duracao_segundos=_numero(dados.get("duracao_segundos")),
        url_execucao=url,
        resumo_erro=erro,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", required=True, choices=sorted(STATUS_VALIDOS))
    parser.add_argument("--limite-total", required=True, type=int)
    parser.add_argument("--resultado")
    args = parser.parse_args()
    if not 1 <= args.limite_total <= 20:
        raise ValueError("limite_total_invalido")
    registrar(args.status, args.limite_total, args.resultado)
    print("Histórico operacional registrado.")


if __name__ == "__main__":
    main()
