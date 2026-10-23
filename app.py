import datetime
import pytz
import config
from modules.utils import conectar_gspread, disparar_alertas
from modules.scraper_acoes import rodar_garimpo_acoes
from modules.scraper_fiis import rodar_garimpo_fiis
from modules.eod_snapshots import tentar_persistir_eod


def _texto_digest(pacote):
    if isinstance(pacote, dict):
        return str(pacote.get("texto") or "").strip()
    return str(pacote or "").strip()


def _tickers_digest(pacote):
    if isinstance(pacote, dict):
        return list(pacote.get("tickers") or [])
    return []


def _tipo_digest(pacote, padrao):
    if isinstance(pacote, dict):
        return pacote.get("tipo") or padrao
    return padrao


def _enviar_movimentacao(pacote, tipo):
    """Push de MOVIMENTACAO (Sheets+Telegram). Nao grava alertas_eventos."""
    texto = _texto_digest(pacote)
    if not texto:
        return False
    disparar_alertas(
        texto,
        tickers=_tickers_digest(pacote),
        tipo=_tipo_digest(pacote, tipo),
    )
    return True


def executar_auditoria_carteira():
    print("INICIANDO ARQUITETURA MODULAR DE ALTA PERFORMANCE")
    
    print("[1/5] Conectando ao Banco de Dados (Google Sheets)...")
    gc = conectar_gspread()
    planilha = gc.open_by_url(config.SPREADSHEET_URL)
    
    sp_tz = pytz.timezone('America/Sao_Paulo')
    agora_dt = datetime.datetime.now(sp_tz)
    agora_sp = agora_dt.strftime('%d/%m %H:%M')
    
    print("\nAcionando Motor de Fundos Imobiliarios...")
    batch_updates_fiis, digest_fiis, aba_fiis = rodar_garimpo_fiis(planilha, agora_dt, agora_sp, sp_tz)
    
    print("\nAcionando Motor de Acoes Estruturais...")
    batch_updates_acoes, digest_acoes, aba_acoes = rodar_garimpo_acoes(planilha, agora_dt, agora_sp, sp_tz)
    
    print("\n[5/5] Consolidando gravacao de dados e envio de notificacoes...")
    if batch_updates_fiis:
        aba_fiis.batch_update(batch_updates_fiis)
        print(f"Sucesso: {len(batch_updates_fiis)} registros de FIIs gravados.")
        
    if batch_updates_acoes:
        aba_acoes.batch_update(batch_updates_acoes)
        print(f"Sucesso: {len(batch_updates_acoes)} registros de acoes gravados.")
        
    enviou_fii = _enviar_movimentacao(digest_fiis, "fii")
    enviou_acao = _enviar_movimentacao(digest_acoes, "acao")
    if not enviou_fii and not enviou_acao:
        print("Execucao concluida com sucesso. (Mercado esta estavel, sem alertas de distorcoes).")

    tentar_persistir_eod(planilha, agora_dt)

if __name__ == "__main__":
    executar_auditoria_carteira()
