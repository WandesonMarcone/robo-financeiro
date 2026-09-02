"""Validação determinística de qualidade de dados — Fase 3, Bloco 3.

Responsabilidade única: impedir que dados inválidos, incompletos ou
claramente suspeitos sejam persistidos silenciosamente no Core de Dados.
A camada é 100% determinística (regras explícitas, nenhuma IA) e é reutilizada
pelos pipelines existentes (CVM, FNET/B3, informes mensais de FIIs).

Classificação de um registro:
- VALID   -> consistente; pode persistir sem ressalvas.
- WARNING -> aceitável, porém suspeito; persiste, mas o alerta é registrado.
- INVALID -> contaminaria a base; NÃO persiste/atualiza o dado.

Princípios de desenho:
- Dado AUSENTE (None/vazio) é diferente de dado INVÁLIDO (valor presente e
  errado). Campo obrigatório ausente bloqueia o registro; campo opcional
  ausente é aceito.
- Erro de coleta nunca vira zero: valor não-numérico vira None (ausente).
- NaN/Inf são valores inválidos (não ausentes) e bloqueiam o campo.
- Nenhum limite financeiro arbitrário: onde não há certeza usa-se WARNING.
- Todo achado registra origem (fonte, ativo, documento, timestamp) para
  diagnóstico, sem alterar o schema do banco.
"""
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pipeline_dados.normalizacao import normalizar_cnpj, normalizar_data
from pipeline_dados.numerico import coerir_numero, parsear_numero

VALID = "VALID"
WARNING = "WARNING"
INVALID = "INVALID"


@dataclass
class AchadoQualidade:
    """Uma violação (ou suspeita) detectada em um campo do registro."""

    campo: str
    severidade: str
    regra: str
    valor: Any
    mensagem: str


@dataclass
class ResultadoQualidade:
    """Resultado da validação de um registro, com rastreabilidade de origem."""

    achados: list[AchadoQualidade] = field(default_factory=list)
    origem: str | None = None
    ativo: str | None = None
    documento: str | None = None

    @property
    def status(self) -> str:
        if any(achado.severidade == INVALID for achado in self.achados):
            return INVALID
        if self.achados:
            return WARNING
        return VALID

    @property
    def aceita(self) -> bool:
        return self.status != INVALID


def _achado(campo: str, severidade: str, regra: str, valor: Any, mensagem: str) -> AchadoQualidade:
    return AchadoQualidade(
        campo=campo, severidade=severidade, regra=regra, valor=valor, mensagem=mensagem
    )


# ==========================================
# REGRAS DE CAMPO
# ==========================================

