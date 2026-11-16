"""Contingência auditável da descoberta de documentos FNET, sem processar a fila."""
from pipeline_dados.coletor_fnet import ColetorFnet
from services.historico_operacional import iniciar_evento, registrar_resultado, concluir_evento


def executar(coletor=None, dias=60):
    evento = iniciar_evento(
        "VARREDURA_FNET", origem="GITHUB_ACTIONS",
        mensagem="Contingência diária da descoberta FNET iniciada.",
    )
    concluido = False
    try:
        resultado = (coletor or ColetorFnet()).coletar(dias=dias)
        detalhes = resultado.detalhes_painel()
        registrar_resultado(evento, detalhes)
        mensagem = resultado.mensagem_telegram()
        falhou = resultado.status == "erro" or resultado.falhas_persistencia > 0
        concluir_evento(evento, sucesso=not falhou, mensagem=mensagem,
                        erro=resultado.erro or ("Falha parcial de persistência" if falhou else None))
        concluido = True
        print(mensagem)
        if falhou:
            raise RuntimeError(resultado.erro or "FNET_FALHA_PERSISTENCIA")
        return detalhes
    except Exception as erro:
        # Se a coleta lançou exceção antes de retornar, a operação não pode
        # permanecer EM_ANDAMENTO no histórico administrativo.
        if not concluido:
            concluir_evento(evento, sucesso=False, erro=type(erro).__name__,
                            mensagem="Falha na contingência FNET.")
        raise


if __name__ == "__main__":
    executar()
