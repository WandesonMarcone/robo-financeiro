"""Testes do catalogo central, taxonomia, importador CVM, IA e cache de logos.

Todos usam SQLite em memoria isolado. Nenhum teste acessa Neon, GitHub, CVM ou
provedores de IA reais.
"""

import json
import os
import sys
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import config
import services.catalogo_ia as catalogo_ia
import services.logo_service as logo_service
from pipeline_dados.banco_dados import Ativo, Base, DadosFinanceirosAcoes, TipoAtivo
from pipeline_dados.coletor_catalogo_cvm import ColetorCatalogoCVM
from pipeline_dados.modelos_catalogo import (
    BaseCatalogo,
    CacheLogoTelegram,
    Empresa,
    EmpresaAtividade,
    EmpresaAtivo,
    EmpresaSegmento,
)
from pipeline_dados.repositorio_catalogo import RepositorioCatalogo
from pipeline_dados.repositorio_logos import RepositorioLogos
from services.catalogo_empresas import aplicar_mapa_setores_b3

CNPJ_PETROBRAS = "33.000.167/0001-01"
CNPJ_PRIO = "06.082.980/0001-03"


class TestCatalogoEmpresas(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        BaseCatalogo.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.repo = RepositorioCatalogo(session_factory=self.Session)
        self._semear_ativos()

    def tearDown(self):
        logo_service.definir_repositorio_logos(None)
        logo_service.limpar_cache_logos()
        self.engine.dispose()

    def _semear_ativos(self):
        sessao = self.Session()
        try:
            sessao.add_all(
                [
                    Ativo(ticker="PETR3", cnpj="PENDENTE-PETR3", tipo=TipoAtivo.ACAO),
                    Ativo(ticker="PETR4", cnpj="PENDENTE-PETR4", tipo=TipoAtivo.ACAO),
                    Ativo(ticker="PRIO3", cnpj="PENDENTE-PRIO3", tipo=TipoAtivo.ACAO),
                ]
            )
            sessao.commit()
        finally:
            sessao.close()

    def _ativo(self, ticker):
        sessao = self.Session()
        try:
            return sessao.query(Ativo).filter(Ativo.ticker == ticker).one()
        finally:
            sessao.close()

    def _contar(self, modelo):
        sessao = self.Session()
        try:
            return sessao.query(modelo).count()
        finally:
            sessao.close()

    # -- Empresa unica / multiplos tickers --------------------------------

    def test_empresa_unica_com_multiplos_tickers_e_dados_separados(self):
        empresa, criada = self.repo.obter_ou_criar_empresa(
            "Petroleo Brasileiro S.A.", cnpj=CNPJ_PETROBRAS
        )
        self.assertTrue(criada)
        self.assertIsNotNone(
            self.repo.vincular_ativo(empresa.id, "PETR3", fonte="teste")
        )
        self.assertIsNotNone(
            self.repo.vincular_ativo(empresa.id, "PETR4", fonte="teste")
        )

        self.assertEqual(self.repo.obter_tickers_da_empresa(empresa.id), ["PETR3", "PETR4"])
        self.assertEqual(self.repo.obter_empresa_por_ticker("PETR3").id, empresa.id)
        self.assertEqual(self.repo.obter_empresa_por_ticker("PETR4").id, empresa.id)

        # Dados financeiros sao por ativo e nunca se misturam entre tickers.
        sessao = self.Session()
        try:
            petr3 = sessao.query(Ativo).filter(Ativo.ticker == "PETR3").one()
            petr4 = sessao.query(Ativo).filter(Ativo.ticker == "PETR4").one()
            sessao.add(
                DadosFinanceirosAcoes(
                    ativo_id=petr3.id,
                    data_referencia=date(2026, 6, 30),
                    tipo_doc="ITR",
                    receita=123.0,
                )
            )
            sessao.commit()
            self.assertEqual(
                sessao.query(DadosFinanceirosAcoes)
                .filter(DadosFinanceirosAcoes.ativo_id == petr3.id)
                .count(),
                1,
            )
            self.assertEqual(
                sessao.query(DadosFinanceirosAcoes)
                .filter(DadosFinanceirosAcoes.ativo_id == petr4.id)
                .count(),
                0,
            )
        finally:
            sessao.close()

    def test_upsert_de_empresa_nao_duplica_por_cnpj_ou_nome(self):
        primeira, criada = self.repo.obter_ou_criar_empresa(
            "Petroleo Brasileiro S.A.", cnpj=CNPJ_PETROBRAS
        )
        segunda, criada_2 = self.repo.obter_ou_criar_empresa(
            "PETROLEO BRASILEIRO S.A.", cnpj="33000167000101"
        )
        self.assertTrue(criada)
        self.assertFalse(criada_2)
        self.assertEqual(primeira.id, segunda.id)
        self.assertEqual(self._contar(Empresa), 1)

    # -- Taxonomia e historico -------------------------------------------

    def test_setores_sem_duplicidade_e_historico_preservado(self):
        empresa, _ = self.repo.obter_ou_criar_empresa(
            "Petroleo Brasileiro S.A.", cnpj=CNPJ_PETROBRAS
        )
        setor_a = self.repo.obter_ou_criar_setor("Petroleo, Gas & Biocombustiveis")
        setor_a_2 = self.repo.obter_ou_criar_setor("Petroleo, Gas & Biocombustiveis")
        self.assertEqual(setor_a, setor_a_2)
        sub_a = self.repo.obter_ou_criar_subsetor(setor_a, "Exploracao e Refino")

        _, criado = self.repo.classificar_empresa(empresa.id, setor_a, sub_a)
        self.assertTrue(criado)
        _, criado_2 = self.repo.classificar_empresa(empresa.id, setor_a, sub_a)
        self.assertFalse(criado_2)
        self.assertEqual(self._contar(EmpresaSegmento), 1)

        setor_b = self.repo.obter_ou_criar_setor("Utilidade Publica")
        sub_b = self.repo.obter_ou_criar_subsetor(setor_b, "Energia")
        _, mudou = self.repo.classificar_empresa(empresa.id, setor_b, sub_b)
        self.assertTrue(mudou)

        sessao = self.Session()
        try:
            linhas = (
                sessao.query(EmpresaSegmento)
                .filter(EmpresaSegmento.empresa_id == empresa.id)
                .order_by(EmpresaSegmento.id)
                .all()
            )
        finally:
            sessao.close()
        self.assertEqual(len(linhas), 2)
        self.assertFalse(linhas[0].vigente)
        self.assertEqual(linhas[0].status, "historico")
        self.assertTrue(linhas[1].vigente)

    def test_subsetor_de_outro_setor_e_rejeitado(self):
        empresa, _ = self.repo.obter_ou_criar_empresa(
            "Petroleo Brasileiro S.A.", cnpj=CNPJ_PETROBRAS
        )
        setor_a = self.repo.obter_ou_criar_setor("Petroleo")
        setor_b = self.repo.obter_ou_criar_setor("Financeiro")
        sub_b = self.repo.obter_ou_criar_subsetor(setor_b, "Bancos")
        with self.assertRaises(ValueError):
            self.repo.classificar_empresa(empresa.id, setor_a, sub_b)

    def test_classificar_setor_nao_herda_atividades(self):
        empresa, _ = self.repo.obter_ou_criar_empresa(
            "Petroleo Brasileiro S.A.", cnpj=CNPJ_PETROBRAS
        )
        setor = self.repo.obter_ou_criar_setor("Petroleo")
        sub = self.repo.obter_ou_criar_subsetor(setor, "Exploracao e Refino")
        self.repo.classificar_empresa(empresa.id, setor, sub)
        self.assertEqual(self._contar(EmpresaAtividade), 0)

        atividade = self.repo.obter_ou_criar_atividade("Refino de petroleo")
        self.repo.adicionar_atividade(empresa.id, atividade)
        self.repo.adicionar_atividade(empresa.id, atividade)
        self.assertEqual(self._contar(EmpresaAtividade), 1)

    # -- Importador oficial CVM FCA --------------------------------------

    def _dataframes_fca(self):
        geral = pd.DataFrame(
            [
                {
                    "CNPJ_Companhia": CNPJ_PETROBRAS,
                    "Nome_Empresarial": "PETROLEO BRASILEIRO S.A. PETROBRAS",
                    "Setor_Atividade": "Petroleo e Gas",
                    "Descricao_Atividade": "Exploracao e producao de petroleo",
                    "Situacao_Emissor": "Fase Operacional",
                    "Data_Referencia": "2026-01-01",
                },
                {
                    "CNPJ_Companhia": CNPJ_PRIO,
                    "Nome_Empresarial": "PRIO S.A.",
                    "Setor_Atividade": "Petroleo e Gas",
                    "Descricao_Atividade": "Producao de petroleo em campos",
                    "Situacao_Emissor": "Fase Operacional",
                    "Data_Referencia": "2026-01-01",
                },
            ]
        )
        valores = pd.DataFrame(
            [
                {
                    "CNPJ_Companhia": CNPJ_PETROBRAS,
                    "Codigo_Negociacao": "PETR3",
                    "Mercado": "Bolsa",
                    "Data_Fim_Negociacao": "",
                },
                {
                    "CNPJ_Companhia": CNPJ_PETROBRAS,
                    "Codigo_Negociacao": "PETR4",
                    "Mercado": "Bolsa",
                    "Data_Fim_Negociacao": "",
                },
                {
                    "CNPJ_Companhia": CNPJ_PRIO,
                    "Codigo_Negociacao": "PRIO3",
                    "Mercado": "Bolsa",
                    "Data_Fim_Negociacao": "",
                },
                {
                    "CNPJ_Companhia": CNPJ_PRIO,
                    "Codigo_Negociacao": "PRIO4",
                    "Mercado": "Bolsa",
                    "Data_Fim_Negociacao": "2025-01-01",
                },
            ]
        )
        return geral, valores

    def test_importador_cvm_cria_empresa_unica_e_tickers_oficiais(self):
        coletor = ColetorCatalogoCVM(repositorio=self.repo)
        geral, valores = self._dataframes_fca()
        resumo = coletor.importar_dataframes(
            geral, valores, fonte="https://dados.cvm.gov.br/fca"
        )

        self.assertIsNone(resumo["erro"])
        self.assertEqual(resumo["empresas_criadas"], 2)
        petrobras = self.repo.obter_empresa_por_cnpj(CNPJ_PETROBRAS)
        prio = self.repo.obter_empresa_por_cnpj(CNPJ_PRIO)
        self.assertEqual(self.repo.obter_tickers_da_empresa(petrobras.id), ["PETR3", "PETR4"])
        self.assertEqual(self.repo.obter_tickers_da_empresa(prio.id), ["PRIO3"])

        resumo_petro = self.repo.obter_resumo_empresa("PETR3")
        resumo_prio = self.repo.obter_resumo_empresa("PRIO3")
        self.assertEqual(resumo_petro["setor"], "Petróleo, Gás & Biocombustíveis")
        self.assertEqual(
            resumo_petro["atividades"], ["Exploracao e producao de petroleo"]
        )
        self.assertEqual(resumo_prio["atividades"], ["Producao de petroleo em campos"])

    def test_reimportacao_cvm_nao_duplica(self):
        coletor = ColetorCatalogoCVM(repositorio=self.repo)
        geral, valores = self._dataframes_fca()
        coletor.importar_dataframes(geral, valores, fonte="https://dados.cvm.gov.br/fca")
        resumo = coletor.importar_dataframes(
            geral, valores, fonte="https://dados.cvm.gov.br/fca"
        )
        self.assertEqual(resumo["empresas_criadas"], 0)
        self.assertEqual(self._contar(Empresa), 2)
        self.assertEqual(self._contar(EmpresaAtivo), 3)
        self.assertEqual(self._contar(EmpresaSegmento), 2)

    def test_falha_de_fonte_nao_altera_banco(self):
        def http_falha(*args, **kwargs):
            raise RuntimeError("fora do ar")

        coletor = ColetorCatalogoCVM(
            repositorio=self.repo, http_get=http_falha
        )
        resumo = coletor.importar(2026)
        self.assertIn("Falha ao baixar FCA", resumo["erro"])
        self.assertEqual(self._contar(Empresa), 0)

    def test_dataframe_invalido_nao_altera_banco(self):
        coletor = ColetorCatalogoCVM(repositorio=self.repo)
        resumo = coletor.importar_dataframes(
            pd.DataFrame([{"x": 1}]), pd.DataFrame([{"y": 2}])
        )
        self.assertIn("Colunas obrigatorias", resumo["erro"])
        self.assertEqual(self._contar(Empresa), 0)

    # -- Mapa setorial B3 ------------------------------------------------

    def test_mapa_b3_classifica_empresa_e_nao_cria_atividade(self):
        petrobras, _ = self.repo.obter_ou_criar_empresa(
            "Petroleo Brasileiro S.A.", cnpj=CNPJ_PETROBRAS
        )
        self.repo.vincular_ativo(petrobras.id, "PETR4")
        resumo = aplicar_mapa_setores_b3(
            repositorio=self.repo,
            mapa={
                "Petroleo, Gas & Biocombustiveis": {
                    "Exploracao e Refino": ["PETR3", "PETR4"]
                }
            },
        )
        self.assertEqual(resumo["empresas_classificadas"], 1)
        dados = self.repo.obter_resumo_empresa("PETR4")
        self.assertEqual(dados["setor"], "Petróleo, Gás & Biocombustíveis")
        self.assertEqual(dados["subsetor"], "Exploração e Refino")
        self.assertEqual(dados["atividades"], [])
        self.assertEqual(self._contar(EmpresaAtividade), 0)

    # -- IA --------------------------------------------------------------

    def _analisador(self, payload):
        return lambda prompt, system_prompt=None: json.dumps(payload)

    def test_ia_oficial_com_confianca_cria_catalogo(self):
        payload = {
            "empresas": [
                {
                    "nome": "PETROLEO BRASILEIRO S.A. PETROBRAS",
                    "cnpj": CNPJ_PETROBRAS,
                    "tickers": ["PETR3", "PETR4"],
                    "setor": "Petroleo e Gas",
                    "subsetor": "Exploracao e Refino",
                    "atividades": ["Refino de petroleo"],
                    "confianca": 98,
                    "evidencia": "A companhia PETROBRAS informa refino de petroleo.",
                    "justificativa": "Fonte oficial e evidencia literal.",
                }
            ]
        }
        resumo = catalogo_ia.processar_texto_monitorado(
            "A companhia PETROBRAS informa refino de petroleo.",
            fonte="https://dados.cvm.gov.br/fca",
            repositorio=self.repo,
            analisador=self._analisador(payload),
        )
        self.assertIsNone(resumo["erro"])
        self.assertEqual(resumo["empresas_criadas"], 1)
        self.assertEqual(self.repo.obter_tickers_da_empresa(
            self.repo.obter_empresa_por_cnpj(CNPJ_PETROBRAS).id
        ), ["PETR3", "PETR4"])
        dados = self.repo.obter_resumo_empresa("PETR4")
        self.assertEqual(dados["atividades"], ["Refino de petroleo"])

    def test_ia_ambigua_vai_para_revisao_sem_criar(self):
        payload = {
            "empresas": [
                {
                    "nome": "EMPRESA NOVA S.A.",
                    "cnpj": "",
                    "tickers": ["NOVA3"],
                    "setor": "Setor Incerto",
                    "atividades": ["Atividade Incerta"],
                    "confianca": 40,
                    "evidencia": "Nome citado em um blog.",
                    "justificativa": "Sem CNPJ e fonte nao oficial.",
                }
            ]
        }
        resumo = catalogo_ia.processar_texto_monitorado(
            "Nome citado em um blog.",
            fonte="https://blog.example.com/post",
            repositorio=self.repo,
            analisador=self._analisador(payload),
        )
        self.assertEqual(resumo["sugestoes"], 1)
        self.assertEqual(self._contar(Empresa), 0)
        pendentes = self.repo.listar_sugestoes_pendentes()
        self.assertEqual(len(pendentes), 1)
        self.assertIn("fonte nao oficial", pendentes[0].justificativa)

    def test_ia_nao_duplica_empresa_ticker_setor_ou_atividade(self):
        payload = {
            "empresas": [
                {
                    "nome": "PETROLEO BRASILEIRO S.A. PETROBRAS",
                    "cnpj": CNPJ_PETROBRAS,
                    "tickers": ["PETR3", "PETR4"],
                    "setor": "Petroleo e Gas",
                    "atividades": ["Refino de petroleo"],
                    "confianca": 99,
                    "evidencia": "PETROBRAS atua em refino.",
                    "justificativa": "Fonte oficial.",
                }
            ]
        }
        analisador = self._analisador(payload)
        primeiro = catalogo_ia.processar_texto_monitorado(
            "PETROBRAS atua em refino.",
            fonte="https://dados.cvm.gov.br/fca",
            repositorio=self.repo,
            analisador=analisador,
        )
        segundo = catalogo_ia.processar_texto_monitorado(
            "PETROBRAS atua em refino.",
            fonte="https://dados.cvm.gov.br/fca",
            repositorio=self.repo,
            analisador=analisador,
        )
        self.assertEqual(primeiro["empresas_criadas"], 1)
        self.assertEqual(segundo["empresas_criadas"], 0)
        self.assertEqual(self._contar(Empresa), 1)
        self.assertEqual(self._contar(EmpresaAtivo), 2)
        self.assertEqual(self._contar(EmpresaSegmento), 1)
        self.assertEqual(self._contar(EmpresaAtividade), 1)

    def test_falha_da_ia_nao_altera_banco(self):
        resumo = catalogo_ia.processar_texto_monitorado(
            "texto",
            fonte="https://dados.cvm.gov.br/fca",
            repositorio=self.repo,
            analisador=lambda prompt, system_prompt=None: "❌ Erro critico na IA.",
        )
        self.assertIn("Falha ao obter/validar", resumo["erro"])
        self.assertEqual(self._contar(Empresa), 0)
        self.assertEqual(len(self.repo.listar_sugestoes_pendentes()), 0)

    # -- Cache persistente de logo do Telegram ---------------------------

    def test_file_id_persistente_e_compartilhado_por_empresa(self):
        empresa, _ = self.repo.obter_ou_criar_empresa(
            "Petroleo Brasileiro S.A.", cnpj=CNPJ_PETROBRAS
        )
        self.repo.vincular_ativo(empresa.id, "PETR3")
        self.repo.vincular_ativo(empresa.id, "PETR4")
        repo_logos = RepositorioLogos(session_factory=self.Session)
        logo_service.definir_repositorio_logos(repo_logos)
        logo_service.limpar_cache_logos()

        logo_service.registrar_file_id_logo("PETR3", "FILE-PETR")
        # Simula reinicio do bot: apenas o cache em memoria e limpo.
        logo_service.limpar_cache_logos()
        self.assertEqual(logo_service.obter_file_id_logo("PETR4"), "FILE-PETR")

        sessao = self.Session()
        try:
            registro = sessao.query(CacheLogoTelegram).one()
            self.assertEqual(registro.empresa_id, empresa.id)
            self.assertEqual(registro.file_id, "FILE-PETR")
            self.assertEqual(registro.status, "ativo")
        finally:
            sessao.close()

    def test_cache_negativo_expira_e_nao_reutiliza_file_id_invalido(self):
        empresa, _ = self.repo.obter_ou_criar_empresa(
            "Petroleo Brasileiro S.A.", cnpj=CNPJ_PETROBRAS
        )
        self.repo.vincular_ativo(empresa.id, "PETR4")
        repo_logos = RepositorioLogos(session_factory=self.Session)
        repo_logos.registrar_file_id("PETR4", "FILE-ANTIGO")
        agora = datetime.utcnow()
        repo_logos.registrar_falha(
            "PETR4", erro="HTTP 400", ttl_segundos=60, agora=agora
        )
        self.assertIsNone(repo_logos.obter_file_id("PETR4", agora=agora))
        self.assertIsNone(
            repo_logos.obter_file_id("PETR4", agora=agora + timedelta(seconds=61))
        )
        registro = repo_logos.obter_registro("PETR4")
        self.assertEqual(registro.status, "negativo")
        self.assertEqual(registro.falhas, 1)
        self.assertIsNone(registro.file_id)

        repo_logos.registrar_file_id("PETR4", "FILE-NOVO")
        self.assertEqual(
            repo_logos.obter_file_id("PETR4", agora=agora + timedelta(seconds=61)),
            "FILE-NOVO",
        )

    def test_falha_de_logo_limpa_memoria_e_evita_media_rapida(self):
        repo_logos = RepositorioLogos(session_factory=self.Session)
        logo_service.definir_repositorio_logos(repo_logos)
        logo_service.limpar_cache_logos()
        logo_service.registrar_file_id_logo("PETR4", "FILE-PETR")
        logo_service.registrar_falha_logo("PETR4", erro="HTTP 400")
        self.assertIsNone(logo_service.obter_file_id_logo("PETR4"))
        self.assertEqual(logo_service.obter_media_logo_rapida("PETR4"), "")


class TestFonteOficial(unittest.TestCase):
    def test_dominios_oficiais(self):
        self.assertTrue(catalogo_ia._fonte_oficial("https://dados.cvm.gov.br/x"))
        self.assertTrue(catalogo_ia._fonte_oficial("https://www.b3.com.br/x"))
        self.assertFalse(catalogo_ia._fonte_oficial("https://blog.example.com/x"))
        self.assertFalse(catalogo_ia._fonte_oficial("CVM"))


if __name__ == "__main__":
    unittest.main()
