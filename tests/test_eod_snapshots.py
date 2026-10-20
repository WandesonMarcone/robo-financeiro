"""Writer EOD de snapshots (Sheets -> Neon), isolado do cron de producao.

Nenhum teste acessa DATABASE_URL real nem o Google. Persistencia usa SQLite
em memoria. Falhas de conexao sao simuladas.
"""

import os
import sys
import unittest
from datetime import date, datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytz  # noqa: E402
from sqlalchemy import create_engine, inspect, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app as app_mod  # noqa: E402
import modules.eod_snapshots as eod  # noqa: E402
from pipeline_dados.banco_dados import Ativo, Base, TipoAtivo  # noqa: E402
from pipeline_dados.modelos_snapshots import (  # noqa: E402
    BaseSnapshots,
    SnapshotAcao,
    SnapshotFii,
)
from pipeline_dados.repositorio_snapshots import persistir_snapshots  # noqa: E402

SP_TZ = pytz.timezone("America/Sao_Paulo")
COLETA = datetime(2026, 10, 19, 18, 5, tzinfo=SP_TZ)


def _linha_acao(ticker, **campos):
    linha = [""] * 33
    linha[0] = ticker
    mapa = {
        "preco": 2,
        "dy": 3,
        "pl": 5,
        "pvp": 6,
        "p_ativo": 7,
        "marg_bruta": 8,
        "marg_ebit": 9,
        "marg_liquida": 10,
        "p_ebit": 11,
        "ev_ebit": 12,
        "div_liq_patrimonio": 13,
        "psr": 15,
        "p_cap_giro": 16,
        "p_at_circ_liq": 17,
        "liq_corrente": 18,
        "roe": 19,
        "roa": 20,
        "roic": 21,
        "cagr_rec_5a": 25,
        "liq_media": 27,
        "vpa": 28,
        "lpa": 29,
        "peg_ratio": 30,
        "valor_mercado": 31,
    }
    for nome, valor in campos.items():
        linha[mapa[nome]] = valor
    return linha


def _linha_fii(ticker, **campos):
    linha = [""] * 18
    linha[0] = ticker
    mapa = {
        "preco": 3,
        "pvp": 5,
        "dy": 6,
        "qtd_imoveis": 8,
        "liquidez": 12,
        "vpa": 14,
        "lucro_12m": 15,
        "dividendo_mensal": 16,
    }
    for nome, valor in campos.items():
        linha[mapa[nome]] = valor
    return linha


CABECALHO_ACAO = ["Papel"] + ["x"] * 32
CABECALHO_FII = [
    "Ticker", "Tipo", "Setor", "Preço", "Qtd", "P/VP", "DY", "Vacância",
    "Imóveis", "Inquilinos", "WALT", "Alav", "Liquidez", "Valor Mercado",
    "VPA", "Lucro", "Div Mensal", "Atualização",
]


def _num(valor):
    if valor is None:
        return None
    return float(valor)


