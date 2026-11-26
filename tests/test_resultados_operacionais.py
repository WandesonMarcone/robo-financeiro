import unittest

from services.resultados_operacionais import (
    FALHOU,
    PARCIAL,
    SUCESSO_TOTAL,
    classificar_resultado,
)


class ResultadosOperacionaisTests(unittest.TestCase):
    def test_sucesso_total_nao_tem_falhas_nem_pendencias(self):
        self.assertEqual(SUCESSO_TOTAL, classificar_resultado(processados=4))

    def test_parcial_preserva_itens_processados(self):
        self.assertEqual(PARCIAL, classificar_resultado(processados=3, falhas=1))
        self.assertEqual(PARCIAL, classificar_resultado(processados=0, pendentes=2))

    def test_falha_quando_nenhum_item_foi_processado(self):
        self.assertEqual(FALHOU, classificar_resultado(processados=0, falhas=2))


if __name__ == "__main__":
    unittest.main()
