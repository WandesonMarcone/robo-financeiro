"""Testes simulados da coleta ITR de acoes.

Nenhuma rede, CVM, Neon, Sheets ou Telegram e acessado. ZIP/CSV e HTTP sao
fabricados em memoria. Persistencia usa SQLite isolado.
"""

import io
import os
import sys
import zipfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pipeline_dados.banco_dados import Ativo, Base, DadosFinanceirosAcoes, TipoAtivo
from pipeline_dados import coletor_cvm as cc
from pipeline_dados.coletor_fiis import ano_padrao_coleta

CNPJ_PETR = "33.000.167/0001-01"
CNPJ_PETR_DIGITOS = "33000167000101"
CNPJ_VALE = "33.592.510/0001-54"
CNPJ_DESCONHECIDO = "00.000.000/0001-91"


def _zip_csvs(*tabelas):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as pacote:
        for nome, texto in tabelas:
            pacote.writestr(nome, texto.encode("latin1"))
    buffer.seek(0)
    return buffer.getvalue()


def _csv_conta(ano, tipo, cnpj, data, contas, ordem="ÚLTIMO"):
    nome = f"itr_cia_aberta_{tipo}_{ano}.csv"
    linhas = ["CNPJ_CIA;DT_REFER;ORDEM_EXERC;CD_CONTA;VL_CONTA"]
    for conta, valor in contas:
        linhas.append(f"{cnpj};{data};{ordem};{conta};{valor}")
    return nome, "\n".join(linhas) + "\n"


class FakeHttp:
    def __init__(self, status=200, content=b"", raise_on_call=None):
        self.status = status
        self.content = content
        self.raise_on_call = raise_on_call
        self.urls = []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        if self.raise_on_call:
            raise self.raise_on_call
        return SimpleNamespace(status_code=self.status, content=self.content)


