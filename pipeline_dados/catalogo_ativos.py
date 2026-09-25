"""Catálogo central de ativos — Fase 7, Etapa 7.2 (aditivo).

Camada única de consulta/seed do catálogo financeiro no PostgreSQL. O
PostgreSQL passa progressivamente a ser a fonte ativa do catálogo; o Google
Sheets permanece como fallback/legado para os consumidores ainda dependentes
da planilha (o fallback fica explícito em ``obter_tickers_com_fallback``).

Fontes de seed (sem inventar identificadores):
- ``config.MAPA_CNPJ_B3``      -> ACAO  (ticker, cnpj, setor via MAPA_SETORES_B3)
- ``config.MAPA_ISCAS_MASTER`` -> FII   (ticker, nome_emissor; cnpj NULL)

Nenhum dado existente é alterado: a tabela ``ativos_catalogo`` é nova e o
seed é idempotente (insert-only por ticker).
"""

import logging
import re

import config
from pipeline_dados.banco_dados import Ativo, AtivoCatalogo, TipoAtivo
from pipeline_dados.normalizacao import formatar_cnpj, normalizar_cnpj, normalizar_texto

logger = logging.getLogger(__name__)

# Origem dos registros semeado a partir dos mapas de config.py.
FONTE_CONFIG = "config"

# Sentinel interno: sem classificação econômica confiável. Não é setor B3.
SETOR_NAO_CLASSIFICADO = "NAO_CLASSIFICADO"

_TIPOS_VALIDOS = {t.value for t in TipoAtivo}

# Rótulos legados/ausentes que nunca contam como setor econômico confiável.
_SETORES_NAO_CONFIAVEIS = frozenset({
    "",
    "OUTROS",
    "NAO CLASSIFICADO",
    "NAO_CLASSIFICADO",
    "AUSENTE",
    "N/D",
    "ND",
    "N/A",
    "NA",
})

# Mapa reverso ticker -> CNPJ (ACAO) usado como fallback offline do seed.
_TICKER_PARA_CNPJ = {ticker.upper(): cnpj for cnpj, ticker in config.MAPA_CNPJ_B3.items()}


def _normalizar_tipo(tipo) -> str | None:
    """Normaliza o tipo para a string do catálogo (ACAO/FII/ETF/CRIPTO)."""
    if isinstance(tipo, TipoAtivo):
        return tipo.value
    if tipo is None:
        return None
    texto = str(tipo).strip().upper()
    return texto if texto in _TIPOS_VALIDOS else None


def _cnpj_normalizado(cnpj) -> str | None:
    """CNPJ no formato XX.XXX.XXX/XXXX-XX; None quando não tem 14 dígitos."""
    if normalizar_cnpj(cnpj) is None:
        return None
    return formatar_cnpj(cnpj)


def _chave_setor(setor) -> str | None:
    """Chave comparável (maiúsculas, sem acento) ou None se vazio."""
    if setor is None:
        return None
    texto = str(setor).strip()
    if not texto:
        return None
    return " ".join(normalizar_texto(texto).upper().replace("_", " ").replace("-", " ").split())


def _rotulo_nao_confiavel(setor) -> bool:
    """True para None/vazio/Outros/Não Classificado/NAO_CLASSIFICADO/AUSENTE."""
    chave = _chave_setor(setor)
    if chave is None:
        return True
    compacto = chave.replace(" ", "_")
    return chave in _SETORES_NAO_CONFIAVEIS or compacto in _SETORES_NAO_CONFIAVEIS


