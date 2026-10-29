"""Coleta de Informes Mensais de FIIs da CVM (CSV em ZIP).

Associa cada informe ao ``Ativo`` pelo CNPJ cadastrado (coluna ``ativos.cnpj``),
nunca pelo ticker. O ano vem do chamador; o padrao, se omitido, e o ano civil
corrente (``datetime.now().year``).
"""

import csv
import io
import unicodedata
import zipfile
from datetime import datetime

import requests

from pipeline_dados.banco_dados import Ativo, DadosFinanceirosFiis, TipoAtivo

STATUS_ARQUIVO_INDISPONIVEL = "arquivo_indisponivel"
STATUS_ARQUIVO_INVALIDO = "arquivo_invalido"
STATUS_SEM_INFORMES = "sem_informes"
STATUS_SEM_ATIVOS = "sem_ativos"
STATUS_GRAVADO = "gravado"
STATUS_ERRO = "erro"

URL_INFORME_MENSAL = (
    "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip"
)


def ano_padrao_coleta():
    """Ano civil corrente. Usado quando ``/forcar_fiis`` nao informa o ano."""
    return datetime.now().year


def normalizar_cnpj(valor):
    """Devolve 14 digitos ou ``None``. Pontuacao e texto sao ignorados."""
    if valor is None:
        return None
    digitos = "".join(ch for ch in str(valor) if ch.isdigit())
    if len(digitos) != 14:
        return None
    return digitos


def _float_cvm(valor):
    if valor is None:
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto or texto in {"-", "--"}:
        return None
    try:
        return float(texto.replace(",", "."))
    except (TypeError, ValueError):
        return None


def _int_cvm(valor):
    numero = _float_cvm(valor)
    if numero is None:
        return None
    try:
        return int(numero)
    except (TypeError, ValueError, OverflowError):
        return None


def _valor_coluna(linha, *nomes):
    """Primeiro valor presente na linha (CSV CVM muda o nome da coluna).

    Coluna existente com valor vazio devolve ``""`` (ausencia vira None no
    parse numerico). Coluna ausente devolve ``None``.
    """
    if not linha:
        return None
    mapa = {}
    for chave, valor in linha.items():
        limpa = str(chave or "").strip().lstrip("\ufeff").upper()
        if limpa and limpa not in mapa:
            mapa[limpa] = valor
    for nome in nomes:
        if nome is None:
            continue
        chave = str(nome).strip().lstrip("\ufeff").upper()
        if chave in mapa:
            return mapa.get(chave)
    return None


def _normalizar_nome_fii(valor):
    """Normaliza nomes para uma conciliação conservadora por texto."""
    texto = str(valor or "").upper().strip()
    sem_acento = "".join(
        c
        for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.split())


class ResultadoColetaFiis:
    """Contagens da coleta. Nao afirma sucesso se nada foi gravado."""

    def __init__(self, ano):
        self.ano = ano
        self.status = STATUS_ERRO
        self.http_status = None
        self.informes_encontrados = 0
        self.gravados = 0
        self.sem_ativo = 0
        self.ignorados_validacao = 0
        self.falhas_persistencia = 0
        self.erro = None

    def mensagem_telegram(self):
        ano = self.ano
        if self.status == STATUS_ARQUIVO_INDISPONIVEL:
            codigo = self.http_status if self.http_status is not None else "—"
            return (
                f"Coleta de FIIs ({ano}): arquivo nao obtido na CVM "
                f"(HTTP {codigo}). Nenhum registro gravado."
            )
        if self.status == STATUS_ARQUIVO_INVALIDO:
            return (
                f"Coleta de FIIs ({ano}): arquivo obtido, mas invalido "
                "(ZIP/CSV ilegivel ou sem tabelas). Nenhum registro gravado."
            )
        if self.status == STATUS_SEM_INFORMES:
            return (
                f"Coleta de FIIs ({ano}): arquivo obtido, porem nenhum informe "
                "valido foi encontrado. Nenhum registro gravado."
            )
        if self.status == STATUS_SEM_ATIVOS:
            return (
                f"Coleta de FIIs ({ano}): {self.informes_encontrados} informe(s) "
                f"no arquivo; nenhum CNPJ corresponde a um FII cadastrado. "
                f"Sem ativo: {self.sem_ativo}. Ignorados: {self.ignorados_validacao}. "
                "Nenhum registro gravado."
            )
        if self.status == STATUS_GRAVADO:
            return (
                f"Coleta de FIIs ({ano}) concluida.\n"
                f"Registros gravados: {self.gravados}\n"
                f"Informes no arquivo: {self.informes_encontrados}\n"
                f"Sem ativo correspondente: {self.sem_ativo}\n"
                f"Ignorados por validacao: {self.ignorados_validacao}\n"
                f"Falhas de persistencia: {self.falhas_persistencia}"
            )
        detalhe = self.erro or "falha de processamento"
        return (
            f"Coleta de FIIs ({ano}): falha de processamento ou persistencia "
            f"({detalhe}). Gravados: {self.gravados}."
        )