class TestColetorCvm(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        self.session.add_all(
            [
                Ativo(ticker="PETR4", cnpj=CNPJ_PETR, tipo=TipoAtivo.ACAO),
                Ativo(ticker="MXRF11", cnpj="97.521.225/0001-25", tipo=TipoAtivo.FII),
            ]
        )
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _coletar(self, conteudo, ano=2025, status=200):
        http = FakeHttp(status=status, content=conteudo)
        return cc.AcoesCVMReader(self.session, http_get=http).atualizar_acoes(ano), http

    def test_cnpj_formatado_associa_ao_ativo(self):
        zip_bytes = _zip_csvs(
            _csv_conta(
                2025,
                "BPA_con",
                CNPJ_PETR,
                "2025-03-31",
                [("1", "100"), ("1.01.01", "10")],
            )
        )
        resultado, http = self._coletar(zip_bytes)
        self.assertEqual(resultado.status, cc.STATUS_GRAVADO)
        self.assertEqual(resultado.gravados, 1)
        self.assertIn("itr_cia_aberta_2025.zip", http.urls[0])
        petr = self.session.query(Ativo).filter_by(ticker="PETR4").one()
        linha = (
            self.session.query(DadosFinanceirosAcoes)
            .filter_by(ativo_id=petr.id)
            .one()
        )
        self.assertEqual(linha.data_referencia, date(2025, 3, 31))
        self.assertEqual(linha.tipo_doc, "ITR")
        self.assertAlmostEqual(linha.ativo_total, 100000.0)
        self.assertAlmostEqual(linha.caixa, 10000.0)

    def test_cnpj_sem_pontuacao_casa_com_cadastro_formatado(self):
        zip_bytes = _zip_csvs(
            _csv_conta(2025, "BPA_con", CNPJ_PETR_DIGITOS, "2025-06-30", [("1", "50")])
        )
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 1)

    def test_ticker_nao_substitui_cnpj(self):
        zip_bytes = _zip_csvs(
            _csv_conta(2025, "BPA_con", "PETR4", "2025-03-31", [("1", "10")])
        )
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 0)
        self.assertGreaterEqual(resultado.ignorados_validacao, 1)
        self.assertEqual(self.session.query(DadosFinanceirosAcoes).count(), 0)

    def test_cnpj_desconhecido_nao_associa(self):
        zip_bytes = _zip_csvs(
            _csv_conta(2025, "BPA_con", CNPJ_DESCONHECIDO, "2025-03-31", [("1", "10")])
        )
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.status, cc.STATUS_SEM_ATIVOS)
        self.assertEqual(resultado.sem_ativo, 1)
        self.assertEqual(resultado.gravados, 0)
        self.assertIn("Nenhum registro gravado", resultado.mensagem_telegram())

    def test_nao_grava_em_fii_mesmo_com_cnpj(self):
        zip_bytes = _zip_csvs(
            _csv_conta(
                2025, "BPA_con", "97.521.225/0001-25", "2025-03-31", [("1", "10")]
            )
        )
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 0)
        self.assertEqual(resultado.sem_ativo, 1)

    def test_nao_cria_ativo_ausente(self):
        zip_bytes = _zip_csvs(
            _csv_conta(2025, "BPA_con", CNPJ_VALE, "2025-03-31", [("1", "10")])
        )
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 0)
        self.assertIsNone(self.session.query(Ativo).filter_by(ticker="VALE3").first())

    def test_ordem_penultimo_e_ignorada(self):
        zip_bytes = _zip_csvs(
            _csv_conta(
                2025,
                "BPA_con",
                CNPJ_PETR,
                "2025-03-31",
                [("1", "10")],
                ordem="PENÚLTIMO",
            )
        )
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.status, cc.STATUS_SEM_INFORMES)
        self.assertEqual(resultado.gravados, 0)

    def test_sentinela_nao_vira_zero(self):
        zip_bytes = _zip_csvs(
            _csv_conta(2025, "BPA_con", CNPJ_PETR, "2025-03-31", [("1", "-")])
        )
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 0)
        self.assertEqual(self.session.query(DadosFinanceirosAcoes).count(), 0)

    def test_divida_liquida_nao_trata_caixa_ausente_como_zero(self):
        zip_bytes = _zip_csvs(
            _csv_conta(
                2025,
                "BPP_con",
                CNPJ_PETR,
                "2025-03-31",
                [("2.01.04", "20"), ("2.02.01", "30")],
            )
        )
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 1)
        linha = self.session.query(DadosFinanceirosAcoes).one()
        self.assertAlmostEqual(linha.divida_bruta, 50000.0)
        self.assertIsNone(linha.divida_liquida)
        self.assertIsNone(linha.caixa)

    def test_ebitda_com_depreciacao_ausente(self):
        zip_bytes = _zip_csvs(
            _csv_conta(2025, "DRE_con", CNPJ_PETR, "2025-03-31", [("3.05", "40")])
        )
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 1)
        linha = self.session.query(DadosFinanceirosAcoes).one()
        self.assertAlmostEqual(linha.ebitda, 40000.0)

    def test_ano_escolhido_entra_na_url(self):
        http = FakeHttp(status=404, content=b"")
        resultado = cc.AcoesCVMReader(self.session, http_get=http).atualizar_acoes(2024)
        self.assertEqual(resultado.ano, 2024)
        self.assertIn("itr_cia_aberta_2024.zip", http.urls[0])
        self.assertEqual(resultado.status, cc.STATUS_ARQUIVO_INDISPONIVEL)

    def test_ano_omitido_usa_ano_civil_corrente(self):
        http = FakeHttp(status=404, content=b"")
        resultado = cc.AcoesCVMReader(self.session, http_get=http).atualizar_acoes()
        self.assertEqual(resultado.ano, ano_padrao_coleta())
        self.assertIn(
            f"itr_cia_aberta_{ano_padrao_coleta()}.zip", http.urls[0]
        )

    def test_http_nao_200_nao_mente_sucesso(self):
        resultado, _ = self._coletar(b"", status=404)
        self.assertEqual(resultado.status, cc.STATUS_ARQUIVO_INDISPONIVEL)
        self.assertIn("Nenhum registro gravado", resultado.mensagem_telegram())
        self.assertNotIn("concluida", resultado.mensagem_telegram().lower())

    def test_zip_invalido_nao_mente_sucesso(self):
        resultado, _ = self._coletar(b"nao-e-zip")
        self.assertEqual(resultado.status, cc.STATUS_ARQUIVO_INVALIDO)
        self.assertEqual(resultado.gravados, 0)

    def test_zip_sem_csv_itr_e_invalido(self):
        resultado, _ = self._coletar(_zip_csvs(("leia.txt", "vazio")))
        self.assertEqual(resultado.status, cc.STATUS_ARQUIVO_INVALIDO)

    def test_upsert_nao_duplica(self):
        zip_bytes = _zip_csvs(
            _csv_conta(2025, "BPA_con", CNPJ_PETR, "2025-03-31", [("1", "10")])
        )
        cc.AcoesCVMReader(
            self.session, http_get=FakeHttp(content=zip_bytes)
        ).atualizar_acoes(2025)
        zip_bytes2 = _zip_csvs(
            _csv_conta(2025, "BPA_con", CNPJ_PETR, "2025-03-31", [("1", "99")])
        )
        resultado, _ = self._coletar(zip_bytes2)
        self.assertEqual(resultado.gravados, 1)
        self.assertEqual(self.session.query(DadosFinanceirosAcoes).count(), 1)
        self.assertAlmostEqual(
            self.session.query(DadosFinanceirosAcoes).one().ativo_total, 99000.0
        )

    def test_nao_usa_planilha(self):
        with open(cc.__file__, encoding="utf-8") as fonte:
            texto = fonte.read()
        self.assertNotIn("conectar_gspread", texto)
        self.assertNotIn("MAPA_CNPJ_B3", texto)
        self.assertNotIn("BD_Acoes", texto)


