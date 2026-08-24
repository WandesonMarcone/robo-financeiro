"""Mapeamento Google Sheets -> PostgreSQL — Fase 3, Bloco 4.

Responsabilidade única: documentar e transformar as colunas das abas
BD_FIIs/BD_Acoes do Google Sheets, classificando cada campo segundo seu
destino no ORM existente (pipeline_dados.banco_dados) e as lacunas que exigem
nova modelagem. Não acessa banco nem rede; é reutilizável e testável offline.

Decisões de modelagem (verificadas no schema real, NÃO inventadas):
- Apenas a identidade do ativo (ticker/tipo/cnpj) possui destino claro no ORM:
  a tabela ``ativos`` (colunas ``ticker``, ``cnpj``, ``tipo``).
- As demais colunas do Sheets são indicadores de mercado (preço, P/VP, DY, VPA,
  vacância, setor, margens, ROE etc.) e, no Bloco 4, NÃO possuíam coluna
  equivalente nas tabelas ``dados_financeiros_fiis``/``dados_financeiros_acoes``
  (modelo voltado a dados contábeis/estruturados da CVM/INF_MENSAL).
- Bloco 5B implementou a modelagem desses indicadores: os campos antes
  classificados como NOVA_MODELAGEM agora apontam para ``ativos_perfil``
  (setor/tipo_fii), ``snapshots_fiis``/``snapshots_acoes`` (série temporal dos
  indicadores) e ``ativos_inquilinos`` (inquilinos de FIIs). A população das
  colunas é responsabilidade do Bloco 5C; o Sheets continua a fonte ativa.
- Campos sem equivalente fiel (classificação NAO_MAPEADO) permanecem sem
  destino no ORM: são redundantes ou ambíguos na origem (ex.: "PL Total" do FII
  que na verdade contém valor de mercado, vacância que mistura física e
  financeira, Qtd de cotas estimada, sharesOutstanding).
- O Sheets não possui coluna de CNPJ nem data de referência (o "carimbo" é
  "%d/%m %H:%M", sem ano). CNPJ é resolvido via catálogo (config.MAPA_CNPJ_B3)
  ou placeholder "PENDENTE-{ticker}" (mesmo padrão de atualizador_documentos).
- Reutiliza pipeline_dados.normalizacao e pipeline_dados.qualidade_dados
  (parsear_numero), preservando None quando o valor não puder ser interpretado
  (NUNCA converte erro de coleta em 0.0).
"""
from dataclasses import dataclass

import config
from pipeline_dados.banco_dados import TipoAtivo
from pipeline_dados.qualidade_dados import parsear_numero

ORIGEM_GOOGLE_SHEETS = "Google Sheets"

ABAS_ESPELHAVEIS = ("BD_FIIs", "BD_Acoes")

# ---------------------------------------------------------------------------
# Classificações de campo (Etapa 1 do mapeamento)
# ---------------------------------------------------------------------------
MAPEADO = "MAPEADO"                    # possui destino claro no ORM atual
NAO_MAPEADO = "NAO_MAPEADO"            # sem destino fiel (redundante/ambíguo na origem)
TEMPORARIO = "TEMPORARIO"              # cache operacional / carimbo de carga
LOG = "LOG"                            # registro operacional (BD_Logs)
DUPLICADO = "DUPLICADO"                # redundante com outra fonte já modelada
NOVA_MODELAGEM = "NOVA_MODELAGEM"      # histórico: exigia nova tabela (implementada no Bloco 5B)

CLASSIFICACOES_SEM_DESTINO = (NAO_MAPEADO, NOVA_MODELAGEM)

# Constraints reais do ORM (não inventadas; inspecionadas em banco_dados.py).
CONSTRAINT_DADOS_ACOES = "uix_dados_acoes (ativo_id, data_referencia, tipo_doc)"
CONSTRAINT_DADOS_FIIS = "uix_dados_fiis (ativo_id, data_referencia)"

