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
  
def buscar_ativo_na_planilha(ticker, is_fii):
    """
    Substitui a antiga _buscar_dados_planilha.
    Busca o ativo no cache da planilha e retorna o dicionário com os dados.
    """
    nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
    matriz = buscar_dados_planilha_com_cache(nome_aba)
    
    if not matriz:
        return None

    # Procura a linha do ticker na matriz carregada (a primeira coluna é o ticker)
    for row in matriz[1:]:  # Pula o cabeçalho
        if row[0].strip().upper() == ticker.upper():
            
            # Mapeamento de colunas (Mantendo a lógica original)
            if is_fii:
            return {
                "tipo": row[1],    # Coluna B
                "setor": row[2],   # Coluna C
                "preco": row[3],   # Coluna D
                "pvp": row[5],     # Coluna F
                "dy": row[6],      # Coluna G
                "vpa": row[14],    # Coluna N
                "raw": row         # Guarda a linha toda caso precise de detalhes
            }
            else:
            return {
                "setor": row[1],   # Coluna B
                "preco": row[2],   # Coluna C
                "dy": row[3],      # Coluna D
                "pl": row[5],      # Coluna F
                "pvp": row[6],     # Coluna G
                "roe": row[19],    # Coluna T
                "raw": row         # Guarda a linha toda
            }
    return None

