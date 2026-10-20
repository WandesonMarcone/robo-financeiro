"""Testes do coletor de FIIs (Fundamentus + Yahoo Finance).

Cobrem:

* correção do erro SSL ``Hostname mismatch`` do Fundamentus (uso do domínio
  raiz sem ``www``), sem desativar a validação de certificado;
* conversão de valores de fonte preservando zero legítimo e tratando
  sentinelas/None/NaN/infinitos como ausência;
* proteção dos dados: uma falha de fonte não pode sobrescrever indicadores
  válidos já gravados nem marcar dados antigos como recém-atualizados.

Nenhuma rede real é acessada: ``get_request_with_retry``, ``yf.Ticker`` e
``buscar_dados_profundos_fii`` são substituídos por dublês.
"""

import os
import sys
import math
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytz  # noqa: E402
import modules.scraper_fiis as sf  # noqa: E402

SP_TZ = pytz.timezone("America/Sao_Paulo")
AGORA_SP = "15/10 19:30"


HTML_OK = """<html><body><table>
<tr><th>Papel</th><th>Segmento</th><th>Cotação</th><th>Dividend Yield</th>
<th>P/VP</th><th>Valor de Mercado</th><th>Liquidez</th><th>Qtd de imóveis</th>
<th>Vacância Média</th></tr>
<tr><td>MXRF11</td><td>Papel</td><td>9,36</td><td>11,34%</td><td>1,01</td>
<td>5.309.050.000</td><td>24.953.800</td><td>2</td><td>0,00%</td></tr>
</table></body></html>"""

HTML_SEM_PVP = """<html><body><table>
<tr><th>Papel</th><th>Segmento</th><th>Cotação</th><th>Dividend Yield</th>
<th>P/VP</th><th>Valor de Mercado</th><th>Liquidez</th><th>Qtd de imóveis</th>
<th>Vacância Média</th></tr>
<tr><td>MXRF11</td><td>Papel</td><td>9,36</td><td>11,34%</td><td>-</td>
<td>5.309.050.000</td><td>24.953.800</td><td>2</td><td>0,00%</td></tr>
</table></body></html>"""

HTML_SEM_COTACAO_PVP = """<html><body><table>
<tr><th>Papel</th><th>Segmento</th><th>Cotação</th><th>Dividend Yield</th>
<th>P/VP</th><th>Valor de Mercado</th><th>Liquidez</th><th>Qtd de imóveis</th>
<th>Vacância Média</th></tr>
<tr><td>MXRF11</td><td>Papel</td><td>-</td><td>11,34%</td><td>-</td>
<td>5.309.050.000</td><td>24.953.800</td><td>2</td><td>0,00%</td></tr>
</table></body></html>"""

DEEP_PADRAO = {
    "imoveis_reais": None,
    "vacancia_real": float("nan"),
    "principais_inquilinos": None,
    "segmento_real": None,
}

CABECALHO = [
    "Ticker", "Tipo", "Setor", "Preço", "Qtd", "P/VP", "DY", "Vacância",
    "Imóveis", "Inquilinos", "WALT", "Alav", "Liquidez", "Valor Mercado",
    "VPA", "Lucro", "Div Mensal", "Atualização",
]

LINHA_MXRF = [
    "MXRF11", "Papel", "Papel", "9,50", "1000", "1,05", "0,12", "0,01",
    "10", "LOREM", "Pendente de IA", "Pendente de IA", "20000000",
    "5000000000", "9,05", "600000000", "0,09", "OK 01/01 00:00",
]


class FakeResposta:
    def __init__(self, texto):
        self.text = texto
        self.status_code = 200
        self.headers = {"Content-Type": "text/html"}

    def raise_for_status(self):
        return None


class FakeTicker:
    def __init__(self, info):
        self.info = info


class FakeWorksheet:
    def __init__(self, linhas):
        self._linhas = linhas
        self.updates = []

    def get_all_values(self):
        return self._linhas

    def batch_update(self, data):
        self.updates = data


class FakePlanilha:
    def __init__(self, aba_fiis):
        self._aba = aba_fiis

    def worksheet(self, nome):
        if nome == "BD_FIIs":
            return self._aba
        return FakeWorksheet([])


def _mapa_updates(updates):
    """Converte a lista de batch_update em {coluna: valor} para a última linha."""
    resultado = {}
    for item in updates:
        rng = item["range"]
        coluna = "".join(c for c in rng if c.isalpha())
        resultado[coluna] = item["values"][0][0]
    return resultado