# CNPJ nunca participa da identidade espelhada: o Sheets não tem coluna de CNPJ.
# Para ações usa-se o catálogo config.MAPA_CNPJ_B3; demais ativos usam o mesmo
# placeholder já adotado por atualizador_documentos ("PENDENTE-{ticker}").
_PLACEHOLDER_PREFIXO = "PENDENTE-"
_TICKER_PARA_CNPJ = {ticker: cnpj for cnpj, ticker in config.MAPA_CNPJ_B3.items()}


@dataclass(frozen=True)
class ColunaSheet:
    """Definição de uma coluna do Google Sheets e seu destino no ORM."""

    indice: int
    letra: str
    nome: str
    significado: str
    tipo: str
    origem: str
    produtor: str
    consumidor: str
    classificacao: str
    destino: str | None = None
    observacao: str = ""


# ===========================================================================
# BD_FIIs (18 colunas: A..R) — produtor: modules/scraper_fiis.py
# Consumidores: services/dashboard_menus.py, bot/callbacks_menus.py,
#               modules/scraper_fiis.py (carimbo -> precisa_atualizar).
# ===========================================================================
MAPEAMENTO_BD_FIIS = (
    ColunaSheet(0, "A", "ticker", "Ticker do FII na B3", "str",
                "Fila do garimpo", "scraper_fiis", "menu/painel", MAPEADO,
                "ativos.ticker"),
    ColunaSheet(1, "B", "tipo_fii", "Tipo do FII (Tijolo/Papel/FOF/Híbrido)", "str",
                "classificar_fii_e_emoji", "scraper_fiis", "callbacks_menus",
                MAPEADO, "ativos_perfil.tipo_fii", "classificação derivada do setor"),
    ColunaSheet(2, "C", "setor", "Segmento específico do fundo", "str",
                "StatusInvest JSON/HTML", "scraper_fiis", "dashboard_menus/callbacks",
                MAPEADO, "ativos_perfil.setor"),
    ColunaSheet(3, "D", "preco", "Cotação atualizada (R$)", "float",
                "yfinance/Fundamentus", "scraper_fiis", "dashboard_menus",
                MAPEADO, "snapshots_fiis.preco"),
    ColunaSheet(4, "E", "numero_cotas", "Quantidade total de cotas (estimada)", "float",
                "derivado (valor_mercado/preco)", "scraper_fiis", "—", NAO_MAPEADO, None,
                "não equivale a cotas_emitidas (estimativa de mercado)"),
    ColunaSheet(5, "F", "pvp", "P/VP", "float", "Fundamentus", "scraper_fiis",
                "dashboard_menus/callbacks", MAPEADO, "snapshots_fiis.pvp"),
    ColunaSheet(6, "G", "dy", "Dividend Yield (decimal)", "float", "Fundamentus",
                "scraper_fiis", "dashboard_menus", MAPEADO, "snapshots_fiis.dy"),
    ColunaSheet(7, "H", "vacancia", "Vacância média (física/financeira)", "float",
                "StatusInvest/Fundamentus", "scraper_fiis", "—", NAO_MAPEADO, None,
                "mistura física/financeira; sem equivalente fiel"),
    ColunaSheet(8, "I", "qtd_imoveis", "Quantidade física de imóveis", "int",
                "StatusInvest/Fundamentus", "scraper_fiis", "—", MAPEADO,
                "snapshots_fiis.qtd_imoveis"),
    ColunaSheet(9, "J", "inquilinos", "Lista de principais inquilinos", "str",
                "StatusInvest", "scraper_fiis", "—", MAPEADO, "ativos_inquilinos.nome",
                "nova tabela do Bloco 5B (nome+participação)"),
    ColunaSheet(10, "K", "walt", "Prazo médio de contratos (WALT)", "str",
                "IA (Pendente de IA)", "scraper_fiis", "—", MAPEADO, "snapshots_fiis.walt",
                "output de IA ainda não preenchido"),
    ColunaSheet(11, "L", "alavancagem", "Alavancagem / dívida", "str",
                "IA (Pendente de IA)", "scraper_fiis", "—", MAPEADO, "snapshots_fiis.alavancagem",
                "output de IA ainda não preenchido"),
    ColunaSheet(12, "M", "liquidez", "Liquidez média diária negociada", "float",
                "Fundamentus", "scraper_fiis", "—", MAPEADO, "snapshots_fiis.liquidez"),
    ColunaSheet(13, "N", "valor_mercado", "Valor de mercado (rotulado como PL)", "float",
                "Fundamentus", "scraper_fiis", "—", NAO_MAPEADO, None,
                "coluna rotulada 'PL Total' mas contém valor de mercado; PL real vem da CVM"),
    ColunaSheet(14, "O", "vpa", "Valor patrimonial da cota (VPA)", "float",
                "derivado (preco/pvp)", "scraper_fiis", "dashboard_menus", MAPEADO,
                "snapshots_fiis.vpa"),
    ColunaSheet(15, "P", "lucro_12m", "Lucro distribuído (12M)", "float",
                "derivado (valor_mercado*dy)", "scraper_fiis", "—", MAPEADO,
                "snapshots_fiis.lucro_12m"),
    ColunaSheet(16, "Q", "dividendo_mensal", "Projeção de dividendo mensal", "float",
                "derivado (preco*dy/12)", "scraper_fiis", "—", MAPEADO,
                "snapshots_fiis.dividendo_mensal"),
    ColunaSheet(17, "R", "carimbo", "Carimbo de conclusão da carga (d/m %H:%M)", "str",
                "agente", "scraper_fiis", "scraper_fiis (precisa_atualizar)",
                TEMPORARIO, None, "sem ano; não serve como data_referencia"),
)

