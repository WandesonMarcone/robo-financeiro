"""Testes simulados da varredura FNET de documentos de FIIs.

Nenhuma rede, B3, Neon, Sheets, Drive ou Telegram e acessado.
"""

import os
import sys
import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pipeline_dados.banco_dados import Ativo, Base, DocumentosQualitativos, TipoAtivo
from pipeline_dados import coletor_fnet as cf


def _doc(id_doc, nome, data="15/01/2025", tipo="Informe Mensal"):
    return {
        "id": id_doc,
        "nome_fundo": nome,
        "data_ref": data,
        "tipo_doc": tipo,
    }


class TestColetorFnet(unittest.TestCase):
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
                Ativo(
                    ticker="MXRF11",
                    cnpj="97.521.225/0001-25",
                    tipo=TipoAtivo.FII,
                ),
                Ativo(
                    ticker="PETR4",
                    cnpj="33.000.167/0001-01",
                    tipo=TipoAtivo.ACAO,
                ),
            ]
        )
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _coletar(self, documentos, dias=60):
        return cf.ColetorFnet(
            session=self.session, capturar_tudo=lambda data: documentos
        ).coletar(dias=dias)

    def test_casa_pela_isca_de_nome(self):
        resultado = self._coletar(
            [_doc("100", "FII MAXI RENDA FUNDO DE INVESTIMENTO")]
        )
        self.assertEqual(resultado.status, cf.STATUS_GRAVADO)
        self.assertEqual(resultado.gravados, 1)
        mxrf = self.session.query(Ativo).filter_by(ticker="MXRF11").one()
        doc = self.session.query(DocumentosQualitativos).one()
        self.assertEqual(doc.ativo_id, mxrf.id)
        self.assertEqual(doc.id_b3, "100")
        self.assertEqual(doc.data_publicacao, date(2025, 1, 15))
        self.assertEqual(doc.status_processamento, "PENDENTE")

    def test_casa_pelo_ticker_no_nome(self):
        resultado = self._coletar([_doc("101", "MXRF11 MAXI RENDA")])
        self.assertEqual(resultado.gravados, 1)

    def test_nao_grava_em_acao(self):
        resultado = self._coletar([_doc("102", "PETROBRAS PETR4")])
        self.assertEqual(resultado.gravados, 0)
        self.assertEqual(resultado.sem_ativo, 1)

    def test_nome_desconhecido_nao_cria_pendente(self):
        resultado = self._coletar([_doc("103", "FUNDO INEXISTENTE XYZ")])
        self.assertEqual(resultado.status, cf.STATUS_SEM_ATIVOS)
        self.assertEqual(resultado.sem_ativo, 1)
        self.assertEqual(self.session.query(Ativo).count(), 2)
        self.assertIsNone(
            self.session.query(Ativo).filter(Ativo.cnpj.like("PENDENTE-%")).first()
        )
        self.assertIn("Nenhum documento gravado", resultado.mensagem_telegram())

    def test_id_ausente_e_ignorado(self):
        resultado = self._coletar([_doc("", "FII MAXI RENDA")])
        self.assertGreaterEqual(resultado.ignorados_validacao, 1)
        self.assertEqual(resultado.gravados, 0)

    def test_data_invalida_e_ignorada(self):
        resultado = self._coletar([_doc("104", "FII MAXI RENDA", data="janeiro")])
        self.assertEqual(resultado.gravados, 0)
        self.assertGreaterEqual(resultado.ignorados_validacao, 1)

    def test_duplicata_por_id_b3(self):
        docs = [_doc("105", "FII MAXI RENDA")]
        cf.ColetorFnet(
            session=self.session, capturar_tudo=lambda data: docs
        ).coletar()
        resultado = self._coletar(docs)
        self.assertEqual(resultado.gravados, 0)
        self.assertEqual(resultado.ja_existentes, 1)
        self.assertEqual(resultado.status, cf.STATUS_SEM_NOVOS)
        self.assertEqual(self.session.query(DocumentosQualitativos).count(), 1)

    def test_lista_vazia_nao_mente_sucesso(self):
        resultado = self._coletar([])
        self.assertEqual(resultado.status, cf.STATUS_SEM_INFORMES)
        self.assertIn("Nenhum documento gravado", resultado.mensagem_telegram())

    def test_nao_usa_planilha(self):
        with open(cf.__file__, encoding="utf-8") as fonte:
            texto = fonte.read()
        self.assertNotIn("conectar_gspread", texto)
        self.assertNotIn("BD_FIIs", texto)
        self.assertNotIn('cnpj=f"PENDENTE-', texto)
        self.assertNotIn("obter_tickers_da_planilha", texto)

    def test_dias_entram_na_data_de_busca(self):
        capturado = {}

        def fake_captura(data_inicio):
            capturado["data"] = data_inicio
            return []

        cf.ColetorFnet(
            session=self.session, capturar_tudo=fake_captura
        ).coletar(dias=10)
        self.assertIn("data", capturado)


