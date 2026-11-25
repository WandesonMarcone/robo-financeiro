import unittest
from unittest.mock import patch
from flask import Flask
from io import BytesIO
from PIL import Image
from services.portfolio_catalogo import paginar, _ler_neon
from services.portfolio_logos_web import converter,chave_valida
from services.portfolio_api import portfolio_api

ROWS=[{"ticker":"BBAS3","name":"Banco do Brasil","sector":"Financeiro"},{"ticker":"ABEV3","name":"Ambev","sector":"Consumo"},{"ticker":"B3SA3","name":"B3","sector":"Financeiro"}]

class CatalogResult:
    def __init__(self, rows=(), scalar=None): self.rows,self.value=rows,scalar
    def scalar(self): return self.value
    def mappings(self): return self
    def __iter__(self): return iter(self.rows)

class CatalogSession:
    def __init__(self, oficial): self.oficial,self.sql=oficial,[]
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self, statement, params=None):
        query=str(statement);self.sql.append(query)
        if "universo_acoes_autorizadas" in query and "to_regclass" in query:
            return CatalogResult(scalar=self.oficial)
        if "cadastro_cnpj_acoes" in query and "to_regclass" in query:
            return CatalogResult(scalar=False)
        return CatalogResult()

class CatalogTest(unittest.TestCase):
    def test_acoes_usam_lista_autorizada_quando_disponivel(self):
        session=CatalogSession(True)
        _ler_neon("stock",session_factory=lambda:session)
        consulta=next(q for q in session.sql if "WITH universo AS" in q)
        self.assertIn("SELECT ticker FROM universo_acoes_autorizadas",consulta)
        self.assertNotIn("UNION SELECT ticker FROM ativos_catalogo",consulta)

    def test_catalogo_mantem_fallback_antes_da_migracao_da_lista(self):
        session=CatalogSession(False)
        _ler_neon("stock",session_factory=lambda:session)
        consulta=next(q for q in session.sql if "WITH universo AS" in q)
        self.assertIn("SELECT ticker FROM ativos WHERE tipo::text=:tipo",consulta)
        self.assertIn("UNION SELECT ticker FROM ativos_catalogo",consulta)

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
