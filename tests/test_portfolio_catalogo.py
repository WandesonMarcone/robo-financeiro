import unittest
from unittest.mock import patch
from flask import Flask
from io import BytesIO
from PIL import Image
from services.portfolio_catalogo import paginar
from services.portfolio_logos_web import converter,chave_valida
from services.portfolio_api import portfolio_api

ROWS=[{"ticker":"BBAS3","name":"Banco do Brasil","sector":"Financeiro"},{"ticker":"ABEV3","name":"Ambev","sector":"Consumo"},{"ticker":"B3SA3","name":"B3","sector":"Financeiro"}]

class CatalogTest(unittest.TestCase):
    def test_paginar(self):
        r=paginar(ROWS,page=1,page_size=1,sector="Financeiro")
        self.assertEqual(r["data"][0]["ticker"],"B3SA3")
        self.assertEqual(r["total"],2)
        self.assertTrue(r["has_more"])
        self.assertEqual(r["sectors"],["Consumo","Financeiro"])
        self.assertEqual(paginar(ROWS,q="bánco")["total"],1)
        self.assertEqual(paginar(ROWS,page=9)["data"],[])
    def test_api(self):
        app=Flask(__name__);app.register_blueprint(portfolio_api)
        with patch.dict("os.environ",{"PORTFOLIO_SUPABASE_URL":"https://example.supabase.co","PORTFOLIO_SUPABASE_PUBLISHABLE_KEY":"fake"}), patch("services.portfolio_api._supabase_user",return_value={"id":"1"}),patch("services.portfolio_catalogo.obter_catalogo",return_value=ROWS):
            c=app.test_client();h={"Authorization":"Bearer x"}
            self.assertEqual(c.get("/api/v1/assets?asset_type=stock").status_code,401)
            self.assertEqual(c.get("/api/v1/assets?asset_type=stock&page_size=101",headers=h).status_code,400)
            self.assertEqual(c.get("/api/v1/assets?asset_type=fixed_income",headers=h).status_code,501)
            self.assertEqual(c.get("/api/v1/assets?asset_type=stock&q=ambev",headers=h).json["total"],1)
        with patch.dict("os.environ",{"PORTFOLIO_SUPABASE_URL":"https://example.supabase.co","PORTFOLIO_SUPABASE_PUBLISHABLE_KEY":"fake"}),patch("services.portfolio_api._supabase_user",return_value={"id":"1"}),patch("services.portfolio_catalogo.obter_catalogo",side_effect=RuntimeError):
            self.assertEqual(app.test_client().get("/api/v1/assets?asset_type=stock",headers={"Authorization":"Bearer x"}).status_code,503)
    def test_logo(self):
        b=BytesIO();Image.new("RGB",(300,300),"white").save(b,format="PNG")
        dados=converter(b.getvalue())
        with Image.open(BytesIO(dados)) as im:
            self.assertEqual(im.size,(160,160))
            self.assertEqual(im.format,"WEBP")
        self.assertFalse(chave_valida("stock","../x","a"*64))
        self.assertTrue(chave_valida("stock","BBAS3","a"*64))
