"""Filtro de exibicao de alertas persistidos.

Nao grava nem apaga fatos. Apenas esconde eventos que sao ruido conhecido:

* Dividend Yield fora da faixa (0, 0.35) quando o valor e percentual (ex.: 11.54)
  e, na escala fracao, estaria dentro da faixa;
* variacao ~-99% / ~+9900% causada so pela troca de escala (11.54 vs 0.1158);
* repeticoes do mesmo (ativo, indicador, regra) no mesmo dia civil.
"""

from datetime import datetime

FAIXA_DY = (0.0, 0.35)
VARIACAO_ESCALA_MIN = 90.0


def _numero(valor):
    if valor is None:
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    if numero != numero:  # NaN
        return None
    return numero


def normalizar_dy(valor):
    """Converte percentual (11.54) para fracao (0.1154). Fracao permanece."""
    numero = _numero(valor)
    if numero is None:
        return None
    if abs(numero) > 1:
        return numero / 100.0
    return numero


def _indicador_dy(evento):
    indicador = str(getattr(evento, "indicador", "") or "").strip().lower()
    return indicador in {"dy", "dividend_yield", "dividend yield"}


def _data_civil(evento):
    data = getattr(evento, "data_referencia", None)
    if data is not None:
        if hasattr(data, "date"):
            return data.date()
        return data
    momento = getattr(evento, "data_evento", None)
    if momento is None:
        return None
    if isinstance(momento, datetime):
        return momento.date()
    if hasattr(momento, "date"):
        return momento.date()
    return momento


def _eh_ruido_escala_dy(evento):
    if not _indicador_dy(evento):
        return False
    atual = _numero(getattr(evento, "valor_atual", None))
    anterior = _numero(getattr(evento, "valor_anterior", None))
    regra = str(getattr(evento, "regra", "") or "").upper()
    variacao = _numero(getattr(evento, "variacao_percentual", None))

    if atual is not None and anterior is not None:
        um_percentual = (abs(atual) > 1) != (abs(anterior) > 1)
        if um_percentual:
            return True
        if variacao is not None and abs(variacao) >= VARIACAO_ESCALA_MIN:
            n_atual = normalizar_dy(atual)
            n_ant = normalizar_dy(anterior)
            if n_atual is not None and n_ant is not None and n_ant != 0:
                razao = abs(n_atual / n_ant - 1)
                if razao < 0.15:
                    return True

    if "FORA_FAIXA" in regra:
        for bruto in (atual, anterior):
            if bruto is None:
                continue
            if abs(bruto) > FAIXA_DY[1]:
                normalizado = normalizar_dy(bruto)
                if (
                    normalizado is not None
                    and FAIXA_DY[0] < abs(normalizado) <= FAIXA_DY[1]
                ):
                    return True
    return False


def evento_relevante_para_exibicao(evento):
    """False para ruido de escala de DY; True para o restante."""
    return not _eh_ruido_escala_dy(evento)


def filtrar_eventos_exibicao(eventos):
    """Remove ruido de escala e colapsa repeticoes do mesmo dia."""
    vistos = set()
    saida = []
    for evento in eventos or []:
        if not evento_relevante_para_exibicao(evento):
            continue
        chave = (
            getattr(evento, "ativo_id", None),
            str(getattr(evento, "indicador", "") or "").strip().lower(),
            str(getattr(evento, "regra", "") or "").strip().upper(),
            _data_civil(evento),
        )
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(evento)
    return saida
