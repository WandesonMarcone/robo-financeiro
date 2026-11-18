"""Executa lotes seguros e auditáveis da fila documental."""

from atualizador_documentos import rotina_processar_acoes, rotina_processar_pendentes
from services.historico_operacional import concluir_evento, iniciar_evento, registrar_resultado

LIMITE_POR_CLASSE = 20


def _detalhes(resultado):
    return {
        "fila": int(getattr(resultado, "fila", 0) or 0),
        "lote": int(getattr(resultado, "lote", 0) or 0),
        "processados": int(getattr(resultado, "processados", 0) or 0),
        "salvo_drive": int(getattr(resultado, "salvo_drive", 0) or 0),
        "revisao": int(getattr(resultado, "revisao", 0) or 0),
        "erros": int(getattr(resultado, "erros", 0) or 0),
        "notificados": int(getattr(resultado, "notificados", 0) or 0),
        "erro": getattr(resultado, "erro", None),
    }


def main():
    evento = iniciar_evento(
        "PROCESSAMENTO_DOCUMENTAL",
        origem="GITHUB_ACTIONS",
        mensagem="Processamento documental diário iniciado.",
    )
    try:
        fii = rotina_processar_pendentes(limite=LIMITE_POR_CLASSE)
        acoes = rotina_processar_acoes(limite=LIMITE_POR_CLASSE)
        detalhes = {"fii": _detalhes(fii), "acoes": _detalhes(acoes)}
        registrar_resultado(evento, detalhes)
        erro = detalhes["fii"]["erro"] or detalhes["acoes"]["erro"]
        mensagem = (
            "Processamento documental concluído: "
            f"FIIs={detalhes['fii']['processados']}, "
            f"ações={detalhes['acoes']['processados']}, "
            f"Drive={detalhes['fii']['salvo_drive'] + detalhes['acoes']['salvo_drive']}, "
            f"revisão={detalhes['fii']['revisao'] + detalhes['acoes']['revisao']}, "
            f"erros={detalhes['fii']['erros'] + detalhes['acoes']['erros']}."
        )
        concluir_evento(evento, sucesso=not bool(erro), mensagem=mensagem, erro=erro)
        print(mensagem)
        if erro:
            raise RuntimeError(str(erro))
    except Exception as exc:
        concluir_evento(
            evento,
            sucesso=False,
            mensagem="Processamento documental interrompido.",
            erro=type(exc).__name__,
        )
        raise


if __name__ == "__main__":
    main()
