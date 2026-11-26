import sys
import types
import unittest
from unittest.mock import patch

from services import coletor_tesouro_direto as coletor


class _Sessao:
    def execute(self, *_args):
        return None

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


class _Resposta:
    content = (
        b"Data Base;Tipo Titulo;Data Vencimento;Taxa Compra Manha\n"
        b"25/11/2026;Tesouro Selic;01/03/2031;10,00\n"
    )

    def raise_for_status(self):
        return None


class TesouroFallbackTests(unittest.TestCase):
    def test_tenta_novamente_fonte_oficial(self):
        chamadas = []

        def get(url, **_kwargs):
            chamadas.append(url)
            if len(chamadas) == 1:
                raise coletor.requests.ConnectionError("reset TLS")
            return _Resposta()

        with patch.object(coletor.requests, "get", side_effect=get), patch.object(
            coletor.time, "sleep"
        ):
            resultado = coletor.coletar_tesouro_direto(session_factory=_Sessao)

        self.assertEqual(1, resultado["gravadas"])
        self.assertEqual(coletor.URLS_TESOURO[0], resultado["url_fonte"])
        self.assertEqual(2, len(chamadas))


if __name__ == "__main__":
    unittest.main()