def _cnpj_cadastro_fii(ativo, session):
    """CNPJ efetivo do FII: cadastro em ``ativos`` ou, se PENDENTE, o da empresa."""
    chave = normalizar_cnpj(getattr(ativo, "cnpj", None))
    if chave:
        return chave
    try:
        from pipeline_dados.modelos_catalogo import Empresa, EmpresaAtivo

        linha = (
            session.query(Empresa.cnpj)
            .join(EmpresaAtivo, EmpresaAtivo.empresa_id == Empresa.id)
            .filter(EmpresaAtivo.ativo_id == ativo.id)
            .first()
        )
    except Exception:
        return None
    if not linha:
        return None
    return normalizar_cnpj(linha[0])


def _mapa_fiis_por_cnpj(session):
    mapa = {}
    consulta = session.query(Ativo).filter(Ativo.tipo == TipoAtivo.FII)
    for ativo in consulta:
        chave = _cnpj_cadastro_fii(ativo, session)
        if chave is None:
            continue
        if chave not in mapa:
            mapa[chave] = ativo
    return mapa


def _mapa_fiis_por_nome(session):
    """Cria aliases de nomes somente para FIIs sem CNPJ cadastrado.

    O alias vem do catalogo mantido para a associacao dos documentos FNET.
    Ele nunca substitui o CNPJ quando ha mais de uma correspondencia.
    """
    from config import MAPA_ISCAS_MASTER

    mapa = {}
    for ativo in session.query(Ativo).filter(Ativo.tipo == TipoAtivo.FII):
        if _cnpj_cadastro_fii(ativo, session):
            continue
        ticker = str(getattr(ativo, "ticker", "") or "").strip().upper()
        alias = MAPA_ISCAS_MASTER.get(ticker)
        if not alias:
            continue
        alias_normalizado = _normalizar_nome_fii(alias)
        if len(alias_normalizado) < 5:
            continue
        mapa.setdefault(alias_normalizado, []).append(ativo)
    return mapa


