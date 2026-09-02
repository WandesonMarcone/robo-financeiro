"""Dupla escrita FIIs/Ações -> PostgreSQL — Fase 3, Bloco 5C.

O Google Sheets permanece a fonte ativa: os scrapers
(modules/scraper_fiis.py / modules/scraper_acoes.py) escrevem nas abas
BD_FIIs/BD_Acoes e este módulo apenas ESPELHA os indicadores de mercado nas
novas tabelas do Bloco 5B (``snapshots_fiis``, ``snapshots_acoes`` e
``ativos_perfil``). Não há corte Sheets -> PostgreSQL: nenhum leitor de
produção depende destas tabelas ainda e esta rotina nunca altera a planilha.

Escopo atual do Bloco 5C: FIIs (``snapshots_fiis`` + ``ativos_perfil``),
Ações (``snapshots_acoes`` + ``ativos_perfil.setor``) e Inquilinos
(``ativos_inquilinos`` a partir da coluna J do BD_FIIs).

Garantias da rotina:
- Reutiliza ``pipeline_dados.qualidade_dados`` (``validar_registro``/
  ``parsear_numero``), ``mapeamento_sheets`` (``transformar_linha_fii``/
  ``transformar_linha_acao``) e ``espelhamento_sheets`` (``espelhar_ativo``).
  NUNCA usa ``modules.utils.formatar()`` (legado transforma erro de coleta em
  0.0); número ilegível vira None (ausente) e é aceito como opcional.
- INVALID não persiste o snapshot; WARNING persiste e registra diagnóstico.
- Idempotente por ``(ativo_id, data_referencia)``: segunda execução do mesmo
  dia atualiza em vez de duplicar; data_referencia diferente cria nova linha.
- ``data_referencia`` = data da coleta em São Paulo (o Sheets não possui coluna
  de data válida; o carimbo não contém ano e não é usado como referência).
- Rastreável: ``fonte="Google Sheets"``, ``data_coleta`` preenchido e
  ``url_origem=None`` (o Sheets não transporta URL de origem; não se inventa
  esse dado).
- Inquilinos: parser 100% determinístico da coluna J (``parsear_inquilinos``),
  nenhuma IA. Participação é persistida como fração (0–1): ``"12,3%"`` vira
  ``Decimal("0.123")``; ``"0,5"`` (sem ``%``) é preservado como está (não se
  inventa escala). A participação ausente/ilegível permanece NULL e sentinelas
  ("Não informado / Não aplicável" e variações) não geram registro.
  Idempotente por ``(ativo_id, nome, data_referencia)``.
- Integração mínima de produção: ``espelhar_mercado_se_ativo`` é invocado por
  app.py DEPOIS da escrita bem-sucedida no Sheets, controlado pela flag
  ``config.ESPELHAMENTO_PG_ATIVO`` (padrão desligado — comportamento legado).
  A falha do PostgreSQL propaga para o app.py, que a registra sem desfazer o
  Sheets. Não altera banco_dados.py, scrapers, main.py nem o workflow de
  produção (B3/FNET/CVM/Telegram/Drive).
"""
import logging
import re
from datetime import date, datetime
from decimal import Decimal

import pytz
from sqlalchemy.orm import Session

import config
from pipeline_dados.banco_dados import AtivoInquilino, AtivoPerfil, SnapshotAcao, SnapshotFii, TipoAtivo
from pipeline_dados.espelhamento_sheets import (
    STATUS_ATUALIZADO,
    STATUS_CRIADO,
    STATUS_INVALIDO,
    _criar_sessao,
    espelhar_ativo,
)
from pipeline_dados.mapeamento_sheets import (
    ORIGEM_GOOGLE_SHEETS,
    transformar_linha_acao,
    transformar_linha_fii,
)
from pipeline_dados.motor_alertas import processar_indicadores_ativo
from pipeline_dados.normalizacao import normalizar_texto
from pipeline_dados.qualidade_dados import (
    INVALID,
    WARNING,
    parsear_numero,
    registrar_diagnostico,
    validar_registro,
)

logger = logging.getLogger(__name__)

ABAS_5C = ("BD_FIIs", "BD_Acoes")


def _data_referencia_sp() -> date:
    """Data da coleta no fuso oficial do projeto (America/Sao_Paulo)."""
    return datetime.now(pytz.timezone("America/Sao_Paulo")).date()


