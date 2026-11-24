import unittest
from unittest.mock import patch

from scripts.notificar_falha_workflow import mensagem


class TesteNotificacaoFalhaWorkflow(unittest.TestCase):
    def test_informa_etapa_que_realmente_falhou(self):
        ambiente = {
            "GITHUB_WORKFLOW": "Documentos — descoberta e processamento",
            "GITHUB_REPOSITORY": "WandesonMarcone/robo-financeiro",
            "GITHUB_RUN_ID": "123",
            "ETAPA_FALHA": "processamento de documentos pendentes",
        }
        with patch.dict("os.environ", ambiente, clear=True):
            texto = mensagem()

        self.assertIn("Etapa: processamento de documentos pendentes.", texto)
        self.assertIn("/actions/runs/123", texto)


if __name__ == "__main__":
    unittest.main()
