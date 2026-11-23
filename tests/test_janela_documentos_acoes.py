"""Regressões da janela móvel de 30 dias dos documentos IPE/CVM."""

import csv
import io
import unittest
import zipfile
from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import Ativo, Base, DocumentosQualitativos, TipoAtivo
from pipeline_dados.coletor_docs_acoes import (
    RelatoriosAcoesCVM,
    janela_documental_30_dias,
)
from scripts.processar_documentos_pendentes import arquivar_fora_da_janela


def _zip_ipe(linhas):
    texto = io.StringIO()
    escritor = csv.DictWriter(
        texto,
        fieldnames=["CNPJ_Companhia", "Link_Download", "Data_Referencia", "Categoria", "Assunto"],
        delimiter=";",
    )
    escritor.writeheader()
    escritor.writerows(linhas)
    conteudo = io.BytesIO()
    with zipfile.ZipFile(conteudo, "w") as pacote:
        pacote.writestr("ipe_cia_aberta_2026.csv", texto.getvalue().encode("latin1"))
    return conteudo.getvalue()


class TesteJanelaDocumentosAcoes(unittest.TestCase):
    def test_janela_inclui_somente_ultimos_30_dias(self):
        inicio, fim = janela_documental_30_dias(date(2026, 11, 23))
        self.assertEqual(inicio, date(2026, 10, 24))
        self.assertEqual(fim, date(2026, 11, 23))

    def test_janela_de_30_dias_cruza_ano(self):
        inicio, fim = janela_documental_30_dias(date(2027, 1, 10))
        self.assertEqual(inicio, date(2026, 12, 11))
        self.assertEqual(fim, date(2027, 1, 10))

    def test_periodo_solicitado_e_limitado_a_30_dias(self):
        inicio, fim = janela_documental_30_dias(date(2027, 2, 10))
        self.assertEqual(inicio, date(2027, 1, 11))
        self.assertEqual(fim, date(2027, 2, 10))

    def test_coletor_grava_somente_documentos_dentro_da_janela(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        sessao = sessionmaker(bind=engine)()
        try:
            sessao.add(Ativo(
                ticker="BBAS3",
                cnpj="00.000.000/0001-91",
                tipo=TipoAtivo.ACAO,
            ))
            sessao.commit()
            conteudo = _zip_ipe([
                {
                    "CNPJ_Companhia": "00.000.000/0001-91",
                    "Link_Download": "https://cvm.example/antigo.pdf",
                    "Data_Referencia": "2026-06-30",
                    "Categoria": "Apresentação de Resultados",
                    "Assunto": "Resultado do segundo trimestre",
                },
                {
                    "CNPJ_Companhia": "00.000.000/0001-91",
                    "Link_Download": "https://cvm.example/atual.pdf",
                    "Data_Referencia": "2026-11-10",
                    "Categoria": "Apresentação de Resultados",
                    "Assunto": "Resultado do terceiro trimestre",
                },
            ])
            resposta = SimpleNamespace(status_code=200, content=conteudo)
            resultado = RelatoriosAcoesCVM(
                session=sessao,
                http_get=lambda *_args, **_kwargs: resposta,
            ).vasculhar_documentos(
                data_inicio=date(2026, 7, 1),
                data_fim=date(2026, 11, 23),
            )

            documentos = sessao.query(DocumentosQualitativos).all()
            self.assertEqual(resultado.gravados, 1)
            self.assertEqual(len(documentos), 1)
            self.assertEqual(documentos[0].url_pdf, "https://cvm.example/atual.pdf")
        finally:
            sessao.close()
            engine.dispose()

    def test_processamento_retira_historico_e_datas_futuras_da_fila(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        sessao = sessionmaker(bind=engine)()
        try:
            fii = Ativo(
                ticker="MXRF11", cnpj="00.000.000/0001-01",
                tipo=TipoAtivo.FII,
            )
            acao = Ativo(
                ticker="BBAS3", cnpj="00.000.000/0001-02",
                tipo=TipoAtivo.ACAO,
            )
            sessao.add_all([fii, acao])
            sessao.flush()
            sessao.add_all([
                DocumentosQualitativos(
                    ativo_id=fii.id, data_publicacao=date(2026, 9, 1),
                    tipo_documento="Documento",
                    status_processamento="PENDENTE",
                ),
                DocumentosQualitativos(
                    ativo_id=fii.id, data_publicacao=date(2026, 11, 10),
                    tipo_documento="Documento",
                    status_processamento="PENDENTE",
                ),
                DocumentosQualitativos(
                    ativo_id=acao.id, data_publicacao=date(2026, 6, 30),
                    tipo_documento="Documento",
                    status_processamento="PENDENTE_ACAO",
                ),
                DocumentosQualitativos(
                    ativo_id=acao.id, data_publicacao=date(3026, 4, 30),
                    tipo_documento="Documento",
                    status_processamento="PENDENTE_ACAO",
                ),
                DocumentosQualitativos(
                    ativo_id=acao.id, data_publicacao=date(2026, 11, 10),
                    tipo_documento="Documento",
                    status_processamento="PENDENTE_ACAO",
                ),
            ])
            sessao.commit()

            resumo = arquivar_fora_da_janela(date(2026, 11, 23), sessao)
            status = [
                item.status_processamento
                for item in sessao.query(DocumentosQualitativos).order_by(
                    DocumentosQualitativos.id
                )
            ]
            self.assertEqual(resumo["fiis"], 1)
            self.assertEqual(resumo["acoes"], 2)
            self.assertEqual(status, [
                "FORA_JANELA", "PENDENTE", "FORA_JANELA",
                "FORA_JANELA", "PENDENTE_ACAO",
            ])
        finally:
            sessao.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
