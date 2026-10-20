"""Protecao de dados do coletor de acoes (Fundamentus + Yahoo).

Garante que valor ausente/invalido nao vira zero na planilha e que
celulas invalidas sao omitidas. Nenhuma rede real e acessada.
"""

import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytz  # noqa: E402
import modules.scraper_acoes as sa  # noqa: E402

SP_TZ = pytz.timezone("America/Sao_Paulo")
AGORA_SP = "15/10 19:30"

HTML_OK = """<html><body><table>
<tr><th>Papel</th><th>Cotação</th><th>P/L</th><th>P/VP</th><th>Div.Yield</th>
<th>ROE</th><th>Liq.2meses</th><th>P/Ativo</th><th>Mrg Bruta</th>
<th>Mrg Ebit</th><th>Mrg. Líq.</th><th>P/EBIT</th><th>EV/EBIT</th>
<th>Dív.Líq/ Patrim.</th><th>PSR</th><th>P/Cap.Giro</th>
<th>P/Ativ Circ.Liq</th><th>Liq. Corr.</th><th>ROIC</th>
<th>Cresc. Rec.5a</th></tr>
<tr><td>PETR4</td><td>38,00</td><td>6,50</td><td>1,20</td><td>12,00%</td>
<td>18,00%</td><td>500000000</td><td>0,80</td><td>40,00%</td>
<td>30,00%</td><td>20,00%</td><td>4,00</td><td>5,00</td>
<td>0,50</td><td>1,10</td><td>2,00</td><td>1,50</td><td>1,20</td>
<td>15,00%</td><td>8,00%</td></tr>
</table></body></html>"""

HTML_SEM_PEG_E_PL = """<html><body><table>
<tr><th>Papel</th><th>Cotação</th><th>P/L</th><th>P/VP</th><th>Div.Yield</th>
<th>ROE</th><th>Liq.2meses</th><th>P/Ativo</th><th>Mrg Bruta</th>
<th>Mrg Ebit</th><th>Mrg. Líq.</th><th>P/EBIT</th><th>EV/EBIT</th>
<th>Dív.Líq/ Patrim.</th><th>PSR</th><th>P/Cap.Giro</th>
<th>P/Ativ Circ.Liq</th><th>Liq. Corr.</th><th>ROIC</th>
<th>Cresc. Rec.5a</th></tr>
<tr><td>PETR4</td><td>38,00</td><td>-</td><td>1,20</td><td>12,00%</td>
<td>18,00%</td><td>500000000</td><td>-</td><td>-</td>
<td>-</td><td>-</td><td>-</td><td>-</td>
<td>-</td><td>-</td><td>-</td><td>-</td><td>-</td>
<td>-</td><td>-</td></tr>
</table></body></html>"""

CABECALHO = ["Papel"] + ["x"] * 32
LINHA_PETR = ["PETR4"] + ["1"] * 32
LINHA_PETR[32] = "01/01 00:00"


class FakeResposta:
    def __init__(self, texto):
        self.text = texto
        self.status_code = 200
        self.headers = {"Content-Type": "text/html"}


class FakeTicker:
    def __init__(self, info):
        self.info = info


class FakeWorksheet:
    def __init__(self, linhas):
        self._linhas = linhas

    def get_all_values(self):
        return self._linhas

    def append_row(self, _row):
        return None


class FakePlanilha:
    def __init__(self, aba):
        self._aba = aba

    def worksheet(self, nome):
        return self._aba


def _mapa_updates(updates):
    resultado = {}
    for item in updates:
        rng = item["range"]
        coluna = "".join(c for c in rng if c.isalpha())
        resultado[coluna] = item["values"][0][0]
    return resultado


class TestProtecaoScraperAcoes(unittest.TestCase):
    def _executar(self, html, yf_info, erro_ssl=False):
        aba = FakeWorksheet([CABECALHO, LINHA_PETR])
        planilha = FakePlanilha(aba)
        if erro_ssl:
            patch_req = mock.patch.object(
                sa,
                "get_request_with_retry",
                side_effect=sa.requests.exceptions.SSLError("hostname mismatch"),
            )
        else:
            patch_req = mock.patch.object(
                sa, "get_request_with_retry", return_value=FakeResposta(html)
            )
        with patch_req, mock.patch.object(
            sa.yf, "Ticker", return_value=FakeTicker(yf_info)
        ):
            batch_updates, _, _ = sa.rodar_garimpo_acoes(
                planilha, datetime.now(SP_TZ), AGORA_SP, SP_TZ
            )
        return _mapa_updates(batch_updates)

    def test_sucesso_grava_indicadores_validos(self):
        valores = self._executar(
            HTML_OK,
            {
                "currentPrice": 38.5,
                "trailingEps": 5.0,
                "bookValue": 32.0,
                "returnOnAssets": 0.09,
                "trailingPegRatio": 1.2,
                "marketCap": 1000,
                "sharesOutstanding": 50,
            },
        )
        self.assertEqual(valores.get("C"), 38.5)
        self.assertAlmostEqual(valores.get("F"), 6.5)
        self.assertAlmostEqual(valores.get("G"), 1.2)
        self.assertAlmostEqual(valores.get("D"), 0.12)
        self.assertAlmostEqual(valores.get("T"), 0.18)
        self.assertEqual(valores.get("AE"), 1.2)
        self.assertEqual(valores.get("AG"), AGORA_SP)
        self.assertNotIn("W", valores)
        self.assertNotIn("X", valores)
        self.assertNotIn("Y", valores)
        self.assertNotIn("AA", valores)

    def test_peg_ausente_nao_grava_zero(self):
        valores = self._executar(
            HTML_OK,
            {
                "currentPrice": 38.5,
                "trailingPegRatio": None,
                "trailingEps": 5.0,
                "bookValue": 32.0,
            },
        )
        self.assertNotIn("AE", valores)

    def test_pl_sentinela_nao_grava_zero(self):
        valores = self._executar(
            HTML_SEM_PEG_E_PL,
            {
                "currentPrice": 38.5,
                "trailingEps": None,
                "bookValue": 32.0,
                "trailingPegRatio": None,
            },
        )
        self.assertNotIn("F", valores)
        self.assertNotIn("H", valores)
        self.assertNotIn("P", valores)
        self.assertAlmostEqual(valores.get("G"), 1.2)
        self.assertEqual(valores.get("AG"), AGORA_SP)

    def test_preco_invalido_nao_sobrescreve(self):
        valores = self._executar(
            HTML_SEM_PEG_E_PL.replace("38,00", "-"),
            {"currentPrice": 0, "regularMarketPrice": None},
        )
        self.assertNotIn("C", valores)

    def test_falha_fundamentus_nao_carimba_nem_zera(self):
        valores = self._executar(
            "",
            {"currentPrice": 38.5},
            erro_ssl=True,
        )
        self.assertEqual(valores.get("C"), 38.5)
        self.assertNotIn("AG", valores)
        for col in ("D", "F", "G", "H", "P", "T", "AE"):
            self.assertNotIn(col, valores)


if __name__ == "__main__":
    unittest.main()
