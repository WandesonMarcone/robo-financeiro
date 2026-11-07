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
from urllib.parse import urlencode
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
    from services.historico_operacional import iniciar_evento
    evento_id = iniciar_evento(
        action, origem="PAINEL_ADMIN", ticker=alvo, mensagem=descricao,
        detalhes={"task_id": tarefa_id},
    )
    _TASKS[tarefa_id] = {
        "id": tarefa_id,
        "action": action,
        "label": descricao,
        "target": alvo,
        "status": "em_andamento",
        "when": datetime.now().strftime("%d/%m %H:%M"),
        "event_id": evento_id,
        "progress": [{"at": datetime.now().isoformat(), "message": "Tarefa recebida pelo painel."}],
    }
    return tarefa_id


def _executar_em_background(tarefa_id: str, funcao, *args):
    def executar():
        from services.historico_operacional import concluir_evento, registrar_progresso, registrar_resultado
        try:
            _TASKS[tarefa_id]["progress"].append({"at": datetime.now().isoformat(), "message": "Execução iniciada no robô."})
            registrar_progresso(_TASKS[tarefa_id].get("event_id"), "Execução iniciada no robô.")
            retorno = funcao(*args)
            detalhes = getattr(retorno, "detalhes_painel", None)
            if callable(detalhes):
                registrar_resultado(_TASKS[tarefa_id].get("event_id"), detalhes())
            _TASKS[tarefa_id]["status"] = "ok"
            mensagem = _resumo_retorno(retorno) or _TASKS[tarefa_id]["label"]
            _TASKS[tarefa_id]["progress"].append({"at": datetime.now().isoformat(), "message": mensagem})
            registrar_progresso(_TASKS[tarefa_id].get("event_id"), mensagem)
            concluir_evento(_TASKS[tarefa_id].get("event_id"), sucesso=True,
                            mensagem=mensagem)
        except Exception as exc:  # detalhes ficam somente no log privado Render
            _TASKS[tarefa_id]["status"] = "falha"
            _TASKS[tarefa_id]["error"] = type(exc).__name__
            _TASKS[tarefa_id]["progress"].append({"at": datetime.now().isoformat(), "message": f"Falha: {type(exc).__name__}"})
            registrar_progresso(_TASKS[tarefa_id].get("event_id"), f"Falha: {type(exc).__name__}")
            concluir_evento(_TASKS[tarefa_id].get("event_id"), sucesso=False,
                            erro=type(exc).__name__)
    threading.Thread(target=executar, daemon=True).start()


def _resumo_retorno(retorno) -> str:
    if retorno is None:
        return "Concluída sem resumo retornado."
    mensagem = getattr(retorno, "mensagem_telegram", None)
    if callable(mensagem):
        try:
            return str(mensagem())[:1500]
        except Exception:
            pass
    if isinstance(retorno, dict):
        pares = [f"{chave}: {valor}" for chave, valor in retorno.items() if isinstance(valor, (str, int, float, bool))]
        return "; ".join(pares)[:1500] or "Concluída."
    return str(retorno)[:1500]


def _medir_armazenamento():
    """Medição leve do Neon e do diretório raiz usado pelo robô no Drive."""
    from sqlalchemy import text
    from atualizador_documentos import SessionDB

    _STORAGE.update({"status": "measuring", "phase": "Medindo banco Neon…", "error": None,
                     "started_at": datetime.now().strftime("%d/%m/%Y %H:%M")})
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
        _STORAGE.update({"phase": "Neon medido. Contando arquivos da pasta do robô no Drive…",
                         "neon": {"database_bytes": banco_bytes, "tables_bytes": tabelas_bytes}})
        from modules.GoogleDriveManager import GoogleDriveManager
        drive = GoogleDriveManager().medir_armazenamento_robo()
        _STORAGE.update({
            "status": "ready",
            "phase": "Medição concluída.",
            "measured_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "neon": {"database_bytes": banco_bytes, "tables_bytes": tabelas_bytes},
            "drive": drive,
        })
    except Exception as exc:
        _STORAGE.update({"status": "error", "phase": "Falha na medição.", "error": type(exc).__name__})


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
        return ColetorFnet().coletar(dias=int(periodo or 60), ticker=ticker)
    else:
        from pipeline_dados.coletor_docs_acoes import RelatoriosAcoesCVM
        ano = int(periodo) if periodo and len(periodo) == 4 else datetime.now().year
        return RelatoriosAcoesCVM().vasculhar_documentos(ano=ano, ticker=ticker)


def _indicadores_planilha_para_painel(ticker: str, tipo: str) -> dict:
    """Lê os indicadores que o workflow isolado realmente atualiza.

    A atualização cíclica escreve primeiro na planilha. Ela não deve ser
    apresentada como se tivesse persistido cotação e DY nas tabelas contábeis
    do Neon. O cache de cinco minutos evita uma chamada ao Sheets por clique.
    """
    try:
        from services.planilhas import buscar_ativo_na_planilha
        item = buscar_ativo_na_planilha(ticker, tipo == "FII")
    except Exception:
        item = None
    if not item:
        return {"source": "Planilha indisponível ou ativo sem indicadores", "fields": []}
    if tipo == "FII":
        campos = [
            ["Cotação", item.get("preco")], ["P/VP", item.get("pvp")],
            ["Dividend Yield", item.get("dy")], ["VPA", item.get("vpa")],
            ["Dividendo mensal", item.get("div_mensal")],
            ["Tipo", item.get("tipo")], ["Setor", item.get("setor")],
        ]
    else:
        campos = [
            ["Cotação", item.get("preco")], ["Dividend Yield", item.get("dy")],
            ["P/L", item.get("pl")], ["P/VP", item.get("pvp")],
            ["ROE", item.get("roe")], ["Setor", item.get("setor")],
            ["Subsetor", item.get("subsetor")],
        ]
    return {
        "source": "Planilha de investimentos — atualizada pelo GitHub Actions",
        "updated_at": item.get("atualizado_em") or None,
        "fields": [[nome, valor] for nome, valor in campos if valor not in (None, "", "N/A")],
    }


