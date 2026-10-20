"""Testes de regressao da auditoria do catalogo (P0, P1, P3 e P4).

Todos usam SQLite isolado em memoria apenas para a logica de repositorio/servico.
As constraints, indices, migracoes e concorrencia reais sao validadas em
PostgreSQL por ``tests/test_catalogo_postgres.py``.
"""

import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import services.catalogo_ia as catalogo_ia
import services.logo_service as logo_service
from pipeline_dados.banco_dados import Ativo, Base, TipoAtivo
from pipeline_dados.coletor_catalogo_cvm import ColetorCatalogoCVM
from pipeline_dados.modelos_catalogo import (
    BaseCatalogo,
    Empresa,
    EmpresaAtivo,
    EmpresaSegmento,
    SugestaoCatalogo,
)
from pipeline_dados.repositorio_catalogo import (
    ConflitoEmpresa,
    ConflitoVinculoAtivo,
    DecisaoSugestaoInvalida,
    RepositorioCatalogo,
    ticker_negociacao_valido,
)
from pipeline_dados.repositorio_logos import RepositorioLogos

CNPJ_PETROBRAS = "33.000.167/0001-01"
CNPJ_PRIO = "06.082.980/0001-03"
CNPJ_NOVA = "11.222.333/0001-81"


class CatalogoCorrecoesBase(unittest.TestCase):
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
        sessao = self.Session()
        try:
            sessao.add_all([
                Ativo(ticker="PETR3", cnpj="PENDENTE-PETR3", tipo=TipoAtivo.ACAO),
                Ativo(ticker="PETR4", cnpj="PENDENTE-PETR4", tipo=TipoAtivo.ACAO),
                Ativo(ticker="PRIO3", cnpj="PENDENTE-PRIO3", tipo=TipoAtivo.ACAO),
            ])
            sessao.commit()
        finally:
            sessao.close()

    def tearDown(self):
        logo_service.definir_repositorio_logos(None)
        logo_service.limpar_cache_logos()
        self.engine.dispose()

    def _contar(self, modelo):
        sessao = self.Session()
        try:
            return sessao.query(modelo).count()
        finally:
            sessao.close()

    def _empresa(self, nome, cnpj=None):
        return self.repo.obter_ou_criar_empresa(nome, cnpj=cnpj)[0]


class TestP0Integridade(CatalogoCorrecoesBase):
    def test_ticker_em_outra_empresa_e_recusado_sem_trocar_dono(self):
        petro = self._empresa("Petrobras", CNPJ_PETROBRAS)
        prio = self._empresa("PRIO", CNPJ_PRIO)
        self.repo.vincular_ativo(petro.id, "PETR4", fonte="teste")

        with self.assertRaises(ConflitoVinculoAtivo):
            self.repo.vincular_ativo(prio.id, "PETR4", fonte="teste")

        self.assertEqual(self.repo.obter_empresa_por_ticker("PETR4").id, petro.id)
        self.assertEqual(self._contar(EmpresaAtivo), 1)

    def test_mesmo_ticker_na_mesma_empresa_e_idempotente(self):
        petro = self._empresa("Petrobras", CNPJ_PETROBRAS)
        self.repo.vincular_ativo(petro.id, "PETR4", fonte="teste")
        self.repo.vincular_ativo(petro.id, "PETR4", fonte="teste")
        self.assertEqual(self._contar(EmpresaAtivo), 1)

    def test_cnpj_diferente_com_mesmo_nome_nao_e_fundido(self):
        petro = self._empresa("Petroleo Brasileiro S.A.", CNPJ_PETROBRAS)

        with self.assertRaises(ConflitoEmpresa):
            self.repo.obter_ou_criar_empresa(
                "Petroleo Brasileiro S.A.", cnpj=CNPJ_PRIO
            )

        self.assertEqual(self._contar(Empresa), 1)
        self.assertEqual(self.repo.obter_empresa_por_cnpj(CNPJ_PETROBRAS).id, petro.id)
        self.assertIsNone(self.repo.obter_empresa_por_cnpj(CNPJ_PRIO))

    def test_empresa_sem_cnpj_nao_inventa_identificador(self):
        empresa, criada = self.repo.obter_ou_criar_empresa("Fundo Sem CNPJ")
        self.assertTrue(criada)
        self.assertIsNone(empresa.cnpj)

        invalida, criada_invalida = self.repo.obter_ou_criar_empresa(
            "Fundo Sem CNPJ", cnpj="123.456"
        )
        self.assertFalse(criada_invalida)
        self.assertEqual(invalida.id, empresa.id)
        self.assertIsNone(invalida.cnpj)
        self.assertEqual(self._contar(Empresa), 1)

        oficial, criada_oficial = self.repo.obter_ou_criar_empresa(
            "Fundo Sem CNPJ", cnpj=CNPJ_NOVA
        )
        self.assertFalse(criada_oficial)
        self.assertEqual(oficial.id, empresa.id)
        self.assertEqual(oficial.cnpj, CNPJ_NOVA)

    def test_nome_ambiguo_sem_cnpj_nao_escolhe_primeiro(self):
        sessao = self.Session()
        try:
            sessao.add_all([
                Empresa(nome="Empresa Homônima", cnpj=None),
                Empresa(nome="Empresa Homônima", cnpj=None),
            ])
            sessao.commit()
        finally:
            sessao.close()

        with self.assertRaises(ConflitoEmpresa):
            self.repo.obter_ou_criar_empresa("Empresa Homônima")
        with self.assertRaises(ConflitoEmpresa):
            self.repo.obter_ou_criar_empresa("Empresa Homônima", cnpj=CNPJ_NOVA)
        self.assertEqual(self._contar(Empresa), 2)


