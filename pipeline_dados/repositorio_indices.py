"""Persistência idempotente do OHLC diário de índices de mercado.

A tabela é criada somente pela migração 0012. Este módulo não cria schema.
Cada chamada atualiza a mesma linha de índice/pregão; não há histórico de
amostras de 30 minutos para apagar.
"""

from sqlalchemy import text

from pipeline_dados.conexao import obter_session_factory

SQL_UPSERT = text(
    """
    INSERT INTO indices_mercado_diario (
        indice, data_pregao, abertura, maxima, minima, fechamento,
        fechamento_anterior, variacao_percentual, fonte, atualizado_em
    ) VALUES (
        :indice, :data_pregao, :abertura, :maxima, :minima, :fechamento,
        :fechamento_anterior, :variacao_percentual, :fonte, NOW()
    )
    ON CONFLICT (indice, data_pregao) DO UPDATE SET
        abertura = COALESCE(EXCLUDED.abertura, indices_mercado_diario.abertura),
        maxima = COALESCE(EXCLUDED.maxima, indices_mercado_diario.maxima),
        minima = COALESCE(EXCLUDED.minima, indices_mercado_diario.minima),
        fechamento = COALESCE(EXCLUDED.fechamento, indices_mercado_diario.fechamento),
        fechamento_anterior = COALESCE(
            EXCLUDED.fechamento_anterior,
            indices_mercado_diario.fechamento_anterior
        ),
        variacao_percentual = COALESCE(
            EXCLUDED.variacao_percentual,
            indices_mercado_diario.variacao_percentual
        ),
        fonte = EXCLUDED.fonte,
        atualizado_em = NOW()
    """
)


def persistir_indices_diarios(registros, data_pregao, session_factory=None):
    """Grava registros OHLC sem duplicar o mesmo índice/pregão."""
    registros = [r for r in (registros or []) if r and r.get("indice")]
    if not registros:
        return {"gravados": 0, "data_pregao": data_pregao}

    fabrica = session_factory or obter_session_factory()
    sessao = fabrica()
    try:
        for registro in registros:
            sessao.execute(
                SQL_UPSERT,
                {
                    "indice": registro["indice"],
                    "data_pregao": data_pregao,
                    "abertura": registro.get("abertura"),
                    "maxima": registro.get("maxima"),
                    "minima": registro.get("minima"),
                    "fechamento": registro.get("fechamento"),
                    "fechamento_anterior": registro.get("fechamento_anterior"),
                    "variacao_percentual": registro.get("variacao_percentual"),
                    "fonte": registro.get("fonte") or "desconhecida",
                },
            )
        sessao.commit()
        return {"gravados": len(registros), "data_pregao": data_pregao}
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao.close()