def _decimal(valor) -> Decimal | None:
    """Converte float normalizado em Decimal para as colunas NUMERIC.

    Usa ``Decimal(str(valor))`` para evitar artefatos de ponto flutuante
    binário (ex.: 9.87 -> Decimal('9.87'), nunca Decimal('9.8700000000...')).
    """
    if valor is None:
        return None
    return Decimal(str(valor))


def _qtd_imoveis(valor) -> int | None:
    """Contagem de imóveis: só persiste quando o valor é inteiro; senão None."""
    if valor is None:
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return int(numero) if numero.is_integer() else None


# ===========================================================================
# Inquilinos (coluna J do BD_FIIs) — Fase 3, Bloco 5C
# ===========================================================================

# Sentinela emitida por buscar_dados_profundos_fii (modules/scraper_fiis.py)
# quando não há lista de inquilinos. Nunca deve virar um inquilino válido.
_SENTINEL_SEM_INQUILINO = (
    "Não informado",
    "N/A",
    "N/D",
    "Não aplicável",
    "Não informado / Não aplicável",
    "Não informado/Não aplicável",
    "Sem inquilinos",
    "Não possui inquilinos",
    "-",
    "--",
    "—",
)

_SENTINEL_NORMALIZADO = frozenset(
    normalizar_texto(s).strip().lower() for s in _SENTINEL_SEM_INQUILINO
)


def _dividir_itens(texto: str) -> list[str]:
    """Divide a lista de inquilinos no separador real (vírgula) em nível 0.

    O produtor junta os itens com ``", "``, mas o percentual usa vírgula
    decimal dentro dos parênteses (ex.: ``"A (12,3%), B (8%)"``). Por isso a
    divisão ignora vírgulas dentro de parênteses, evitando quebrar o número.
    """
    itens: list[str] = []
    atual: list[str] = []
    profundidade = 0
    for char in texto:
        if char == "(":
            profundidade += 1
            atual.append(char)
        elif char == ")":
            profundidade = max(0, profundidade - 1)
            atual.append(char)
        elif char == "," and profundidade == 0:
            itens.append("".join(atual).strip())
            atual = []
        else:
            atual.append(char)
    resto = "".join(atual).strip()
    if resto:
        itens.append(resto)
    return itens


