"""Fase 8 Etapa 9: INF_MENSAL VPA/DY, INF_TRIMESTRAL receita/taxas, ITR+DFP."""
from datetime import date

import pandas as pd
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import (
    Ativo,
    Base,
    DadosFinanceirosAcoes,
    DadosFinanceirosFiis,
    TipoAtivo,
    garantir_colunas_cvm_fii,
)
from pipeline_dados.catalogo_ativos import garantir_ativo, registrar_no_catalogo
from pipeline_dados.coletor_cvm import AcoesCVMReader
from pipeline_dados.coletor_fiis import (
    CAMPOS_CVM_AUSENTES_NO_CSV,
    CAMPOS_INF_MENSAL_SEM_DESTINO_ORM,
    consolidar_linhas_inf_mensal,
    consolidar_linhas_inf_trimestral,
    extrair_campos_inf_mensal,
    extrair_campos_inf_trimestral,
    persistir_informes_fiis,
    persistir_informes_trimestrais_fiis,
)
from pipeline_dados.numerico import parsear_percentual


def _sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def _catalogar_mxrf(session):
    registrar_no_catalogo(
        session, "MXRF11", TipoAtivo.FII, cnpj="00.332.266/0001-31", nome_emissor="MAXI RENDA"
    )
    garantir_ativo(session, "MXRF11", TipoAtivo.FII, cnpj="00.332.266/0001-31")
    session.commit()


def linha_mensal_completa():
    return {
        "CNPJ_Fundo_Classe": "00.332.266/0001-31",
        "Data_Referencia": "2026-01-01",
        "Patrimonio_Liquido": "1000.50",
        "Valor_Ativo": "1100.00",
        "Cotas_Emitidas": "500",
        "Total_Numero_Cotistas": "10",
        "Valor_Patrimonial_Cotas": "10.39",
        "Percentual_Dividend_Yield_Mes": "0.004342",
        "Nome_Fundo_Classe": "MAXI RENDA FUNDO DE INVESTIMENTO",
    }


def linha_trimestral():
    return {
        "CNPJ_Fundo_Classe": "00.332.266/0001-31",
        "Data_Referencia": "2026-03-31",
        "Receita_Aluguel_Investimento_Contabil": "120000.00",
        "Taxa_Administracao_Contabil": "8500.00",
        "Receita_Venda_Imoveis_Contabil": "30000.00",
        "Resultado_Venda_TVM_Contabil": "4000.00",
        "Nome_Fundo_Classe": "MAXI RENDA FUNDO DE INVESTIMENTO",
    }


def test_inf_mensal_mapeia_vpa_e_dy_fracao():
    extraido = extrair_campos_inf_mensal(linha_mensal_completa())
    assert extraido["valor_patrimonial_cotas"] == "10.39"
    assert extraido["percentual_dividend_yield_mes"] == "0.004342"
    assert parsear_percentual(extraido["percentual_dividend_yield_mes"]) == 0.004342
    assert "rendimento_por_cota" not in extraido
    assert "vacancia_fisica" not in extraido


def test_inf_mensal_ausencia_vpa_dy_nao_vira_zero():
    extraido = extrair_campos_inf_mensal(
        {
            "CNPJ_Fundo_Classe": "00.332.266/0001-31",
            "Data_Referencia": "2026-01-01",
            "Patrimonio_Liquido": "1000.50",
        }
    )
    assert "valor_patrimonial_cotas" not in extraido
    assert "percentual_dividend_yield_mes" not in extraido


def test_inf_mensal_zero_real_de_vpa_e_dy_preservado():
    extraido = extrair_campos_inf_mensal(
        {
            "CNPJ_Fundo_Classe": "00.332.266/0001-31",
            "Data_Referencia": "2026-01-01",
            "Valor_Patrimonial_Cotas": "0",
            "Percentual_Dividend_Yield_Mes": "0",
        }
    )
    assert extraido["valor_patrimonial_cotas"] == "0"
    assert extraido["percentual_dividend_yield_mes"] == "0"


