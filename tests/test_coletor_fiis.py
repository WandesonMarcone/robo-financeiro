"""Testes simulados da coleta de informes mensais de FIIs.

Nenhuma rede, CVM, Neon, Sheets ou Telegram e acessado. ZIP/CSV e HTTP sao
fabricados em memoria. Persistencia usa SQLite isolado.
"""

import io
import os
import sys
import zipfile
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pipeline_dados.banco_dados import Ativo, Base, DadosFinanceirosFiis, TipoAtivo
from pipeline_dados import coletor_fiis as cf

CNPJ_MXRF = "97.521.225/0001-25"
CNPJ_MXRF_DIGITOS = "97521225000125"
CNPJ_HGLG = "11.728.688/0001-47"
CNPJ_DESCONHECIDO = "00.000.000/0001-91"


def _zip_csv(*tabelas):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as pacote:
        for nome, texto in tabelas:
            pacote.writestr(nome, texto.encode("latin1"))
    buffer.seek(0)
    return buffer.getvalue()


def _zip_geral_e_ativo(cnpj, data, patrimonio="1000,50", cotistas="10", ativo_total="2000"):
    geral = (
        "CNPJ_Fundo;DT_COMPTC;VL_PATRIM_LIQ;NR_COTISTAS\n"
        f"{cnpj};{data};{patrimonio};{cotistas}\n"
    )
    ativo = (
        "CNPJ_Fundo;DT_COMPTC;VL_TOTAL\n"
        f"{cnpj};{data};{ativo_total}\n"
    )
    return _zip_csv(("geral.csv", geral), ("ativo.csv", ativo))


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


class TestNormalizarCnpj(unittest.TestCase):
    def test_formatado_e_somente_digitos_sao_iguais(self):
        self.assertEqual(cf.normalizar_cnpj(CNPJ_MXRF), CNPJ_MXRF_DIGITOS)
        self.assertEqual(cf.normalizar_cnpj(CNPJ_MXRF_DIGITOS), CNPJ_MXRF_DIGITOS)

    def test_invalido_vira_none(self):
        self.assertIsNone(cf.normalizar_cnpj("MXRF11"))
        self.assertIsNone(cf.normalizar_cnpj("123"))
        self.assertIsNone(cf.normalizar_cnpj(""))
        self.assertIsNone(cf.normalizar_cnpj(None))


