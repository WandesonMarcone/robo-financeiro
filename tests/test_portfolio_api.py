import os
import unittest
from datetime import date
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
        self.auth = {"Authorization": "Bearer valid-token"}

    def tearDown(self):
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


if __name__ == "__main__":
    unittest.main()