class TestP1ImportacaoEClassificacao(CatalogoCorrecoesBase):
    def _fca(self):
        geral = pd.DataFrame([
            {
                "CNPJ_Companhia": CNPJ_PETROBRAS,
                "Nome_Empresarial": "PETROBRAS VERSAO NOVA",
                "Setor_Atividade": "Petroleo e Gas",
                "Descricao_Atividade": "Refino novo",
                "Data_Referencia": "2026-12-31",
                "Versao": "2",
            },
            {
                "CNPJ_Companhia": CNPJ_PETROBRAS,
                "Nome_Empresarial": "PETROBRAS VERSAO ANTIGA",
                "Setor_Atividade": "Petroleo e Gas",
                "Descricao_Atividade": "Refino antigo",
                "Data_Referencia": "2025-12-31",
                "Versao": "1",
            },
            {
                "CNPJ_Companhia": CNPJ_PRIO,
                "Nome_Empresarial": "PRIO S.A.",
                "Setor_Atividade": "Petroleo e Gas",
                "Descricao_Atividade": "Producao",
                "Data_Referencia": "2026-01-01",
                "Versao": "1",
            },
        ])
        valores = pd.DataFrame([
            {
                "CNPJ_Companhia": CNPJ_PETROBRAS,
                "Codigo_Negociacao": "B3SA3",
                "Mercado": "Mercado de Titulos Publicos",
                "Tipo": "Derivativo",
                "Data_Referencia": "2025-01-01",
                "Versao": "1",
                "Data_Fim_Negociacao": "",
            },
            {
                "CNPJ_Companhia": CNPJ_PETROBRAS,
                "Codigo_Negociacao": "B3SA3",
                "Mercado": "Bolsa",
                "Tipo": "Acoes",
                "Data_Referencia": "2026-01-01",
                "Versao": "2",
                "Data_Fim_Negociacao": "",
            },
            {
                "CNPJ_Companhia": CNPJ_PRIO,
                "Codigo_Negociacao": "PRIO3",
                "Mercado": "Bolsa",
                "Tipo": "Acoes",
                "Data_Referencia": "2026-01-01",
                "Versao": "1",
                "Data_Fim_Negociacao": "",
            },
            {
                "CNPJ_Companhia": CNPJ_PRIO,
                "Codigo_Negociacao": "PRIO4",
                "Mercado": "Bolsa",
                "Tipo": "Acoes",
                "Data_Referencia": "2026-01-01",
                "Versao": "1",
                "Data_Fim_Negociacao": "2025-01-01",
            },
        ])
        return geral, valores

    def test_cvm_prioriza_data_e_versao_e_aceita_b3sa3(self):
        coletor = ColetorCatalogoCVM(repositorio=self.repo)
        resumo = coletor.importar_dataframes(
            *self._fca(), fonte="https://dados.cvm.gov.br/fca"
        )

        self.assertIsNone(resumo["erro"])
        petro = self.repo.obter_empresa_por_cnpj(CNPJ_PETROBRAS)
        self.assertEqual(petro.nome, "PETROBRAS VERSAO NOVA")
        self.assertEqual(self.repo.obter_tickers_da_empresa(petro.id), ["B3SA3"])
        self.assertEqual(
            self.repo.obter_resumo_empresa("B3SA3")["atividades"], ["Refino novo"]
        )
        prio = self.repo.obter_empresa_por_cnpj(CNPJ_PRIO)
        self.assertEqual(self.repo.obter_tickers_da_empresa(prio.id), ["PRIO3"])

    def test_formato_de_ticker_aceita_raiz_alfanumerica(self):
        for ticker in ("PETR4", "MXRF11", "B3SA3", "AURA33"):
            self.assertTrue(ticker_negociacao_valido(ticker), ticker)
        for ticker in ("ABCD", "1234", "ABC", "ABCDE", "PETR4X"):
            self.assertFalse(ticker_negociacao_valido(ticker), ticker)

    def test_precedencia_cvm_sobre_b3_preserva_historico(self):
        empresa = self._empresa("Petrobras", CNPJ_PETROBRAS)
        self.repo.vincular_ativo(empresa.id, "PETR3", fonte="teste")
        setor_b3 = self.repo.obter_ou_criar_setor("Financeiro")
        setor_cvm = self.repo.obter_ou_criar_setor("Petroleo e Gas")

        self.repo.classificar_empresa(
            empresa.id, setor_b3, fonte="config.MAPA_SETORES_B3"
        )
        self.repo.classificar_empresa(
            empresa.id, setor_cvm, fonte="https://dados.cvm.gov.br/fca"
        )
        # B3 (menor precedencia) nao pode reverter a CVM.
        self.repo.classificar_empresa(
            empresa.id, setor_b3, fonte="config.MAPA_SETORES_B3"
        )

        sessao = self.Session()
        try:
            linhas = (
                sessao.query(EmpresaSegmento)
                .filter(EmpresaSegmento.empresa_id == empresa.id)
                .order_by(EmpresaSegmento.id)
                .all()
            )
            resumo = self.repo.obter_resumo_empresa("PETR3")
        finally:
            sessao.close()

        self.assertEqual(len(linhas), 2)
        self.assertFalse(linhas[0].vigente)
        self.assertEqual(linhas[0].status, "historico")
        self.assertTrue(linhas[1].vigente)
        self.assertIn("cvm", linhas[1].fonte)
        self.assertEqual(resumo["setor"], "Petróleo, Gás & Biocombustíveis")

    def test_setores_e_subsetores_semanticos_nao_duplicam(self):
        setor_a = self.repo.obter_ou_criar_setor("Petroleo e Gas")
        setor_b = self.repo.obter_ou_criar_setor(
            "Petróleo, Gás & Biocombustíveis"
        )
        self.assertEqual(setor_a, setor_b)

        sub_a = self.repo.obter_ou_criar_subsetor(setor_a, "Exploração e Produção")
        sub_b = self.repo.obter_ou_criar_subsetor(setor_b, "Exploração e Refino")
        self.assertEqual(sub_a, sub_b)


