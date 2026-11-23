"""Descobre documentos IPE/CVM dentro da janela móvel de 30 dias."""

from pipeline_dados.coletor_docs_acoes import RelatoriosAcoesCVM
from services.historico_operacional import concluir_evento, iniciar_evento, registrar_resultado


def executar(coletor=None):
    evento = iniciar_evento(
        "VARREDURA_DOCUMENTOS_ACOES",
        origem="GITHUB_ACTIONS",
        mensagem="Descoberta trimestral de documentos de ações iniciada.",
    )
    concluido = False
    try:
        resultado = (coletor or RelatoriosAcoesCVM()).vasculhar_documentos()
        detalhes = resultado.detalhes_painel()
        registrar_resultado(evento, detalhes)
        mensagem = resultado.mensagem_telegram()
        falhou = resultado.status in {
            "erro", "arquivo_indisponivel", "arquivo_invalido"
        } or resultado.falhas_persistencia > 0
        concluir_evento(
            evento,
            sucesso=not falhou,
            mensagem=mensagem,
            erro=resultado.erro or (
                "Falha parcial de persistência" if falhou else None
            ),
        )
        concluido = True
        print(mensagem)
        if falhou:
            raise RuntimeError(resultado.erro or "CVM_IPE_FALHA_DESCOBERTA")
        return detalhes
    except Exception as erro:
        if not concluido:
            concluir_evento(
                evento,
                sucesso=False,
                erro=type(erro).__name__,
                mensagem="Falha na descoberta trimestral de documentos de ações.",
            )
        raise


if __name__ == "__main__":
    executar()
