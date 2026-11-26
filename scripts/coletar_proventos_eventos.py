"""Coleta proventos e eventos em lote curto e rotativo."""
import argparse
import os

from services.historico_operacional import concluir_evento, iniciar_evento, registrar_resultado
from services.proventos_eventos import coletar_proventos_eventos
from services.resultados_operacionais import FALHOU, classificar_resultado


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limite-por-classe", type=int, default=int(os.getenv("EVENTOS_LIMITE_POR_CLASSE", "20")))
    parser.add_argument("--janela-dias", type=int, default=int(os.getenv("EVENTOS_JANELA_DIAS", "75")))
    parser.add_argument("--pausa-segundos", type=float, default=1)
    parser.add_argument("--falhar-com-falhas", action="store_true")
    parser.add_argument("--arquivo-resultado")
    args = parser.parse_args()
    evento = iniciar_evento("COLETA_PROVENTOS_EVENTOS", origem="GITHUB_ACTIONS",
                            mensagem="Coleta de proventos e eventos iniciada.")
    try:
        resultado = coletar_proventos_eventos(
            limite_por_classe=args.limite_por_classe,
            janela_dias=args.janela_dias,
            pausa_segundos=args.pausa_segundos,
        )
        pendentes = 1 if (resultado.get("espelho_planilha") or {}).get("estado") == "PENDENTE" else 0
        oficiais = resultado.get("pagamentos_oficiais") or {}
        pendentes += oficiais.get("pendentes", 0) + oficiais.get("conflitos", 0)
        estado = classificar_resultado(processados=resultado.get("processados"),
                                       falhas=len(resultado.get("falhas") or []), pendentes=pendentes)
        resultado["status"] = estado
        registrar_resultado(evento, resultado)
        mensagem = (f"Proventos e eventos: {estado.lower()}; "
                    f"processados={resultado['processados']}, proventos={resultado['proventos']}, "
                    f"eventos={resultado['eventos']}, pagamentos B3 confirmados={oficiais.get('confirmados', 0)}, "
                    f"pendentes={oficiais.get('pendentes', 0)}, conflitos={oficiais.get('conflitos', 0)}, "
                    f"falhas={len(resultado['falhas'])}.")
        concluir_evento(evento, sucesso=estado != FALHOU, mensagem=mensagem,
                        erro="COLETA_SEM_SUCESSO" if estado == FALHOU else None, status=estado)
        if args.arquivo_resultado:
            with open(args.arquivo_resultado, "a", encoding="utf-8") as arquivo:
                arquivo.write(f"status={estado}\n")
        print(resultado)
        if estado == FALHOU or (args.falhar_com_falhas and resultado["falhas"]):
            raise SystemExit("coleta_proventos_eventos_incompleta")
    except Exception:
        concluir_evento(evento, sucesso=False, mensagem="Coleta de proventos e eventos interrompida.",
                        erro="EXCECAO_COLETA", status=FALHOU)
        raise
