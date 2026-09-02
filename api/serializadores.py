"""Serializers explícitos da API (Fase 5, Etapa 10).

Convertem objetos ORM em dicionários JSON-friendly, campo a campo, evitando
``obj.__dict__`` e vazamento acidental de campos internos ou sensíveis:

- documentos: exclui ``texto_extraido``, ``resumo_ia``, ``log_erro`` e arquivos;
- usuário: exclui ``senha_hash``, sessões, API Keys, tokens e segredos;
- valores NUMERIC/Date/DateTime são normalizados para JSON (float/isoformat).
"""
import json
from datetime import date, datetime
from decimal import Decimal

from services import planos
from services.carteira import valor_investido_posicao


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

    Exclui ``senha_hash``, sessões, API Keys, tokens, hashes e segredos. O
    Telegram é exposto apenas como vínculo (booleano) — nunca o ID interno.
    ``plano`` é o plano efetivo (Fase 6, Etapa 8) decidido pela camada central
    ``services/planos.py`` — nunca um valor vindo do cliente.
    """
    return {
        "id": usuario.id,
        "nome": usuario.nome,
        "email": usuario.email,
        "papel": usuario.papel,
        "plano": planos.plano_de(usuario),
        "ativo": bool(usuario.ativo),
        "telegram_vinculado": bool(usuario.telegram_user_id),
        "ultimo_login": _data(usuario.ultimo_login),
        "criado_em": _data(usuario.criado_em),
        "atualizado_em": _data(usuario.atualizado_em),
    }


def serializar_chave_api(registro):
    """Serialize uma ``ChaveApi`` sem o hash nem qualquer segredo.

    Nunca expõe ``chave_hash`` (a chave original é irreversível e exibida
    somente na criação). Apenas estado e metadados para navegação do dono.
    """
    if registro is None:
        return None
    return {
        "id": registro.id,
        "rotulo": registro.rotulo,
        "ativa": bool(registro.ativa),
        "expira_em": _data(registro.expira_em),
        "criado_em": _data(registro.criado_em),
    }


def serializar_acompanhamento(acompanhamento):
    """Serialize um ``AtivoAcompanhado`` sem dados de terceiros nem segredos.

    Inclui apenas dados públicos do ativo (ticker/tipo) e o vínculo; o
    ``usuario_id`` do dono não é necessário ao cliente autenticado.
    """
    ativo = getattr(acompanhamento, "ativo", None)
    return {
        "id": acompanhamento.id,
        "ativo_id": acompanhamento.ativo_id,
        "ticker": ativo.ticker if ativo is not None else None,
        "tipo": _texto_tipo_ativo(ativo.tipo) if ativo is not None else None,
        "criado_em": _data(acompanhamento.criado_em),
    }


def serializar_notificacao(notificacao):
    """Serialize uma ``Notificacao`` sem nenhum dado de terceiros nem segredos.

    Não expõe ``usuario_id`` (o cliente autenticado é o dono). ``dados`` é
    retornado como objeto quando presente — o payload já foi sanitizado pelo
    motor (nenhum segredo é persistido ou exposto). O ticker aparece apenas
    quando o ativo está vinculado.
    """
    if notificacao is None:
        return None
    ativo = getattr(notificacao, "ativo", None)
    dados = None
    if notificacao.dados:
        try:
            dados = json.loads(notificacao.dados)
        except (TypeError, ValueError):
            dados = None
    return {
        "id": notificacao.id,
        "tipo": notificacao.tipo,
        "titulo": notificacao.titulo,
        "mensagem": notificacao.mensagem,
        "ativo_id": notificacao.ativo_id,
        "ticker": ativo.ticker if ativo is not None else None,
        "canal": notificacao.canal,
        "status": notificacao.status,
        "dados": dados,
        "criado_em": _data(notificacao.criado_em),
        "lida_em": _data(notificacao.lida_em),
        "tentativas": int(notificacao.tentativas or 0),
        "enviada_em": _data(notificacao.enviada_em),
    }


def serializar_preferencias(preferencias):
    """Serialize ``PreferenciasUsuario`` sem nenhum dado sensível.

    Não expõe ``usuario_id`` (o cliente autenticado é o dono) nem qualquer
    segredo. Campos de notificação/mercado aparecem como booleanos explícitos
    e as frequências como texto controlado pelas enums de
    ``services/preferencias``.
    """
    if preferencias is None:
        return None
    return {
        "notificacoes_ativas": bool(preferencias.notificacoes_ativas),
        "notificacoes_preco": bool(preferencias.notificacoes_preco),
        "notificacoes_dividendos": bool(preferencias.notificacoes_dividendos),
        "notificacoes_resultados": bool(preferencias.notificacoes_resultados),
        "notificacoes_documentos": bool(preferencias.notificacoes_documentos),
        "notificacoes_alertas": bool(preferencias.notificacoes_alertas),
        "frequencia_notificacoes": preferencias.frequencia_notificacoes,
        "telegram_ativo": bool(preferencias.telegram_ativo),
        "web_ativo": bool(preferencias.web_ativo),
        "relatorios_ativos": bool(preferencias.relatorios_ativos),
        "frequencia_relatorios": preferencias.frequencia_relatorios,
        "mercado_acoes": bool(preferencias.mercado_acoes),
        "mercado_fiis": bool(preferencias.mercado_fiis),
        "criado_em": _data(preferencias.criado_em),
        "atualizado_em": _data(preferencias.atualizado_em),
    }


def serializar_posicao(posicao):
    """Serialize uma ``PosicaoCarteira`` com a derivada simples, sem segredos.

    Exibe ``quantidade``, ``preco_medio`` e ``valor_investido`` (derivado de
    dados persistidos — nenhuma fonte externa). Nunca expõe ``usuario_id`` nem
    qualquer campo sensível.
    """
    ativo = getattr(posicao, "ativo", None)
    return {
        "id": posicao.id,
        "ativo_id": posicao.ativo_id,
        "ticker": ativo.ticker if ativo is not None else None,
        "tipo": _texto_tipo_ativo(ativo.tipo) if ativo is not None else None,
        "quantidade": _numero(posicao.quantidade),
        "preco_medio": _numero(posicao.preco_medio),
        "valor_investido": _numero(valor_investido_posicao(posicao)),
        "criado_em": _data(posicao.criado_em),
        "atualizado_em": _data(posicao.atualizado_em),
    }