def test_persistencia_mensal_grava_vpa_dy_e_nao_inventa_vacancia():
    session, _ = _sessao()
    _catalogar_mxrf(session)
    dados, nomes = consolidar_linhas_inf_mensal([linha_mensal_completa()])
    gravados = persistir_informes_fiis(session, dados, nomes, "https://dados.cvm.gov.br/x.zip")
    session.commit()
    assert gravados == 1
    registro = session.query(DadosFinanceirosFiis).one()
    assert registro.valor_patrimonial_cotas == 10.39
    assert registro.percentual_dividend_yield_mes == 0.004342
    assert registro.vacancia_fisica is None
    assert registro.rendimento_por_cota is None
    assert registro.resultado_ligado_venda is None
    assert registro.fonte_primaria == "CVM/INF_MENSAL"
    session.close()


def test_persistencia_mensal_nao_grava_zero_quando_coluna_ausente():
    session, _ = _sessao()
    _catalogar_mxrf(session)
    dados, nomes = consolidar_linhas_inf_mensal(
        [
            {
                "CNPJ_Fundo_Classe": "00.332.266/0001-31",
                "Data_Referencia": "2026-01-01",
                "Patrimonio_Liquido": "1000.50",
                "Nome_Fundo_Classe": "MAXI RENDA FUNDO DE INVESTIMENTO",
            }
        ]
    )
    persistir_informes_fiis(session, dados, nomes, "https://dados.cvm.gov.br/x.zip")
    session.commit()
    registro = session.query(DadosFinanceirosFiis).one()
    assert registro.patrimonio_liquido == 1000.50
    assert registro.valor_patrimonial_cotas is None
    assert registro.percentual_dividend_yield_mes is None
    session.close()


def test_persistencia_mensal_preserva_zero_real():
    session, _ = _sessao()
    _catalogar_mxrf(session)
    dados, nomes = consolidar_linhas_inf_mensal(
        [
            {
                "CNPJ_Fundo_Classe": "00.332.266/0001-31",
                "Data_Referencia": "2026-01-01",
                "Valor_Patrimonial_Cotas": "0",
                "Percentual_Dividend_Yield_Mes": "0",
                "Nome_Fundo_Classe": "MAXI RENDA FUNDO DE INVESTIMENTO",
            }
        ]
    )
    persistir_informes_fiis(session, dados, nomes, "https://dados.cvm.gov.br/x.zip")
    session.commit()
    registro = session.query(DadosFinanceirosFiis).one()
    assert registro.valor_patrimonial_cotas == 0.0
    assert registro.percentual_dividend_yield_mes == 0.0
    session.close()


def test_inf_trimestral_mapeia_aluguel_e_taxa_nao_venda():
    extraido = extrair_campos_inf_trimestral(linha_trimestral())
    assert extraido["receita_imoveis"] == "120000.00"
    assert extraido["despesas_taxas"] == "8500.00"
    assert "resultado_ligado_venda" not in extraido
    assert "Receita_Venda_Imoveis_Contabil" not in extraido


def test_inf_trimestral_nao_confunde_receita_venda_com_resultado():
    extraido = extrair_campos_inf_trimestral(
        {
            "CNPJ_Fundo_Classe": "00.332.266/0001-31",
            "Data_Referencia": "2026-03-31",
            "Receita_Venda_Imoveis_Contabil": "30000.00",
            "Resultado_Venda_TVM_Contabil": "4000.00",
        }
    )
    assert extraido is not None
    assert "receita_imoveis" not in extraido
    assert "resultado_ligado_venda" not in extraido
    assert "despesas_taxas" not in extraido


