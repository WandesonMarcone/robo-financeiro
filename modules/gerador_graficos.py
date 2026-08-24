import yfinance as yf
import matplotlib.pyplot as plt
import os

def criar_grafico_dividendos(ticker, caminho_saida="grafico_div.png"):
    """
    Puxa os últimos dividendos do FII e gera um gráfico de barras com fundo transparente.
    """
    try:
        print(f"📊 Extraindo histórico de dividendos de {ticker}...")
        # Adiciona o .SA que é o padrão do Yahoo Finance para a bolsa brasileira
        ativo = yf.Ticker(f"{ticker}.SA")
        historico = ativo.history(period="1y")

        if historico.empty or 'Dividends' not in historico.columns:
            print(f"⚠️ Sem dados de dividendos para {ticker}")
            return False

        # Filtra apenas os dias que efetivamente pagaram dividendos
        dividendos = historico[historico['Dividends'] > 0]['Dividends']

        # Pega apenas os últimos 6 pagamentos para o gráfico não ficar espremido
        dividendos = dividendos.tail(6)

        # Formata as datas (Ex: de '2023-10-15' para '10/23')
        datas = [d.strftime("%m/%y") for d in dividendos.index]
        valores = dividendos.values

        # --- INÍCIO DA CRIAÇÃO DO GRÁFICO ---
        # Tamanho (6x3) proporcional para caber no canto inferior do seu Post do Instagram
        fig, ax = plt.subplots(figsize=(6, 3))

        # MÁGICA: Deixa o fundo do gráfico e da imagem transparentes (Alpha = 0.0)
        fig.patch.set_alpha(0.0)
        ax.patch.set_alpha(0.0)

        # Desenha as barras (Cor de destaque institucional: Verde Primavera ou Ouro)
        barras = ax.bar(datas, valores, color='#00FF7F', width=0.5)

        # Escreve o valor em Reais (R$) no topo de cada barrazinha
        for barra in barras:
            yval = barra.get_height()
            ax.text(barra.get_x() + barra.get_width()/2, yval + 0.01, f"R$ {yval:.2f}",
                    ha='center', va='bottom', color='white', fontsize=12, fontweight='bold')

        # Estiliza as letras e linhas (Branco para contrastar com seu template escuro)
        ax.tick_params(axis='x', colors='white', labelsize=14)

        # Removemos os números laterais (eixo Y) e as bordas de cima e direita para ficar mais "limpo"
        ax.get_yaxis().set_visible(False)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.spines['bottom'].set_color('white') # Linha do chão branca

        plt.tight_layout()

        # Salva o arquivo final em alta resolução (300 dpi)
        plt.savefig(caminho_saida, transparent=True, dpi=300)
        plt.close()

        print(f"✅ Gráfico gerado com sucesso: {caminho_saida}")
        return True

    except Exception as e:
        print(f"❌ Erro ao gerar gráfico de {ticker}: {e}")
        return False
