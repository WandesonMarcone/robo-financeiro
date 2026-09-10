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

from services import mercado, planos
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


# Unidades conhecidas na API para campos CVM ainda fora do catálogo 8.5.
# Não altera valores persistidos nem a camada de coleta.
_UNIDADES_API = {
    "ativo_total": ("monetario", "R$"),
    "patrimonio_liquido": ("monetario", "R$"),
    "disponibilidades_caixa": ("monetario", "R$"),
    "caixa": ("monetario", "R$"),
    "passivo_total": ("monetario", "R$"),
    "divida_bruta": ("monetario", "R$"),
    "divida_liquida": ("monetario", "R$"),
    "receita": ("monetario", "R$"),
    "lucro_bruto": ("monetario", "R$"),
        "ebitda": ("monetario", "R$"),
        "ebit": ("monetario", "R$"),
        "depreciacao": ("monetario", "R$"),
        "ativo_circulante": ("monetario", "R$"),
        "passivo_circulante": ("monetario", "R$"),
        "lucro_liquido": ("monetario", "R$"),
    "fco": ("monetario", "R$"),
    "rendimento_por_cota": ("monetario", "R$"),
    "valor_patrimonial_cotas": ("monetario", "R$"),
    "percentual_dividend_yield_mes": ("fracao", "%"),
    "cotas_emitidas": ("quantidade", "un."),
    "receita_imoveis": ("monetario", "R$"),
    "resultado_ligado_venda": ("monetario", "R$"),
    "vacancia_fisica": ("fracao", "%"),
    "vacancia_financeira": ("fracao", "%"),
    "despesas_taxas": ("monetario", "R$"),
}


def _campo_semantico(tipo_ativo, indicador, valor):
    """Contrato 8.5 ao lado do número persistido, sem alterar o valor armazenado."""
    interpretacao = mercado.interpretar_indicador(tipo_ativo, indicador, valor)
    unidade = interpretacao.get("unidade")
    escala = interpretacao.get("escala")
    if unidade is None and indicador in _UNIDADES_API:
        escala, unidade = _UNIDADES_API[indicador]
    return {
        "semantica": interpretacao.get("semantica"),
        "unidade": unidade,
        "escala": escala,
        "aplicavel": interpretacao.get("aplicavel"),
    }


def _anexar_semantica(payload, tipo_ativo, campos):
    """Acrescenta bloco ``campos`` com semantica/unidade/escala por indicador."""
    semantica = {}
    for indicador in campos:
        if indicador not in payload:
            continue
        semantica[indicador] = _campo_semantico(tipo_ativo, indicador, payload.get(indicador))
    if semantica:
        payload["campos"] = semantica
    return payload


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
    valor_atual = _numero(registro.valor_atual)
    interpretacao = mercado.interpretar_indicador(
        registro.tipo_ativo, registro.indicador, registro.valor_atual
    )
    return {
        "id": registro.id,
        "ativo_id": registro.ativo_id,
        "ticker": ativo.ticker if ativo is not None else None,
        "tipo_ativo": registro.tipo_ativo,
        "indicador": registro.indicador,
        "valor_atual": valor_atual,
        "valor_anterior": _numero(registro.valor_anterior),
        "variacao_percentual": _numero(registro.variacao_percentual),
        "data_referencia": _data(registro.data_referencia),
        "data_ultima_alteracao": _data(registro.data_ultima_alteracao),
        "ultima_coleta": _data(registro.ultima_coleta),
        "origem": registro.origem,
        "semantica": interpretacao.get("semantica"),
        "unidade": interpretacao.get("unidade"),
        "escala": interpretacao.get("escala"),
        "aplicavel": interpretacao.get("aplicavel"),
    }


def serializar_freshness(estado):
    """Serialize o dict de freshness (FRESH/STALE/MISSING) por categoria."""
    if estado is None:
        return None

    def _categoria(item):
        if not item:
            return None
        sla = item.get("sla")
        return {
            "categoria": item.get("categoria"),
            "status": item.get("status"),
            "valor": _numero(item.get("valor")),
            "data_referencia": _data(item.get("data_referencia")),
            "data_coleta": _data(item.get("data_coleta")),
            "data_publicacao": _data(item.get("data_publicacao")),
            "fonte": item.get("fonte"),
            "fonte_primaria": item.get("fonte_primaria"),
            "fonte_intermediaria": item.get("fonte_intermediaria"),
            "url_origem": item.get("url_origem"),
            "sla_segundos": int(sla.total_seconds()) if sla is not None else None,
        }

    categorias = estado.get("categorias") or {}
    return {
        "ticker": estado.get("ticker"),
        "tipo": estado.get("tipo"),
        "categorias": {nome: _categoria(valor) for nome, valor in categorias.items()},
    }