class TestColetorFiis(unittest.TestCase):
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
                Ativo(ticker="MXRF11", cnpj=CNPJ_MXRF, tipo=TipoAtivo.FII),
                Ativo(ticker="PETR4", cnpj="33.000.167/0001-01", tipo=TipoAtivo.ACAO),
            ]
        )
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _coletar(self, conteudo, ano=2025, status=200, raise_on_call=None):
        http = FakeHttp(status=status, content=conteudo, raise_on_call=raise_on_call)
        return cf.processar_informes_fiis_cvm(
            ano=ano, session=self.session, http_get=http
        ), http

    def test_cnpj_formatado_associa_ao_ativo_pelo_cadastro(self):
        zip_bytes = _zip_geral_e_ativo(CNPJ_MXRF, "2025-01-31")
        resultado, http = self._coletar(zip_bytes, ano=2025)
        self.assertEqual(resultado.status, cf.STATUS_GRAVADO)
        self.assertEqual(resultado.gravados, 1)
        self.assertEqual(resultado.ano, 2025)
        self.assertIn("inf_mensal_fii_2025.zip", http.urls[0])
        mxrf = self.session.query(Ativo).filter_by(ticker="MXRF11").one()
        linhas = (
            self.session.query(DadosFinanceirosFiis)
            .filter_by(ativo_id=mxrf.id)
            .all()
        )
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0].data_referencia, date(2025, 1, 31))
        self.assertAlmostEqual(linhas[0].patrimonio_liquido, 1000.50)
        self.assertEqual(linhas[0].cotistas, 10)
        self.assertAlmostEqual(linhas[0].ativo_total, 2000.0)
        self.assertIsNone(linhas[0].rendimento_por_cota)
        self.assertIsNone(linhas[0].vacancia_fisica)

    def test_cnpj_sem_pontuacao_casa_com_cadastro_formatado(self):
        zip_bytes = _zip_geral_e_ativo(CNPJ_MXRF_DIGITOS, "2025-02-28")
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 1)
        mxrf = self.session.query(Ativo).filter_by(ticker="MXRF11").one()
        self.assertEqual(
            self.session.query(DadosFinanceirosFiis)
            .filter_by(ativo_id=mxrf.id)
            .count(),
            1,
        )

    def test_ticker_nao_substitui_cnpj(self):
        zip_bytes = _zip_geral_e_ativo("MXRF11", "2025-01-31")
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 0)
        self.assertGreaterEqual(resultado.ignorados_validacao, 1)
        self.assertEqual(self.session.query(DadosFinanceirosFiis).count(), 0)

    def test_cnpj_desconhecido_nao_associa(self):
        zip_bytes = _zip_geral_e_ativo(CNPJ_DESCONHECIDO, "2025-01-31")
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.status, cf.STATUS_SEM_ATIVOS)
        self.assertEqual(resultado.gravados, 0)
        self.assertEqual(resultado.sem_ativo, 1)
        self.assertEqual(resultado.informes_encontrados, 1)
        self.assertEqual(self.session.query(DadosFinanceirosFiis).count(), 0)
        self.assertIn("nenhum CNPJ corresponde", resultado.mensagem_telegram())
        self.assertIn("Nenhum registro gravado", resultado.mensagem_telegram())

    def test_nao_grava_em_acao_mesmo_com_cnpj(self):
        zip_bytes = _zip_geral_e_ativo("33.000.167/0001-01", "2025-01-31")
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 0)
        self.assertEqual(resultado.sem_ativo, 1)

    def test_ausencia_nao_vira_zero(self):
        geral = "CNPJ_Fundo;DT_COMPTC;VL_PATRIM_LIQ;NR_COTISTAS\n"
        geral += f"{CNPJ_MXRF};2025-03-31;;\n"
        zip_bytes = _zip_csv(("geral.csv", geral))
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 1)
        linha = self.session.query(DadosFinanceirosFiis).one()
        self.assertIsNone(linha.patrimonio_liquido)
        self.assertIsNone(linha.cotistas)
        self.assertIsNone(linha.ativo_total)
        self.assertIsNone(linha.disponibilidades_caixa)

    def test_sentinela_nao_vira_zero(self):
        zip_bytes = _zip_geral_e_ativo(CNPJ_MXRF, "2025-04-30", patrimonio="-", cotistas="")
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 1)
        linha = self.session.query(DadosFinanceirosFiis).one()
        self.assertIsNone(linha.patrimonio_liquido)
        self.assertIsNone(linha.cotistas)

    def test_ano_escolhido_entra_na_url(self):
        http = FakeHttp(status=404, content=b"")
        resultado = cf.processar_informes_fiis_cvm(
            ano=2024, session=self.session, http_get=http
        )
        self.assertEqual(resultado.ano, 2024)
        self.assertIn("inf_mensal_fii_2024.zip", http.urls[0])
        self.assertEqual(resultado.status, cf.STATUS_ARQUIVO_INDISPONIVEL)

    def test_ano_omitido_usa_ano_civil_corrente(self):
        http = FakeHttp(status=404, content=b"")
        esperado = datetime.now().year
        resultado = cf.processar_informes_fiis_cvm(
            session=self.session, http_get=http
        )
        self.assertEqual(resultado.ano, esperado)
        self.assertIn(f"inf_mensal_fii_{esperado}.zip", http.urls[0])

    def test_http_nao_200_nao_mente_sucesso(self):
        resultado, _ = self._coletar(b"", status=404)
        self.assertEqual(resultado.status, cf.STATUS_ARQUIVO_INDISPONIVEL)
        self.assertEqual(resultado.gravados, 0)
        texto = resultado.mensagem_telegram()
        self.assertIn("arquivo nao obtido", texto)
        self.assertIn("Nenhum registro gravado", texto)
        self.assertNotIn("concluida", texto.lower())

    def test_zip_invalido_nao_mente_sucesso(self):
        resultado, _ = self._coletar(b"nao-e-zip")
        self.assertEqual(resultado.status, cf.STATUS_ARQUIVO_INVALIDO)
        self.assertEqual(resultado.gravados, 0)
        self.assertIn("invalido", resultado.mensagem_telegram())
        self.assertIn("Nenhum registro gravado", resultado.mensagem_telegram())

    def test_zip_sem_csv_e_invalido(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as pacote:
            pacote.writestr("leia.txt", "vazio")
        resultado, _ = self._coletar(buffer.getvalue())
        self.assertEqual(resultado.status, cf.STATUS_ARQUIVO_INVALIDO)
        self.assertEqual(resultado.gravados, 0)

    def test_csv_sem_informes_validos(self):
        csv_vazio = "OUTRA_COLUNA;X\n1;2\n"
        resultado, _ = self._coletar(_zip_csv(("x.csv", csv_vazio)))
        self.assertEqual(resultado.status, cf.STATUS_SEM_INFORMES)
        self.assertEqual(resultado.gravados, 0)
        self.assertIn("nenhum informe valido", resultado.mensagem_telegram())

    def test_data_invalida_e_ignorada(self):
        zip_bytes = _zip_geral_e_ativo(CNPJ_MXRF, "31/01/2025")
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 0)
        self.assertGreaterEqual(resultado.ignorados_validacao, 1)
        self.assertEqual(self.session.query(DadosFinanceirosFiis).count(), 0)

    def test_contagem_gravados_bate_com_persistencia(self):
        geral = (
            "CNPJ_Fundo;DT_COMPTC;VL_PATRIM_LIQ;NR_COTISTAS\n"
            f"{CNPJ_MXRF};2025-01-31;10;1\n"
            f"{CNPJ_MXRF};2025-02-28;20;2\n"
            f"{CNPJ_HGLG};2025-01-31;99;9\n"
        )
        resultado, _ = self._coletar(_zip_csv(("geral.csv", geral)))
        self.assertEqual(resultado.gravados, 2)
        self.assertEqual(resultado.sem_ativo, 1)
        self.assertEqual(resultado.informes_encontrados, 3)
        self.assertEqual(self.session.query(DadosFinanceirosFiis).count(), 2)
        self.assertIn("Registros gravados: 2", resultado.mensagem_telegram())

    def test_upsert_nao_duplica_mesmo_ativo_e_data(self):
        zip_bytes = _zip_geral_e_ativo(CNPJ_MXRF, "2025-01-31", patrimonio="10")
        cf.processar_informes_fiis_cvm(
            ano=2025, session=self.session, http_get=FakeHttp(content=zip_bytes)
        )
        zip_bytes2 = _zip_geral_e_ativo(CNPJ_MXRF, "2025-01-31", patrimonio="99")
        resultado, _ = self._coletar(zip_bytes2)
        self.assertEqual(resultado.gravados, 1)
        self.assertEqual(self.session.query(DadosFinanceirosFiis).count(), 1)
        self.assertAlmostEqual(
            self.session.query(DadosFinanceirosFiis).one().patrimonio_liquido, 99.0
        )

    def test_cnpj_pendente_nao_casa_com_informe(self):
        self.session.add(
            Ativo(ticker="HGLG11", cnpj="PENDENTE-HGLG11", tipo=TipoAtivo.FII)
        )
        self.session.commit()
        zip_bytes = _zip_geral_e_ativo(CNPJ_HGLG, "2025-01-31")
        resultado, _ = self._coletar(zip_bytes)
        self.assertEqual(resultado.gravados, 0)
        self.assertEqual(resultado.sem_ativo, 1)


