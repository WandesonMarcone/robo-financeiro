import os
import unittest
from unittest.mock import Mock, patch

from services.github_actions import disparar_fundamentos_valuation


class GithubFundamentosDispatchTest(unittest.TestCase):
    @patch("services.github_actions.requests.post")
    def test_envia_ticker_e_cinco_anos(self, post):
        post.return_value = Mock(status_code=204, text="")
        with patch.dict(os.environ, {"GITHUB_ACTIONS_TOKEN": "segredo", "GITHUB_REPOSITORY": "dono/repo"}, clear=False):
            ok, mensagem = disparar_fundamentos_valuation("bbas3", 5)
        self.assertTrue(ok)
        self.assertIn("enfileirada", mensagem)
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["json"]["inputs"], {"ticker": "BBAS3", "anos": "5"})
        self.assertTrue(post.call_args.args[0].endswith("/fundamentos-valuation.yml/dispatches"))

    def test_rejeita_periodo_invalido(self):
        ok, mensagem = disparar_fundamentos_valuation("BBAS3", "abc")
        self.assertFalse(ok)
        self.assertIn("3, 4 ou 5", mensagem)


if __name__ == "__main__":
    unittest.main()


class GithubOpportunitiesDispatchTest(unittest.TestCase):
    @patch("services.github_actions.requests.post")
    def test_dispara_varredura_unificada_sem_classe(self, post):
        from services.github_actions import disparar_oportunidades_unificadas

        post.return_value = Mock(status_code=204, text="")
        with patch.dict(os.environ, {"GITHUB_ACTIONS_TOKEN": "segredo", "GITHUB_REPOSITORY": "dono/repo"}, clear=False):
            ok, mensagem = disparar_oportunidades_unificadas()
        self.assertTrue(ok)
        self.assertIn("Varredura completa", mensagem)
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["json"]["inputs"], {"modo": "oportunidades"})
        self.assertTrue(post.call_args.args[0].endswith("/mercado-oportunidades.yml/dispatches"))
