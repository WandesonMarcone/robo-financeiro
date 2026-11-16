"""Coleta BCB com auditoria durável e erro visível em falhas parciais."""
from services.coletor_macro_bcb import coletar_bcb
from services.historico_operacional import iniciar_evento, registrar_resultado, concluir_evento


def executar(coletor=coletar_bcb):
    evento = iniciar_evento("COLETA_MACRO", origem="GITHUB_ACTIONS",
                            mensagem="Coleta de Selic, CDI, IPCA e PTAX iniciada.")
    concluido = False
    try:
        resultado = coletor()
        registrar_resultado(evento, resultado)
        falhas = resultado.get("falhas") or []
        ausentes = [str(f.get("serie") or "?") for f in falhas]
        gravadas = sum(int(s.get("gravadas") or 0) for s in (resultado.get("series") or {}).values())
        if not gravadas or ausentes:
            detalhe = "Séries com erro: " + ", ".join(ausentes) if ausentes else "Nenhuma observação coletada"
            concluir_evento(evento, sucesso=False, erro=detalhe, mensagem=detalhe)
            concluido = True
            raise RuntimeError(detalhe)
        mensagem = f"Macro: {gravadas} observação(ões) em {len(resultado['series'])} séries."
        concluir_evento(evento, sucesso=True, mensagem=mensagem)
        concluido = True
        print(resultado)
        return resultado
    except Exception as erro:
        if not concluido:
            concluir_evento(evento, sucesso=False, erro=type(erro).__name__,
                            mensagem="Falha na coleta macro oficial.")
        raise


if __name__ == "__main__":
    executar()
