"""Repositorio do catalogo central de empresas, ativos e taxonomia.

Regras principais:

* nao cria nem altera tabelas: a infraestrutura e aplicada por migracoes
  manuais (``0005``/``0006``);
* ``ativos`` continua sendo a fonte dos dados financeiros por ticker. O
  repositorio apenas associa tickers existentes (ou criados a partir de uma
  fonte oficial) a uma ``empresa``;
* duplicidades de setor/subsetor/atividade/empresa sao evitadas por chave
  normalizada e pelas restricoes do banco;
* reclassificacoes nao apagam o passado: a linha anterior vira
  ``vigente=False`` e ``status='historico'``;
* falhas de banco sao propagadas nos metodos de escrita para que o chamador
  possa abortar a operacao sem estado parcial.

O modulo nao abre conexao ao ser importado. A sessao e criada sob demanda.
"""

import json
import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from pipeline_dados.banco_dados import Ativo, TipoAtivo
from pipeline_dados.conexao import obter_session_factory
from pipeline_dados.modelos_catalogo import (
    STATUS_CONFIRMADA,
    STATUS_HISTORICO,
    STATUS_SUGESTAO_APLICADA,
    STATUS_SUGESTAO_APROVADA,
    STATUS_SUGESTAO_DUPLICADA,
    STATUS_SUGESTAO_PENDENTE,
    STATUS_SUGESTAO_REJEITADA,
    AtividadeEconomica,
    Empresa,
    EmpresaAtividade,
    EmpresaAtivo,
    EmpresaSegmento,
    Setor,
    Subsetor,
    SugestaoCatalogo,
)
from pipeline_dados.taxonomia_catalogo import (
    chave_semantica,
    resolver_setor,
    resolver_subsetor,
)

logger = logging.getLogger("robo.catalogo")
logger_auditoria = logging.getLogger("robo.catalogo.auditoria")

TIPO_ATIVO_MAPA = {"acao": TipoAtivo.ACAO, "fii": TipoAtivo.FII}
TIPO_ATIVO_INVERSO = {TipoAtivo.ACAO: "acao", TipoAtivo.FII: "fii"}

# Codigo de negociacao da B3: raiz de 4 caracteres alfanumericos seguida de
# 1-2 digitos. A raiz pode conter digitos (ex.: ``B3SA3``), por isso nao se usa
# ``[A-Z]{4}``. Exige ao menos uma letra para nao aceitar apenas numeros.
PADRAO_TICKER_NEGOCIACAO = re.compile(
    r"^(?=.*[A-Z])[A-Z0-9]{4}\d{1,2}$"
)


class ConflitoVinculoAtivo(ValueError):
    """Um ativo ja esta vinculado a outra empresa; nao ha escolha arbitraria."""


class ConflitoEmpresa(ValueError):
    """Dados de identidade conflitam com um cadastro existente."""


class DecisaoSugestaoInvalida(ValueError):
    """Tentativa de decidir uma sugestao fora do estado ``pendente``."""


# Uma sugestao em "aprovada" pode estar sendo aplicada por outro processo. Se
# ela ficar presa nesse estado (processo interrompido), so pode ser retomada
# depois deste intervalo, com uma reivindicacao atomica.
LIMITE_RETOMADA_APROVACAO_SEGUNDOS = 300
ESPERA_APLICACAO_SEGUNDOS = 5.0

PRECEDENCIA_FONTES = {
    "cvm": 100,
    "fca": 100,
    "b3": 80,
    "mapa_setores_b3": 80,
    "ia": 40,
    "llm": 40,
}


def precedencia_fonte(fonte):
    """Ranking de confianca da fonte para reclassificacoes setoriais.

    A CVM (cadastro oficial) prevalece sobre o mapa B3, que por sua vez prevalece
    sobre sugestoes de IA. Fontes desconhecidas ficam no nivel neutro para nao
    bloquear operacoes administrativas explicitas.
    """
    texto = str(fonte or "").casefold()
    if not texto:
        return 50
    for marcador, peso in PRECEDENCIA_FONTES.items():
        if marcador in texto:
            return peso
    return 50


def somente_digitos(valor):
    return "".join(c for c in str(valor or "") if c.isdigit())


def normalizar_cnpj(cnpj):
    """Retorna o CNPJ no formato da CVM (XX.XXX.XXX/XXXX-XX) ou ``None``."""
    digitos = somente_digitos(cnpj)
    if len(digitos) != 14:
        return None
    return (
        f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/"
        f"{digitos[8:12]}-{digitos[12:]}"
    )


def normalizar_ticker(ticker):
    """Normaliza ticker/callback (``MXRF11_fii`` -> ``MXRF11``)."""
    if ticker is None:
        return ""
    texto = str(ticker).strip().upper().split("_", 1)[0]
    return re.sub(r"[^A-Z0-9]", "", texto)


def ticker_negociacao_valido(ticker):
    """Valida o formato de um codigo de negociacao da B3.

    Aceita raizes alfanumericas (``B3SA3``, ``PETR4``, ``MXRF11``) e recusa
    textos arbitrarios que nao tenham o formato de codigo de bolsa.
    """
    return bool(PADRAO_TICKER_NEGOCIACAO.fullmatch(normalizar_ticker(ticker)))


def normalizar_texto(valor):
    """Minusculo e sem acentos, para comparacoes de nome."""
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().casefold()


def gerar_slug(valor):
    texto = normalizar_texto(valor)
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    return texto or "sem-nome"


def _slug_taxonomia(valor):
    """Slug semantico para setor/subsetor/atividade.

    Usa a mesma chave tolerante a acentos, artigos e ``&`` da taxonomia, de
    modo que variacoes equivalentes nao criem linhas duplicadas no catalogo.
    """
    return chave_semantica(valor) or gerar_slug(valor)