class TestConversaoDeValores(unittest.TestCase):
    def test_sentinela_vira_ausencia(self):
        self.assertTrue(math.isnan(sf.converter_numero("-")))
        self.assertTrue(math.isnan(sf.converter_numero("")))
        self.assertTrue(math.isnan(sf.converter_numero("N/D")))
        self.assertTrue(math.isnan(sf.converter_numero(None)))

    def test_zero_legitimo_preservado(self):
        self.assertEqual(sf.converter_numero(0), 0.0)
        self.assertEqual(sf.converter_numero("0,00%"), 0.0)
        self.assertEqual(sf.converter_numero("0"), 0.0)

    def test_porcentagem_e_formato_brasileiro(self):
        self.assertAlmostEqual(sf.converter_numero("11,34%"), 0.1134)
        self.assertAlmostEqual(sf.converter_numero("R$ 1.234,56"), 1234.56)

    def test_infinitos_e_nan_sao_ausencia(self):
        self.assertTrue(math.isnan(sf.converter_numero(float("inf"))))
        self.assertTrue(math.isnan(sf.converter_numero(float("-inf"))))
        self.assertTrue(math.isnan(sf.converter_numero(float("nan"))))
        self.assertFalse(sf.eh_valido(float("nan")))
        self.assertFalse(sf.eh_valido(None))


class TestFundamentusSSL(unittest.TestCase):
    def _capturar_url(self):
        capturado = {}

        def fake_get(url, headers=None, **kwargs):
            capturado["url"] = url
            raise sf.requests.exceptions.SSLError("certificado inválido")

        with mock.patch.object(sf, "get_request_with_retry", side_effect=fake_get):
            sf.rodar_garimpo_fiis(
                FakePlanilha(FakeWorksheet([CABECALHO])), datetime.now(SP_TZ), AGORA_SP, SP_TZ
            )
        return capturado["url"]

    def test_url_fundamentus_sem_www(self):
        url = self._capturar_url()
        self.assertTrue(url.startswith("https://fundamentus.com.br/"))
        self.assertNotIn("www.", url)

    def test_validacao_ssl_nao_desativada(self):
        with open(sf.__file__, encoding="utf-8") as arquivo:
            fonte = arquivo.read()
        self.assertNotIn("verify=False", fonte)


