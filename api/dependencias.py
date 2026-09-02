"""Dependências da camada HTTP/API (Fase 5, Etapa 10).

Centraliza a abertura de sessão de banco e a interpretação de argumentos de
consulta (filtros/limites). ``obter_sessao`` é o ponto de injeção usado pelos
testes com SQLite em memória: as rotas sempre chamam ``dependencias.obter_sessao``
em runtime, permitindo substituir a fábrica sem reload de módulos.
"""
from services.db import SessionDB

# Limites seguros de resposta (sem paginação de produção nesta etapa).
LIMITE_PADRAO = 100
LIMITE_MAXIMO = 500


def obter_sessao():
    """Abre uma nova sessão de banco usando a fábrica padrão do projeto."""
    return SessionDB()


def obter_limite():
    """Interpreta ``?limite=N`` de forma tolerante, com teto máximo seguro."""
    from flask import request

    try:
        valor = int(request.args.get("limite", LIMITE_PADRAO))
    except (TypeError, ValueError):
        return LIMITE_PADRAO
    if valor <= 0:
        return LIMITE_PADRAO
    return min(valor, LIMITE_MAXIMO)


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
