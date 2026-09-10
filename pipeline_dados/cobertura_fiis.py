"""Cobertura e qualidade dos dados de FII — Fase 8, Etapa 8.6.

Mede, por FII e por campo já existente, o que está preenchido, ausente,
derivado ou sem fonte integrada. Não expande o universo, não cria fonte nova
e não inventa valor: ausência permanece ausência; placeholder não é dado.

Reutiliza freshness 8.4 (FRESH/STALE/MISSING) na categoria do campo.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pipeline_dados.banco_dados import (
    Ativo,
    AtivoInquilino,
    AtivoPerfil,
    DadosFinanceirosFiis,
    SnapshotFii,
    TipoAtivo,
)
from pipeline_dados.cobertura import tickers_catalogo
from pipeline_dados.freshness import (
    CONTABIL,
    DADOS_FII,
    DOCUMENTOS,
    INDICADORES_MERCADO,
    MISSING,
    PRECO,
    avaliar_ativo,
    dado_utilizavel,
)
from pipeline_dados.normalizacao import normalizar_texto

PREENCHIDO = "PREENCHIDO"
AUSENTE = "AUSENTE"
DERIVADO = "DERIVADO"
PLACEHOLDER = "PLACEHOLDER"
FONTE_INEXISTENTE = "FONTE_INEXISTENTE"
NAO_MAPEADO = "NAO_MAPEADO"

CONFIAVEL = "CONFIAVEL"
FRAGIL = "FRAGIL"

ORIGEM_SNAPSHOT = "snapshots_fiis"
ORIGEM_CONTABIL = "dados_financeiros_fiis"
ORIGEM_PERFIL = "ativos_perfil"
ORIGEM_INQUILINOS = "ativos_inquilinos"
ORIGEM_DOCUMENTOS = "documentos_qualitativos"
ORIGEM_SHEETS = "BD_FIIs"

_PLACEHOLDERS = frozenset(
    {
        "pendente de ia",
        "pendente",
        "n/a",
        "n/d",
        "na",
        "-",
        "--",
    }
)


@dataclass(frozen=True)
class CampoFii:
    nome: str
    origem: str
    qualidade: str
    persistido: str | None
    categoria_freshness: str | None
    observacao: str = ""


def _campo(nome, origem, qualidade, persistido, categoria, observacao=""):
    return CampoFii(nome, origem, qualidade, persistido, categoria, observacao)


CAMPOS_FII: tuple[CampoFii, ...] = (
    _campo("preco", ORIGEM_SNAPSHOT, CONFIAVEL, "preco", PRECO, "yfinance/Fundamentus"),
    _campo("pvp", ORIGEM_SNAPSHOT, CONFIAVEL, "pvp", INDICADORES_MERCADO, "Fundamentus"),
    _campo("dy", ORIGEM_SNAPSHOT, CONFIAVEL, "dy", INDICADORES_MERCADO, "Fundamentus; fração 0-1"),
    _campo("liquidez", ORIGEM_SNAPSHOT, CONFIAVEL, "liquidez", INDICADORES_MERCADO, "Fundamentus"),
    _campo(
        "vpa", ORIGEM_SNAPSHOT, DERIVADO, "vpa", INDICADORES_MERCADO,
        "derivado preco/pvp no scraper",
    ),
    _campo(
        "lucro_12m", ORIGEM_SNAPSHOT, DERIVADO, "lucro_12m", INDICADORES_MERCADO,
        "derivado valor_mercado*dy no scraper",
    ),
    _campo(
        "dividendo_mensal", ORIGEM_SNAPSHOT, DERIVADO, "dividendo_mensal", INDICADORES_MERCADO,
        "derivado preco*dy/12 no scraper",
    ),
    _campo(
        "qtd_imoveis", ORIGEM_SNAPSHOT, FRAGIL, "qtd_imoveis", INDICADORES_MERCADO,
        "StatusInvest/Fundamentus HTML; 0 real de Papel é válido",
    ),
    _campo(
        "walt", ORIGEM_SNAPSHOT, FONTE_INEXISTENTE, "walt", INDICADORES_MERCADO,
        "PENDENTE: coluna Sheets é placeholder de IA; sem fonte integrada",
    ),
    _campo(
        "alavancagem", ORIGEM_SNAPSHOT, FONTE_INEXISTENTE, "alavancagem", INDICADORES_MERCADO,
        "PENDENTE: coluna Sheets é placeholder de IA; sem fonte integrada",
    ),
    _campo(
        "patrimonio_liquido", ORIGEM_CONTABIL, CONFIAVEL, "patrimonio_liquido", CONTABIL,
        "CVM INF_MENSAL Patrimonio_Liquido",
    ),
    _campo(
        "ativo_total", ORIGEM_CONTABIL, CONFIAVEL, "ativo_total", CONTABIL,
        "CVM INF_MENSAL Valor_Ativo",
    ),
    _campo(
        "disponibilidades_caixa", ORIGEM_CONTABIL, CONFIAVEL, "disponibilidades_caixa", CONTABIL,
        "CVM INF_MENSAL Disponibilidades",
    ),
    _campo("cotistas", ORIGEM_CONTABIL, CONFIAVEL, "cotistas", CONTABIL, "CVM Total_Numero_Cotistas"),
    _campo(
        "cotas_emitidas", ORIGEM_CONTABIL, CONFIAVEL, "cotas_emitidas", CONTABIL,
        "CVM Cotas_Emitidas / Quantidade_Cotas_Emitidas",
    ),
    _campo(
        "valor_patrimonial_cotas", ORIGEM_CONTABIL, CONFIAVEL, "valor_patrimonial_cotas", CONTABIL,
        "CVM INF_MENSAL Valor_Patrimonial_Cotas (R$/cota)",
    ),
    _campo(
        "percentual_dividend_yield_mes", ORIGEM_CONTABIL, CONFIAVEL,
        "percentual_dividend_yield_mes", CONTABIL,
        "CVM INF_MENSAL Percentual_Dividend_Yield_Mes (fracao 0-1); nao e DY 12m",
    ),
    _campo(
        "rendimento_por_cota", ORIGEM_CONTABIL, FONTE_INEXISTENTE, "rendimento_por_cota", CONTABIL,
        "PENDENTE: schema existe; INF_MENSAL CSV não traz R$/cota",
    ),
    _campo(
        "vacancia_fisica", ORIGEM_CONTABIL, FONTE_INEXISTENTE, "vacancia_fisica", CONTABIL,
        "PENDENTE: schema existe; INF_MENSAL CSV não traz vacância",
    ),
    _campo(
        "vacancia_financeira", ORIGEM_CONTABIL, FONTE_INEXISTENTE, "vacancia_financeira", CONTABIL,
        "PENDENTE: schema existe; INF_MENSAL CSV não traz vacância",
    ),
    _campo(
        "receita_imoveis", ORIGEM_CONTABIL, CONFIAVEL, "receita_imoveis", CONTABIL,
        "CVM INF_TRIMESTRAL Receita_Aluguel_Investimento_Contabil",
    ),
    _campo(
        "resultado_ligado_venda", ORIGEM_CONTABIL, FONTE_INEXISTENTE, "resultado_ligado_venda", CONTABIL,
        "PENDENTE: receita de venda CVM nao equivale ao resultado do schema",
    ),
    _campo(
        "despesas_taxas", ORIGEM_CONTABIL, CONFIAVEL, "despesas_taxas", CONTABIL,
        "CVM INF_TRIMESTRAL Taxa_Administracao_Contabil (R$ do periodo)",
    ),
    _campo("setor", ORIGEM_PERFIL, CONFIAVEL, "setor", DADOS_FII, "StatusInvest segmento"),
    _campo(
        "tipo_fii", ORIGEM_PERFIL, DERIVADO, "tipo_fii", DADOS_FII,
        "classificar_fii_e_emoji a partir do setor",
    ),
    _campo(
        "inquilinos", ORIGEM_INQUILINOS, FRAGIL, "nome", DADOS_FII,
        "StatusInvest HTML top-3; sentinela não gera registro",
    ),
    _campo(
        "documentos", ORIGEM_DOCUMENTOS, CONFIAVEL, None, DOCUMENTOS,
        "FNET/B3 quando o matching 8.3 resolve o ativo",
    ),
    _campo(
        "vacancia", ORIGEM_SHEETS, NAO_MAPEADO, None, None,
        "Sheets mistura física/financeira; sem destino fiel no ORM",
    ),
    _campo(
        "numero_cotas", ORIGEM_SHEETS, NAO_MAPEADO, None, None,
        "estimativa valor_mercado/preco; não equivale a cotas_emitidas CVM",
    ),
    _campo(
        "valor_mercado", ORIGEM_SHEETS, NAO_MAPEADO, None, None,
        "coluna rotulada PL Total; PL real vem da CVM",
    ),
)

CAMPOS_POR_NOME = {campo.nome: campo for campo in CAMPOS_FII}


def campos_pendentes() -> tuple[str, ...]:
    return tuple(
        campo.nome
        for campo in CAMPOS_FII
        if campo.observacao.startswith("PENDENTE")
    )


def _valor_serializavel(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    return valor


def eh_placeholder_fii(valor) -> bool:
    if valor is None or not isinstance(valor, str):
        return False
    texto = normalizar_texto(valor).strip().lower()
    return texto in _PLACEHOLDERS


def _esperavel(campo: CampoFii) -> bool:
    return campo.qualidade in (CONFIAVEL, FRAGIL, DERIVADO)


def _valor_do_campo(campo: CampoFii, snapshot, contabil, perfil, inquilinos, tem_documento):
    if campo.qualidade == NAO_MAPEADO:
        return None
    if campo.nome == "inquilinos":
        return len(inquilinos) if inquilinos else None
    if campo.nome == "documentos":
        return True if tem_documento else None
    if campo.origem == ORIGEM_SNAPSHOT:
        return getattr(snapshot, campo.persistido, None) if snapshot is not None else None
    if campo.origem == ORIGEM_CONTABIL:
        return getattr(contabil, campo.persistido, None) if contabil is not None else None
    if campo.origem == ORIGEM_PERFIL:
        return getattr(perfil, campo.persistido, None) if perfil is not None else None
    return None


def _status_campo(campo: CampoFii, valor) -> str:
    if campo.qualidade == NAO_MAPEADO:
        return NAO_MAPEADO
    if eh_placeholder_fii(valor):
        return PLACEHOLDER if campo.qualidade != FONTE_INEXISTENTE else FONTE_INEXISTENTE
    if campo.qualidade == FONTE_INEXISTENTE:
        if dado_utilizavel(valor):
            return PREENCHIDO
        return FONTE_INEXISTENTE
    if campo.nome == "inquilinos":
        if valor:
            return PREENCHIDO
        return AUSENTE
    if campo.nome == "documentos":
        return PREENCHIDO if valor else AUSENTE
    if not dado_utilizavel(valor):
        return AUSENTE
    if campo.qualidade == DERIVADO:
        return DERIVADO
    return PREENCHIDO


def _freshness_campo(campo: CampoFii, categorias: dict) -> str | None:
    if campo.categoria_freshness is None:
        return None
    estado = categorias.get(campo.categoria_freshness) or {}
    return estado.get("status")


def avaliar_campos_fii(session, ativo, agora=None) -> dict:
    """Cobertura por campo de um FII persistido. Não inventa valor."""
    tipo = ativo.tipo.value if hasattr(ativo.tipo, "value") else str(ativo.tipo)
    if tipo != "FII":
        return {
            "ticker": ativo.ticker,
            "tipo": tipo,
            "campos": {},
            "resumo": {
                "esperados": 0,
                "preenchidos": 0,
                "ausentes": 0,
                "derivados": 0,
                "fonte_inexistente": 0,
                "nao_mapeados": 0,
                "placeholders": 0,
                "percentual_preenchido": None,
            },
            "freshness": None,
        }

    freshness = avaliar_ativo(session, ativo, agora=agora)
    categorias = freshness.get("categorias") or {}
    snapshot = (
        session.query(SnapshotFii)
        .filter(SnapshotFii.ativo_id == ativo.id)
        .order_by(SnapshotFii.data_referencia.desc(), SnapshotFii.id.desc())
        .first()
    )
    contabil = (
        session.query(DadosFinanceirosFiis)
        .filter(DadosFinanceirosFiis.ativo_id == ativo.id)
        .order_by(DadosFinanceirosFiis.data_referencia.desc(), DadosFinanceirosFiis.id.desc())
        .first()
    )
    perfil = session.query(AtivoPerfil).filter(AtivoPerfil.ativo_id == ativo.id).first()
    inquilinos = (
        session.query(AtivoInquilino)
        .filter(AtivoInquilino.ativo_id == ativo.id)
        .all()
    )
    tem_documento = categorias.get(DOCUMENTOS, {}).get("status") not in (None, MISSING)

    campos = {}
    preenchidos = 0
    ausentes = 0
    derivados = 0
    fonte_inexistente = 0
    nao_mapeados = 0
    placeholders = 0
    esperados = 0

    for definicao in CAMPOS_FII:
        valor = _valor_do_campo(definicao, snapshot, contabil, perfil, inquilinos, tem_documento)
        status = _status_campo(definicao, valor)
        if status == PLACEHOLDER or eh_placeholder_fii(valor):
            valor_exibido = None
        elif definicao.nome == "inquilinos":
            valor_exibido = valor
        elif definicao.nome == "documentos":
            valor_exibido = bool(valor)
        else:
            valor_exibido = _valor_serializavel(valor) if dado_utilizavel(valor) else None
        campos[definicao.nome] = {
            "campo": definicao.nome,
            "status": status,
            "qualidade": definicao.qualidade,
            "origem": definicao.origem,
            "persistido": definicao.persistido,
            "valor": valor_exibido,
            "freshness": _freshness_campo(definicao, categorias),
            "observacao": definicao.observacao,
        }
        if _esperavel(definicao):
            esperados += 1
            if status in (PREENCHIDO, DERIVADO):
                preenchidos += 1
            elif status == AUSENTE:
                ausentes += 1
        if status == DERIVADO:
            derivados += 1
        elif status == FONTE_INEXISTENTE:
            fonte_inexistente += 1
        elif status == NAO_MAPEADO:
            nao_mapeados += 1
        elif status == PLACEHOLDER:
            placeholders += 1

    percentual = (preenchidos / esperados) if esperados else None
    return {
        "ticker": ativo.ticker,
        "tipo": tipo,
        "campos": campos,
        "resumo": {
            "esperados": esperados,
            "preenchidos": preenchidos,
            "ausentes": ausentes,
            "derivados": derivados,
            "fonte_inexistente": fonte_inexistente,
            "nao_mapeados": nao_mapeados,
            "placeholders": placeholders,
            "percentual_preenchido": percentual,
        },
        "freshness": freshness,
    }


def cobertura_campos_fii(session, agora=None, ticker=None) -> dict:
    """Cobertura por campo do universo FII cadastrado, sem expandir coleta."""
    universo = tickers_catalogo(session, TipoAtivo.FII)
    if ticker:
        ticker_limpo = str(ticker).strip().upper()
        universo_alvo = [ticker_limpo]
        ativos = session.query(Ativo).filter(
            Ativo.ticker == ticker_limpo, Ativo.tipo == TipoAtivo.FII
        ).all()
    else:
        universo_alvo = list(universo)
        ativos = session.query(Ativo).filter(Ativo.tipo == TipoAtivo.FII).all()

    por_ticker = {
        ativo.ticker: avaliar_campos_fii(session, ativo, agora=agora) for ativo in ativos
    }
    fora = sorted(set(universo_alvo) - set(por_ticker))
    totais = {
        "esperados": 0,
        "preenchidos": 0,
        "ausentes": 0,
        "derivados": 0,
        "fonte_inexistente": 0,
        "nao_mapeados": 0,
        "placeholders": 0,
    }
    for relatorio in por_ticker.values():
        for chave in totais:
            totais[chave] += relatorio["resumo"][chave]
    percentual = (
        totais["preenchidos"] / totais["esperados"] if totais["esperados"] else None
    )
    return {
        "tipo": "FII",
        "universo_total": len(universo_alvo),
        "avaliados": sorted(por_ticker),
        "avaliados_total": len(por_ticker),
        "fora": fora,
        "fora_total": len(fora),
        "por_ticker": por_ticker,
        "campos": [campo.nome for campo in CAMPOS_FII],
        "pendentes": campos_pendentes(),
        "resumo": {**totais, "percentual_preenchido": percentual},
    }
