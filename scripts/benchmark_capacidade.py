"""Benchmark de cotação Yahoo, isolado dos imports e efeitos do robô."""
import argparse
import json
import math
import re
import time
import urllib.request
from pathlib import Path


def cotacao(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.SA?interval=1d&range=5d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.load(response)
    result = data["chart"]["result"][0]
    price = result["meta"].get("regularMarketPrice")
    stamp = result["meta"].get("regularMarketTime")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0 or not stamp:
        raise ValueError("cotacao_invalida")
    return {"preco": price, "horario_fonte": stamp}


def executar(tickers, limite, orçamento, pausa, coletar=cotacao, clock=time.monotonic, sleep=time.sleep, checkpoint=lambda rows: None):
    if not 1 <= limite <= 100 or not 25 <= orçamento <= 1800 or not 0 <= pausa <= 30:
        raise ValueError("limites_invalidos")
    ativos = list(dict.fromkeys(t.strip().upper() for t in tickers if t.strip()))
    if any(not re.fullmatch(r"[A-Z]{4}[0-9]{1,2}", t) for t in ativos):
        raise ValueError("ticker_invalido")
    inicio = clock()
    rows = []
    for ticker in ativos[:limite]:
        if clock() - inicio + 20 + pausa > orçamento:
            break
        start = clock()
        try:
            dados = coletar(ticker)
            row = {"ticker": ticker, "status": "valido", "dados": dados}
        except Exception as exc:
            row = {"ticker": ticker, "status": "falha", "erro": type(exc).__name__}
        row["segundos"] = round(clock() - start, 3)
        rows.append(row)
        checkpoint(rows)
        sleep(pausa)
    return {"solicitados": len(ativos), "tentados": len(rows), "validos": sum(r["status"] == "valido" for r in rows), "duracao_segundos": round(clock() - inicio, 3), "resultados": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", required=True)
    parser.add_argument("--limite", type=int, default=10)
    parser.add_argument("--orcamento", type=int, default=600)
    parser.add_argument("--pausa", type=float, default=2)
    args = parser.parse_args()
    output = Path("benchmark-resultados.json")
    def checkpoint(rows):
        output.write_text(json.dumps({"parcial": True, "resultados": rows}, indent=2), encoding="utf-8")
    report = executar(args.tickers.split(","), args.limite, args.orcamento, args.pausa, checkpoint=checkpoint)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "resultados"}))
    return 0 if report["tentados"] and report["validos"] == report["tentados"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
