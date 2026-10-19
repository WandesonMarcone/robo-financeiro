"""Importador do catalogo oficial de companhias da CVM (FCA).

Fonte: Formulario Cadastral (FCA) da CVM, arquivo publico
``fca_cia_aberta_<ano>.zip``. Diferentemente de listas fixas, o importador
percorre TODAS as companhias abertas presentes na fonte oficial e usa:

* ``fca_cia_aberta_geral``: CNPJ, nome, setor de atividade e descricao da
  atividade principal;
* ``fca_cia_aberta_valor_mobiliario``: codigos de negociacao (tickers) por
  companhia.

O importador NAO e executado no boot. A aplicacao continua sem tocar no schema
ou no Neon automaticamente. A execucao e manual/administrativa, por exemplo::

    from pipeline_dados.coletor_catalogo_cvm import ColetorCatalogoCVM
    ColetorCatalogoCVM().importar(2026)

Falhas de fonte (rede, HTTP, ZIP/CSV invalido) retornam um resumo com ``erro`` e
NAO alteram o banco. Linhas individuais invalidas sao contabilizadas em
``erros`` sem interromper o restante do lote.
"""

import io
import logging
import zipfile
from datetime import datetime

import pandas as pd
import requests

from pipeline_dados.repositorio_catalogo import (
    RepositorioCatalogo,
    normalizar_cnpj,
    normalizar_ticker,
    ticker_negociacao_valido,
)

logger = logging.getLogger("robo.catalogo.cvm")

URL_FCA = (
    "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/"
    "fca_cia_aberta_{ano}.zip"
)

ARQUIVO_GERAL = "fca_cia_aberta_geral_{ano}.csv"
ARQUIVO_VALORES = "fca_cia_aberta_valor_mobiliario_{ano}.csv"

# Mercados aceitos como negociacao em bolsa/balcao organizado. A comparacao e
# tolerante a caixa/acentos; valores explicitamente diferentes (ex.: mercado de
# balcao de titulos publicos de outra natureza) sao descartados.
_MERCADOS_ACEITOS = (
    "bolsa",
    "b3",
    "balcao",
    "mercado a vista",
    "mercado fracionario",
)
_TIPOS_VALOR_ACEITOS = (
    "acao",
    "acoes",
    "unit",
    "units",
    "bdr",
    "bdrs",
    "recibo",
    "recibos",
    "cota",
    "cotas",
)


class FonteCatalogoIndisponivel(RuntimeError):
    """Erro controlado de fonte oficial (sem alterar o banco)."""