def _monitorar_atualizacao_isolada(evento_id: int | None, ticker: str, iniciado_ts: float) -> None:
    """Converte o aceite do dispatch no resultado real do workflow, quando visível."""
    import time
    import requests
    from services.historico_operacional import concluir_evento, registrar_progresso

    token = (os.environ.get("GITHUB_ACTIONS_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    repo = (os.environ.get("GITHUB_REPOSITORY") or "WandesonMarcone/robo-financeiro").strip()
    if not token:
        return
    url = f"https://api.github.com/repos/{repo}/actions/workflows/atualizacao-isolada.yml/runs?event=workflow_dispatch&per_page=5"
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"}
    encontrado = None
    for tentativa in range(30):  # até ~10 min; o workflow possui orçamento de 9 min
        time.sleep(12 if tentativa == 0 else 20)
        try:
            resposta = requests.get(url, headers=headers, timeout=12)
            if resposta.status_code != 200:
                continue
            execucoes = resposta.json().get("workflow_runs") or []
            candidatos = []
            for execucao in execucoes:
                try:
                    criado = datetime.fromisoformat(str(execucao.get("created_at") or "").replace("Z", "+00:00")).timestamp()
                except (TypeError, ValueError):
                    criado = 0
                # Não confunde uma execução isolada antiga com a que acabou
                # de ser disparada pelo painel.
                if criado >= iniciado_ts - 15:
                    candidatos.append(execucao)
            if candidatos:
                encontrado = candidatos[0]
                if tentativa == 0:
                    registrar_progresso(evento_id, f"Workflow localizado no GitHub Actions: {encontrado.get('html_url') or 'sem link'}")
                if encontrado.get("status") == "completed":
                    sucesso = encontrado.get("conclusion") == "success"
                    registrar_progresso(evento_id, "Workflow concluído com sucesso." if sucesso else f"Workflow terminou em {encontrado.get('conclusion') or 'falha'}.")
                    concluir_evento(evento_id, sucesso=sucesso,
                                   mensagem=("Atualização isolada concluída no GitHub Actions. Reabra o ativo para consultar os indicadores atualizados."
                                             if sucesso else "Atualização isolada terminou com falha no GitHub Actions."),
                                   erro=None if sucesso else str(encontrado.get("conclusion") or "GITHUB_ACTION_FAILED"))
                    return
        except Exception:
            continue
    registrar_progresso(evento_id, "O workflow ainda não finalizou dentro da janela de acompanhamento; consulte a execução no GitHub Actions.")


def _varrer_fnet_pelo_painel(dias: int):
    """Executa apenas FNET; não mistura CVM, ações ou a fila residual."""
    from pipeline_dados.coletor_fnet import ColetorFnet
    return ColetorFnet().coletar(dias=dias)


def _diagnostico_fontes():
    """Executa uma amostra curta; o diagnóstico completo continua no Actions."""
    from scripts.diagnostico_fontes import diagnosticar
    tickers = (os.environ.get("DIAGNOSTICO_TICKERS") or "PETR4,MXRF11,HGLG11").split(",")
    return diagnosticar(tickers, limite=min(3, len(tickers)), pausa=2, orcamento=120)


def _ativos_para_painel(limite: int = 300, busca: str | None = None,
                        tipo: str | None = None) -> tuple[list[dict], dict]:
    """Leitura curta do cadastro no Neon, sem acionar coletas externas."""
    from atualizador_documentos import SessionDB
    from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
    from sqlalchemy import case, func

    session = SessionDB()
    try:
        consulta = (
            session.query(
                Ativo.id, Ativo.ticker, Ativo.tipo,
                func.count(DocumentosQualitativos.id).label("documentos"),
                func.sum(case((DocumentosQualitativos.status_processamento.in_(("PENDENTE", "PENDENTE_ACAO")), 1), else_=0)).label("pendentes"),
                func.sum(case((DocumentosQualitativos.status_processamento == "AGUARDANDO_REVISAO", 1), else_=0)).label("revisao"),
                func.sum(case((DocumentosQualitativos.status_processamento == "SALVO_DRIVE", 1), else_=0)).label("salvos_drive"),
                func.max(DocumentosQualitativos.data_atualizacao).label("ultimo_documento_em"),
            )
            .outerjoin(DocumentosQualitativos, DocumentosQualitativos.ativo_id == Ativo.id)
        )
        if busca:
            consulta = consulta.filter(func.upper(Ativo.ticker).like(f"%{busca.upper()}%"))
        if tipo in {"ACAO", "FII"}:
            consulta = consulta.filter(Ativo.tipo == tipo)
        linhas = consulta.group_by(Ativo.id, Ativo.ticker, Ativo.tipo).order_by(Ativo.ticker.asc()).limit(min(max(limite, 1), 300)).all()
        ativos = [{
            "ticker": linha.ticker,
            "tipo": str(getattr(linha.tipo, "value", linha.tipo) or "—"),
            "documentos": int(linha.documentos or 0),
            "pendentes": int(linha.pendentes or 0),
            "revisao": int(linha.revisao or 0),
            "salvos_drive": int(linha.salvos_drive or 0),
            "ultimo_documento_em": linha.ultimo_documento_em.isoformat() if linha.ultimo_documento_em else None,
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


def _historico_para_painel(limite: int = 25) -> dict:
    """Lê somente a auditoria que já foi persistida no Neon."""
    from atualizador_documentos import SessionDB
    from pipeline_dados.banco_dados import EventoOperacional, HistoricoNotificacao

    session = SessionDB()
    try:
        eventos = session.query(EventoOperacional).order_by(EventoOperacional.iniciado_em.desc()).limit(limite).all()
        notificacoes = session.query(HistoricoNotificacao).order_by(HistoricoNotificacao.criado_em.desc()).limit(limite).all()
        return {
            "operations": [{
                "id": e.id, "type": e.tipo, "origin": e.origem, "ticker": e.ticker,
                "status": e.status, "message": e.mensagem or "", "error": e.erro or "",
                "started_at": e.iniciado_em.isoformat() if e.iniciado_em else None,
                "finished_at": e.concluido_em.isoformat() if e.concluido_em else None,
                "details": _detalhes_evento(e.detalhes),
            } for e in eventos],
            "notifications": [{
                "id": n.id, "type": n.tipo, "ticker": n.ticker, "channel": n.canal,
                "status": n.status, "summary": n.resumo or "", "error": n.erro or "",
                "audience": getattr(n, "audiencia", "USUARIO") or "USUARIO",
                "user_id": getattr(n, "usuario_id", None),
                "created_at": n.criado_em.isoformat() if n.criado_em else None,
                "sent_at": n.enviado_em.isoformat() if n.enviado_em else None,
            } for n in notificacoes],
        }
    finally:
        session.close()


def _usuarios_para_painel(limite: int = 100) -> list[dict]:
    """Visão administrativa: usuários, favoritos, alertas e última entrega."""
    from sqlalchemy import text
    from atualizador_documentos import SessionDB
    session = SessionDB()
    try:
        linhas = session.execute(text("""
            SELECT u.id, u.nome, u.email, u.papel, u.status_cadastro, u.ativo,
                   COALESCE(p.alertas_ativos, TRUE) AS alertas_ativos,
                   p.variacao_minima_percentual,
                   COUNT(DISTINCT aa.ativo_id) AS favoritos,
                   MAX(h.enviado_em) AS ultima_notificacao
            FROM usuarios u
            LEFT JOIN preferencias_alertas_usuarios p ON p.usuario_id = u.id
            LEFT JOIN ativos_acompanhados aa ON aa.usuario_id = u.id
            LEFT JOIN historico_notificacoes h ON h.usuario_id = u.id
            GROUP BY u.id, u.nome, u.email, u.papel, u.status_cadastro, u.ativo,
                     p.alertas_ativos, p.variacao_minima_percentual
            ORDER BY u.id ASC LIMIT :limite
        """), {"limite": min(max(int(limite), 1), 200)}).mappings().all()
        return [{"id": x["id"], "name": x["nome"] or "Sem nome", "email": x["email"] or "",
                 "role": x["papel"] or "USUARIO", "status": x["status_cadastro"] or "—",
                 "active": bool(x["ativo"]), "alerts_active": bool(x["alertas_ativos"]),
                 "threshold": float(x["variacao_minima_percentual"]) if x["variacao_minima_percentual"] is not None else None,
                 "favorites": int(x["favoritos"] or 0),
                 "last_notification": x["ultima_notificacao"].isoformat() if x["ultima_notificacao"] else None}
                for x in linhas]
    finally:
        session.close()


def _detalhes_evento(valor) -> dict:
    try:
        import json
        resultado = json.loads(valor or "{}")
        return resultado if isinstance(resultado, dict) else {}
    except (TypeError, ValueError):
        return {}


def _alertas_para_painel(limite: int = 80) -> list[dict]:
    from atualizador_documentos import SessionDB
    from pipeline_dados.banco_dados import Ativo
    from pipeline_dados.modelos_alertas import AlertaEvento

    session = SessionDB()
    try:
        linhas = session.query(AlertaEvento, Ativo.ticker).join(
            Ativo, Ativo.id == AlertaEvento.ativo_id
        ).order_by(AlertaEvento.data_evento.desc()).limit(limite).all()
        return [{
            "ticker": ticker, "indicator": alerta.indicador, "type": alerta.tipo_alerta,
            "reason": alerta.motivo, "severity": alerta.severidade,
            "sent": bool(alerta.telegram_enviado),
            "at": alerta.data_evento.isoformat() if alerta.data_evento else None,
            "variation": float(alerta.variacao_percentual) if alerta.variacao_percentual is not None else None,
        } for alerta, ticker in linhas]
    finally:
        session.close()


def _fontes_para_painel() -> dict:
    """Estado conhecido: configurado não é tratado como teste bem-sucedido."""
    import config
    def configurada(nome: str) -> str:
        return "configured" if (os.environ.get(nome) or getattr(config, nome, None)) else "missing"
    return {
        "sources": [
            {"name": "Google Drive", "status": _saude_externa_atual().get("drive", "checking"), "detail": "Credenciais do Drive"},
            {"name": "GitHub Actions", "status": _saude_externa_atual().get("github", "checking"), "detail": "Token de consulta"},
            {"name": "FNET / B3", "status": "unknown", "detail": "Use Diagnosticar fontes para teste pontual"},
            {"name": "CVM", "status": "unknown", "detail": "Use Diagnosticar fontes para teste pontual"},
            {"name": "OpenAI", "status": configurada("OPENAI_API_KEY"), "detail": "Chave configurada"},
            {"name": "Groq", "status": configurada("GROQ_API_KEY"), "detail": "Chave configurada"},
            {"name": "OpenRouter", "status": configurada("OPENROUTER_API_KEY"), "detail": "Chave configurada"},
        ]
    }


def _detalhe_ativo_para_painel(ticker: str) -> dict | None:
    """Ficha administrativa de um ativo, sem requisitar dados de mercado."""
    from atualizador_documentos import SessionDB
    from pipeline_dados.banco_dados import (
        Ativo, DadosFinanceirosAcoes, DadosFinanceirosFiis, DocumentosQualitativos,
        EventoOperacional,
    )
    from sqlalchemy import func, text

    session = SessionDB()
    try:
        ativo = session.query(Ativo).filter(func.upper(Ativo.ticker) == ticker).first()
        if not ativo:
            return None
        tipo = str(getattr(ativo.tipo, "value", ativo.tipo) or "")
        documentos = session.query(DocumentosQualitativos).filter_by(ativo_id=ativo.id).order_by(
            DocumentosQualitativos.data_publicacao.desc(), DocumentosQualitativos.id.desc()
        ).limit(12).all()
        ultima_operacao = session.query(EventoOperacional).filter(
            func.upper(EventoOperacional.ticker) == ticker
        ).order_by(EventoOperacional.iniciado_em.desc()).first()
        dados = {"data_referencia": None, "data_coleta": None, "campos": []}
        if tipo == "FII":
            linha = session.query(DadosFinanceirosFiis).filter_by(ativo_id=ativo.id).order_by(
                DadosFinanceirosFiis.data_referencia.desc()
            ).first()
            if linha:
                dados = {
                    "data_referencia": linha.data_referencia.isoformat() if linha.data_referencia else None,
                    "data_coleta": None,
                    "campos": [
                        ["Patrimônio líquido", linha.patrimonio_liquido], ["Cotistas", linha.cotistas],
                        ["Cotas emitidas", linha.cotas_emitidas], ["Vacância física", linha.vacancia_fisica],
                    ],
                }
        else:
            linha = session.query(DadosFinanceirosAcoes).filter_by(ativo_id=ativo.id).order_by(
                DadosFinanceirosAcoes.data_referencia.desc()
            ).first()
            if linha:
                dados = {
                    "data_referencia": linha.data_referencia.isoformat() if linha.data_referencia else None,
                    "data_coleta": linha.data_coleta.isoformat() if linha.data_coleta else None,
                    "campos": [
                        ["Patrimônio líquido", linha.patrimonio_liquido], ["Receita", linha.receita],
                        ["Lucro líquido", linha.lucro_liquido], ["Dívida líquida", linha.divida_liquida],
                    ],
                }
        indicadores_mercado = _indicadores_planilha_para_painel(ativo.ticker, tipo)
        if indicadores_mercado["fields"]:
            # Mantém os dados oficiais do Neon e acrescenta os indicadores de
            # mercado da planilha, sem fingir que são a mesma fonte.
            dados["campos"] = indicadores_mercado["fields"] + dados["campos"]
        dados["fonte_mercado"] = indicadores_mercado["source"]
        dados["mercado_atualizado_em"] = indicadores_mercado.get("updated_at")
        try:
            manuais = session.execute(text(
                "SELECT chave, valor_texto, fonte, data_referencia, bloqueado, atualizado_em "
                "FROM indicadores_manuais_ativos WHERE ativo_id = :ativo_id ORDER BY chave"
            ), {"ativo_id": ativo.id}).mappings().all()
            dados["indicadores_manuais"] = [{"key": x["chave"], "value": x["valor_texto"], "source": x["fonte"],
                "reference_date": x["data_referencia"].isoformat() if x["data_referencia"] else None,
                "locked": bool(x["bloqueado"]), "updated_at": x["atualizado_em"].isoformat() if x["atualizado_em"] else None} for x in manuais]
        except Exception:
            session.rollback()
            dados["indicadores_manuais"] = []
        # A sobreposição é uma decisão humana separada da coleta. Se a migração
        # ainda não tiver sido aplicada, a ficha continua disponível normalmente.
        classificacao_manual = None
        try:
            linha_manual = session.execute(text(
                "SELECT classe, segmento, estrategia, bloqueado, atualizado_em "
                "FROM sobreposicoes_manuais_ativos WHERE ativo_id = :ativo_id"
            ), {"ativo_id": ativo.id}).mappings().first()
            if linha_manual:
                classificacao_manual = {
                    "classe": linha_manual["classe"],
                    "segmento": linha_manual["segmento"],
                    "estrategia": linha_manual["estrategia"],
                    "bloqueado": bool(linha_manual["bloqueado"]),
                    "updated_at": linha_manual["atualizado_em"].isoformat() if linha_manual["atualizado_em"] else None,
                }
        except Exception:
            session.rollback()
        return {
            "ticker": ativo.ticker, "tipo": tipo,
            "documents": [_serializar_documento(doc, ativo.ticker, tipo) for doc in documentos],
            "documents_total": session.query(func.count(DocumentosQualitativos.id)).filter_by(ativo_id=ativo.id).scalar() or 0,
            "pending_documents": session.query(func.count(DocumentosQualitativos.id)).filter(
                DocumentosQualitativos.ativo_id == ativo.id,
                DocumentosQualitativos.status_processamento == ("PENDENTE" if tipo == "FII" else "PENDENTE_ACAO"),
            ).scalar() or 0,
            "financial": dados,
            "manual_classification": classificacao_manual,
            "last_scan": {
                "type": ultima_operacao.tipo, "status": ultima_operacao.status,
                "at": ultima_operacao.iniciado_em.isoformat() if ultima_operacao and ultima_operacao.iniciado_em else None,
                "finished_at": ultima_operacao.concluido_em.isoformat() if ultima_operacao and ultima_operacao.concluido_em else None,
            } if ultima_operacao else None,
        }
    finally:
        session.close()


def _origem_documento(documento) -> tuple[str, str]:
    """Retorna uma origem auditável sem confundir a URL da fonte com o Drive."""
    url_drive = str(getattr(documento, "url_pdf", None) or "").strip()
    if "drive.google.com" in url_drive:
        return "Google Drive", url_drive
    if url_drive:
        return "Fonte oficial registrada", url_drive
    id_b3 = str(getattr(documento, "id_b3", None) or "").strip()
    if id_b3:
        # A B3 pode exigir cookies para servir o PDF. O painel identifica este
        # botão como origem, e não promete que seja um link público do arquivo.
        return "B3/FNET", "https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?" + urlencode({"id": id_b3})
    return "Origem não registrada", ""


def _serializar_documento(documento, ticker: str, tipo_ativo: str | None = None) -> dict:
    """Campos seguros e úteis para auditoria documental no painel."""
    origem, origem_url = _origem_documento(documento)
    return {
        "id": documento.id,
        "ticker": ticker,
        "tipo": documento.tipo_documento or "Não classificado",
        "data_publicacao": documento.data_publicacao.isoformat() if documento.data_publicacao else None,
        "status": documento.status_processamento or "SALVO",
        "atualizado_em": documento.data_atualizacao.isoformat() if documento.data_atualizacao else None,
        "assunto": documento.assunto or "",
        "url": documento.url_pdf or "",
        "origin": origem,
        "origin_url": origem_url,
        "id_origem": str(documento.id_b3 or "") if getattr(documento, "id_b3", None) else "",
        "asset_type": tipo_ativo or getattr(getattr(documento, "ativo", None), "tipo", ""),
        "tem_resumo": bool(documento.resumo_ia),
    }


def _documentos_para_painel(ticker: str | None = None, status: str | None = None, limite: int = 100) -> list[dict]:
    """Consulta documental no Neon. Não baixa PDFs nem chama fontes externas."""
    from atualizador_documentos import SessionDB
    from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
    from sqlalchemy import func

    session = SessionDB()
    try:
        consulta = session.query(DocumentosQualitativos, Ativo.ticker, Ativo.tipo).join(Ativo, Ativo.id == DocumentosQualitativos.ativo_id)
        if ticker:
            consulta = consulta.filter(func.upper(Ativo.ticker) == ticker.upper())
        if status:
            consulta = consulta.filter(func.upper(DocumentosQualitativos.status_processamento) == status.upper())
        linhas = consulta.order_by(
            DocumentosQualitativos.data_publicacao.desc(),
            DocumentosQualitativos.id.desc(),
        ).limit(min(max(limite, 1), 200)).all()
        return [_serializar_documento(documento, ativo_ticker, getattr(ativo_tipo, "value", ativo_tipo)) for documento, ativo_ticker, ativo_tipo in linhas]
    finally:
        session.close()


def _cobertura_documental() -> dict:
    """Resumo factual da base documental gravada no Neon."""
    from atualizador_documentos import SessionDB
    from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
    from sqlalchemy import func

    session = SessionDB()
    try:
        por_ativo = session.query(
            Ativo.id, func.count(DocumentosQualitativos.id).label("total")
        ).outerjoin(
            DocumentosQualitativos, DocumentosQualitativos.ativo_id == Ativo.id
        ).group_by(Ativo.id).all()
        por_status = dict(session.query(
            DocumentosQualitativos.status_processamento,
            func.count(DocumentosQualitativos.id),
        ).group_by(DocumentosQualitativos.status_processamento).all())
        ultimo = session.query(func.max(DocumentosQualitativos.data_atualizacao)).scalar()
        ativos_total = len(por_ativo)
        com_documento = sum(1 for item in por_ativo if int(item.total or 0) > 0)
        return {
            "assets_total": ativos_total,
            "assets_with_documents": com_documento,
            "assets_without_documents": max(0, ativos_total - com_documento),
            "documents_total": sum(int(valor or 0) for valor in por_status.values()),
            "saved_drive": int(por_status.get("SALVO_DRIVE", 0) or 0),
            "pending": int(por_status.get("PENDENTE", 0) or 0) + int(por_status.get("PENDENTE_ACAO", 0) or 0),
            "review": int(por_status.get("AGUARDANDO_REVISAO", 0) or 0),
            "last_document_event": ultimo.isoformat() if ultimo else None,
        }
    finally:
        session.close()


def _ultimas_execucoes_github(limite: int = 8) -> tuple[list[dict], str | None]:
    """Consulta o histórico de workflows sem disparar operação alguma."""
    import requests

    token = (os.environ.get("GITHUB_ACTIONS_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    repo = (os.environ.get("GITHUB_REPOSITORY") or "WandesonMarcone/robo-financeiro").strip()
    if not token:
        return [], "Token do GitHub não configurado no Render."
    resposta = requests.get(
        f"https://api.github.com/repos/{repo}/actions/runs?per_page=30",
        headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"},
        timeout=12,
    )
    if resposta.status_code != 200:
        return [], f"GitHub não respondeu ao histórico (HTTP {resposta.status_code})."
    permitidos = {"Atualização cíclica de ativos", "Atualização isolada de ativo", "Robô Financeiro"}
    linhas = []
    for item in resposta.json().get("workflow_runs", []):
        if item.get("name") not in permitidos:
            continue
        linhas.append({
            "workflow": item.get("name"), "status": item.get("status"),
            "conclusion": item.get("conclusion"),
            "started_at": item.get("run_started_at") or item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "title": item.get("display_title") or item.get("head_commit", {}).get("message") or "Execução",
            "url": item.get("html_url"),
        })
        if len(linhas) >= limite:
            break
    return linhas, None


@admin_api.route("/api/admin/status", methods=["GET"])
@exige_admin
def status():
    recentes = list(_TASKS.values())[-8:]
    recentes.reverse()
    pendentes = sum(1 for item in _TASKS.values() if item["status"] == "em_andamento")
    try:
        auditoria = _historico_para_painel(limite=8)
        if auditoria["operations"]:
            recentes = [{
                "id": item["id"], "action": item["type"],
                "label": item["message"] or item["type"], "target": item["ticker"],
                "status": {"CONCLUIDA": "ok", "FALHOU": "falha"}.get(item["status"], "em_andamento"),
                "when": item["finished_at"] or item["started_at"] or "",
            } for item in auditoria["operations"]]
            pendentes = sum(1 for item in auditoria["operations"] if item["status"] == "EM_ANDAMENTO")
    except Exception:
        pass
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
    """Lista o cadastro real e sua cobertura documental, sem coletar dados."""
    busca = str(request.args.get("q") or "").strip()
    tipo = str(request.args.get("type") or "").strip().upper()
    try:
        ativos, totais = _ativos_para_painel(busca=busca or None, tipo=tipo or None)
    except Exception:
        return jsonify({"message": "Não foi possível consultar o cadastro de ativos agora."}), 503
    return jsonify({"assets": ativos, "totals": totais})


@admin_api.route("/api/admin/users", methods=["GET"])
@exige_admin
def listar_usuarios():
    try:
        return jsonify({"users": _usuarios_para_painel()})
    except Exception:
        return jsonify({"message": "Não foi possível consultar usuários, favoritos e preferências agora."}), 503


@admin_api.route("/api/admin/assets/<ticker>", methods=["GET"])
@exige_admin
def detalhe_ativo(ticker: str):
    ticker = str(ticker or "").strip().upper()
    if not _TICKER.fullmatch(ticker):
        return jsonify({"message": "Ticker inválido."}), 400
    try:
        detalhe = _detalhe_ativo_para_painel(ticker)
    except Exception:
        return jsonify({"message": "Não foi possível carregar a ficha do ativo agora."}), 503
    if detalhe is None:
        return jsonify({"message": "Ativo não encontrado no cadastro-base."}), 404
    return jsonify(detalhe)


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


@admin_api.route("/api/admin/document-types", methods=["GET"])
@exige_admin
def tipos_documento():
    """Catálogo idêntico ao usado nos botões de revisão do Telegram."""
    tipo_ativo = str(request.args.get("asset_type") or "FII").strip().upper()
    if tipo_ativo not in {"FII", "ACAO"}:
        return jsonify({"message": "Tipo de ativo inválido."}), 400
    from config import TIPOS_DOC_ACAO, TIPOS_DOC_FII
    catalogo = TIPOS_DOC_ACAO if tipo_ativo == "ACAO" else TIPOS_DOC_FII
    tipos = list(dict.fromkeys(nome for nome in catalogo.values() if nome))
    return jsonify({"asset_type": tipo_ativo, "types": tipos})


@admin_api.route("/api/admin/operations", methods=["GET"])
@exige_admin
def operacoes():
    try:
        cobertura = _cobertura_documental()
    except Exception:
        return jsonify({"message": "Não foi possível medir a cobertura documental no Neon."}), 503
    execucoes, erro_github = _ultimas_execucoes_github()
    return jsonify({"coverage": cobertura, "workflow_runs": execucoes, "github_error": erro_github})


@admin_api.route("/api/admin/history", methods=["GET"])
@exige_admin
def historico():
    """Auditoria persistente de tarefas, varreduras, erros e notificações."""
    try:
        return jsonify(_historico_para_painel(limite=40))
    except Exception:
        return jsonify({"message": "O histórico ainda não foi inicializado no Neon."}), 503


@admin_api.route("/api/admin/alerts", methods=["GET"])
@exige_admin
def alertas():
    try:
        return jsonify({"alerts": _alertas_para_painel()})
    except Exception:
        return jsonify({"message": "Não foi possível consultar os eventos de alerta no Neon."}), 503


@admin_api.route("/api/admin/market", methods=["GET"])
@exige_admin
def mercado():
    """Séries oficiais e histórico curto para a Central, sem acionar coleta."""
    try:
        from services.painel_mercado import resumo_mercado
        return jsonify(resumo_mercado())
    except Exception:
        return jsonify({"message": "Não foi possível consultar as séries de mercado no Neon."}), 503


@admin_api.route("/api/admin/instruments", methods=["GET"])
@exige_admin
def instrumentos_internacionais():
    """ETFs e BDRs têm cadastro e métricas próprios, sem se passar por ações."""
    from atualizador_documentos import SessionDB
    sessao = SessionDB()
    try:
        tipo = str(request.args.get("type") or "").upper().strip()
        if tipo and tipo not in {"ETF", "BDR"}:
            return jsonify({"message": "Tipo inválido."}), 400
        linhas = sessao.execute(text("""
          WITH ultima AS (
            SELECT DISTINCT ON (instrumento_id) instrumento_id, referencia_em, fechamento,
              variacao_percentual, volume, fonte, qualidade_fonte
            FROM observacoes_instrumentos_internacionais
            ORDER BY instrumento_id, referencia_em DESC
          )
          SELECT i.ticker,i.tipo,i.nome,i.simbolo_exterior,i.indice_referencia,i.gestora,i.moeda_origem,
            i.atualizado_em,u.referencia_em,u.fechamento,u.variacao_percentual,u.volume,u.fonte,u.qualidade_fonte
          FROM instrumentos_internacionais i LEFT JOIN ultima u ON u.instrumento_id=i.id
          WHERE i.ativo=TRUE AND (:tipo='' OR i.tipo=:tipo)
          ORDER BY i.tipo,i.ticker
        """), {"tipo": tipo}).mappings().all()
        return jsonify({"instruments": [{**dict(l), "referencia_em": l["referencia_em"].isoformat() if l["referencia_em"] else None,
                          "atualizado_em": l["atualizado_em"].isoformat() if l["atualizado_em"] else None} for l in linhas]})
    except Exception:
        return jsonify({"message": "A estrutura de ETFs e BDRs ainda não está disponível no Neon."}), 503
    finally:
        sessao.close()


@admin_api.route("/api/admin/instruments/<ticker>", methods=["GET"])
@exige_admin
def detalhe_instrumento_internacional(ticker):
    from atualizador_documentos import SessionDB
    sessao = SessionDB()
    try:
        item = sessao.execute(text("SELECT * FROM instrumentos_internacionais WHERE ticker=:ticker"), {"ticker": ticker.upper()}).mappings().first()
        if not item:
            return jsonify({"message": "Instrumento não encontrado."}), 404
        metricas = sessao.execute(text("""
          SELECT chave, valor_numerico, valor_texto, unidade, fonte, qualidade_fonte, referencia_em, bloqueado
          FROM metricas_instrumentos_internacionais WHERE instrumento_id=:id ORDER BY chave
        """), {"id": item["id"]}).mappings().all()
        return jsonify({"instrument": {**dict(item), "criado_em": item["criado_em"].isoformat(), "atualizado_em": item["atualizado_em"].isoformat()},
                        "metrics": [{**dict(m), "referencia_em": m["referencia_em"].isoformat() if m["referencia_em"] else None} for m in metricas]})
    except Exception:
        return jsonify({"message": "Não foi possível consultar a ficha do instrumento."}), 503
    finally:
        sessao.close()


@admin_api.route("/api/admin/sources", methods=["GET"])
@exige_admin
def fontes():
    return jsonify(_fontes_para_painel())


@admin_api.route("/api/admin/commands", methods=["POST"])
@exige_admin
def executar_comando():
    dados = request.get_json(silent=True) or {}
    action = str(dados.get("action") or "").strip()
    ticker = str(dados.get("ticker") or "").strip().upper()
    periodo = str(dados.get("period") or "").strip()
    documento_id = dados.get("document_id")
    tipo_instrumento = str(dados.get("instrument_type") or "").strip().upper()
    simbolo_exterior = str(dados.get("external_symbol") or "").strip().upper() or None
    if ticker and not _TICKER.fullmatch(ticker):
        return jsonify({"message": "Ticker inválido."}), 400

    if action == "status":
        return jsonify({"message": "Status atualizado."})
    if action == "registrar_instrumento":
        if not ticker or tipo_instrumento not in {"ETF", "BDR"}:
            return jsonify({"message": "Informe ticker e escolha ETF ou BDR."}), 400
        try:
            from services.coletor_etfs_bdrs import registrar_instrumento
            item = registrar_instrumento(ticker, tipo_instrumento, simbolo_exterior)
            return jsonify({"message": f"{item['ticker']} cadastrado como {item['tipo']}. Use Atualizar para buscar o primeiro histórico."})
        except Exception:
            return jsonify({"message": "Não foi possível cadastrar: confirme que a migração 0016 foi aplicada no Neon."}), 503
    if action == "atualizar_instrumento":
        if not ticker:
            return jsonify({"message": "Informe o ticker do ETF ou BDR."}), 400
        from services.coletor_etfs_bdrs import coletar_instrumento
        tarefa = _registrar_tarefa(action, f"Atualização de ETF/BDR: {ticker}", ticker)
        _executar_em_background(tarefa, coletar_instrumento, ticker, tipo_instrumento or None, simbolo_exterior)
        return jsonify({"message": f"Atualização de {ticker} iniciada; origem e qualidade aparecerão na ficha.", "task_id": tarefa}), 202
    if action == "atualizar_instrumentos":
        from services.coletor_etfs_bdrs import coletar_instrumentos_ativos
        tarefa = _registrar_tarefa(action, "Atualização dos ETFs e BDRs cadastrados")
        _executar_em_background(tarefa, coletar_instrumentos_ativos, 30)
        return jsonify({"message": "Atualização de até 30 ETFs/BDRs cadastrados iniciada.", "task_id": tarefa}), 202
    if action == "salvar_classificacao_manual":
        if not ticker:
            return jsonify({"message": "Informe o ticker do ativo."}), 400
        valores = {
            nome: " ".join(str(dados.get(nome) or "").split()).strip() or None
            for nome in ("classe", "segmento", "estrategia")
        }
        if not any(valores.values()):
            return jsonify({"message": "Informe ao menos uma classificação manual."}), 400
        if any(valor and len(valor) > 160 for valor in valores.values()):
            return jsonify({"message": "Cada campo de classificação aceita até 160 caracteres."}), 400
        from sqlalchemy import text
        from atualizador_documentos import SessionDB
        from pipeline_dados.banco_dados import Ativo
        session = SessionDB()
        try:
            ativo = session.query(Ativo).filter(func.upper(Ativo.ticker) == ticker).first()
            if not ativo:
                return jsonify({"message": "Ativo não encontrado no cadastro-base."}), 404
            session.execute(text(
                "INSERT INTO sobreposicoes_manuais_ativos "
                "(ativo_id, classe, segmento, estrategia, bloqueado, origem, atualizado_em) "
                "VALUES (:ativo_id, :classe, :segmento, :estrategia, TRUE, 'PAINEL_ADMIN', NOW()) "
                "ON CONFLICT (ativo_id) DO UPDATE SET classe = EXCLUDED.classe, "
                "segmento = EXCLUDED.segmento, estrategia = EXCLUDED.estrategia, "
                "bloqueado = TRUE, origem = 'PAINEL_ADMIN', atualizado_em = NOW()"
            ), {"ativo_id": ativo.id, **valores})
            session.commit()
            return jsonify({"message": f"Classificação manual de {ticker} salva e bloqueada contra sobrescrita automática."})
        except Exception:
            session.rollback()
            return jsonify({"message": "A estrutura de classificação manual ainda não está disponível no Neon."}), 503
        finally:
            session.close()
    if action == "salvar_indicador_manual":
        chave = re.sub(r"[^a-z0-9_]", "", str(dados.get("chave") or "").lower().replace(" ", "_"))
        valor = " ".join(str(dados.get("valor") or "").split()).strip()
        fonte = " ".join(str(dados.get("fonte") or "").split()).strip()
        referencia = str(dados.get("data_referencia") or "").strip() or None
        if not ticker or not chave or not valor or not fonte:
            return jsonify({"message": "Ticker, indicador, valor e fonte são obrigatórios."}), 400
        from sqlalchemy import text, func
        from atualizador_documentos import SessionDB
        from pipeline_dados.banco_dados import Ativo
        session = SessionDB()
        try:
            ativo = session.query(Ativo).filter(func.upper(Ativo.ticker) == ticker).first()
            if not ativo:
                return jsonify({"message": "Ativo não encontrado no cadastro-base."}), 404
            session.execute(text("""
                INSERT INTO indicadores_manuais_ativos (ativo_id, chave, valor_texto, fonte, data_referencia, bloqueado, atualizado_em)
                VALUES (:ativo_id, :chave, :valor, :fonte, CAST(:referencia AS DATE), TRUE, NOW())
                ON CONFLICT (ativo_id, chave) DO UPDATE SET valor_texto=EXCLUDED.valor_texto, fonte=EXCLUDED.fonte,
                data_referencia=EXCLUDED.data_referencia, bloqueado=TRUE, atualizado_em=NOW()
            """), {"ativo_id": ativo.id, "chave": chave, "valor": valor, "fonte": fonte, "referencia": referencia})
            session.commit()
            return jsonify({"message": f"Indicador manual '{chave}' salvo e bloqueado."})
        except Exception:
            session.rollback()
            return jsonify({"message": "Não foi possível salvar o indicador manual."}), 502
        finally:
            session.close()
    if action == "atualizar_ativo":
        if not ticker:
            return jsonify({"message": "Informe o ticker do ativo."}), 400
        from services.github_actions import disparar_atualizacao_isolada
        from services.historico_operacional import iniciar_evento, registrar_progresso
        evento_id = iniciar_evento(action, origem="PAINEL_ADMIN", ticker=ticker,
                                   mensagem=f"Atualização isolada de {ticker}")
        registrar_progresso(evento_id, "Solicitando workflow de atualização isolada ao GitHub Actions.")
        ok, mensagem = disparar_atualizacao_isolada(ticker)
        if not ok:
            from services.historico_operacional import concluir_evento
            concluir_evento(evento_id, sucesso=False, mensagem=mensagem,
                            erro="GITHUB_ACTIONS_DISPATCH_FAILED")
            return jsonify({"message": mensagem}), 502
        registrar_progresso(evento_id, "Disparo aceito pelo GitHub. Aguardando o início do workflow para confirmar o resultado real.")
        threading.Thread(target=_monitorar_atualizacao_isolada, args=(evento_id, ticker, datetime.now().timestamp()), daemon=True).start()
        return jsonify({
            "message": "Atualização enviada ao GitHub Actions. O histórico mostrará o andamento e só marcará concluída após o workflow terminar.",
            "task_id": evento_id,
        }), 202
    if action == "forcar_documentos":
        if not ticker:
            return jsonify({"message": "Informe o ticker do ativo."}), 400
        tarefa = _registrar_tarefa(action, f"Busca documental de {ticker}", ticker)
        _executar_em_background(tarefa, _coletar_documentos_isolados, ticker, periodo)
        return jsonify({"message": f"Busca documental de {ticker} iniciada.", "task_id": tarefa}), 202
    if action == "forcar_varredura":
        try:
            dias = int(periodo or 60)
            if not 1 <= dias <= 365:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"message": "Informe um período entre 1 e 365 dias para a varredura FNET."}), 400
        tarefa = _registrar_tarefa(action, f"Varredura de documentos FNET — últimos {dias} dias")
        _executar_em_background(tarefa, _varrer_fnet_pelo_painel, dias)
        return jsonify({"message": f"Varredura FNET dos últimos {dias} dias iniciada.", "task_id": tarefa}), 202
    if action == "processar_pendentes_acao":
        if not ticker:
            return jsonify({"message": "Informe o ticker da ação para processar somente seus pendentes."}), 400
        from services import orquestrador
        tarefa = _registrar_tarefa(action, f"Classificação de pendentes de {ticker}", ticker)
        _executar_em_background(tarefa, orquestrador.processar_ia_acoes, ticker)
        return jsonify({"message": f"Classificação dos documentos PENDENTE_ACAO de {ticker} iniciada.", "task_id": tarefa}), 202
    if action == "processar_pendentes_fii":
        if not ticker:
            return jsonify({"message": "Informe o ticker do FII para processar somente seus pendentes."}), 400
        from atualizador_documentos import rotina_processar_pendentes
        tarefa = _registrar_tarefa(action, f"Classificação de pendentes FII de {ticker}", ticker)
        _executar_em_background(tarefa, rotina_processar_pendentes, None, ticker)
        return jsonify({"message": f"Classificação dos documentos PENDENTE de {ticker} iniciada.", "task_id": tarefa}), 202
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
    if action == "corrigir_tipo_documento":
        try:
            documento_id = int(documento_id)
            if documento_id <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"message": "Documento inválido."}), 400
        novo_tipo = " ".join(str(dados.get("tipo_documento") or "").split()).strip()
        if not 3 <= len(novo_tipo) <= 120:
            return jsonify({"message": "Escolha um tipo de documento válido."}), 400
        from atualizador_documentos import SessionDB, confirmar_classificacao_manual
        from pipeline_dados.banco_dados import DocumentosQualitativos
        session = SessionDB()
        try:
            documento = session.query(DocumentosQualitativos).filter_by(id=documento_id).first()
            if not documento:
                return jsonify({"message": "Documento não encontrado."}), 404
            from config import TIPOS_DOC_ACAO, TIPOS_DOC_FII
            tipo_ativo = str(getattr(documento.ativo.tipo, "value", documento.ativo.tipo)).upper()
            tipos_permitidos = set((TIPOS_DOC_ACAO if tipo_ativo == "ACAO" else TIPOS_DOC_FII).values())
            if novo_tipo not in tipos_permitidos:
                return jsonify({"message": "Tipo não pertence ao catálogo oficial deste ativo."}), 400
            anterior = documento.tipo_documento
            link = confirmar_classificacao_manual(documento, novo_tipo)
            if not link:
                raise RuntimeError("arquivo_nao_organizado_no_drive")
            session.commit()
            mensagem = f"Tipo alterado de '{anterior}' para '{novo_tipo}' e arquivo organizado no Drive."
            return jsonify({"message": mensagem, "drive_renamed": True})
        except Exception as exc:
            session.rollback()
            return jsonify({"message": "Não foi possível organizar o PDF no Drive; o tipo não foi alterado. Tente 'Salvar no Drive' ou consulte a origem do documento."}), 502
        finally:
            session.close()

    from services import orquestrador
    acoes = {
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
