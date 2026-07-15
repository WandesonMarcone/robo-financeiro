import os

# --- INFRAESTRUTURA DE BANCO DE DADOS ---
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 
JSON_KEY = 'credenciais.json' 

# --- CONFIGURAÇÕES DE NOTIFICAÇÃO (TELEGRAM) ---
# 🔒 O Token é secreto e puxado direto do cofre do Render.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 
TELEGRAM_CHAT_ID = "8867098987"

# ==========================================
# PREFERÊNCIAS DO MENU: ⭐ MEUS FAVORITOS
# ==========================================
# Aqui ficam APENAS os ativos que você quer fixos no menu de favoritos 
# para acesso em 1 clique (sem precisar navegar pelas pastas de setores).

FIXAS_FIIS = ["GARE11", "MXRF11", "VISC11", "HGLG11", "XPML11"]
FIXAS_ACOES = ["PETR4", "VALE3", "WEGE3", "ITUB4"]

# ==========================================
# SCRAPERS ESPECÍFICOS (Herança)
# ==========================================
# Mapa utilizado caso o scraper tente buscar links em sites de RI fora da B3
MAPA_RI_SITES = {
    "HGLG11": "https://ri.hglg11.com.br/central-de-resultados/",
    "VISC11": "https://ri.visc11.com.br/central-de-resultados/",
    "GARE11": "https://guardiangestora.com.br/fundo/guardian-logistica/"
}