def _serializar_campo_cobertura_fii(campo):
    """Serialize um campo do relatório 8.6 sem objetos internos."""
    if not campo:
        return None
    valor = campo.get("valor")
    if isinstance(valor, Decimal):
        valor = float(valor)
    elif isinstance(valor, (date, datetime)):
        valor = valor.isoformat()
    return {
        "campo": campo.get("campo"),
        "status": campo.get("status"),
        "qualidade": campo.get("qualidade"),
        "origem": campo.get("origem"),
        "persistido": campo.get("persistido"),
        "valor": valor,
        "freshness": campo.get("freshness"),
        "observacao": campo.get("observacao"),
    }


def serializar_cobertura_fii_ticker(relatorio):
    """Serialize a cobertura de um FII, incluindo freshness via adapter HTTP."""
    if not relatorio:
        return None
    campos = relatorio.get("campos") or {}
    resumo = dict(relatorio.get("resumo") or {})
    if "percentual_preenchido" in resumo and isinstance(resumo["percentual_preenchido"], Decimal):
        resumo["percentual_preenchido"] = float(resumo["percentual_preenchido"])
    return {
        "ticker": relatorio.get("ticker"),
        "tipo": relatorio.get("tipo"),
        "campos": {nome: _serializar_campo_cobertura_fii(valor) for nome, valor in campos.items()},
        "resumo": resumo,
        "freshness": serializar_freshness(relatorio.get("freshness")),
    }