def regra_obrigatorio(campo: str, valor) -> AchadoQualidade | None:
    """Campo obrigatório ausente = dado AUSENTE (bloqueia o registro)."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return _achado(
            campo, INVALID, "CAMPO_OBRIGATORIO", valor,
            "Campo obrigatório ausente (dado AUSENTE, não inválido).",
        )
    return None


def regra_texto_obrigatorio(campo: str, valor) -> AchadoQualidade | None:
    """Campo textual obrigatório ausente = dado AUSENTE (bloqueia o registro)."""
    if valor is None or not isinstance(valor, str) or not valor.strip():
        return _achado(
            campo, INVALID, "CAMPO_OBRIGATORIO", valor,
            "Campo textual obrigatório ausente (dado AUSENTE).",
        )
    return None


def regra_texto_se_presente(campo: str, valor) -> AchadoQualidade | None:
    """Campo opcional presente porém vazio = suspeito (WARNING)."""
    if valor is None:
        return None
    if not isinstance(valor, str) or not valor.strip():
        return _achado(
            campo, WARNING, "TEXTO_VAZIO", valor,
            "Campo opcional presente porém vazio (dado suspeito).",
        )
    return None


def regra_numero(campo: str, valor) -> AchadoQualidade | None:
    """Valor deve ser numérico e finito (dado INVÁLIDO quando não é)."""
    _, motivo = coerir_numero(valor)
    if motivo == "NAO_NUMERO":
        return _achado(
            campo, INVALID, "NAO_NUMERO", valor,
            "Valor não é um número válido (dado INVÁLIDO).",
        )
    if motivo == "NAO_FINITO":
        return _achado(
            campo, INVALID, "NAO_FINITO", valor,
            "Valor NaN/Inf não pode ser persistido (dado INVÁLIDO).",
        )
    return None


def regra_nao_negativo(
    campo: str, valor, severidade: str = INVALID, regra: str = "VALOR_NEGATIVO"
) -> AchadoQualidade | None:
    """Valor numérico não pode ser negativo quando não faz sentido."""
    numero, motivo = coerir_numero(valor)
    if motivo is not None or numero is None:
        return None
    if numero < 0:
        return _achado(
            campo, severidade, regra, valor,
            "Valor negativo não faz sentido para este campo.",
        )
    return None


def regra_inteiro(campo: str, valor, severidade: str = WARNING) -> AchadoQualidade | None:
    """Valor deveria ser um número inteiro (contagem) — suspeito se não for."""
    numero, motivo = coerir_numero(valor)
    if motivo is not None or numero is None:
        return None
    if not numero.is_integer():
        return _achado(
            campo, severidade, "NAO_INTEIRO", valor,
            "Valor deveria ser inteiro (contagem), recebido com casas decimais.",
        )
    return None


def regra_vacancia(campo: str, valor) -> AchadoQualidade | None:
    """Vacância: negativa é impossível (INVALID); acima de 1 é escala suspeita (WARNING)."""
    numero, motivo = coerir_numero(valor)
    if motivo is not None or numero is None:
        return None
    if numero < 0:
        return _achado(
            campo, INVALID, "VALOR_NEGATIVO", valor,
            "Vacância negativa é impossível.",
        )
    if numero > 1:
        return _achado(
            campo, WARNING, "VACANCIA_ESCALA", valor,
            "Vacância > 1 sugere problema de escala (espera-se decimal 0–1).",
        )
    return None


def regra_data(campo: str, valor) -> AchadoQualidade | None:
    """Data deve ser reconhecida por normalizar_data (dado INVÁLIDO se não)."""
    if valor is None:
        return None
    if normalizar_data(valor) is None:
        return _achado(
            campo, INVALID, "DATA_INVALIDA", valor,
            "Data inválida ou em formato desconhecido (dado INVÁLIDO).",
        )
    return None


def regra_data_nao_futura(campo: str, valor) -> AchadoQualidade | None:
    """Data de publicação no futuro = suspeita (WARNING), não bloqueia."""
    data = normalizar_data(valor)
    if data is None:
        return None
    if data > date.today():
        return _achado(
            campo, WARNING, "DATA_FUTURA", valor,
            "Data de publicação no futuro (possível fuso ou timestamp errado).",
        )
    return None


def regra_data_nao_antiga(campo: str, valor, limite: date = date(1990, 1, 1)) -> AchadoQualidade | None:
    """Data anterior ao registro eletrônico da B3/CVM = suspeita (WARNING).

    FNET da B3 existe desde ~2013 e a CVM desde ~2005; documentos datados
    antes de 1990 são claramente suspeitos, mas não são rejeitados.
    """
    data = normalizar_data(valor)
    if data is None:
        return None
    if data < limite:
        return _achado(
            campo, WARNING, "DATA_ANTIGA", valor,
            "Data anterior ao início do registro eletrônico (possível erro de captura).",
        )
    return None


def regra_url(campo: str, valor) -> AchadoQualidade | None:
    """URL de download deve começar com http(s):// (dado INVÁLIDO se não)."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if not str(valor).strip().startswith(("http://", "https://")):
        return _achado(
            campo, INVALID, "URL_INVALIDA", valor,
            "URL deve começar com http(s):// (dado INVÁLIDO).",
        )
    return None


