import os
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from flask import Flask

from services.portfolio_api import portfolio_api


class PortfolioApiTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(portfolio_api)
        self.client = self.app.test_client()
        self.env = patch.dict(os.environ, {
            "PORTFOLIO_SUPABASE_URL": "https://example.supabase.co",
            "PORTFOLIO_SUPABASE_PUBLISHABLE_KEY": "public-test-key",
            "PORTFOLIO_WEB_ORIGINS": "https://wandesonmarcone.github.io",
        })
        self.env.start()
        self.identidade = patch("services.portfolio_api._identidade_catalogo",return_value={})
        self.identidade.start()
        self.auth = {"Authorization": "Bearer valid-token"}

    def tearDown(self):
        self.identidade.stop()
        self.env.stop()

    @patch("services.portfolio_api._supabase_user", return_value={"id": "user-1"})
    @patch("services.planilhas.buscar_ativo_na_planilha")
    def test_returns_stock_from_consolidated_sheet(self, lookup, _user):
        lookup.return_value = {
            "preco": "R$ 42,50", "dy": "7,2%", "pvp": "1,05",
            "tipo": "ACAO", "setor": "Financeiro", "atualizado_em": "2026-11-23",
        }
        response = self.client.get(
            "/api/v1/assets/BBAS3?asset_type=stock", headers=self.auth
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["price"], 42.5)
        self.assertEqual(response.json["data"]["indicators"]["dy"], 7.2)

    @patch("services.portfolio_api._supabase_user", return_value={"id": "user-1"})
    @patch("services.coletor_etfs_bdrs.detalhe_instrumento_menu")
    def test_returns_etf_from_neon_instrument_tables(self, detail, _user):
        detail.return_value = ({
            "ticker": "IVVB11", "tipo": "ETF", "fechamento": 410.25,
            "referencia_em": date(2026, 11, 23), "indice_referencia": "S&P 500",
        }, [
            {"chave": "volatilidade_30d", "valor_numerico": 18.4},
            {"chave": "liquidez_media_30d_brl", "valor_numerico": 5000000},
        ])
        response = self.client.get(
            "/api/v1/assets/IVVB11?asset_type=etf", headers=self.auth
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["price"], 410.25)
        self.assertEqual(response.json["data"]["classification"]["subsector"], "S&P 500")
        self.assertEqual(response.json["data"]["indicators"]["volatility_30d"], 18.4)

    @patch("services.portfolio_api._supabase_user", return_value={"id": "user-1"})
    @patch("services.coletor_etfs_bdrs.detalhe_instrumento_menu")
    def test_returns_crypto_from_same_readonly_api(self, detail, _user):
        detail.return_value = ({
            "ticker": "BTCBRL", "tipo": "CRIPTO", "fechamento": 510000,
            "referencia_em": date(2026, 11, 23), "indice_referencia": None,
        }, [{"chave": "volatilidade_30d", "valor_numerico": 52.1}])
        response = self.client.get(
            "/api/v1/assets/BTCBRL?asset_type=crypto", headers=self.auth
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["price"], 510000.0)
        self.assertEqual(response.json["data"]["classification"]["type"], "CRIPTO")

    def test_rejects_request_without_session(self):
        response = self.client.get("/api/v1/assets/BBAS3?asset_type=stock")
        self.assertEqual(response.status_code, 401)

    def test_allows_pages_origin_on_preflight(self):
        response = self.client.options(
            "/api/v1/assets/BBAS3",
            headers={"Origin": "https://wandesonmarcone.github.io"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "https://wandesonmarcone.github.io",
        )

    @patch("services.portfolio_api._supabase_user", return_value={"id": "user-1"})
    @patch("atualizador_documentos.SessionDB")
    def test_returns_income_with_source_quality(self, session_factory, _user):
        class Result:
            def mappings(self): return self
            def all(self):
                return [{
                    "data_ex": date(2026, 11, 10), "data_pagamento": None,
                    "tipo": "DISTRIBUICAO", "valor_unitario": Decimal("0.50"),
                    "moeda": "BRL", "fonte": "YAHOO_FINANCE",
                    "qualidade_fonte": "COMPLEMENTAR",
                }]
        session_factory.return_value.execute.return_value = Result()
        response = self.client.get(
            "/api/v1/assets/BBAS3/income?asset_type=stock&days=30", headers=self.auth
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(0.5, response.json["data"][0]["amount_per_unit"])
        self.assertEqual("COMPLEMENTAR", response.json["data"][0]["source_quality"])
        self.assertEqual(1, response.json["coverage"]["pending_payment_dates"])
        self.assertEqual(1, response.json["coverage"]["complementary_events"])

    @patch("services.portfolio_api._supabase_user", return_value={"id": "user-1"})
    @patch("atualizador_documentos.SessionDB")
    def test_performance_separates_price_and_income(self, session_factory, _user):
        class PriceResult:
            def mappings(self): return self
            def all(self):
                return [
                    {"data": date(2026, 11, 1), "preco": Decimal("10")},
                    {"data": date(2026, 11, 24), "preco": Decimal("11")},
                ]
        class IncomeResult:
            def scalar_one(self): return Decimal("0.50")
        session_factory.return_value.execute.side_effect = [PriceResult(), IncomeResult()]
        response = self.client.get(
            "/api/v1/assets/BBAS3/performance?asset_type=stock&days=30", headers=self.auth
        )
        self.assertEqual(200, response.status_code)
        self.assertAlmostEqual(10, response.json["data"]["price_return_percent"])
        self.assertAlmostEqual(5, response.json["data"]["income_return_percent"])
        self.assertAlmostEqual(15, response.json["data"]["simple_total_return_percent"])
        self.assertFalse(response.json["data"]["personalized_portfolio_return"])


if __name__ == "__main__":
    unittest.main()
