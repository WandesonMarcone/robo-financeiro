"""Dependências da camada HTTP/API (Fase 5, Etapa 10 / Fase 9, Etapa 9.2).

Centraliza a abertura de sessão de banco e a interpretação de argumentos de
consulta (filtros/limites/paginação). ``obter_sessao`` é o ponto de injeção usado pelos
testes com SQLite em memória: as rotas sempre chamam ``dependencias.obter_sessao``
em runtime, permitindo substituir a fábrica sem reload de módulos.
"""
from services.db import SessionDB

# Limites seguros de resposta. Paginação usa o mesmo teto.
LIMITE_PADRAO = 100
LIMITE_MAXIMO = 500
PAGINA_PADRAO = 1


def obter_sessao():
    """Abre uma nova sessão de banco usando a fábrica padrão do projeto."""
    return SessionDB()


def _inteiro_positivo(bruto, padrao):
    """Interpreta um inteiro positivo; devolve ``padrao`` se inválido ou <= 0."""
    try:
        valor = int(bruto)
    except (TypeError, ValueError):
        return padrao
    if valor <= 0:
        return padrao
    return valor


def obter_limite():
    """Interpreta ``?limite=N`` de forma tolerante, com teto máximo seguro."""
    from flask import request

    valor = _inteiro_positivo(request.args.get("limite", LIMITE_PADRAO), LIMITE_PADRAO)
    return min(valor, LIMITE_MAXIMO)


def obter_paginacao():
    """Lê ``page``/``page_size`` (ou ``limite``) com teto seguro.

    ``page`` é 1-indexado. ``page_size`` tem precedência sobre ``limite`` quando
    ambos aparecem. Devolve ``(page, page_size, offset)``.
    """
    from flask import request

    page = _inteiro_positivo(request.args.get("page", PAGINA_PADRAO), PAGINA_PADRAO)
    bruto_tamanho = request.args.get("page_size")
    if bruto_tamanho is None or str(bruto_tamanho).strip() == "":
        page_size = obter_limite()
    else:
        page_size = min(
            _inteiro_positivo(bruto_tamanho, LIMITE_PADRAO),
            LIMITE_MAXIMO,
        )
    offset = (page - 1) * page_size
    return page, page_size, offset


def meta_paginacao(total, page, page_size, retornados=None):
    """Monta o bloco de paginação do envelope ``meta`` sem alterar ``data``."""
    total = int(total or 0)
    has_next = (page * page_size) < total
    meta = {
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": has_next,
        "next_page": page + 1 if has_next else None,
    }
    if retornados is not None:
        meta["retornados"] = int(retornados)
    return meta


def inteiro_do_argumento(nome):
    """Interpreta um argumento inteiro opcional; levanta ValueError se inválido."""
    from flask import request

    bruto = request.args.get(nome)
    if bruto is None or str(bruto).strip() == "":
        return None
    try:
        return int(bruto)
    except (TypeError, ValueError):
        raise ValueError(f"O parâmetro '{nome}' deve ser um inteiro válido.") from None
