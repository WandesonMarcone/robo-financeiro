"""Testes simulados da varredura IPE de documentos de acoes.

Nenhuma rede, CVM, Neon, Sheets ou Telegram e acessado.
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

from pipeline_dados.banco_dados import Ativo, Base, DocumentosQualitativos, TipoAtivo
from pipeline_dados import coletor_docs_acoes as cd
from pipeline_dados.coletor_fiis import ano_padrao_coleta

CNPJ_PETR = "33.000.167/0001-01"
CNPJ_PETR_DIGITOS = "33000167000101"
CNPJ_DESCONHECIDO = "00.000.000/0001-91"


def _zip_csv(texto, nome="ipe.csv"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as pacote:
        pacote.writestr(nome, texto.encode("latin1"))
    buffer.seek(0)
    return buffer.getvalue()


def _ipe_csv(cnpj, data, categoria="Fato Relevante", link="http://ex/a.pdf"):
    return (
        "CNPJ_Companhia;Data_Referencia;Categoria;Assunto;Link_Download\n"
        f"{cnpj};{data};{categoria};Assunto X;{link}\n"
    )


class FakeHttp:
    def __init__(self, status=200, content=b""):
        self.status = status
        self.content = content
        self.urls = []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        return SimpleNamespace(status_code=self.status, content=self.content)


class TestColetorDocsAcoes(unittest.TestCase):
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
        return (
            cd.RelatoriosAcoesCVM(self.session, http_get=http).vasculhar_documentos(ano),
            http,
        )

    def test_cnpj_formatado_grava_documento(self):
        resultado, http = self._coletar(_zip_csv(_ipe_csv(CNPJ_PETR, "2025-01-15")))
        self.assertEqual(resultado.status, cd.STATUS_GRAVADO)
        self.assertEqual(resultado.gravados, 1)
        self.assertIn("ipe_cia_aberta_2025.zip", http.urls[0])
        doc = self.session.query(DocumentosQualitativos).one()
        self.assertEqual(doc.data_publicacao, date(2025, 1, 15))
        self.assertEqual(doc.tipo_documento, "Fato Relevante")
        self.assertEqual(doc.status_processamento, "PENDENTE_ACAO")

    def test_cnpj_sem_pontuacao_casa(self):
        resultado, _ = self._coletar(
            _zip_csv(_ipe_csv(CNPJ_PETR_DIGITOS, "2025-02-01"))
        )
        self.assertEqual(resultado.gravados, 1)

    def test_ticker_nao_substitui_cnpj(self):
        resultado, _ = self._coletar(_zip_csv(_ipe_csv("PETR4", "2025-01-15")))
        self.assertEqual(resultado.gravados, 0)
        self.assertGreaterEqual(resultado.ignorados_validacao, 1)

    def test_cnpj_desconhecido(self):
        resultado, _ = self._coletar(
            _zip_csv(_ipe_csv(CNPJ_DESCONHECIDO, "2025-01-15"))
        )
        self.assertEqual(resultado.status, cd.STATUS_SEM_ATIVOS)
        self.assertEqual(resultado.sem_ativo, 1)
        self.assertIn("Nenhum documento gravado", resultado.mensagem_telegram())

    def test_nao_grava_em_fii(self):
        resultado, _ = self._coletar(
            _zip_csv(_ipe_csv("97.521.225/0001-25", "2025-01-15"))
        )
        self.assertEqual(resultado.gravados, 0)
        self.assertEqual(resultado.sem_ativo, 1)

    def test_categoria_fora_da_lista_e_ignorada(self):
        resultado, _ = self._coletar(
            _zip_csv(_ipe_csv(CNPJ_PETR, "2025-01-15", categoria="Outros"))
        )
        self.assertEqual(resultado.status, cd.STATUS_SEM_INFORMES)
        self.assertEqual(resultado.gravados, 0)

    def test_data_invalida_e_ignorada(self):
        resultado, _ = self._coletar(
            _zip_csv(_ipe_csv(CNPJ_PETR, "15/01/2025"))
        )
        self.assertEqual(resultado.gravados, 0)
        self.assertGreaterEqual(resultado.ignorados_validacao, 1)

    def test_duplicata_por_url_nao_grava_de_novo(self):
        zip_bytes = _zip_csv(_ipe_csv(CNPJ_PETR, "2025-01-15", link="http://ex/a.pdf"))
        cd.RelatoriosAcoesCVM(
            self.session, http_get=FakeHttp(content=zip_bytes)
        ).vasculhar_documentos(2025)
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 0)
        self.assertEqual(resultado.ja_existentes, 1)
        self.assertEqual(resultado.status, cd.STATUS_SEM_NOVOS)
        self.assertEqual(self.session.query(DocumentosQualitativos).count(), 1)
        self.assertIn("nenhum documento novo", resultado.mensagem_telegram())

    def test_http_404_nao_mente_sucesso(self):
        resultado, _ = self._coletar(b"", status=404)
        self.assertEqual(resultado.status, cd.STATUS_ARQUIVO_INDISPONIVEL)
        self.assertIn("Nenhum documento gravado", resultado.mensagem_telegram())

    def test_zip_invalido(self):
        resultado, _ = self._coletar(b"nao-e-zip")
        self.assertEqual(resultado.status, cd.STATUS_ARQUIVO_INVALIDO)

    def test_ano_omitido_usa_ano_civil(self):
        http = FakeHttp(status=404, content=b"")
        resultado = cd.RelatoriosAcoesCVM(
            self.session, http_get=http
        ).vasculhar_documentos()
        self.assertEqual(resultado.ano, ano_padrao_coleta())
        self.assertIn(f"ipe_cia_aberta_{ano_padrao_coleta()}.zip", http.urls[0])


class TestComandoForcarDocsAcoes(unittest.TestCase):
    def test_comando_nao_dispara_ia_sem_gravacao(self):
        if "fitz" not in sys.modules:
            sys.modules["fitz"] = mock.MagicMock()
        sys.modules.setdefault("yfinance", mock.MagicMock())
        import bot.comandos as comandos

        enviadas = []
        ia_chamada = []

        class FakeBot:
            def reply_to(self, message, texto, **kwargs):
                enviadas.append(("reply", texto))

            def send_message(self, chat_id, texto, **kwargs):
                enviadas.append(("send", texto))

        resultado = cd.ResultadoColetaDocs(2024)
        resultado.status = cd.STATUS_ARQUIVO_INDISPONIVEL
        resultado.http_status = 404

        class FakeColetor:
            def __init__(self, session):
                pass

            def vasculhar_documentos(self, ano):
                return resultado

        def fake_thread_cls(target, args=None, **kwargs):
            target(*(args or ()))
            return mock.Mock(start=mock.Mock())

        mensagem = SimpleNamespace(
            chat=SimpleNamespace(id=3), text="/forcar_docs_acoes 2024"
        )
        with mock.patch.object(comandos, "bot", FakeBot()), mock.patch(
            "pipeline_dados.coletor_docs_acoes.RelatoriosAcoesCVM", FakeColetor
        ), mock.patch.object(
            comandos, "SessionDB", return_value=mock.Mock()
        ), mock.patch.object(
            comandos, "rodar_ia_acoes", side_effect=lambda m: ia_chamada.append(1)
        ), mock.patch.object(
            comandos.threading, "Thread", side_effect=fake_thread_cls
        ):
            comandos.rodar_docs_acoes(mensagem)

        self.assertEqual(ia_chamada, [])
        self.assertTrue(any("arquivo nao obtido" in t for _, t in enviadas))

    def test_comando_dispara_ia_so_com_gravados(self):
        if "fitz" not in sys.modules:
            sys.modules["fitz"] = mock.MagicMock()
        sys.modules.setdefault("yfinance", mock.MagicMock())
        import bot.comandos as comandos

        ia_chamada = []
        resultado = cd.ResultadoColetaDocs(2025)
        resultado.status = cd.STATUS_GRAVADO
        resultado.gravados = 2

        class FakeColetor:
            def __init__(self, session):
                pass

            def vasculhar_documentos(self, ano):
                return resultado

        class FakeBot:
            def reply_to(self, message, texto, **kwargs):
                pass

            def send_message(self, chat_id, texto, **kwargs):
                pass

        def fake_thread_cls(target, args=None, **kwargs):
            target(*(args or ()))
            return mock.Mock(start=mock.Mock())

        mensagem = SimpleNamespace(
            chat=SimpleNamespace(id=3), text="/forcar_docs_acoes"
        )
        with mock.patch.object(comandos, "bot", FakeBot()), mock.patch(
            "pipeline_dados.coletor_docs_acoes.RelatoriosAcoesCVM", FakeColetor
        ), mock.patch.object(
            comandos, "SessionDB", return_value=mock.Mock()
        ), mock.patch.object(
            comandos, "rodar_ia_acoes", side_effect=lambda m: ia_chamada.append(1)
        ), mock.patch.object(
            comandos.threading, "Thread", side_effect=fake_thread_cls
        ):
            comandos.rodar_docs_acoes(mensagem)

        self.assertEqual(ia_chamada, [1])


if __name__ == "__main__":
    unittest.main()
