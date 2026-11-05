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
_STORAGE: dict[str, object] = {"status": "not_measured"}
_EXTERNAL_HEALTH: dict[str, object] = {"drive": "checking", "github": "checking"}
_EXTERNAL_HEALTH_AT: datetime | None = None
_EXTERNAL_HEALTH_RUNNING = False


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


def _medir_armazenamento():
    """Medição leve do Neon e do diretório raiz usado pelo robô no Drive."""
    from sqlalchemy import text
    from atualizador_documentos import SessionDB

    _STORAGE.update({"status": "measuring", "error": None})
    try:
        session = SessionDB()
        try:
            banco_bytes = int(session.execute(text("SELECT pg_database_size(current_database())")).scalar() or 0)
            tabelas_bytes = int(session.execute(text(
                "SELECT COALESCE(SUM(pg_total_relation_size(relid)), 0) "
                "FROM pg_catalog.pg_statio_user_tables"
            )).scalar() or 0)
        finally:
            session.close()
        from modules.GoogleDriveManager import GoogleDriveManager
        drive = GoogleDriveManager().medir_armazenamento_robo()
        _STORAGE.update({
            "status": "ready",
            "measured_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "neon": {"database_bytes": banco_bytes, "tables_bytes": tabelas_bytes},
            "drive": drive,
        })
    except Exception as exc:
        _STORAGE.update({"status": "error", "error": type(exc).__name__})


