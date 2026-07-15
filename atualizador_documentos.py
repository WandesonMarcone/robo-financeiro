from fnet_scraper import FnetDownloader
from modules.dropbox_manager import upload_para_dropbox
from modules.utils import conectar_gspread
import config

# O seu mapa para corrigir os nomes da B3
MAPA_FNET_B3 = {
    'MAXI REN': 'MXRF11', 'MXRF': 'MXRF11',
    'GUARDIAN': 'GARE11', 'GARE': 'GARE11',
    'CSHG LOG': 'HGLG11', 'HGLG': 'HGLG11',
    'VINCI SC': 'VISC11', 'VISC': 'VISC11',
    'VBI CRI': 'CVBI11', 'CVBI': 'CVBI11',
    'XP MALLS': 'XPML11',
    'KINEA RI': 'KNCR11',
    'BTLG': 'BTLG11'
}

def obter_tickers_da_planilha():
    """Conecta no Google Sheets e puxa todos os FIIs cadastrados na Coluna A."""
    try:
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        aba = planilha.worksheet("BD_FIIs")
        # Pega todos os valores da coluna 1 (A), ignorando o cabeçalho
        tickers = aba.col_values(1)
        # Remove espaços em branco e deixa tudo em maiúsculo
        tickers = [t.strip().upper() for t in tickers if t.strip()]
        return list(set(tickers)) # Retorna lista sem duplicatas
    except Exception as e:
        print(f"Erro ao ler planilha: {e}")
        return []

def rotina_de_atualizacao_em_massa():
    """Função Mestra que lê a planilha e atualiza todos os FIIs de uma vez"""
    # 1. Instancia as ferramentas da B3
    b3 = FnetDownloader()
    
    # 2. Descobre quem são os FIIs lendo a planilha
    lista_de_fiis = obter_tickers_da_planilha()
    print(f"🚀 Iniciando atualização para {len(lista_de_fiis)} FIIs...")
    
    relatorios_salvos = 0
    
    # 3. Faz o loop inteligente
    for ticker in lista_de_fiis:
        # Verifica se o ticker precisa ser "traduzido" usando o seu mapa
        nome_pesquisa = ticker
        for chave, valor in MAPA_FNET_B3.items():
            if valor == ticker:
                nome_pesquisa = chave
                break # Encontrou a tradução
        
        # O Librariano entra em ação
        documentos = b3.pesquisar_documentos(nome_pesquisa)
        
        # Se encontrou documentos, pega apenas o mais recente (o primeiro da lista)
        # Se quiser baixar o histórico todo, é só tirar esse '[:1]'
        for id_doc, data_ref in documentos[:1]:
            pdf_bytes = b3.baixar_pdf(id_doc)
            
            if pdf_bytes:
                # Usa a data de referência no nome do arquivo!
                nome_formatado = f"Relatorio_Gerencial_{data_ref}"
                link_gerado = upload_para_dropbox(
                    conteudo_pdf=pdf_bytes, 
                    ticker=ticker, 
                    tipo_doc=nome_formatado, 
                    data_str="Oficial"
                )
                if link_gerado:
                    relatorios_salvos += 1
    
    return relatorios_salvos