def _resultado_fila(fila=0, processados=0, salvo=0, revisao=0, erros=0, notificados=0):
    from atualizador_documentos import ResultadoProcessamento

    resultado = ResultadoProcessamento("PENDENTE")
    resultado.fila = fila
    resultado.processados = processados
    resultado.salvo_drive = salvo
    resultado.revisao = revisao
    resultado.erros = erros
    resultado.notificados = notificados
    return resultado


class TestComandoForcarVarredura(unittest.TestCase):
    def test_comando_processa_fila_residual_mesmo_sem_gravacao(self):
        if "fitz" not in sys.modules:
            sys.modules["fitz"] = mock.MagicMock()
        sys.modules.setdefault("yfinance", mock.MagicMock())
        import bot.comandos as comandos

        enviadas = []
        fila = []

        class FakeBot:
            def reply_to(self, message, texto, **kwargs):
                enviadas.append(("reply", texto))

            def send_message(self, chat_id, texto, **kwargs):
                enviadas.append(("send", texto))

        resultado = cf.ResultadoVarreduraFnet(60)
        resultado.status = cf.STATUS_SEM_INFORMES
        processamento = _resultado_fila(fila=3, processados=3, salvo=1, revisao=1, erros=1)

        class FakeColetor:
            def __init__(self, session):
                pass

            def coletar(self, dias=60):
                return resultado

        def fake_fila():
            fila.append(1)
            return processamento

        def fake_thread_cls(target, args=None, **kwargs):
            target(*(args or ()))
            return mock.Mock(start=mock.Mock())

        mensagem = SimpleNamespace(
            chat=SimpleNamespace(id=9), text="/forcar_varredura"
        )
        with mock.patch.object(comandos, "bot", FakeBot()), mock.patch(
            "pipeline_dados.coletor_fnet.ColetorFnet", FakeColetor
        ), mock.patch.object(
            comandos, "SessionDB", return_value=mock.Mock()
        ), mock.patch(
            "atualizador_documentos.rotina_processar_pendentes",
            side_effect=fake_fila,
        ), mock.patch.object(
            comandos.threading, "Thread", side_effect=fake_thread_cls
        ):
            comandos.acionar_varredura_manual(mensagem)

        self.assertEqual(fila, [1])
        textos = [t for _, t in enviadas]
        self.assertTrue(any("Nenhum documento gravado" in t for t in textos))
        self.assertTrue(any("Processando fila PENDENTE" in t for t in textos))
        self.assertTrue(any("Na fila: 3" in t for t in textos))
        self.assertTrue(any("Processados: 3" in t for t in textos))

    def test_comando_repassa_dias_e_processa_fila(self):
        if "fitz" not in sys.modules:
            sys.modules["fitz"] = mock.MagicMock()
        sys.modules.setdefault("yfinance", mock.MagicMock())
        import bot.comandos as comandos

        capturado = {}
        fila = []

        class FakeBot:
            def reply_to(self, message, texto, **kwargs):
                capturado.setdefault("msgs", []).append(texto)

            def send_message(self, chat_id, texto, **kwargs):
                capturado.setdefault("msgs", []).append(texto)

        resultado = cf.ResultadoVarreduraFnet(15)
        resultado.status = cf.STATUS_GRAVADO
        resultado.gravados = 2
        processamento = _resultado_fila(fila=2, processados=2, salvo=2)

        class FakeColetor:
            def __init__(self, session):
                pass

            def coletar(self, dias=60):
                capturado["dias"] = dias
                return resultado

        def fake_fila():
            fila.append(1)
            return processamento

        def fake_thread_cls(target, args=None, **kwargs):
            target(*(args or ()))
            return mock.Mock(start=mock.Mock())

        mensagem = SimpleNamespace(
            chat=SimpleNamespace(id=9), text="/forcar_varredura 15"
        )
        with mock.patch.object(comandos, "bot", FakeBot()), mock.patch(
            "pipeline_dados.coletor_fnet.ColetorFnet", FakeColetor
        ), mock.patch.object(
            comandos, "SessionDB", return_value=mock.Mock()
        ), mock.patch(
            "atualizador_documentos.rotina_processar_pendentes",
            side_effect=fake_fila,
        ), mock.patch.object(
            comandos.threading, "Thread", side_effect=fake_thread_cls
        ):
            comandos.acionar_varredura_manual(mensagem)

        self.assertEqual(capturado["dias"], 15)
        self.assertEqual(fila, [1])
        self.assertTrue(
            any("Documentos novos gravados: 2" in t for t in capturado["msgs"])
        )
        self.assertTrue(any("Salvos no Drive: 2" in t for t in capturado["msgs"]))


if __name__ == "__main__":
    unittest.main()