# ===========================================================================
# BD_Acoes (33 colunas: A..AG) — produtor: modules/scraper_acoes.py
# Consumidores: services/dashboard_menus.py, bot/callbacks_menus.py,
#               modules/scraper_acoes.py (carimbo -> precisa_atualizar).
# ===========================================================================
MAPEAMENTO_BD_ACOES = (
    ColunaSheet(0, "A", "ticker", "Ticker da ação na B3", "str",
                "Fila do garimpo", "scraper_acoes", "menu/painel", MAPEADO,
                "ativos.ticker"),
    ColunaSheet(1, "B", "setor", "Setor (macro, mapa B3)", "str",
                "classificar_setor_por_mapa", "scraper_acoes", "callbacks_menus",
                MAPEADO, "ativos_perfil.setor"),
    ColunaSheet(2, "C", "preco", "Cotação atualizada (R$)", "float",
                "yfinance/Fundamentus", "scraper_acoes", "dashboard_menus",
                MAPEADO, "snapshots_acoes.preco"),
    ColunaSheet(3, "D", "dy", "Dividend Yield (decimal)", "float", "Fundamentus",
                "scraper_acoes", "dashboard_menus", MAPEADO, "snapshots_acoes.dy"),
    ColunaSheet(4, "E", "qtd_acoes", "Ações em circulação (sharesOutstanding)", "float",
                "yfinance", "scraper_acoes", "—", NAO_MAPEADO),
    ColunaSheet(5, "F", "pl", "P/L", "float", "Fundamentus", "scraper_acoes",
                "dashboard_menus", MAPEADO, "snapshots_acoes.pl"),
    ColunaSheet(6, "G", "pvp", "P/VP", "float", "Fundamentus", "scraper_acoes",
                "dashboard_menus", MAPEADO, "snapshots_acoes.pvp"),
    ColunaSheet(7, "H", "p_ativo", "P/Ativo", "float", "Fundamentus", "scraper_acoes",
                "—", MAPEADO, "snapshots_acoes.p_ativo"),
    ColunaSheet(8, "I", "marg_bruta", "Margem bruta", "float", "Fundamentus",
                "scraper_acoes", "—", MAPEADO, "snapshots_acoes.marg_bruta"),
    ColunaSheet(9, "J", "marg_ebit", "Margem EBIT", "float", "Fundamentus",
                "scraper_acoes", "—", MAPEADO, "snapshots_acoes.marg_ebit"),
    ColunaSheet(10, "K", "marg_liquida", "Margem líquida", "float", "Fundamentus",
                "scraper_acoes", "—", MAPEADO, "snapshots_acoes.marg_liquida"),
    ColunaSheet(11, "L", "p_ebit", "P/EBIT", "float", "Fundamentus", "scraper_acoes",
                "—", MAPEADO, "snapshots_acoes.p_ebit"),
    ColunaSheet(12, "M", "ev_ebit", "EV/EBIT", "float", "Fundamentus", "scraper_acoes",
                "—", MAPEADO, "snapshots_acoes.ev_ebit"),
    ColunaSheet(13, "N", "div_liq_ebit", "Dív. Líq. / EBIT", "float", "Fundamentus",
                "scraper_acoes", "—", MAPEADO, "snapshots_acoes.div_liq_ebit",
                "campo preenchido com Dív.Líq/Patrim. (duplicação na origem)"),
    ColunaSheet(14, "O", "div_liq_patrimonio", "Dív. Líq. / Patrimônio", "float",
                "Fundamentus", "scraper_acoes", "—", MAPEADO, "snapshots_acoes.div_liq_patrimonio"),
    ColunaSheet(15, "P", "psr", "PSR", "float", "Fundamentus", "scraper_acoes",
                "—", MAPEADO, "snapshots_acoes.psr"),
    ColunaSheet(16, "Q", "p_cap_giro", "P/Cap. Giro", "float", "Fundamentus",
                "scraper_acoes", "—", MAPEADO, "snapshots_acoes.p_cap_giro"),
    ColunaSheet(17, "R", "p_at_circ_liq", "P/Ativ. Circ. Líq.", "float", "Fundamentus",
                "scraper_acoes", "—", MAPEADO, "snapshots_acoes.p_at_circ_liq"),
    ColunaSheet(18, "S", "liq_corrente", "Liquidez corrente", "float", "Fundamentus",
                "scraper_acoes", "—", MAPEADO, "snapshots_acoes.liq_corrente"),
    ColunaSheet(19, "T", "roe", "ROE", "float", "Fundamentus", "scraper_acoes",
                "dashboard_menus", MAPEADO, "snapshots_acoes.roe"),
    ColunaSheet(20, "U", "roa", "ROA", "float", "yfinance", "scraper_acoes",
                "—", MAPEADO, "snapshots_acoes.roa"),
    ColunaSheet(21, "V", "roic", "ROIC", "float", "Fundamentus", "scraper_acoes",
                "—", MAPEADO, "snapshots_acoes.roic"),
    ColunaSheet(22, "W", "reservado_w", "Reservado", "float", "—", "scraper_acoes",
                "—", TEMPORARIO, None, "slots reservados"),
    ColunaSheet(23, "X", "reservado_x", "Reservado", "float", "—", "scraper_acoes",
                "—", TEMPORARIO, None, "slots reservados"),
    ColunaSheet(24, "Y", "reservado_y", "Reservado", "float", "—", "scraper_acoes",
                "—", TEMPORARIO, None, "slots reservados"),
    ColunaSheet(25, "Z", "cagr_rec_5a", "Cresc. Rec. 5a (CAGR)", "float", "Fundamentus",
                "scraper_acoes", "—", MAPEADO, "snapshots_acoes.cagr_rec_5a"),
    ColunaSheet(26, "AA", "reservado_aa", "Reservado", "float", "—", "scraper_acoes",
                "—", TEMPORARIO, None, "slots reservados"),
    ColunaSheet(27, "AB", "liq_media", "Liquidez média (Liq.2meses)", "float",
                "Fundamentus", "scraper_acoes", "—", MAPEADO, "snapshots_acoes.liq_media"),
    ColunaSheet(28, "AC", "vpa", "VPA", "float", "yfinance", "scraper_acoes",
                "—", MAPEADO, "snapshots_acoes.vpa"),
    ColunaSheet(29, "AD", "lpa", "LPA", "float", "yfinance", "scraper_acoes",
                "—", MAPEADO, "snapshots_acoes.lpa"),
    ColunaSheet(30, "AE", "peg_ratio", "PEG Ratio", "float", "yfinance",
                "scraper_acoes", "—", MAPEADO, "snapshots_acoes.peg_ratio"),
    ColunaSheet(31, "AF", "valor_mercado", "Valor de mercado (marketCap)", "float",
                "yfinance", "scraper_acoes", "—", MAPEADO, "snapshots_acoes.valor_mercado"),
    ColunaSheet(32, "AG", "carimbo", "Carimbo de atualização (d/m %H:%M)", "str",
                "agente", "scraper_acoes", "scraper_acoes (precisa_atualizar)",
                TEMPORARIO, None, "sem ano; não serve como data_referencia"),
)

