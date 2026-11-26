import io
import unittest
import zipfile
from datetime import date

from services.fundamentos_valuation import (
    _metrica,
    avaliar_cobertura,
    derivar_indicadores,
    extrair_demonstracoes_cvm,
)


def _zip_dfp(ano=2025):
    campos = "CNPJ_CIA;DT_REFER;DT_INI_EXERC;DT_FIM_EXERC;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ESCALA_MOEDA\n"
    dre = campos + "\n".join([
        f"00.000.000/0001-91;{ano}-12-31;{ano}-01-01;{ano}-12-31;ÚLTIMO;3.01;Receita;1000;MIL",
        f"00.000.000/0001-91;{ano}-12-31;{ano}-01-01;{ano}-12-31;ÚLTIMO;3.05;Resultado antes do financeiro;200;MIL",
        f"00.000.000/0001-91;{ano}-12-31;{ano}-01-01;{ano}-12-31;ÚLTIMO;3.11;Lucro do período;100;MIL",
        f"00.000.000/0001-91;{ano}-12-31;{ano}-01-01;{ano}-12-31;ÚLTIMO;3.99.02.01;Lucro por ação diluído;2,00;UNIDADE",
        f"11.111.111/0001-11;{ano}-12-31;{ano}-01-01;{ano}-12-31;ÚLTIMO;3.11;Outra empresa;999;MIL",
    ])
    bpp = campos + "\n".join([
        f"00.000.000/0001-91;{ano}-12-31;;{ano}-12-31;ÚLTIMO;2.03;Patrimônio Líquido;500;MIL",
        f"00.000.000/0001-91;{ano}-12-31;;{ano}-12-31;ÚLTIMO;2.01.04;Empréstimos CP;50;MIL",
        f"00.000.000/0001-91;{ano}-12-31;;{ano}-12-31;ÚLTIMO;2.02.01;Empréstimos LP;100;MIL",
    ])
    conteudo = io.BytesIO()
    with zipfile.ZipFile(conteudo, "w") as pacote:
        pacote.writestr(f"dfp_cia_aberta_DRE_con_{ano}.csv", dre.encode("latin1"))
        pacote.writestr(f"dfp_cia_aberta_BPP_con_{ano}.csv", bpp.encode("latin1"))
    return conteudo.getvalue()


def _zip_dfp_controladora(ano=2024):
    campos = "CNPJ_CIA;DT_REFER;DT_INI_EXERC;DT_FIM_EXERC;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ESCALA_MOEDA\n"
    dre = campos + "\n".join([
        f"00.000.000/0001-91;{ano}-12-31;{ano}-01-01;{ano}-12-31;ÚLTIMO;3.11;Lucro/Prejuízo Consolidado do Período;29171;MIL",
        f"00.000.000/0001-91;{ano}-12-31;{ano}-01-01;{ano}-12-31;ÚLTIMO;3.11.01;Atribuído a Sócios da Empresa Controladora;26480;MIL",
        f"00.000.000/0001-91;{ano}-12-31;{ano}-01-01;{ano}-12-31;ÚLTIMO;3.11.02;Atribuído a Sócios Não Controladores;2691;MIL",
        f"00.000.000/0001-91;{ano}-12-31;{ano}-01-01;{ano}-12-31;ÚLTIMO;3.99;Lucro por Ação;4,62;UNIDADE",
    ])
    conteudo = io.BytesIO()
    with zipfile.ZipFile(conteudo, "w") as pacote:
        pacote.writestr(f"dfp_cia_aberta_DRE_con_{ano}.csv", dre.encode("latin1"))
    return conteudo.getvalue()


