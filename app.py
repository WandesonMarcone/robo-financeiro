import datetime
import pytz
import config
from modules.utils import conectar_gspread, disparar_alertas
from modules.scraper_acoes import rodar_garimpo_acoes
from modules.scraper_fiis import rodar_garimpo_fiis # <--- Importação Corrigida

def executar_auditoria_carteira():
    print("🚀 INICIANDO ARQUITETURA MODULAR DE ALTA PERFORMANCE 🚀")
    
    print("[1/5] Conectando ao Banco de Dados (Google Sheets)...")
    gc = conectar_gspread()
    planilha = gc.open_by_url(config.SPREADSHEET_URL)
    
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
        
    msg_consolidada = ""
    if msg_fiis: msg_consolidada += msg_fiis
    if msg_acoes: msg_consolidada += msg_acoes
        
    if msg_consolidada.strip():
        disparar_alertas(msg_consolidada)
    else:
        print("✅ Execução concluída com sucesso. (Mercado está estável, sem alertas de distorções).")

if __name__ == "__main__":
    executar_auditoria_carteira()
        
