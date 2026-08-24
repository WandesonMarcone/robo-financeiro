import datetime
import logging

import pytz

import config
from modules.scraper_acoes import rodar_garimpo_acoes
from modules.scraper_fiis import rodar_garimpo_fiis  # <--- Importação Corrigida
from modules.utils import conectar_gspread, disparar_alertas
from pipeline_dados.espelhamento_mercado_5c import espelhar_mercado_se_ativo

logger = logging.getLogger(__name__)

def executar_auditoria_carteira():
    print("🚀 INICIANDO ARQUITETURA MODULAR DE ALTA PERFORMANCE 🚀")

    print("[1/5] Conectando ao Banco de Dados (Google Sheets)...")
    try:
        gc = conectar_gspread()
        planilha = gc.open_by_url(config.SPREADSHEET_URL)
    except RuntimeError as e:
        print(f"❌ {e}")
        raise SystemExit(2)

    sp_tz = pytz.timezone('America/Sao_Paulo')
    agora_dt = datetime.datetime.now(sp_tz)
    agora_sp = agora_dt.strftime('%d/%m %H:%M')

    # --- TURBO DE FIIS ---
    print("\n⚡ Acionando Motor de Fundos Imobiliários...")
    batch_updates_fiis, msg_fiis, aba_fiis = rodar_garimpo_fiis(planilha, agora_dt, agora_sp, sp_tz)

    # --- TURBO DE AÇÕES ---
    print("\n⚡ Acionando Motor de Ações Estruturais...")
    batch_updates_acoes, msg_acoes, aba_acoes = rodar_garimpo_acoes(planilha, agora_dt, agora_sp, sp_tz)

    # --- SALVAMENTO EM LOTE E ALERTA CONSOLIDADO ---
    print("\n[5/5] Consolidando gravação de dados e envio de notificações...")
    if batch_updates_fiis:
        aba_fiis.batch_update(batch_updates_fiis)
        print(f"💾 Sucesso: {len(batch_updates_fiis)} registros de FIIs gravados.")

    if batch_updates_acoes:
        aba_acoes.batch_update(batch_updates_acoes)
        print(f"💾 Sucesso: {len(batch_updates_acoes)} registros de ações gravados.")

    # ==========================================
    # 📡 ESPELHAMENTO POSTGRESQL (Fase 3, Bloco 5C)
    # ==========================================
    # O Google Sheets já foi gravado acima (fonte ativa). O espelhamento 5C roda
    # DEPOIS, de forma controlada pela flag ESPELHAMENTO_PG_ATIVO. Uma falha
    # aqui (ex.: PostgreSQL indisponível) é apenas registrada: NUNCA desfaz,
    # corrompe nem bloqueia os dados já gravados no Sheets.
    if config.ESPELHAMENTO_PG_ATIVO:
        matriz_fiis = aba_fiis.get_all_values() if batch_updates_fiis else None
        matriz_acoes = aba_acoes.get_all_values() if batch_updates_acoes else None
        try:
            espelhar_mercado_se_ativo(matriz_fiis=matriz_fiis, matriz_acoes=matriz_acoes)
        except Exception as e:
            logger.exception("Espelhamento PostgreSQL falhou (Sheets preservado): %s", e)

    msg_consolidada = ""
    if msg_fiis:
        msg_consolidada += msg_fiis
    if msg_acoes:
        msg_consolidada += msg_acoes

    if msg_consolidada.strip():
        disparar_alertas(msg_consolidada)
    else:
        print("✅ Execução concluída com sucesso. (Mercado está estável, sem alertas de distorções).")

if __name__ == "__main__":
    executar_auditoria_carteira()

