import os
import time
import unicodedata
from datetime import datetime, timedelta
import config
from fnet_scraper import FnetDownloader
from modules.GoogleDriveManager import GoogleDriveManager
from modules.utils import conectar_gspread
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine("sqlite:///pipeline_dados/banco_institucional.db")
SessionDB = sessionmaker(bind=engine)

# ==========================================
# 🗺️ O RADAR DE ISCAS (MAPA REVISADO)
# ==========================================
MAPA_ISCAS = {
    'XPML11': 'XP MALLS', # CORRIGIDO: Evita puxar os documentos do XPLG11 (XP Log)
    'MXRF11': 'MAXI RENDA',
    'HGLG11': 'CGHG LOG',
    'VISC11': 'VINCI SHOPPING CENTERS',
    'KNCR11': 'KINEA RENDIMENTOS',
    'GARE11': 'GUARDIAN LOG',
    'BTLG11': 'BTG PACTUAL LOG',
    'VILG11': 'VINCI LOG',
    'CPSH11': 'CAPITANIA', 
    'HGCR11': 'CSHG RECEBIVEIS',
    'VGIR11': 'VALORA RENDA IMOBILIÁRIA', # CORRIGIDO: Removido espaço em branco no final
    'RBRY11': 'RBR PRIVATE',
    'CLIN11': 'CLAVE',
    'KNHF11': 'KINEA HEDGE',
    'KNUQ11': 'KINEA UNICO',
    'BTCI11': 'BTG PACTUAL CREDITO',
    'RZTR11': 'RZ TR',
    'GGRC11': 'GGR COVEPI',
    'TRXF11': 'TRX REAL ESTATE FUNDO',
    'CVBI11': 'VBI CRI'
}

def obter_tickers_da_planilha():
    try:
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)
        aba = planilha.worksheet("BD_FIIs")
        tickers = aba.col_values(1)[1:] 
        return list(set([t.strip().upper() for t in tickers if t.strip()])) 
    except Exception as e:
        print(f"Erro ao ler planilha: {e}")
        return []

def normalizar_texto(texto):
    """Remove acentos e caracteres especiais para a busca ser infalível"""
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def rotina_de_atualizacao_em_massa():
    b3 = FnetDownloader()
    drive_manager = GoogleDriveManager()
    lista_de_fiis = obter_tickers_da_planilha()
    
    print(f"🚀 Iniciando OPERAÇÃO FURTIVA para {len(lista_de_fiis)} FIIs...")
    relatorios_salvos = 0
    session = SessionDB()

    # Janela de 100 dias (trazendo o passado com segurança)
    data_busca = (datetime.now() - timedelta(days=100)).strftime("%d/%m/%Y")
    
    # 🎯 Nossa lista de alvos (Filtra o lixo burocrático e foca no que importa)
    CATEGORIAS_ALVO = ["14", "10", "15", "12", "3", "17", "23"]

    for id_categoria in CATEGORIAS_ALVO:
        print(f"\n📡 Puxando pacotes da Categoria {id_categoria}...")
        
        todos_documentos = b3.capturar_tudo(data_busca, id_categoria)
        
        print(f"📦 B3 entregou {len(todos_documentos)} documentos. Analisando...")

        for doc in todos_documentos:
            nome_fundo_b3 = normalizar_texto(doc['nome_fundo'])
            id_doc = doc['id']
            data_ref = doc['data_ref']
            nome_categoria_real = doc['tipo_doc'] # <--- A ETIQUETA REAL DA B3

            # Verifica se algum dos nossos fundos publicou o documento
            for ticker in lista_de_fiis:
                isca = normalizar_texto(MAPA_ISCAS.get(ticker, ticker))
                
                # O Match: A isca está dentro do nome bizarro da B3?
                if isca in nome_fundo_b3:
                    
                    ativo_db = session.query(Ativo).filter(Ativo.ticker == ticker).first()
                    if not ativo_db:
                        ativo_db = Ativo(ticker=ticker, cnpj=f"PENDENTE-{ticker}", tipo="FII") 
                        session.add(ativo_db)
                        session.commit()

                    # Trava Anti-Duplicata no Banco
                    doc_existente = session.query(DocumentosQualitativos).filter(
                        DocumentosQualitativos.ativo_id == ativo_db.id,
                        DocumentosQualitativos.assunto.contains(id_doc) 
                    ).first()

                    if doc_existente:
                        continue

                    print(f"🎯 MATCH! {ticker} publicou: {nome_categoria_real} (ID: {id_doc})")
                    pdf_bytes = b3.baixar_pdf(id_doc)

                    # Só cria a pasta se o arquivo for um PDF real (ignora os XMLs)
                    if pdf_bytes:
                        temp_filename = f"/tmp/{ticker}_{id_doc}.pdf"
                        with open(temp_filename, "wb") as f:
                            f.write(pdf_bytes)

                        # Arruma a pasta pelo MÊS do documento na B3 (YYYY-MM)
                        partes_data = data_ref.split('-')
                        if len(partes_data) == 3:
                            mes_pasta = f"{partes_data[2]}-{partes_data[1]}" 
                        else:
                            mes_pasta = datetime.now().strftime("%Y-%m")

                        link_gerado = drive_manager.upload_pdf_organizado(
                            caminho_arquivo=temp_filename,
                            nome_arquivo=f"{nome_categoria_real}_{data_ref}_{id_doc}.pdf",
                            ticker=ticker,
                            mes_ref=mes_pasta 
                        )

                        if os.path.exists(temp_filename):
                            os.remove(temp_filename)

                        # Salva no Banco de Dados com a Categoria Perfeita
                        if link_gerado:
                            novo_doc = DocumentosQualitativos(
                                ativo_id=ativo_db.id,
                                tipo_documento=nome_categoria_real, 
                                data_publicacao=datetime.now(),
                                assunto=f"{nome_categoria_real} ref. {data_ref} (ID B3: {id_doc})",
                                url_pdf=link_gerado
                            )
                            session.add(novo_doc)
                            session.commit()
                            relatorios_salvos += 1
                            print(f"☁️ ✅ Salvo: {ticker} -> {nome_categoria_real} (Pasta: {mes_pasta})")
                    
                    break # Documento alocado. Pula para o próximo doc da B3.

    session.close()
    return relatorios_salvos