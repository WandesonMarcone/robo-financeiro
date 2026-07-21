# services/planilhas.py
import time
from modules.utils import conectar_gspread
import config

CACHE_PLANILHA = {
    "BD_FIIs": {"dados": None, "timestamp": 0},
    "BD_Acoes": {"dados": None, "timestamp": 0}
}

TEMPO_CACHE_SEGUNDOS = 300 # 5 minutos

def buscar_dados_planilha_com_cache(nome_aba):
    """Retorna os dados da planilha via cache para não sobrecarregar a API"""
    agora = time.time()
    
    if CACHE_PLANILHA[nome_aba]["dados"] is not None:
        if (agora - CACHE_PLANILHA[nome_aba]["timestamp"]) < TEMPO_CACHE_SEGUNDOS:
            return CACHE_PLANILHA[nome_aba]["dados"]
    
    planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
    aba = planilha.worksheet(nome_aba)
    matriz = aba.get_all_values()
    
    CACHE_PLANILHA[nome_aba]["dados"] = matriz
    CACHE_PLANILHA[nome_aba]["timestamp"] = agora
    
    return matriz
  
def buscar_ativo_na_planilha(ticker, is_fii):
    """Busca os indicadores de um ativo específico no cache"""
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
    matriz = buscar_dados_planilha_com_cache(nome_aba)
    
    if not matriz:
        return None

    for row in matriz[1:]:
        if row[0].strip().upper() == ticker.upper():
            # CORREÇÃO: Indentação arrumada aqui!
            if is_fii:
                return {
                    "tipo": row[1], "setor": row[2], "preco": row[3],
                    "pvp": row[5], "dy": row[6], "vpa": row[14], "raw": row
                }
            else:
                return {
                    "setor": row[1], "preco": row[2], "dy": row[3],
                    "pl": row[5], "pvp": row[6], "roe": row[19], "raw": row
                }
    return None