def _ler_zip_informes(conteudo):
    with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
        nomes = [
            nome
            for nome in pacote.namelist()
            if nome.lower().endswith(".csv")
        ]
        if not nomes:
            return None
        consolidados = {}
        for nome in nomes:
            with pacote.open(nome) as arquivo:
                leitor = csv.DictReader(
                    io.TextIOWrapper(arquivo, encoding="latin1"),
                    delimiter=";",
                )
                if leitor.fieldnames:
                    leitor.fieldnames = [
                        str(n or "").lstrip("\ufeff").strip()
                        for n in leitor.fieldnames
                    ]
                for linha in leitor:
                    cnpj_fundo = _valor_coluna(
                        linha, "CNPJ_Fundo", "CNPJ_Fundo_Classe", "CNPJ_FUNDO"
                    )
                    data_ref_str = _valor_coluna(
                        linha,
                        "Data_Referencia",
                        "DT_COMPTC",
                        "Data_Competencia",
                    )
                    if not cnpj_fundo or not data_ref_str:
                        continue
                    chave = (cnpj_fundo, data_ref_str)
                    if chave not in consolidados:
                        consolidados[chave] = {}
                    nome_fundo = _valor_coluna(
                        linha,
                        "Nome_Fundo_Classe",
                        "Nome_Fundo",
                        "NM_FUNDO",
                    )
                    if str(nome_fundo or "").strip():
                        consolidados[chave]["nome_fundo"] = nome_fundo
                    patrimonio = _valor_coluna(
                        linha, "Patrimonio_Liquido", "VL_PATRIM_LIQ"
                    )
                    if patrimonio is not None:
                        consolidados[chave]["patrimonio_liquido"] = patrimonio
                    cotistas = _valor_coluna(
                        linha,
                        "Total_Numero_Cotistas",
                        "NR_COTISTAS",
                        "NR_COTST",
                        "NR_COTISTA",
                    )
                    if cotistas is not None:
                        consolidados[chave]["cotistas"] = cotistas
                    val_ativo = _valor_coluna(
                        linha, "Valor_Ativo", "Ativo_Total", "VL_TOTAL"
                    )
                    if val_ativo is not None:
                        consolidados[chave]["ativo_total"] = val_ativo
                    caixa = _valor_coluna(linha, "Disponibilidades")
                    if caixa is not None:
                        consolidados[chave]["disponibilidades_caixa"] = caixa
                    rendimento = _valor_coluna(
                        linha,
                        "VL_REND_COTA",
                        "Rendimento_Cota",
                        "VL_DIST_COTA",
                        "VL_RENDIMENTO_COTA",
                        "Valor_Rendimento_Cota",
                        "VL_DISTRIBUICAO_COTA",
                        "VL_REND_DIST_COTA",
                    )
                    if str(rendimento or "").strip():
                        consolidados[chave]["rendimento_por_cota"] = rendimento
                    cotas_emitidas = _valor_coluna(
                        linha, "Cotas_Emitidas", "Quantidade_Cotas_Emitidas"
                    )
                    if cotas_emitidas is not None:
                        consolidados[chave]["cotas_emitidas"] = cotas_emitidas
        return consolidados


