import unittest

from services.universo_acoes import sincronizar_universo


class Sessao:
    def __init__(self):
        self.sql = []

    def execute(self, consulta, parametros=None):
        self.sql.append((str(consulta), parametros))


class UniversoAcoesTests(unittest.TestCase):
    def test_saida_da_planilha_desativa_sem_apagar_historico(self):
        sessao = Sessao()
        sincronizar_universo(sessao, {"PETR4", "VALE3"})
        texto = "\n".join(sql for sql, _ in sessao.sql)
        self.assertIn("SET ativo=FALSE", texto)
        self.assertIn("desativado_em=COALESCE", texto)
        self.assertNotIn("DELETE FROM universo_acoes_autorizadas", texto)
        self.assertIn("WHERE ativo=TRUE", texto)


if __name__ == "__main__":
    unittest.main()