class TestMapeamentoSheets(unittest.TestCase):
    def test_mapeia_campos_de_acao(self):
        linhas = [
            CABECALHO_ACAO,
            _linha_acao(
                "PETR4",
                preco="38,50",
                dy="12,00%",
                pl="6,50",
                pvp="1,20",
                roe="18,00%",
                peg_ratio="1,2",
                valor_mercado="1000",
            ),
        ]
        payloads = eod.montar_payloads_acoes(linhas, COLETA)
        self.assertEqual(len(payloads), 1)
        p = payloads[0]
        self.assertEqual(p["ticker"], "PETR4")
        self.assertEqual(p["preco"], 38.5)
        self.assertAlmostEqual(p["dy"], 0.12)
        self.assertAlmostEqual(p["pl"], 6.5)
        self.assertAlmostEqual(p["pvp"], 1.2)
        self.assertAlmostEqual(p["roe"], 0.18)
        self.assertEqual(p["peg_ratio"], 1.2)
        self.assertEqual(p["fonte"], "Google Sheets")
        self.assertNotIn("cagr_lucro_5a", p)
        self.assertNotIn("div_liq_ebit", p)
        self.assertNotIn("giro_ativos", p)

    def test_mapeia_campos_de_fii(self):
        linhas = [
            CABECALHO_FII,
            _linha_fii(
                "MXRF11",
                preco="9,36",
                pvp="1,01",
                dy="11,34%",
                qtd_imoveis="2",
                liquidez="24953800",
                vpa="9,05",
                lucro_12m="600000000",
                dividendo_mensal="0,09",
            ),
        ]
        payloads = eod.montar_payloads_fiis(linhas, COLETA)
        self.assertEqual(len(payloads), 1)
        p = payloads[0]
        self.assertEqual(p["ticker"], "MXRF11")
        self.assertEqual(p["preco"], 9.36)
        self.assertAlmostEqual(p["pvp"], 1.01)
        self.assertAlmostEqual(p["dy"], 0.1134)
        self.assertEqual(p["qtd_imoveis"], 2)
        self.assertNotIn("walt", p)
        self.assertNotIn("alavancagem", p)
        self.assertNotIn("vacancia", p)

    def test_catalogo_completo_nao_so_fila(self):
        linhas = [
            CABECALHO_ACAO,
            _linha_acao("PETR4", preco="38"),
            _linha_acao("VALE3", preco="60"),
            _linha_acao("WEGE3", preco="40"),
        ]
        payloads = eod.montar_payloads_acoes(linhas, COLETA)
        self.assertEqual([p["ticker"] for p in payloads], ["PETR4", "VALE3", "WEGE3"])

    def test_ausente_invalido_omitido_zero_nao_inventado(self):
        linhas = [
            CABECALHO_ACAO,
            _linha_acao(
                "PETR4",
                preco="-",
                dy="",
                pl="N/D",
                pvp="1,20",
                peg_ratio="",
                roe="0",
            ),
        ]
        p = eod.montar_payloads_acoes(linhas, COLETA)[0]
        self.assertNotIn("preco", p)
        self.assertNotIn("dy", p)
        self.assertNotIn("pl", p)
        self.assertNotIn("peg_ratio", p)
        self.assertAlmostEqual(p["pvp"], 1.2)
        self.assertEqual(p["roe"], 0.0)

    def test_preco_zero_nao_entra(self):
        p = eod.montar_payloads_acoes(
            [CABECALHO_ACAO, _linha_acao("PETR4", preco="0", pvp="1,1")],
            COLETA,
        )[0]
        self.assertNotIn("preco", p)
        self.assertAlmostEqual(p["pvp"], 1.1)

    def test_qtd_imoveis_zero_preservado(self):
        p = eod.montar_payloads_fiis(
            [CABECALHO_FII, _linha_fii("MXRF11", preco="9", qtd_imoveis="0")],
            COLETA,
        )[0]
        self.assertEqual(p["qtd_imoveis"], 0)
        self.assertEqual(p["preco"], 9.0)

    def test_data_referencia_e_civil_sp(self):
        dt = datetime(2026, 10, 19, 21, 30, tzinfo=pytz.UTC)
        self.assertEqual(eod.data_referencia_eod(dt), date(2026, 10, 19))
        dt_sp = datetime(2026, 10, 20, 0, 30, tzinfo=SP_TZ)
        self.assertEqual(eod.data_referencia_eod(dt_sp), date(2026, 10, 20))


