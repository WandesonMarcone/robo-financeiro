import importlib.util
import pathlib
import unittest

path = pathlib.Path(__file__).resolve().parents[1] / "scripts/benchmark_capacidade.py"
spec = importlib.util.spec_from_file_location("benchmark", path)
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class BenchmarkTests(unittest.TestCase):
    def run_fake(self, tickers, limite=10, coletar=lambda t: {}, checkpoint=lambda r: None):
        return b.executar(tickers, limite, 600, 0, coletar=coletar, clock=lambda: 0, sleep=lambda s: None, checkpoint=checkpoint)

    def test_limite_e_duplicatas(self):
        r = self.run_fake(["PETR4", "petr4", "MXRF11"], limite=1)
        self.assertEqual((r["solicitados"], r["tentados"]), (2, 1))

    def test_falha_nao_interrompe(self):
        def collect(t):
            if t == "PETR4":
                raise TimeoutError()
            return {}
        r = self.run_fake(["PETR4", "MXRF11"], coletar=collect)
        self.assertEqual((r["tentados"], r["validos"]), (2, 1))
        self.assertEqual(r["resultados"][0]["erro"], "TimeoutError")

    def test_checkpoint_por_ativo(self):
        sizes = []
        self.run_fake(["PETR4", "MXRF11"], checkpoint=lambda rows: sizes.append(len(rows)))
        self.assertEqual(sizes, [1, 2])

    def test_ticker_invalido(self):
        with self.assertRaises(ValueError):
            self.run_fake(["https://example.com"])

    def test_limite_invalido(self):
        with self.assertRaises(ValueError):
            self.run_fake(["PETR4"], limite=101)

    def test_orcamento_interrompe(self):
        times = iter([0, 590, 590])
        r = b.executar(["PETR4"], 10, 600, 0, clock=lambda: next(times))
        self.assertEqual(r["tentados"], 0)