class FundamentosValuationTest(unittest.TestCase):
    def test_plano_bancario_nao_confunde_provisoes_com_patrimonio(self):
        self.assertIsNone(_metrica("2.03", "Provisões"))
        self.assertEqual(
            _metrica("2.07.01", "Patrimônio Líquido Atribuído ao Controlador"),
            "patrimonio_liquido",
        )
        self.assertEqual(_metrica("3.99", "Lucro por Ação (R$/Ação)"), "lpa_diluido")

    def test_extrai_somente_cnpj_e_respeita_escala(self):
        fatos = extrair_demonstracoes_cvm(
            _zip_dfp(), "BBAS3", "00.000.000/0001-91", "DFP", 2025,
        )
        mapa = {item["metrica"]: item for item in fatos}
        self.assertEqual(mapa["lucro_liquido"]["valor"], 100_000)
        self.assertEqual(mapa["lpa_diluido"]["valor"], 2.0)
        self.assertEqual(mapa["patrimonio_liquido"]["valor"], 500_000)
        self.assertTrue(all(item["ticker"] == "BBAS3" for item in fatos))

    def test_prioriza_lucro_atribuido_a_controladora(self):
        fatos = extrair_demonstracoes_cvm(
            _zip_dfp_controladora(), "BBAS3", "00.000.000/0001-91", "DFP", 2024,
        )
        mapa = {item["metrica"]: item for item in fatos}
        self.assertEqual(mapa["lucro_liquido"]["valor"], 26_480_000)
        self.assertEqual(mapa["lucro_liquido"]["conta_codigo"], "3.11.01")

    def test_nao_le_lpa_de_fluxo_de_caixa_por_descricao(self):
        campos = "CNPJ_CIA;DT_REFER;DT_INI_EXERC;DT_FIM_EXERC;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ESCALA_MOEDA\n"
        dfc = campos + "00.000.000/0001-91;2025-12-31;2025-01-01;2025-12-31;ÚLTIMO;6.01.01.05;Lucro por Ação Diluído;99877;UNIDADE\n"
        conteudo = io.BytesIO()
        with zipfile.ZipFile(conteudo, "w") as pacote:
            pacote.writestr("dfp_cia_aberta_DFC_MI_con_2025.csv", dfc.encode("latin1"))
        fatos = extrair_demonstracoes_cvm(
            conteudo.getvalue(), "TEST3", "00.000.000/0001-91", "DFP", 2025,
        )
        self.assertNotIn("lpa_diluido", {f["metrica"] for f in fatos})

    def test_deriva_lpa_vpa_payout_crescimento_e_divida(self):
        fundamentos = []
        proventos = []
        for ano in range(2021, 2026):
            periodo = date(ano, 12, 31)
            valores = {
                "lucro_liquido": 100_000 + (ano - 2021) * 10_000,
                "lpa_diluido": 2 + (ano - 2021) * 0.2,
                "patrimonio_liquido": 500_000,
                "divida_curto_prazo": 50_000,
                "divida_longo_prazo": 100_000,
                "caixa_equivalentes": 20_000,
            }
            for metrica, valor in valores.items():
                fundamentos.append({"periodo_fim": periodo, "periodicidade": "ANUAL", "metrica": metrica, "valor": valor})
            proventos.append({"data_ex": date(ano, 6, 1), "valor_unitario": 1.0})
        indicadores = derivar_indicadores("BBAS3", "ACAO", fundamentos, proventos)
        nomes = {item["indicador"] for item in indicadores}
        self.assertTrue({"lpa", "vpa", "roe", "dpa", "payout", "crescimento_lpa_5a", "divida_liquida"} <= nomes)

    def test_normaliza_lpa_anterior_ao_desdobramento(self):
        fundamentos = [
            {"periodo_fim": date(2023, 12, 31), "periodicidade": "ANUAL", "metrica": "lpa_diluido", "valor": 10.0},
            {"periodo_fim": date(2024, 12, 31), "periodicidade": "ANUAL", "metrica": "lpa_diluido", "valor": 6.0},
        ]
        eventos = [{
            "data_referencia": date(2024, 4, 15),
            "tipo": "DESDOBRAMENTO_OU_GRUPAMENTO",
            "fator": 2.0,
        }]
        indicadores = derivar_indicadores(
            "BBAS3", "ACAO", fundamentos, eventos=eventos,
        )
        lpas = {
            item["exercicio"]: item["valor"]
            for item in indicadores if item["indicador"] == "lpa"
        }
        self.assertEqual(lpas[2023], 5.0)
        self.assertEqual(lpas[2024], 6.0)

    def test_banco_bloqueia_fcff_e_preserva_fcfe(self):
        periodo = date(2025, 12, 31)
        indicadores = [
            {"periodo_fim": periodo, "indicador": metrica}
            for metrica in {
                "receita_liquida", "ebit", "taxa_imposto_efetiva", "depreciacao_amortizacao",
                "capex", "variacao_capital_giro", "divida_liquida", "acoes_media_diluida",
                "fluxo_caixa_operacional", "captacao_liquida_divida",
            }
        ]
        cobertura = avaliar_cobertura("BBAS3", "ACAO", [], indicadores, setor="Bancos e serviços financeiros")
        por_metodo = {item["metodo"]: item for item in cobertura}
        self.assertEqual(por_metodo["DCF_FCFF"]["status"], "NAO_APLICAVEL")
        self.assertEqual(por_metodo["DCF_FCFE"]["status"], "PARCIAL")


if __name__ == "__main__":
    unittest.main()
