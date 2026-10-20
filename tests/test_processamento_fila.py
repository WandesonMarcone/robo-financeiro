"""Testes das correcoes C1-C4 (fila residual, mensagem honesta, orquestrador).

Nenhuma rede, Neon, Drive, Groq, Telegram ou CVM e acessada.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline_dados import coletor_fnet as cf
from atualizador_documentos import ResultadoProcessamento
import atualizador_documentos as ad


def _fake_thread(target, args=None, **kwargs):
    target(*(args or ()))
    return mock.Mock(start=mock.Mock())


class TestResultadoProcessamento(unittest.TestCase):
    def test_fila_vazia_nao_mente_sucesso(self):
        resultado = ResultadoProcessamento("PENDENTE")
        texto = resultado.mensagem_telegram()
        self.assertIn("nenhum documento PENDENTE", texto)
        self.assertIn("Nada processado", texto)
        self.assertNotIn("concluido", texto.lower())
        self.assertNotIn("todos", texto.lower())

    def test_contagens_aparecem_quando_ha_fila(self):
        resultado = ResultadoProcessamento("PENDENTE_ACAO")
        resultado.fila = 4
        resultado.processados = 4
        resultado.salvo_drive = 2
        resultado.revisao = 1
        resultado.erros = 1
        resultado.notificados = 3
        texto = resultado.mensagem_telegram()
        self.assertIn("Na fila: 4", texto)
        self.assertIn("Processados: 4", texto)
        self.assertIn("Salvos no Drive: 2", texto)
        self.assertIn("Enviados para revisao: 1", texto)
        self.assertIn("Erros: 1", texto)
        self.assertIn("Seguidores notificados: 3", texto)


class TestMassaProcessaFilaResidual(unittest.TestCase):
    def test_massa_processa_fila_mesmo_sem_gravados(self):
        coleta = cf.ResultadoVarreduraFnet(60)
        coleta.status = cf.STATUS_SEM_INFORMES
        processamento = ResultadoProcessamento("PENDENTE")
        processamento.fila = 2
        processamento.processados = 2

        with mock.patch.object(
            ad, "rotina_de_coleta_b3", return_value=coleta
        ), mock.patch.object(
            ad, "rotina_processar_pendentes", return_value=processamento
        ) as fila:
            saida = ad.rotina_de_atualizacao_em_massa(dias=7)

        fila.assert_called_once()
        self.assertIs(saida.processamento, processamento)
        self.assertEqual(saida.status, cf.STATUS_SEM_INFORMES)


class TestOrquestradorNaoAnunciaIaFalsa(unittest.TestCase):
    def test_cron_nao_anuncia_ia_sem_executar(self):
        if "fitz" not in sys.modules:
            sys.modules["fitz"] = mock.MagicMock()
        from services import orquestrador

        avisos = []
        coleta = cf.ResultadoVarreduraFnet(60)
        coleta.status = cf.STATUS_SEM_INFORMES
        coleta.processamento = ResultadoProcessamento("PENDENTE")

        class FakeCvm:
            def __init__(self, session):
                pass

            def atualizar_acoes(self):
                resultado = SimpleNamespace(
                    mensagem_telegram=lambda: "CVM: nenhum registro gravado."
                )
                return resultado

        with mock.patch.object(
            orquestrador, "_avisar", side_effect=lambda t, **k: avisos.append(t)
        ), mock.patch.object(
            orquestrador,
            "rotina_de_atualizacao_em_massa",
            return_value=coleta,
        ), mock.patch.object(
            orquestrador, "AcoesCVMReader", FakeCvm
        ), mock.patch.object(
            orquestrador, "SessionDB", return_value=mock.Mock()
        ):
            orquestrador.varredura_diaria()

        texto = "\n".join(avisos)
        self.assertNotIn("Leitura de IA finalizada", texto)
        self.assertNotIn("Iniciando leitura de PDFs com IA", texto)
        self.assertIn("IA nao executada neste cron", texto)
        self.assertTrue(any("nenhum documento PENDENTE" in a for a in avisos))


class TestComandoProcessarAcoesIa(unittest.TestCase):
    def test_fila_vazia_nao_diz_todos_organizados(self):
        if "fitz" not in sys.modules:
            sys.modules["fitz"] = mock.MagicMock()
        sys.modules.setdefault("yfinance", mock.MagicMock())
        import bot.comandos as comandos

        enviadas = []
        resultado = ResultadoProcessamento("PENDENTE_ACAO")

        class FakeBot:
            def send_message(self, chat_id, texto, **kwargs):
                enviadas.append(texto)

        mensagem = SimpleNamespace(chat=SimpleNamespace(id=4), text="/processar_acoes_ia")
        with mock.patch.object(comandos, "bot", FakeBot()), mock.patch(
            "atualizador_documentos.rotina_processar_acoes",
            return_value=resultado,
        ), mock.patch.object(
            comandos.threading, "Thread", side_effect=_fake_thread
        ):
            comandos.rodar_ia_acoes(mensagem)

        texto = "\n".join(enviadas)
        self.assertIn("nenhum documento PENDENTE_ACAO", texto)
        self.assertNotIn("Todos os documentos", texto)
        self.assertNotIn("Concluído", texto)


class TestComandoAlimentarIa(unittest.TestCase):
    def test_zero_lidos_nao_diz_cerebro_atualizado(self):
        if "fitz" not in sys.modules:
            sys.modules["fitz"] = mock.MagicMock()
        sys.modules.setdefault("yfinance", mock.MagicMock())
        import bot.comandos as comandos

        enviadas = []

        class FakeQuery:
            def filter(self, *a, **k):
                return self

            def all(self):
                return []

        class FakeSession:
            def query(self, *a, **k):
                return FakeQuery()

            def close(self):
                return None

        class FakeBot:
            def send_message(self, chat_id, texto, **kwargs):
                enviadas.append(texto)

        mensagem = SimpleNamespace(chat=SimpleNamespace(id=5), text="/alimentar_ia")
        with mock.patch.object(comandos, "bot", FakeBot()), mock.patch(
            "atualizador_documentos.SessionDB", return_value=FakeSession()
        ), mock.patch.object(
            comandos.threading, "Thread", side_effect=_fake_thread
        ):
            comandos.alimentar_ia_passado(mensagem)

        texto = "\n".join(enviadas)
        self.assertIn("nenhum texto extraido", texto)
        self.assertNotIn("Cérebro", texto)
        self.assertNotIn("Atualizado", texto)


if __name__ == "__main__":
    unittest.main()
