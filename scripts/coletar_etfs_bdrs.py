"""Coleta e notifica uma classe cotada por execução do Actions."""
import argparse
import os

from services.coletor_etfs_bdrs import TIPOS_INSTRUMENTO_MERCADO, coletar_instrumentos_ativos
from services.notificacoes_instrumentos import notificar_atualizacoes_diarias, notificar_resumo_admin

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tipo", choices=sorted(TIPOS_INSTRUMENTO_MERCADO), default=None)
    parser.add_argument("--limite", type=int, default=30)
    parser.add_argument("--sem-notificacoes", action="store_true")
    parser.add_argument("--arquivo-falhas-parciais",
                        help="Arquivo temporário do workflow para registrar classe com coleta parcial.")
    args = parser.parse_args()
    resultado = coletar_instrumentos_ativos(args.limite, tipo=args.tipo)
    if not args.sem_notificacoes:
        resultado["notificacoes"] = notificar_atualizacoes_diarias(
            resultado.get("ativos"), tipo=args.tipo
        )
        resultado["resumo_admin_enviado"] = notificar_resumo_admin(resultado, args.tipo)
    print(resultado)
    if resultado.get("falhas") and resultado.get("ativos") and args.arquivo_falhas_parciais:
        with open(args.arquivo_falhas_parciais, "a", encoding="utf-8") as arquivo:
            arquivo.write(f"{args.tipo or 'TODOS'}\n")
    # Uma fonte complementar pode falhar para um ticker isolado. Se ao menos
    # um ativo foi atualizado, a rodada é parcial e não deve derrubar todo o
    # workflow unificado nem gerar um falso alarme no Telegram.
    if resultado.get("falhas") and not resultado.get("ativos"):
        raise SystemExit("coleta_instrumentos_incompleta")
