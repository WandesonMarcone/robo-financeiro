import datetime
import pytz
import config
from modules.utils import conectar_gspread, disparar_alertas
from modules.scraper_acoes import rodar_garimpo_acoes
import module_fiis # Mantido temporariamente até a Reestruturação da Etapa 3 do link do Fundamentus

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
    aba_fiis = planilha.worksheet("BD_FIIs")
    msg_fiis = module_fiis.atualizar_fiis(aba_fiis)
    
    # --- TURBO DE AÇÕES ---
    print("\n⚡ Acionando Motor de Ações Esturutrais...")
    batch_updates, msg_acoes, aba_base = rodar_garimpo_acoes(planilha, agora_dt, agora_sp, sp_tz)
    
    # --- SALVAMENTO EM LOTE E ALERTA CONSOLIDADO ---
    print("\n[5/5] Consolidando gravação de dados e envio de notificações...")
    if batch_updates:
        aba_base.batch_update(batch_updates)
        print(f"💾 Sucesso: {len(batch_updates)} registros de ações gravados.")
        
    # Agrupa os alertas dos dois motores para não fludar o Telegram
    msg_consolidada = ""
    if msg_fiis:
        msg_consolidada += msg_fiis + "\n"
    if msg_acoes:
        msg_consolidada += msg_acoes
        
    if msg_consolidada.strip():
        disparar_alertas(msg_consolidada)
    else:
        print("✅ Execução concluída com sucesso. (Mercado está estável, sem alertas de distorções).")

if __name__ == "__main__":
    executar_auditoria_carteira()