class TestP3AprovacaoIA(CatalogoCorrecoesBase):
    def _payload_setor_novo(self):
        return {
            "empresas": [{
                "nome": "NOVA EMPRESA S.A.",
                "cnpj": CNPJ_NOVA,
                "tickers": ["NOVA3"],
                "setor": "Setor Experimental",
                "subsetor": "Subsetor Experimental",
                "atividades": ["Atividade Experimental"],
                "confianca": 99,
                "evidencia": "NOVA EMPRESA S.A. atua em atividade experimental.",
                "justificativa": "Fonte oficial com evidencia literal.",
            }]
        }

    def _sugestao_pendente(self):
        resumo = catalogo_ia.processar_texto_monitorado(
            "NOVA EMPRESA S.A. atua em atividade experimental.",
            fonte="https://dados.cvm.gov.br/fca",
            repositorio=self.repo,
            analisador=lambda prompt, system_prompt=None: json.dumps(
                self._payload_setor_novo()
            ),
        )
        self.assertEqual(resumo["sugestoes"], 1)
        pendentes = self.repo.listar_sugestoes_pendentes()
        self.assertEqual(len(pendentes), 1)
        return pendentes[0]

    def test_ia_fora_da_taxonomia_so_sugere_e_aprovacao_aplica(self):
        self.assertEqual(self._contar(Empresa), 0)
        sugestao = self._sugestao_pendente()
        self.assertEqual(self._contar(Empresa), 0)

        self.assertEqual(
            self.repo.aprovar_sugestao(sugestao.id, decidido_por="admin:1"),
            sugestao.id,
        )

        empresa = self.repo.obter_empresa_por_cnpj(CNPJ_NOVA)
        self.assertIsNotNone(empresa)
        self.assertEqual(self.repo.obter_tickers_da_empresa(empresa.id), ["NOVA3"])
        resumo = self.repo.obter_resumo_empresa("NOVA3")
        self.assertEqual(resumo["setor"], "Setor Experimental")
        self.assertEqual(resumo["subsetor"], "Subsetor Experimental")
        self.assertEqual(resumo["atividades"], ["Atividade Experimental"])

        sessao = self.Session()
        try:
            atual = sessao.query(SugestaoCatalogo).filter_by(id=sugestao.id).one()
            self.assertEqual(atual.status, "aplicada")
            self.assertEqual(atual.decidido_por, "admin:1")
            self.assertIsNotNone(atual.decidido_em)
            self.assertIn("cvm", atual.fonte)
        finally:
            sessao.close()

    def test_aprovacao_idempotente_e_rejeicao_contraditoria_recusada(self):
        sugestao = self._sugestao_pendente()
        self.repo.aprovar_sugestao(sugestao.id, decidido_por="admin:1")
        empresas = self._contar(Empresa)
        vinculos = self._contar(EmpresaAtivo)

        self.repo.aprovar_sugestao(sugestao.id, decidido_por="admin:2")
        self.assertEqual(self._contar(Empresa), empresas)
        self.assertEqual(self._contar(EmpresaAtivo), vinculos)

        with self.assertRaises(DecisaoSugestaoInvalida):
            self.repo.decidir_sugestao(
                sugestao.id, "rejeitada", decidido_por="admin:3"
            )

    def test_conflito_de_ticker_devolve_sugestao_para_pendente_sem_empresa_parcial(self):
        petro = self._empresa("Petrobras", CNPJ_PETROBRAS)
        self.repo.vincular_ativo(petro.id, "PETR4", fonte="teste")
        sugestao_id, _ = self.repo.registrar_sugestao(
            "empresa",
            "outra-empresa",
            dados={
                "nome": "OUTRA EMPRESA S.A.",
                "cnpj": CNPJ_PRIO,
                "tickers": ["PETR4"],
                "setor": "Petroleo e Gas",
            },
            fonte="https://dados.cvm.gov.br/fca",
            evidencia="Outra empresa tentou assumir PETR4.",
        )

        with self.assertRaises(ConflitoVinculoAtivo):
            self.repo.aprovar_sugestao(sugestao_id, decidido_por="admin:1")

        sessao = self.Session()
        try:
            sugestao = sessao.query(SugestaoCatalogo).filter_by(id=sugestao_id).one()
            self.assertEqual(sugestao.status, "pendente")
        finally:
            sessao.close()
        # Pre-validacao impede criar a empresa B antes de detectar o conflito.
        self.assertIsNone(self.repo.obter_empresa_por_cnpj(CNPJ_PRIO))
        self.assertEqual(self.repo.obter_empresa_por_ticker("PETR4").id, petro.id)


