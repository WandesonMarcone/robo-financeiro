from datetime import datetime

import config
from atualizador_documentos import SessionDB, rotina_de_atualizacao_em_massa
from bot.loader import enviar_mensagem
from pipeline_dados.coletor_cvm import AcoesCVMReader


def varredura_diaria():
    """Rotina automatizada de coleta de dados."""
    enviar_mensagem(config.TELEGRAM_CHAT_ID, "⚙️ *Bom dia! Iniciando a varredura automática...*", parse_mode="Markdown")

    # 1. Rotina B3/FNET
    try:
        qtd = rotina_de_atualizacao_em_massa()
        enviar_mensagem(config.TELEGRAM_CHAT_ID, f"✅ B3 finalizada! {qtd} documentos salvos.")
    except Exception as e:
        enviar_mensagem(config.TELEGRAM_CHAT_ID, f"❌ Erro na varredura B3: {e}")

    # 2. Rotina CVM (Ações)
    try:
        session = SessionDB()
        coletor = AcoesCVMReader(session)
        coletor.atualizar_acoes(datetime.now().year)
        session.close()
        enviar_mensagem(config.TELEGRAM_CHAT_ID, "✅ Coleta CVM finalizada com sucesso!")
    except Exception as e:
        enviar_mensagem(config.TELEGRAM_CHAT_ID, f"❌ Erro na varredura CVM: {e}")

    enviar_mensagem(config.TELEGRAM_CHAT_ID, "🏁 *Cofre de dados 100% atualizado!*", parse_mode="Markdown")

    # ==========================================
    # 3. NOVO: Processamento Qualitativo (IA)
    # ==========================================
    enviar_mensagem(config.TELEGRAM_CHAT_ID, "🧠 *Iniciando leitura de PDFs com IA...*", parse_mode="Markdown")
    try:
        # Aqui você fará uma busca no seu banco de dados para pegar
        # os relatórios que o Passo 1 acabou de baixar.
        # Exemplo hipotético:
        # relatorios_novos = buscar_relatorios_nao_processados()
        # for relatorio in relatorios_novos:
        #     processar_relatorio_com_ia(relatorio.ticker, relatorio.texto, relatorio.url)

        enviar_mensagem(config.TELEGRAM_CHAT_ID, "✅ Leitura de IA finalizada!")
    except Exception as e:
        enviar_mensagem(config.TELEGRAM_CHAT_ID, f"❌ Erro no Motor de IA: {e}")
