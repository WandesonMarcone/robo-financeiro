import unittest
from datetime import datetime, timedelta, timezone

from scripts.auditar_mercado_multiclasse import executar


class Resultado:
    def __init__(self, linhas, unico=False):
        self.linhas = linhas
        self.unico = unico

    def mappings(self):
        return self

    def all(self):
        return self.linhas

    def one(self):
        return self.linhas


class Sessao:
    def __init__(self, instrumentos, macro, tesouro):
        self.resultados = iter([
            Resultado(instrumentos), Resultado(macro), Resultado(tesouro, True)
        ])

    def execute(self, *_args, **_kwargs):
        return next(self.resultados)

    def close(self):
        pass


class AuditoriaMercadoMulticlasseTests(unittest.TestCase):
    def test_coleta_de_hoje_aceita_fechamento_antigo_de_ativo_ilíquido(self):
        agora = datetime(2026, 11, 24, tzinfo=timezone.utc)
        instrumentos = [{
            "ticker": "HMRN31", "tipo": "BDR",
            "ultima_referencia": agora - timedelta(days=8),
            "ultima_coleta": agora,
        }]
        macro = [{"codigo": "IPCA", "ultima_referencia": agora - timedelta(days=54)}]
        tesouro = {"ultima_referencia": agora - timedelta(days=5), "titulos": 58}
        resultado = executar(
            session_factory=lambda: Sessao(instrumentos, macro, tesouro), agora=agora
        )
        self.assertTrue(resultado["ok"])
        self.assertEqual([], resultado["instrumentos"]["BDR"]["atrasados"])
        self.assertEqual(["HMRN31"], resultado["instrumentos"]["BDR"]["referencia_atrasada"])

    def test_sem_coleta_recente_continua_sendo_falha(self):
        agora = datetime(2026, 11, 24, tzinfo=timezone.utc)
        instrumentos = [{
            "ticker": "PARADO11", "tipo": "ETF",
            "ultima_referencia": agora - timedelta(days=1),
            "ultima_coleta": agora - timedelta(days=3),
        }]
        macro = []
        tesouro = {"ultima_referencia": agora, "titulos": 1}
        resultado = executar(
            session_factory=lambda: Sessao(instrumentos, macro, tesouro), agora=agora
        )
        self.assertFalse(resultado["ok"])
        self.assertIn("ETF:PARADO11", resultado["pendentes"])


if __name__ == "__main__":
    unittest.main()
