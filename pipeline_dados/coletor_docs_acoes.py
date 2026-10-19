"""Coleta de documentos IPE de acoes da CVM (CSV em ZIP).

Associa cada documento ao ``Ativo`` pelo CNPJ cadastrado (coluna
``ativos.cnpj``), nunca pelo ticker. O ano vem do chamador; o padrao, se
omitido, e o ano civil corrente. Nao baixa o PDF nesta etapa: grava a URL.
"""

import csv
import io
import zipfile
from datetime import datetime

import requests

from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos, TipoAtivo
from pipeline_dados.coletor_fiis import ano_padrao_coleta, normalizar_cnpj

STATUS_ARQUIVO_INDISPONIVEL = "arquivo_indisponivel"
STATUS_ARQUIVO_INVALIDO = "arquivo_invalido"
STATUS_SEM_INFORMES = "sem_informes"
STATUS_SEM_ATIVOS = "sem_ativos"
STATUS_SEM_NOVOS = "sem_novos"
STATUS_GRAVADO = "gravado"
STATUS_ERRO = "erro"

URL_IPE = (
    "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/"
    "ipe_cia_aberta_{ano}.zip"
)

TIPOS_DESEJADOS = frozenset(
    {
        "Fato Relevante",
        "Aviso aos Acionistas",
        "Comunicado ao Mercado",
        "Apresentação de Resultados",
        "Demonstrações Financeiras",
        "Relatório da Administração",
        "Assembleia",
        "Formulário de Referência",
    }
)


class ResultadoColetaDocs:
    """Contagens da varredura IPE. Nao afirma sucesso se nada foi gravado."""

    def __init__(self, ano):
        self.ano = ano
        self.status = STATUS_ERRO
        self.http_status = None
        self.informes_encontrados = 0
        self.gravados = 0
        self.ja_existentes = 0
        self.sem_ativo = 0
        self.ignorados_validacao = 0
        self.falhas_persistencia = 0
        self.erro = None

    def mensagem_telegram(self):
        ano = self.ano
        if self.status == STATUS_ARQUIVO_INDISPONIVEL:
            codigo = self.http_status if self.http_status is not None else "—"
            return (
                f"Varredura de PDFs de acoes ({ano}): arquivo nao obtido na CVM "
                f"(HTTP {codigo}). Nenhum documento gravado."
            )
        if self.status == STATUS_ARQUIVO_INVALIDO:
            return (
                f"Varredura de PDFs de acoes ({ano}): arquivo obtido, mas invalido "
                "(ZIP/CSV ilegivel). Nenhum documento gravado."
            )
        if self.status == STATUS_SEM_INFORMES:
            return (
                f"Varredura de PDFs de acoes ({ano}): arquivo obtido, porem nenhum "
                "documento valido foi encontrado. Nenhum documento gravado."
            )
        if self.status == STATUS_SEM_ATIVOS:
            return (
                f"Varredura de PDFs de acoes ({ano}): {self.informes_encontrados} "
                "documento(s) no arquivo; nenhum CNPJ corresponde a uma acao "
                f"cadastrada. Sem ativo: {self.sem_ativo}. "
                f"Ignorados: {self.ignorados_validacao}. Nenhum documento gravado."
            )
        if self.status == STATUS_SEM_NOVOS:
            return (
                f"Varredura de PDFs de acoes ({ano}): {self.informes_encontrados} "
                "documento(s) no arquivo; nenhum documento novo. "
                f"Ja existentes: {self.ja_existentes}. Sem ativo: {self.sem_ativo}. "
                f"Ignorados: {self.ignorados_validacao}."
            )
        if self.status == STATUS_GRAVADO:
            return (
                f"Varredura de PDFs de acoes ({ano}) concluida.\n"
                f"Documentos novos gravados: {self.gravados}\n"
                f"Documentos no arquivo: {self.informes_encontrados}\n"
                f"Ja existentes: {self.ja_existentes}\n"
                f"Sem ativo correspondente: {self.sem_ativo}\n"
                f"Ignorados por validacao: {self.ignorados_validacao}\n"
                f"Falhas de persistencia: {self.falhas_persistencia}"
            )
        detalhe = self.erro or "falha de processamento"
        return (
            f"Varredura de PDFs de acoes ({ano}): falha de processamento ou "
            f"persistencia ({detalhe}). Gravados: {self.gravados}."
        )


def _coluna(nomes, trecho, padrao):
    for nome in nomes:
        if trecho in nome.upper():
            return nome
    return padrao


