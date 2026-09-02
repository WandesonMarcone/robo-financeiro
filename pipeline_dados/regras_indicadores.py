"""Catálogo de regras por indicador — Fase 4 (aditivo).

Responsabilidade única: definir, para cada indicador de mercado de AÇÕES e
FIIs, a sua própria regra semântica de qualidade. Diferente da camada de
persistência (pipeline_dados.qualidade_dados, que decide VALID/WARNING/INVALID
para gravar no banco), esta camada classifica a *natureza* de cada ocorrência:

- OK       -> valor financeiramente plausível.
- WARNING  -> possível dado incorreto (fora da faixa usual) OU sinal negativo
              financeiramente possível, porém incomum.
- ERRO     -> valor impossível/inválido para o indicador.
- CRITICO  -> valor implausível (possível inconsistência de fonte/escala).

Princípios:
- NEGATIVO NÃO É SINÔNIMO DE ERRO. Indicadores que podem ser negativos de
  forma legítima (ROE, margens, lucro líquido, dívida líquida, resultado
  financeiro, LPA etc.) são classificados como OK. Indicadores em que negativo
  é impossível (preço, ativo total, cotistas) são ERRO.
- Nenhum valor original é alterado para silenciar um alerta: a classificação é
  apenas diagnóstica.
- O catálogo também carrega os limiares de variação (mercado/crítico) usados
  pela detecção de mudanças (pipeline_dados.motor_alertas).

Estrutura base por ativo/indicador (arquitetura genérica da Fase 4):
    tipo_ativo + ativo + indicador + valor + histórico + regra + severidade
"""
from dataclasses import dataclass

from pipeline_dados.qualidade_dados import parsear_numero

OK = "OK"
WARNING = "WARNING"
ERRO = "ERRO"
CRITICO = "CRITICO"


@dataclass(frozen=True)
class RegraIndicador:
    """Regra semântica de um indicador de mercado.

    ``classificacao_negativo`` define como tratar valores negativos:
    OK (legítimo), WARNING (possível, porém suspeito) ou ERRO (impossível).
    ``faixa_ok``/``faixa_critica`` são faixas (min, max) de plausibilidade;
    valores fora de ``faixa_ok`` geram WARNING e fora de ``faixa_critica``
    geram CRITICO. Limites de variação (``limite_variacao_pct`` /
    ``limite_variacao_critica_pct``) controlam o disparo de alertas de mercado.
    """

    indicador: str
    nome_exibicao: str
    unidade: str = ""
    classificacao_negativo: str = WARNING
    aceita_zero: bool = True
    faixa_ok: tuple[float | None, float | None] | None = None
    faixa_critica: tuple[float | None, float | None] | None = None
    limite_variacao_pct: float = 0.20
    limite_variacao_critica_pct: float = 0.50
    motivo_negativo: str = "Valor negativo não faz sentido para este indicador."


def _fii(
    indicador, nome, unidade="", neg=WARNING, aceita_zero=True,
    faixa_ok=None, faixa_critica=None, var=0.20, var_crit=0.50, motivo="",
):
    return RegraIndicador(
        indicador=indicador, nome_exibicao=nome, unidade=unidade,
        classificacao_negativo=neg, aceita_zero=aceita_zero,
        faixa_ok=faixa_ok, faixa_critica=faixa_critica,
        limite_variacao_pct=var, limite_variacao_critica_pct=var_crit,
        motivo_negativo=motivo or f"Valor negativo não faz sentido para {nome}.",
    )


def _acao(
    indicador, nome, unidade="", neg=WARNING, aceita_zero=True,
    faixa_ok=None, faixa_critica=None, var=0.20, var_crit=0.50, motivo="",
):
    return RegraIndicador(
        indicador=indicador, nome_exibicao=nome, unidade=unidade,
        classificacao_negativo=neg, aceita_zero=aceita_zero,
        faixa_ok=faixa_ok, faixa_critica=faixa_critica,
        limite_variacao_pct=var, limite_variacao_critica_pct=var_crit,
        motivo_negativo=motivo or f"Valor negativo não faz sentido para {nome}.",
    )


