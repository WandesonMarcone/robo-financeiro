"""Coleta oficial do Tesouro com resultado persistente na Central de Controle."""
from services.coletor_tesouro_direto import coletar_tesouro_direto
from services.historico_operacional import iniciar_evento, registrar_resultado, concluir_evento


def executar(coletor=coletar_tesouro_direto):
    evento = iniciar_evento(
        "COLETA_TESOURO", origem="GITHUB_ACTIONS",
        mensagem="Coleta oficial do Tesouro iniciada.",
    )
    try:
        resultado = coletor()
        if not resultado or int(resultado.get("gravadas", 0)) <= 0:
            raise ValueError("TESOURO_SEM_TITULOS_GRAVADOS")
        registrar_resultado(evento, resultado)
        concluir_evento(evento, sucesso=True,
                        mensagem=f"Tesouro: {resultado['gravadas']} título(s), referência {resultado.get('referencia')}.")
        print(resultado)
        return resultado
    except Exception as erro:
        concluir_evento(evento, sucesso=False, erro=type(erro).__name__,
                        mensagem=f"Coleta Tesouro falhou: {type(erro).__name__}.")
        raise


if __name__ == "__main__":
    executar()
