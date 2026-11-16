"""Confirma que a contingência EOD não inventa pregão nem duplica coleta."""
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from scripts.persistir_fechamento_eod import executar


AGORA = datetime(2026, 11, 16, 20, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))


def vela(indice, dia):
    return {"indice": indice, "data_pregao": dia, "fechamento": 100.0}


class TesteFechamentoContingencia(unittest.TestCase):
    def test_sem_vela_do_dia_nao_grava(self):
        chamadas = []
        resultado = executar(
            AGORA,
            buscar_indices=lambda: [vela("Ibovespa", date(2026, 11, 13))],
            abrir_planilha=lambda: chamadas.append("planilha"),
            salvar_snapshots=lambda *_: chamadas.append("snapshots"),
            salvar_indices=lambda *_: chamadas.append("indices"),
        )
        self.assertEqual(resultado["status"], "sem_pregao_confirmado")
        self.assertEqual(chamadas, [])

    def test_duas_velas_do_dia_gravam_uma_vez_cada(self):
        datas = []
        resultado = executar(
            AGORA,
            buscar_indices=lambda: [vela("Ibovespa", AGORA.date()),
                                    vela("IFIX", AGORA.date())],
            abrir_planilha=lambda: "planilha",
            salvar_snapshots=lambda planilha, data: {
                "acoes_gravadas": 70, "fiis_gravados": 33
            },
            salvar_indices=lambda registros, data: datas.append(
                (registros[0]["indice"], data)
            ),
        )
        self.assertEqual(resultado["status"], "gravado")
        self.assertEqual(datas, [
            ("IFIX", AGORA.date()), ("Ibovespa", AGORA.date())
        ])

    def test_indice_ausente_interrompe_sem_snapshot(self):
        with self.assertRaisesRegex(RuntimeError, "incompleto"):
            executar(AGORA, buscar_indices=lambda: [
                vela("Ibovespa", AGORA.date())
            ], abrir_planilha=lambda: self.fail("Não deve abrir Sheets"))


if __name__ == "__main__":
    unittest.main()
