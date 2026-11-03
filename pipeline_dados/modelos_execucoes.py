"""Modelo isolado do histórico operacional dos ciclos do GitHub.

A tabela é criada exclusivamente pela migração 0013. Este módulo não cria
schema automaticamente, para preservar a regra de segurança do projeto.
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func


BaseExecucoes = declarative_base()


class ExecucaoCiclica(BaseExecucoes):
    __tablename__ = "execucoes_ciclicas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(80), nullable=False, unique=True)
    status = Column(String(20), nullable=False)
    limite_total = Column(Integer, nullable=False)
    acoes_solicitadas = Column(Integer, nullable=True)
    fiis_solicitados = Column(Integer, nullable=True)
    acoes_gravadas = Column(Boolean, nullable=True)
    fiis_gravados = Column(Boolean, nullable=True)
    duracao_segundos = Column(Numeric(12, 3), nullable=True)
    url_execucao = Column(Text, nullable=True)
    resumo_erro = Column(String(300), nullable=True)
    concluido_em = Column(DateTime, nullable=False, server_default=func.now())