def _taxonomia_b3() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Reutiliza config.MAPA_SETORES_B3. Não cria taxonomia paralela.

    Retorna (ticker->macro, subsetor->macro, macros presentes).
    """
    ticker_para_macro = {}
    subsetor_para_macro = {}
    macros = {}
    for macro, subsetores in config.MAPA_SETORES_B3.items():
        macros[macro] = macro
        for subsetor, tickers in subsetores.items():
            subsetor_para_macro[subsetor] = macro
            for ticker in tickers:
                ticker_para_macro[str(ticker).strip().upper()] = macro
    return ticker_para_macro, subsetor_para_macro, macros


def setor_confiavel(setor) -> bool:
    """True só se o rótulo for um macro/subsetor real de MAPA_SETORES_B3."""
    if _rotulo_nao_confiavel(setor):
        return False
    texto = str(setor).strip()
    _ticker_para_macro, subsetor_para_macro, macros = _taxonomia_b3()
    return texto in macros or texto in subsetor_para_macro


def setor_canonico(setor) -> str | None:
    """Macro B3 correspondente, ou None se o rótulo não for confiável."""
    if not setor_confiavel(setor):
        return None
    texto = str(setor).strip()
    _ticker_para_macro, subsetor_para_macro, macros = _taxonomia_b3()
    if texto in macros:
        return texto
    return subsetor_para_macro.get(texto)


def classificar_setor_catalogo(ticker) -> str:
    """Macro confiável do mapa B3, senão NAO_CLASSIFICADO. Não inventa setor."""
    if not ticker:
        return SETOR_NAO_CLASSIFICADO
    ticker_norm = str(ticker).strip().upper()
    ticker_para_macro, _subsetor_para_macro, _macros = _taxonomia_b3()
    return ticker_para_macro.get(ticker_norm, SETOR_NAO_CLASSIFICADO)


def inventario_mapa_setores_b3() -> dict:
    """Contagens da taxonomia existente em config.MAPA_SETORES_B3."""
    ticker_para_macro, subsetor_para_macro, macros = _taxonomia_b3()
    return {
        "macrosetores": len(macros),
        "subsetores": len(subsetor_para_macro),
        "tickers": len(ticker_para_macro),
    }


def _resolver_setor_catalogo(existente, setor_informado, ticker, tipo) -> str | None:
    """Aplica a regra de persistência de setor no catálogo.

    Confiável informado substitui. Ausência/Outros nunca apaga setor confiável.
    Ação nova ou sem setor confiável usa o mapa B3 automaticamente.
    """
    informado_canonico = setor_canonico(setor_informado)
    if informado_canonico is not None:
        return informado_canonico

    informado_ausente = _rotulo_nao_confiavel(setor_informado)

    if tipo == TipoAtivo.ACAO.value:
        if setor_confiavel(existente):
            return existente
        automatico = classificar_setor_catalogo(ticker)
        if setor_confiavel(automatico):
            return automatico
        return SETOR_NAO_CLASSIFICADO

    if not informado_ausente:
        return str(setor_informado).strip()
    if not _rotulo_nao_confiavel(existente):
        return existente
    if existente is not None and str(existente).strip() == SETOR_NAO_CLASSIFICADO:
        return SETOR_NAO_CLASSIFICADO
    return None


def _setor_por_ticker() -> dict[str, str]:
    """Mapa reverso ticker -> setor macro a partir de config.MAPA_SETORES_B3."""
    ticker_para_macro, _subsetor_para_macro, _macros = _taxonomia_b3()
    return ticker_para_macro


def _entradas_acao() -> list[dict]:
    """Entradas ACAO do catálogo derivadas de config.MAPA_CNPJ_B3."""
    setor_por_ticker = _setor_por_ticker()
    entradas = []
    for cnpj, ticker in config.MAPA_CNPJ_B3.items():
        ticker_norm = str(ticker).strip().upper()
        entradas.append({
            "ticker": ticker_norm,
            "tipo": TipoAtivo.ACAO.value,
            "cnpj": _cnpj_normalizado(cnpj),
            "nome_emissor": None,
            "setor": setor_por_ticker.get(ticker_norm) or SETOR_NAO_CLASSIFICADO,
            "fonte": FONTE_CONFIG,
        })
    return entradas


def _entradas_fii() -> list[dict]:
    """Entradas FII do catálogo derivadas de config.MAPA_ISCAS_MASTER."""
    entradas = []
    for ticker, nome in config.MAPA_ISCAS_MASTER.items():
        entradas.append({
            "ticker": str(ticker).strip().upper(),
            "tipo": TipoAtivo.FII.value,
            "cnpj": None,
            "nome_emissor": nome,
            "setor": None,
            "fonte": FONTE_CONFIG,
        })
    return entradas


def _inserir_se_ausente(session, entrada: dict) -> int:
    """Insere um registro de catálogo somente se o ticker ainda não existir."""
    existente = (
        session.query(AtivoCatalogo)
        .filter(AtivoCatalogo.ticker == entrada["ticker"])
        .first()
    )
    if existente is not None:
        return 0
    session.add(AtivoCatalogo(**entrada))
    return 1


def seed_catalogo(session) -> int:
    """Seed idempotente do catálogo a partir de config.

    Cria apenas os tickers ainda ausentes (chave de identidade: ticker).
    Nunca sobrescreve, apaga ou altera registros existentes. Retorna a
    quantidade de registros criados.
    """
    criados = 0
    for entrada in _entradas_acao():
        criados += _inserir_se_ausente(session, entrada)
    for entrada in _entradas_fii():
        criados += _inserir_se_ausente(session, entrada)
    session.commit()
    if criados:
        logger.info("Catálogo de ativos semeado: %s registros criados.", criados)
    return criados


def _garantir_catalogo_semeado(session) -> None:
    """Semeia o catálogo uma única vez (quando a tabela está vazia)."""
    if session.query(AtivoCatalogo).first() is None:
        seed_catalogo(session)


def registrar_no_catalogo(
    session,
    ticker,
    tipo,
    cnpj=None,
    nome_emissor=None,
    setor=None,
    fonte=None,
) -> AtivoCatalogo:
    """Registra/atualiza um ativo no catálogo (idempotente por ticker).

    ``cnpj`` é armazenado apenas quando tem 14 dígitos; caso contrário vira
    NULL (nunca se inventa identificador).

    ``setor`` de ação usa ``MAPA_SETORES_B3`` quando confiável. None/vazio/
    ``Outros``/``Não Classificado`` nunca sobrescrevem um setor econômico
    existente; sem classificação o catálogo grava ``NAO_CLASSIFICADO``.
    """
    ticker_norm = str(ticker).strip().upper()
    tipo_norm = _normalizar_tipo(tipo)
    if not ticker_norm or tipo_norm is None:
        raise ValueError(f"ticker/tipo inválidos para o catálogo: {ticker!r}, {tipo!r}")

    registro = consultar_por_ticker(session, ticker_norm)
    if registro is None:
        registro = AtivoCatalogo(ticker=ticker_norm, tipo=tipo_norm)
        session.add(registro)
    registro.tipo = tipo_norm
    registro.cnpj = cnpj_real(cnpj)
    registro.nome_emissor = nome_emissor
    registro.setor = _resolver_setor_catalogo(registro.setor, setor, ticker_norm, tipo_norm)
    if fonte is not None:
        registro.fonte = fonte
    session.commit()
    return registro


def consultar_por_ticker(session, ticker) -> AtivoCatalogo | None:
    """Registro do catálogo por ticker (normalizado para maiúsculas)."""
    if not ticker:
        return None
    return (
        session.query(AtivoCatalogo)
        .filter(AtivoCatalogo.ticker == str(ticker).strip().upper())
        .first()
    )


def consultar_por_cnpj(session, cnpj) -> AtivoCatalogo | None:
    """Registro do catálogo por CNPJ (qualquer máscara de 14 dígitos)."""
    digitos = normalizar_cnpj(cnpj)
    if digitos is None:
        return None
    return (
        session.query(AtivoCatalogo)
        .filter(AtivoCatalogo.cnpj == formatar_cnpj(digitos))
        .first()
    )


_PREFIXOS_FAMILIA = frozenset({
    "XP",
    "KINEA",
    "BTG",
    "BTG PACTUAL",
    "VINCI",
    "VBI",
    "HEDGE",
    "SUNO",
    "CSHG",
    "HSI",
    "RBR",
    "REC",
})

_TICKER_TOKEN = re.compile(r"^[A-Z]{4}\d{1,2}$")


def cnpj_real(cnpj) -> str | None:
    """CNPJ canônico (14 dígitos formatados) ou None. Nunca inventa valor."""
    if cnpj is None:
        return None
    texto = str(cnpj).strip()
    if not texto:
        return None
    if texto.upper().startswith("PENDENTE-"):
        return None
    if _TICKER_TOKEN.match(texto.upper()):
        return None
    return _cnpj_normalizado(texto)


def resolver_cnpj(session, ticker, tipo=None) -> str | None:
    """CNPJ do ativo: catálogo PostgreSQL primeiro; config como fallback.

    Retorna ``None`` quando o CNPJ não é conhecido — nunca inventa CNPJ nem
    devolve placeholder.
    """
    registro = consultar_por_ticker(session, ticker)
    if registro is not None:
        return cnpj_real(registro.cnpj)
    if tipo is None or _normalizar_tipo(tipo) == TipoAtivo.ACAO.value:
        return _cnpj_normalizado(_TICKER_PARA_CNPJ.get(str(ticker).strip().upper()))
    return None


def _nome_catalogo_normalizado(nome) -> str:
    """Nome de fundo para casamento: acentos, pontuação e espaços colapsados."""
    texto = normalizar_texto(nome).strip().upper()
    if not texto:
        return ""
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _isca_casa_nome(isca_norm: str, nome_norm: str) -> bool:
    """True se a isca casa o nome sem substring solta (famílias XP/Kinea/BTG)."""
    if not isca_norm or not nome_norm:
        return False
    if isca_norm in _PREFIXOS_FAMILIA:
        return False
    if isca_norm == nome_norm:
        return True
    padrao = r"(?:^|\s)" + re.escape(isca_norm) + r"(?:\s|$)"
    return re.search(padrao, nome_norm) is not None


def _iscas_fii():
    """Iscas de FII ordenadas da mais específica para a mais genérica."""
    pares = []
    for ticker, isca in config.MAPA_ISCAS_MASTER.items():
        isca_norm = _nome_catalogo_normalizado(isca)
        if isca_norm:
            pares.append((isca_norm, str(ticker).strip().upper()))
    pares.sort(key=lambda item: (-len(item[0]), item[1]))
    return pares


def consultar_por_nome_fii(session, nome) -> AtivoCatalogo | None:
    """FII do catálogo pelo nome normalizado; None se vazio, 0 ou 2+ colisões."""
    nome_norm = _nome_catalogo_normalizado(nome)
    if not nome_norm:
        return None
    _garantir_catalogo_semeado(session)
    fiis = (
        session.query(AtivoCatalogo)
        .filter(AtivoCatalogo.tipo == TipoAtivo.FII.value)
        .all()
    )
    candidatos = []
    for registro in fiis:
        isca_norm = _nome_catalogo_normalizado(registro.nome_emissor)
        if _isca_casa_nome(isca_norm, nome_norm):
            candidatos.append(registro)
    if len(candidatos) == 1:
        return candidatos[0]
    return None


def ticker_por_nome_fii(nome, session=None) -> str | None:
    """Ticker FII pelo nome: catálogo (se houver sessão) senão MAPA_ISCAS_MASTER.

    Último recurso, com validação de colisão. Substring solta é rejeitada.
    """
    nome_norm = _nome_catalogo_normalizado(nome)
    if not nome_norm:
        return None
    if session is not None:
        registro = consultar_por_nome_fii(session, nome)
        if registro is not None:
            return registro.ticker
        return None
    candidatos = []
    for isca_norm, ticker in _iscas_fii():
        if _isca_casa_nome(isca_norm, nome_norm):
            candidatos.append(ticker)
    if len(candidatos) == 1:
        return candidatos[0]
    return None


def _tickers_fii_conhecidos(session=None) -> set[str]:
    """Tickers FII do catálogo (sessão) ou do mapa de config."""
    if session is not None:
        try:
            return {t.upper() for t in listar_tickers_catalogo(session, TipoAtivo.FII)}
        except Exception:
            logger.exception("Falha ao listar tickers FII do catálogo.")
    return {str(t).strip().upper() for t in config.MAPA_ISCAS_MASTER}


def ticker_token_em_nome(nome, session=None) -> str | None:
    """Ticker FII presente como token no nome; None se ausente ou ambíguo."""
    nome_norm = _nome_catalogo_normalizado(nome)
    if not nome_norm:
        return None
    conhecidos = _tickers_fii_conhecidos(session)
    if not conhecidos:
        return None
    encontrados = []
    for token in nome_norm.split():
        if _TICKER_TOKEN.match(token) and token in conhecidos and token not in encontrados:
            encontrados.append(token)
    if len(encontrados) == 1:
        return encontrados[0]
    return None


def resolver_ticker_fii(session, ticker=None, cnpj=None, nome=None) -> str | None:
    """Identidade operacional do FII: CNPJ, depois ticker, nome único por último."""
    cnpj_canonico = cnpj_real(cnpj)
    if cnpj_canonico:
        catalogo = consultar_por_cnpj(session, cnpj_canonico) if session is not None else None
        if catalogo is not None:
            return catalogo.ticker
        if session is not None:
            chaves_cnpj = [cnpj_canonico]
            digitos = normalizar_cnpj(cnpj_canonico)
            if digitos and digitos not in chaves_cnpj:
                chaves_cnpj.append(digitos)
            ativo = session.query(Ativo).filter(Ativo.cnpj.in_(chaves_cnpj)).first()
            if ativo is not None:
                return ativo.ticker
    if ticker:
        ticker_limpo = str(ticker).strip().upper()
        if ticker_limpo:
            return ticker_limpo
    if nome:
        ticker_nome = ticker_token_em_nome(nome, session)
        if ticker_nome:
            return ticker_nome
        return ticker_por_nome_fii(nome, session=session)
    return None


def identificar_ativo_fii(session, ticker=None, cnpj=None, nome=None) -> Ativo | None:
    """Resolve FII já persistido: CNPJ oficial, depois ticker, nome por último."""
    cnpj_canonico = cnpj_real(cnpj)
    if cnpj_canonico:
        chaves_cnpj = [cnpj_canonico]
        digitos = normalizar_cnpj(cnpj_canonico)
        if digitos and digitos not in chaves_cnpj:
            chaves_cnpj.append(digitos)
        ativo = session.query(Ativo).filter(Ativo.cnpj.in_(chaves_cnpj)).first()
        if ativo is not None:
            return ativo
        catalogo = consultar_por_cnpj(session, cnpj_canonico)
        if catalogo is not None:
            ativo = session.query(Ativo).filter(Ativo.ticker == catalogo.ticker).first()
            if ativo is not None:
                if cnpj_real(ativo.cnpj) is None:
                    ativo.cnpj = cnpj_canonico
                return ativo
    ticker_resolvido = resolver_ticker_fii(session, ticker=ticker, cnpj=None, nome=nome)
    if ticker_resolvido:
        ativo = session.query(Ativo).filter(Ativo.ticker == ticker_resolvido).first()
        if ativo is not None:
            if cnpj_canonico and cnpj_real(ativo.cnpj) is None:
                ativo.cnpj = cnpj_canonico
            return ativo
    return None


def garantir_ativo(session, ticker, tipo, cnpj=None) -> Ativo:
    """Garante ``Ativo`` por ticker. CNPJ só entra se for real; senão NULL."""
    ticker_limpo = str(ticker).strip().upper()
    tipo_norm = _normalizar_tipo(tipo)
    if not ticker_limpo or tipo_norm is None:
        raise ValueError(f"ticker/tipo inválidos: {ticker!r}, {tipo!r}")
    tipo_enum = TipoAtivo(tipo_norm)
    cnpj_canonico = cnpj_real(cnpj)
    if cnpj_canonico is None:
        cnpj_canonico = resolver_cnpj(session, ticker_limpo, tipo_enum)
    ativo = session.query(Ativo).filter(Ativo.ticker == ticker_limpo).first()
    if ativo is None:
        ativo = Ativo(ticker=ticker_limpo, cnpj=cnpj_canonico, tipo=tipo_enum)
        session.add(ativo)
        session.flush()
        return ativo
    if cnpj_real(ativo.cnpj) is None:
        ativo.cnpj = cnpj_canonico
    return ativo


def listar_tickers_catalogo(session, tipo) -> list[str]:
    """Tickers do catálogo PostgreSQL para um tipo (semeado idempotente).

    Vazio quando o catálogo ainda não possui o tipo solicitado.
    """
    tipo_norm = _normalizar_tipo(tipo)
    if tipo_norm is None:
        return []
    _garantir_catalogo_semeado(session)
    linhas = (
        session.query(AtivoCatalogo.ticker)
        .filter(AtivoCatalogo.tipo == tipo_norm)
        .all()
    )
    return sorted({linha[0] for linha in linhas})


def obter_tickers_com_fallback(session, tipo, fallback) -> list[str]:
    """Tickers do catálogo PostgreSQL; se vazio/indisponível, chama ``fallback``.

    ``fallback`` é um callable sem argumentos retornando ``list[str]`` (ex.:
    leitura da aba do Google Sheets). Centraliza a estratégia "catálogo
    primeiro, Sheets como fallback" para os consumidores: qualquer falha do
    catálogo (banco indisponível, seed com erro) também cai no fallback, para
    nunca bloquear o fluxo legado.
    """
    try:
        tickers = listar_tickers_catalogo(session, tipo)
    except Exception:
        logger.exception(
            "Catálogo PostgreSQL indisponível para tipo %s; usando fallback.",
            tipo,
        )
        tickers = []
    if tickers:
        return tickers
    if callable(fallback):
        return fallback()
    return []