class TestP4LogosPersistentes(CatalogoCorrecoesBase):
    def test_petr3_e_petr4_compartilham_logo_com_apenas_um_vinculo(self):
        petro = self._empresa("Petrobras", CNPJ_PETROBRAS)
        # Apenas PETR3 foi vinculado; PETR4 ainda nao possui linha em
        # empresa_ativos. A identidade visual da empresa deve valer para ambos.
        self.repo.vincular_ativo(petro.id, "PETR3", fonte="teste")
        repo_logos = RepositorioLogos(session_factory=self.Session)
        logo_service.definir_repositorio_logos(repo_logos)
        logo_service.limpar_cache_logos()

        logo_service.registrar_file_id_logo("PETR3", "FILE-PETR-UNICO")
        logo_service.limpar_cache_logos()  # simula reinicio do bot

        self.assertEqual(logo_service.obter_file_id_logo("PETR3"), "FILE-PETR-UNICO")
        self.assertEqual(logo_service.obter_file_id_logo("PETR4"), "FILE-PETR-UNICO")

    def test_invalidar_file_id_permite_resolver_nova_media(self):
        repo_logos = RepositorioLogos(session_factory=self.Session)
        logo_service.definir_repositorio_logos(repo_logos)
        logo_service.limpar_cache_logos()
        logo_service.registrar_file_id_logo("PETR4", "FILE-EXPIRADO")
        self.assertEqual(logo_service.obter_file_id_logo("PETR4"), "FILE-EXPIRADO")

        logo_service.invalidar_file_id_logo("PETR4", erro="HTTP 400")
        self.assertIsNone(logo_service.obter_file_id_logo("PETR4"))

        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
        with mock.patch.dict(os.environ, {"LOGO_DEV_TOKEN": "token-teste"}), \
             mock.patch.object(
            logo_service.requests, "get", return_value=mock.Mock(
                status_code=200,
                headers={"Content-Type": "image/png"},
                content=png,
            )
        ):
            url = logo_service.obter_link_logo("PETR4")
        self.assertIn("img.logo.dev", url)
        self.assertIn("ticker:PETR4.SA", url)


if __name__ == "__main__":
    unittest.main()
