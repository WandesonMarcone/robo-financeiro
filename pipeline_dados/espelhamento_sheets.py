"""Espelhamento Google Sheets -> PostgreSQL — Fase 3, Bloco 4.

Responsabilidade única: ler as abas BD_FIIs/BD_Acoes do Google Sheets,
normalizar, validar (pipeline_dados.qualidade_dados) e persistir no PostgreSQL
apenas o que o ORM atual suporta sem alteração de schema — a identidade do
ativo (tabela ``ativos``). As demais colunas (indicadores de mercado) são
registradas como LACUNAS no relatório de diagnóstico.

Garantias da rotina:
- Idempotente: executar repetidas vezes não cria duplicatas (unique ticker).
- Não apaga dados existentes do PostgreSQL e não modifica o Google Sheets.
- Reversível: remove apenas registros que ela própria criou (rollback em
  sessão local) — o módulo em si nunca apaga nada.
- Rastreável: origem registrada como "Google Sheets" e diagnósticos
  VALID/WARNING/INVALID via registrar_diagnostico.
- Google Sheets continua sendo a fonte ativa; o PostgreSQL é apenas espelho.
"""
import logging

from sqlalchemy.orm import Session

from pipeline_dados.banco_dados import Ativo, TipoAtivo
from pipeline_dados.catalogo_ativos import resolver_cnpj as resolver_cnpj_catalogo
from pipeline_dados.mapeamento_sheets import (
    ABAS_ESPELHAVEIS,
    ORIGEM_GOOGLE_SHEETS,
    campos_sem_destino,
    tipo_ativo_da_aba,
    transformar_linha_acao,
    transformar_linha_fii,
)
from pipeline_dados.qualidade_dados import (
    INVALID,
    WARNING,
    AchadoQualidade,
    registrar_diagnostico,
    regra_cnpj,
    validar_registro,
)

logger = logging.getLogger(__name__)

STATUS_CRIADO = "CRIADO"
STATUS_ATUALIZADO = "ATUALIZADO"
STATUS_INALTERADO = "INALTERADO"
STATUS_INVALIDO = "INVALID"


def _rebaixar_para_warning(achado: AchadoQualidade) -> AchadoQualidade:
    """Rebaixa um achado para WARNING (diagnóstico que não bloqueia a persistência)."""
    return AchadoQualidade(
        campo=achado.campo,
        severidade=WARNING,
        regra=achado.regra,
        valor=achado.valor,
        mensagem=achado.mensagem,
    )


def _criar_sessao() -> Session:
    """Abre sessão no engine central (Fase 7, Etapa 7.4).

    Antes criava um engine local duplicado; agora usa o engine único de
    ``services/db`` (mesmos parâmetros de pool do legado: ``pool_pre_ping`` e
    ``pool_recycle``). Mantém a garantia histórica de criar as tabelas ausentes
    (idempotente) antes de devolver a sessão, preservando o comportamento em
    contextos sem `create_all` explícito.
    """
    from services.db import criar_sessao, criar_tabelas

    criar_tabelas()
    return criar_sessao()


def espelhar_ativo(session: Session, ticker, tipo_ativo: TipoAtivo, cnpj=None, log=None):
    """Garante a existência do Ativo (ticker único) de forma idempotente.

    Retorna ``(ativo, resultado, status)``. ``ativo`` é None quando o registro
    é INVALID (ticker ausente/vazio); ``status`` indica CRIADO/ATUALIZADO/
    INALTERADO/INVALID. WARNINGs (ex.: CNPJ do catálogo com dígitos inválidos)
    são aceitos e não bloqueiam a persistência.

    A identidade do ativo segue o catálogo da Fase 7, Etapa 7.2
    (``pipeline_dados.catalogo_ativos``): o CNPJ é resolvido no PostgreSQL
    primeiro (``ativos_catalogo``) e apenas como fallback nos mapas de config
    (a mesma base de seed do catálogo). O placeholder ``PENDENTE-{ticker}`` é
    usado apenas quando o CNPJ não é conhecido por nenhuma das duas fontes —
    exigido pela constraint ``NOT NULL`` de ``ativos.cnpj``.
    """
    resultado = validar_registro(
        {"ticker": ticker}, "sheets_ativo", origem=ORIGEM_GOOGLE_SHEETS, ativo=ticker
    )
    if resultado.status == INVALID:
        registrar_diagnostico(resultado, log)
        return None, resultado, STATUS_INVALIDO

    ticker_limpo = str(ticker).strip().upper()
    cnpj_resolvido = cnpj
    if cnpj_resolvido is None:
        cnpj_resolvido = resolver_cnpj_catalogo(session, ticker_limpo, tipo_ativo)
    if cnpj_resolvido is None:
        cnpj_resolvido = f"PENDENTE-{ticker_limpo}"

    # CNPJ do catálogo (MAPA_CNPJ_B3) é identidade confiável, mas dígitos
    # inválidos geram WARNING (aceito). Placeholder é marcador interno e não
    # participa da validação.
    if cnpj_resolvido and not cnpj_resolvido.startswith("PENDENTE-"):
        achado = regra_cnpj("cnpj", cnpj_resolvido)
        if achado is not None:
            resultado.achados.append(_rebaixar_para_warning(achado))

    ativo = session.query(Ativo).filter(Ativo.ticker == ticker_limpo).first()
    if not ativo:
        ativo = Ativo(ticker=ticker_limpo, cnpj=cnpj_resolvido, tipo=tipo_ativo)
        session.add(ativo)
        session.flush()
        status = STATUS_CRIADO
    else:
        # Preserva dados existentes; apenas troca placeholder por CNPJ real.
        status = STATUS_INALTERADO
        if (
            ativo.cnpj
            and ativo.cnpj.startswith("PENDENTE-")
            and not cnpj_resolvido.startswith("PENDENTE-")
        ):
            ativo.cnpj = cnpj_resolvido
            status = STATUS_ATUALIZADO

    registrar_diagnostico(resultado, log)
    return ativo, resultado, status


