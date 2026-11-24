"""Envia sinais de instrumentos 24x7 sem executar os motores da B3."""
from modules.utils import disparar_alertas
from services.oportunidades_unificadas import montar_digest_oportunidades_instrumentos


def executar():
    pacote = montar_digest_oportunidades_instrumentos()
    texto = str(pacote.get("texto") or "").strip()
    if not texto:
        print("Mercado 24x7 sem sinal relevante.")
        return False
    resultado = disparar_alertas(texto, tickers=pacote.get("tickers") or [], tipo="instrumento")
    print({"enviado": bool(resultado), "tickers": pacote.get("tickers") or []})
    return bool(resultado)


if __name__ == "__main__":
    executar()
