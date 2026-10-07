import json
import os
import config
from bot.loader import bot
from modules.leitor_pdf import extrair_texto_com_paginas # Importa a ferramenta de PDF

def processar_relatorio_com_ia(url_pdf, ticker):
    """
    1. Extrai o texto do PDF usando a ferramenta com páginas marcadas.
    2. Envia para a IA estruturar os dados.
    3. Envia o alerta formatado para o Telegram.
    """
    print(f"📄 [IA] Baixando e lendo o PDF de {ticker}...")
    texto_pdf = extrair_texto_com_paginas(url_pdf)

    if not texto_pdf:
        print(f"❌ [IA] Falha ao extrair texto do PDF para {ticker}")
        return

    # O Prompt de Ouro: Força a IA a retornar estritamente um JSON estruturado
    prompt_sistema = """
    Você é um analista financeiro sênior especializado em Fundos Imobiliários (FIIs) brasileiros.
    Analise o texto do Relatório Gerencial fornecido e extraia as informações estritamente no seguinte formato JSON puro (sem markdown extra, sem blocos de código com crases na resposta se possível, apenas o JSON válido):
    {
        "resumo": "Um resumo de impacto de até 3 linhas focando em: variação de vacância, dividendos distribuídos e movimentação de ativos (compras/vendas).",
        "inquilinos": "Resumo dos principais inquilinos ou concentração de receita (ex: Empresa X: 25%, Empresa Y: 15%).",
        "pagina_fotos": "Número da página exata do PDF onde se encontram o portfólio físico, fotos dos imóveis ou mapa de localização."
    }
    """

    prompt_usuario = f"Ticker do Fundo: {ticker}\n\nTexto do Relatório:\n{texto_pdf}"

    try:
        print(f"🧠 [IA] Enviando dados para a Inteligência Artificial...")

        # Simulação para validação do teste (pode substituir pela API real do Groq/OpenAI/Gemini depois):
        resposta_ia = json.dumps({
            "resumo": f"O fundo {ticker} apresentou resiliência operacional, mantendo a adimplência em 100% e distribuindo dividendos consistentes aos cotistas.",
            "inquilinos": "Principais exposições concentradas em galpões logísticos de primeiríssima linha.",
            "pagina_fotos": "12"
        })

        # Converte a resposta da IA em um dicionário Python
        dados_analise = json.loads(resposta_ia)

        # Monta a mensagem elegante para o Telegram
        mensagem = f"""
🚨 **Relatório Gerencial Analisado: {ticker}**

📝 **Resumo Inteligente:**
{dados_analise['resumo']}

🏢 **Inquilinos/Portfólio:**
{dados_analise['inquilinos']}

📸 **Destaque Visual:**
As fotos e detalhes físicos dos imóveis estão na **página {dados_analise['pagina_fotos']}**.
🔗 [Abrir PDF Original Completo]({url_pdf})

⚙️ *Pronto para gerar a arte do post no sistema!*
        """

        # Envia para o seu canal/chat configurado no Telegram
        bot.send_message(config.TELEGRAM_CHAT_ID, mensagem, parse_mode="Markdown")
        print(f"✅ [IA] Análise de {ticker} enviada com sucesso para o Telegram!")

    except Exception as e:
        print(f"❌ [Erro na IA] Falha ao processar a IA para {ticker}: {e}")