def _carregar_comandos():
    """Importa ``bot.comandos`` sem PyMuPDF nem Telegram real."""
    if "fitz" not in sys.modules:
        sys.modules["fitz"] = mock.MagicMock()
    sys.modules.setdefault("yfinance", mock.MagicMock())
    import bot.comandos as comandos

    return comandos


class TestComandoForcarFiis(unittest.TestCase):
    def test_comando_repassa_ano_e_mensagem_do_resultado(self):
        comandos = _carregar_comandos()

        enviadas = []

        class FakeBot:
            def reply_to(self, message, texto, **kwargs):
                enviadas.append(("reply", texto))

            def send_message(self, chat_id, texto, **kwargs):
                enviadas.append(("send", texto))

        resultado = cf.ResultadoColetaFiis(2024)
        resultado.status = cf.STATUS_GRAVADO
        resultado.gravados = 3
        resultado.informes_encontrados = 5

        def fake_thread_cls(target, args=None, **kwargs):
            target(*(args or ()))
            return mock.Mock(start=mock.Mock())

        mensagem = SimpleNamespace(chat=SimpleNamespace(id=99), text="/forcar_fiis 2024")
        with mock.patch.object(comandos, "bot", FakeBot()), mock.patch.object(
            comandos, "processar_informes_fiis_cvm", return_value=resultado
        ), mock.patch.object(comandos.threading, "Thread", side_effect=fake_thread_cls):
            comandos.cmd_forcar_fiis(mensagem)

        self.assertTrue(any("2024" in t for _, t in enviadas))
        self.assertTrue(any("Registros gravados: 3" in t for _, t in enviadas))

    def test_comando_sem_ano_usa_padrao_civil(self):
        comandos = _carregar_comandos()

        capturado = {}

        class FakeBot:
            def reply_to(self, message, texto, **kwargs):
                capturado["reply"] = texto

            def send_message(self, chat_id, texto, **kwargs):
                capturado["send"] = texto

        resultado = cf.ResultadoColetaFiis(cf.ano_padrao_coleta())
        resultado.status = cf.STATUS_ARQUIVO_INDISPONIVEL
        resultado.http_status = 404

        def fake_thread_cls(target, args=None, **kwargs):
            capturado["ano"] = (args or (None,))[0]
            target(*(args or ()))
            return mock.Mock(start=mock.Mock())

        mensagem = SimpleNamespace(chat=SimpleNamespace(id=1), text="/forcar_fiis")
        with mock.patch.object(comandos, "bot", FakeBot()), mock.patch.object(
            comandos, "processar_informes_fiis_cvm", return_value=resultado
        ) as coleta, mock.patch.object(
            comandos.threading, "Thread", side_effect=fake_thread_cls
        ):
            comandos.cmd_forcar_fiis(mensagem)

        self.assertEqual(capturado["ano"], cf.ano_padrao_coleta())
        self.assertEqual(coleta.call_args.kwargs["ano"], cf.ano_padrao_coleta())
        self.assertIn("arquivo nao obtido", capturado["send"])


if __name__ == "__main__":
    unittest.main()
