"""A consulta de favoritos aceita filtro opcional sem parâmetro SQL ambíguo."""
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline_dados.repositorio_favoritos_internacionais import RepositorioFavoritosInternacionais


class TestFavoritosInternacionaisSql(unittest.TestCase):
    def test_consulta_com_e_sem_tipo(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE instrumentos_internacionais (id INTEGER, ticker TEXT, tipo TEXT, ativo BOOLEAN)")
            conn.exec_driver_sql("CREATE TABLE favoritos_instrumentos_internacionais (id INTEGER, usuario_id INTEGER, instrumento_id INTEGER, criado_em TEXT)")
            conn.exec_driver_sql("INSERT INTO instrumentos_internacionais VALUES (1, 'BOVA11', 'ETF', 1), (2, 'HMRN31', 'BDR', 1)")
            conn.exec_driver_sql("INSERT INTO favoritos_instrumentos_internacionais VALUES (1, 7, 1, '2026-11-17'), (2, 7, 2, '2026-11-17')")
        repo = RepositorioFavoritosInternacionais(sessionmaker(bind=engine))
        self.assertEqual(repo.resolver_instrumento("BOVA11")["tipo"], "ETF")
        self.assertIsNone(repo.resolver_instrumento("BOVA11", "BDR"))
        self.assertEqual([x.ticker for x in repo.listar(7)], ["BOVA11", "HMRN31"])
        self.assertEqual([x.ticker for x in repo.listar(7, "BDR")], ["HMRN31"])


if __name__ == "__main__":
    unittest.main()
