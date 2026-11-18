import unittest

from pipeline_dados.tipos_documento import normalizar_tipo_documento


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


if __name__ == "__main__":
    unittest.main()