def _converter_participacao(valor) -> Decimal | None:
    """Converte a participação em Decimal (fração 0–1).

    ``"12,3%"`` -> ``Decimal("0.123")``; ``"0,5"`` (sem ``%``) -> ``Decimal("0.5")``.
    O ``%`` é representação inequívoca de percentual e é normalizado para
    fração; sem ``%`` o número é preservado como está (não se inventa escala).
    Valores ilegíveis (não numéricos) retornam None — nunca zero.
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    tem_percentual = "%" in texto
    limpo = texto.replace("%", "").replace(" ", "").strip()
    if not limpo:
        return None
    if "," in limpo and "." in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif "," in limpo:
        limpo = limpo.replace(",", ".")
    numero = parsear_numero(limpo)
    if numero is None:
        return None
    decimal_valor = Decimal(str(numero))
    if tem_percentual:
        decimal_valor = decimal_valor / Decimal("100")
    return decimal_valor


def _interpretar_item(item: str) -> tuple[str | None, Decimal | None]:
    """Interpreta um item ``"Nome (percentual)"`` de forma determinística.

    Nome sem parênteses é aceito com participação ausente (None) — segurança,
    não invenção. Nome vazio ou sem nenhum caractere alfabético é descartado.
    """
    texto = item.strip()
    if not texto:
        return None, None
    m = re.match(r"^(?P<nome>.+?)\s*\(\s*(?P<participacao>[^()]*?)\s*\)\s*$", texto)
    if m:
        nome = m.group("nome").strip()
        participacao = _converter_participacao(m.group("participacao"))
    else:
        nome = texto
        participacao = None
    if not nome or not any(c.isalpha() for c in nome):
        return None, None
    return nome, participacao


def parsear_inquilinos(valor) -> list[dict]:
    """Extrai inquilinos da coluna J do BD_FIIs, de forma determinística.

    Formato real produzido por ``buscar_dados_profundos_fii``
    (modules/scraper_fiis.py): itens separados por ``", "``, cada um no formato
    ``"Nome (percentual)"`` — ex.: ``"Magazine Luiza (12,3%), Via Varejo (8,5%)"``.
    O percentual vem do HTML do StatusInvest (pode usar vírgula ou ponto).

    Retorna lista de ``{"nome": str, "participacao": Decimal | None}``. Nome
    vazio/impossível de interpretar não gera registro e a sentinela
    "Não informado / Não aplicável" (e variações) não gera nenhum inquilino.
    """
    if valor is None:
        return []
    texto = " ".join(str(valor).split())
    if not texto:
        return []
    if normalizar_texto(texto).strip().lower() in _SENTINEL_NORMALIZADO:
        return []
    resultado = []
    for item in _dividir_itens(texto):
        nome, participacao = _interpretar_item(item)
        if nome is None:
            continue
        resultado.append({"nome": nome, "participacao": participacao})
    return resultado


def gravar_inquilinos_fii(
    session: Session,
    ativo,
    dados: dict,
    data_referencia: date,
    log=None,
) -> tuple[int, int]:
    """Espelha os inquilinos da coluna J do BD_FIIs em ``ativos_inquilinos``.

    Parser 100% determinístico (ver ``parsear_inquilinos``); nenhuma IA. Nome
    obrigatório (INVALID não persiste — o parser já filtra, esta regra é a
    rede de segurança); participação opcional (ausente permanece NULL, nunca
    vira zero). Idempotente por ``(ativo_id, nome, data_referencia)``: segunda
    execução do mesmo dia atualiza em vez de duplicar. Retorna
    ``(criados, atualizados)``.
    """
    criados = 0
    atualizados = 0
    for inquilino in parsear_inquilinos(dados.get("inquilinos")):
        participacao = inquilino["participacao"]
        resultado = validar_registro(
            {
                "nome": inquilino["nome"],
                "data_referencia": data_referencia,
                "participacao": float(participacao) if participacao is not None else None,
            },
            "inquilino_fii",
            origem=ORIGEM_GOOGLE_SHEETS,
            ativo=ativo.ticker,
            documento=str(data_referencia),
        )
        registrar_diagnostico(resultado, log)
        if resultado.status == INVALID:
            continue

        registro = (
            session.query(AtivoInquilino)
            .filter_by(
                ativo_id=ativo.id,
                nome=inquilino["nome"],
                data_referencia=data_referencia,
            )
            .first()
        )
        if registro is None:
            registro = AtivoInquilino(
                ativo_id=ativo.id,
                nome=inquilino["nome"],
                data_referencia=data_referencia,
            )
            session.add(registro)
            criados += 1
        else:
            atualizados += 1

        registro.participacao = participacao
        registro.data_coleta = datetime.now()

    return criados, atualizados


def gravar_snapshot_fii(
    session: Session,
    ativo,
    dados: dict,
    data_referencia: date,
    log=None,
):
    """Cria/atualiza um registro em ``snapshots_fiis`` de forma idempotente.

    Valida o registro com o contexto ``snapshot_fii_mercado``; INVALID não
    persiste. Retorna ``(snapshot, resultado, status)``.
    """
    resultado = validar_registro(
        {
            "ticker": dados.get("ticker"),
            "data_referencia": data_referencia,
            "preco": dados.get("preco"),
            "pvp": dados.get("pvp"),
            "dy": dados.get("dy"),
            "qtd_imoveis": dados.get("qtd_imoveis"),
            "liquidez": dados.get("liquidez"),
            "vpa": dados.get("vpa"),
            "lucro_12m": dados.get("lucro_12m"),
            "dividendo_mensal": dados.get("dividendo_mensal"),
            "walt": dados.get("walt"),
            "alavancagem": dados.get("alavancagem"),
        },
        "snapshot_fii_mercado",
        origem=ORIGEM_GOOGLE_SHEETS,
        ativo=ativo.ticker,
        documento=str(data_referencia),
    )
    registrar_diagnostico(resultado, log)
    if resultado.status == INVALID:
        return None, resultado, STATUS_INVALIDO

    snapshot = (
        session.query(SnapshotFii)
        .filter_by(ativo_id=ativo.id, data_referencia=data_referencia)
        .first()
    )
    if snapshot is None:
        snapshot = SnapshotFii(ativo_id=ativo.id, data_referencia=data_referencia)
        session.add(snapshot)
        status = STATUS_CRIADO
    else:
        status = STATUS_ATUALIZADO

    snapshot.data_coleta = datetime.now()
    snapshot.fonte = ORIGEM_GOOGLE_SHEETS
    snapshot.preco = _decimal(dados.get("preco"))
    snapshot.pvp = _decimal(dados.get("pvp"))
    snapshot.dy = _decimal(dados.get("dy"))
    snapshot.liquidez = _decimal(dados.get("liquidez"))
    snapshot.vpa = _decimal(dados.get("vpa"))
    snapshot.lucro_12m = _decimal(dados.get("lucro_12m"))
    snapshot.dividendo_mensal = _decimal(dados.get("dividendo_mensal"))
    snapshot.walt = dados.get("walt")
    snapshot.alavancagem = dados.get("alavancagem")
    snapshot.qtd_imoveis = _qtd_imoveis(dados.get("qtd_imoveis"))

    return snapshot, resultado, status


def _gravar_perfil(session: Session, ativo, setor=None, tipo_fii=None, log=None):
    """Cria/atualiza o perfil 1:1 do ativo em ``ativos_perfil``.

    Campos de classificação (``setor``/``tipo_fii``) só são gravados quando
    presentes; valores vazios nunca apagam os existentes. Retorna
    ``(perfil, status)``.
    """
    perfil = session.query(AtivoPerfil).filter_by(ativo_id=ativo.id).first()
    if perfil is None:
        perfil = AtivoPerfil(ativo_id=ativo.id)
        session.add(perfil)
        status = STATUS_CRIADO
    else:
        status = STATUS_ATUALIZADO

    if setor:
        perfil.setor = setor
    if tipo_fii:
        perfil.tipo_fii = tipo_fii
    perfil.data_atualizacao = datetime.now()

    return perfil, status


def gravar_perfil_fii(session: Session, ativo, dados: dict, log=None):
    """Cria/atualiza o perfil 1:1 do FII (setor + tipo_fii)."""
    return _gravar_perfil(
        session,
        ativo,
        setor=dados.get("setor"),
        tipo_fii=dados.get("tipo_fii"),
        log=log,
    )


def gravar_perfil_acao(session: Session, ativo, dados: dict, log=None):
    """Cria/atualiza o perfil 1:1 da ação (apenas ``setor``)."""
    return _gravar_perfil(session, ativo, setor=dados.get("setor"), log=log)


def _relatorio_vazio(aba: str, data_referencia: date) -> dict:
    return {
        "aba": aba,
        "origem": ORIGEM_GOOGLE_SHEETS,
        "data_referencia": str(data_referencia),
        "linhas": 0,
        "criados": 0,
        "atualizados": 0,
        "invalidos": 0,
        "warnings": 0,
        "perfis_criados": 0,
        "perfis_atualizados": 0,
        "inquilinos_criados": 0,
        "inquilinos_atualizados": 0,
        "alertas": 0,
        "tickers": [],
    }


def _espelhar_matriz_fiis(session: Session, matriz, data_referencia: date, log=None) -> dict:
    relatorio = _relatorio_vazio("BD_FIIs", data_referencia)
    if not matriz or len(matriz) < 2:
        return relatorio

    for linha in matriz[1:]:
        if not linha or not str(linha[0]).strip():
            continue
        dados = transformar_linha_fii(linha)
        relatorio["linhas"] += 1

        ativo, _, status_ativo = espelhar_ativo(
            session, dados["ticker"], TipoAtivo.FII, log=log
        )
        if ativo is None or status_ativo == STATUS_INVALIDO:
            relatorio["invalidos"] += 1
            continue

        criados_inquilinos, atualizados_inquilinos = gravar_inquilinos_fii(
            session, ativo, dados, data_referencia, log=log
        )
        relatorio["inquilinos_criados"] += criados_inquilinos
        relatorio["inquilinos_atualizados"] += atualizados_inquilinos

        _, resultado, status = gravar_snapshot_fii(
            session, ativo, dados, data_referencia, log=log
        )
        if status == STATUS_INVALIDO:
            relatorio["invalidos"] += 1
            continue
        if status == STATUS_CRIADO:
            relatorio["criados"] += 1
        else:
            relatorio["atualizados"] += 1
        if resultado.status == WARNING:
            relatorio["warnings"] += 1

        try:
            alertas = processar_indicadores_ativo(
                session, ativo, dados, "FII",
                data_referencia=data_referencia, origem=ORIGEM_GOOGLE_SHEETS,
                log=log,
            )
            relatorio["alertas"] += len(alertas)
        except Exception as e:
            (log or logger).warning(
                "FASE4 espelhamento FIIs ativo=%s falhou sem impedir o fluxo 5C: %s",
                dados["ticker"], e,
            )

        _, status_perfil = gravar_perfil_fii(session, ativo, dados, log=log)
        if status_perfil == STATUS_CRIADO:
            relatorio["perfis_criados"] += 1
        else:
            relatorio["perfis_atualizados"] += 1

        if dados["ticker"]:
            relatorio["tickers"].append(dados["ticker"])

    return relatorio


def espelhar_mercado_fiis(
    session: Session | None = None,
    matriz: list | None = None,
    data_referencia: date | None = None,
    log=None,
) -> dict:
    """Espelha os indicadores de mercado dos FIIs do Sheets para o PostgreSQL.

    ``matriz`` = get_all_values() da aba BD_FIIs (1ª linha = cabeçalho). Quando
    não informada, busca via ``services.planilhas`` (cache de 5min). Se a
    planilha estiver indisponível, retorna relatório vazio (o caminho legado do
    Sheets não é afetado). Se ``session`` não for informada, abre e fecha uma
    sessão local própria (padrão de espelhamento_sheets).
    """
    if data_referencia is None:
        data_referencia = _data_referencia_sp()
    if matriz is None:
        from services.planilhas import buscar_dados_planilha_com_cache

        matriz = buscar_dados_planilha_com_cache("BD_FIIs")
    if not matriz or len(matriz) < 2:
        return _relatorio_vazio("BD_FIIs", data_referencia)

    sessao_propria = False
    if session is None:
        session = _criar_sessao()
        sessao_propria = True

    try:
        relatorio = _espelhar_matriz_fiis(session, matriz, data_referencia, log=log)
        session.commit()
        return relatorio
    finally:
        if sessao_propria:
            session.close()


def gravar_snapshot_acao(
    session: Session,
    ativo,
    dados: dict,
    data_referencia: date,
    log=None,
):
    """Cria/atualiza um registro em ``snapshots_acoes`` de forma idempotente.

    Valida o registro com o contexto ``snapshot_acao_mercado``; INVALID não
    persiste. A coluna de origem ``div_liq_ebit`` do Sheets é, na prática,
    preenchida com Dív.Líq/Patrimônio (duplicação da origem — ver mapeamento);
    por isso o valor é persistido apenas em ``div_liq_patrimonio`` e
    ``div_liq_ebit`` permanece NULL (não se inventa significado). Retorna
    ``(snapshot, resultado, status)``.
    """
    resultado = validar_registro(
        {
            "ticker": dados.get("ticker"),
            "data_referencia": data_referencia,
            "preco": dados.get("preco"),
            "dy": dados.get("dy"),
            "pl": dados.get("pl"),
            "pvp": dados.get("pvp"),
            "p_ativo": dados.get("p_ativo"),
            "marg_bruta": dados.get("marg_bruta"),
            "marg_ebit": dados.get("marg_ebit"),
            "marg_liquida": dados.get("marg_liquida"),
            "p_ebit": dados.get("p_ebit"),
            "ev_ebit": dados.get("ev_ebit"),
            "div_liq_patrimonio": dados.get("div_liq_patrimonio"),
            "psr": dados.get("psr"),
            "p_cap_giro": dados.get("p_cap_giro"),
            "p_at_circ_liq": dados.get("p_at_circ_liq"),
            "liq_corrente": dados.get("liq_corrente"),
            "roe": dados.get("roe"),
            "roa": dados.get("roa"),
            "roic": dados.get("roic"),
            "cagr_rec_5a": dados.get("cagr_rec_5a"),
            "liq_media": dados.get("liq_media"),
            "vpa": dados.get("vpa"),
            "lpa": dados.get("lpa"),
            "peg_ratio": dados.get("peg_ratio"),
            "valor_mercado": dados.get("valor_mercado"),
        },
        "snapshot_acao_mercado",
        origem=ORIGEM_GOOGLE_SHEETS,
        ativo=ativo.ticker,
        documento=str(data_referencia),
    )
    registrar_diagnostico(resultado, log)
    if resultado.status == INVALID:
        return None, resultado, STATUS_INVALIDO

    snapshot = (
        session.query(SnapshotAcao)
        .filter_by(ativo_id=ativo.id, data_referencia=data_referencia)
        .first()
    )
    if snapshot is None:
        snapshot = SnapshotAcao(ativo_id=ativo.id, data_referencia=data_referencia)
        session.add(snapshot)
        status = STATUS_CRIADO
    else:
        status = STATUS_ATUALIZADO

    snapshot.data_coleta = datetime.now()
    snapshot.fonte = ORIGEM_GOOGLE_SHEETS
    snapshot.preco = _decimal(dados.get("preco"))
    snapshot.dy = _decimal(dados.get("dy"))
    snapshot.pl = _decimal(dados.get("pl"))
    snapshot.pvp = _decimal(dados.get("pvp"))
    snapshot.p_ativo = _decimal(dados.get("p_ativo"))
    snapshot.marg_bruta = _decimal(dados.get("marg_bruta"))
    snapshot.marg_ebit = _decimal(dados.get("marg_ebit"))
    snapshot.marg_liquida = _decimal(dados.get("marg_liquida"))
    snapshot.p_ebit = _decimal(dados.get("p_ebit"))
    snapshot.ev_ebit = _decimal(dados.get("ev_ebit"))
    snapshot.div_liq_patrimonio = _decimal(dados.get("div_liq_patrimonio"))
    snapshot.psr = _decimal(dados.get("psr"))
    snapshot.p_cap_giro = _decimal(dados.get("p_cap_giro"))
    snapshot.p_at_circ_liq = _decimal(dados.get("p_at_circ_liq"))
    snapshot.liq_corrente = _decimal(dados.get("liq_corrente"))
    snapshot.roe = _decimal(dados.get("roe"))
    snapshot.roa = _decimal(dados.get("roa"))
    snapshot.roic = _decimal(dados.get("roic"))
    snapshot.cagr_rec_5a = _decimal(dados.get("cagr_rec_5a"))
    snapshot.liq_media = _decimal(dados.get("liq_media"))
    snapshot.vpa = _decimal(dados.get("vpa"))
    snapshot.lpa = _decimal(dados.get("lpa"))
    snapshot.peg_ratio = _decimal(dados.get("peg_ratio"))
    snapshot.valor_mercado = _decimal(dados.get("valor_mercado"))

    return snapshot, resultado, status


def _espelhar_matriz_acoes(session: Session, matriz, data_referencia: date, log=None) -> dict:
    relatorio = _relatorio_vazio("BD_Acoes", data_referencia)
    if not matriz or len(matriz) < 2:
        return relatorio

    for linha in matriz[1:]:
        if not linha or not str(linha[0]).strip():
            continue
        dados = transformar_linha_acao(linha)
        relatorio["linhas"] += 1

        ativo, _, status_ativo = espelhar_ativo(
            session, dados["ticker"], TipoAtivo.ACAO, log=log
        )
        if ativo is None or status_ativo == STATUS_INVALIDO:
            relatorio["invalidos"] += 1
            continue

        _, resultado, status = gravar_snapshot_acao(
            session, ativo, dados, data_referencia, log=log
        )
        if status == STATUS_INVALIDO:
            relatorio["invalidos"] += 1
            continue
        if status == STATUS_CRIADO:
            relatorio["criados"] += 1
        else:
            relatorio["atualizados"] += 1
        if resultado.status == WARNING:
            relatorio["warnings"] += 1

        try:
            alertas = processar_indicadores_ativo(
                session, ativo, dados, "ACAO",
                data_referencia=data_referencia, origem=ORIGEM_GOOGLE_SHEETS,
                log=log,
            )
            relatorio["alertas"] += len(alertas)
        except Exception as e:
            (log or logger).warning(
                "FASE4 espelhamento Ações ativo=%s falhou sem impedir o fluxo 5C: %s",
                dados["ticker"], e,
            )

        _, status_perfil = gravar_perfil_acao(session, ativo, dados, log=log)
        if status_perfil == STATUS_CRIADO:
            relatorio["perfis_criados"] += 1
        else:
            relatorio["perfis_atualizados"] += 1

        if dados["ticker"]:
            relatorio["tickers"].append(dados["ticker"])

    return relatorio


def espelhar_mercado_acoes(
    session: Session | None = None,
    matriz: list | None = None,
    data_referencia: date | None = None,
    log=None,
) -> dict:
    """Espelha os indicadores de mercado das ações do Sheets para o PostgreSQL.

    ``matriz`` = get_all_values() da aba BD_Acoes (1ª linha = cabeçalho). Quando
    não informada, busca via ``services.planilhas`` (cache de 5min). Se a
    planilha estiver indisponível, retorna relatório vazio (o caminho legado do
    Sheets não é afetado). Se ``session`` não for informada, abre e fecha uma
    sessão local própria (padrão de espelhamento_sheets).
    """
    if data_referencia is None:
        data_referencia = _data_referencia_sp()
    if matriz is None:
        from services.planilhas import buscar_dados_planilha_com_cache

        matriz = buscar_dados_planilha_com_cache("BD_Acoes")
    if not matriz or len(matriz) < 2:
        return _relatorio_vazio("BD_Acoes", data_referencia)

    sessao_propria = False
    if session is None:
        session = _criar_sessao()
        sessao_propria = True

    try:
        relatorio = _espelhar_matriz_acoes(session, matriz, data_referencia, log=log)
        session.commit()
        return relatorio
    finally:
        if sessao_propria:
            session.close()


def _logar_resumo(aba: str, relatorio: dict, data_ref: date) -> None:
    """Registra em log o resumo observável de um espelhamento de aba."""
    logger.info(
        "Espelhamento %s (data=%s): linhas=%s snapshots_criados=%s "
        "snapshots_atualizados=%s invalidos=%s warnings=%s perfis_criados=%s "
        "perfis_atualizados=%s inquilinos_criados=%s inquilinos_atualizados=%s",
        aba,
        data_ref,
        relatorio["linhas"],
        relatorio["criados"],
        relatorio["atualizados"],
        relatorio["invalidos"],
        relatorio["warnings"],
        relatorio["perfis_criados"],
        relatorio["perfis_atualizados"],
        relatorio["inquilinos_criados"],
        relatorio["inquilinos_atualizados"],
    )


def espelhar_mercado_se_ativo(
    matriz_fiis: list | None = None,
    matriz_acoes: list | None = None,
    session: Session | None = None,
    log=None,
) -> dict | None:
    """Executa o espelhamento 5C quando habilitado via ``config.ESPELHAMENTO_PG_ATIVO``.

    Google Sheets permanece a fonte ativa: esta rotina roda DEPOIS da escrita
    no Sheets (app.py) e nunca a substitui. Quando desabilitada retorna ``None``
    (comportamento legado, somente Sheets). Quando habilitada, espelha FIIs
    (``snapshots_fiis`` + ``ativos_perfil`` + ``ativos_inquilinos``) e Ações
    (``snapshots_acoes`` + ``ativos_perfil``), registrando um resumo observável
    (linhas, snapshots criados/atualizados, inválidos, warnings e inquilinos).

    ``matriz_fiis``/``matriz_acoes`` são as matrizes recém-atualizadas pelo
    fluxo do Sheets (quando None, busca via cache de services.planilhas). Uma
    falha do PostgreSQL NÃO é mascarada aqui: ela propaga para o chamador
    (app.py), que garante que o Sheets já gravado não é afetado.
    """
    if not config.ESPELHAMENTO_PG_ATIVO:
        logger.info("Espelhamento PostgreSQL desabilitado (ESPELHAMENTO_PG_ATIVO=false).")
        return None

    data_ref = _data_referencia_sp()
    relatorio_fiis = espelhar_mercado_fiis(session=session, matriz=matriz_fiis, log=log)
    _logar_resumo("BD_FIIs", relatorio_fiis, data_ref)
    relatorio_acoes = espelhar_mercado_acoes(session=session, matriz=matriz_acoes, log=log)
    _logar_resumo("BD_Acoes", relatorio_acoes, data_ref)
    logger.info("Espelhamento 5C concluído com sucesso (data_referencia=%s).", data_ref)

    return {
        "origem": ORIGEM_GOOGLE_SHEETS,
        "data_referencia": str(data_ref),
        "fiis": relatorio_fiis,
        "acoes": relatorio_acoes,
    }
