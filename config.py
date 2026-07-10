import os

# --- INFRAESTRUTURA DE BANCO DE DADOS ---
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 
JSON_KEY = 'credenciais.json' 

# --- CONFIGURAÇÕES DE NOTIFICAÇÃO (TELEGRAM) ---
# 🔒 O Token agora é secreto! O código vai puxar diretamente do servidor Render.
SEU_CHAT_ID = os.environ.get("TELEGRAM_BOT_TOKEN") 
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
    "GARE11": "https://guardiangestora.com.br/fundo/guardian-logistica/" # <--- Adicionado
}