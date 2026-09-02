"""Envelope JSON padronizado das respostas da API (Fase 5, Etapa 10).

Toda resposta de sucesso segue ``{"status": "success", "data": ..., "meta": ...}``
e todo erro segue ``{"status": "error", "data": None, "meta": {"error": ...}}``.
Nenhum objeto ORM é retornado diretamente ao cliente e nenhum stack trace ou
detalhe interno de SQL é exposto na resposta de erro.
"""


def resposta_ok(data, meta=None):
    """Envelope de sucesso com ``status``, ``data`` e ``meta``."""
    return {"status": "success", "data": data, "meta": meta or {}}, 200


def resposta_erro(mensagem, codigo):
    """Envelope de erro com mensagem genérica e código HTTP."""
    return {"status": "error", "data": None, "meta": {"error": mensagem}}, codigo
