import os

# --- INFRAESTRUTURA DE BANCO DE DADOS ---
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 
JSON_KEY = 'credenciais.json' 

# --- CONFIGURAÇÕES DE NOTIFICAÇÃO (TELEGRAM) ---
# 🔒 O Token agora é secreto! O código vai puxar diretamente do servidor Render.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 
# O Chat ID pode ficar público, pois é apenas um endereço de destino e sem o Token ninguém consegue mandar mensagens para lá.
TELEGRAM_CHAT_ID = "8867098987"

# Adicione isso ao seu config.py
DRIVE_FOLDER_ID = "1Q-dkO4oSd6_9zmOeZmPX8nmuVWzdjHOq"

# --- PREFERÊNCIAS DE ATIVOS FIXOS (A SUA CARTEIRA DO CORAÇÃO) ---
FIXAS_ACOES = ["PETR4", "VALE3", "ITUB4", "BBDC4"] 
FIXAS_FIIS = ["GARE11", "MXRF11", "VISC11", "HGLG11"] # Pode alterar e colocar os seus FIIs reais aqui

# ==========================================
# CATEGORIAS DO MENU INSTITUCIONAL
# ==========================================

# 1. FIIs (Fundos Imobiliários)
FIXAS_FIIS = ["GARE11", "MXRF11", "VISC11"] # Os seus favoritos
FII_TIJOLO = ["GARE11", "VISC11", "HGLG11", "PQDP11"]
FII_PAPEL = ["MXRF11", "KNRI11"]
FII_FOF = ["HGRU11"] # Coloque os seus FOFs aqui

# 2. Ações e Empresas
FIXAS_ACOES = ["PETR4", "VALE3", "WEGE3"] # As suas favoritas
ACOES_BANCOS = ["BBAS3", "ITSA4", "B3SA3"]
ACOES_ENERGIA = ["TAEE11", "EGIE3"]
ACOES_SANEAMENTO = ["RADL3"] # Coloque as suas aqui (RADL3 é saúde, mas é só um exemplo!)


# Adicione novos sites de RI aqui de forma simples!
# O formato é: "TICKER": "URL_DA_CENTRAL_DE_RESULTADOS"
MAPA_RI_SITES = {
    "HGLG11": "https://ri.hglg11.com.br/central-de-resultados/",
    "VISC11": "https://ri.visc11.com.br/central-de-resultados/",
    "GARE11": "https://guardiangestora.com.br/fundo/guardian-logistica/" # <--- Adicionado
}