def serializar_cobertura_fii(relatorio):
    """Serialize o relatório agregado de cobertura FII (sem JSON cru)."""
    if not relatorio:
        return None
    por_ticker = relatorio.get("por_ticker") or {}
    items = [
        serializar_cobertura_fii_ticker(por_ticker[ticker])
        for ticker in sorted(por_ticker)
    ]
    resumo = dict(relatorio.get("resumo") or {})
    if "percentual_preenchido" in resumo and isinstance(resumo["percentual_preenchido"], Decimal):
        resumo["percentual_preenchido"] = float(resumo["percentual_preenchido"])
    return {
        "tipo": relatorio.get("tipo"),
        "universo_total": relatorio.get("universo_total"),
        "avaliados": list(relatorio.get("avaliados") or []),
        "avaliados_total": relatorio.get("avaliados_total"),
        "fora": list(relatorio.get("fora") or []),
        "fora_total": relatorio.get("fora_total"),
        "items": items,
        "por_ticker": {item["ticker"]: item for item in items if item and item.get("ticker")},
        "campos": list(relatorio.get("campos") or []),
        "pendentes": list(relatorio.get("pendentes") or []),
        "resumo": resumo,
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


def _campos_base_snapshot(snapshot, tipo):
    """Campos comuns a um snapshot de mercado (FII ou ação)."""
    ativo = getattr(snapshot, "ativo", None)
    return {
        "id": snapshot.id,
        "ativo_id": snapshot.ativo_id,
        "ticker": ativo.ticker if ativo is not None else None,
        "tipo": tipo,
        "data_referencia": _data(snapshot.data_referencia),
        "data_coleta": _data(snapshot.data_coleta),
        "data_publicacao": _data(snapshot.data_publicacao),
        "fonte": snapshot.fonte,
        "fonte_primaria": getattr(snapshot, "fonte_primaria", None),
        "fonte_intermediaria": getattr(snapshot, "fonte_intermediaria", None),
        "url_origem": snapshot.url_origem,
        "preco": _numero(snapshot.preco),
        "dy": _numero(snapshot.dy),
        "pvp": _numero(snapshot.pvp),
        "vpa": _numero(snapshot.vpa),
    }


def serializar_snapshot_fii(snapshot):
    """Serialize um ``SnapshotFii`` com os indicadores de mercado do FII."""
    base = _campos_base_snapshot(snapshot, "FII")
    payload = {
        **base,
        "qtd_imoveis": snapshot.qtd_imoveis,
        "walt": snapshot.walt,
        "alavancagem": snapshot.alavancagem,
        "liquidez": _numero(snapshot.liquidez),
        "lucro_12m": _numero(snapshot.lucro_12m),
        "dividendo_mensal": _numero(snapshot.dividendo_mensal),
        "proveniencia": {
            "vpa": "snapshots_fiis.vpa (mercado; distinto de valor_patrimonial_cotas CVM)",
            "dy": "snapshots_fiis.dy (fracao 0-1; distinto de percentual_dividend_yield_mes CVM)",
        },
    }
    return _anexar_semantica(
        payload,
        "FII",
        ("preco", "dy", "pvp", "vpa", "liquidez", "lucro_12m", "dividendo_mensal", "qtd_imoveis"),
    )


def serializar_snapshot_acao(snapshot):
    """Serialize um ``SnapshotAcao`` com os múltiplos e margens da ação."""
    base = _campos_base_snapshot(snapshot, "ACAO")
    payload = {
        **base,
        "pl": _numero(snapshot.pl),
        "p_ativo": _numero(snapshot.p_ativo),
        "marg_bruta": _numero(snapshot.marg_bruta),
        "marg_ebit": _numero(snapshot.marg_ebit),
        "marg_liquida": _numero(snapshot.marg_liquida),
        "p_ebit": _numero(snapshot.p_ebit),
        "ev_ebit": _numero(snapshot.ev_ebit),
        "div_liq_ebit": _numero(snapshot.div_liq_ebit),
        "div_liq_patrimonio": _numero(snapshot.div_liq_patrimonio),
        "psr": _numero(snapshot.psr),
        "p_cap_giro": _numero(snapshot.p_cap_giro),
        "p_at_circ_liq": _numero(snapshot.p_at_circ_liq),
        "liq_corrente": _numero(snapshot.liq_corrente),
        "roe": _numero(snapshot.roe),
        "roa": _numero(snapshot.roa),
        "roic": _numero(snapshot.roic),
        "cagr_rec_5a": _numero(snapshot.cagr_rec_5a),
        "liq_media": _numero(snapshot.liq_media),
        "lpa": _numero(snapshot.lpa),
        "peg_ratio": _numero(snapshot.peg_ratio),
        "valor_mercado": _numero(snapshot.valor_mercado),
        "proveniencia": {
            "vpa": "snapshots_acoes.vpa (mercado)",
            "dy": "snapshots_acoes.dy (fracao 0-1)",
        },
    }
    return _anexar_semantica(
        payload,
        "ACAO",
        (
            "preco", "dy", "pvp", "vpa", "pl", "p_ativo", "marg_bruta", "marg_ebit",
            "marg_liquida", "p_ebit", "ev_ebit", "div_liq_ebit", "div_liq_patrimonio",
            "psr", "p_cap_giro", "p_at_circ_liq", "liq_corrente", "roe", "roa", "roic",
            "cagr_rec_5a", "liq_media", "lpa", "peg_ratio", "valor_mercado",
        ),
    )


def serializar_snapshot(snapshot):
    """Serialize um snapshot de mercado (FII ou ação) de forma explícita."""
    from pipeline_dados.banco_dados import SnapshotAcao, SnapshotFii

    if isinstance(snapshot, SnapshotFii):
        return serializar_snapshot_fii(snapshot)
    if isinstance(snapshot, SnapshotAcao):
        return serializar_snapshot_acao(snapshot)
    raise TypeError(f"Tipo de snapshot não suportado: {type(snapshot).__name__}")


def _campos_base_dados_financeiros(registro, tipo):
    """Campos comuns a um registro contábil persistido (FII ou ação)."""
    ativo = getattr(registro, "ativo", None)
    return {
        "id": registro.id,
        "ativo_id": registro.ativo_id,
        "ticker": ativo.ticker if ativo is not None else None,
        "tipo": tipo,
        "data_referencia": _data(registro.data_referencia),
        "data_coleta": _data(getattr(registro, "data_coleta", None)),
        "fonte": getattr(registro, "fonte", None),
        "fonte_primaria": getattr(registro, "fonte_primaria", None),
        "url_origem": getattr(registro, "url_origem", None),
        "ativo_total": _numero(registro.ativo_total),
        "patrimonio_liquido": _numero(registro.patrimonio_liquido),
    }


def serializar_dados_financeiros_acoes(registro):
    """Serialize um ``DadosFinanceirosAcoes`` (CVM ITR/DFP) de forma explícita."""
    base = _campos_base_dados_financeiros(registro, "ACAO")
    payload = {
        **base,
        "tipo_doc": registro.tipo_doc,
        "caixa": _numero(registro.caixa),
        "passivo_total": _numero(registro.passivo_total),
        "divida_bruta": _numero(registro.divida_bruta),
        "divida_curto_prazo": _numero(registro.divida_curto_prazo),
        "divida_longo_prazo": _numero(registro.divida_longo_prazo),
        "divida_liquida": _numero(registro.divida_liquida),
        "receita": _numero(registro.receita),
        "lucro_bruto": _numero(registro.lucro_bruto),
        "ebitda": _numero(registro.ebitda),
        "ebit": _numero(getattr(registro, "ebit", None)),
        "depreciacao": _numero(getattr(registro, "depreciacao", None)),
        "ativo_circulante": _numero(getattr(registro, "ativo_circulante", None)),
        "passivo_circulante": _numero(getattr(registro, "passivo_circulante", None)),
        "resultado_financeiro": _numero(registro.resultado_financeiro),
        "lucro_liquido": _numero(registro.lucro_liquido),
        "fco": _numero(registro.fco),
    }
    return _anexar_semantica(
        payload,
        "ACAO",
        (
            "ativo_total", "patrimonio_liquido", "caixa", "passivo_total",
            "divida_bruta", "divida_liquida", "receita", "lucro_bruto",
            "ebitda", "ebit", "lucro_liquido", "fco",
        ),
    )


def serializar_dados_financeiros_fiis(registro):
    """Serialize um ``DadosFinanceirosFiis`` (informe mensal CVM)."""
    base = _campos_base_dados_financeiros(registro, "FII")
    payload = {
        **base,
        "disponibilidades_caixa": _numero(registro.disponibilidades_caixa),
        "rendimento_por_cota": _numero(registro.rendimento_por_cota),
        "valor_patrimonial_cotas": _numero(getattr(registro, "valor_patrimonial_cotas", None)),
        "percentual_dividend_yield_mes": _numero(
            getattr(registro, "percentual_dividend_yield_mes", None)
        ),
        "cotistas": registro.cotistas,
        "cotas_emitidas": _numero(registro.cotas_emitidas),
        "receita_imoveis": _numero(registro.receita_imoveis),
        "resultado_ligado_venda": _numero(registro.resultado_ligado_venda),
        "vacancia_fisica": _numero(registro.vacancia_fisica),
        "vacancia_financeira": _numero(registro.vacancia_financeira),
        "despesas_taxas": _numero(registro.despesas_taxas),
        "proveniencia": {
            "valor_patrimonial_cotas": (
                "dados_financeiros_fiis.valor_patrimonial_cotas (CVM INF_MENSAL; R$/cota)"
            ),
            "percentual_dividend_yield_mes": (
                "dados_financeiros_fiis.percentual_dividend_yield_mes "
                "(CVM INF_MENSAL; fracao 0-1; nao e DY 12m de snapshot.dy)"
            ),
        },
    }
    return _anexar_semantica(
        payload,
        "FII",
        (
            "ativo_total", "patrimonio_liquido", "disponibilidades_caixa",
            "rendimento_por_cota", "valor_patrimonial_cotas",
            "percentual_dividend_yield_mes", "cotas_emitidas", "receita_imoveis",
            "resultado_ligado_venda", "vacancia_fisica", "vacancia_financeira",
            "despesas_taxas",
        ),
    )


def serializar_dados_financeiros(registro):
    """Serialize um registro contábil persistido (FII ou ação)."""
    from pipeline_dados.banco_dados import DadosFinanceirosAcoes, DadosFinanceirosFiis

    if isinstance(registro, DadosFinanceirosFiis):
        return serializar_dados_financeiros_fiis(registro)
    if isinstance(registro, DadosFinanceirosAcoes):
        return serializar_dados_financeiros_acoes(registro)
    raise TypeError(f"Tipo de dado financeiro não suportado: {type(registro).__name__}")


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
