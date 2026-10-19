"""Deteccao assistida por IA de novidades no catalogo.

Reutiliza a integracao existente em ``modules.module_ia.analisar_fatos_com_ia``
(Groq -> OpenRouter -> OpenAI). Nenhum provedor novo e criado.

Politica de seguranca/qualidade:

* a IA NAO grava direto no banco: primeiro valida estrutura, CNPJ, tickers,
  fonte e confianca;
* uma novidade so e criada automaticamente quando ha fonte oficial
  (``*.gov.br``/``*.b3.com.br``), evidencia textual e confianca >= limite;
* casos ambiguos ou de fonte nao oficial vao para ``sugestoes_catalogo`` com
  fonte, evidencia, justificativa e dados completos;
* duplicidades sao verificadas no repositorio antes de qualquer criacao;
* atividades sao vinculadas apenas quando citadas individualmente — nunca se
  herda o conjunto de atividades do setor;
* falha do provedor/fonte nao altera o banco e retorna ``erro`` no resumo.
"""

import json
import logging
import re
from urllib.parse import urlparse

from pipeline_dados.repositorio_catalogo import (
    ConflitoEmpresa,
    ConflitoVinculoAtivo,
    RepositorioCatalogo,
    gerar_slug,
    normalizar_cnpj,
    normalizar_ticker,
    ticker_negociacao_valido,
)
from pipeline_dados.taxonomia_catalogo import (
    resolver_setor,
    resolver_subsetor,
)

logger = logging.getLogger("robo.catalogo.ia")

CONFIANCA_MINIMA_AUTO = 90
# Mantido como alias publico para compatibilidade; a regra real e a mesma do
# repositorio/importador CVM e aceita raizes alfanumericas (``B3SA3``).
PADRAO_TICKER = re.compile(r"^(?=.*[A-Z])[A-Z0-9]{4}\d{1,2}$")

PROMPT_SISTEMA = (
    "Voce e um analista de dados cadastrais do mercado brasileiro. "
    "Nao invente empresas, tickers, setores ou atividades. "
    "Responda apenas JSON valido."
)

PROMPT_TEMPLATE = """
Analise o texto abaixo, proveniente de uma fonte monitorada, e identifique
SOMENTE entidades explicitamente citadas e sustentadas por evidencias do texto.

Texto:
---
{texto}
---

Fonte monitorada: {fonte}

Responda EXCLUSIVAMENTE com JSON neste formato:
{{
  "empresas": [
    {{
      "nome": "nome da empresa",
      "cnpj": "CNPJ se aparecer no texto, senao vazio",
      "tickers": ["codigos de negociacao explicitamente citados"],
      "setor": "setor explicitamente citado/confirmado, senao vazio",
      "subsetor": "subsetor explicitamente citado, senao vazio",
      "atividades": ["atividades economicas explicitamente citadas"],
      "confianca": 0,
      "evidencia": "trecho literal que sustenta a identificacao",
      "justificativa": "por que a classificacao e segura ou ambigua"
    }}
  ]
}}

Regras:
- confianca e um inteiro de 0 a 100;
- nao complete campos por conhecimento externo ao texto/fonte;
- se nao houver empresa explicita, retorne {{"empresas": []}};
- nao inclua markdown.
"""


def _fonte_oficial(fonte):
    if not fonte:
        return False
    texto = str(fonte).strip().lower()
    if "://" not in texto:
        return False
    host = (urlparse(texto).hostname or "").lower()
    return (
        host == "gov.br"
        or host.endswith(".gov.br")
        or host == "b3.com.br"
        or host.endswith(".b3.com.br")
    )


