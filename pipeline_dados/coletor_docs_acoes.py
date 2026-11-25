"""Coleta de documentos IPE de acoes da CVM (CSV em ZIP).

Associa cada documento ao ``Ativo`` pelo CNPJ cadastrado (coluna
``ativos.cnpj``), nunca pelo ticker. A coleta é limitada à janela móvel dos
últimos 30 dias. Nao baixa o PDF nesta etapa: grava a URL.
"""

import csv
import io
import zipfile
from datetime import date, datetime, timedelta

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

JANELA_DOCUMENTAL_DIAS = 30

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


def janela_documental(referencia=None, dias=JANELA_DOCUMENTAL_DIAS):
    """Retorna a janela móvel permitida para documentos de ações."""
    referencia = referencia or date.today()
    if isinstance(referencia, datetime):
        referencia = referencia.date()
    return referencia - timedelta(days=max(1, int(dias))), referencia


def janela_documental_30_dias(referencia=None):
    """Compatibilidade para consumidores antigos e testes da janela padrão."""
    return janela_documental(referencia, JANELA_DOCUMENTAL_DIAS)


def janela_trimestral_documentos(referencia=None):
    """Compatibilidade: a coleta documental agora é limitada a 30 dias."""
    return janela_documental_30_dias(referencia)


class ResultadoColetaDocs:
    """Contagens da varredura IPE. Nao afirma sucesso se nada foi gravado."""

    def __init__(self, ano, data_inicio=None, data_fim=None):
        self.ano = ano
        self.data_inicio = data_inicio
        self.data_fim = data_fim
        self.status = STATUS_ERRO
        self.http_status = None
        self.informes_encontrados = 0
        self.gravados = 0
        self.ja_existentes = 0
        self.sem_ativo = 0
        self.ignorados_validacao = 0
        self.falhas_persistencia = 0
        self.erro = None
        self.documentos_novos = []
        self.por_ativo = {}

    def registrar_documento_novo(self, ticker, tipo, data, origem):
        bloco = self.por_ativo.setdefault(str(ticker), {"ticker": str(ticker), "novos": 0, "documentos": []})
        bloco["novos"] += 1
        item = {"ticker": str(ticker), "tipo": str(tipo), "data": data.isoformat() if data else None, "origem": str(origem)}
        if len(bloco["documentos"]) < 30:
            bloco["documentos"].append(item)
        if len(self.documentos_novos) < 120:
            self.documentos_novos.append(item)

    def detalhes_painel(self):
        return {"ano": self.ano,
                "data_inicio": self.data_inicio.isoformat() if self.data_inicio else None,
                "data_fim": self.data_fim.isoformat() if self.data_fim else None,
                "status": self.status, "documentos_arquivo": self.informes_encontrados,
                "novos": self.gravados, "ja_existentes": self.ja_existentes, "sem_ativo": self.sem_ativo,
                "falhas_persistencia": self.falhas_persistencia, "ativos": list(self.por_ativo.values()),
                "documentos": self.documentos_novos}

    def mensagem_telegram(self):
        ano = (
            f"{self.data_inicio.strftime('%d/%m/%Y')} a {self.data_fim.strftime('%d/%m/%Y')}"
            if self.data_inicio and self.data_fim else str(self.ano)
        )
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
    from services.cadastro_cnpj_oficial import ler_cadastro
    oficiais = ler_cadastro(session)
    mapa = {}
    consulta = session.query(Ativo).filter(Ativo.tipo == TipoAtivo.ACAO)
    for ativo in consulta:
        oficial = oficiais.get(str(ativo.ticker or "").upper())
        chave = oficial["cnpj"] if oficial else normalizar_cnpj(ativo.cnpj)
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

    def vasculhar_documentos(self, ano=None, ticker=None, data_inicio=None,
                             data_fim=None):
        session_propria = self.session is None
        session = self.session
        if session_propria:
            from atualizador_documentos import SessionDB

            session = SessionDB()

        from services.configuracoes_sistema import obter_janela_documentos_dias
        dias_configurados = obter_janela_documentos_dias(session)
        if data_fim is None:
            data_inicio, data_fim = janela_documental(dias=dias_configurados)
        else:
            limite_inicio, data_fim = janela_documental(data_fim, dias_configurados)
            data_inicio = max(data_inicio or limite_inicio, limite_inicio)
        if data_inicio and data_fim and data_inicio > data_fim:
            raise ValueError("data_inicio deve ser anterior ou igual a data_fim")
        anos = (
            list(range(data_inicio.year, data_fim.year + 1))
            if data_inicio and data_fim else [ano or ano_padrao_coleta()]
        )
        ano_resultado = anos[0] if len(anos) == 1 else f"{anos[0]}-{anos[-1]}"
        resultado = ResultadoColetaDocs(ano_resultado, data_inicio, data_fim)
        ticker_filtro = str(ticker or "").strip().upper() or None
        obter = self.http_get if self.http_get is not None else requests.get

        try:
            linhas = []
            for ano_consulta in anos:
                resposta = obter(URL_IPE.format(ano=ano_consulta), timeout=40)
                resultado.http_status = getattr(resposta, "status_code", None)
                if resultado.http_status != 200:
                    resultado.status = STATUS_ARQUIVO_INDISPONIVEL
                    return resultado

                try:
                    linhas_ano = _ler_zip_ipe(resposta.content)
                except zipfile.BadZipFile:
                    resultado.status = STATUS_ARQUIVO_INVALIDO
                    return resultado
                except Exception as erro:
                    resultado.status = STATUS_ARQUIVO_INVALIDO
                    resultado.erro = type(erro).__name__
                    return resultado

                if linhas_ano is None:
                    resultado.status = STATUS_ARQUIVO_INVALIDO
                    return resultado
                linhas.extend(linhas_ano)

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
                if data_inicio and data_pub < data_inicio:
                    continue
                if data_fim and data_pub > data_fim:
                    continue

                ativo = mapa_cnpj.get(cnpj_limpo)
                if ativo is None:
                    if ticker_filtro:
                        continue
                    resultado.informes_encontrados += 1
                    resultado.sem_ativo += 1
                    continue
                if ticker_filtro and str(ativo.ticker or "").upper() != ticker_filtro:
                    continue
                resultado.informes_encontrados += 1

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
                    resultado.registrar_documento_novo(ativo.ticker, categoria, data_pub, link_pdf)
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

