import unittest
import io
import zipfile
from datetime import datetime, timedelta, timezone, date
from services.fila_fundamentos_acoes import selecionar_pendentes, resumo_progresso, resumo_erro
from services.fundamentos_valuation import avaliar_cobertura, _escala, extrair_demonstracoes_cvm

class TestFilaFundamentos(unittest.TestCase):
    def test_prioriza_novos_e_respeita_retry(self):
        agora = datetime(2026, 11, 25, tzinfo=timezone.utc)
        estados = {
            "BBAS3": {"ultima_tentativa": agora - timedelta(days=1), "proxima_tentativa": agora},
            "ITSA4": {"ultima_tentativa": agora, "proxima_tentativa": agora + timedelta(days=1)}
        }
        self.assertEqual(selecionar_pendentes(["BBAS3", "PETR4", "ITSA4"], estados, agora, 2), ["PETR4", "BBAS3"])

    def test_novos_nao_ficam_bloqueados_por_falhas(self):
        agora = datetime(2026, 11, 25, tzinfo=timezone.utc)
        estados = {
            "AZZA3": {"estado": "FALHA", "ultima_tentativa": agora - timedelta(hours=1), "proxima_tentativa": agora},
        }
        self.assertEqual(selecionar_pendentes(["AZZA3", "PETR4"], estados, agora, 2), ["PETR4", "AZZA3"])

    def test_progresso_usa_universo_completo(self):
        progresso = resumo_progresso(
            ["BBAS3", "PETR4", "ITSA4", "VALE3"],
            {"BBAS3": {"estado": "OK"}, "PETR4": {"estado": "PARCIAL"}, "ITSA4": {"estado": "FALHA"}},
        )
        self.assertEqual(progresso["total"], 4)
        self.assertEqual(progresso["concluidos"], 2)
        self.assertEqual(progresso["falhas"], 1)
        self.assertEqual(progresso["pendentes"], 1)

    def test_resumo_erro_preserva_motivo_api_sem_segredos(self):
        motivo = resumo_erro(RuntimeError(
            "APIError 429: quota exceeded; token=abc123 Bearer eyJhbGciOiJ.fake"
        ))
        self.assertIn("APIError 429: quota exceeded", motivo)
        self.assertNotIn("abc123", motivo)
        self.assertNotIn("eyJhbGciOiJ.fake", motivo)

    def test_resumo_erro_tem_limite_de_tamanho(self):
        self.assertEqual(len(resumo_erro(RuntimeError("x" * 500))), 240)

    def test_nao_confunde_campos_espalhados_com_historico(self):
        fatos = [{"periodo_fim": date(ano, 12, 31), "periodicidade": "ANUAL", "metrica": "lpa" if ano < 2025 else "vpa"} for ano in range(2021, 2026)]
        metodos = {x["metodo"]: x for x in avaliar_cobertura("TEST3", "ACAO", fatos, [])}
        self.assertEqual(metodos["GRAHAM"]["status"], "PARCIAL")

    def test_composicao_capital(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("dfp_cia_aberta_DRE_con_2025.csv", "CNPJ_CIA;DT_FIM_EXERC;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ESCALA_MOEDA\n00.000.000/0001-91;2025-12-31;ULTIMO;3.01;Receita;100;MIL\n")
            z.writestr("dfp_cia_aberta_composicao_capital_2025.csv", "CNPJ_CIA;DT_REFER;VERSAO;QT_ACAO_ORDIN_CAP_INTEGR;QT_ACAO_PREF_CAP_INTEGR;QT_ACAO_TOTAL_CAP_INTEGR;QT_ACAO_TOTAL_TESOURO\n00.000.000/0001-91;2025-12-31;1;80;20;100;5\n")
        fatos = extrair_demonstracoes_cvm(b.getvalue(), "TEST3", "00.000.000/0001-91", "DFP", 2025)
        self.assertEqual({f["metrica"]: f["valor"] for f in fatos}["acoes_circulacao_ex_tesouraria"], 95)

    def test_composicao_capital_respeita_escala_de_quantidade_da_cvm(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("dfp_cia_aberta_DRE_con_2025.csv", "CNPJ_CIA;DT_FIM_EXERC;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ESCALA_MOEDA\n00.000.000/0001-91;2025-12-31;ULTIMO;3.01;Receita;100;MIL\n")
            z.writestr("dfp_cia_aberta_composicao_capital_2025.csv", "CNPJ_CIA;DT_REFER;VERSAO;ESCALA_MOEDA;QT_ACAO_ORDIN_CAP_INTEGR;QT_ACAO_PREF_CAP_INTEGR;QT_ACAO_TOTAL_CAP_INTEGR;QT_ACAO_TOTAL_TESOURO\n00.000.000/0001-91;2025-12-31;1;MIL;80;20;100;5\n")
        fatos = extrair_demonstracoes_cvm(b.getvalue(), "TEST3", "00.000.000/0001-91", "DFP", 2025)
        mapa = {f["metrica"]: f for f in fatos}
        self.assertEqual(100_000, mapa["acoes_emitidas"]["valor"])
        self.assertEqual(95_000, mapa["acoes_circulacao_ex_tesouraria"]["valor"])
        self.assertEqual("ACOES", mapa["acoes_emitidas"]["unidade"])

    def test_escala_milhoes(self):
        self.assertEqual(_escala({"ESCALA_MOEDA": "MILHÃO"}, "receita_liquida"), 1000000)

if __name__ == "__main__":
    unittest.main()