# BD_Logs: registro operacional de erros dos scrapers [datetime, ativo, erro].
# Não é espelhado: classificação LOG.
MAPEAMENTO_BD_LOGS = (
    ColunaSheet(0, "A", "data_log", "Data/hora do erro", "str", "agente",
                "scraper_fiis/acoes", "—", LOG),
    ColunaSheet(1, "B", "ativo", "Ativo relacionado", "str", "agente",
                "scraper_fiis/acoes", "—", LOG),
    ColunaSheet(2, "C", "erro", "Descrição do erro", "str", "agente",
                "scraper_fiis/acoes", "—", LOG),
)

MAPA_POR_ABA = {
    "BD_FIIs": MAPEAMENTO_BD_FIIS,
    "BD_Acoes": MAPEAMENTO_BD_ACOES,
    "BD_Logs": MAPEAMENTO_BD_LOGS,
}

# LACUNA transversal: nenhuma aba possui data de referência válida para as
# tabelas financeiras (dados_financeiros_fiis/acoes exigem data_referencia).
LACUNAS_GERAIS = (
    "data_referencia (sem coluna de data no Sheets; o carimbo não contém ano)",
    "cnpj (Sheets sem coluna de CNPJ; resolvido via catálogo/placeholder)",
)


def tipo_ativo_da_aba(nome_aba) -> TipoAtivo | None:
    """Mapeia a aba do Sheets para o enum TipoAtivo do ORM."""
    if nome_aba == "BD_FIIs":
        return TipoAtivo.FII
    if nome_aba == "BD_Acoes":
        return TipoAtivo.ACAO
    return None