def _extrair_json(resposta):
    if not isinstance(resposta, str):
        raise ValueError("Resposta da IA nao e texto.")
    texto = resposta.strip()
    if texto.startswith("❌"):
        raise ValueError("Provedor de IA indisponivel.")
    texto = re.sub(r"^```(?:json)?\s*", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s*```$", "", texto)
    inicio = texto.find("{")
    fim = texto.rfind("}")
    if inicio < 0 or fim <= inicio:
        raise ValueError("Resposta da IA sem JSON.")
    return json.loads(texto[inicio : fim + 1])


def _texto(valor):
    return str(valor or "").strip()


def _confianca(valor):
    try:
        numero = int(float(valor))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, numero))


def _analisador_padrao(prompt, system_prompt=PROMPT_SISTEMA):
    from modules.module_ia import analisar_fatos_com_ia

    return analisar_fatos_com_ia(prompt, system_prompt=system_prompt)


def _resumo_vazio():
    return {
        "empresas_criadas": 0,
        "empresas_existentes": 0,
        "ativos_vinculados": 0,
        "empresas_classificadas": 0,
        "atividades_vinculadas": 0,
        "sugestoes": 0,
        "duplicados": 0,
        "erros": 0,
        "erro": None,
    }


def processar_texto_monitorado(texto, fonte=None, repositorio=None,
                                analisador=None,
                                confianca_minima=CONFIANCA_MINIMA_AUTO):
    """Detecta e aplica (ou enfileira) novidades a partir de um texto.

    Retorna um resumo com contadores. Nunca levanta erro de provedor: falhas
    viram ``erro`` no resumo, sem alterar o banco.
    """
    repositorio = repositorio or RepositorioCatalogo()
    analisador = analisador or _analisador_padrao
    resumo = _resumo_vazio()

    texto = _texto(texto)
    if not texto:
        resumo["erro"] = "Texto vazio."
        return resumo

    prompt = PROMPT_TEMPLATE.format(texto=texto[:12000], fonte=fonte or "")
    try:
        resposta = analisador(prompt, system_prompt=PROMPT_SISTEMA)
        dados = _extrair_json(resposta)
    except Exception as erro:
        resumo["erro"] = f"Falha ao obter/validar resposta da IA: {type(erro).__name__}"
        logger.warning("Falha no processamento de catalogo por IA", exc_info=True)
        return resumo

    empresas = dados.get("empresas") if isinstance(dados, dict) else None
    if not isinstance(empresas, list):
        resumo["erro"] = "JSON da IA sem lista 'empresas'."
        return resumo

    oficial = _fonte_oficial(fonte)
    for candidato in empresas:
        if not isinstance(candidato, dict):
            resumo["erros"] += 1
            continue
        try:
            _processar_candidato(
                candidato,
                fonte=fonte,
                oficial=oficial,
                repositorio=repositorio,
                confianca_minima=confianca_minima,
                resumo=resumo,
            )
        except Exception:
            resumo["erros"] += 1
            logger.warning(
                "Candidato de catalogo ignorado pela IA", exc_info=True
            )
    return resumo


def _processar_candidato(candidato, fonte, oficial, repositorio,
                         confianca_minima, resumo):
    nome = _texto(candidato.get("nome"))
    if not nome:
        resumo["erros"] += 1
        return

    confianca = _confianca(candidato.get("confianca"))
    evidencia = _texto(candidato.get("evidencia"))
    justificativa = _texto(candidato.get("justificativa"))
    cnpj = normalizar_cnpj(candidato.get("cnpj"))
    tickers = []
    for bruto in candidato.get("tickers") or []:
        ticker = normalizar_ticker(bruto)
        if ticker and ticker_negociacao_valido(ticker) and ticker not in tickers:
            tickers.append(ticker)
    setor_nome = _texto(candidato.get("setor"))
    subsetor_nome = _texto(candidato.get("subsetor"))
    atividades = []
    for bruto in candidato.get("atividades") or []:
        atividade = _texto(bruto)
        if atividade and atividade not in atividades:
            atividades.append(atividade)

    # A IA so classifica dentro da taxonomia validada. Nomes desconhecidos NAO
    # criam setor/subsetor: viram sugestao para revisao humana.
    setor_canonico = None
    subsetor_canonico = None
    motivo_taxonomia = None
    if setor_nome:
        setor_canonico = resolver_setor(setor_nome)
        if setor_canonico is None:
            motivo_taxonomia = f"setor fora da taxonomia validada: {setor_nome}"
        elif subsetor_nome:
            subsetor_canonico = resolver_subsetor(
                setor_canonico, subsetor_nome
            )
            if subsetor_canonico is None:
                motivo_taxonomia = (
                    "subsetor fora da taxonomia validada: "
                    f"{setor_nome} > {subsetor_nome}"
                )
    elif subsetor_nome:
        motivo_taxonomia = "subsetor informado sem setor validado"

    existente = None
    motivo_identidade = None
    try:
        if cnpj:
            existente = repositorio.obter_empresa_por_cnpj(cnpj)
        if existente is None:
            existente = repositorio.obter_empresa_por_nome(nome)
        if (
            cnpj
            and existente is not None
            and existente.cnpj
            and existente.cnpj != cnpj
        ):
            motivo_identidade = (
                f"CNPJ {cnpj} conflita com o CNPJ {existente.cnpj} ja "
                "cadastrado para o mesmo nome"
            )
        for ticker in tickers:
            dono = repositorio.obter_empresa_por_ticker(ticker)
            if dono is not None and (
                existente is None or dono.id != existente.id
            ):
                motivo_identidade = (
                    f"ticker {ticker} ja vinculado a empresa {dono.id}; "
                    "vinculo nao pode ser trocado automaticamente"
                )
                break
    except ConflitoEmpresa as erro:
        # Nunca escolhe uma empresa arbitrariamente por coincidencia de nome.
        motivo_identidade = str(erro)
    except ConflitoVinculoAtivo as erro:
        motivo_identidade = str(erro)

    pode_auto = bool(
        confianca >= confianca_minima
        and oficial
        and evidencia
        and motivo_taxonomia is None
        and motivo_identidade is None
        and (existente is not None or cnpj is not None)
    )

    chave = (cnpj.replace(".", "").replace("/", "").replace("-", "")
             if cnpj else gerar_slug(nome))
    dados_sugestao = {
        "nome": nome,
        "cnpj": cnpj,
        "tickers": tickers,
        "setor": setor_canonico or setor_nome,
        "subsetor": subsetor_canonico or subsetor_nome,
        "atividades": atividades,
        "confianca": confianca,
        "evidencia": evidencia,
        "justificativa": justificativa,
    }

    if not pode_auto:
        motivo = []
        if not oficial:
            motivo.append("fonte nao oficial")
        if confianca < confianca_minima:
            motivo.append(f"confianca {confianca} < {confianca_minima}")
        if not evidencia:
            motivo.append("sem evidencia textual")
        if existente is None and not cnpj:
            motivo.append("empresa nova sem CNPJ oficial")
        if motivo_taxonomia:
            motivo.append(motivo_taxonomia)
        if motivo_identidade:
            motivo.append(motivo_identidade)
        repositorio.registrar_sugestao(
            "empresa",
            chave,
            dados=dados_sugestao,
            fonte=fonte,
            evidencia=evidencia,
            justificativa=justificativa or "; ".join(motivo),
            confianca=confianca,
        )
        resumo["sugestoes"] += 1
        return

    empresa, criada = repositorio.obter_ou_criar_empresa(
        nome=nome,
        cnpj=cnpj,
        razao_social=nome,
        fonte=fonte,
        evidencia=evidencia,
    )
    if criada:
        resumo["empresas_criadas"] += 1
    else:
        resumo["empresas_existentes"] += 1

    alterou_algo = criada
    for ticker in tickers:
        antes = repositorio.obter_empresa_por_ticker(ticker)
        ativo_id = repositorio.vincular_ativo(
            empresa.id,
            ticker,
            fonte=fonte,
            evidencia=evidencia,
            criar_ativo=True,
            tipo="acao",
        )
        if ativo_id is not None:
            resumo["ativos_vinculados"] += 1
            if antes is None or antes.id != empresa.id:
                alterou_algo = True

    if setor_canonico:
        setor_id = repositorio.obter_setor_por_nome(setor_canonico)
        if setor_id is None:
            setor_id = repositorio.obter_ou_criar_setor(
                setor_canonico, fonte=fonte
            )
            alterou_algo = True
        subsetor_id = None
        if subsetor_canonico:
            subsetor_id = repositorio.obter_subsetor_por_nome(
                setor_id, subsetor_canonico
            )
            if subsetor_id is None:
                subsetor_id = repositorio.obter_ou_criar_subsetor(
                    setor_id, subsetor_canonico, fonte=fonte
                )
                alterou_algo = True
        _, mudou = repositorio.classificar_empresa(
            empresa.id,
            setor_id,
            subsetor_id=subsetor_id,
            fonte=fonte,
            evidencia=evidencia,
            justificativa=justificativa,
        )
        if mudou:
            resumo["empresas_classificadas"] += 1
            alterou_algo = True

    for atividade_nome in atividades:
        atividade_id = repositorio.obter_atividade_por_nome(atividade_nome)
        if atividade_id is None:
            atividade_id = repositorio.obter_ou_criar_atividade(
                atividade_nome, fonte=fonte, evidencia=evidencia
            )
            alterou_algo = True
        _, mudou = repositorio.adicionar_atividade(
            empresa.id,
            atividade_id,
            fonte=fonte,
            evidencia=evidencia,
            justificativa=justificativa,
        )
        if mudou:
            resumo["atividades_vinculadas"] += 1
            alterou_algo = True

    if not alterou_algo:
        resumo["duplicados"] += 1


__all__ = [
    "CONFIANCA_MINIMA_AUTO",
    "PADRAO_TICKER",
    "processar_texto_monitorado",
]
