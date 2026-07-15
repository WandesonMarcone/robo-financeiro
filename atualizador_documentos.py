from fnet_scraper import FnetDownloader
from modules.Dropbox_manager import upload_para_dropbox
from modules.utils import conectar_gspread
import config
from datetime import datetime

# ==========================================
# IMPORTAÇÕES DO BANCO DE DADOS
# ==========================================
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Configura a conexão com a sua memória SQLite
engine = create_engine("sqlite:///pipeline_dados/banco_institucional.db")
SessionDB = sessionmaker(bind=engine)

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
        tickers = aba.col_values(1)[1:] 
        tickers = [t.strip().upper() for t in tickers if t.strip()]
        return list(set(tickers)) 
    except Exception as e:
        print(f"Erro ao ler planilha: {e}")
        return []

def rotina_de_atualizacao_em_massa():
    """Função Mestra com Memória Anti-Duplicata e Foco no Fluxo Diário"""
    b3 = FnetDownloader()
    lista_de_fiis = obter_tickers_da_planilha()
    print(f"🚀 Iniciando atualização diária para {len(lista_de_fiis)} FIIs...")
    
    relatorios_salvos = 0
    session = SessionDB()
    
    # Define a data de hoje para filtrar apenas o que saiu agora
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    
    for ticker in lista_de_fiis:
        # Verifica se o ticker precisa ser "traduzido"
        nome_pesquisa = ticker
        for chave, valor in MAPA_FNET_B3.items():
            if valor == ticker:
                nome_pesquisa = chave
                break 
                
        # Garante que o Ativo existe no Banco de Dados
        ativo_db = session.query(Ativo).filter(Ativo.ticker == ticker).first()
        if not ativo_db:
            ativo_db = Ativo(ticker=ticker)
            session.add(ativo_db)
            session.commit()
        
        # O Librariano pesquisa APENAS documentos a partir de hoje
        documentos = b3.pesquisar_documentos(nome_pesquisa, data_inicio=data_hoje)
        
        # A Trava Anti-Duplicata continua protegendo a integridade
        for id_doc, data_ref in documentos:
            
            doc_existente = session.query(DocumentosQualitativos).filter(
                DocumentosQualitativos.ativo_id == ativo_db.id,
                DocumentosQualitativos.assunto.contains(id_doc) 
            ).first()
            
            if doc_existente:
                continue
            
            print(f"⬇️ Baixando documento inédito do dia: {ticker} (Data: {data_ref})...")
            pdf_bytes = b3.baixar_pdf(id_doc)
            
            if pdf_bytes:
                nome_formatado = f"Relatorio_Gerencial_{data_ref}_ID{id_doc}"
                
                link_gerado = upload_para_dropbox(
                    conteudo_pdf=pdf_bytes, 
                    ticker=ticker, 
                    tipo_doc=nome_formatado, 
                    data_str="Oficial"
                )
                
                if link_gerado:
                    novo_doc = DocumentosQualitativos(
                        ativo_id=ativo_db.id,
                        tipo_documento="Relatório Gerencial",
                        data_publicacao=datetime.now(),
                        assunto=f"Relatório ref. {data_ref} (ID B3: {id_doc})",
                        url_pdf=link_gerado
                    )
                    session.add(novo_doc)
                    session.commit()
                    relatorios_salvos += 1
    
    session.close()
    return relatorios_salvos