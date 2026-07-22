# services/planilhas.py
import time
from modules.utils import conectar_gspread
import config

CACHE_PLANILHA = {
    "BD_FIIs": {"dados": None, "timestamp": 0},
    "BD_Acoes": {"dados": None, "timestamp": 0}
}

TEMPO_CACHE_SEGUNDOS = 300 # 5 minutos

def safe_get(lista, indice, padrao="N/A"):
    """Evita erro se a coluna do Google Sheets estiver vazia"""
    return lista[indice].strip() if len(lista) > indice and lista[indice].strip() else padrao

def buscar_ativo_na_planilha(ticker, is_fii):
    """Busca os indicadores de um ativo específico no cache"""
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
    matriz = buscar_dados_planilha_com_cache(nome_aba)
    
    if not matriz: return None

    for row in matriz[1:]:
        if row[0].strip().upper() == ticker.upper():
            if is_fii:
                return {
                    "tipo": safe_get(row, 1), "setor": safe_get(row, 2), "preco": safe_get(row, 3),
                    "pvp": safe_get(row, 5), "dy": safe_get(row, 6), "vpa": safe_get(row, 14), "raw": row
                }
            else:
                return {
                    "setor": safe_get(row, 1), "preco": safe_get(row, 2), "dy": safe_get(row, 3),
                    "pl": safe_get(row, 5), "pvp": safe_get(row, 6), "roe": safe_get(row, 19), "raw": row
                }
    return None