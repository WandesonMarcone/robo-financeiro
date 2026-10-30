import unittest
from datetime import date, timedelta
from services.classificacao_ativos import (
    INTERVALO_REANALISE_DIAS, normalizar_classificacao,
    prompt_classificacao_fii, reanalise_devida,
)

class ClassificacaoAtivosTest(unittest.TestCase):
    def test_reanalise_em_quatro_meses(self):
        ultima = date.today() - timedelta(days=INTERVALO_REANALISE_DIAS)
        self.assertTrue(reanalise_devida(ultima))

    def test_papel_sem_segmento_fica_pendente(self):
        r = normalizar_classificacao({
            "tipo_ativo": "FII", "classe": "Papel", "fonte": "cvm",
            "evidencia": "carteira de CRI", "confianca": 98})
        self.assertEqual(r["status"], "pendente")

    def test_high_grade_exige_evidencia(self):
        r = normalizar_classificacao({
            "tipo_ativo": "FII", "classe": "Papel",
            "segmento": "Recebíveis Imobiliários", "subtipo": "CRI",
            "estrategias": ["High Grade"], "fonte": "administrador",
            "evidencia": "carteira de CRI", "confianca": 99})
        self.assertEqual(r["status"], "pendente")

    def test_classificacao_valida(self):
        r = normalizar_classificacao({
            "tipo_ativo": "FII", "classe": "Papel",
            "segmento": "Recebíveis Imobiliários", "subtipo": "CRI",
            "indexadores": ["CDI", "IPCA"], "fonte": "cvm",
            "evidencia": "CRI com grau de investimento; indexação CDI e IPCA",
            "confianca": 95})
        self.assertEqual(r["status"], "aprovada")

    def test_prompt_proibe_inferencia(self):
        p = prompt_classificacao_fii("KNCR11", "documento")
        self.assertIn("não use DY", p)
        self.assertIn("não classifique automaticamente como Tijolo", p)

if __name__ == "__main__":
    unittest.main()
