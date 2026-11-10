"""Favoritos individuais de ETFs e BDRs.

Esta camada não mistura instrumentos internacionais com ``ativos`` nem com a
tabela histórica ``ativos_acompanhados``. Todo vínculo é validado contra o
cadastro próprio de ETFs/BDRs e só usuários aprovados/ativos são retornados
para entrega de notificações.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text


class InstrumentoNaoCadastradoError(Exception):
    """O ticker não existe no cadastro internacional ativo."""


@dataclass(frozen=True)
class FavoritoInternacionalDTO:
    id: int
    usuario_id: int
    instrumento_id: int
    ticker: str
    tipo: str
    criado_em: object


class RepositorioFavoritosInternacionais:
    TIPOS = {"ETF", "BDR"}

    def __init__(self, session_factory=None):
        self._session_factory = session_factory

    def _sessao(self):
        if self._session_factory:
            return self._session_factory()
        from atualizador_documentos import SessionDB
        return SessionDB()

    @staticmethod
    def _ticker(ticker):
        return str(ticker or "").strip().upper()

    @classmethod
    def _tipo(cls, tipo):
        valor = str(tipo or "").strip().upper()
        return valor if valor in cls.TIPOS else None

    def resolver_instrumento(self, ticker, tipo=None):
        ticker = self._ticker(ticker)
        tipo = self._tipo(tipo) if tipo else None
        if not ticker:
            return None
        sessao = self._sessao()
        try:
            row = sessao.execute(text("""
                SELECT id,ticker,tipo FROM instrumentos_internacionais
                WHERE ticker=:ticker AND ativo=TRUE AND (:tipo IS NULL OR tipo=:tipo)
            """), {"ticker": ticker, "tipo": tipo}).mappings().first()
            return dict(row) if row else None
        finally:
            sessao.close()

    def listar(self, usuario_id, tipo=None):
        tipo = self._tipo(tipo) if tipo else None
        if tipo is None and tipo not in (None, ""):
            return []
        sessao = self._sessao()
        try:
            rows = sessao.execute(text("""
                SELECT f.id,f.usuario_id,f.instrumento_id,i.ticker,i.tipo,f.criado_em
                FROM favoritos_instrumentos_internacionais f
                JOIN instrumentos_internacionais i ON i.id=f.instrumento_id
                WHERE f.usuario_id=:usuario_id AND i.ativo=TRUE
                  AND (:tipo IS NULL OR i.tipo=:tipo)
                ORDER BY i.ticker
            """), {"usuario_id": int(usuario_id), "tipo": tipo}).mappings().all()
            return [FavoritoInternacionalDTO(**dict(row)) for row in rows]
        finally:
            sessao.close()

    def listar_disponiveis(self, usuario_id, tipo):
        tipo = self._tipo(tipo)
        if not tipo:
            return []
        sessao = self._sessao()
        try:
            return [row[0] for row in sessao.execute(text("""
                SELECT i.ticker FROM instrumentos_internacionais i
                WHERE i.ativo=TRUE AND i.tipo=:tipo AND NOT EXISTS (
                    SELECT 1 FROM favoritos_instrumentos_internacionais f
                    WHERE f.instrumento_id=i.id AND f.usuario_id=:usuario_id
                ) ORDER BY i.ticker
            """), {"usuario_id": int(usuario_id), "tipo": tipo}).all()]
        finally:
            sessao.close()

    def adicionar(self, usuario_id, ticker, tipo=None):
        instrumento = self.resolver_instrumento(ticker, tipo)
        if not instrumento:
            raise InstrumentoNaoCadastradoError(self._ticker(ticker))
        sessao = self._sessao()
        try:
            row = sessao.execute(text("""
                INSERT INTO favoritos_instrumentos_internacionais (usuario_id,instrumento_id)
                VALUES (:usuario_id,:instrumento_id)
                ON CONFLICT (usuario_id,instrumento_id) DO NOTHING
                RETURNING id,criado_em
            """), {"usuario_id": int(usuario_id), "instrumento_id": instrumento["id"]}).mappings().first()
            sessao.commit()
            return FavoritoInternacionalDTO(
                id=row["id"] if row else 0, usuario_id=int(usuario_id),
                instrumento_id=instrumento["id"], ticker=instrumento["ticker"],
                tipo=instrumento["tipo"], criado_em=row["criado_em"] if row else None,
            ), bool(row)
        except Exception:
            sessao.rollback()
            raise
        finally:
            sessao.close()

    def remover(self, usuario_id, ticker, tipo=None):
        instrumento = self.resolver_instrumento(ticker, tipo)
        if not instrumento:
            return False
        sessao = self._sessao()
        try:
            result = sessao.execute(text("""
                DELETE FROM favoritos_instrumentos_internacionais
                WHERE usuario_id=:usuario_id AND instrumento_id=:instrumento_id
            """), {"usuario_id": int(usuario_id), "instrumento_id": instrumento["id"]})
            sessao.commit()
            return result.rowcount > 0
        except Exception:
            sessao.rollback()
            raise
        finally:
            sessao.close()

    def usuarios_que_acompanham(self, ticker, tipo=None):
        instrumento = self.resolver_instrumento(ticker, tipo)
        if not instrumento:
            return []
        sessao = self._sessao()
        try:
            return [dict(row) for row in sessao.execute(text("""
                SELECT u.id,u.telegram_user_id,u.telegram_chat_id,u.nome,
                       COALESCE(p.alertas_ativos,TRUE) AS alertas_ativos,
                       p.variacao_minima_percentual
                FROM favoritos_instrumentos_internacionais f
                JOIN usuarios u ON u.id=f.usuario_id
                LEFT JOIN preferencias_alertas_usuarios p ON p.usuario_id=u.id
                WHERE f.instrumento_id=:instrumento_id
                  AND u.ativo=TRUE AND LOWER(u.status_cadastro)='aprovado'
                  AND COALESCE(p.alertas_ativos,TRUE)=TRUE
                ORDER BY u.id
            """), {"instrumento_id": instrumento["id"]}).mappings().all()]
        finally:
            sessao.close()
