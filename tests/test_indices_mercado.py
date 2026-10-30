import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from modules.utils import buscar_ohlc_diario_yahoo, buscar_indices_b3_ohlc
from pipeline_dados.repositorio_indices import persistir_indices_diarios


class _TickerFake:
    def __init__(self, historico):
        self._historico = historico

    def history(self, **kwargs):
        return self._historico


class _SessaoFake:
    def __init__(self):
        self.comandos = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def execute(self, comando, parametros):
        self.comandos.append((comando, parametros))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class _FabricaFake:
    def __init__(self, sessao):
        self.sessao = sessao

    def __call__(self):
        return self.sessao


class IndicesMercadoTest(unittest.TestCase):
    def setUp(self):
        self.historico = pd.DataFrame(
            {
                "Open": [100.0, 110.0],
                "High": [105.0, 120.0],
                "Low": [95.0, 108.0],
                "Close": [102.0, 115.0],
            },
            index=pd.to_datetime(["2026-10-29", "2026-10-30"]),
        )

    def test_le_ohlc_diario_e_fechamento_anterior(self):
        registro = buscar_ohlc_diario_yahoo(
            "IFIX.SA", ticker_factory=lambda _simbolo: _TickerFake(self.historico)
        )
        self.assertEqual(registro["data_pregao"], date(2026, 10, 30))
        self.assertEqual(registro["maxima"], 120.0)
        self.assertEqual(registro["minima"], 108.0)
        self.assertEqual(registro["fechamento"], 115.0)
        self.assertEqual(registro["fechamento_anterior"], 102.0)

    def test_monta_os_dois_indices(self):
        registros = buscar_indices_b3_ohlc(
            ticker_factory=lambda _simbolo: _TickerFake(self.historico)
        )
        self.assertEqual([r["indice"] for r in registros], ["IFIX", "Ibovespa"])

    def test_persistencia_faz_upsert_sem_aplicar_migracao(self):
        sessao = _SessaoFake()
        resultado = persistir_indices_diarios(
            [{"indice": "IFIX", "fechamento": 115.0, "fonte": "teste"}],
            date(2026, 10, 30),
            session_factory=_FabricaFake(sessao),
        )
        self.assertEqual(resultado["gravados"], 1)
        self.assertEqual(len(sessao.comandos), 1)
        self.assertEqual(sessao.commits, 1)
        self.assertTrue(sessao.closed)


if __name__ == "__main__":
    unittest.main()
