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