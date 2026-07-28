import os
import zipfile
import io
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from pipeline_dados.banco_dados import Ativo, DadosFinanceirosFiis
from atualizador_documentos import SessionDB

def processar_informes_fiis_cvm(ano=2026):
    """
    Baixa o pacote de Informes Mensais de FIIs da CVM do ano especificado,
    extrai os dados e salva na tabela DadosFinanceirosFiis.
    """
    session = SessionDB()
    url = f"https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip"
    
    print(f"📥 Baixando informes mensais de FIIs para o ano de {ano}...")
    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            print(f"❌ Erro ao baixar dados da CVM para FIIs: Status {response.status_code}")
            return False

        # Abre o arquivo ZIP diretamente na memória RAM
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            # Procura os arquivos XML dentro do zip
            arquivos_xml = [f for f in z.namelist() if f.endswith('.xml') or f.endswith('.XML')]
            
            if not arquivos_xml:
                # Se estiver em formato CSV (alguns anos usam CSV no informe mensal), 
                # a CVM padroniza bastante. Vamos focar na estrutura XML padrão solicitada.
                print("⚠️ Nenhum arquivo XML encontrado no pacote da CVM.")
                return False

            print(f"🔍 Processando {len(arquivos_xml)} arquivos de FIIs...")

            for arquivo_nome in arquivos_xml:
                with z.open(arquivo_nome) as f_xml:
                    try:
                        tree = ET.parse(f_xml)
                        root = tree.getroot()

                        # Extração segura das tags padrão do informe da CVM
                        # (Nota: As tags exatas variam conforme o layout da CVM, ajustamos a raiz genérica)
                        cnpj_fundo = root.findtext('.//CNPJFundo') or root.findtext('.//CNPJ')
                        data_ref_str = root.findtext('.//DataReferencia') or root.findtext('.//Competencia')

                        if not cnpj_fundo or not data_ref_str:
                            continue

                        # Limpa formatação do CNPJ para buscar no banco
                        cnpj_limpo = ''.join(filter(str.isdigit, cnpj_fundo))
                        
                        # Busca o ativo correspondente no banco local
                        ativo = session.query(Ativo).filter(Ativo.ticker.ilike(f"%{cnpj_limpo}%") ).first()
                        
                        # Se não achar por CNPJ, tenta mapear se o ticker estiver associado
                        if not ativo:
                            # Caso o XML traga o nome/ticker diretamente
                            ticker_xml = root.findtext('.//CodigoFundo') or root.findtext('.//Ticker')
                            if ticker_xml:
                                ativo = session.query(Ativo).filter(Ativo.ticker == ticker_xml.strip()).first()

                        if not ativo:
                            continue # Pula se o fundo não estiver cadastrado na sua base

                        data_referencia = datetime.strptime(data_ref_str[:10], "%Y-%m-%d").date()

                        # Leitura dos Indicadores Contábeis e Operacionais
                        def safe_float(val):
                            try: return float(val) if val else None
                            except: return None

                        def safe_int(val):
                            try: return int(val) if val else None
                            except: return None

                        patrimonio_liq = safe_float(root.findtext('.//PatrimonioLiquido'))
                        ativo_tot = safe_float(root.findtext('.//AtivoTotal'))
                        caixa_disp = safe_float(root.findtext('.//Disponibilidades')) or safe_float(root.findtext('.//Caixa'))
                        rend_cota = safe_float(root.findtext('.//ValorRendimentoPorCota'))
                        
                        # Novos campos adicionados
                        qtd_cotistas = safe_int(root.findtext('.//NumCotistas'))
                        qtd_cotas = safe_float(root.findtext('.//EmissãoCotas')) or safe_float(root.findtext('.//QtdCotasEmitidas'))
                        rec_imoveis = safe_float(root.findtext('.//ReceitaImoveis'))
                        res_venda = safe_float(root.findtext('.//ResultadoVendaAtivos'))

                        # Indicadores Físicos
                        vac_fisica = safe_float(root.findtext('.//VacanciaFisica'))
                        vac_financeira = safe_float(root.findtext('.//VacanciaFinanceira'))
                        desp_taxas = safe_float(root.findtext('.//DespesasTaxaAdministracao'))

                        # Verifica se já existe registro para atualizar ou inserir (Upsert limpo)
                        registro = session.query(DadosFinanceirosFiis).filter_by(
                            ativo_id=ativo.id, 
                            data_referencia=data_referencia
                        ).first()

                        if not registro:
                            registro = DadosFinanceirosFiis(ativo_id=ativo.id, data_referencia=data_referencia)
                            session.add(registro)

                        # Atualiza os valores
                        registro.patrimonio_liquido = patrimonio_liq
                        registro.ativo_total = ativo_tot
                        registro.disponibilidades_caixa = caixa_disp
                        registro.rendimento_por_cota = rend_cota
                        registro.cotistas = qtd_cotistas
                        registro.cotas_emitidas = qtd_cotas
                        registro.receita_imoveis = rec_imoveis
                        registro.resultado_ligado_venda = res_venda
                        registro.vacancia_fisica = vac_fisica
                        registro.vacancia_financeira = vac_financeira
                        registro.despesas_taxas = desp_taxas

                        session.commit()

                    except Exception as inner_err:
                        # Ignora arquivos corrompidos individuais para não travar o lote
                        continue

        print("✅ Processamento dos Informes de FIIs concluído com sucesso!")
        return True

    except Exception as e:
        print(f"❌ Erro geral ao processar XML de FIIs: {e}")
        return False
    finally:
        session.close()