def cnpj_verificar_digitos(cnpj) -> bool:
    """Valida os dígitos verificadores do CNPJ, reaproveitando a normalização."""
    digitos = normalizar_cnpj(cnpj)
    if digitos is None or len(set(digitos)) == 1:
        return False
    numeros = [int(d) for d in digitos]

    def digito_verificador(primeiros: list[int], pesos: tuple[int, ...]) -> int:
        resto = sum(n * p for n, p in zip(primeiros, pesos, strict=False)) % 11
        return 0 if resto < 2 else 11 - resto

    dv1 = digito_verificador(numeros[:12], (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    dv2 = digito_verificador(numeros[:13], (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return dv1 == numeros[12] and dv2 == numeros[13]


def regra_cnpj(campo: str, valor) -> AchadoQualidade | None:
    """CNPJ presente deve ter dígitos verificadores válidos (dado INVÁLIDO)."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if not cnpj_verificar_digitos(valor):
        return _achado(
            campo, INVALID, "CNPJ_INVALIDO", valor,
            "CNPJ com dígitos verificadores inválidos (dado INVÁLIDO).",
        )
    return None


# ==========================================
# REGRAS DE REGISTRO (cruzamento entre campos)
# ==========================================

def regra_consistencia_balanco(registro: dict[str, Any]) -> list[AchadoQualidade]:
    """Checagens básicas de consistência contábil (WARNING, nunca bloqueia).

    No layout da CVM, a conta '2' (Total do Passivo) já inclui o patrimônio
    líquido; portanto Ativo Total deve igualar o Passivo Total (tolerância de
    5%), e o PL não pode ser maior que o passivo total.
    """
    ativo_total = parsear_numero(registro.get("ativo_total"))
    passivo_total = parsear_numero(registro.get("passivo_total"))
    pl = parsear_numero(registro.get("patrimonio_liquido"))
    achados = []

    if ativo_total is not None and passivo_total is not None and ativo_total > 0:
        tolerancia = max(ativo_total * 0.05, 1.0)
        if abs(ativo_total - passivo_total) > tolerancia:
            achados.append(_achado(
                "ativo_total", WARNING, "INCONSISTENCIA_BALANCO",
                {"ativo_total": ativo_total, "passivo_total": passivo_total},
                "Ativo total diverge do passivo total em mais de 5% (balanço inconsistente).",
            ))

    if pl is not None and passivo_total is not None and pl > passivo_total:
        achados.append(_achado(
            "patrimonio_liquido", WARNING, "INCONSISTENCIA_BALANCO",
            {"patrimonio_liquido": pl, "passivo_total": passivo_total},
            "Patrimônio líquido maior que o passivo total (só possível com passivo exigível negativo).",
        ))
    return achados


# ==========================================
# ESPECIFICAÇÕES POR CONTEXTO
# ==========================================

def _nao_negativo_invalido(campo: str, valor) -> AchadoQualidade | None:
    return regra_nao_negativo(campo, valor)


def _nao_negativo_aviso(campo: str, valor) -> AchadoQualidade | None:
    return regra_nao_negativo(campo, valor, severidade=WARNING, regra="VALOR_NEGATIVO_SUSPEITO")


def _inteiro_aviso(campo: str, valor) -> AchadoQualidade | None:
    return regra_inteiro(campo, valor, severidade=WARNING)


ESPECIFICACOES: dict[str, dict[str, Any]] = {
    "fii_informe_cvm": {
        "campos": {
            "cnpj_fundo": [regra_cnpj],
            "patrimonio_liquido": [regra_numero, _nao_negativo_invalido],
            "ativo_total": [regra_numero, _nao_negativo_invalido],
            "disponibilidades_caixa": [regra_numero, _nao_negativo_invalido],
            "cotistas": [regra_numero, _nao_negativo_invalido, _inteiro_aviso],
            "cotas_emitidas": [regra_numero, _nao_negativo_invalido],
            "rendimento_por_cota": [regra_numero, _nao_negativo_invalido],
            "vacancia_fisica": [regra_numero, regra_vacancia],
            "vacancia_financeira": [regra_numero, regra_vacancia],
            "despesas_taxas": [regra_numero, _nao_negativo_aviso],
            "receita_imoveis": [regra_numero, _nao_negativo_invalido],
            "resultado_ligado_venda": [regra_numero],
        },
        "registro": [],
    },
    "acao_itr_cvm": {
        "campos": {
            "data_referencia": [regra_data],
            "ativo_total": [regra_numero, _nao_negativo_invalido],
            "passivo_total": [regra_numero, _nao_negativo_invalido],
            "caixa": [regra_numero, _nao_negativo_invalido],
            "patrimonio_liquido": [regra_numero, _nao_negativo_aviso],
            "divida_bruta": [regra_numero, _nao_negativo_invalido],
            "divida_curto_prazo": [regra_numero, _nao_negativo_invalido],
            "divida_longo_prazo": [regra_numero, _nao_negativo_invalido],
            "divida_liquida": [regra_numero],
            "receita": [regra_numero, _nao_negativo_aviso],
            "lucro_bruto": [regra_numero],
            "ebitda": [regra_numero],
            "resultado_financeiro": [regra_numero],
            "lucro_liquido": [regra_numero],
            "fco": [regra_numero],
        },
        "registro": [regra_consistencia_balanco],
    },
    "documento_fnet": {
        "campos": {
            "data_publicacao": [regra_obrigatorio, regra_data, regra_data_nao_futura, regra_data_nao_antiga],
            "tipo_documento": [regra_texto_obrigatorio],
            "url_pdf": [regra_url],
            "id_b3": [regra_texto_se_presente],
        },
        "registro": [],
    },
    "documento_ipe": {
        "campos": {
            "data_publicacao": [regra_obrigatorio, regra_data, regra_data_nao_futura, regra_data_nao_antiga],
            "tipo_documento": [regra_texto_obrigatorio],
            "url_pdf": [regra_url],
            "ativo": [regra_obrigatorio],
        },
        "registro": [],
    },
    # Espelhamento Google Sheets -> PostgreSQL (Fase 3, Bloco 4): a identidade
    # do ativo (ticker) é o único campo obrigatório do espelho. O CNPJ é
    # resolvido via catálogo (MAPA_CNPJ_B3) ou placeholder "PENDENTE-{ticker}",
    # e não participa desta validação (placeholders nunca são CNPJ válidos).
    "sheets_ativo": {
        "campos": {
            "ticker": [regra_texto_obrigatorio],
        },
        "registro": [],
    },
    # Dupla escrita FIIs -> PostgreSQL (Fase 3, Bloco 5C): snapshot diário dos
    # indicadores de mercado da aba BD_FIIs. Reaproveita as regras existentes;
    # nenhuma regra arbitrária. INVALID bloqueia o snapshot; WARNING persiste.
    # Erro de coleta nunca vira 0.0: valor não-numérico vira None (ausente) na
    # normalização (parsear_numero) e é aceito como campo opcional ausente.
    "snapshot_fii_mercado": {
        "campos": {
            "ticker": [regra_texto_obrigatorio],
            "data_referencia": [regra_data],
            "preco": [regra_numero, _nao_negativo_invalido],
            "pvp": [regra_numero, _nao_negativo_aviso],
            "dy": [regra_numero, _nao_negativo_aviso],
            "qtd_imoveis": [regra_numero, _nao_negativo_invalido, _inteiro_aviso],
            "liquidez": [regra_numero, _nao_negativo_aviso],
            "vpa": [regra_numero, _nao_negativo_aviso],
            "lucro_12m": [regra_numero, _nao_negativo_aviso],
            "dividendo_mensal": [regra_numero, _nao_negativo_aviso],
            "walt": [regra_texto_se_presente],
            "alavancagem": [regra_texto_se_presente],
        },
        "registro": [],
    },
    # Dupla escrita Ações -> PostgreSQL (Fase 3, Bloco 5C): snapshot diário dos
    # indicadores de mercado da aba BD_Acoes. Mesma filosofia do contexto de
    # FIIs: reusa as regras existentes; INVALID bloqueia, WARNING persiste.
    # Preço negativo bloqueia (INVALID); demais indicadores com sinal suspeito
    # (ex.: margens/ROE negativos) são aceitos e apenas sinalizados (WARNING).
    "snapshot_acao_mercado": {
        "campos": {
            "ticker": [regra_texto_obrigatorio],
            "data_referencia": [regra_data],
            "preco": [regra_numero, _nao_negativo_invalido],
            "dy": [regra_numero, _nao_negativo_aviso],
            "pl": [regra_numero, _nao_negativo_aviso],
            "pvp": [regra_numero, _nao_negativo_aviso],
            "p_ativo": [regra_numero, _nao_negativo_aviso],
            "marg_bruta": [regra_numero, _nao_negativo_aviso],
            "marg_ebit": [regra_numero, _nao_negativo_aviso],
            "marg_liquida": [regra_numero, _nao_negativo_aviso],
            "p_ebit": [regra_numero, _nao_negativo_aviso],
            "ev_ebit": [regra_numero, _nao_negativo_aviso],
            "div_liq_patrimonio": [regra_numero, _nao_negativo_aviso],
            "psr": [regra_numero, _nao_negativo_aviso],
            "p_cap_giro": [regra_numero, _nao_negativo_aviso],
            "p_at_circ_liq": [regra_numero, _nao_negativo_aviso],
            "liq_corrente": [regra_numero, _nao_negativo_aviso],
            "roe": [regra_numero, _nao_negativo_aviso],
            "roa": [regra_numero, _nao_negativo_aviso],
            "roic": [regra_numero, _nao_negativo_aviso],
            "cagr_rec_5a": [regra_numero, _nao_negativo_aviso],
            "liq_media": [regra_numero, _nao_negativo_aviso],
            "vpa": [regra_numero, _nao_negativo_aviso],
            "lpa": [regra_numero, _nao_negativo_aviso],
            "peg_ratio": [regra_numero, _nao_negativo_aviso],
            "valor_mercado": [regra_numero, _nao_negativo_aviso],
        },
        "registro": [],
    },
    # Inquilinos de FIIs -> ativos_inquilinos (Fase 3, Bloco 5C): o nome é
    # obrigatório (nome vazio/impossível de interpretar não persiste — o parser
    # de inquilinos já filtra; esta regra é a rede de segurança). Participação
    # é opcional: ausente (None) é aceita e permanece NULL; presente porém
    # não-numérica ou negativa bloqueia (INVALID). Percentuais são convertidos
    # para fração 0–1 pelo parser, sem regra arbitrária de escala aqui.
    "inquilino_fii": {
        "campos": {
            "nome": [regra_texto_obrigatorio],
            "data_referencia": [regra_data],
            "participacao": [regra_numero, _nao_negativo_invalido],
        },
        "registro": [],
    },
}


# ==========================================
# API PÚBLICA
# ==========================================

def validar_registro(
    registro: dict[str, Any],
    contexto: str,
    origem: str | None = None,
    ativo: str | None = None,
    documento: str | None = None,
) -> ResultadoQualidade:
    """Aplica as regras determinísticas do contexto ao registro.

    registro: dict {campo: valor}. contextos disponíveis: ESPECIFICACOES.keys().
    """
    if contexto not in ESPECIFICACOES:
        raise ValueError(f"Contexto de validação desconhecido: {contexto}")
    espec = ESPECIFICACOES[contexto]
    achados = []
    for campo, regras in espec["campos"].items():
        valor = registro.get(campo)
        for regra in regras:
            achado = regra(campo, valor)
            if achado is not None:
                achados.append(achado)
    for regra in espec["registro"]:
        achados.extend(regra(registro))
    return ResultadoQualidade(
        achados=achados, origem=origem, ativo=ativo, documento=documento
    )


def registrar_diagnostico(resultado: ResultadoQualidade, logger: logging.Logger | None = None) -> None:
    """Registra em log estruturado cada achado, preservando o contexto de origem."""
    if not resultado.achados:
        return
    logger = logger or logging.getLogger("qualidade_dados")
    for achado in resultado.achados:
        nivel = logging.ERROR if achado.severidade == INVALID else logging.WARNING
        logger.log(
            nivel,
            "QUALIDADE origem=%s ativo=%s documento=%s campo=%s valor=%r regra=%s severidade=%s mensagem=%s",
            resultado.origem,
            resultado.ativo,
            resultado.documento,
            achado.campo,
            achado.valor,
            achado.regra,
            achado.severidade,
            achado.mensagem,
        )