# ===========================================================================
# FIIs (snapshots_fiis)
# ===========================================================================
REGRAS_FIIS: dict[str, RegraIndicador] = {
    "preco": _fii("preco", "Preço", "R$", neg=ERRO, aceita_zero=False,
                  faixa_ok=(0.01, None), var=0.10, var_crit=0.30),
    "pvp": _fii("pvp", "P/VP", "x", neg=WARNING, aceita_zero=False,
                faixa_ok=(0.0, 3.0), faixa_critica=(0.0, 5.0), var=0.20, var_crit=0.50,
                motivo="P/VP negativo é possível com VPA negativo, porém incomum."),
    "dy": _fii("dy", "Dividend Yield", "%", neg=WARNING, aceita_zero=False,
               faixa_ok=(0.0, 0.25), faixa_critica=(0.0, 0.35), var=0.15, var_crit=0.50,
               motivo="DY negativo não é esperado para FIIs."),
    "liquidez": _fii("liquidez", "Liquidez", "R$", neg=WARNING, var=0.25, var_crit=0.60),
    "vpa": _fii("vpa", "VPA", "R$", neg=WARNING, aceita_zero=False, var=0.20, var_crit=0.50,
                motivo="VPA negativo é possível com patrimônio negativo, porém incomum."),
    "lucro_12m": _fii("lucro_12m", "Lucro 12M", "R$", neg=WARNING, aceita_zero=False,
                      var=0.20, var_crit=0.50),
    "dividendo_mensal": _fii("dividendo_mensal", "Dividendo Mensal", "R$", neg=WARNING,
                             var=0.20, var_crit=0.50),
    "qtd_imoveis": _fii("qtd_imoveis", "Qtd. Imóveis", "un.", neg=ERRO, var=0.20, var_crit=0.50),
}

# ===========================================================================
# Ações (snapshots_acoes)
# ===========================================================================
REGRAS_ACOES: dict[str, RegraIndicador] = {
    "preco": _acao("preco", "Preço", "R$", neg=ERRO, aceita_zero=False,
                   faixa_ok=(0.01, None), var=0.10, var_crit=0.30),
    "dy": _acao("dy", "Dividend Yield", "%", neg=WARNING, aceita_zero=False,
                faixa_ok=(0.0, 0.15), faixa_critica=(0.0, 0.25), var=0.20, var_crit=0.50,
                motivo="DY negativo não é esperado para ações."),
    "pl": _acao("pl", "P/L", "x", neg=WARNING, aceita_zero=False,
                faixa_ok=(0.0, 60.0), faixa_critica=(0.0, 120.0), var=0.25, var_crit=0.60,
                motivo="P/L negativo reflete prejuízo; o múltiplo perde significado."),
    "pvp": _acao("pvp", "P/VP", "x", neg=WARNING, aceita_zero=False,
                 faixa_ok=(0.0, 8.0), faixa_critica=(0.0, 15.0), var=0.20, var_crit=0.50,
                 motivo="P/VP negativo é possível com patrimônio negativo, porém incomum."),
    "p_ativo": _acao("p_ativo", "P/Ativo", "x", neg=WARNING, faixa_ok=(0.0, 10.0),
                     var=0.25, var_crit=0.60),
    "marg_bruta": _acao("marg_bruta", "Margem Bruta", "%", neg=OK, faixa_ok=(-1.0, 1.0),
                        faixa_critica=(-2.0, 2.0), var=0.30, var_crit=0.60,
                        motivo=""),
    "marg_ebit": _acao("marg_ebit", "Margem EBIT", "%", neg=OK, faixa_ok=(-1.0, 1.0),
                       faixa_critica=(-2.0, 2.0), var=0.30, var_crit=0.60,
                       motivo=""),
    "marg_liquida": _acao("marg_liquida", "Margem Líquida", "%", neg=OK, faixa_ok=(-1.0, 1.0),
                          faixa_critica=(-2.0, 2.0), var=0.30, var_crit=0.60,
                          motivo=""),
    "p_ebit": _acao("p_ebit", "P/EBIT", "x", neg=WARNING, var=0.30, var_crit=0.60),
    "ev_ebit": _acao("ev_ebit", "EV/EBIT", "x", neg=WARNING, var=0.30, var_crit=0.60),
    "div_liq_patrimonio": _acao("div_liq_patrimonio", "Dív. Líq./Patrimônio", "x", neg=OK,
                                faixa_ok=(-3.0, 3.0), faixa_critica=(-6.0, 6.0),
                                var=0.25, var_crit=0.60,
                                motivo=""),
    "psr": _acao("psr", "PSR", "x", neg=WARNING, faixa_ok=(0.0, 10.0), var=0.30, var_crit=0.60),
    "p_cap_giro": _acao("p_cap_giro", "P/Cap. Giro", "x", neg=WARNING, var=0.30, var_crit=0.60),
    "p_at_circ_liq": _acao("p_at_circ_liq", "P/Ativ. Circ. Líq.", "x", neg=WARNING,
                           var=0.30, var_crit=0.60),
    "liq_corrente": _acao("liq_corrente", "Liquidez Corrente", "x", neg=WARNING, aceita_zero=False,
                          faixa_ok=(0.0, 10.0), var=0.30, var_crit=0.60),
    "roe": _acao("roe", "ROE", "%", neg=OK, faixa_ok=(-1.0, 1.0), faixa_critica=(-3.0, 3.0),
                 var=0.30, var_crit=0.60,
                 motivo=""),
    "roa": _acao("roa", "ROA", "%", neg=OK, faixa_ok=(-1.0, 1.0), faixa_critica=(-3.0, 3.0),
                 var=0.30, var_crit=0.60,
                 motivo=""),
    "roic": _acao("roic", "ROIC", "%", neg=OK, faixa_ok=(-1.0, 1.0), faixa_critica=(-3.0, 3.0),
                  var=0.30, var_crit=0.60,
                  motivo=""),
    "cagr_rec_5a": _acao("cagr_rec_5a", "CAGR Rec. 5a", "%", neg=OK, faixa_ok=(-1.0, 1.0),
                         faixa_critica=(-2.0, 2.0), var=0.30, var_crit=0.60,
                         motivo=""),
    "liq_media": _acao("liq_media", "Liquidez Média", "R$", neg=WARNING, aceita_zero=False,
                       var=0.30, var_crit=0.60),
    "vpa": _acao("vpa", "VPA", "R$", neg=WARNING, faixa_ok=(-5.0, None), var=0.25, var_crit=0.60,
                 motivo="VPA negativo é possível com patrimônio negativo, porém incomum."),
    "lpa": _acao("lpa", "LPA", "R$", neg=OK, var=0.30, var_crit=0.60, motivo=""),
    "peg_ratio": _acao("peg_ratio", "PEG Ratio", "x", neg=OK, aceita_zero=False,
                       faixa_ok=(0.0, 20.0), var=0.30, var_crit=0.60,
                       motivo=""),
    "valor_mercado": _acao("valor_mercado", "Valor de Mercado", "R$", neg=WARNING, aceita_zero=False,
                           var=0.20, var_crit=0.50),
}

