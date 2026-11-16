import unittest

from modules.resiliencia_planilha import executar_gravacao_com_retentativa


class AbaInstavel:
    def __init__(self, falhas):
        self.falhas = falhas
        self.chamadas = 0

    def gravar(self):
        self.chamadas += 1
        if self.chamadas <= self.falhas:
            raise ConnectionError("conexão encerrada pelo servidor")


class GravacaoPlanilhaTests(unittest.TestCase):
    def test_repete_gravacao_quando_conexao_e_interrompida(self):
        aba = AbaInstavel(falhas=2)
        pausas = []

        resultado = executar_gravacao_com_retentativa(
            aba.gravar, "FIIs", sleep=pausas.append,
        )

        self.assertTrue(resultado)
        self.assertEqual(aba.chamadas, 3)
        self.assertEqual(pausas, [2, 4])

    def test_preserva_lote_quando_todas_as_tentativas_falham(self):
        aba = AbaInstavel(falhas=10)

        resultado = executar_gravacao_com_retentativa(
            aba.gravar, "FIIs", sleep=lambda _: None,
        )

        self.assertFalse(resultado)
        self.assertEqual(aba.chamadas, 4)


if __name__ == "__main__":
    unittest.main()
