"""Leitura e gravação das configurações operacionais persistidas no Neon."""

from datetime import datetime

from pipeline_dados.banco_dados import ConfiguracaoSistema

CHAVE_JANELA_DOCUMENTOS = "janela_documentos_dias"
JANELA_DOCUMENTOS_PADRAO = 30
JANELA_DOCUMENTOS_MINIMA = 1
JANELA_DOCUMENTOS_MAXIMA = 365


def normalizar_janela_documentos_dias(valor):
    try:
        dias = int(valor)
    except (TypeError, ValueError) as exc:
        raise ValueError("A janela documental deve ser um número inteiro.") from exc
    if not JANELA_DOCUMENTOS_MINIMA <= dias <= JANELA_DOCUMENTOS_MAXIMA:
        raise ValueError(
            f"A janela documental deve ficar entre {JANELA_DOCUMENTOS_MINIMA} e "
            f"{JANELA_DOCUMENTOS_MAXIMA} dias."
        )
    return dias


def obter_janela_documentos_dias(session=None):
    propria = session is None
    if propria:
        from atualizador_documentos import SessionDB

        session = SessionDB()
    try:
        item = session.get(ConfiguracaoSistema, CHAVE_JANELA_DOCUMENTOS)
        if item is None:
            return JANELA_DOCUMENTOS_PADRAO
        return normalizar_janela_documentos_dias(item.valor)
    except Exception:
        # Uma falha de configuração não pode ampliar silenciosamente a coleta.
        return JANELA_DOCUMENTOS_PADRAO
    finally:
        if propria:
            session.close()


def definir_janela_documentos_dias(valor, session=None):
    dias = normalizar_janela_documentos_dias(valor)
    propria = session is None
    if propria:
        from atualizador_documentos import SessionDB

        session = SessionDB()
    try:
        item = session.get(ConfiguracaoSistema, CHAVE_JANELA_DOCUMENTOS)
        if item is None:
            item = ConfiguracaoSistema(
                chave=CHAVE_JANELA_DOCUMENTOS,
                valor=str(dias),
                descricao="Janela máxima de coleta e processamento de documentos.",
            )
            session.add(item)
        else:
            item.valor = str(dias)
            item.atualizado_em = datetime.now()
        session.commit()
        return {
            "days": dias,
            "updated_at": item.atualizado_em.isoformat() if item.atualizado_em else None,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        if propria:
            session.close()
