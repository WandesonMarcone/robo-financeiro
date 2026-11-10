"""Coleta e notifica uma classe internacional por execução do Actions."""
import argparse

from services.coletor_etfs_bdrs import coletar_instrumentos_ativos
from services.notificacoes_instrumentos import notificar_atualizacoes_diarias, notificar_resumo_admin

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tipo", choices=["ETF", "BDR"], default=None)
    parser.add_argument("--limite", type=int, default=30)
    parser.add_argument("--sem-notificacoes", action="store_true")
    args = parser.parse_args()
    resultado = coletar_instrumentos_ativos(args.limite, tipo=args.tipo)
    if not args.sem_notificacoes:
        resultado["notificacoes"] = notificar_atualizacoes_diarias(
            resultado.get("ativos"), tipo=args.tipo
        )
        resultado["resumo_admin_enviado"] = notificar_resumo_admin(resultado, args.tipo)
    print(resultado)
