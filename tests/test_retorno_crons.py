"""Os comandos do painel devem devolver resultado e propagar falha."""
import unittest
from unittest.mock import patch

from services import orquestrador


class Resultado:
    def mensagem_telegram(self):
        return "2 documentos processados"


class TesteRetornoCron(unittest.TestCase):
    def test_classificacao_de_acao_devolve_resumo_ao_painel(self):
        resultado = Resultado()
        with patch.object(orquestrador, "_avisar"), patch(
            "atualizador_documentos.rotina_processar_acoes", return_value=resultado
        ) as rotina:
            recebido = orquestrador.processar_ia_acoes("PETR4")
        self.assertIs(recebido, resultado)
        rotina.assert_called_once_with(ticker="PETR4")

    def test_falha_na_classificacao_nao_aparece_como_concluida(self):
        with patch.object(orquestrador, "_avisar"), patch(
            "atualizador_documentos.rotina_processar_acoes",
            side_effect=RuntimeError("fonte indisponível"),
        ):
            with self.assertRaisesRegex(RuntimeError, "fonte indisponível"):
                orquestrador.processar_ia_acoes("PETR4")


if __name__ == "__main__":
    unittest.main()