class EmpresaDTO:
    """Representacao desanexada de uma empresa para uso fora da sessao."""

    __slots__ = (
        "id",
        "cnpj",
        "nome",
        "razao_social",
        "nome_comercial",
        "situacao",
        "fonte",
    )

    def __init__(self, id, cnpj, nome, razao_social=None, nome_comercial=None,
                 situacao=None, fonte=None):
        self.id = id
        self.cnpj = cnpj
        self.nome = nome
        self.razao_social = razao_social
        self.nome_comercial = nome_comercial
        self.situacao = situacao
        self.fonte = fonte

    def __repr__(self):  # pragma: no cover - diagnostico
        return f"EmpresaDTO(id={self.id!r}, cnpj={self.cnpj!r}, nome={self.nome!r})"


class RepositorioCatalogo:
    """Operacoes de leitura/escrita do catalogo central."""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory

    def _nova_sessao(self):
        factory = self._session_factory or obter_session_factory()
        return factory()

    # ------------------------------------------------------------------
    # Taxonomia
    # ------------------------------------------------------------------

    def obter_ou_criar_setor(self, nome, fonte=None):
        nome = str(nome or "").strip()
        if not nome:
            raise ValueError("Nome do setor e obrigatorio.")
        # Canonicaliza aliases conhecidos (CVM/B3) para nao criar duplicatas
        # semanticas como "Petroleo e Gas" e "Petroleo, Gas & Biocombustiveis".
        nome = resolver_setor(nome) or nome
        slug = _slug_taxonomia(nome)
        session = self._nova_sessao()
        try:
            setor = session.query(Setor).filter(Setor.slug == slug).first()
            if setor is None:
                setor = Setor(nome=nome, slug=slug, fonte=fonte)
                session.add(setor)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    setor = session.query(Setor).filter(Setor.slug == slug).first()
                    if setor is None:
                        raise
            elif fonte and not setor.fonte:
                setor.fonte = fonte
                session.commit()
            session.refresh(setor)
            return setor.id
        finally:
            session.close()

    def obter_setor_por_nome(self, nome):
        nome = resolver_setor(nome) or str(nome or "").strip()
        slug = _slug_taxonomia(nome)
        if not slug:
            return None
        session = self._nova_sessao()
        try:
            setor = session.query(Setor).filter(Setor.slug == slug).first()
            return setor.id if setor else None
        finally:
            session.close()

    @staticmethod
    def _canonicalizar_subsetor(session, setor_id, nome):
        setor = session.query(Setor).filter(Setor.id == int(setor_id)).first()
        if setor is None:
            raise ValueError("Setor inexistente.")
        return (
            resolver_subsetor(setor.nome, nome)
            or str(nome or "").strip()
        )

    def obter_subsetor_por_nome(self, setor_id, nome):
        session = self._nova_sessao()
        try:
            nome = self._canonicalizar_subsetor(session, setor_id, nome)
            slug = _slug_taxonomia(nome)
            subsetor = (
                session.query(Subsetor)
                .filter(Subsetor.setor_id == int(setor_id), Subsetor.slug == slug)
                .first()
            )
            return subsetor.id if subsetor else None
        finally:
            session.close()

    def obter_atividade_por_nome(self, nome):
        slug = _slug_taxonomia(nome)
        session = self._nova_sessao()
        try:
            atividade = (
                session.query(AtividadeEconomica)
                .filter(AtividadeEconomica.slug == slug)
                .first()
            )
            return atividade.id if atividade else None
        finally:
            session.close()

    def obter_ou_criar_subsetor(self, setor_id, nome, fonte=None):
        nome = str(nome or "").strip()
        if not nome:
            raise ValueError("Nome do subsetor e obrigatorio.")
        session = self._nova_sessao()
        try:
            nome = self._canonicalizar_subsetor(session, setor_id, nome)
            slug = _slug_taxonomia(nome)
            subsetor = (
                session.query(Subsetor)
                .filter(Subsetor.setor_id == setor_id, Subsetor.slug == slug)
                .first()
            )
            if subsetor is None:
                subsetor = Subsetor(
                    setor_id=setor_id, nome=nome, slug=slug, fonte=fonte
                )
                session.add(subsetor)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    subsetor = (
                        session.query(Subsetor)
                        .filter(
                            Subsetor.setor_id == setor_id, Subsetor.slug == slug
                        )
                        .first()
                    )
                    if subsetor is None:
                        raise
            session.refresh(subsetor)
            return subsetor.id
        finally:
            session.close()

    def obter_ou_criar_atividade(self, nome, fonte=None, codigo_cnae=None,
                                 evidencia=None):
        nome = str(nome or "").strip()
        if not nome:
            raise ValueError("Nome da atividade e obrigatorio.")
        slug = _slug_taxonomia(nome)
        session = self._nova_sessao()
        try:
            atividade = (
                session.query(AtividadeEconomica)
                .filter(AtividadeEconomica.slug == slug)
                .first()
            )
            if atividade is None:
                atividade = AtividadeEconomica(
                    nome=nome,
                    slug=slug,
                    fonte=fonte,
                    codigo_cnae=codigo_cnae,
                    evidencia=evidencia,
                )
                session.add(atividade)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    atividade = (
                        session.query(AtividadeEconomica)
                        .filter(AtividadeEconomica.slug == slug)
                        .first()
                    )
                    if atividade is None:
                        raise
            else:
                alterou = False
                if fonte and not atividade.fonte:
                    atividade.fonte = fonte
                    alterou = True
                if codigo_cnae and not atividade.codigo_cnae:
                    atividade.codigo_cnae = codigo_cnae
                    alterou = True
                if alterou:
                    session.commit()
            session.refresh(atividade)
            return atividade.id
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Empresas e ativos
    # ------------------------------------------------------------------

    def obter_empresa_por_cnpj(self, cnpj):
        cnpj_normalizado = normalizar_cnpj(cnpj)
        if cnpj_normalizado is None:
            return None
        session = self._nova_sessao()
        try:
            empresa = (
                session.query(Empresa)
                .filter(Empresa.cnpj == cnpj_normalizado)
                .first()
            )
            return self._empresa_dto(empresa)
        finally:
            session.close()

    @staticmethod
    def _candidatos_por_nome(session, nome):
        alvo = str(nome or "").strip().casefold()
        if not alvo:
            return []
        return (
            session.query(Empresa)
            .filter(
                or_(
                    func.lower(func.trim(Empresa.nome)) == alvo,
                    func.lower(func.trim(Empresa.razao_social)) == alvo,
                )
            )
            .order_by(Empresa.id.asc())
            .all()
        )

    def obter_empresa_por_nome(self, nome):
        alvo = str(nome or "").strip()
        if not alvo:
            return None
        session = self._nova_sessao()
        try:
            candidatos = self._candidatos_por_nome(session, alvo)
            if len(candidatos) > 1:
                # Qualquer segundo cadastro com o mesmo nome e ambiguidade,
                # inclusive quando um tem CNPJ e outro nao: escolher o menor id
                # aqui poderia fundir empresas diferentes por coincidencia.
                raise ConflitoEmpresa(
                    "Nome de empresa ambiguo: ha mais de um cadastro para o "
                    "mesmo nome (com ou sem CNPJ); e necessaria revisao "
                    "manual."
                )
            return self._empresa_dto(candidatos[0]) if candidatos else None
        finally:
            session.close()

    @staticmethod
    def _empresa_dto(empresa):
        if empresa is None:
            return None
        return EmpresaDTO(
            id=empresa.id,
            cnpj=empresa.cnpj,
            nome=empresa.nome,
            razao_social=empresa.razao_social,
            nome_comercial=empresa.nome_comercial,
            situacao=empresa.situacao,
            fonte=empresa.fonte,
        )

    @classmethod
    def _resolver_candidata_existente(cls, session, nome, cnpj_normalizado):
        """Escolhe uma empresa existente sem fundir CNPJs diferentes.

        Regras:
        * CNPJ valido e a chave preferencial;
        * coincidencia de nome so pode ser usada quando nao ha CNPJ oficial
          conflitante;
        * mais de um cadastro sem CNPJ para o mesmo nome e ambiguidade, nao um
          convite para escolher o primeiro.
        """
        if cnpj_normalizado:
            por_cnpj = (
                session.query(Empresa)
                .filter(Empresa.cnpj == cnpj_normalizado)
                .first()
            )
            if por_cnpj is not None:
                return por_cnpj

        candidatos = cls._candidatos_por_nome(session, nome)
        if not candidatos:
            return None

        if cnpj_normalizado:
            conflitantes = [
                empresa
                for empresa in candidatos
                if empresa.cnpj and empresa.cnpj != cnpj_normalizado
            ]
            if conflitantes:
                raise ConflitoEmpresa(
                    "Ja existe empresa com este nome e CNPJ diferente; "
                    "os cadastros nao podem ser fundidos por coincidencia "
                    "de nome."
                )
            sem_cnpj = [empresa for empresa in candidatos if not empresa.cnpj]
            if len(sem_cnpj) > 1:
                raise ConflitoEmpresa(
                    "Ha mais de um cadastro sem CNPJ com este nome; "
                    "e necessaria revisao manual."
                )
            return sem_cnpj[0] if sem_cnpj else None

        # Sem CNPJ informado: so aceita coincidencia de nome quando ha um
        # unico cadastro. Dois cadastros com o mesmo nome sao ambiguidade,
        # mesmo que um deles ainda nao tenha CNPJ confirmado.
        if len(candidatos) > 1:
            raise ConflitoEmpresa(
                "Nome de empresa ambiguo; e necessaria revisao manual."
            )
        return candidatos[0]

    def obter_ou_criar_empresa(self, nome, cnpj=None, razao_social=None,
                               nome_comercial=None, situacao=None, fonte=None,
                               evidencia=None):
        """Upsert idempotente por CNPJ (preferencial) ou nome.

        Retorna ``(empresa_dto, criada)``. Nao cria empresa sem nome. CNPJ
        invalido e ignorado (jamais se inventa um identificador oficial). Uma
        empresa sem CNPJ confirmado permanece com ``cnpj=None`` e pode receber
        o CNPJ oficial depois, desde que nao haja conflito.
        """
        nome = str(nome or "").strip()
        cnpj_normalizado = normalizar_cnpj(cnpj)
        if not nome:
            raise ValueError("Nome da empresa e obrigatorio.")

        session = self._nova_sessao()
        try:
            empresa = self._resolver_candidata_existente(
                session, nome, cnpj_normalizado
            )

            if empresa is None:
                empresa = Empresa(
                    cnpj=cnpj_normalizado,
                    nome=nome,
                    razao_social=razao_social or nome,
                    nome_comercial=nome_comercial,
                    situacao=situacao,
                    fonte=fonte,
                    evidencia=evidencia,
                )
                session.add(empresa)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    empresa = self._resolver_candidata_existente(
                        session, nome, cnpj_normalizado
                    )
                    if empresa is None:
                        raise
                else:
                    session.refresh(empresa)
                    return self._empresa_dto(empresa), True

            # Atualizacao conservadora: so preenche campos vazios. Nunca apaga
            # informação existente nem troca um CNPJ oficial por outro.
            alterou = False
            for campo, valor in (
                ("razao_social", razao_social),
                ("nome_comercial", nome_comercial),
                ("situacao", situacao),
            ):
                if valor and not getattr(empresa, campo):
                    setattr(empresa, campo, valor)
                    alterou = True
            if cnpj_normalizado and not empresa.cnpj:
                empresa.cnpj = cnpj_normalizado
                alterou = True
            if fonte and not empresa.fonte:
                empresa.fonte = fonte
                alterou = True
            if evidencia and not empresa.evidencia:
                empresa.evidencia = evidencia
                alterou = True
            if alterou:
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    # Outra sessao pode ter gravado o mesmo CNPJ/nome. Releia e
                    # valide a identidade antes de devolver qualquer resultado.
                    empresa = self._resolver_candidata_existente(
                        session, nome, cnpj_normalizado
                    )
                    if empresa is None:
                        raise
                    else:
                        session.refresh(empresa)
            else:
                session.refresh(empresa)
            return self._empresa_dto(empresa), False
        finally:
            session.close()

    def obter_empresa_por_ticker(self, ticker):
        chave = normalizar_ticker(ticker)
        if not chave:
            return None
        session = self._nova_sessao()
        try:
            empresas = (
                session.query(Empresa)
                .join(EmpresaAtivo, EmpresaAtivo.empresa_id == Empresa.id)
                .join(Ativo, Ativo.id == EmpresaAtivo.ativo_id)
                .filter(Ativo.ticker == chave)
                .order_by(Empresa.id.asc())
                .all()
            )
            if len(empresas) > 1:
                raise ConflitoVinculoAtivo(
                    f"O ativo {chave} possui mais de uma empresa vinculada; "
                    "e necessaria revisao manual antes de continuar."
                )
            return self._empresa_dto(empresas[0]) if empresas else None
        finally:
            session.close()

    def obter_empresa_id_por_ticker(self, ticker):
        empresa = self.obter_empresa_por_ticker(ticker)
        return empresa.id if empresa else None

    def obter_tickers_da_empresa(self, empresa_id):
        try:
            empresa_id = int(empresa_id)
        except (TypeError, ValueError):
            return []
        session = self._nova_sessao()
        try:
            linhas = (
                session.query(Ativo.ticker)
                .join(EmpresaAtivo, EmpresaAtivo.ativo_id == Ativo.id)
                .filter(EmpresaAtivo.empresa_id == empresa_id)
                .order_by(Ativo.ticker.asc())
                .all()
            )
            return [ticker for (ticker,) in linhas]
        finally:
            session.close()

    @staticmethod
    def _vinculo_do_ativo(session, ativo_id):
        return (
            session.query(EmpresaAtivo)
            .filter(EmpresaAtivo.ativo_id == ativo_id)
            .first()
        )

    def vincular_ativo(self, empresa_id, ticker, fonte=None, evidencia=None,
                       criar_ativo=False, tipo="acao"):
        """Associa um ticker a no maximo UMA empresa.

        Por padrao NAO cria o ativo: o ticker precisa existir em ``ativos`` ou
        ser criado explicitamente por um importador de fonte oficial. Quando
        ``criar_ativo=True``, o CNPJ financeiro recebe o placeholder
        ``PENDENTE-<TICKER>`` porque a coluna legada exige unicidade por ativo e
        o CNPJ real pertence a empresa (que pode ter varios tickers).

        Se o ativo ja estiver vinculado a OUTRA empresa, levanta
        :class:`ConflitoVinculoAtivo`; o vinculo existente nunca e trocado
        silenciosamente.
        """
        chave = normalizar_ticker(ticker)
        if not chave:
            return None
        try:
            empresa_id = int(empresa_id)
        except (TypeError, ValueError):
            return None

        session = self._nova_sessao()
        try:
            empresa_existe = (
                session.query(Empresa.id)
                .filter(Empresa.id == empresa_id)
                .first()
            )
            if empresa_existe is None:
                return None

            ativo = session.query(Ativo).filter(Ativo.ticker == chave).first()
            if ativo is None:
                if not criar_ativo:
                    return None
                tipo_enum = TIPO_ATIVO_MAPA.get(str(tipo or "acao").lower())
                if tipo_enum is None:
                    tipo_enum = TipoAtivo.ACAO
                ativo = Ativo(
                    ticker=chave,
                    cnpj=f"PENDENTE-{chave}",
                    tipo=tipo_enum,
                )
                session.add(ativo)
                try:
                    session.flush()
                except IntegrityError:
                    session.rollback()
                    ativo = (
                        session.query(Ativo)
                        .filter(Ativo.ticker == chave)
                        .first()
                    )
                    if ativo is None:
                        raise

            vinculo = self._vinculo_do_ativo(session, ativo.id)
            if vinculo is not None:
                if vinculo.empresa_id != empresa_id:
                    raise ConflitoVinculoAtivo(
                        f"O ativo {chave} ja esta vinculado a empresa "
                        f"{vinculo.empresa_id}; vinculo com {empresa_id} "
                        "recusado."
                    )
                alterou = False
                if fonte and not vinculo.fonte:
                    vinculo.fonte = fonte
                    alterou = True
                if evidencia and not vinculo.evidencia:
                    vinculo.evidencia = evidencia
                    alterou = True
                if alterou:
                    session.commit()
                return ativo.id

            vinculo = EmpresaAtivo(
                empresa_id=empresa_id,
                ativo_id=ativo.id,
                fonte=fonte,
                evidencia=evidencia,
            )
            session.add(vinculo)
            try:
                # Um unico commit cobre a criacao do ativo (quando houver) e o
                # vinculo, evitando estado parcial.
                session.commit()
            except IntegrityError:
                session.rollback()
                ativo = (
                    session.query(Ativo)
                    .filter(Ativo.ticker == chave)
                    .first()
                )
                if ativo is None:
                    raise
                vinculo = self._vinculo_do_ativo(session, ativo.id)
                if vinculo is None:
                    raise
                if vinculo.empresa_id != empresa_id:
                    raise ConflitoVinculoAtivo(
                        f"O ativo {chave} ja esta vinculado a empresa "
                        f"{vinculo.empresa_id}; vinculo com {empresa_id} "
                        "recusado."
                    )
            return ativo.id
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Classificacoes (com historico)
    # ------------------------------------------------------------------

    def classificar_empresa(self, empresa_id, setor_id, subsetor_id=None,
                            fonte=None, evidencia=None, justificativa=None,
                            forcar=False):
        """Define a classificacao principal vigente, preservando a anterior.

        Precedencia: CVM > B3 > IA (fontes desconhecidas ficam no nivel
        neutro). Uma fonte de menor precedencia nao sobrescreve a classificacao
        vigente; a linha antiga continua no historico. ``forcar=True`` e
        reservado a decisoes humanas explicitas.
        """
        session = self._nova_sessao()
        try:
            setor = session.query(Setor).filter(Setor.id == int(setor_id)).first()
            if setor is None:
                raise ValueError("Setor inexistente.")
            if subsetor_id is not None:
                subsetor = (
                    session.query(Subsetor)
                    .filter(Subsetor.id == int(subsetor_id))
                    .first()
                )
                if subsetor is None:
                    raise ValueError("Subsetor inexistente.")
                if subsetor.setor_id != setor.id:
                    raise ValueError("Subsetor nao pertence ao setor informado.")

            atual = (
                session.query(EmpresaSegmento)
                .filter(
                    EmpresaSegmento.empresa_id == int(empresa_id),
                    EmpresaSegmento.vigente.is_(True),
                    EmpresaSegmento.principal.is_(True),
                )
                .first()
            )
            rank_atual = precedencia_fonte(atual.fonte) if atual else 0
            rank_nova = precedencia_fonte(fonte)
            if (
                atual is not None
                and not forcar
                and rank_nova < rank_atual
            ):
                logger.info(
                    "Classificacao de empresa %s preservada: fonte %s "
                    "(peso %s) nao sobrescreve %s (peso %s).",
                    empresa_id,
                    fonte,
                    rank_nova,
                    atual.fonte,
                    rank_atual,
                )
                return atual.id, False

            if (
                atual is not None
                and atual.setor_id == setor.id
                and atual.subsetor_id == subsetor_id
            ):
                alterou = False
                if fonte and (not atual.fonte or rank_nova > rank_atual):
                    atual.fonte = fonte
                    alterou = True
                # A evidencia mais recente da mesma fonte (ou de fonte mais
                # confiavel) substitui a anterior; o historico de mudanca de
                # setor continua preservado nas linhas nao vigentes.
                if evidencia and rank_nova >= rank_atual and atual.evidencia != evidencia:
                    atual.evidencia = evidencia
                    alterou = True
                if (
                    justificativa
                    and rank_nova >= rank_atual
                    and atual.justificativa != justificativa
                ):
                    atual.justificativa = justificativa
                    alterou = True
                if alterou:
                    session.commit()
                return atual.id, False

            if atual is not None:
                atual.vigente = False
                atual.principal = False
                atual.status = STATUS_HISTORICO
                atual.atualizado_em = datetime.utcnow()

            nova = EmpresaSegmento(
                empresa_id=int(empresa_id),
                setor_id=setor.id,
                subsetor_id=subsetor_id,
                principal=True,
                status=STATUS_CONFIRMADA,
                fonte=fonte,
                evidencia=evidencia,
                justificativa=justificativa,
                vigente=True,
            )
            session.add(nova)
            try:
                session.commit()
            except IntegrityError:
                # Outra sessao pode ter publicado a classificacao principal
                # vigente entre a leitura e o commit. O indice parcial garante
                # uma unica linha principal; nao deixamos estado parcial.
                session.rollback()
                atual = (
                    session.query(EmpresaSegmento)
                    .filter(
                        EmpresaSegmento.empresa_id == int(empresa_id),
                        EmpresaSegmento.vigente.is_(True),
                        EmpresaSegmento.principal.is_(True),
                    )
                    .first()
                )
                if (
                    atual is not None
                    and atual.setor_id == setor.id
                    and atual.subsetor_id == subsetor_id
                ):
                    return atual.id, False
                raise
            session.refresh(nova)
            return nova.id, True
        finally:
            session.close()

    def adicionar_atividade(self, empresa_id, atividade_id, principal=False,
                            fonte=None, evidencia=None, justificativa=None):
        """Vincula atividade a empresa sem herdar o setor inteiro."""
        session = self._nova_sessao()
        try:
            atual = (
                session.query(EmpresaAtividade)
                .filter(
                    EmpresaAtividade.empresa_id == int(empresa_id),
                    EmpresaAtividade.atividade_id == int(atividade_id),
                    EmpresaAtividade.vigente.is_(True),
                )
                .first()
            )
            if atual is not None:
                alterou = False
                if principal and not atual.principal:
                    atual.principal = True
                    alterou = True
                if fonte and not atual.fonte:
                    atual.fonte = fonte
                    alterou = True
                if evidencia and not atual.evidencia:
                    atual.evidencia = evidencia
                    alterou = True
                if alterou:
                    session.commit()
                return atual.id, False

            nova = EmpresaAtividade(
                empresa_id=int(empresa_id),
                atividade_id=int(atividade_id),
                principal=bool(principal),
                status=STATUS_CONFIRMADA,
                fonte=fonte,
                evidencia=evidencia,
                justificativa=justificativa,
                vigente=True,
            )
            session.add(nova)
            session.commit()
            session.refresh(nova)
            return nova.id, True
        finally:
            session.close()

    def obter_resumo_empresa(self, ticker):
        """Retorna empresa, tickers, segmento vigente e atividades vigentes."""
        chave = normalizar_ticker(ticker)
        session = self._nova_sessao()
        try:
            linha = (
                session.query(Empresa, Ativo)
                .join(EmpresaAtivo, EmpresaAtivo.empresa_id == Empresa.id)
                .join(Ativo, Ativo.id == EmpresaAtivo.ativo_id)
                .filter(Ativo.ticker == chave)
                .first()
            )
            if linha is None:
                return None
            empresa, ativo = linha
            segmento = (
                session.query(EmpresaSegmento, Setor, Subsetor)
                .join(Setor, Setor.id == EmpresaSegmento.setor_id)
                .outerjoin(Subsetor, Subsetor.id == EmpresaSegmento.subsetor_id)
                .filter(
                    EmpresaSegmento.empresa_id == empresa.id,
                    EmpresaSegmento.vigente.is_(True),
                )
                .order_by(EmpresaSegmento.principal.desc())
                .first()
            )
            atividades = (
                session.query(AtividadeEconomica)
                .join(
                    EmpresaAtividade,
                    EmpresaAtividade.atividade_id == AtividadeEconomica.id,
                )
                .filter(
                    EmpresaAtividade.empresa_id == empresa.id,
                    EmpresaAtividade.vigente.is_(True),
                )
                .order_by(AtividadeEconomica.nome.asc())
                .all()
            )
            return {
                "empresa": self._empresa_dto(empresa),
                "ativo_id": ativo.id,
                "ticker": ativo.ticker,
                "tickers": self._tickers_sessao(session, empresa.id),
                "setor": segmento[1].nome if segmento else None,
                "subsetor": segmento[2].nome if segmento and segmento[2] else None,
                "atividades": [atividade.nome for atividade in atividades],
            }
        finally:
            session.close()

    @staticmethod
    def _tickers_sessao(session, empresa_id):
        return [
            ticker
            for (ticker,) in session.query(Ativo.ticker)
            .join(EmpresaAtivo, EmpresaAtivo.ativo_id == Ativo.id)
            .filter(EmpresaAtivo.empresa_id == empresa_id)
            .order_by(Ativo.ticker.asc())
            .all()
        ]

    # ------------------------------------------------------------------
    # Fila de revisao / auditoria
    # ------------------------------------------------------------------

    def registrar_sugestao(self, tipo, chave, dados=None, fonte=None,
                           evidencia=None, justificativa=None, confianca=None,
                           status=STATUS_SUGESTAO_PENDENTE):
        """Registra sugestao; nao duplica uma pendente para o mesmo tipo/chave."""
        tipo = str(tipo or "").strip()
        chave = str(chave or "").strip()
        if not tipo or not chave:
            raise ValueError("Tipo e chave da sugestao sao obrigatorios.")
        dados_json = None
        if dados is not None:
            dados_json = json.dumps(dados, ensure_ascii=False, sort_keys=True)

        session = self._nova_sessao()
        try:
            if status == STATUS_SUGESTAO_PENDENTE:
                existente = (
                    session.query(SugestaoCatalogo)
                    .filter(
                        SugestaoCatalogo.tipo == tipo,
                        SugestaoCatalogo.chave == chave,
                        SugestaoCatalogo.status == STATUS_SUGESTAO_PENDENTE,
                    )
                    .first()
                )
                if existente is not None:
                    return existente.id, False

            sugestao = SugestaoCatalogo(
                tipo=tipo,
                chave=chave,
                dados_json=dados_json,
                fonte=fonte,
                evidencia=evidencia,
                justificativa=justificativa,
                confianca=confianca,
                status=status,
            )
            session.add(sugestao)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existente = (
                    session.query(SugestaoCatalogo)
                    .filter(
                        SugestaoCatalogo.tipo == tipo,
                        SugestaoCatalogo.chave == chave,
                        SugestaoCatalogo.status == STATUS_SUGESTAO_PENDENTE,
                    )
                    .first()
                )
                if existente is None:
                    raise
                return existente.id, False
            session.refresh(sugestao)
            return sugestao.id, True
        finally:
            session.close()

    def listar_sugestoes_pendentes(self, tipo=None):
        session = self._nova_sessao()
        try:
            consulta = session.query(SugestaoCatalogo).filter(
                SugestaoCatalogo.status == STATUS_SUGESTAO_PENDENTE
            )
            if tipo:
                consulta = consulta.filter(SugestaoCatalogo.tipo == str(tipo))
            return consulta.order_by(SugestaoCatalogo.criado_em.asc()).all()
        finally:
            session.close()

    def obter_sugestao(self, sugestao_id):
        """Retorna a sugestao (objeto ORM carregado) ou ``None``."""
        session = self._nova_sessao()
        try:
            return (
                session.query(SugestaoCatalogo)
                .filter(SugestaoCatalogo.id == int(sugestao_id))
                .first()
            )
        finally:
            session.close()

    @staticmethod
    def _dados_sugestao(sugestao):
        try:
            dados = json.loads(sugestao.dados_json or "{}")
        except (TypeError, ValueError):
            dados = {}
        return dados if isinstance(dados, dict) else {}

    def _atualizar_decisao(self, sugestao_id, status, decidido_por,
                           status_origem=None):
        """Transicao atomica; retorna ``False`` se outro processo decidiu antes."""
        origens = (
            list(status_origem)
            if status_origem is not None
            else [STATUS_SUGESTAO_PENDENTE, STATUS_SUGESTAO_APROVADA]
        )
        session = self._nova_sessao()
        try:
            total = (
                session.query(SugestaoCatalogo)
                .filter(
                    SugestaoCatalogo.id == int(sugestao_id),
                    SugestaoCatalogo.status.in_(origens),
                )
                .update(
                    {
                        SugestaoCatalogo.status: status,
                        SugestaoCatalogo.decidido_em: datetime.utcnow(),
                        SugestaoCatalogo.decidido_por: (
                            str(decidido_por)[:60] if decidido_por else None
                        ),
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            return total > 0
        finally:
            session.close()

    def _aguardar_aplicacao(self, sugestao_id):
        """Espera outra aprovacao concorrente concluir a aplicacao.

        Retorna o id quando a sugestao chega a ``aplicada`` ou ``None`` se o
        tempo esgotar (o chamador decide se pode retomar uma aprovacao antiga).
        """
        limite = time.monotonic() + ESPERA_APLICACAO_SEGUNDOS
        while time.monotonic() < limite:
            atual = self.obter_sugestao(sugestao_id)
            if atual is None:
                return None
            if atual.status == STATUS_SUGESTAO_APLICADA:
                return atual.id
            if atual.status != STATUS_SUGESTAO_APROVADA:
                raise DecisaoSugestaoInvalida(
                    f"Sugestao {sugestao_id} mudou de estado durante a "
                    f"aprovacao ({atual.status!r})."
                )
            time.sleep(0.05)
        return None

    def _reivindicar_aprovacao_antiga(self, sugestao_id, decidido_por):
        """Retoma de forma atomica uma aprovacao presa (processo interrompido)."""
        limite = datetime.utcnow() - timedelta(
            seconds=LIMITE_RETOMADA_APROVACAO_SEGUNDOS
        )
        session = self._nova_sessao()
        try:
            total = (
                session.query(SugestaoCatalogo)
                .filter(
                    SugestaoCatalogo.id == int(sugestao_id),
                    SugestaoCatalogo.status == STATUS_SUGESTAO_APROVADA,
                    or_(
                        SugestaoCatalogo.decidido_em.is_(None),
                        SugestaoCatalogo.decidido_em <= limite,
                    ),
                )
                .update(
                    {
                        SugestaoCatalogo.decidido_em: datetime.utcnow(),
                        SugestaoCatalogo.decidido_por: (
                            str(decidido_por)[:60] if decidido_por else None
                        ),
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            return total > 0
        finally:
            session.close()

    def _reverter_aprovacao(self, sugestao_id):
        """Devolve a sugestao a ``pendente`` quando a aplicacao falhou."""
        session = self._nova_sessao()
        try:
            total = (
                session.query(SugestaoCatalogo)
                .filter(
                    SugestaoCatalogo.id == int(sugestao_id),
                    SugestaoCatalogo.status == STATUS_SUGESTAO_APROVADA,
                )
                .update(
                    {
                        SugestaoCatalogo.status: STATUS_SUGESTAO_PENDENTE,
                        SugestaoCatalogo.decidido_em: None,
                        SugestaoCatalogo.decidido_por: None,
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            return total > 0
        finally:
            session.close()

    def _validar_aplicacao_sugestao(self, dados):
        """Faz a pre-validacao de identidade/vinculos antes de aplicar.

        A aprovacao humana pode criar taxonomia nova, mas nao pode trocar o
        dono de um ticker nem fundir CNPJs. Esta checagem evita criar uma
        empresa parcial quando o vinculo solicitado conflita com o catalogo.
        """
        if not isinstance(dados, dict):
            raise ValueError("Sugestao sem dados aplicaveis.")
        nome = str(dados.get("nome") or dados.get("razao_social") or "").strip()
        cnpj = normalizar_cnpj(dados.get("cnpj"))
        tickers = []
        for bruto in dados.get("tickers") or []:
            ticker = normalizar_ticker(bruto)
            if ticker and ticker not in tickers:
                tickers.append(ticker)

        if (nome or cnpj) and not nome:
            raise ValueError("Sugestao de empresa sem nome.")

        session = self._nova_sessao()
        try:
            existente = None
            if nome:
                existente = self._resolver_candidata_existente(
                    session, nome, cnpj
                )
            for ticker in tickers:
                ativo = session.query(Ativo).filter(Ativo.ticker == ticker).first()
                if ativo is None:
                    continue
                vinculo = self._vinculo_do_ativo(session, ativo.id)
                if vinculo is None:
                    continue
                if existente is None or vinculo.empresa_id != existente.id:
                    raise ConflitoVinculoAtivo(
                        f"O ativo {ticker} ja esta vinculado a empresa "
                        f"{vinculo.empresa_id}; vinculo com "
                        f"{existente.id if existente else 'nova empresa'} "
                        "recusado."
                    )
        finally:
            session.close()

    def _aplicar_dados_sugestao(self, dados, fonte=None, evidencia=None,
                                justificativa=None):
        """Aplica os dados de uma sugestao HUMANA ao catalogo.

        A criacao de setor/subsetor aqui e permitida porque a aprovacao humana e
        o ato de validacao da taxonomia. A IA nunca chama este caminho sem
        revisao.
        """
        if not isinstance(dados, dict):
            raise ValueError("Sugestao sem dados aplicaveis.")
        resumo = {
            "empresa": None,
            "criada": False,
            "tickers_vinculados": 0,
            "setor": None,
            "subsetor": None,
            "atividades": 0,
        }

        nome = str(dados.get("nome") or dados.get("razao_social") or "").strip()
        cnpj = normalizar_cnpj(dados.get("cnpj"))
        setor_nome = str(dados.get("setor") or "").strip()
        subsetor_nome = str(dados.get("subsetor") or "").strip()
        atividades = [
            str(item).strip()
            for item in (dados.get("atividades") or [])
            if str(item).strip()
        ]
        tickers = []
        for bruto in dados.get("tickers") or []:
            ticker = normalizar_ticker(bruto)
            if ticker and ticker not in tickers:
                tickers.append(ticker)

        empresa = None
        if nome or cnpj:
            if not nome:
                raise ValueError("Sugestao de empresa sem nome.")
            empresa, criada = self.obter_ou_criar_empresa(
                nome=nome,
                cnpj=cnpj,
                razao_social=dados.get("razao_social") or nome,
                nome_comercial=dados.get("nome_comercial"),
                fonte=fonte,
                evidencia=evidencia,
            )
            resumo["empresa"] = empresa.id
            resumo["criada"] = criada
            for ticker in tickers:
                if self.vincular_ativo(
                    empresa.id,
                    ticker,
                    fonte=fonte,
                    evidencia=evidencia,
                    criar_ativo=True,
                    tipo=dados.get("tipo") or "acao",
                ) is not None:
                    resumo["tickers_vinculados"] += 1

        if setor_nome:
            setor_canonico = resolver_setor(setor_nome) or setor_nome
            setor_id = self.obter_ou_criar_setor(setor_canonico, fonte=fonte)
            resumo["setor"] = setor_id
            subsetor_id = None
            if subsetor_nome:
                subsetor_id = self.obter_ou_criar_subsetor(
                    setor_id, subsetor_nome, fonte=fonte
                )
                resumo["subsetor"] = subsetor_id
            if empresa is not None:
                self.classificar_empresa(
                    empresa.id,
                    setor_id,
                    subsetor_id=subsetor_id,
                    fonte=fonte,
                    evidencia=evidencia,
                    justificativa=justificativa,
                    forcar=True,
                )

        for atividade_nome in atividades:
            atividade_id = self.obter_ou_criar_atividade(
                atividade_nome, fonte=fonte, evidencia=evidencia
            )
            if empresa is not None and self.adicionar_atividade(
                empresa.id,
                atividade_id,
                principal=True,
                fonte=fonte,
                evidencia=evidencia,
                justificativa=justificativa,
            )[1]:
                resumo["atividades"] += 1

        return resumo

    def aprovar_sugestao(self, sugestao_id, decidido_por=None):
        """Aprova E aplica uma sugestao pendente (idempotente).

        A transicao ``pendente -> aprovada`` e feita de forma atomica ANTES de
        aplicar os dados. Assim, duas aprovacoes concorrentes nao aplicam a
        mesma sugestao duas vezes. Se a aplicacao falhar por conflito de
        identidade/vinculo, a sugestao volta a ``pendente`` para revisao;
        nada e escolhido arbitrariamente.
        """
        sugestao = self.obter_sugestao(sugestao_id)
        if sugestao is None:
            return None
        if sugestao.status == STATUS_SUGESTAO_APLICADA:
            return sugestao.id
        if sugestao.status not in (
            STATUS_SUGESTAO_PENDENTE,
            STATUS_SUGESTAO_APROVADA,
        ):
            raise DecisaoSugestaoInvalida(
                f"Sugestao {sugestao_id} ja foi decidida como "
                f"{sugestao.status!r}; nao pode ser aprovada novamente."
            )

        if sugestao.status == STATUS_SUGESTAO_PENDENTE:
            # Reivindica a sugestao. Se outro processo venceu a corrida,
            # apenas devolve o estado atual (sem aplicar em duplicidade).
            if not self._atualizar_decisao(
                sugestao.id,
                STATUS_SUGESTAO_APROVADA,
                decidido_por,
                status_origem=[STATUS_SUGESTAO_PENDENTE],
            ):
                atual = self.obter_sugestao(sugestao.id)
                if atual is not None and atual.status == STATUS_SUGESTAO_APLICADA:
                    return atual.id
                if atual is not None and atual.status == STATUS_SUGESTAO_APROVADA:
                    aguardado = self._aguardar_aplicacao(sugestao.id)
                    if aguardado is not None:
                        return aguardado
                    raise DecisaoSugestaoInvalida(
                        f"Sugestao {sugestao_id} esta sendo aplicada por outro "
                        "processo."
                    )
                raise DecisaoSugestaoInvalida(
                    f"Sugestao {sugestao_id} mudou de estado durante a aprovacao."
                )
        else:
            # Ja estava "aprovada": somente o processo dono da aplicacao deve
            # aplica-la. Se outro processo estiver trabalhando, aguarda. Se a
            # aprovacao estiver presa ha tempo suficiente, retoma de forma
            # atomica (recuperacao de processo interrompido) sem duplicar.
            aguardado = self._aguardar_aplicacao(sugestao.id)
            if aguardado is not None:
                return aguardado
            if not self._reivindicar_aprovacao_antiga(
                sugestao.id, decidido_por
            ):
                raise DecisaoSugestaoInvalida(
                    f"Sugestao {sugestao_id} esta sendo aplicada por outro "
                    "processo."
                )

        dados = self._dados_sugestao(sugestao)
        try:
            self._validar_aplicacao_sugestao(dados)
            resumo = self._aplicar_dados_sugestao(
                dados,
                fonte=sugestao.fonte,
                evidencia=sugestao.evidencia,
                justificativa=sugestao.justificativa,
            )
        except Exception:
            # Nada foi aplicado de forma completa: a sugestao continua na fila
            # para revisao humana em vez de ficar presa em "aprovada".
            self._reverter_aprovacao(sugestao.id)
            raise

        if not self._atualizar_decisao(
            sugestao.id,
            STATUS_SUGESTAO_APLICADA,
            decidido_por,
            status_origem=[STATUS_SUGESTAO_APROVADA],
        ):
            atual = self.obter_sugestao(sugestao.id)
            if atual is not None and atual.status == STATUS_SUGESTAO_APLICADA:
                return atual.id
            raise DecisaoSugestaoInvalida(
                f"Sugestao {sugestao_id} mudou de estado durante a aprovacao."
            )

        logger_auditoria.info(
            "AUDITORIA_CATALOGO acao=aprovar_sugestao sugestao_id=%s tipo=%s "
            "chave=%s decidido_por=%s fonte=%s resumo=%s",
            sugestao.id,
            sugestao.tipo,
            sugestao.chave,
            decidido_por,
            sugestao.fonte,
            json.dumps(resumo, ensure_ascii=False, sort_keys=True),
        )
        return sugestao.id

    def decidir_sugestao(self, sugestao_id, status, decidido_por=None):
        """Decide uma sugestao pendente; aprovar aplica a alteracao."""
        status = str(status or "").strip()
        if status in {STATUS_SUGESTAO_APROVADA, STATUS_SUGESTAO_APLICADA}:
            return self.aprovar_sugestao(sugestao_id, decidido_por=decidido_por)
        if status not in {
            STATUS_SUGESTAO_REJEITADA,
            STATUS_SUGESTAO_DUPLICADA,
        }:
            raise ValueError("Status de decisao invalido.")

        sugestao = self.obter_sugestao(sugestao_id)
        if sugestao is None:
            return None
        if sugestao.status == status:
            return sugestao.id
        if sugestao.status != STATUS_SUGESTAO_PENDENTE:
            raise DecisaoSugestaoInvalida(
                f"Sugestao {sugestao_id} ja foi decidida como "
                f"{sugestao.status!r}; decisao contraditoria recusada."
            )

        if not self._atualizar_decisao(
            sugestao.id,
            status,
            decidido_por,
            status_origem=[STATUS_SUGESTAO_PENDENTE],
        ):
            atual = self.obter_sugestao(sugestao.id)
            if atual is not None and atual.status == status:
                return atual.id
            raise DecisaoSugestaoInvalida(
                f"Sugestao {sugestao_id} mudou de estado durante a decisao."
            )

        logger_auditoria.info(
            "AUDITORIA_CATALOGO acao=decidir_sugestao sugestao_id=%s tipo=%s "
            "chave=%s decisao=%s decidido_por=%s fonte=%s",
            sugestao.id,
            sugestao.tipo,
            sugestao.chave,
            status,
            decidido_por,
            sugestao.fonte,
        )
        return sugestao.id


__all__ = [
    "ConflitoEmpresa",
    "ConflitoVinculoAtivo",
    "DecisaoSugestaoInvalida",
    "EmpresaDTO",
    "RepositorioCatalogo",
    "gerar_slug",
    "normalizar_cnpj",
    "normalizar_texto",
    "LIMITE_RETOMADA_APROVACAO_SEGUNDOS",
    "normalizar_ticker",
    "precedencia_fonte",
    "somente_digitos",
    "ticker_negociacao_valido",
]