class TestPersistenciaSqlite(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        BaseSnapshots.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        sessao = self.Session()
        sessao.add_all(
            [
                Ativo(ticker="PETR4", cnpj="cnpj-PETR4", tipo=TipoAtivo.ACAO),
                Ativo(ticker="MXRF11", cnpj="cnpj-MXRF11", tipo=TipoAtivo.FII),
            ]
        )
        sessao.commit()
        sessao.close()

    def tearDown(self):
        self.engine.dispose()

    def _persistir(self, acoes, fiis, data_ref=date(2026, 10, 19)):
        return persistir_snapshots(acoes, fiis, data_ref, session_factory=self.Session)

    def test_schema_compativel(self):
        insp = inspect(self.engine)
        cols_a = {c["name"] for c in insp.get_columns("snapshots_acoes")}
        cols_f = {c["name"] for c in insp.get_columns("snapshots_fiis")}
        for nome in (
            "ativo_id",
            "data_referencia",
            "data_coleta",
            "preco",
            "pl",
            "pvp",
            "peg_ratio",
            "fonte_primaria",
            "fonte_intermediaria",
        ):
            self.assertIn(nome, cols_a)
        for nome in (
            "ativo_id",
            "data_referencia",
            "preco",
            "pvp",
            "qtd_imoveis",
            "walt",
            "alavancagem",
            "dividendo_mensal",
            "fonte_intermediaria",
        ):
            self.assertIn(nome, cols_f)
        self.assertNotIn("vacancia", cols_f)

    def test_grava_acao_e_fii_com_ids(self):
        acoes = eod.montar_payloads_acoes(
            [CABECALHO_ACAO, _linha_acao("PETR4", preco="38,5", pl="6,5")],
            COLETA,
        )
        fiis = eod.montar_payloads_fiis(
            [CABECALHO_FII, _linha_fii("MXRF11", preco="9,36", dy="0")],
            COLETA,
        )
        resumo = self._persistir(acoes, fiis)
        self.assertEqual(resumo["acoes_gravadas"], 1)
        self.assertEqual(resumo["fiis_gravados"], 1)
        sessao = self.Session()
        acao = sessao.execute(select(SnapshotAcao)).scalar_one()
        fii = sessao.execute(select(SnapshotFii)).scalar_one()
        petr = sessao.execute(select(Ativo).where(Ativo.ticker == "PETR4")).scalar_one()
        mxrf = sessao.execute(select(Ativo).where(Ativo.ticker == "MXRF11")).scalar_one()
        self.assertEqual(acao.ativo_id, petr.id)
        self.assertEqual(fii.ativo_id, mxrf.id)
        self.assertEqual(_num(acao.preco), 38.5)
        self.assertEqual(_num(acao.pl), 6.5)
        self.assertIsNone(acao.peg_ratio)
        self.assertEqual(_num(fii.preco), 9.36)
        self.assertEqual(_num(fii.dy), 0.0)
        self.assertIsNone(acao.data_publicacao)
        sessao.close()

    def test_ticker_desconhecido_omitido(self):
        acoes = eod.montar_payloads_acoes(
            [CABECALHO_ACAO, _linha_acao("XXXX3", preco="10")],
            COLETA,
        )
        resumo = self._persistir(acoes, [])
        self.assertEqual(resumo["acoes_gravadas"], 0)
        self.assertEqual(resumo["omitidos_sem_ativo"], 1)
        sessao = self.Session()
        self.assertEqual(sessao.execute(select(SnapshotAcao)).scalars().all(), [])
        sessao.close()

    def test_sem_indicador_valido_nao_grava(self):
        acoes = eod.montar_payloads_acoes(
            [CABECALHO_ACAO, _linha_acao("PETR4", preco="-", pl="N/D")],
            COLETA,
        )
        resumo = self._persistir(acoes, [])
        self.assertEqual(resumo["acoes_gravadas"], 0)
        self.assertEqual(resumo["omitidos_sem_dados"], 1)

    def test_idempotencia_mesma_data_preserva_validos(self):
        data_ref = date(2026, 10, 19)
        primeiro = eod.montar_payloads_acoes(
            [CABECALHO_ACAO, _linha_acao("PETR4", preco="38,5", pl="6,5", pvp="1,20")],
            COLETA,
        )
        self._persistir(primeiro, [], data_ref)
        segundo = eod.montar_payloads_acoes(
            [CABECALHO_ACAO, _linha_acao("PETR4", preco="39,0", pl="-", dy="10,00%")],
            COLETA,
        )
        resumo = self._persistir(segundo, [], data_ref)
        self.assertEqual(resumo["acoes_gravadas"], 1)
        sessao = self.Session()
        linhas = sessao.execute(select(SnapshotAcao)).scalars().all()
        self.assertEqual(len(linhas), 1)
        self.assertEqual(_num(linhas[0].preco), 39.0)
        self.assertEqual(_num(linhas[0].pl), 6.5)
        self.assertAlmostEqual(_num(linhas[0].pvp), 1.2)
        self.assertAlmostEqual(_num(linhas[0].dy), 0.10)
        sessao.close()


class TestIsolamento(unittest.TestCase):
    def test_flag_desligada_nao_persiste(self):
        planilha = mock.Mock()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EOD_SNAPSHOTS", None)
            with mock.patch.object(eod, "persistir_catalogo_sheets") as persistir:
                saida = eod.tentar_persistir_eod(planilha, COLETA)
        self.assertIsNone(saida)
        persistir.assert_not_called()

    def test_database_url_ausente_nao_quebra(self):
        planilha = mock.Mock()
        planilha.worksheet.return_value.get_all_values.return_value = [CABECALHO_ACAO]

        class BancoNaoConfiguradoError(RuntimeError):
            pass

        with mock.patch(
            "pipeline_dados.repositorio_snapshots.persistir_snapshots",
            side_effect=BancoNaoConfiguradoError("DATABASE_URL ausente"),
        ):
            saida = eod.persistir_catalogo_sheets(planilha, COLETA)
        self.assertIsNone(saida)

    def test_falha_de_conexao_nao_expoe_segredo(self):
        planilha = mock.Mock()
        planilha.worksheet.return_value.get_all_values.return_value = [
            CABECALHO_ACAO,
            _linha_acao("PETR4", preco="10"),
        ]
        with mock.patch(
            "pipeline_dados.repositorio_snapshots.persistir_snapshots",
            side_effect=RuntimeError(
                "could not connect postgresql://user:segredo@host/db"
            ),
        ), mock.patch.object(eod.logger, "error") as log_erro:
            saida = eod.persistir_catalogo_sheets(planilha, COLETA)
        self.assertIsNone(saida)
        texto = " ".join(str(c) for c in log_erro.call_args[0])
        self.assertIn("RuntimeError", texto)
        self.assertNotIn("segredo", texto)

    def test_app_grava_sheets_mesmo_com_neon_fora(self):
        aba_fiis = mock.Mock()
        aba_acoes = mock.Mock()
        planilha = mock.Mock()
        planilha.worksheet.side_effect = lambda nome: {
            "BD_FIIs": aba_fiis,
            "BD_Acoes": aba_acoes,
        }[nome]
        aba_fiis.get_all_values.return_value = [CABECALHO_FII]
        aba_acoes.get_all_values.return_value = [CABECALHO_ACAO]
        gc = mock.Mock()
        gc.open_by_url.return_value = planilha
        upd_fii = [{"range": "D2", "values": [[9.36]]}]
        upd_acao = [{"range": "C2", "values": [[38.5]]}]

        with mock.patch.object(app_mod, "conectar_gspread", return_value=gc), mock.patch.object(
            app_mod, "rodar_garimpo_fiis", return_value=(upd_fii, "", aba_fiis)
        ), mock.patch.object(
            app_mod, "rodar_garimpo_acoes", return_value=(upd_acao, "", aba_acoes)
        ), mock.patch.object(
            app_mod, "disparar_alertas"
        ) as alertas, mock.patch.dict(
            os.environ, {"EOD_SNAPSHOTS": "1"}
        ), mock.patch(
            "pipeline_dados.repositorio_snapshots.persistir_snapshots",
            side_effect=ConnectionError("neon down"),
        ):
            app_mod.executar_auditoria_carteira()

        aba_fiis.batch_update.assert_called_once_with(upd_fii)
        aba_acoes.batch_update.assert_called_once_with(upd_acao)
        alertas.assert_not_called()

    def test_app_sem_flag_nao_chama_persistencia(self):
        aba_fiis = mock.Mock()
        aba_acoes = mock.Mock()
        planilha = mock.Mock()
        gc = mock.Mock()
        gc.open_by_url.return_value = planilha
        with mock.patch.object(app_mod, "conectar_gspread", return_value=gc), mock.patch.object(
            app_mod, "rodar_garimpo_fiis", return_value=([], "", aba_fiis)
        ), mock.patch.object(
            app_mod, "rodar_garimpo_acoes", return_value=([], "", aba_acoes)
        ), mock.patch.object(
            app_mod, "disparar_alertas"
        ), mock.patch.dict(
            os.environ, {}, clear=False
        ), mock.patch.object(
            eod, "persistir_catalogo_sheets"
        ) as persistir:
            os.environ.pop("EOD_SNAPSHOTS", None)
            app_mod.executar_auditoria_carteira()
        persistir.assert_not_called()
        aba_fiis.batch_update.assert_not_called()
        aba_acoes.batch_update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
