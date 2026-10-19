"""Coleta de documentos de FIIs no FNET (B3).

Associa cada documento a um ``Ativo`` FII ja cadastrado (ticker e isca de
nome), nunca cria ``PENDENTE-*`` nem consulta Google Sheets. A FNET nao
entrega CNPJ; o ticker nao substitui CNPJ em outras coletas.
"""

import unicodedata
from datetime import datetime, timedelta

from config import MAPA_ISCAS_MASTER
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos, TipoAtivo

STATUS_SEM_INFORMES = "sem_informes"
STATUS_SEM_ATIVOS = "sem_ativos"
STATUS_SEM_NOVOS = "sem_novos"
STATUS_GRAVADO = "gravado"
STATUS_ERRO = "erro"

DIAS_PADRAO = 60


def normalizar_texto(texto):
    if texto is None:
        return ""
    sem_acento = "".join(
        c
        for c in unicodedata.normalize("NFD", str(texto))
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.upper().split())


class ResultadoVarreduraFnet:
    """Contagens da varredura FNET. Nao afirma sucesso se nada foi gravado."""

    def __init__(self, dias):
        self.dias = dias
        self.status = STATUS_ERRO
        self.informes_encontrados = 0
        self.gravados = 0
        self.ja_existentes = 0
        self.sem_ativo = 0
        self.ignorados_validacao = 0
        self.falhas_persistencia = 0
        self.erro = None

    def mensagem_telegram(self):
        janela = f"ultimos {self.dias} dia(s)"
        if self.status == STATUS_SEM_INFORMES:
            return (
                f"Varredura FNET de FIIs ({janela}): nenhum documento retornado "
                "pela B3. Nenhum documento gravado."
            )
        if self.status == STATUS_SEM_ATIVOS:
            return (
                f"Varredura FNET de FIIs ({janela}): {self.informes_encontrados} "
                "documento(s) na B3; nenhum nome corresponde a um FII cadastrado. "
                f"Sem ativo: {self.sem_ativo}. Ignorados: {self.ignorados_validacao}. "
                "Nenhum documento gravado."
            )
        if self.status == STATUS_SEM_NOVOS:
            return (
                f"Varredura FNET de FIIs ({janela}): {self.informes_encontrados} "
                "documento(s) na B3; nenhum documento novo. "
                f"Ja existentes: {self.ja_existentes}. Sem ativo: {self.sem_ativo}. "
                f"Ignorados: {self.ignorados_validacao}."
            )
        if self.status == STATUS_GRAVADO:
            return (
                f"Varredura FNET de FIIs ({janela}) concluida.\n"
                f"Documentos novos gravados: {self.gravados}\n"
                f"Documentos na B3: {self.informes_encontrados}\n"
                f"Ja existentes: {self.ja_existentes}\n"
                f"Sem ativo correspondente: {self.sem_ativo}\n"
                f"Ignorados por validacao: {self.ignorados_validacao}\n"
                f"Falhas de persistencia: {self.falhas_persistencia}"
            )
        detalhe = self.erro or "falha de processamento"
        return (
            f"Varredura FNET de FIIs ({janela}): falha de processamento ou "
            f"persistencia ({detalhe}). Gravados: {self.gravados}."
        )


def _iscas_do_ticker(ticker):
    iscas = [normalizar_texto(ticker)]
    extra = MAPA_ISCAS_MASTER.get(ticker)
    if extra:
        texto = normalizar_texto(extra)
        if texto and texto not in iscas:
            iscas.append(texto)
    return [i for i in iscas if i]


def _pares_fiis(session):
    pares = []
    consulta = session.query(Ativo).filter(Ativo.tipo == TipoAtivo.FII)
    for ativo in consulta:
        ticker = str(ativo.ticker or "").strip().upper()
        if not ticker:
            continue
        pares.append((ativo, _iscas_do_ticker(ticker)))
    return pares


def _encontrar_ativo(nome_fundo, pares):
    nome = normalizar_texto(nome_fundo)
    if not nome:
        return None
    for ativo, iscas in pares:
        for isca in iscas:
            if isca in nome:
                return ativo
    return None


def _parse_data_ref(valor):
    if valor is None:
        return None
    texto = str(valor).strip().replace("/", "-")
    if not texto:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto[:10], fmt).date()
        except (TypeError, ValueError):
            continue
    return None


class ColetorFnet:
    """Varredura FNET. Nao acessa Google Sheets nem Telegram."""

    def __init__(self, session=None, capturar_tudo=None):
        self.session = session
        self.capturar_tudo = capturar_tudo

    def coletar(self, dias=DIAS_PADRAO):
        resultado = ResultadoVarreduraFnet(dias)
        session_propria = self.session is None
        session = self.session
        if session_propria:
            from atualizador_documentos import SessionDB

            session = SessionDB()

        data_busca = (datetime.now() - timedelta(days=dias)).strftime("%d/%m/%Y")
        try:
            if self.capturar_tudo is not None:
                documentos = self.capturar_tudo(data_busca)
            else:
                from fnet_scraper import FnetDownloader

                documentos = FnetDownloader().capturar_tudo(data_busca)

            if not documentos:
                resultado.status = STATUS_SEM_INFORMES
                return resultado

            pares = _pares_fiis(session)
            vistos = set()

            for doc in documentos:
                id_doc = str(doc.get("id") or "").strip()
                nome_fundo = doc.get("nome_fundo")
                tipo_doc = str(doc.get("tipo_doc") or "").strip() or "Documento"
                data_pub = _parse_data_ref(doc.get("data_ref"))

                if not id_doc or data_pub is None:
                    resultado.ignorados_validacao += 1
                    continue
                if id_doc in vistos:
                    continue
                vistos.add(id_doc)

                resultado.informes_encontrados += 1
                ativo = _encontrar_ativo(nome_fundo, pares)
                if ativo is None:
                    resultado.sem_ativo += 1
                    continue

                try:
                    existe = (
                        session.query(DocumentosQualitativos)
                        .filter(DocumentosQualitativos.id_b3 == id_doc)
                        .first()
                    )
                    if existe:
                        resultado.ja_existentes += 1
                        continue
                    session.add(
                        DocumentosQualitativos(
                            ativo_id=ativo.id,
                            id_b3=id_doc,
                            data_publicacao=data_pub,
                            tipo_documento=tipo_doc,
                            assunto=str(doc.get("data_ref") or ""),
                            status_processamento="PENDENTE",
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
