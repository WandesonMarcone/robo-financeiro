"""Coerção numérica centralizada — Fase 7, Etapa 7.5.

Ponto único de conversão/normalização numérica do projeto. Substitui as formas
concorrentes de parsing apontadas pela auditoria 7.1 (``modules.utils.formatar``
e ``services.dashboard_menus.converter_numero``), que mascaram erro de coleta
retornando ``0.0``, por uma semântica explícita e compatível com o código do
Core (que já usa ``qualidade_dados.parsear_numero``).

Semântica preservada (auditoria 7.1, regra 5 da Etapa 7.5):

- valor VÁLIDO igual a zero -> ``(0.0, None)`` (zero legítimo é preservado);
- valor AUSENTE (None/vazio) -> ``(None, None)`` (dado ausente, não inválido);
- valor INVÁLIDO -> ``(None, "NAO_NUMERO")`` para não-numérico e
  ``(None, "NAO_FINITO")`` para NaN/Inf;
- ERRO de parsing/coleta -> NUNCA vira ``0.0``; retorna ``None`` e motivo.

Separadores: aceita o formato brasileiro (``"1.234,56"`` -> ``1234.56``) quando
há vírgula decimal e o formato internacional (``"1234.56"``). Prefere o ponto
como separador decimal sempre que ele for inequívoco.

Este módulo não importa ``qualidade_dados`` (nem ``modules``): é a base reutilizável
e offline sobre a qual a camada de validação e os consumidores seguros se apoiam.
"""
import math

NAO_NUMERO = "NAO_NUMERO"
NAO_FINITO = "NAO_FINITO"


def coerir_numero(valor) -> tuple[float | None, str | None]:
    """Converte para float. Retorna ``(numero, None)`` ou ``(None, motivo)``.

    ``motivo`` é ``None`` quando o valor é numérico válido (incluindo ``0.0``)
    ou quando está AUSENTE (``None``/string vazia/espacos). Para valor presente
    e não-numérico retorna ``NAO_NUMERO``; para NaN/Inf retorna ``NAO_FINITO``.
    """
    if valor is None:
        return None, None
    if isinstance(valor, bool):
        return None, NAO_NUMERO
    if isinstance(valor, (int, float)):
        numero = float(valor)
    elif isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return None, None
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        try:
            numero = float(texto)
        except ValueError:
            return None, NAO_NUMERO
    else:
        return None, NAO_NUMERO
    if not math.isfinite(numero):
        return None, NAO_FINITO
    return numero, None


def parsear_numero(valor) -> float | None:
    """Converte valor em ``float`` ou ``None`` (API canônica).

    Erro de coleta/parsing NUNCA vira zero: valor não-numérico, NaN ou Inf
    retornam ``None``, deixando a distinção ausente/inválido/zero para
    ``coerir_numero`` e para as regras de obrigatoriedade do chamador.
    """
    numero, _ = coerir_numero(valor)
    return numero
