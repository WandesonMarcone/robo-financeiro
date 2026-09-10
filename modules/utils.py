import json
import os
import time
from datetime import datetime

import gspread
import pandas as pd
import pytz
import requests
import telebot
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config


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


def formatar(val):
    """Converte valor de mercado. Erro/ausência/NaN → None; zero real → 0.0.

    Delegado a ``pipeline_dados.numerico`` (Fase 8.2). Não mascara coleta
    falha como zero. Percentual com ``%`` vira fração (``12,5%`` → ``0.125``).
    """
    from pipeline_dados.numerico import parsear_numero, parsear_percentual

    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(val, str) and "%" in val:
        return parsear_percentual(val)
    return parsear_numero(val)


def celula_planilha(valor):
    """Ausência (None) vira célula vazia no Sheets; zero real permanece 0.0."""
    return "" if valor is None else valor

def disparar_alertas(msg):
    """Garante a entrega da notificação via Telegram."""
    if not msg or msg.strip() == "":
        return
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    if not token or ":" not in token:
        print("[Telegram] TELEGRAM = SKIPPED (TELEGRAM_BOT_TOKEN ausente ou inválido)")
        return
    if not chat_id:
        print("[Telegram] TELEGRAM = SKIPPED (TELEGRAM_CHAT_ID ausente)")
        return
    try:
        bot = telebot.TeleBot(token)
        bot.send_message(chat_id, msg, parse_mode='Markdown')
        print("📲 [Telegram] Notificação de ALERTA entregue com sucesso!")
    except Exception as e:
        print(f"⚠️ [Telegram] Erro de conexão ao enviar alerta: {e}")

def conectar_gspread():
    """Conecta ao Google Sheets, falhando de forma clara quando faltar configuração.

    Se GOOGLE_CREDS/GOOGLE_CREDS_FILE ou SPREADSHEET_URL estiverem ausentes,
    levanta RuntimeError com mensagem clara listando o que falta, em vez de
    propagar uma exceção obscura do gspread. O funcionamento com a configuração
    correta permanece inalterado.
    """
    ausentes = config.validar_configuracao_sheets()
    if ausentes:
        raise RuntimeError(
            "CONFIGURAÇÃO AUSENTE DO GOOGLE SHEETS: "
            + "; ".join(ausentes)
            + ". Defina as credenciais do service account e a URL da planilha "
            "antes de executar."
        )
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
