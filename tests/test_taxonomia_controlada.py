import unittest
from types import SimpleNamespace

from services.taxonomia_controlada import (
    POLITICAS_DE_FONTE,
    classificar_texto_fii,
    melhor_evidencia_fii,
)


class TaxonomiaControladaTests(unittest.TestCase):
    def test_relatorio_logistico_tem_evidencia_alta(self):
        texto = """
        Vinci Logística FII – VILG11. Relatório de Desempenho Mensal.
        Tipo Anbima – foco de atuação: FII Renda Gestão Ativa –
        Segmento de Atuação: Logística.
        """
        resultado = classificar_texto_fii(texto, "Relatório Gerencial")
        self.assertEqual((resultado.classe, resultado.segmento, resultado.confianca),
                         ("Tijolo", "Logística", "ALTA"))

    def test_relatorio_cri_nao_vira_tijolo(self):
        texto = """
        Kinea Unique HY CDI. IMOBILIÁRIO CRI. O portfólio é dedicado ao
        investimento em Certificados de Recebíveis Imobiliários (CRI).
        """
        resultado = classificar_texto_fii(texto, "Relatório Gerencial")
        self.assertEqual((resultado.classe, resultado.segmento), ("Papel", "CRI"))

    def test_mencao_solteira_de_outro_fii_nao_e_prova(self):
        self.assertIsNone(classificar_texto_fii(
            "O fundo vendeu cotas de HGLG11 no mercado secundário.", "Relatório Gerencial"))

    def test_prioriza_relatorio_gerencial(self):
        outros = SimpleNamespace(tipo_documento="Fato Relevante", data_publicacao="2026-10-01",
                                  texto_extraido="Sem classificação", resumo_ia=None, assunto=None)
        relatorio = SimpleNamespace(tipo_documento="Relatório Gerencial", data_publicacao="2026-09-30",
                                    texto_extraido="Relatório mensal do fundo. Segmento de Atuação: Logística. " * 3,
                                    resumo_ia=None, assunto=None)
        resultado, documento = melhor_evidencia_fii([outros, relatorio])
        self.assertEqual(resultado.segmento, "Logística")
        self.assertIs(documento, relatorio)

    def test_politicas_separam_classes_de_ativo(self):
        self.assertIn("RELATORIO_GERENCIAL", POLITICAS_DE_FONTE["FII"]["primaria"])
        self.assertIn("B3", POLITICAS_DE_FONTE["ACAO"]["primaria"])
        self.assertIn("FACTSHEET", POLITICAS_DE_FONTE["ETF"]["primaria"])
        self.assertIn("BDR", POLITICAS_DE_FONTE["BDR"]["primaria"])