def resolver_cnpj(ticker, tipo_ativo) -> str:
    """Resolve o CNPJ do ativo: catálogo MAPA_CNPJ_B3 ou placeholder.

    Placeholder no mesmo formato já usado por atualizador_documentos
    (``PENDENTE-{ticker}``); é preenchido depois pelos coletores CVM.
    """
    ticker_limpo = str(ticker).strip().upper()
    if tipo_ativo is TipoAtivo.ACAO:
        return _TICKER_PARA_CNPJ.get(ticker_limpo, f"{_PLACEHOLDER_PREFIXO}{ticker_limpo}")
    return f"{_PLACEHOLDER_PREFIXO}{ticker_limpo}"


def _celula(linha, indice):
    if indice < len(linha):
        return linha[indice]
    return None


def _ticker(linha):
    valor = _celula(linha, 0)
    if valor is None or not str(valor).strip():
        return None
    return str(valor).strip().upper()


def _texto(linha, indice):
    valor = _celula(linha, indice)
    if valor is None or not str(valor).strip():
        return None
    return str(valor).strip()


def parsear_valor_market(valor) -> float | None:
    """Converte valor do Sheets em float, preservando None quando ilegível.

    Diferente de modules/utils.formatar(), NUNCA converte erro em 0.0. Trata
    prefixos monetários (R$/%), separadores BR e marcadores vazios ("-", "N/A").
    """
    if valor is None:
        return None
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return parsear_numero(valor)
    texto = str(valor).strip()
    if not texto:
        return None
    texto = texto.replace("R$", "").replace("$", "").replace("%", "").replace(" ", "").strip()
    if texto in ("-", "N/A", "N/D", "NA", "—", "--"):
        return None
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    return parsear_numero(texto)