def test_persistencia_trimestral_grava_receita_e_taxas():
    session, _ = _sessao()
    _catalogar_mxrf(session)
    dados, nomes = consolidar_linhas_inf_trimestral([linha_trimestral()])
    gravados = persistir_informes_trimestrais_fiis(
        session, dados, nomes, "https://dados.cvm.gov.br/trim.zip"
    )
    session.commit()
    assert gravados == 1
    registro = session.query(DadosFinanceirosFiis).one()
    assert registro.receita_imoveis == 120000.00
    assert registro.despesas_taxas == 8500.00
    assert registro.resultado_ligado_venda is None
    assert registro.vacancia_fisica is None
    assert registro.fonte_primaria == "CVM/INF_TRIMESTRAL"
    session.close()


def test_trimestral_nao_sobrescreve_mensal_quando_campo_ausente():
    session, _ = _sessao()
    _catalogar_mxrf(session)
    dados_m, nomes_m = consolidar_linhas_inf_mensal(
        [
            {
                "CNPJ_Fundo_Classe": "00.332.266/0001-31",
                "Data_Referencia": "2026-03-31",
                "Patrimonio_Liquido": "2000.00",
                "Valor_Patrimonial_Cotas": "11.20",
                "Nome_Fundo_Classe": "MAXI RENDA FUNDO DE INVESTIMENTO",
            }
        ]
    )
    persistir_informes_fiis(session, dados_m, nomes_m, "https://dados.cvm.gov.br/x.zip")
    session.commit()
    dados_t, nomes_t = consolidar_linhas_inf_trimestral(
        [
            {
                "CNPJ_Fundo_Classe": "00.332.266/0001-31",
                "Data_Referencia": "2026-03-31",
                "Receita_Aluguel_Investimento_Contabil": "5000.00",
                "Nome_Fundo_Classe": "MAXI RENDA FUNDO DE INVESTIMENTO",
            }
        ]
    )
    persistir_informes_trimestrais_fiis(
        session, dados_t, nomes_t, "https://dados.cvm.gov.br/trim.zip"
    )
    session.commit()
    registro = session.query(DadosFinanceirosFiis).one()
    assert registro.patrimonio_liquido == 2000.00
    assert registro.valor_patrimonial_cotas == 11.20
    assert registro.receita_imoveis == 5000.00
    assert registro.despesas_taxas is None
    session.close()


def test_campos_trimestrais_nao_estao_ausentes_no_mensal_list():
    assert "receita_imoveis" in CAMPOS_INF_MENSAL_SEM_DESTINO_ORM
    assert "despesas_taxas" in CAMPOS_INF_MENSAL_SEM_DESTINO_ORM
    assert "resultado_ligado_venda" in CAMPOS_CVM_AUSENTES_NO_CSV
    assert "receita_imoveis" not in CAMPOS_CVM_AUSENTES_NO_CSV


def test_garantir_colunas_cvm_fii_idempotente():
    _, engine = _sessao()
    assert garantir_colunas_cvm_fii(engine) == 0
    nomes = {c["name"] for c in inspect(engine).get_columns("dados_financeiros_fiis")}
    assert "valor_patrimonial_cotas" in nomes
    assert "percentual_dividend_yield_mes" in nomes


def test_serializacao_fii_expoe_vpa_dy_trimestral():
    from api.serializadores import serializar_dados_financeiros

    session, _ = _sessao()
    _catalogar_mxrf(session)
    ativo = session.query(Ativo).filter_by(ticker="MXRF11").one()
    registro = DadosFinanceirosFiis(
        ativo_id=ativo.id,
        data_referencia=date(2026, 1, 1),
        valor_patrimonial_cotas=10.39,
        percentual_dividend_yield_mes=0.004342,
        receita_imoveis=120000.0,
        despesas_taxas=8500.0,
        resultado_ligado_venda=None,
    )
    session.add(registro)
    session.commit()
    dados = serializar_dados_financeiros(registro)
    assert dados["valor_patrimonial_cotas"] == 10.39
    assert dados["percentual_dividend_yield_mes"] == 0.004342
    assert dados["receita_imoveis"] == 120000.0
    assert dados["despesas_taxas"] == 8500.0
    assert dados["resultado_ligado_venda"] is None
    session.close()


