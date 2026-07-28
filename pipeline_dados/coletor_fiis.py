import os
import zipfile
import io
import requests
import csv
from datetime import datetime
from pipeline_dados.banco_dados import Ativo, DadosFinanceirosFiis
from atualizador_documentos import SessionDB

def processar_informes_fiis_cvm(ano=2026):
    """
    Baixa o pacote de Informes Mensais de FIIs da CVM (formato CSV),
    extrai os dados e salva na tabela DadosFinanceirosFiis.
    """
    session = SessionDB()
    url = f"https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip"
    
    print(f"📥 Baixando informes mensais de FIIs (CSV) para o ano de {ano}...")
    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            print(f"❌ Erro ao baixar dados da CVM para FIIs: Status {response.status_code}")
            return False

        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            # Filtra apenas os arquivos CSV
            arquivos_csv = [f for f in z.namelist() if f.endswith('.csv') or f.endswith('.CSV')]
            
            if not arquivos_csv:
                print("⚠️ Nenhum arquivo CSV encontrado no pacote da CVM.")
                return False

            print(f"🔍 Processando {len(arquivos_csv)} arquivos de tabelas da CVM...")

            # Dicionário em memória para juntar as métricas do mesmo fundo no mesmo mês
            # Chave: (CNPJ, DATA_REFERENCIA) -> Valor: Dicionário de métricas
            dados_consolidados = {}

            for arquivo_nome in arquivos_csv:
                with z.open(arquivo_nome) as f_csv:
                    # A CVM usa codificação latin1 e separador ponto e vírgula
                    reader = csv.DictReader(io.TextIOWrapper(f_csv, encoding='latin1'), delimiter=';')
                    
                    for row in reader:
                        cnpj_fundo = row.get('CNPJ_Fundo')
                        data_ref_str = row.get('DT_COMPTC')

                        if not cnpj_fundo or not data_ref_str:
                            continue

                        # O formato da data no CSV costuma ser YYYY-MM-DD
                        chave = (cnpj_fundo, data_ref_str)
                        if chave not in dados_consolidados:
                            dados_consolidados[chave] = {}

                        # Captura as métricas dependendo de qual tabela CSV estamos lendo
                        if 'VL_PATRIM_LIQ' in row: # Aba Geral
                            dados_consolidados[chave]['patrimonio_liquido'] = row.get('VL_PATRIM_LIQ')
                            dados_consolidados[chave]['cotistas'] = row.get('NR_COTISTAS')
                        
                        if 'Ativo_Total' in row or 'VL_TOTAL' in row: # Aba Ativo
                            val_ativo = row.get('Ativo_Total') or row.get('VL_TOTAL')
                            if val_ativo: dados_consolidados[chave]['ativo_total'] = val_ativo
                        
                        if 'Disponibilidades' in row: # Aba Caixa/Passivo
                            dados_consolidados[chave]['disponibilidades_caixa'] = row.get('Disponibilidades')

            print("📝 Tabelas lidas! Inserindo os dados no Banco de Dados...")
            
            # Agora vamos salvar no banco de dados local!
            for (cnpj_fundo, data_ref_str), metricas in dados_consolidados.items():
                if not metricas: # Se não achou nada relevante nas tabelas, pula
                    continue
                    
                cnpj_limpo = ''.join(filter(str.isdigit, cnpj_fundo))
                ativo = session.query(Ativo).filter(Ativo.ticker.ilike(f"%{cnpj_limpo}%")).first()
                
                if not ativo:
                    continue # Fundo não monitorado

                data_referencia = datetime.strptime(data_ref_str[:10], "%Y-%m-%d").date()

                registro = session.query(DadosFinanceirosFiis).filter_by(
                    ativo_id=ativo.id, 
                    data_referencia=data_referencia
                ).first()

                if not registro:
                    registro = DadosFinanceirosFiis(ativo_id=ativo.id, data_referencia=data_referencia)
                    session.add(registro)

                # Conversores seguros para lidar com os formatos do CSV
                def safe_float(val):
                    try: return float(val.replace(',', '.')) if isinstance(val, str) else float(val)
                    except: return None

                def safe_int(val):
                    try: return int(float(val)) if val else None
                    except: return None

                # Popula os campos
                if 'patrimonio_liquido' in metricas: registro.patrimonio_liquido = safe_float(metricas['patrimonio_liquido'])
                if 'cotistas' in metricas: registro.cotistas = safe_int(metricas['cotistas'])
                if 'ativo_total' in metricas: registro.ativo_total = safe_float(metricas['ativo_total'])
                if 'disponibilidades_caixa' in metricas: registro.disponibilidades_caixa = safe_float(metricas['disponibilidades_caixa'])

            session.commit()
            print("✅ Processamento dos Informes de FIIs concluído com sucesso!")
            return True

    except Exception as e:
        print(f"❌ Erro geral ao processar CSV de FIIs: {e}")
        return False
    finally:
        session.close()