def _num(linha, indice) -> float | None:
    return parsear_valor_market(_celula(linha, indice))


def _inteiro(linha, indice) -> int | float | None:
    numero = parsear_valor_market(_celula(linha, indice))
    if numero is None:
        return None
    return int(numero) if float(numero).is_integer() else numero


def transformar_linha_fii(linha) -> dict:
    """Normaliza uma linha da aba BD_FIIs em campos nomeados/numéricos."""
    return {
        "ticker": _ticker(linha),
        "tipo_fii": _texto(linha, 1),
        "setor": _texto(linha, 2),
        "preco": _num(linha, 3),
        "numero_cotas": _num(linha, 4),
        "pvp": _num(linha, 5),
        "dy": _num(linha, 6),
        "vacancia": _num(linha, 7),
        "qtd_imoveis": _inteiro(linha, 8),
        "inquilinos": _texto(linha, 9),
        "walt": _texto(linha, 10),
        "alavancagem": _texto(linha, 11),
        "liquidez": _num(linha, 12),
        "valor_mercado": _num(linha, 13),
        "vpa": _num(linha, 14),
        "lucro_12m": _num(linha, 15),
        "dividendo_mensal": _num(linha, 16),
        "carimbo": _texto(linha, 17),
    }


def transformar_linha_acao(linha) -> dict:
    """Normaliza uma linha da aba BD_Acoes em campos nomeados/numéricos."""
    return {
        "ticker": _ticker(linha),
        "setor": _texto(linha, 1),
        "preco": _num(linha, 2),
        "dy": _num(linha, 3),
        "qtd_acoes": _num(linha, 4),
        "pl": _num(linha, 5),
        "pvp": _num(linha, 6),
        "p_ativo": _num(linha, 7),
        "marg_bruta": _num(linha, 8),
        "marg_ebit": _num(linha, 9),
        "marg_liquida": _num(linha, 10),
        "p_ebit": _num(linha, 11),
        "ev_ebit": _num(linha, 12),
        "div_liq_ebit": _num(linha, 13),
        "div_liq_patrimonio": _num(linha, 14),
        "psr": _num(linha, 15),
        "p_cap_giro": _num(linha, 16),
        "p_at_circ_liq": _num(linha, 17),
        "liq_corrente": _num(linha, 18),
        "roe": _num(linha, 19),
        "roa": _num(linha, 20),
        "roic": _num(linha, 21),
        "reservado_w": _num(linha, 22),
        "reservado_x": _num(linha, 23),
        "reservado_y": _num(linha, 24),
        "cagr_rec_5a": _num(linha, 25),
        "reservado_aa": _num(linha, 26),
        "liq_media": _num(linha, 27),
        "vpa": _num(linha, 28),
        "lpa": _num(linha, 29),
        "peg_ratio": _num(linha, 30),
        "valor_mercado": _num(linha, 31),
        "carimbo": _texto(linha, 32),
    }


def campos_sem_destino(nome_aba) -> set[str]:
    """Campos da aba sem destino no ORM atual (NÃO MAPEADO/NOVA MODELAGEM)."""
    return {col.nome for col in MAPA_POR_ABA[nome_aba] if col.classificacao in CLASSIFICACOES_SEM_DESTINO}


def lacunas(nome_aba) -> list[str]:
    """Lacunas da aba: campos presentes sem destino + lacunas transversais."""
    return sorted(campos_sem_destino(nome_aba)) + list(LACUNAS_GERAIS)