def _ler_zip_ipe(conteudo):
    with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
        nomes = [n for n in pacote.namelist() if n.lower().endswith(".csv")]
        if not nomes:
            return None
        linhas = []
        for nome in nomes:
            with pacote.open(nome) as arquivo:
                leitor = csv.DictReader(
                    io.TextIOWrapper(arquivo, encoding="latin1"),
                    delimiter=";",
                )
                campos = leitor.fieldnames or []
                col_cnpj = _coluna(campos, "CNPJ", "CNPJ_Companhia")
                col_link = _coluna(campos, "LINK", "Link_Download")
                col_data = _coluna(campos, "DATA", "Data_Referencia")
                col_categoria = _coluna(campos, "CATEGORIA", "Categoria")
                col_assunto = _coluna(campos, "ASSUNTO", "Assunto")
                for linha in leitor:
                    linhas.append(
                        {
                            "cnpj": linha.get(col_cnpj),
                            "link": linha.get(col_link),
                            "data": linha.get(col_data),
                            "categoria": linha.get(col_categoria),
                            "assunto": linha.get(col_assunto),
                        }
                    )
        return linhas


def _mapa_acoes_por_cnpj(session):
    mapa = {}
    consulta = session.query(Ativo).filter(Ativo.tipo == TipoAtivo.ACAO)
    for ativo in consulta:
        chave = normalizar_cnpj(ativo.cnpj)
        if chave is None:
            continue
        if chave not in mapa:
            mapa[chave] = ativo
    return mapa


class RelatoriosAcoesCVM:
    """Varredura IPE. Nao acessa Google Sheets nem Telegram."""

    def __init__(self, session=None, http_get=None):
        self.session = session
        self.http_get = http_get

    def vasculhar_documentos(self, ano=None):
        if ano is None:
            ano = ano_padrao_coleta()
        resultado = ResultadoColetaDocs(ano)
        session_propria = self.session is None
        obter = self.http_get if self.http_get is not None else requests.get
        session = self.session

        if session_propria:
            from atualizador_documentos import SessionDB

            session = SessionDB()

        url = URL_IPE.format(ano=ano)
        try:
            resposta = obter(url, timeout=40)
            resultado.http_status = getattr(resposta, "status_code", None)
            if resultado.http_status != 200:
                resultado.status = STATUS_ARQUIVO_INDISPONIVEL
                return resultado

            try:
                linhas = _ler_zip_ipe(resposta.content)
            except zipfile.BadZipFile:
                resultado.status = STATUS_ARQUIVO_INVALIDO
                return resultado
            except Exception as erro:
                resultado.status = STATUS_ARQUIVO_INVALIDO
                resultado.erro = type(erro).__name__
                return resultado

            if linhas is None:
                resultado.status = STATUS_ARQUIVO_INVALIDO
                return resultado

            mapa_cnpj = _mapa_acoes_por_cnpj(session)

            for linha in linhas:
                categoria = str(linha.get("categoria") or "").strip()
                if categoria not in TIPOS_DESEJADOS:
                    continue

                cnpj_limpo = normalizar_cnpj(linha.get("cnpj"))
                link_pdf = str(linha.get("link") or "").strip()
                data_doc_str = str(linha.get("data") or "").strip()
                assunto = str(linha.get("assunto") or "").strip() or None

                if cnpj_limpo is None or not link_pdf:
                    resultado.ignorados_validacao += 1
                    continue

                try:
                    data_limpa = data_doc_str.split(" ")[0]
                    data_pub = datetime.strptime(data_limpa, "%Y-%m-%d").date()
                except (TypeError, ValueError):
                    resultado.ignorados_validacao += 1
                    continue

                resultado.informes_encontrados += 1
                ativo = mapa_cnpj.get(cnpj_limpo)
                if ativo is None:
                    resultado.sem_ativo += 1
                    continue

                try:
                    existe = (
                        session.query(DocumentosQualitativos)
                        .filter(DocumentosQualitativos.url_pdf == link_pdf)
                        .first()
                    )
                    if existe:
                        resultado.ja_existentes += 1
                        continue
                    session.add(
                        DocumentosQualitativos(
                            ativo_id=ativo.id,
                            data_publicacao=data_pub,
                            tipo_documento=categoria,
                            url_pdf=link_pdf,
                            assunto=assunto,
                            status_processamento="PENDENTE_ACAO",
                        )
                    )
                    session.commit()
                    resultado.gravados += 1
                except Exception:
                    session.rollback()
                    resultado.falhas_persistencia += 1

            if resultado.gravados > 0:
                resultado.status = STATUS_GRAVADO
            elif resultado.ja_existentes > 0:
                resultado.status = STATUS_SEM_NOVOS
            elif resultado.informes_encontrados == 0:
                resultado.status = STATUS_SEM_INFORMES
            else:
                resultado.status = STATUS_SEM_ATIVOS
            return resultado
        except Exception as erro:
            resultado.status = STATUS_ERRO
            resultado.erro = type(erro).__name__
            return resultado
        finally:
            if session_propria and session is not None:
                session.close()
