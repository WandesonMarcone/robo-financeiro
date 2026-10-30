import os
import json
import math
import gspread
import pandas as pd
import pytz
import telebot
from datetime import datetime
import config
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_SENTINELAS_AUSENCIA = frozenset(
    {"", "-", "--", "n/d", "nd", "n/a", "s/n", "none", "nan"}
)

def get_request_with_retry(url, headers):
    """Uma requisição blindada que tenta 3 vezes antes de desistir."""
    session = requests.Session()
    retry = Retry(
        total=3, 
        backoff_factor=1, # Espera 1s, 2s, 4s entre tentativas
        status_forcelist=[500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session.get(url, headers=headers, timeout=15)


def converter_numero(valor):
    """Converte valor de fonte para float, preservando zero legitimo.

    Ausencia, sentinela, None, texto invalido, NaN e infinitos viram
    ``float('nan')``. Nunca devolve 0.0 como substituto de dado faltante.
    """
    if valor is None or isinstance(valor, bool):
        return float("nan")
    try:
        if pd.isna(valor):
            return float("nan")
    except (TypeError, ValueError):
        pass
    if isinstance(valor, (int, float)):
        numero = float(valor)
        return numero if math.isfinite(numero) else float("nan")

    texto = str(valor).strip().lower().replace("r$", "").strip()
    if texto in _SENTINELAS_AUSENCIA:
        return float("nan")

    eh_percentual = "%" in texto
    texto = texto.replace("%", "").replace(" ", "")
    if not texto:
        return float("nan")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        numero = float(texto)
    except (TypeError, ValueError):
        return float("nan")
    if not math.isfinite(numero):
        return float("nan")
    return numero / 100 if eh_percentual else numero


def eh_valido(valor):
    """True somente para numero finito. Zero e valido; NaN/None/bool nao."""
    return (
        isinstance(valor, (int, float))
        and not isinstance(valor, bool)
        and math.isfinite(valor)
    )


def formatar(val):
    return converter_numero(val)


def formatar_pct(valor):
    """Percentual para exibicao. Aceita fracao (0.1154) ou porcento (11.54)."""
    if not eh_valido(valor):
        return "N/D"
    numero = float(valor)
    if abs(numero) > 1:
        numero = numero / 100.0
    return f"{numero * 100:.1f}%"


def montar_markup_painel(tickers, tipo):
    """Botoes para o painel ja existente: painel_{TICKER}_fii|acao."""
    if not tickers or not tipo:
        return None
    tipo_norm = "fii" if str(tipo).strip().lower() == "fii" else "acao"
    unicos = []
    vistos = set()
    for bruto in tickers:
        chave = str(bruto or "").strip().upper()
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(chave)
    if not unicos:
        return None
    from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        *[
            InlineKeyboardButton(t, callback_data=f"painel_{t}_{tipo_norm}")
            for t in unicos
        ]
    )
    return markup


def disparar_alertas(msg, tickers=None, tipo=None, chat_id=None):
    """Push de MOVIMENTACAO (Sheets+Telegram). Nao grava alertas_eventos."""
    if not msg or str(msg).strip() == "":
        return
    destino = chat_id if chat_id is not None else config.TELEGRAM_CHAT_ID
    if destino is None:
        return
    try:
        bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
        kwargs = {"parse_mode": "Markdown"}
        markup = montar_markup_painel(tickers, tipo)
        if markup is not None:
            kwargs["reply_markup"] = markup
        bot.send_message(destino, msg, **kwargs)
        print("📲 [Telegram] Notificação de ALERTA entregue com sucesso!")
    except Exception as e:
        print(f"⚠️ [Telegram] Erro de conexão ao enviar alerta: {e}")


def _destino_telegram(usuario):
    return getattr(usuario, "telegram_chat_id", None) or getattr(
        usuario, "telegram_user_id", None
    )


def notificar_seguidores_ticker(itens, tipo, repo=None, enviar=None):
    """Aviso individual a quem favoritou o ticker (admin incluso).

    Nao grava alertas_eventos. Sem seguidor, nada e enviado.
    """
    if not itens:
        return 0
    if repo is None:
        try:
            from pipeline_dados.repositorio_favoritos import RepositorioFavoritos

            repo = RepositorioFavoritos()
        except Exception:
            return 0
    disparar = enviar or disparar_alertas
    enviados = 0
    for item in itens:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").strip().upper()
        texto = str(item.get("texto") or "").strip()
        if not ticker or not texto:
            continue
        try:
            resolvido = repo.resolver_ativo(ticker)
        except Exception:
            continue
        if not resolvido:
            continue
        try:
            seguidores = repo.usuarios_que_acompanham(resolvido[0])
        except Exception:
            continue
        for usuario in seguidores or []:
            destino = _destino_telegram(usuario)
            if destino is None:
                continue
            disparar(texto, tickers=[ticker], tipo=tipo, chat_id=destino)
            enviados += 1
    return enviados

def conectar_gspread():
    google_creds = os.environ.get('GOOGLE_CREDS')
    if google_creds:
        creds_dict = json.loads(google_creds)
        gc = gspread.service_account_from_dict(creds_dict)
    else:
        gc = gspread.service_account(filename=config.JSON_KEY)
    return gc

def precisa_atualizar(ticker, mapa_atualizacao, agora_dt, sp_tz):
    if ticker not in mapa_atualizacao:
        return True

    val = str(mapa_atualizacao[ticker]).strip()
    if 'OK' not in val:
        return True

    val = val.replace('OK', '').strip() 
    try:
        dia, resto = val.split('/')
        mes, horario = resto.split(' ')
        hora, minuto = horario.split(':')

        dt_af = datetime(agora_dt.year, int(mes), int(dia), int(hora), int(minuto))
        dt_af = sp_tz.localize(dt_af)
        if dt_af > agora_dt: 
            dt_af = dt_af.replace(year=agora_dt.year - 1)

        janela = int(getattr(config, "THROTTLE_ATUALIZACAO_SEGUNDOS", 3600) or 3600)
        if (agora_dt - dt_af).total_seconds() < janela:
            return False
    except:
        pass
    return True


def _ticker_yahoo(simbolo):
    import yfinance as yf

    return yf.Ticker(simbolo)


def _numero_yahoo(obj, *nomes):
    for nome in nomes:
        try:
            valor = obj.get(nome) if isinstance(obj, dict) else getattr(obj, nome, None)
        except Exception:
            valor = None
        numero = converter_numero(valor)
        if eh_valido(numero):
            return numero
    return float("nan")


def buscar_cotacao_yahoo(simbolo, ticker_factory=None):
    """Ultimo preco e fechamento anterior. Sem rede nos testes (factory injetavel)."""
    factory = ticker_factory or _ticker_yahoo
    try:
        ticker = factory(simbolo)
    except Exception:
        return float("nan"), float("nan")

    last = float("nan")
    prev = float("nan")
    try:
        last = _numero_yahoo(
            ticker.fast_info, "last_price", "lastPrice", "regularMarketPrice"
        )
        prev = _numero_yahoo(
            ticker.fast_info, "previous_close", "previousClose", "regularMarketPreviousClose"
        )
    except Exception:
        pass
    if eh_valido(last):
        return last, prev
    try:
        hist = ticker.history(period="5d")
        closes = hist["Close"].dropna() if hist is not None and not hist.empty else None
        if closes is not None and len(closes) >= 1:
            last = converter_numero(closes.iloc[-1])
            if len(closes) >= 2:
                prev = converter_numero(closes.iloc[-2])
    except Exception:
        pass
    return last, prev


def formatar_pontos(valor, casas=2):
    if not eh_valido(valor):
        return "N/D"
    texto = f"{float(valor):,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _linha_indice(nome, preco, anterior):
    if not eh_valido(preco):
        return f"{nome}: N/D"
    if eh_valido(anterior) and float(anterior) != 0:
        variacao = (float(preco) - float(anterior)) / float(anterior) * 100.0
        sinal = "+" if variacao > 0 else ""
        icone = "📈" if variacao > 0 else ("📉" if variacao < 0 else "➖")
        return (
            f"{nome}: {formatar_pontos(preco)} "
            f"({sinal}{variacao:.2f}%) {icone}"
        )
    return f"{nome}: {formatar_pontos(preco)}"



def buscar_ohlc_diario_yahoo(simbolo, ticker_factory=None):
    """Retorna a última vela diária disponível e o fechamento anterior.

    A fonte é o Yahoo Finance; portanto o resultado não é chamado de cotação
    oficial B3. A data do pregão vem do índice da série retornada.
    """
    factory = ticker_factory or _ticker_yahoo
    try:
        ticker = factory(simbolo)
        historico = ticker.history(
            period="10d", interval="1d", auto_adjust=False
        )
        if historico is None or historico.empty or "Close" not in historico:
            return None
        historico = historico.dropna(subset=["Close"])
        if historico.empty:
            return None
        atual = historico.iloc[-1]
        anterior = historico.iloc[-2] if len(historico) >= 2 else None

        def numero_linha(linha, coluna):
            if linha is None or coluna not in linha:
                return None
            numero = converter_numero(linha[coluna])
            return numero if eh_valido(numero) else None

        indice = historico.index[-1]
        data_pregao = indice.date() if hasattr(indice, "date") else indice
        fechamento = numero_linha(atual, "Close")
        fechamento_anterior = numero_linha(anterior, "Close")
        variacao = None
        if (
            eh_valido(fechamento)
            and eh_valido(fechamento_anterior)
            and fechamento_anterior != 0
        ):
            variacao = (
                (fechamento - fechamento_anterior)
                / fechamento_anterior
                * 100.0
            )
        return {
            "data_pregao": data_pregao,
            "abertura": numero_linha(atual, "Open"),
            "maxima": numero_linha(atual, "High"),
            "minima": numero_linha(atual, "Low"),
            "fechamento": fechamento,
            "fechamento_anterior": fechamento_anterior,
            "variacao_percentual": variacao,
            "fonte": "Yahoo Finance - OHLC diário",
        }
    except Exception:
        return None


def buscar_indices_b3_ohlc(ticker_factory=None):
    """Busca a última vela diária disponível do IFIX e Ibovespa."""
    configuracoes = (
        ("IFIX", "IFIX.SA"),
        ("Ibovespa", "^BVSP"),
    )
    registros = []
    for indice, simbolo in configuracoes:
        registro = buscar_ohlc_diario_yahoo(
            simbolo, ticker_factory=ticker_factory
        )
        if registro is not None:
            registros.append({"indice": indice, **registro})
    return registros

def buscar_indices_b3(ticker_factory=None):
    factory = ticker_factory or _ticker_yahoo
    ifix_preco, ifix_ant = buscar_cotacao_yahoo("IFIX.SA", ticker_factory=factory)
    ibov_preco, ibov_ant = buscar_cotacao_yahoo("^BVSP", ticker_factory=factory)
    return [
        ("IFIX", ifix_preco, ifix_ant),
        ("Ibovespa", ibov_preco, ibov_ant),
    ]


def montar_mensagem_indices(indices):
    linhas = ["*Indices B3*"]
    for item in indices or []:
        if len(item) < 3:
            continue
        linhas.append(_linha_indice(item[0], item[1], item[2]))
    return "\n".join(linhas)


def mensagem_indices_b3(ticker_factory=None):
    return montar_mensagem_indices(buscar_indices_b3(ticker_factory=ticker_factory))