class TestComandoForcarCvm(unittest.TestCase):
    def test_comando_repassa_ano_e_mensagem(self):
        if "fitz" not in sys.modules:
            sys.modules["fitz"] = mock.MagicMock()
        sys.modules.setdefault("yfinance", mock.MagicMock())
        import bot.comandos as comandos

        enviadas = []

        class FakeBot:
            def reply_to(self, message, texto, **kwargs):
                enviadas.append(("reply", texto))

            def send_message(self, chat_id, texto, **kwargs):
                enviadas.append(("send", texto))

        resultado = cc.ResultadoColetaAcoes(2024)
        resultado.status = cc.STATUS_GRAVADO
        resultado.gravados = 4

        class FakeReader:
            def __init__(self, session):
                pass

            def atualizar_acoes(self, ano):
                self.ano = ano
                return resultado

        def fake_thread_cls(target, args=None, **kwargs):
            target(*(args or ()))
            return mock.Mock(start=mock.Mock())

        mensagem = SimpleNamespace(chat=SimpleNamespace(id=7), text="/forcar_cvm 2024")
        with mock.patch.object(comandos, "bot", FakeBot()), mock.patch(
            "pipeline_dados.coletor_cvm.AcoesCVMReader", FakeReader
        ), mock.patch.object(
            comandos, "SessionDB", return_value=mock.Mock()
        ), mock.patch.object(
            comandos.threading, "Thread", side_effect=fake_thread_cls
        ):
            comandos.rodar_cvm(mensagem)

        self.assertTrue(any("2024" in t for _, t in enviadas))
        self.assertTrue(any("Registros gravados: 4" in t for _, t in enviadas))

    def test_comando_sem_ano_usa_padrao_civil(self):
        if "fitz" not in sys.modules:
            sys.modules["fitz"] = mock.MagicMock()
        sys.modules.setdefault("yfinance", mock.MagicMock())
        import bot.comandos as comandos

        capturado = {}

        class FakeBot:
            def reply_to(self, message, texto, **kwargs):
                capturado["reply"] = texto

            def send_message(self, chat_id, texto, **kwargs):
                capturado["send"] = texto

        resultado = cc.ResultadoColetaAcoes(ano_padrao_coleta())
        resultado.status = cc.STATUS_ARQUIVO_INDISPONIVEL
        resultado.http_status = 404

        def fake_thread_cls(target, args=None, **kwargs):
            capturado["ano"] = (args or (None,))[0]
            target(*(args or ()))
            return mock.Mock(start=mock.Mock())

        class FakeReader:
            def __init__(self, session):
                pass

            def atualizar_acoes(self, ano):
                capturado["ano_coleta"] = ano
                return resultado

        mensagem = SimpleNamespace(chat=SimpleNamespace(id=1), text="/forcar_cvm")
        with mock.patch.object(comandos, "bot", FakeBot()), mock.patch(
            "pipeline_dados.coletor_cvm.AcoesCVMReader", FakeReader
        ), mock.patch.object(
            comandos, "SessionDB", return_value=mock.Mock()
        ), mock.patch.object(
            comandos.threading, "Thread", side_effect=fake_thread_cls
        ):
            comandos.rodar_cvm(mensagem)

        self.assertEqual(capturado["ano"], ano_padrao_coleta())
        self.assertEqual(capturado["ano_coleta"], ano_padrao_coleta())
        self.assertIn("arquivo nao obtido", capturado["send"])


if __name__ == "__main__":
    unittest.main()
