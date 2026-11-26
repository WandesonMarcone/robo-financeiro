"""Executa lotes seguros, auditáveis e classificáveis da fila documental."""

from datetime import date, datetime, timedelta
import argparse

from sqlalchemy import or_

from atualizador_documentos import (
    SessionDB,
    reclassificar_apresentacoes_resultados_acoes,
    rotina_processar_acoes,
    rotina_processar_pendentes,
)
from pipeline_dados.banco_dados import DocumentosQualitativos
from services.historico_operacional import concluir_evento, iniciar_evento, registrar_resultado
from services.resultados_operacionais import FALHOU, classificar_resultado
from services.taxonomia_fiis_automatica import corrigir_taxonomia_fiis

LIMITE_POR_CLASSE = 20


def arquivar_fora_da_janela(referencia=None, session=None):
    """Retira da fila ativa o histórico anterior ao escopo atual do projeto."""
    referencia = referencia or date.today()
    if isinstance(referencia, datetime):
        referencia = referencia.date()
    propria = session is None
    session = session or SessionDB()
    try:
        from services.configuracoes_sistema import obter_janela_documentos_dias
        dias = obter_janela_documentos_dias(session)
        inicio_fiis = referencia - timedelta(days=dias)
        inicio_acoes = referencia - timedelta(days=dias)
        fiis = session.query(DocumentosQualitativos).filter(
            DocumentosQualitativos.status_processamento == "PENDENTE",
            or_(
                DocumentosQualitativos.data_publicacao.is_(None),
                DocumentosQualitativos.data_publicacao < inicio_fiis,
                DocumentosQualitativos.data_publicacao > referencia,
            ),
        ).update(
            {DocumentosQualitativos.status_processamento: "FORA_JANELA"},
            synchronize_session=False,
        )
        acoes = session.query(DocumentosQualitativos).filter(
            DocumentosQualitativos.status_processamento == "PENDENTE_ACAO",
            or_(
                DocumentosQualitativos.data_publicacao.is_(None),
                DocumentosQualitativos.data_publicacao < inicio_acoes,
                DocumentosQualitativos.data_publicacao > referencia,
            ),
        ).update(
            {DocumentosQualitativos.status_processamento: "FORA_JANELA"},
            synchronize_session=False,
        )
        session.commit()
        return {
            "fiis": int(fiis or 0),
            "acoes": int(acoes or 0),
            "inicio_fiis": inicio_fiis.isoformat(),
            "inicio_acoes": inicio_acoes.isoformat(),
            "fim": referencia.isoformat(),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        if propria:
            session.close()


def _detalhes(resultado):
    return {
        "fila": int(getattr(resultado, "fila", 0) or 0),
        "lote": int(getattr(resultado, "lote", 0) or 0),
        "processados": int(getattr(resultado, "processados", 0) or 0),
        "salvo_drive": int(getattr(resultado, "salvo_drive", 0) or 0),
        "revisao": int(getattr(resultado, "revisao", 0) or 0),
        "erros": int(getattr(resultado, "erros", 0) or 0),
        "sem_fonte": int(getattr(resultado, "sem_fonte", 0) or 0),
        "adiados": int(getattr(resultado, "adiados", 0) or 0),
        "notificados": int(getattr(resultado, "notificados", 0) or 0),
        "itens": list(getattr(resultado, "itens", []) or []),
        "erro": getattr(resultado, "erro", None),
    }


def main(arquivo_resultado=None):
    evento = iniciar_evento(
        "PROCESSAMENTO_DOCUMENTAL",
        origem="GITHUB_ACTIONS",
        mensagem="Processamento documental diário iniciado.",
    )
    try:
        fora_janela = arquivar_fora_da_janela()
        resultados_reclassificados = reclassificar_apresentacoes_resultados_acoes()
        fii = rotina_processar_pendentes(limite=LIMITE_POR_CLASSE)
        acoes = rotina_processar_acoes(limite=LIMITE_POR_CLASSE)
        detalhes = {
            "fora_janela": fora_janela,
            "resultados_reclassificados": resultados_reclassificados,
            "fii": _detalhes(fii),
            "acoes": _detalhes(acoes),
        }
        erro = detalhes["fii"]["erro"] or detalhes["acoes"]["erro"]
        total_erros = detalhes["fii"]["erros"] + detalhes["acoes"]["erros"]
        pendentes = detalhes["fii"]["sem_fonte"] + detalhes["acoes"]["adiados"]

        # Só usa PDFs que acabaram de ser confirmados no Drive; nunca infere
        # setor de FII a partir de preço, ticker ou fonte não documental.
        taxonomia = corrigir_taxonomia_fiis()
        detalhes["taxonomia"] = taxonomia
        from atualizador_documentos import enviar_relatorio_processamento_documental
        detalhes["telegram_resumo_enviado"] = enviar_relatorio_processamento_documental(detalhes)
        estado = classificar_resultado(
            processados=detalhes["fii"]["processados"] + detalhes["acoes"]["processados"],
            falhas=total_erros + (1 if erro else 0),
            pendentes=pendentes,
        )
        detalhes["status"] = estado
        registrar_resultado(evento, detalhes)
        mensagem = (
            (f"Processamento documental {estado.lower()}: ")
            + f"FIIs={detalhes['fii']['processados']}, "
            f"ações={detalhes['acoes']['processados']}, "
            f"Drive={detalhes['fii']['salvo_drive'] + detalhes['acoes']['salvo_drive']}, "
            f"revisão={detalhes['fii']['revisao'] + detalhes['acoes']['revisao']}, "
            f"setores corrigidos={taxonomia.get('quantidade_corrigida', 0)}, "
            f"resultados reclassificados={resultados_reclassificados}, "
            f"histórico fora da janela={fora_janela['fiis'] + fora_janela['acoes']}, "
            f"aguardando fonte FNET={detalhes['fii']['sem_fonte']}, "
            f"adiados pela CVM={detalhes['acoes']['adiados']}, "
            f"erros={detalhes['fii']['erros'] + detalhes['acoes']['erros']}. "
            f"Telegram={'enviado' if detalhes['telegram_resumo_enviado'] else 'não enviado'}."
        )
        falha = erro or (f"{total_erros} erro(s) na fila documental." if total_erros else None)
        concluir_evento(evento, sucesso=estado != FALHOU, mensagem=mensagem,
                        erro=falha, status=estado)
        if arquivo_resultado:
            with open(arquivo_resultado, "a", encoding="utf-8") as arquivo:
                arquivo.write(f"status={estado}\n")
        print(mensagem)
    except Exception as exc:
        concluir_evento(
            evento,
            sucesso=False,
            mensagem="Processamento documental interrompido.",
            erro=type(exc).__name__,
        )
        raise
    if estado == FALHOU:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--arquivo-resultado")
    main(arquivo_resultado=parser.parse_args().arquivo_resultado)