def _df_contas(linhas):
    return pd.DataFrame(linhas)


def test_processar_itr_dfp_marca_tipo_e_campos():
    session, _ = _sessao()
    registrar_no_catalogo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    garantir_ativo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    session.commit()
    leitor = AcoesCVMReader(session)
    leitor.meus_tickers = ["PETR4"]
    leitor.cnpjs_alvo = {"33000167000101"}
    df = _df_contas(
        [
            {
                "CNPJ_CIA": "33.000.167/0001-01",
                "DT_REFER": "2025-12-31",
                "ORDEM_EXERC": "ÚLTIMO",
                "CD_CONTA": "1",
                "VL_CONTA": 100.0,
            },
            {
                "CNPJ_CIA": "33.000.167/0001-01",
                "DT_REFER": "2025-12-31",
                "ORDEM_EXERC": "ÚLTIMO",
                "CD_CONTA": "2",
                "VL_CONTA": 60.0,
            },
            {
                "CNPJ_CIA": "33.000.167/0001-01",
                "DT_REFER": "2025-12-31",
                "ORDEM_EXERC": "ÚLTIMO",
                "CD_CONTA": "2.03",
                "VL_CONTA": 40.0,
            },
            {
                "CNPJ_CIA": "33.000.167/0001-01",
                "DT_REFER": "2025-12-31",
                "ORDEM_EXERC": "ÚLTIMO",
                "CD_CONTA": "1.01.01",
                "VL_CONTA": 5.0,
            },
            {
                "CNPJ_CIA": "33.000.167/0001-01",
                "DT_REFER": "2025-12-31",
                "ORDEM_EXERC": "ÚLTIMO",
                "CD_CONTA": "3.01",
                "VL_CONTA": 80.0,
            },
            {
                "CNPJ_CIA": "33.000.167/0001-01",
                "DT_REFER": "2025-12-31",
                "ORDEM_EXERC": "ÚLTIMO",
                "CD_CONTA": "3.11",
                "VL_CONTA": 12.0,
            },
        ]
    )
    regs = leitor._processar_itr_dfp({"bpa": df}, tipo_doc="DFP")
    assert len(regs) == 1
    reg = regs[0]
    assert reg["tipo_doc"] == "DFP"
    assert reg["ativo_total"] == 100000.0
    assert reg["passivo_total"] == 60000.0
    assert reg["patrimonio_liquido"] == 40000.0
    assert reg["caixa"] == 5000.0
    assert reg["receita"] == 80000.0
    assert reg["lucro_liquido"] == 12000.0
    session.close()


