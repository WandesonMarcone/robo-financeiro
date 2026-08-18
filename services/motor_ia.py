import json
from bot.loader import bot
import config

# Aqui você usará a biblioteca da sua IA (Grok, Groq, etc)
# Exemplo genérico de chamada:
def chamar_ia_grok(texto_do_pdf):
    prompt = f"""
    Você é um analista financeiro sênior de Fundos Imobiliários.
    Leia o texto extraído do Relatório Gerencial abaixo.
    
    Sua tarefa é me devolver APENAS um JSON (sem explicações adicionais) com as seguintes chaves:
    1. "resumo": Um resumo de impacto de 3 linhas sobre as novidades do fundo (foco em vacância, dividendos e compras/vendas).
    2. "inquilinos": Um dicionário com os 5 maiores inquilinos e suas porcentagens.
    3. "pagina_fotos": O número da página onde estão as fotos dos imóveis ou o portfólio físico (procure por palavras como "Ativos", "Portfólio", "Imóveis").

    Texto do Relatório:
    {texto_do_pdf}
    """
    
    # Lógica de chamada da sua API gratuita (Grok/Groq/etc) vai aqui
    # ...
    # resposta_ia = chamda_api(prompt)
    
    # Exemplo do que a IA vai devolver:
    resposta_simulada = '''
    {
        "resumo": "O fundo reduziu a vacância para 4% e adquiriu um novo galpão em Extrema-MG. O dividendo projetado aumentou para R$ 1,10.",
        "inquilinos": {"Mercado Livre": 30, "Amazon": 20, "Assaí": 15},
        "pagina_fotos": "14"
    }
    '''
    return json.loads(resposta_simulada)

def processar_relatorio_com_ia(ticker, texto_do_pdf, link_pdf):
    """Envia para a IA e manda o alerta no Telegram"""
    
    dados = chamar_ia_grok(texto_do_pdf)
    
    mensagem = f"""
🚨 **Novo Relatório Gerencial: {ticker}**

📝 **Resumo IA:** {dados['resumo']}

📊 *Gráfico de Inquilinos pode ser gerado.*

📸 **Ação Manual Sugerida:** As fotos e detalhes dos imóveis físicos estão na **página {dados['pagina_fotos']}**. 
🔗 [Clique aqui para abrir o PDF original]({link_pdf})

⚙️ *Deseja aprovar e montar a arte do post? (/gerar_post {ticker})*
    """
    
    bot.send_message(config.TELEGRAM_CHAT_ID, mensagem, parse_mode="Markdown")