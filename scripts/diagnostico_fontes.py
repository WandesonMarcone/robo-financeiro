"""Diagnóstico isolado e comparável de cobertura: Yahoo Finance x Fundamentus.

Não importa módulos do robô nem acessa credenciais, planilhas, Neon, Drive, Render
ou Telegram. Fundamentus é consultado uma vez por execução porque publica uma tabela
consolidada; Yahoo é consultado ativo a ativo.
"""
import argparse
import json
import math
import re
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


URL_FUNDAMENTUS = "https://fundamentus.com.br/resultado.php"
URL_YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.SA?interval=1d&range=5d"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RoboFinanceiroDiagnostico/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
}


class TabelasHTML(HTMLParser):
    """Extrai células de tabelas sem depender de pandas ou dos módulos do robô."""

    def __init__(self):
        super().__init__()
        self.tables = []
        self._rows = []
        self._row = None
        self._cell = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._rows = []
        elif self._depth == 1 and tag == "tr":
            self._row = []
        elif self._depth == 1 and tag in ("th", "td") and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if self._depth == 1 and tag in ("th", "td") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif self._depth == 1 and tag == "tr" and self._row is not None:
            if any(self._row):
                self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._depth:
            if self._depth == 1 and self._rows:
                self.tables.append(self._rows)
            self._depth -= 1


def _ticker_list(tickers, limite):
    ativos = list(dict.fromkeys(t.strip().upper() for t in tickers if t.strip()))
    if not 1 <= limite <= 100:
        raise ValueError("limite_invalido")
    if not ativos or any(not re.fullmatch(r"[A-Z]{4}[0-9]{1,2}", ticker) for ticker in ativos):
        raise ValueError("ticker_invalido")
    return ativos[:limite]


def _http_error(exc):
    item = {"tipo": type(exc).__name__}
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        item["http_status"] = code
    return item


def _request_text(url, timeout=20):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return {
            "texto": response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace"),
            "http_status": response.getcode(),
        }


def _fundamentus_rows(html):
    parser = TabelasHTML()
    parser.feed(html)
    for table in parser.tables:
        if not table:
            continue
        headers = [str(item).strip() for item in table[0]]
        normalized = [header.casefold() for header in headers]
        if "papel" not in normalized:
            continue
        index = normalized.index("papel")
        rows = {}
        for line in table[1:]:
            if len(line) <= index:
                continue
            ticker = str(line[index]).strip().upper()
            if re.fullmatch(r"[A-Z]{4}[0-9]{1,2}", ticker):
                rows.setdefault(ticker, dict(zip(headers, line)))
        if rows:
            return headers, rows
    raise ValueError("tabela_fundamentus_nao_encontrada")


def coletar_fundamentus(request_text=_request_text, clock=time.monotonic):
    started = clock()
    try:
        response = request_text(URL_FUNDAMENTUS)
        headers, rows = _fundamentus_rows(response["texto"])
        return {
            "status": "valido",
            "segundos": round(clock() - started, 3),
            "http_status": response.get("http_status"),
            "colunas": headers,
            "linhas": len(rows),
            "dados": rows,
        }
    except Exception as exc:
        result = {
            "status": "falha",
            "segundos": round(clock() - started, 3),
            "dados": {},
            "colunas": [],
            "linhas": 0,
        }
        result.update(_http_error(exc))
        return result


def coletar_yahoo(ticker, request_text=_request_text, clock=time.monotonic):
    started = clock()
    try:
        response = request_text(URL_YAHOO.format(ticker=ticker))
        payload = json.loads(response["texto"])
        result = payload["chart"]["result"][0]["meta"]
        price = result.get("regularMarketPrice")
        stamp = result.get("regularMarketTime")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0 or not stamp:
            raise ValueError("cotacao_invalida")
        return {
            "status": "valido",
            "segundos": round(clock() - started, 3),
            "http_status": response.get("http_status"),
            "preco": price,
            "horario_fonte": stamp,
        }
    except Exception as exc:
        result = {"status": "falha", "segundos": round(clock() - started, 3)}
        result.update(_http_error(exc))
        return result


def _p95(numbers):
    if not numbers:
        return None
    values = sorted(numbers)
    return values[max(0, math.ceil(len(values) * 0.95) - 1)]


def diagnosticar(tickers, limite, pausa, orcamento=600, coletar_fund=coletar_fundamentus, coletar_yf=coletar_yahoo, clock=time.monotonic, sleep=time.sleep):
    if not 0 <= pausa <= 30 or not 25 <= orcamento <= 1800:
        raise ValueError("limites_invalidos")
    ativos = _ticker_list(tickers, limite)
    inicio = clock()
    fundamentus = coletar_fund()
    fund_rows = fundamentus.pop("dados", {})
    resultados = []

    for ticker in ativos:
        if clock() - inicio + 20 + pausa > orcamento:
            break
        yahoo = coletar_yf(ticker)
        presente_fund = ticker in fund_rows
        if yahoo["status"] == "valido" and presente_fund:
            cobertura = "ambas"
        elif yahoo["status"] == "valido":
            cobertura = "somente_yahoo"
        elif presente_fund:
            cobertura = "somente_fundamentus"
        else:
            cobertura = "nenhuma"
        resultados.append({
            "ticker": ticker,
            "cobertura": cobertura,
            "yahoo": yahoo,
            "fundamentus": {"presente_na_tabela": presente_fund},
        })
        sleep(pausa)

    tempos_yahoo = [row["yahoo"]["segundos"] for row in resultados if row["yahoo"]["status"] == "valido"]
    p95_yahoo = _p95(tempos_yahoo)
    intervalo = round(max(2.0, (p95_yahoo or 0) * 2), 2)
    tempo_fund = fundamentus.get("segundos") if fundamentus["status"] == "valido" else None
    limite_estimado = max(1, min(100, math.floor((orcamento - (tempo_fund or 0) - 30) / (intervalo + (p95_yahoo or 0)))))

    return {
        "tentados": len(resultados),
        "duracao_segundos": round(clock() - inicio, 3),
        "fundamentus": fundamentus,
        "yahoo": {
            "validos": sum(row["yahoo"]["status"] == "valido" for row in resultados),
            "falhas": sum(row["yahoo"]["status"] == "falha" for row in resultados),
            "p95_segundos": p95_yahoo,
        },
        "cobertura": {
            "ambas": sum(row["cobertura"] == "ambas" for row in resultados),
            "somente_yahoo": sum(row["cobertura"] == "somente_yahoo" for row in resultados),
            "somente_fundamentus": sum(row["cobertura"] == "somente_fundamentus" for row in resultados),
            "nenhuma": sum(row["cobertura"] == "nenhuma" for row in resultados),
        },
        "parametro_recomendado": {
            "fundamentus_por_execucao": 1,
            "intervalo_yahoo_segundos": intervalo,
            "limite_yahoo_estimado_no_orcamento": limite_estimado,
            "observacao": "Referência do teste isolado; não representa a capacidade do robô completo.",
        },
        "resultados": resultados,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", required=True)
    parser.add_argument("--limite", type=int, default=10)
    parser.add_argument("--orcamento", type=int, default=600)
    parser.add_argument("--pausa", type=float, default=2)
    parser.add_argument("--saida", default="diagnostico-fontes-resultados.json")
    args = parser.parse_args()
    report = diagnosticar(args.tickers.split(","), args.limite, args.pausa, args.orcamento)
    Path(args.saida).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "resultados"}, ensure_ascii=False))
    return 0 if report["tentados"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
