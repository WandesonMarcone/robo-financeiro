import time
from modules.utils import conectar_gspread
import config

# Variável global para armazenar os dados por 5 minutos
CACHE_PLANILHA = {
    "BD_FIIs": {"dados": None, "timestamp": 0},
    "BD_Acoes": {"dados": None, "timestamp": 0}
}

TEMPO_CACHE_SEGUNDOS = 300 # 5 minutos

def buscar_dados_planilha_com_cache(nome_aba):
    """Retorna os dados da planilha. Se tiver consultado nos últimos 5 min, não vai na internet."""
    agora = time.time()
    
    # 1. Verifica se o cache ainda é válido
    if CACHE_PLANILHA[nome_aba]["dados"] is not None:
        if (agora - CACHE_PLANILHA[nome_aba]["timestamp"]) < TEMPO_CACHE_SEGUNDOS:
            return CACHE_PLANILHA[nome_aba]["dados"]
    
    # 2. Se o cache expirou ou está vazio, vai ao Google
    planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
    aba = planilha.worksheet(nome_aba)
    matriz = aba.get_all_values()
    
    # 3. Salva no cache
    CACHE_PLANILHA[nome_aba]["dados"] = matriz
    CACHE_PLANILHA[nome_aba]["timestamp"] = agora
    
    return matriz
  
