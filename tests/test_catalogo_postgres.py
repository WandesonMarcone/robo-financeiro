"""Testes PostgreSQL reais do catalogo central.

Diferentemente dos testes SQLite, estes exercitam as constraints, os indices
parciais, as migracoes e a concorrencia no mesmo dialeto usado em producao.

Como executar (banco local/descartavel, NUNCA o Neon)::

    TEST_DATABASE_URL=postgresql+psycopg://usuario:senha@127.0.0.1:5432/robo_test \
        python3 -m unittest tests.test_catalogo_postgres -v

Sem ``TEST_DATABASE_URL`` os testes sao ignorados. Por seguranca, a URL so e
aceita quando o host e local (localhost/127.0.0.1/::1). Cada teste cria um
schema exclusivo e NAO remove/apaga nada.
"""

import os
import sys
import threading
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from pipeline_dados.banco_dados import Ativo
from pipeline_dados.conexao import normalizar_database_url
from pipeline_dados.modelos_catalogo import (
    AtividadeEconomica,
    CacheLogoTelegram,
    Empresa,
    EmpresaAtividade,
    EmpresaAtivo,
    EmpresaSegmento,
    Setor,
    Subsetor,
    SugestaoCatalogo,
)
from pipeline_dados.repositorio_catalogo import (
    ConflitoEmpresa,
    ConflitoVinculoAtivo,
    RepositorioCatalogo,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
RAIZ = Path(__file__).resolve().parent.parent
MIGRACOES = (
    "0005_catalogo_empresas.sql",
    "0006_cache_logos_telegram.sql",
    "0007_empresa_ativo_unico.sql",
)
CNPJ_A = "33.000.167/0001-01"
CNPJ_B = "06.082.980/0001-03"
CNPJ_C = "11.222.333/0001-81"


def _url_local(url):
    if not url:
        return False
    limpa = url.replace("postgresql+psycopg://", "postgresql://", 1)
    limpa = limpa.replace("postgres://", "postgresql://", 1)
    host = urlparse(limpa).hostname
    return host in (None, "localhost", "127.0.0.1", "::1")


def _dsn(url):
    limpa = url.replace("postgresql+psycopg://", "postgresql://", 1)
    return limpa.replace("postgres://", "postgresql://", 1)


def _sql_up(nome):
    sql = (RAIZ / "migrations" / "versions" / nome).read_text(encoding="utf-8")
    return sql.split("-- +migrate Down", 1)[0]


class PostgresCatalogoTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not TEST_DATABASE_URL:
            raise unittest.SkipTest("TEST_DATABASE_URL nao definido")
        if not _url_local(TEST_DATABASE_URL):
            raise unittest.SkipTest(
                "TEST_DATABASE_URL nao aponta para um banco local; "
                "testes PostgreSQL recusam ambientes remotos/Neon"
            )
        cls.engine_admin = create_engine(
            normalizar_database_url(TEST_DATABASE_URL)
        )
        with cls.engine_admin.connect() as conexao:
            conexao.execute(text("SELECT 1"))

    @classmethod
    def tearDownClass(cls):
        cls.engine_admin.dispose()

    def setUp(self):
        self.schema = f"cat_test_{uuid.uuid4().hex[:12]}"
        with self.engine_admin.begin() as conexao:
            conexao.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_engine(
            normalizar_database_url(TEST_DATABASE_URL),
            connect_args={"options": f"-csearch_path={self.schema}"},
        )
        # A migracao 0005 depende da tabela legada "ativos" ja existente.
        Ativo.__table__.create(self.engine)
        self._aplicar_migracoes()
        self.Session = sessionmaker(bind=self.engine)
        self.repo = RepositorioCatalogo(session_factory=self.Session)

    def tearDown(self):
        self.engine.dispose()

    def _aplicar_migracoes(self):
        with psycopg.connect(_dsn(TEST_DATABASE_URL), autocommit=True) as conexao:
            conexao.execute(f'SET search_path TO "{self.schema}"')
            for nome in MIGRACOES:
                conexao.execute(_sql_up(nome))

    def _empresa(self, nome, cnpj=None):
        return self.repo.obter_ou_criar_empresa(nome, cnpj=cnpj)[0]

    def _contar(self, modelo):
        with self.Session() as sessao:
            return sessao.query(modelo).count()

    def _consultar(self, sql, **parametros):
        with self.engine.connect() as conexao:
            return conexao.execute(text(sql), parametros).fetchall()


class TestMigracoesEIndices(PostgresCatalogoTestCase):
    def test_indices_e_constraints_do_modelo_existem_no_banco(self):
        indices_banco = {
            nome
            for (nome,) in self._consultar(
                "SELECT indexname FROM pg_indexes WHERE schemaname = :schema",
                schema=self.schema,
            )
        }
        constraints_banco = {
            nome
            for (nome,) in self._consultar(
                """
                SELECT c.conname
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = :schema
                """,
                schema=self.schema,
            )
        }
        modelos = (
            Empresa,
            Setor,
            Subsetor,
            AtividadeEconomica,
            EmpresaAtivo,
            EmpresaSegmento,
            EmpresaAtividade,
            SugestaoCatalogo,
            CacheLogoTelegram,
        )
        for modelo in modelos:
            for indice in modelo.__table__.indexes:
                self.assertIn(indice.name, indices_banco, modelo.__tablename__)
            for constraint in modelo.__table__.constraints:
                if constraint.name and constraint.__class__.__name__ in (
                    "UniqueConstraint",
                    "PrimaryKeyConstraint",
                ):
                    self.assertIn(
                        constraint.name, constraints_banco, modelo.__tablename__
                    )

        # Regras parciais que nao podem ser representadas por UNIQUE comum.
        parciais = {
            nome: definicao
            for nome, definicao in self._consultar(
                """
                SELECT indexname, indexdef FROM pg_indexes
                WHERE schemaname = :schema AND indexdef ILIKE '%WHERE%'
                """,
                schema=self.schema,
            )
        }
        self.assertIn("uix_empresa_segmento_principal_vigente", parciais)
        self.assertIn("uix_empresa_atividade_vigente", parciais)
        self.assertIn("uix_sugestao_catalogo_pendente", parciais)
        self.assertIn("vigente", parciais["uix_empresa_segmento_principal_vigente"])
        self.assertIn("vigente", parciais["uix_empresa_atividade_vigente"])
        self.assertIn("pendente", parciais["uix_sugestao_catalogo_pendente"])

    def test_migracoes_sao_idempotentes(self):
        self._aplicar_migracoes()
        self.assertEqual(
            self._consultar(
                """
                SELECT count(*) FROM pg_tables
                WHERE schemaname = :schema AND tablename = 'empresas'
                """,
                schema=self.schema,
            )[0][0],
            1,
        )

    def test_ativo_pertence_a_no_maximo_uma_empresa_no_banco(self):
        a = self._empresa("Empresa A", CNPJ_A)
        b = self._empresa("Empresa B", CNPJ_B)
        self.repo.vincular_ativo(
            a.id, "PETR4", fonte="teste", criar_ativo=True
        )
        with self.Session() as sessao:
            ativo_id = sessao.query(Ativo).filter_by(ticker="PETR4").one().id

        with self.assertRaises(IntegrityError):
            with self.Session() as sessao:
                sessao.add(
                    EmpresaAtivo(empresa_id=b.id, ativo_id=ativo_id)
                )
                sessao.commit()

        self.assertEqual(self._contar(EmpresaAtivo), 1)


class TestIntegridadeP0Postgres(PostgresCatalogoTestCase):
    def test_cnpj_diferente_mesmo_nome_nao_funde(self):
        self._empresa("Petroleo Brasileiro S.A.", CNPJ_A)
        with self.assertRaises(ConflitoEmpresa):
            self.repo.obter_ou_criar_empresa(
                "Petroleo Brasileiro S.A.", cnpj=CNPJ_B
            )
        self.assertEqual(self._contar(Empresa), 1)

    def test_empresa_sem_cnpj_nao_recebe_identificador_inventado(self):
        empresa, _ = self.repo.obter_ou_criar_empresa("Fundo Sem CNPJ")
        self.assertIsNone(empresa.cnpj)
        oficial, criada = self.repo.obter_ou_criar_empresa(
            "Fundo Sem CNPJ", cnpj=CNPJ_C
        )
        self.assertFalse(criada)
        self.assertEqual(oficial.id, empresa.id)
        self.assertEqual(oficial.cnpj, CNPJ_C)


class TestConcorrenciaPostgres(PostgresCatalogoTestCase):
    def test_dois_vinculos_concorrentes_para_o_mesmo_ticker(self):
        a = self._empresa("Empresa A", CNPJ_A)
        b = self._empresa("Empresa B", CNPJ_B)
        with self.Session() as sessao:
            sessao.add(
                Ativo(ticker="PETR4", cnpj="PENDENTE-PETR4", tipo="ACAO")
            )
            sessao.commit()

        barreira = threading.Barrier(2)
        resultados = []
        trava = threading.Lock()

        def trabalhar(empresa_id):
            barreira.wait(timeout=10)
            try:
                self.repo.vincular_ativo(empresa_id, "PETR4", fonte="teste")
                resultado = "ok"
            except ConflitoVinculoAtivo:
                resultado = "conflito"
            except Exception as erro:  # pragma: no cover - diagnostico
                resultado = f"erro:{type(erro).__name__}"
            with trava:
                resultados.append(resultado)

        threads = [
            threading.Thread(target=trabalhar, args=(a.id,)),
            threading.Thread(target=trabalhar, args=(b.id,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertEqual(sorted(resultados), ["conflito", "ok"])
        self.assertEqual(self._contar(EmpresaAtivo), 1)
        dono = self.repo.obter_empresa_por_ticker("PETR4")
        self.assertIn(dono.id, (a.id, b.id))

    def test_aprovacao_concorrente_aplica_uma_unica_vez(self):
        sugestao_id, criada = self.repo.registrar_sugestao(
            "empresa",
            "nova-empresa",
            dados={
                "nome": "NOVA EMPRESA S.A.",
                "cnpj": CNPJ_C,
                "tickers": ["NOVA3"],
                "setor": "Petroleo e Gas",
                "atividades": ["Refino de petroleo"],
            },
            fonte="https://dados.cvm.gov.br/fca",
            evidencia="Fonte oficial.",
        )
        self.assertTrue(criada)

        barreira = threading.Barrier(2)
        resultados = []
        trava = threading.Lock()

        def aprovar(usuario):
            barreira.wait(timeout=10)
            try:
                resultado = self.repo.aprovar_sugestao(
                    sugestao_id, decidido_por=usuario
                )
            except Exception as erro:  # pragma: no cover - diagnostico
                resultado = f"erro:{type(erro).__name__}"
            with trava:
                resultados.append(resultado)

        threads = [
            threading.Thread(target=aprovar, args=("admin:1",)),
            threading.Thread(target=aprovar, args=("admin:2",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertTrue(all(r == sugestao_id for r in resultados), resultados)
        self.assertEqual(self._contar(Empresa), 1)
        self.assertEqual(self._contar(EmpresaAtivo), 1)
        with self.Session() as sessao:
            sugestao = sessao.query(SugestaoCatalogo).filter_by(
                id=sugestao_id
            ).one()
            self.assertEqual(sugestao.status, "aplicada")
            self.assertIsNotNone(sugestao.decidido_em)


if __name__ == "__main__":
    unittest.main()
