"""API protegida da Central de Controle hospedada no GitHub Pages.

O site e' apenas a interface. Credenciais de Drive, GitHub, Neon e Telegram
permanecem somente no Render; o navegador envia um token administrativo de
sessao para solicitar operacoes ja existentes no robô.
"""

from __future__ import annotations

import os
import re
import threading
import uuid
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, request

admin_api = Blueprint("admin_api", __name__)
_TICKER = re.compile(r"^[A-Z]{4,6}[0-9]{1,2}$")
_TASKS: dict[str, dict] = {}


def _origens_permitidas() -> set[str]:
    bruto = os.environ.get("ADMIN_DASHBOARD_ORIGINS", "")
    return {item.strip().rstrip("/") for item in bruto.split(",") if item.strip()}


def _cors(resposta):
    origem = (request.headers.get("Origin") or "").rstrip("/")
    if origem and origem in _origens_permitidas():
        resposta.headers["Access-Control-Allow-Origin"] = origem
        resposta.headers["Vary"] = "Origin"
        resposta.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        resposta.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resposta


@admin_api.after_request
def aplicar_cors(resposta):
    return _cors(resposta)


@admin_api.before_request
def responder_preflight():
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))
    return None


def _token_configurado():
    return (os.environ.get("ADMIN_DASHBOARD_TOKEN") or "").strip()


def exige_admin(funcao):
    @wraps(funcao)
    def protegida(*args, **kwargs):
        esperado = _token_configurado()
        recebido = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if not esperado:
            return jsonify({"message": "ADMIN_DASHBOARD_TOKEN não está configurado no Render."}), 503
        if not recebido or recebido != esperado:
            return jsonify({"message": "Acesso administrativo não autorizado."}), 401
        return funcao(*args, **kwargs)
    return protegida


def _registrar_tarefa(action: str, descricao: str, alvo=None):
    tarefa_id = str(uuid.uuid4())[:8]
    _TASKS[tarefa_id] = {
        "id": tarefa_id,
        "action": action,
        "label": descricao,
        "target": alvo,
        "status": "em_andamento",
        "when": datetime.now().strftime("%d/%m %H:%M"),
    }
    return tarefa_id


def _executar_em_background(tarefa_id: str, funcao, *args):
    def executar():
        try:
            funcao(*args)
            _TASKS[tarefa_id]["status"] = "ok"
        except Exception as exc:  # detalhes ficam somente no log privado Render
            _TASKS[tarefa_id]["status"] = "falha"
            _TASKS[tarefa_id]["error"] = type(exc).__name__
    threading.Thread(target=executar, daemon=True).start()


def _coletar_documentos_isolados(ticker: str, periodo: str | None):
    from atualizador_documentos import SessionDB
    from pipeline_dados.modelos_ativos import Ativo
    from sqlalchemy import func

    session = SessionDB()
    try:
        ativo = session.query(Ativo).filter(func.upper(Ativo.ticker) == ticker).first()
        if ativo is None:
            raise ValueError("ATIVO_NAO_CADASTRADO")
        tipo = str(getattr(ativo.tipo, "value", ativo.tipo) or "").upper()
    finally:
        session.close()
    if tipo == "FII":
        from pipeline_dados.coletor_fnet import ColetorFnet
        ColetorFnet().coletar(dias=int(periodo or 60), ticker=ticker)
    else:
        from pipeline_dados.coletor_docs_acoes import RelatoriosAcoesCVM
        ano = int(periodo) if periodo and len(periodo) == 4 else datetime.now().year
        RelatoriosAcoesCVM().vasculhar_documentos(ano=ano, ticker=ticker)


def _diagnostico_fontes():
    """Executa uma amostra curta; o diagnóstico completo continua no Actions."""
    from scripts.diagnostico_fontes import diagnosticar
    tickers = (os.environ.get("DIAGNOSTICO_TICKERS") or "PETR4,MXRF11,HGLG11").split(",")
    return diagnosticar(tickers, limite=min(3, len(tickers)), pausa=2, orcamento=120)


@admin_api.route("/api/admin/status", methods=["GET"])
@exige_admin
def status():
    recentes = list(_TASKS.values())[-8:]
    recentes.reverse()
    pendentes = sum(1 for item in _TASKS.values() if item["status"] == "em_andamento")
    return jsonify({
        "robot": "Online",
        "updated_at": datetime.now().strftime("Consulta %d/%m/%Y %H:%M"),
        "metrics": {"queue": pendentes, "pending_documents": "—", "last_update": "Agora"},
        "recent": recentes,
    })


@admin_api.route("/api/admin/commands", methods=["POST"])
@exige_admin
def executar_comando():
    dados = request.get_json(silent=True) or {}
    action = str(dados.get("action") or "").strip()
    ticker = str(dados.get("ticker") or "").strip().upper()
    periodo = str(dados.get("period") or "").strip()
    if ticker and not _TICKER.fullmatch(ticker):
        return jsonify({"message": "Ticker inválido."}), 400

    if action == "status":
        return jsonify({"message": "Status atualizado."})
    if action == "atualizar_ativo":
        if not ticker:
            return jsonify({"message": "Informe o ticker do ativo."}), 400
        from services.github_actions import disparar_atualizacao_isolada
        ok, mensagem = disparar_atualizacao_isolada(ticker)
        return jsonify({"message": mensagem}), 202 if ok else 502
    if action == "forcar_documentos":
        if not ticker:
            return jsonify({"message": "Informe o ticker do ativo."}), 400
        tarefa = _registrar_tarefa(action, f"Busca documental de {ticker}", ticker)
        _executar_em_background(tarefa, _coletar_documentos_isolados, ticker, periodo)
        return jsonify({"message": f"Busca documental de {ticker} iniciada.", "task_id": tarefa}), 202

    from services import orquestrador
    acoes = {
        "forcar_varredura": ("Varredura de documentos FNET", orquestrador.varredura_diaria),
        "forcar_docs_acoes": ("Coleta de PDFs de ações", orquestrador.coleta_docs_acoes),
        "forcar_cvm": ("Atualização CVM/ITR", orquestrador.varredura_diaria),
        "forcar_fiis": ("Coleta de informes de FIIs", orquestrador.coleta_informes_fiis),
        "processar_acoes_ia": ("Classificação de ações com IA", orquestrador.processar_ia_acoes),
        "alimentar_ia": ("Alimentação da base de IA", orquestrador.alimentar_ia),
        "auditar_drive": ("Auditoria do Google Drive", orquestrador.auditar_drive),
    }
    if action == "gerar_resumos_ia":
        from services.resumos_ativos import gerar_resumos_ativos
        acoes[action] = ("Geração de resumos por IA", gerar_resumos_ativos)
    if action == "diagnostico_fontes":
        acoes[action] = ("Diagnóstico das fontes", _diagnostico_fontes)
    if action not in acoes:
        return jsonify({"message": "Comando não disponível na Central."}), 400
    descricao, funcao = acoes[action]
    tarefa = _registrar_tarefa(action, descricao)
    _executar_em_background(tarefa, funcao)
    return jsonify({"message": f"{descricao} iniciado em segundo plano.", "task_id": tarefa}), 202