def processar_informes_fiis_cvm(ano=None, session=None, http_get=None):
    """Baixa o ZIP da CVM, associa por CNPJ e grava ``dados_financeiros_fiis``.

    ``ano`` omitido usa :func:`ano_padrao_coleta`. ``session`` e ``http_get``
    existem para testes; em producao a sessao vem de ``SessionDB`` e o HTTP de
    ``requests.get``. Nao acessa Google Sheets nem Telegram.
    """
    if ano is None:
        ano = ano_padrao_coleta()
    resultado = ResultadoColetaFiis(ano)
    session_propria = session is None
    obter = http_get if http_get is not None else requests.get

    if session_propria:
        from atualizador_documentos import SessionDB

        session = SessionDB()

    url = URL_INFORME_MENSAL.format(ano=ano)
    print(f"Baixando informes mensais de FIIs (CSV) para o ano de {ano}...")
    try:
        resposta = obter(url, timeout=30)
        resultado.http_status = getattr(resposta, "status_code", None)
        if resultado.http_status != 200:
            print(
                f"Erro ao baixar dados da CVM para FIIs: Status {resultado.http_status}"
            )
            resultado.status = STATUS_ARQUIVO_INDISPONIVEL
            return resultado

        try:
            consolidados = _ler_zip_informes(resposta.content)
        except zipfile.BadZipFile:
            resultado.status = STATUS_ARQUIVO_INVALIDO
            return resultado
        except Exception as erro:
            resultado.status = STATUS_ARQUIVO_INVALIDO
            resultado.erro = type(erro).__name__
            return resultado

        if consolidados is None:
            resultado.status = STATUS_ARQUIVO_INVALIDO
            return resultado

        mapa_cnpj = _mapa_fiis_por_cnpj(session)
        mapa_nome = _mapa_fiis_por_nome(session)
        informes_com_metrica = 0

        for (cnpj_fundo, data_ref_str), metricas in consolidados.items():
            if not metricas:
                resultado.ignorados_validacao += 1
                continue

            cnpj_limpo = normalizar_cnpj(cnpj_fundo)
            if cnpj_limpo is None:
                resultado.ignorados_validacao += 1
                continue

            try:
                data_referencia = datetime.strptime(
                    str(data_ref_str)[:10], "%Y-%m-%d"
                ).date()
            except (TypeError, ValueError):
                resultado.ignorados_validacao += 1
                continue

            informes_com_metrica += 1
            ativo = mapa_cnpj.get(cnpj_limpo)
            if ativo is None:
                nome_fundo = _normalizar_nome_fii(metricas.get("nome_fundo"))
                candidatos = []
                for alias, ativos in mapa_nome.items():
                    if alias in nome_fundo:
                        candidatos.extend(ativos)
                if len(candidatos) == 1:
                    ativo = candidatos[0]
            if ativo is None:
                resultado.sem_ativo += 1
                continue

            patrimonio = (
                _float_cvm(metricas["patrimonio_liquido"])
                if "patrimonio_liquido" in metricas
                else None
            )
            cotistas = (
                _int_cvm(metricas["cotistas"]) if "cotistas" in metricas else None
            )
            ativo_total = (
                _float_cvm(metricas["ativo_total"])
                if "ativo_total" in metricas
                else None
            )
            caixa = (
                _float_cvm(metricas["disponibilidades_caixa"])
                if "disponibilidades_caixa" in metricas
                else None
            )
            rendimento = (
                _float_cvm(metricas["rendimento_por_cota"])
                if "rendimento_por_cota" in metricas
                else None
            )
            cotas_emitidas = (
                _float_cvm(metricas["cotas_emitidas"])
                if "cotas_emitidas" in metricas
                else None
            )
            if rendimento is None:
                metricas.pop("rendimento_por_cota", None)

            try:
                registro = (
                    session.query(DadosFinanceirosFiis)
                    .filter_by(ativo_id=ativo.id, data_referencia=data_referencia)
                    .first()
                )
                if not registro:
                    registro = DadosFinanceirosFiis(
                        ativo_id=ativo.id, data_referencia=data_referencia
                    )
                    session.add(registro)
                if "patrimonio_liquido" in metricas:
                    registro.patrimonio_liquido = patrimonio
                if "cotistas" in metricas:
                    registro.cotistas = cotistas
                if "ativo_total" in metricas:
                    registro.ativo_total = ativo_total
                if "disponibilidades_caixa" in metricas:
                    registro.disponibilidades_caixa = caixa
                if "rendimento_por_cota" in metricas:
                    registro.rendimento_por_cota = rendimento
                if "cotas_emitidas" in metricas:
                    registro.cotas_emitidas = cotas_emitidas
                session.commit()
                resultado.gravados += 1
            except Exception as erro:
                session.rollback()
                resultado.falhas_persistencia += 1
                print(
                    f"Falha ao gravar informe FII {cnpj_limpo} "
                    f"{data_referencia}: {type(erro).__name__}"
                )

        resultado.informes_encontrados = informes_com_metrica
        if resultado.gravados > 0:
            resultado.status = STATUS_GRAVADO
        elif informes_com_metrica == 0:
            resultado.status = STATUS_SEM_INFORMES
        else:
            resultado.status = STATUS_SEM_ATIVOS
        return resultado
    except Exception as erro:
        print(f"Erro geral ao processar CSV de FIIs: {erro}")
        resultado.status = STATUS_ERRO
        resultado.erro = type(erro).__name__
        return resultado
    finally:
        if session_propria:
            session.close()
