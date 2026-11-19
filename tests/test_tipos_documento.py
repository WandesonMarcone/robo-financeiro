import unittest

from pipeline_dados.tipos_documento import normalizar_tipo_documento, tipo_por_assunto_acao


class TestTiposDocumentoAcao(unittest.TestCase):
    def test_itr_e_dfp_sao_demonstracoes_financeiras(self):
        for bruto in (
            "ITR",
            "DFP",
            "Informações Trimestrais",
            "Demonstrações Financeiras Trimestrais",
            "Demonstrações Financeiras Padronizadas",
        ):
            self.assertEqual(
                normalizar_tipo_documento(bruto, "ACAO"),
                "Demonstracoes Financeiras",
            )

    def test_resultado_trimestral_e_apresentacao(self):
        self.assertEqual(
            normalizar_tipo_documento("Resultados Trimestrais", "ACAO"),
            "Apresentação de Resultados",
        )

    def test_apresentacao_do_resultado_e_reclassificada_pelo_assunto(self):
        self.assertEqual(
            tipo_por_assunto_acao("Apresentação do Resultado 2T26"),
            "Apresentação de Resultados",
        )
        self.assertIsNone(tipo_por_assunto_acao("Apresentação Institucional 1T26"))


if __name__ == "__main__":
    unittest.main()