def test_itr_e_dfp_coexistem_por_periodo():
    session, _ = _sessao()
    registrar_no_catalogo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    garantir_ativo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    session.commit()
    leitor = AcoesCVMReader(session)
    leitor.meus_tickers = ["PETR4"]
    leitor.cnpjs_alvo = {"33000167000101"}
    df_itr = _df_contas(
        [
            {
                "CNPJ_CIA": "33.000.167/0001-01",
                "DT_REFER": "2025-09-30",
                "ORDEM_EXERC": "ÚLTIMO",
                "CD_CONTA": "1",
                "VL_CONTA": 90.0,
            },
            {
                "CNPJ_CIA": "33.000.167/0001-01",
                "DT_REFER": "2025-09-30",
                "ORDEM_EXERC": "ÚLTIMO",
                "CD_CONTA": "3.11",
                "VL_CONTA": 10.0,
            },
        ]
    )
    df_dfp = _df_contas(
        [
            {
                "CNPJ_CIA": "33.000.167/0001-01",
                "DT_REFER": "2025-12-31",
                "ORDEM_EXERC": "ÚLTIMO",
                "CD_CONTA": "1",
                "VL_CONTA": 100.0,
            },
            {
                "CNPJ_CIA": "33.000.167/0001-01",
                "DT_REFER": "2025-12-31",
                "ORDEM_EXERC": "ÚLTIMO",
                "CD_CONTA": "3.11",
                "VL_CONTA": 12.0,
            },
        ]
    )
    itr = leitor._processar_itr_dfp({"bpa": df_itr}, tipo_doc="ITR")
    dfp = leitor._processar_itr_dfp({"bpa": df_dfp}, tipo_doc="DFP")
    leitor._salvar_no_banco(itr, url_origem="https://dados.cvm.gov.br/itr.zip")
    leitor._salvar_no_banco(dfp, url_origem="https://dados.cvm.gov.br/dfp.zip")
    registros = session.query(DadosFinanceirosAcoes).order_by(
        DadosFinanceirosAcoes.data_referencia
    ).all()
    assert [r.tipo_doc for r in registros] == ["ITR", "DFP"]
    assert registros[0].data_referencia == date(2025, 9, 30)
    assert registros[1].data_referencia == date(2025, 12, 31)
    assert registros[0].fonte_primaria == "CVM/ITR"
    assert registros[1].fonte_primaria == "CVM/DFP"
    session.close()


def test_salvar_dfp_nao_substitui_valor_valido_por_null():
    session, _ = _sessao()
    registrar_no_catalogo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    ativo = garantir_ativo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    session.commit()
    session.add(
        DadosFinanceirosAcoes(
            ativo_id=ativo.id,
            data_referencia=date(2025, 12, 31),
            tipo_doc="DFP",
            ativo_total=100000.0,
            receita=80000.0,
            lucro_liquido=12000.0,
        )
    )
    session.commit()
    leitor = AcoesCVMReader(session)
    leitor.meus_tickers = ["PETR4"]
    leitor.cnpjs_alvo = {"33000167000101"}
    parcial = [
        {
            "cnpj": "33.000.167/0001-01",
            "data_referencia": date(2025, 12, 31),
            "tipo_doc": "DFP",
            "ativo_total": 110000.0,
            "patrimonio_liquido": None,
            "caixa": None,
            "passivo_total": None,
            "divida_curto_prazo": None,
            "divida_longo_prazo": None,
            "divida_bruta": None,
            "divida_liquida": None,
            "receita": None,
            "lucro_bruto": None,
            "resultado_financeiro": None,
            "lucro_liquido": 15000.0,
            "ebitda": None,
            "fco": None,
        }
    ]
    leitor._salvar_no_banco(parcial, url_origem="https://dados.cvm.gov.br/dfp.zip")
    registro = session.query(DadosFinanceirosAcoes).one()
    assert registro.ativo_total == 110000.0
    assert registro.lucro_liquido == 15000.0
    assert registro.receita == 80000.0
    session.close()


def test_atualizar_acoes_orquestra_itr_e_dfp(monkeypatch):
    session, _ = _sessao()
    registrar_no_catalogo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    garantir_ativo(session, "PETR4", TipoAtivo.ACAO, cnpj="33.000.167/0001-01")
    session.commit()
    leitor = AcoesCVMReader(session)
    leitor.cnpjs_alvo = {"33000167000101"}
    chamadas = []

    def fake_atualizar(ano, tipo_doc, url_template, prefixo):
        chamadas.append((tipo_doc, prefixo, url_template))

    monkeypatch.setattr(leitor, "_atualizar_documento", fake_atualizar)
    leitor.atualizar_acoes(2025)
    assert [c[0] for c in chamadas] == ["ITR", "DFP", "DFP"]
    assert [c[1] for c in chamadas] == ["itr", "dfp", "dfp"]
    assert "ITR/DADOS" in chamadas[0][2]
    assert "DFP/DADOS" in chamadas[1][2]
    session.close()