REGRAS_POR_TIPO: dict[str, dict[str, RegraIndicador]] = {
    "FII": REGRAS_FIIS,
    "ACAO": REGRAS_ACOES,
}


def obter_regra(tipo_ativo: str, indicador: str) -> RegraIndicador | None:
    """Retorna a regra do indicador ou None (indicador sem regra/não monitorado)."""
    return REGRAS_POR_TIPO.get(tipo_ativo, {}).get(indicador)


def _fora_da_faixa(valor: float, faixa: tuple[float | None, float | None] | None) -> bool:
    if faixa is None:
        return False
    minimo, maximo = faixa
    if minimo is not None and valor < minimo:
        return True
    if maximo is not None and valor > maximo:
        return True
    return False


def classificar_indicador(tipo_ativo: str, indicador: str, valor) -> dict:
    """Classifica uma ocorrência de um indicador (OK/WARNING/ERRO/CRITICO).

    Retorna um dict com chaves: ``regra``, ``severidade``, ``motivo`` e
    ``nome_exibicao``. Valor ausente/ilegível retorna ``severidade`` "IGNORADO"
    (não é erro nem alerta). A classificação NÃO altera o valor original.
    """
    regra = obter_regra(tipo_ativo, indicador)
    if regra is None:
        return {"regra": "SEM_REGRA", "severidade": OK, "motivo": "", "nome_exibicao": indicador}

    numero = parsear_numero(valor)
    if numero is None:
        return {"regra": "VALOR_AUSENTE", "severidade": "IGNORADO",
                "motivo": "Valor ausente/ilegível; indicador não avaliado.", "nome_exibicao": regra.nome_exibicao}

    if numero < 0:
        if regra.classificacao_negativo == ERRO:
            return {"regra": "VALOR_NEGATIVO_IMPOSSIVEL", "severidade": ERRO,
                    "motivo": regra.motivo_negativo, "nome_exibicao": regra.nome_exibicao}
        if regra.classificacao_negativo == WARNING:
            return {"regra": "VALOR_NEGATIVO_SUSPEITO", "severidade": WARNING,
                    "motivo": regra.motivo_negativo, "nome_exibicao": regra.nome_exibicao}
        return {"regra": "VALOR_NEGATIVO_LEGITIMO", "severidade": OK,
                "motivo": "Dado financeiramente válido, porém negativo.", "nome_exibicao": regra.nome_exibicao}

    if numero == 0 and not regra.aceita_zero:
        return {"regra": "VALOR_ZERO_SUSPEITO", "severidade": WARNING,
                "motivo": f"Valor zero é improvável para {regra.nome_exibicao}.", "nome_exibicao": regra.nome_exibicao}

    if regra.faixa_critica is not None and _fora_da_faixa(numero, regra.faixa_critica):
        return {"regra": "FORA_FAIXA_CRITICA", "severidade": CRITICO,
                "motivo": f"{regra.nome_exibicao} fora da faixa de plausibilidade "
                          f"{regra.faixa_critica} (possível inconsistência de fonte/escala).",
                "nome_exibicao": regra.nome_exibicao}

    if regra.faixa_ok is not None and _fora_da_faixa(numero, regra.faixa_ok):
        return {"regra": "FORA_FAIXA", "severidade": WARNING,
                "motivo": f"{regra.nome_exibicao} fora da faixa usual "
                          f"{regra.faixa_ok} (possível dado incorreto).",
                "nome_exibicao": regra.nome_exibicao}

    return {"regra": "OK", "severidade": OK, "motivo": "Valor dentro da faixa esperada.",
            "nome_exibicao": regra.nome_exibicao}
