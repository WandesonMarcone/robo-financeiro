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
    """Função Mestra com Memória Anti-Duplicata"""
    b3 = FnetDownloader()
    lista_de_fiis = obter_tickers_da_planilha()
    print(f"🚀 Iniciando atualização histórica para {len(lista_de_fiis)} FIIs...")
    
    relatorios_salvos = 0
    
    # 1. Abre o Banco de Dados
    session = SessionDB()
    
    for ticker in lista_de_fiis:
        # Verifica se o ticker precisa ser "traduzido"
        nome_pesquisa = ticker
        for chave, valor in MAPA_FNET_B3.items():
            if valor == ticker:
                nome_pesquisa = chave
                break 
                
        # 2. Garante que o Ativo existe no Banco de Dados
        ativo_db = session.query(Ativo).filter(Ativo.ticker == ticker).first()
        if not ativo_db:
            # Se o ativo for novo (adicionado na planilha ontem, por exemplo), cadastra ele no banco
            ativo_db = Ativo(ticker=ticker)
            session.add(ativo_db)
            session.commit()
            print(f"🏢 Novo ativo {ticker} registrado no banco de dados!")
        
        # 3. O Librariano pesquisa TUDO desde 1º de Janeiro
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        documentos = b3.pesquisar_documentos(nome_pesquisa, data_inicio=data_hoje)
        
        # 4. A Trava Anti-Duplicata em ação
        for id_doc, data_ref in documentos:
            
            # Pergunta pro banco: "Já temos esse ID B3 salvo no assunto deste Ativo?"
            doc_existente = session.query(DocumentosQualitativos).filter(
                DocumentosQualitativos.ativo_id == ativo_db.id,
                DocumentosQualitativos.assunto.contains(id_doc) 
            ).first()
            
            if doc_existente:
                # Se já tem, ignora e vai pro próximo da lista na velocidade da luz
                print(f"⏩ Documento de {data_ref} ({ticker}) já está no cofre. Pulando...")
                continue
            
            # Se chegou aqui, é porque é INÉDITO! Pode baixar.
            print(f"⬇️ Baixando documento inédito: {ticker} (Data: {data_ref})...")
            pdf_bytes = b3.baixar_pdf(id_doc)
            
            if pdf_bytes:
                # Adiciona o ID da B3 no nome do arquivo para controle
                nome_formatado = f"Relatorio_Gerencial_{data_ref}_ID{id_doc}"
                
                link_gerado = upload_para_dropbox(
                    conteudo_pdf=pdf_bytes, 
                    ticker=ticker, 
                    tipo_doc=nome_formatado, 
                    data_str="Oficial"
                )
                
                if link_gerado:
                    # 5. Salva na Memória do Banco de Dados para nunca mais baixar!
                    novo_doc = DocumentosQualitativos(
                        ativo_id=ativo_db.id,
                        tipo_documento="Relatório Gerencial",
                        data_publicacao=datetime.now(),
                        assunto=f"Relatório ref. {data_ref} (ID B3: {id_doc})",
                        url_pdf=link_gerado
                    )
                    session.add(novo_doc)
                    session.commit() # Confirma a gravação
                    
                    relatorios_salvos += 1
    
    # 6. Fecha o banco de dados e finaliza
    session.close()
    return relatorios_salvos