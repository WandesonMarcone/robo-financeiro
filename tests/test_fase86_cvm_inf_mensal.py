"""Fase 8.6: INF_MENSAL CVM — colunas reais, ausencia nao vira zero."""
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import Ativo, Base, DadosFinanceirosFiis, TipoAtivo
from pipeline_dados.catalogo_ativos import garantir_ativo, registrar_no_catalogo
from pipeline_dados.coletor_fiis import (
    CAMPOS_CVM_AUSENTES_NO_CSV,
    consolidar_linhas_inf_mensal,
    extrair_campos_inf_mensal,
    persistir_informes_fiis,
)


def _sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def linha_complemento():
    return {
        "CNPJ_Fundo_Classe": "00.332.266/0001-31",
        "Data_Referencia": "2026-01-01",
        "Patrimonio_Liquido": "1000.50",
        "Valor_Ativo": "1100.00",
        "Cotas_Emitidas": "500",
        "Total_Numero_Cotistas": "10",
        "Nome_Fundo_Classe": "",
    }


def linha_ativo_passivo():
    return {
        "CNPJ_Fundo_Classe": "00.332.266/0001-31",
        "Data_Referencia": "2026-01-01",
        "Disponibilidades": "25.00",
    }


def linha_geral():
    return {
        "CNPJ_Fundo_Classe": "00.332.266/0001-31",
        "Data_Referencia": "2026-01-01",
        "Nome_Fundo_Classe": "MAXI RENDA FUNDO DE INVESTIMENTO",
        "Quantidade_Cotas_Emitidas": "500",
    }


def test_extrai_colunas_reais_nao_legadas():
    extraido = extrair_campos_inf_mensal(linha_complemento())
    assert extraido["cnpj_fundo"] == "00.332.266/0001-31"
    assert extraido["data_referencia"] == "2026-01-01"
    assert extraido["patrimonio_liquido"] == "1000.50"
    assert extraido["ativo_total"] == "1100.00"
    assert extraido["cotas_emitidas"] == "500"
    assert extraido["cotistas"] == "10"
    assert "rendimento_por_cota" not in extraido
    assert "vacancia_fisica" not in extraido
    assert "valor_patrimonial_cotas" not in extraido
    assert "percentual_dividend_yield_mes" not in extraido


def test_linha_sem_cnpj_ou_data_e_ignorada():
    assert extrair_campos_inf_mensal({"Patrimonio_Liquido": "1"}) is None
    assert extrair_campos_inf_mensal({"CNPJ_Fundo_Classe": "29.265.280/0001-40"}) is None


def test_aliases_legados_ainda_sao_lidos():
    extraido = extrair_campos_inf_mensal(
        {
            "CNPJ_Fundo": "00.332.266/0001-31",
            "DT_COMPTC": "2026-02-01",
            "VL_PATRIM_LIQ": "9",
            "NR_COTISTAS": "3",
            "DENOM_SOCIAL": "MAXI RENDA",
        }
    )
    assert extraido["patrimonio_liquido"] == "9"
    assert extraido["cotistas"] == "3"
    assert extraido["nome"] == "MAXI RENDA"


def test_campos_ausentes_no_csv_permanecem_pendentes():
    for campo in (
        "rendimento_por_cota",
        "vacancia_fisica",
        "vacancia_financeira",
        "resultado_ligado_venda",
    ):
        assert campo in CAMPOS_CVM_AUSENTES_NO_CSV
    assert "receita_imoveis" not in CAMPOS_CVM_AUSENTES_NO_CSV
    assert "despesas_taxas" not in CAMPOS_CVM_AUSENTES_NO_CSV


def test_consolidacao_nao_inventa_zero():
    dados, nomes = consolidar_linhas_inf_mensal(
        [linha_complemento(), linha_ativo_passivo(), linha_geral()]
    )
    chave = ("00.332.266/0001-31", "2026-01-01")
    assert dados[chave]["disponibilidades_caixa"] == "25.00"
    assert dados[chave]["patrimonio_liquido"] == "1000.50"
    assert "vacancia_fisica" not in dados[chave]
    assert nomes[chave] == "MAXI RENDA FUNDO DE INVESTIMENTO"


def test_persistencia_cvm_preenche_cotas_e_nao_inventa_vacancia():
    session = _sessao()
    registrar_no_catalogo(
        session, "MXRF11", TipoAtivo.FII, cnpj="00.332.266/0001-31", nome_emissor="MAXI RENDA"
    )
    garantir_ativo(session, "MXRF11", TipoAtivo.FII, cnpj="00.332.266/0001-31")
    session.commit()
    dados, nomes = consolidar_linhas_inf_mensal(
        [linha_complemento(), linha_ativo_passivo(), linha_geral()]
    )
    gravados = persistir_informes_fiis(session, dados, nomes, "https://dados.cvm.gov.br/x.zip")
    session.commit()
    assert gravados == 1
    registro = session.query(DadosFinanceirosFiis).one()
    ativo = session.query(Ativo).filter_by(ticker="MXRF11").one()
    assert registro.ativo_id == ativo.id
    assert registro.data_referencia == date(2026, 1, 1)
    assert registro.patrimonio_liquido == 1000.50
    assert registro.ativo_total == 1100.00
    assert registro.cotas_emitidas == 500.0
    assert registro.cotistas == 10
    assert registro.disponibilidades_caixa == 25.00
    assert registro.vacancia_fisica is None
    assert registro.rendimento_por_cota is None
    assert registro.receita_imoveis is None
    assert registro.valor_patrimonial_cotas is None
    assert registro.percentual_dividend_yield_mes is None
    session.close()