def espelhar_planilha(session: Session, nome_aba: str, matriz, log=None) -> dict:
    """Espelha uma aba do Sheets. ``matriz`` = get_all_values() (1ª linha = cabeçalho).

    Retorna relatório de diagnóstico: contagens por status, warnings e as
    lacunas observadas (campos presentes sem destino no ORM).
    """
    if not matriz or len(matriz) < 2:
        return _relatorio_vazio(nome_aba)

    tipo_ativo = tipo_ativo_da_aba(nome_aba)
    if tipo_ativo is None:
        raise ValueError(f"Aba não espelhável: {nome_aba}")

    transformador = transformar_linha_fii if tipo_ativo is TipoAtivo.FII else transformar_linha_acao
    sem_destino = campos_sem_destino(nome_aba)

    relatorio = {
        "aba": nome_aba,
        "linhas": 0,
        "criados": 0,
        "atualizados": 0,
        "inalterados": 0,
        "invalidos": 0,
        "warnings": 0,
        "tickers": [],
        "lacunas": [],
        "origem": ORIGEM_GOOGLE_SHEETS,
    }

    for linha in matriz[1:]:
        if not linha or not str(linha[0]).strip():
            continue
        dados = transformador(linha)
        relatorio["linhas"] += 1

        ativo, resultado, status = espelhar_ativo(session, dados["ticker"], tipo_ativo, log=log)

        if status == STATUS_INVALIDO:
            relatorio["invalidos"] += 1
        elif status == STATUS_CRIADO:
            relatorio["criados"] += 1
        elif status == STATUS_ATUALIZADO:
            relatorio["atualizados"] += 1
        else:
            relatorio["inalterados"] += 1

        if resultado.status == WARNING:
            relatorio["warnings"] += 1

        if dados["ticker"]:
            relatorio["tickers"].append(dados["ticker"])

        for campo, valor in dados.items():
            if valor is not None and campo in sem_destino and campo not in relatorio["lacunas"]:
                relatorio["lacunas"].append(campo)

    session.commit()
    return relatorio


def _relatorio_vazio(nome_aba: str) -> dict:
    return {
        "aba": nome_aba,
        "linhas": 0,
        "criados": 0,
        "atualizados": 0,
        "inalterados": 0,
        "invalidos": 0,
        "warnings": 0,
        "tickers": [],
        "lacunas": [],
        "origem": ORIGEM_GOOGLE_SHEETS,
    }


def _resumir_totais(relatorios: list[dict]) -> dict:
    totais = {"criados": 0, "atualizados": 0, "inalterados": 0, "invalidos": 0, "warnings": 0}
    lacunas = []
    for rel in relatorios:
        for chave in totais:
            totais[chave] += rel[chave]
        for lacuna in rel["lacunas"]:
            if lacuna not in lacunas:
                lacunas.append(lacuna)
    return {**totais, "lacunas": sorted(lacunas)}


def executar_espelhamento_planilhas(session: Session | None = None, log=None) -> dict:
    """Orquestra o espelhamento das abas BD_FIIs e BD_Acoes.

    Lê o Google Sheets via services.planilhas (cache de 5min). Se ``session``
    não for informada, abre uma sessão local própria e a fecha ao final.
    """
    from services.planilhas import buscar_dados_planilha_com_cache

    sessao_propria = False
    if session is None:
        session = _criar_sessao()
        sessao_propria = True

    try:
        relatorios = []
        for nome_aba in ABAS_ESPELHAVEIS:
            matriz = buscar_dados_planilha_com_cache(nome_aba)
            if matriz is None:
                logger.warning("Espelhamento: aba %s indisponível (Google Sheets).", nome_aba)
                continue
            relatorios.append(espelhar_planilha(session, nome_aba, matriz, log=log))
        return {
            "origem": ORIGEM_GOOGLE_SHEETS,
            "abas": relatorios,
            "totais": _resumir_totais(relatorios),
        }
    finally:
        if sessao_propria:
            session.close()