def _verificar_servicos_externos():
    """Testa Drive e GitHub com as credenciais já guardadas no Render."""
    global _EXTERNAL_HEALTH_AT, _EXTERNAL_HEALTH_RUNNING
    resultado = {"drive": "error", "github": "error"}
    try:
        from modules.GoogleDriveManager import GoogleDriveManager
        GoogleDriveManager().service.about().get(fields="storageQuota(usage)").execute()
        resultado["drive"] = "ok"
    except Exception:
        resultado["drive"] = "error"

    try:
        import requests
        token = (os.environ.get("GITHUB_ACTIONS_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
        repo = (os.environ.get("GITHUB_REPOSITORY") or "WandesonMarcone/robo-financeiro").strip()
        if not token:
            resultado["github"] = "missing"
        else:
            resposta = requests.get(
                f"https://api.github.com/repos/{repo}/actions/runs?per_page=1",
                headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"},
                timeout=12,
            )
            resultado["github"] = "ok" if resposta.status_code == 200 else "error"
    except Exception:
        resultado["github"] = "error"
    _EXTERNAL_HEALTH.update(resultado)
    _EXTERNAL_HEALTH_AT = datetime.now()
    _EXTERNAL_HEALTH_RUNNING = False


def _saude_externa_atual() -> dict:
    """Evita chamadas externas em toda atualização da tela; renova a cada 5 min."""
    global _EXTERNAL_HEALTH_AT, _EXTERNAL_HEALTH_RUNNING
    vencida = _EXTERNAL_HEALTH_AT is None or (datetime.now() - _EXTERNAL_HEALTH_AT).total_seconds() > 300
    if vencida and not _EXTERNAL_HEALTH_RUNNING:
        _EXTERNAL_HEALTH.update({"drive": "checking", "github": "checking"})
        _EXTERNAL_HEALTH_RUNNING = True
        threading.Thread(target=_verificar_servicos_externos, daemon=True).start()
    return dict(_EXTERNAL_HEALTH)


@admin_api.route("/api/admin/storage", methods=["GET"])
@exige_admin
def armazenamento():
    """Retorna a última medição e dispara uma nova sem bloquear a interface."""
    atualizar = str(request.args.get("refresh") or "").lower() in {"1", "true", "sim"}
    if atualizar or _STORAGE.get("status") == "not_measured":
        if _STORAGE.get("status") != "measuring":
            threading.Thread(target=_medir_armazenamento, daemon=True).start()
    return jsonify(_STORAGE)


def _coletar_documentos_isolados(ticker: str, periodo: str | None):
    from atualizador_documentos import SessionDB
    from pipeline_dados.banco_dados import Ativo
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


def _ativos_para_painel(limite: int = 120) -> tuple[list[dict], dict]:
    """Leitura curta do cadastro no Neon, sem acionar coletas externas."""
    from atualizador_documentos import SessionDB
    from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
    from sqlalchemy import func

    session = SessionDB()
    try:
        linhas = (
            session.query(
                Ativo.id, Ativo.ticker, Ativo.tipo,
                func.count(DocumentosQualitativos.id).label("documentos"),
            )
            .outerjoin(DocumentosQualitativos, DocumentosQualitativos.ativo_id == Ativo.id)
            .group_by(Ativo.id, Ativo.ticker, Ativo.tipo)
            .order_by(Ativo.ticker.asc()).limit(limite).all()
        )
        ativos = [{
            "ticker": linha.ticker,
            "tipo": str(getattr(linha.tipo, "value", linha.tipo) or "—"),
            "documentos": int(linha.documentos or 0),
        } for linha in linhas]
        totais = {
            "assets": len(ativos),
            "acoes": sum(item["tipo"] == "ACAO" for item in ativos),
            "fiis": sum(item["tipo"] == "FII" for item in ativos),
            "documentos": sum(item["documentos"] for item in ativos),
        }
        return ativos, totais
    finally:
        session.close()


def _serializar_documento(documento, ticker: str) -> dict:
    """Campos seguros e úteis para auditoria documental no painel."""
    return {
        "id": documento.id,
        "ticker": ticker,
        "tipo": documento.tipo_documento or "Não classificado",
        "data_publicacao": documento.data_publicacao.isoformat() if documento.data_publicacao else None,
        "status": documento.status_processamento or "SALVO",
        "atualizado_em": documento.data_atualizacao.isoformat() if documento.data_atualizacao else None,
        "assunto": documento.assunto or "",
        "url": documento.url_pdf or "",
        "tem_resumo": bool(documento.resumo_ia),
    }


def _documentos_para_painel(ticker: str | None = None, status: str | None = None, limite: int = 100) -> list[dict]:
    """Consulta documental no Neon. Não baixa PDFs nem chama fontes externas."""
    from atualizador_documentos import SessionDB
    from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
    from sqlalchemy import func

    session = SessionDB()
    try:
        consulta = session.query(DocumentosQualitativos, Ativo.ticker).join(Ativo, Ativo.id == DocumentosQualitativos.ativo_id)
        if ticker:
            consulta = consulta.filter(func.upper(Ativo.ticker) == ticker.upper())
        if status:
            consulta = consulta.filter(func.upper(DocumentosQualitativos.status_processamento) == status.upper())
        linhas = consulta.order_by(
            DocumentosQualitativos.data_publicacao.desc(),
            DocumentosQualitativos.id.desc(),
        ).limit(min(max(limite, 1), 200)).all()
        return [_serializar_documento(documento, ativo_ticker) for documento, ativo_ticker in linhas]
    finally:
        session.close()


@admin_api.route("/api/admin/status", methods=["GET"])
@exige_admin
def status():
    recentes = list(_TASKS.values())[-8:]
    recentes.reverse()
    pendentes = sum(1 for item in _TASKS.values() if item["status"] == "em_andamento")
    neon_ok = False
    try:
        _, base = _ativos_para_painel(limite=500)
        neon_ok = True
    except Exception:
        base = {"assets": "—", "acoes": "—", "fiis": "—", "documentos": "—"}
    return jsonify({
        "robot": "Online",
        "updated_at": datetime.now().strftime("Consulta %d/%m/%Y %H:%M"),
        "metrics": {"queue": pendentes, "pending_documents": base["documentos"], "last_update": "Agora", **base},
        "services": {
            "render": "ok",
            "neon": "ok" if neon_ok else "error",
            **_saude_externa_atual(),
        },
        "recent": recentes,
    })


@admin_api.route("/api/admin/assets", methods=["GET"])
@exige_admin
def listar_ativos():
    """Lista o cadastro real limitado, sem acionar coleta externa."""
    try:
        ativos, totais = _ativos_para_painel()
    except Exception:
        return jsonify({"message": "Não foi possível consultar o cadastro de ativos agora."}), 503
    return jsonify({"assets": ativos, "totals": totais})


@admin_api.route("/api/admin/documents", methods=["GET"])
@exige_admin
def listar_documentos():
    ticker = str(request.args.get("ticker") or "").strip().upper()
    status = str(request.args.get("status") or "").strip().upper()
    busca = str(request.args.get("q") or "").strip().lower()
    if ticker and not _TICKER.fullmatch(ticker):
        return jsonify({"message": "Ticker inválido."}), 400
    try:
        documentos = _documentos_para_painel(ticker=ticker or None, status=status or None)
    except Exception:
        return jsonify({"message": "Não foi possível consultar os documentos no Neon agora."}), 503
    if busca:
        documentos = [doc for doc in documentos if busca in " ".join([
            doc["ticker"], doc["tipo"], doc["status"], doc["assunto"], doc["data_publicacao"] or "",
        ]).lower()]
    return jsonify({"documents": documentos, "total": len(documentos), "ticker": ticker or None})


@admin_api.route("/api/admin/commands", methods=["POST"])
@exige_admin
def executar_comando():
    dados = request.get_json(silent=True) or {}
    action = str(dados.get("action") or "").strip()
    ticker = str(dados.get("ticker") or "").strip().upper()
    periodo = str(dados.get("period") or "").strip()
    documento_id = dados.get("document_id")
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
    if action == "processar_pendentes_acao":
        if not ticker:
            return jsonify({"message": "Informe o ticker da ação para processar somente seus pendentes."}), 400
        from services import orquestrador
        tarefa = _registrar_tarefa(action, f"Classificação de pendentes de {ticker}", ticker)
        _executar_em_background(tarefa, orquestrador.processar_ia_acoes, ticker)
        return jsonify({"message": f"Classificação dos documentos PENDENTE_ACAO de {ticker} iniciada.", "task_id": tarefa}), 202
    if action == "organizar_documento_drive":
        try:
            documento_id = int(documento_id)
            if documento_id <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"message": "Documento inválido."}), 400
        from atualizador_documentos import rotina_processar_acoes, rotina_processar_pendentes
        from pipeline_dados.banco_dados import DocumentosQualitativos
        from atualizador_documentos import SessionDB
        session = SessionDB()
        try:
            documento = session.query(DocumentosQualitativos).filter_by(id=documento_id).first()
            if not documento:
                return jsonify({"message": "Documento não encontrado."}), 404
            status_documento = documento.status_processamento
            alvo = documento.ativo.ticker
        finally:
            session.close()
        if status_documento == "PENDENTE":
            tarefa = _registrar_tarefa(action, f"Organização no Drive: {alvo}", alvo)
            _executar_em_background(tarefa, rotina_processar_pendentes, documento_id)
        elif status_documento == "PENDENTE_ACAO":
            tarefa = _registrar_tarefa(action, f"Organização no Drive: {alvo}", alvo)
            _executar_em_background(tarefa, rotina_processar_acoes, alvo, documento_id)
        else:
            return jsonify({"message": f"Este documento está em {status_documento} e não pode ser reenviado pela fila pendente."}), 409
        return jsonify({"message": f"Documento de {alvo} enviado para classificação e organização no Drive.", "task_id": tarefa}), 202

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