def _texto(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return str(valor).strip()


def _sem_acento(valor):
    import unicodedata

    texto = unicodedata.normalize("NFKD", _texto(valor))
    return "".join(c for c in texto if not unicodedata.combining(c)).casefold()


def _coluna(df, nomes):
    for nome in nomes:
        if nome in df.columns:
            return nome
    return None


def _selecionar_mais_recente(df, chaves):
    """Mantem a linha de maior Data_Referencia e maior versao por chave.

    A ordenacao original e preservada como criterio de desempate, mas a
    selecao e explicita (nao depende da ordem em que a fonte entregou o CSV).
    """
    if df is None or df.empty:
        return df
    chaves = [chave for chave in chaves if chave in df.columns]
    if not chaves:
        return df

    trabalho = df.copy()
    trabalho["__ordem_original"] = range(len(trabalho))
    coluna_data = _coluna(trabalho, ("Data_Referencia", "Data_Referencia_Arquivo"))
    coluna_versao = _coluna(trabalho, ("Versao", "Versão", "Versao_Arquivo"))
    if coluna_data:
        trabalho["__data"] = pd.to_datetime(
            trabalho[coluna_data], errors="coerce"
        )
    else:
        trabalho["__data"] = pd.NaT
    if coluna_versao:
        trabalho["__versao"] = pd.to_numeric(
            trabalho[coluna_versao], errors="coerce"
        ).fillna(-1)
    else:
        trabalho["__versao"] = -1

    trabalho = trabalho.sort_values(
        by=[*chaves, "__data", "__versao", "__ordem_original"],
        ascending=True,
        kind="stable",
        na_position="first",
    )
    selecionado = trabalho.drop_duplicates(subset=chaves, keep="last")
    return selecionado.drop(
        columns=["__ordem_original", "__data", "__versao"], errors="ignore"
    )


def _mercado_valido(valor):
    texto = _sem_acento(valor)
    if not texto:
        return True
    return any(termo in texto for termo in _MERCADOS_ACEITOS)


def _tipo_valor_valido(valor):
    texto = _sem_acento(valor)
    if not texto:
        return True
    return any(termo in texto for termo in _TIPOS_VALOR_ACEITOS)


def _resumo_vazio(ano=None, fonte=None):
    return {
        "ano": ano,
        "fonte": fonte,
        "empresas_criadas": 0,
        "empresas_atualizadas": 0,
        "ativos_vinculados": 0,
        "setores": 0,
        "atividades": 0,
        "linhas_ignoradas": 0,
        "linhas_mercado_invalido": 0,
        "linhas_tipo_invalido": 0,
        "erros": 0,
        "erro": None,
    }


class ColetorCatalogoCVM:
    def __init__(self, repositorio=None, http_get=None, url_template=URL_FCA):
        self.repositorio = repositorio or RepositorioCatalogo()
        self._http_get = http_get or requests.get
        self._url_template = url_template

    # ------------------------------------------------------------------
    # Download/parsing
    # ------------------------------------------------------------------

    def baixar_dataframes(self, ano):
        url = self._url_template.format(ano=ano)
        try:
            resposta = self._http_get(url, timeout=60)
            resposta.raise_for_status()
        except Exception as erro:
            raise FonteCatalogoIndisponivel(
                f"Falha ao baixar FCA {ano}: {type(erro).__name__}"
            ) from erro

        try:
            with zipfile.ZipFile(io.BytesIO(resposta.content)) as pacote:
                nomes = set(pacote.namelist())
                nome_geral = ARQUIVO_GERAL.format(ano=ano)
                nome_valores = ARQUIVO_VALORES.format(ano=ano)
                if nome_geral not in nomes or nome_valores not in nomes:
                    raise FonteCatalogoIndisponivel(
                        f"ZIP FCA {ano} sem os arquivos esperados."
                    )
                with pacote.open(nome_geral) as arquivo:
                    geral = pd.read_csv(
                        arquivo, sep=";", encoding="latin1", dtype=str
                    )
                with pacote.open(nome_valores) as arquivo:
                    valores = pd.read_csv(
                        arquivo, sep=";", encoding="latin1", dtype=str
                    )
        except FonteCatalogoIndisponivel:
            raise
        except Exception as erro:
            raise FonteCatalogoIndisponivel(
                f"ZIP/CSV FCA {ano} invalido: {type(erro).__name__}"
            ) from erro
        return geral, valores, url

    # ------------------------------------------------------------------
    # Importacao
    # ------------------------------------------------------------------

    def importar(self, ano=None):
        ano = int(ano or datetime.utcnow().year)
        resumo = _resumo_vazio(ano=ano, fonte=URL_FCA.format(ano=ano))
        try:
            geral, valores, url = self.baixar_dataframes(ano)
        except FonteCatalogoIndisponivel as erro:
            resumo["erro"] = str(erro)
            logger.warning("Fonte do catalogo indisponivel: %s", erro)
            return resumo
        resumo["fonte"] = url
        return self.importar_dataframes(geral, valores, fonte=url, resumo=resumo)

    def importar_dataframes(self, geral, valores, fonte=None, resumo=None):
        """Importa DataFrames da FCA (permite teste offline com dados oficiais)."""
        resumo = resumo or _resumo_vazio(fonte=fonte)
        if not isinstance(geral, pd.DataFrame) or not isinstance(
            valores, pd.DataFrame
        ):
            resumo["erro"] = "DataFrames invalidos."
            return resumo

        colunas_gerais = {
            "CNPJ_Companhia",
            "Nome_Empresarial",
            "Setor_Atividade",
        }
        colunas_valores = {"CNPJ_Companhia", "Codigo_Negociacao"}
        if not colunas_gerais.issubset(geral.columns):
            resumo["erro"] = "Colunas obrigatorias ausentes no FCA geral."
            return resumo
        if not colunas_valores.issubset(valores.columns):
            resumo["erro"] = (
                "Colunas obrigatorias ausentes no FCA valor mobiliario."
            )
            return resumo

        # Normaliza as chaves ANTES de deduplicar. A CVM pode entregar o mesmo
        # CNPJ com/sem formatacao e o codigo de negociacao com caixa diferente;
        # sem isso, a mesma entidade apareceria como duas linhas "mais novas".
        geral = geral.copy()
        valores = valores.copy()
        geral["CNPJ_Companhia"] = geral["CNPJ_Companhia"].map(normalizar_cnpj)
        valores["CNPJ_Companhia"] = valores["CNPJ_Companhia"].map(
            normalizar_cnpj
        )
        valores["Codigo_Negociacao"] = valores["Codigo_Negociacao"].map(
            normalizar_ticker
        )

        # Mantem explicitamente a linha de maior Data_Referencia e maior versao
        # por chave. A ordem de entrega do CSV nao e considerada "a mais nova".
        # O ticker e a chave do valor mobiliario; Mercado/Tipo podem mudar entre
        # versoes e nao devem impedir a selecao da linha mais recente.
        geral = _selecionar_mais_recente(geral, ["CNPJ_Companhia"])
        valores = _selecionar_mais_recente(
            valores,
            ["CNPJ_Companhia", "Codigo_Negociacao"],
        )

        empresas_por_cnpj = {}
        setores_vistos = set()
        atividades_vistas = set()

        for _, linha in geral.iterrows():
            cnpj = _texto(linha.get("CNPJ_Companhia"))
            nome = _texto(linha.get("Nome_Empresarial"))
            if not cnpj or not nome:
                resumo["linhas_ignoradas"] += 1
                continue
            try:
                empresa, criada = self.repositorio.obter_ou_criar_empresa(
                    nome=nome,
                    cnpj=cnpj,
                    razao_social=nome,
                    situacao=_texto(linha.get("Situacao_Emissor"))
                    or _texto(linha.get("Situacao_Registro_CVM")),
                    fonte=fonte,
                    evidencia=(
                        f"FCA CVM - {_texto(linha.get('Data_Referencia'))}"
                    ).strip(),
                )
                empresas_por_cnpj[cnpj] = empresa
                if criada:
                    resumo["empresas_criadas"] += 1
                else:
                    resumo["empresas_atualizadas"] += 1

                setor_nome = _texto(linha.get("Setor_Atividade"))
                if setor_nome:
                    setor_id = self.repositorio.obter_ou_criar_setor(
                        setor_nome, fonte=fonte
                    )
                    self.repositorio.classificar_empresa(
                        empresa.id,
                        setor_id,
                        fonte=fonte,
                        evidencia=(
                            f"FCA CVM - Setor_Atividade: {setor_nome}"
                        ),
                    )
                    setores_vistos.add(setor_nome)

                atividade_nome = _texto(linha.get("Descricao_Atividade"))
                if atividade_nome:
                    atividade_id = (
                        self.repositorio.obter_ou_criar_atividade(
                            atividade_nome,
                            fonte=fonte,
                            evidencia=(
                                f"FCA CVM - Descricao_Atividade: "
                                f"{atividade_nome}"
                            ),
                        )
                    )
                    self.repositorio.adicionar_atividade(
                        empresa.id,
                        atividade_id,
                        principal=True,
                        fonte=fonte,
                        evidencia=(
                            f"FCA CVM - Descricao_Atividade: {atividade_nome}"
                        ),
                    )
                    atividades_vistas.add(atividade_nome)
            except Exception:
                resumo["erros"] += 1
                logger.warning(
                    "Linha do catalogo CVM ignorada (%s)", cnpj, exc_info=True
                )

        for _, linha in valores.iterrows():
            cnpj = _texto(linha.get("CNPJ_Companhia"))
            ticker = normalizar_ticker(linha.get("Codigo_Negociacao"))
            if not cnpj or not ticker:
                resumo["linhas_ignoradas"] += 1
                continue
            if not _mercado_valido(linha.get("Mercado")):
                resumo["linhas_mercado_invalido"] += 1
                resumo["linhas_ignoradas"] += 1
                continue
            if not _tipo_valor_valido(linha.get("Tipo")):
                resumo["linhas_tipo_invalido"] += 1
                resumo["linhas_ignoradas"] += 1
                continue
            # Ignora codigos encerrados para nao apresentar ticker morto como
            # ativo negociado atual. O historico permanece na CVM.
            if _texto(linha.get("Data_Fim_Negociacao")):
                resumo["linhas_ignoradas"] += 1
                continue
            if not ticker_negociacao_valido(ticker):
                resumo["linhas_ignoradas"] += 1
                continue

            empresa = empresas_por_cnpj.get(cnpj)
            if empresa is None:
                # Pode ser uma linha de valor mobiliario cuja companhia nao
                # apareceu no recorte do geral. Nao inventamos a empresa.
                resumo["linhas_ignoradas"] += 1
                continue
            try:
                ativo_id = self.repositorio.vincular_ativo(
                    empresa.id,
                    ticker,
                    fonte=fonte,
                    evidencia=(
                        "FCA CVM - Codigo_Negociacao: "
                        f"{ticker} ({_texto(linha.get('Mercado'))})"
                    ),
                    criar_ativo=True,
                    tipo="acao",
                )
                if ativo_id is not None:
                    resumo["ativos_vinculados"] += 1
                else:
                    resumo["linhas_ignoradas"] += 1
            except Exception:
                resumo["erros"] += 1
                logger.warning(
                    "Ticker %s do catalogo CVM ignorado", ticker, exc_info=True
                )

        resumo["setores"] = len(setores_vistos)
        resumo["atividades"] = len(atividades_vistas)
        return resumo


__all__ = [
    "ColetorCatalogoCVM",
    "FonteCatalogoIndisponivel",
    "URL_FCA",
]
