"""Fila independente, persistente e limitada de fundamentos de ações."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256

import requests
from sqlalchemy import text

from services.fundamentos_valuation import coletar_fundamentos_valuation

DDL = """
CREATE TABLE IF NOT EXISTS fila_fundamentos_acoes (
    ticker VARCHAR(20) PRIMARY KEY,
    ultima_tentativa TIMESTAMPTZ,
    ultimo_sucesso TIMESTAMPTZ,
    proxima_tentativa TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    estado VARCHAR(30) NOT NULL DEFAULT 'PENDENTE',
    tentativas INTEGER NOT NULL DEFAULT 0,
    detalhe JSONB NOT NULL DEFAULT '{}'::jsonb
)
"""

def selecionar_pendentes(universo, estados, agora, limite):
    """Não deixa um ativo com erro impedir a entrada dos demais."""
    candidatos = []
    for ticker in sorted(set(universo)):
        estado = estados.get(ticker, {})
        proxima = estado.get("proxima_tentativa")
        if proxima and proxima > agora:
            continue
        tentativa = estado.get("ultima_tentativa")
        # Itens que deram erro devem voltar antes dos itens inéditos: quando a
        # sincronização oficial encontra o CNPJ que faltava, eles são a forma
        # mais rápida de confirmar que a correção realmente funcionou.
        prioridade = 0 if tentativa is None else 1 if estado.get("estado") == "FALHA" else 2
        candidatos.append((prioridade, tentativa or agora, ticker))
    return [item[2] for item in sorted(candidatos)[:limite]]


def resumo_progresso(universo, estados):
    """Resumo estável para Telegram; não confunde o lote com o universo."""
    universo = set(universo)
    contagens = {"OK": 0, "PARCIAL": 0, "FALHA": 0, "EM_COLETA": 0}
    for ticker in universo:
        estado = str((estados.get(ticker) or {}).get("estado") or "PENDENTE")
        if estado in contagens:
            contagens[estado] += 1
    concluidos = contagens["OK"] + contagens["PARCIAL"]
    return {
        "total": len(universo),
        "concluidos": concluidos,
        "ok": contagens["OK"],
        "parciais": contagens["PARCIAL"],
        "falhas": contagens["FALHA"],
        "em_coleta": contagens["EM_COLETA"],
        "pendentes": max(0, len(universo) - sum(contagens.values())),
    }

class CacheCVM:
    """Reutiliza cada ZIP oficial no lote, sem guardar tudo em RAM."""
    def __init__(self, pasta):
        self.pasta = Path(pasta)

    def __call__(self, url, timeout=90):
        arquivo = self.pasta / sha256(url.encode()).hexdigest()
        if arquivo.exists():
            resposta = requests.Response()
            resposta.status_code = 200
            resposta._content = arquivo.read_bytes()
            return resposta
        resposta = requests.get(url, timeout=timeout)
        if resposta.status_code == 200:
            arquivo.write_bytes(resposta.content)
        return resposta

def executar_fila(limite=10, prazo_segundos=900, session_factory=None, planilha=None,
                  coletar=coletar_fundamentos_valuation):
    if session_factory is None:
        from atualizador_documentos import SessionDB
        session_factory = SessionDB
    if planilha is None:
        from services.planilha_fundamentos_valuation import _planilha_padrao
        planilha = _planilha_padrao()
    limite = max(1, min(10, int(limite)))
    inicio = time.monotonic()
    universo = {str(v).strip().upper() for v in planilha.worksheet("BD_Acoes").col_values(1)[1:]
                if re.fullmatch(r"[A-Z0-9]{4,10}", str(v).strip().upper())}
    with session_factory() as sessao:
        sessao.execute(text(DDL))
        sessao.commit()
        universo.update(r[0].upper() for r in sessao.execute(text("""
            SELECT ticker FROM ativos_catalogo WHERE tipo::text='ACAO'
            UNION SELECT ticker FROM ativos WHERE tipo::text='ACAO'
        """)) if r[0] and re.fullmatch(r"[A-Z0-9]{4,10}", r[0].upper()))
        estados = {r["ticker"]: dict(r) for r in sessao.execute(text(
            "SELECT * FROM fila_fundamentos_acoes")).mappings()}
    agora = datetime.now(timezone.utc)
    lote = selecionar_pendentes(universo, estados, agora, limite)
    resultado = {"universo": len(universo), "selecionados": lote, "processados": [], "falhas": []}
    with TemporaryDirectory(prefix="fundamentos-cvm-") as pasta:
        cache = CacheCVM(pasta)
        from services.identidade_fundamentos_acoes import IdentidadeFCA
        identidade = IdentidadeFCA(http_get=cache)
        for ticker in lote:
            if time.monotonic() - inicio > prazo_segundos:
                break
            # Registrar antes da coleta também protege contra cancelamentos.
            with session_factory() as sessao:
                sessao.execute(text("""
                    INSERT INTO fila_fundamentos_acoes(ticker,ultima_tentativa,proxima_tentativa,estado,tentativas)
                    VALUES (:ticker,NOW(),NOW()+INTERVAL '1 day','EM_COLETA',1)
                    ON CONFLICT(ticker) DO UPDATE SET ultima_tentativa=NOW(),
                      proxima_tentativa=NOW()+INTERVAL '1 day',estado='EM_COLETA',
                      tentativas=fila_fundamentos_acoes.tentativas+1
                """), {"ticker": ticker})
                sessao.commit()
            try:
                retorno = coletar(ticker, anos=5, planilha=planilha, session_factory=session_factory, http_get=cache, identidade_resolver=identidade)
                ok = retorno.get("status") == "ok"
                parcial = bool(retorno.get("falhas")) or retorno.get("metodos_prontos", 0) < retorno.get("metodos_total", 10)
                estado = "PARCIAL" if ok and parcial else "OK" if ok else "FALHA"
                detalhe = retorno
            except Exception as exc:
                ok = False
                estado = "FALHA"
                detalhe = {"erro": type(exc).__name__, "motivo": str(exc)[:200] if isinstance(exc, ValueError) else "consultar logs"}
            # Falhas entram automaticamente em novo lote no mesmo dia; assim
            # uma indisponibilidade de fonte não deixa a ação parada até a
            # próxima semana. Sucesso parcial é revisitado em dois dias.
            dias = 7 if ok and not parcial else 2 if ok else 0.25
            if ok and detalhe.get("falhas"):
                dias = 2
            with session_factory() as sessao:
                sessao.execute(text("""
                    UPDATE fila_fundamentos_acoes SET estado=:estado,
                      ultimo_sucesso=CASE WHEN :ok THEN NOW() ELSE ultimo_sucesso END,
                      proxima_tentativa=NOW()+(:dias * INTERVAL '1 day'),
                      detalhe=CAST(:detalhe AS JSONB) WHERE ticker=:ticker
                """), {"ticker": ticker, "estado": estado, "ok": ok, "dias": dias,
                       "detalhe": json.dumps(detalhe, default=str, ensure_ascii=False)})
                sessao.commit()
            resumo = {"ticker": ticker, "estado": estado, "detalhe": detalhe}
            resultado["processados"].append(resumo)
            estados[ticker] = {
                "estado": estado,
                "proxima_tentativa": agora + timedelta(days=dias),
            }
            if not ok or detalhe.get("falhas"):
                resultado["falhas"].append(ticker)
            time.sleep(2)
    resultado["progresso"] = resumo_progresso(universo, estados)
    resultado["sucessos"] = sum(
        1 for item in resultado["processados"] if item["estado"] in {"OK", "PARCIAL"}
    )
    return resultado
