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

# Adicione novos sites de RI aqui de forma simples!
# O formato é: "TICKER": "URL_DA_CENTRAL_DE_RESULTADOS"
MAPA_RI_SITES = {
    "HGLG11": "https://ri.hglg11.com.br/central-de-resultados/",
    "VISC11": "https://ri.visc11.com.br/central-de-resultados/",
    "PETR4": "https://api.mziq.com/mzfilemanager/v2/d/565d0a68-3f8c-4f51-b0e5-79a632742966/f2628468-b714-436f-870f-1b777a82810a?origin=1",
    # Basta adicionar uma nova linha aqui quando quiser novos fundos/ações!
}