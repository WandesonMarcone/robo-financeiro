from PIL import Image, ImageDraw, ImageFont
import os

def criar_imagem_fii(dados_json, ticker, caminho_saida="post_pronto.png"):
    if not dados_json:
        return False

    # 1. Abre o seu template vazio
    try:
        img = Image.open("template_fii.png")
        draw = ImageDraw.Draw(img)
    except FileNotFoundError:
        print("❌ Template de imagem não encontrado!")
        return False

    # 2. Carrega as fontes (ajuste o tamanho conforme sua arte)
    try:
        fonte_titulo = ImageFont.truetype("Montserrat-Bold.ttf", 60)
        fonte_texto = ImageFont.truetype("Montserrat-Regular.ttf", 40)
    except OSError:
        # Fallback caso não ache a fonte
        fonte_titulo = ImageFont.load_default()
        fonte_texto = ImageFont.load_default()

    # 3. Escreve os textos matematicamente na imagem (X, Y)
    # A coordenada (100, 150) significa: 100 pixels da esquerda, 150 do topo.
    
    # Título (Ticker)
    draw.text((100, 100), f"FATO RELEVANTE: {ticker}", font=fonte_titulo, fill=(255, 255, 255))
    
    # Manchete
    draw.text((100, 200), dados_json.get("manchete", ""), font=fonte_texto, fill=(200, 200, 200))
    
    # Dividendos e Vacância
    draw.text((100, 350), f"💰 Dividendos: {dados_json.get('dividendos', '')}", font=fonte_texto, fill=(255, 255, 255))
    draw.text((100, 420), f"🏢 Vacância: {dados_json.get('vacancia', '')}", font=fonte_texto, fill=(255, 255, 255))

    # Lista de Imóveis (Fazendo um loop para pular linhas)
    y_imoveis = 550
    draw.text((100, 500), "Principais Ativos Citados:", font=fonte_titulo, fill=(255, 215, 0)) # Dourado
    for imovel in dados_json.get("imoveis", [])[:4]: # Pega no máx 4 para não vazar da tela
        draw.text((100, y_imoveis), f"- {imovel}", font=fonte_texto, fill=(255, 255, 255))
        y_imoveis += 50

    # NOVO: Adicionando o Gráfico PNG por cima da Arte Final
    try:
        # Tenta abrir o gráfico recém gerado
        grafico = Image.open("grafico_div.png")
        
        # Define onde ele vai ser colado (Ex: Canto inferior direito)
        posicao_x_grafico = 100
        posicao_y_grafico = 750 
        
        # O terceiro argumento (grafico) é a "máscara" que garante que o fundo fique transparente
        img.paste(grafico, (posicao_x_grafico, posicao_y_grafico), grafico)
    except FileNotFoundError:
        print("⚠️ Gráfico não encontrado, gerando imagem apenas com textos.")

    # 4. Salva a imagem final
    img.save(caminho_saida)
    print(f"📸 Imagem gerada com sucesso: {caminho_saida}")
    return True