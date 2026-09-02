"""Serializers explícitos da API (Fase 5, Etapa 10).

Convertem objetos ORM em dicionários JSON-friendly, campo a campo, evitando
``obj.__dict__`` e vazamento acidental de campos internos ou sensíveis:

- documentos: exclui ``texto_extraido``, ``resumo_ia``, ``log_erro`` e arquivos;
- usuário: exclui ``senha_hash``, sessões, API Keys, tokens e segredos;
- valores NUMERIC/Date/DateTime são normalizados para JSON (float/isoformat).
"""
from datetime import date, datetime
from decimal import Decimal


def _numero(valor):
    """Normaliza Decimal para float (JSON-friendly), preservando None."""
    if isinstance(valor, Decimal):
        return float(valor)
    return valor


def _data(valor):
    """Normaliza date/datetime para ISO 8601, preservando None."""
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return valor


def _texto_tipo_ativo(tipo):
    """Retorna o valor textual de um Enum de tipo de ativo (ou o próprio valor)."""
    return getattr(tipo, "value", tipo)


def serializar_ativo(ativo):
    """Serialize um ``Ativo`` sem vazar nenhum dado interno sensível."""
    perfil = getattr(ativo, "perfil", None)
    return {
        "id": ativo.id,
        "ticker": ativo.ticker,
        "cnpj": ativo.cnpj,
        "tipo": _texto_tipo_ativo(ativo.tipo),
        "setor": perfil.setor if perfil is not None else None,
        "tipo_fii": perfil.tipo_fii if perfil is not None else None,
    }


def serializar_indicador(registro):
    """Serialize um ``IndicadorHistorico`` com os campos de estado do indicador."""
    ativo = getattr(registro, "ativo", None)
    return {
        "id": registro.id,
        "ativo_id": registro.ativo_id,
        "ticker": ativo.ticker if ativo is not None else None,
        "tipo_ativo": registro.tipo_ativo,
        "indicador": registro.indicador,
        "valor_atual": _numero(registro.valor_atual),
        "valor_anterior": _numero(registro.valor_anterior),
        "variacao_percentual": _numero(registro.variacao_percentual),
        "data_referencia": _data(registro.data_referencia),
        "data_ultima_alteracao": _data(registro.data_ultima_alteracao),
        "ultima_coleta": _data(registro.ultima_coleta),
        "origem": registro.origem,
    }


def serializar_alerta(alerta):
    """Serialize um ``AlertaEvento`` (somente leitura, nenhum segredo)."""
    ativo = getattr(alerta, "ativo", None)
    return {
        "id": alerta.id,
        "tipo_alerta": alerta.tipo_alerta,
        "tipo_ativo": alerta.tipo_ativo,
        "ativo_id": alerta.ativo_id,
        "ticker": ativo.ticker if ativo is not None else None,
        "indicador": alerta.indicador,
        "valor_anterior": _numero(alerta.valor_anterior),
        "valor_atual": _numero(alerta.valor_atual),
        "variacao_percentual": _numero(alerta.variacao_percentual),
        "regra": alerta.regra,
        "motivo": alerta.motivo,
        "severidade": alerta.severidade,
        "recomendacao": alerta.recomendacao,
        "origem": alerta.origem,
        "data_referencia": _data(alerta.data_referencia),
        "data_evento": _data(alerta.data_evento),
        "telegram_enviado": bool(alerta.telegram_enviado),
    }


def serializar_documento(documento):
    """Serialize um ``DocumentosQualitativos`` sem conteúdo pesado.

    Nunca inclui ``texto_extraido``, ``resumo_ia``, ``log_erro``, ``hash_sha256``
    nem qualquer arquivo binário — apenas metadados para navegação.
    """
    ativo = getattr(documento, "ativo", None)
    return {
        "id": documento.id,
        "ativo_id": documento.ativo_id,
        "ticker": ativo.ticker if ativo is not None else None,
        "data_publicacao": _data(documento.data_publicacao),
        "tipo_documento": documento.tipo_documento,
        "url_pdf": documento.url_pdf,
        "assunto": documento.assunto,
        "id_b3": documento.id_b3,
        "status_processamento": documento.status_processamento,
        "data_atualizacao": _data(documento.data_atualizacao),
    }


def serializar_usuario(usuario):
    """Serialize o usuário autenticado sem nenhum campo sensível.

    Exclui ``senha_hash``, sessões, API Keys, tokens, hashes e segredos.
    """
    return {
        "id": usuario.id,
        "nome": usuario.nome,
        "email": usuario.email,
        "papel": usuario.papel,
        "ativo": bool(usuario.ativo),
        "ultimo_login": _data(usuario.ultimo_login),
        "criado_em": _data(usuario.criado_em),
        "atualizado_em": _data(usuario.atualizado_em),
    }
