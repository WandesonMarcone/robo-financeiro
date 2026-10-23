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


def disparar_alertas(msg, tickers=None, tipo=None):
    """Push de MOVIMENTACAO (Sheets+Telegram). Nao grava alertas_eventos."""
    if not msg or str(msg).strip() == "":
        return
    try:
        bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
        kwargs = {"parse_mode": "Markdown"}
        markup = montar_markup_painel(tickers, tipo)
        if markup is not None:
            kwargs["reply_markup"] = markup
        bot.send_message(config.TELEGRAM_CHAT_ID, msg, **kwargs)
        print("📲 [Telegram] Notificação de ALERTA entregue com sucesso!")
    except Exception as e:
        print(f"⚠️ [Telegram] Erro de conexão ao enviar alerta: {e}")

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

        if (agora_dt - dt_af).total_seconds() < 7200:
            return False 
    except:
        pass 
    return True
