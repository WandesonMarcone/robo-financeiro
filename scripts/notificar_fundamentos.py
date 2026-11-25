"""Resumo real do lote, inclusive quando há falha parcial."""
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

def mensagem(resultado):
    itens = resultado.get("processados", [])
    linhas = ["📊 Fundamentos — rodada concluída",
              f"Universo: {resultado.get('universo', len(itens))} | Processados: {len(itens)}"]
    progresso = resultado.get("progresso") or {}
    if progresso:
        linhas.append(
            "Progresso geral: "
            f"{progresso.get('concluidos', 0)}/{progresso.get('total', resultado.get('universo', 0))} com dados "
            f"(✅ {progresso.get('ok', 0)} | 🟡 {progresso.get('parciais', 0)} | "
            f"❌ {progresso.get('falhas', 0)} | ⏳ {progresso.get('pendentes', 0)} pendentes)"
        )
    for item in itens:
        d = item.get("detalhe", {})
        estado = item["estado"]
        simbolo = {"OK": "✅", "PARCIAL": "🟡", "FALHA": "❌"}.get(estado, "•")
        linhas.append(f"{simbolo} {item['ticker']} — {estado}: {d.get('fundamentos', 0)} fundamentos, {d.get('indicadores', 0)} indicadores, {d.get('proventos', 0)} proventos")
        if d.get("motivo"):
            linhas.append("  " + str(d["motivo"])[:150])
    falhas = resultado.get("falhas", [])
    linhas.append(f"Falhas desta rodada: {len(falhas)}")
    if falhas:
        linhas.append("Reprocessamento automático programado para: " + ", ".join(falhas[:10]))
    if not itens:
        linhas.append("Nenhum ativo processado nesta rodada.")
    run = os.environ.get("GITHUB_RUN_ID")
    if run:
        linhas.append(f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{run}")
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
