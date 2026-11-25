"""Resumo real do lote, inclusive quando há falha parcial."""
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

def mensagem(resultado):
    itens = resultado.get("processados", [])
    progresso = resultado.get("progresso") or {}
    grupos = {}
    for item in itens:
        d = item.get("detalhe", {})
        motivo = str(d.get("motivo") or "").lower()
        falhas = d.get("falhas") or []
        estado = item["estado"]
        if estado == "FALHA":
            if "cnpj" in motivo or any(f.get("fonte") == "FCA" for f in falhas if isinstance(f,dict)):
                rotulo = "❌ CNPJ não confirmado"
            elif any(f.get("erro") == "SEM_DEMONSTRACOES_PARA_CNPJ" for f in falhas if isinstance(f,dict)):
                rotulo = "❌ Sem balanços"
            else:
                rotulo = "❌ Falha"
        else:
            rotulo = "✅ Atualizados" if estado == "OK" else "🟡 Parciais"
        grupos.setdefault(rotulo,[]).append(item["ticker"])
    linhas = ["📊 Fundamentos"]
    for rotulo,tickers in grupos.items():
        linhas.append(rotulo + ": " + ", ".join(tickers))
    if not itens:
        linhas.append("Nenhum ativo pendente nesta rodada.")
    if progresso:
        linhas.append(f"Base: {progresso.get('concluidos',0)}/{progresso.get('total',resultado.get('universo',0))} com dados")
    return "\n".join(linhas)


def enviar(resultado):
    import config
    token = str(getattr(config, "TELEGRAM_BOT_TOKEN", "") or "").strip()
    destino = str(getattr(config, "TELEGRAM_ADMIN_ID", "") or "").strip()
    if not token or not destino:
        print("Telegram administrativo não configurado")
        return False
    dados = urllib.parse.urlencode({"chat_id": destino, "text": mensagem(resultado), "disable_web_page_preview": "true"}).encode()
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=dados, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resposta:
            return 200 <= resposta.status < 300
    except Exception as exc:
        print("Falha na notificação:", type(exc).__name__)
        return False

if __name__ == "__main__":
    if not enviar(json.loads(Path("resultado-fundamentos.json").read_text(encoding="utf-8"))):
        raise SystemExit(1)
