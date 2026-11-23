import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import Base
from services.configuracoes_sistema import (
    definir_janela_documentos_dias,
    obter_janela_documentos_dias,
)


class ConfiguracoesSistemaTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)()

    def tearDown(self):
        self.session.close()

    def test_defaults_to_30_days_and_persists_120(self):
        self.assertEqual(obter_janela_documentos_dias(self.session), 30)
        result = definir_janela_documentos_dias(120, self.session)
        self.assertEqual(result["days"], 120)
        self.assertEqual(obter_janela_documentos_dias(self.session), 120)

    def test_rejects_out_of_range_values(self):
        with self.assertRaises(ValueError):
            definir_janela_documentos_dias(0, self.session)
        with self.assertRaises(ValueError):
            definir_janela_documentos_dias(366, self.session)


if __name__ == "__main__":
    unittest.main()