class TestProtecaoDeDados(unittest.TestCase):
    def _executar(self, html, yf_info, linhas, deep=None, erro_ssl=False):
        aba = FakeWorksheet(linhas)
        planilha = FakePlanilha(aba)

        if erro_ssl:
            efeito = sf.requests.exceptions.SSLError("hostname mismatch")
            patch_req = mock.patch.object(
                sf, "get_request_with_retry", side_effect=efeito
            )
        else:
            patch_req = mock.patch.object(
                sf, "get_request_with_retry", return_value=FakeResposta(html)
            )

        with patch_req, \
             mock.patch.object(sf, "buscar_dados_profundos_fii",
                               return_value=deep or dict(DEEP_PADRAO)), \
             mock.patch.object(sf.yf, "Ticker",
                               return_value=FakeTicker(yf_info)):
            batch_updates, _, _ = sf.rodar_garimpo_fiis(
                planilha, datetime.now(SP_TZ), AGORA_SP, SP_TZ
            )

        return _mapa_updates(batch_updates)

    def test_falha_fundamentus_preserva_dados_e_nao_carimba(self):
        # Fundamentus cai por SSL; Yahoo ainda devolve o preço.
        valores = self._executar(
            "", {"currentPrice": 9.38}, [CABECALHO, LINHA_MXRF], erro_ssl=True
        )
        # Preço confiável é atualizado...
        self.assertEqual(valores.get("D"), 9.38)
        # ...mas os indicadores do Fundamentus NÃO são sobrescritos.
        for col in ("F", "G", "H", "I", "M", "N", "O", "P", "Q"):
            self.assertNotIn(col, valores, f"coluna {col} não deveria ser gravada")
        # Dados antigos não podem ser marcados como recém-atualizados.
        self.assertNotIn("R", valores)

    def test_sucesso_atualiza_indicadores_e_carimba(self):
        valores = self._executar(
            HTML_OK, {"currentPrice": 9.38}, [CABECALHO, LINHA_MXRF]
        )
        self.assertEqual(valores.get("D"), 9.38)          # preço via Yahoo
        self.assertAlmostEqual(valores.get("F"), 1.01)    # P/VP do Fundamentus
        self.assertAlmostEqual(valores.get("G"), 0.1134)  # DY do Fundamentus
        self.assertEqual(valores.get("H"), 0.0)           # vacância 0 é legítima
        self.assertEqual(valores.get("R"), AGORA_SP)      # carimbo atualizado

    def test_pvp_ausente_nao_zera_coluna(self):
        valores = self._executar(
            HTML_SEM_PVP, {"currentPrice": 9.38}, [CABECALHO, LINHA_MXRF]
        )
        # P/VP "-" é ausência: a célula F não é gravada (valor antigo preservado).
        self.assertNotIn("F", valores)
        # O restante da coleta segue normalmente e o carimbo é escrito.
        self.assertAlmostEqual(valores.get("G"), 0.1134)
        self.assertEqual(valores.get("R"), AGORA_SP)

    def test_preco_zero_do_yahoo_nao_sobrescreve(self):
        valores = self._executar(
            HTML_SEM_COTACAO_PVP,
            {"currentPrice": 0, "regularMarketPrice": None},
            [CABECALHO, LINHA_MXRF],
        )
        # Yahoo sem preço válido (0/None) e Fundamentus sem cotação -> não grava
        # preço, preservando o valor anterior.
        self.assertNotIn("D", valores)

    def test_yahoo_indisponivel_usa_fundamentus(self):
        valores = self._executar(HTML_OK, {}, [CABECALHO, LINHA_MXRF])
        # Sem preço no Yahoo, usa a cotação do Fundamentus (9,36).
        self.assertAlmostEqual(valores.get("D"), 9.36)

    def test_fonte_totalmente_indisponivel_nao_grava(self):
        valores = self._executar(
            "", {}, [CABECALHO, LINHA_MXRF], erro_ssl=True
        )
        # Nenhuma fonte respondeu: nada é gravado (nem valores inventados).
        self.assertEqual(valores, {})

    def test_statusinvest_403_nao_sobrescreve_fundamentus(self):
        deep_indisponivel = {
            "imoveis_reais": None,
            "vacancia_real": float("nan"),
            "principais_inquilinos": None,
            "segmento_real": None,
        }
        valores = self._executar(
            HTML_OK,
            {"currentPrice": 9.38},
            [CABECALHO, LINHA_MXRF],
            deep=deep_indisponivel,
        )
        self.assertEqual(valores.get("H"), 0.0)
        self.assertNotIn("J", valores)
        self.assertAlmostEqual(valores.get("G"), 0.1134)

    def test_vacancia_zero_do_statusinvest_e_legitima(self):
        deep_zero = {
            "imoveis_reais": 2,
            "vacancia_real": 0.0,
            "principais_inquilinos": None,
            "segmento_real": "Papel",
        }
        valores = self._executar(
            HTML_OK,
            {"currentPrice": 9.38},
            [CABECALHO, LINHA_MXRF],
            deep=deep_zero,
        )
        self.assertEqual(valores.get("H"), 0.0)
        self.assertEqual(valores.get("I"), 2)
        self.assertEqual(valores.get("C"), "Papel")


class FakeHttpResposta:
    def __init__(self, status, texto="", payload=None):
        self.status_code = status
        self.text = texto
        self._payload = payload

    def json(self):
        return self._payload


class TestStatusInvest403(unittest.TestCase):
    def test_403_e_indisponibilidade_sem_indicador_inventado(self):
        def fake_get(url, headers=None, timeout=None):
            return FakeHttpResposta(403, texto="Just a moment...")

        with mock.patch.object(sf.requests, "get", side_effect=fake_get):
            resultado = sf.buscar_dados_profundos_fii("MXRF11")

        self.assertIsNone(resultado["imoveis_reais"])
        self.assertTrue(math.isnan(resultado["vacancia_real"]))
        self.assertIsNone(resultado["principais_inquilinos"])
        self.assertIsNone(resultado["segmento_real"])

    def test_http_nao_200_nao_inventa_zero(self):
        def fake_get(url, headers=None, timeout=None):
            return FakeHttpResposta(503, texto="unavailable")

        with mock.patch.object(sf.requests, "get", side_effect=fake_get):
            resultado = sf.buscar_dados_profundos_fii("HGLG11")

        self.assertIsNone(resultado["imoveis_reais"])
        self.assertTrue(math.isnan(resultado["vacancia_real"]))
        self.assertIsNone(resultado["segmento_real"])


if __name__ == "__main__":
    unittest.main()
