"""Regressão da contagem de documentos numa busca FNET isolada."""
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import Ativo, Base, TipoAtivo
from pipeline_dados.coletor_fnet import ColetorFnet


class TesteFnetIsolado(unittest.TestCase):
    def test_conta_apenas_documentos_do_fundo_solicitado(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        sessao = sessionmaker(bind=engine)()
        try:
            sessao.add_all([
                Ativo(ticker="GARE11", cnpj="00.000.000/0001-01", tipo=TipoAtivo.FII),
                Ativo(ticker="MXRF11", cnpj="00.000.000/0001-02", tipo=TipoAtivo.FII),
            ])
            sessao.commit()
            documentos = [
                {"id": "fnet-gare", "nome_fundo": "GUARDIAN REAL ESTATE",
                 "tipo_doc": "Relatório gerencial", "data_referencia": "01-11-2026"},
                {"id": "fnet-mxrf", "nome_fundo": "MAXI RENDA",
                 "tipo_doc": "Relatório gerencial", "data_referencia": "01-11-2026"},
                {"id": "fnet-desconhecido", "nome_fundo": "FUNDO DESCONHECIDO",
                 "tipo_doc": "Relatório gerencial", "data_referencia": "01-11-2026"},
            ]
            resultado = ColetorFnet(
                session=sessao, capturar_tudo=lambda _data: documentos
            ).coletar(dias=60, ticker="GARE11")
            self.assertEqual(resultado.informes_encontrados, 1)
            self.assertEqual(resultado.gravados, 1)
            self.assertEqual(resultado.sem_ativo, 0)
            self.assertEqual(resultado.por_ativo["GARE11"]["novos"], 1)
        finally:
            sessao.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
