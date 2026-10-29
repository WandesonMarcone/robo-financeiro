"""Modelo do resumo atual de IA por ativo.

Existe no maximo um registro por ativo. Uma nova geracao substitui o resumo
anterior; nao ha historico operacional nessa tabela.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pipeline_dados.banco_dados import Base


class ResumoAtivo(Base):
    __tablename__ = "resumos_ativos"
    __table_args__ = (
        UniqueConstraint("ativo_id", name="uix_resumos_ativos_ativo"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ativo_id: Mapped[int] = mapped_column(
        ForeignKey("ativos.id"), nullable=False, index=True
    )
    resumo: Mapped[str] = mapped_column(Text, nullable=False)
    fontes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    modelo: Mapped[str] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="GERADO")
    gerado_em: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    erro: Mapped[str] = mapped_column(Text, nullable=True)
