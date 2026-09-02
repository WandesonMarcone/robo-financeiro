"""Motor central de notificações individualizadas por usuário (Fase 6, Etapa 6).

Arquitetura em etapas, independente do canal de entrega:

    EVENTO -> DECISÃO (elegibilidade) -> NOTIFICAÇÃO -> ENTREGA (futura)

O motor decide QUAIS usuários devem receber uma notificação para um dado
evento de mercado e PERSISTE as notificações individualizadas
(``Notificacao``). Nenhum envio (Telegram/web) é realizado nesta etapa — a
entrega real fica para a Etapa 7.

Reutiliza exclusivamente (nenhuma regra paralela, nenhuma segunda tabela):
- ``services/autorizacao.py`` (matriz central): a elegibilidade exige a
  permissão ``notificacoes.consultar`` — USER e SUPERADMIN recebem; usuário
  desativado, VISITOR e ADMIN (sem a permissão) não recebem;
- ``services/preferencias.py``: o tipo de evento mapeia para a preferência
  correspondente e os canais dependem de ``web_ativo``/``telegram_ativo``
  (com o mestre ``notificacoes_ativas``);
- ``services/ativos_acompanhados.py``: ``origem=ACOMPANHAMENTO`` exige o vínculo;
- ``services/carteira.py``: ``origem=CARTEIRA`` exige posição no ativo;
- ``services/escopo.py``: isolamento por usuário (anti-IDOR/BOLA) nas consultas;
- ``services/auditoria.py``: trilha sem segredos;
- padrão de sessão do projeto (``services.usuarios._sessao``).

Garantias:
- A chave de idempotência ``(evento_id, usuario_id, tipo, canal)`` evita
  duplicatas quando o mesmo evento é reprocessado; ``evento_id`` distinto (ou
  ausente) permite múltiplas notificações legítimas.
- ``dados`` estruturados passam por sanitização: nenhum segredo é persistido.
- Telegram nunca é assumido sem vínculo válido (``telegram_user_id`` presente).
- O catálogo de eventos/canais/status é controlado e extensível.
"""
import json
import logging
import re
from datetime import datetime

from sqlalchemy import func

from pipeline_dados.banco_dados import Notificacao, Usuario
from services import (
    ativos_acompanhados,
    auditoria,
    autorizacao,
    carteira,
    planos,
    preferencias,
)
from services.usuarios import _sessao

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CATÁLOGO CONTROLADO DE EVENTOS (extensível: basta adicionar novos membros)
# ---------------------------------------------------------------------------
TIPOS_EVENTO = frozenset(
    {
        "PRECO_ATINGIDO",
        "VARIACAO_PRECO",
        "DIVIDENDO",
        "DOCUMENTO_NOVO",
        "RESULTADO_PUBLICADO",
        "ALERTA_MERCADO",
        "RELATORIO_DISPONIVEL",
    }
)

# Preferência correspondente a cada tipo de evento (``services/preferencias.py``).
# Um evento sem mapeamento exige apenas o mestre ``notificacoes_ativas`` ativo.
PREFERENCIA_POR_EVENTO = {
    "PRECO_ATINGIDO": "notificacoes_preco",
    "VARIACAO_PRECO": "notificacoes_preco",
    "DIVIDENDO": "notificacoes_dividendos",
    "RESULTADO_PUBLICADO": "notificacoes_resultados",
    "DOCUMENTO_NOVO": "notificacoes_documentos",
    "ALERTA_MERCADO": "notificacoes_alertas",
    "RELATORIO_DISPONIVEL": "relatorios_ativos",
}

# ---------------------------------------------------------------------------
# CANAIS
# ---------------------------------------------------------------------------
CANAL_WEB = "WEB"
CANAL_TELEGRAM = "TELEGRAM"
CANAIS_VALIDOS = (CANAL_WEB, CANAL_TELEGRAM)

# Origem da relação do evento com o ativo (define o vínculo exigido).
ORIGEM_ACOMPANHAMENTO = "ACOMPANHAMENTO"
ORIGEM_CARTEIRA = "CARTEIRA"
ORIGENS_VALIDAS = (ORIGEM_ACOMPANHAMENTO, ORIGEM_CARTEIRA)

# ---------------------------------------------------------------------------
# STATUS CONTROLADOS
# ---------------------------------------------------------------------------
STATUS_PENDENTE = "PENDENTE"
STATUS_GERADA = "GERADA"
STATUS_ENVIADA = "ENVIADA"
STATUS_LIDA = "LIDA"
STATUS_FALHA = "FALHA"
STATUS_VALIDOS = (STATUS_PENDENTE, STATUS_GERADA, STATUS_ENVIADA, STATUS_LIDA, STATUS_FALHA)

# ---------------------------------------------------------------------------
# AUDITORIA (apenas eventos administrativos/importantes)
# ---------------------------------------------------------------------------
ACAO_GERADA = "NOTIFICACAO_GERADA"
ACAO_MARCADA_LIDA = "NOTIFICACAO_MARCADA_LIDA"
ACAO_MARCADAS_LIDAS = "NOTIFICACOES_MARCADAS_LIDAS"
ACAO_EXCLUIDA = "NOTIFICACAO_EXCLUIDA"

# Campos aceitos no dicionário de evento (validação estrita).
CAMPOS_EVENTO = frozenset(
    {
        "tipo",
        "titulo",
        "mensagem",
        "ativo_id",
        "evento_id",
        "canais",
        "origem",
        "dados",
    }
)

# Padrões de chaves sensíveis removidos de ``dados`` (payload estruturado).
_PADRAO_SENSIVEL = re.compile(
    r"(?i)(senha|password|passwd|token|api[_-]?key|secret|chave|credential)"
)


# ===========================================================================
# VALIDAÇÃO
# ===========================================================================


def _validar_evento(evento):
    """Valida e normaliza o dicionário de evento; levanta ``ValueError``.

    Exige ``tipo`` no catálogo, ``titulo``/``mensagem`` não vazios, ``ativo_id``
    inteiro positivo (quando informado), ``evento_id`` texto (quando informado),
    ``canais`` válidos, ``origem`` válida e ``dados`` serializável. Campos
    desconhecidos são rejeitados (mesmo rigor das etapas anteriores).
    """
    if not isinstance(evento, dict):
        raise ValueError("Evento inválido.")
    for campo in evento:
        if campo not in CAMPOS_EVENTO:
            raise ValueError(f"Campo desconhecido no evento: '{campo}'.")

    tipo = evento.get("tipo")
    if tipo is None or str(tipo).strip().upper() not in TIPOS_EVENTO:
        raise ValueError(
            f"Tipo de evento inválido. Opções: {', '.join(sorted(TIPOS_EVENTO))}."
        )
    tipo = str(tipo).strip().upper()

    titulo = evento.get("titulo")
    if not isinstance(titulo, str) or not titulo.strip():
        raise ValueError("O campo 'titulo' é obrigatório e deve ser texto.")
    mensagem = evento.get("mensagem")
    if not isinstance(mensagem, str) or not mensagem.strip():
        raise ValueError("O campo 'mensagem' é obrigatório e deve ser texto.")

    ativo_id = evento.get("ativo_id")
    if ativo_id is not None:
        if isinstance(ativo_id, bool) or not isinstance(ativo_id, int) or ativo_id <= 0:
            raise ValueError("O campo 'ativo_id' deve ser um inteiro positivo.")

    evento_id = evento.get("evento_id")
    if evento_id is not None:
        if not isinstance(evento_id, str) or not evento_id.strip():
            raise ValueError("O campo 'evento_id' deve ser um texto não vazio.")
        evento_id = evento_id.strip()[:100]

    canais = evento.get("canais")
    if canais is not None:
        if not isinstance(canais, list) or not canais:
            raise ValueError("O campo 'canais' deve ser uma lista não vazia.")
        canais = [str(canal).strip().upper() for canal in canais]
        for canal in canais:
            if canal not in CANAIS_VALIDOS:
                raise ValueError(
                    f"Canal inválido. Opções: {', '.join(CANAIS_VALIDOS)}."
                )

    origem = str(evento.get("origem", ORIGEM_ACOMPANHAMENTO)).strip().upper()
    if origem not in ORIGENS_VALIDAS:
        raise ValueError(
            f"Origem inválida. Opções: {', '.join(ORIGENS_VALIDAS)}."
        )

    dados = evento.get("dados")
    if dados is not None and not isinstance(dados, dict):
        raise ValueError("O campo 'dados' deve ser um objeto.")

    return {
        "tipo": tipo,
        "titulo": titulo.strip()[:255],
        "mensagem": mensagem.strip(),
        "ativo_id": ativo_id,
        "evento_id": evento_id,
        "canais": canais,
        "origem": origem,
        "dados": dados,
    }


def _sanitizar_dados(dados):
    """Serializa o payload estruturado removendo chaves sensíveis (sem segredos).

    Aplica a mesma política de ``services/auditoria.py``: nenhum segredo é
    persistido. Chaves sensíveis são substituídas por ``[OCULTO]`` de forma
    recursiva. Retorna ``None`` quando não há payload.
    """
    if dados is None:
        return None

    def _limpar(objeto):
        if isinstance(objeto, dict):
            return {
                chave: ("[OCULTO]" if _PADRAO_SENSIVEL.search(str(chave)) else _limpar(valor))
                for chave, valor in objeto.items()
            }
        if isinstance(objeto, list):
            return [_limpar(item) for item in objeto]
        return objeto

    try:
        return json.dumps(_limpar(dados), ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raise ValueError("O campo 'dados' deve ser serializável em JSON.") from None


def _pref(preferencias_registro, nome, padrao=True):
    """Lê uma preferência de um ORM ou de um dict de defaults, sem segredos."""
    if isinstance(preferencias_registro, dict):
        return preferencias_registro.get(nome, padrao)
    return getattr(preferencias_registro, nome, padrao)


# ===========================================================================
# DECISÃO: ELEGIBILIDADE
# ===========================================================================


def _preferencia_ativa(usuario, tipo, session):
    """True quando as preferências do ``usuario`` permitem notificar o ``tipo``.

    O mestre ``notificacoes_ativas`` bloqueia tudo; o tipo de evento mapeia
    para a preferência específica (``PREFERENCIA_POR_EVENTO``). Ausência de
    preferências usa os defaults seguros (todos ativos) — nenhuma linha é
    criada durante a varredura.
    """
    prefs = preferencias.buscar_preferencias(usuario, session=session)
    if prefs is None:
        prefs = preferencias.preferencias_padrao()
    if not _pref(prefs, "notificacoes_ativas"):
        return False
    campo = PREFERENCIA_POR_EVENTO.get(tipo)
    if campo is None:
        return True
    return bool(_pref(prefs, campo))


def _canais_disponiveis(usuario, session):
    """Canais efetivamente disponíveis para ``usuario``.

    - WEB: exige ``web_ativo`` (padrão True);
    - TELEGRAM: exige ``telegram_ativo`` E vínculo ``telegram_user_id`` válido
      (nunca se assume envio sem vínculo Telegram real).
    """
    prefs = preferencias.buscar_preferencias(usuario, session=session)
    if prefs is None:
        prefs = preferencias.preferencias_padrao()
    canais = []
    if _pref(prefs, "web_ativo"):
        canais.append(CANAL_WEB)
    if _pref(prefs, "telegram_ativo") and getattr(usuario, "telegram_user_id", None) is not None:
        canais.append(CANAL_TELEGRAM)
    return canais


def _notificacoes_ativas_restantes(usuario, sessao):
    """Espaço restante no limite de notificações ativas do ``usuario``.

    "Ativas" = notificações ainda não lidas (``status != LIDA``): ocupam a caixa
    de entrada do usuário. A decisão é exclusiva de ``services/planos.py``:
    - ``None`` quando ilimitado (SUPERADMIN);
    - ``0`` quando o usuário está no limite (ou sem recursos);
    - demais usuários conforme o catálogo do plano.

    Contagem e geração acontecem na mesma sessão/transação, evitando ultrapassar
    o limite entre leitura e persistência.
    """
    limite = planos.obter_limite(usuario, "limite.notificacoes_ativas")
    if limite is None:
        return None
    ativas = (
        sessao.query(func.count(Notificacao.id))
        .filter(
            Notificacao.usuario_id == usuario.id,
            Notificacao.status != STATUS_LIDA,
        )
        .scalar()
        or 0
    )
    return max(limite - ativas, 0)


def _usuarios_elegiveis(sessao, evento):
    """Seleção central: usuários elegíveis para o ``evento`` normalizado.

    Regras (nesta ordem):
    1. usuário ativo no banco;
    2. permissão ``notificacoes.consultar`` na matriz central (exclui
       desativado, VISITOR e ADMIN sem permissão; inclui USER e SUPERADMIN);
    3. vínculo com o ativo conforme ``origem``: ACOMPANHAMENTO exige
       acompanhamento; CARTEIRA exige posição na carteira (reusa
       ``carteira.buscar_posicao_por_ativo``);
    4. preferência correspondente ao tipo de evento ativa;
    5. limite de notificações ativas do plano (Fase 6, Etapa 9): usuário no
       limite não recebe novas notificações — a contagem usa a mesma sessão da
       varredura;
    6. ao menos um canal disponível.
    """
    ativo_id = evento.get("ativo_id")
    origem = evento.get("origem", ORIGEM_ACOMPANHAMENTO)
    elegiveis = []
    for usuario in sessao.query(Usuario).filter(Usuario.ativo.is_(True)).all():
        if not autorizacao.tem_permissao(usuario, "notificacoes.consultar"):
            continue
        if ativo_id is not None:
            if origem == ORIGEM_CARTEIRA:
                if carteira.buscar_posicao_por_ativo(usuario, ativo_id, session=sessao) is None:
                    continue
            elif not ativos_acompanhados.usuario_acompanha_ativo(
                usuario, ativo_id, session=sessao
            ):
                continue
        if not _preferencia_ativa(usuario, evento["tipo"], session=sessao):
            continue
        if _notificacoes_ativas_restantes(usuario, sessao) == 0:
            continue
        if not _canais_disponiveis(usuario, session=sessao):
            continue
        elegiveis.append(usuario)
    return elegiveis


def usuarios_elegiveis_para_evento(evento, session=None):
    """Retorna os ``Usuario`` elegíveis para receber notificação do ``evento``.

    API pública da etapa de DECISÃO. Valida o evento e retorna a lista de
    usuários que receberiam a notificação (sem persistir nada).
    """
    dados = _validar_evento(evento)
    with _sessao(session) as s:
        return _usuarios_elegiveis(s, dados)


# ===========================================================================
# NOTIFICAÇÃO: DEDUPLICAÇÃO E PERSISTÊNCIA
# ===========================================================================


def _ja_existe(sessao, evento, usuario_id, canal):
    """True quando já existe notificação para ``(evento_id, usuario, tipo, canal)``.

    Sem ``evento_id`` não há deduplicação (múltiplas notificações legítimas).
    """
    evento_id = evento.get("evento_id")
    if not evento_id:
        return False
    return (
        sessao.query(Notificacao.id)
        .filter(
            Notificacao.evento_id == evento_id,
            Notificacao.usuario_id == usuario_id,
            Notificacao.tipo == evento["tipo"],
            Notificacao.canal == canal,
        )
        .first()
        is not None
    )


def processar_evento(evento, session=None):
    """Pipeline completo: valida, seleciona elegíveis e gera notificações.

    Retorna um resumo com ``elegiveis`` (contagem), ``geradas``,
    ``ignoradas`` (duplicatas) e ``notificacoes`` (objetos persistidos, status
    ``GERADA``). Persiste apenas notificações novas — reprocessar o mesmo
    evento não gera duplicatas. Nenhum envio é realizado. Registra
    ``NOTIFICACAO_GERADA`` na auditoria (uma vez por processamento, sem
    segredos).
    """
    dados = _validar_evento(evento)
    with _sessao(session) as s:
        elegiveis = _usuarios_elegiveis(s, dados)
        geradas = []
        ignoradas = 0
        for usuario in elegiveis:
            canais = _canais_efetivos(usuario, dados, session=s)
            restante = _notificacoes_ativas_restantes(usuario, s)
            if restante is not None and restante < len(canais):
                canais = canais[:restante]
            if not canais:
                continue
            for canal in canais:
                if _ja_existe(s, dados, usuario.id, canal):
                    ignoradas += 1
                    continue
                notificacao = Notificacao(
                    usuario_id=usuario.id,
                    tipo=dados["tipo"],
                    titulo=dados["titulo"],
                    mensagem=dados["mensagem"],
                    ativo_id=dados.get("ativo_id"),
                    evento_id=dados.get("evento_id"),
                    canal=canal,
                    status=STATUS_GERADA,
                    dados=_sanitizar_dados(dados.get("dados")),
                )
                s.add(notificacao)
                geradas.append(notificacao)
        s.commit()
        if geradas:
            auditoria.registrar_evento(
                acao=ACAO_GERADA,
                alvo=f"tipo={dados['tipo']}",
                detalhe=(
                    f"evento_id={dados.get('evento_id') or '-'}, "
                    f"elegiveis={len(elegiveis)}, geradas={len(geradas)}, "
                    f"ignoradas={ignoradas}"
                ),
                session=s,
            )
        return {
            "evento": dados,
            "elegiveis": len(elegiveis),
            "geradas": len(geradas),
            "ignoradas": ignoradas,
            "notificacoes": geradas,
        }


def _canais_efetivos(usuario, evento, session):
    """Canais da notificação: interseção entre disponíveis e solicitados."""
    disponiveis = _canais_disponiveis(usuario, session=session)
    solicitados = evento.get("canais")
    if solicitados:
        return [canal for canal in solicitados if canal in disponiveis]
    return disponiveis


# ===========================================================================
# CONSULTA E ESTADO (isolamento por usuário via services/escopo.py)
# ===========================================================================


def listar_notificacoes(usuario, session=None, tipo=None, status=None, nao_lidas=False):
    """Lista as notificações do próprio ``usuario``, com filtros opcionais seguros."""
    if usuario is None or getattr(usuario, "id", None) is None:
        return []
    with _sessao(session) as s:
        query = s.query(Notificacao).filter(Notificacao.usuario_id == usuario.id)
        if tipo:
            normalizado = str(tipo).strip().upper()
            if normalizado not in TIPOS_EVENTO:
                raise ValueError(
                    f"Filtro 'tipo' inválido. Opções: {', '.join(sorted(TIPOS_EVENTO))}."
                )
            query = query.filter(Notificacao.tipo == normalizado)
        if status:
            normalizado = str(status).strip().upper()
            if normalizado not in STATUS_VALIDOS:
                raise ValueError(
                    f"Filtro 'status' inválido. Opções: {', '.join(STATUS_VALIDOS)}."
                )
            query = query.filter(Notificacao.status == normalizado)
        if nao_lidas:
            query = query.filter(Notificacao.status != STATUS_LIDA)
        return (
            query.order_by(Notificacao.criado_em.desc(), Notificacao.id.desc()).all()
        )


def buscar_notificacao(usuario, notificacao_id, session=None):
    """Busca uma notificação aplicando o escopo (anti-IDOR/BOLA).

    ``None`` tanto para inexistente quanto para notificação de outro usuário —
    resposta indistinguível. SUPERADMIN (wildcard) mantém o acesso
    administrativo previsto na matriz central.
    """
    with _sessao(session) as s:
        return escopo_buscar(s, notificacao_id, usuario)


def escopo_buscar(sessao, notificacao_id, usuario):
    """Encapsula a busca escopada para ``Notificacao`` (import local p/ ciclo)."""
    from services import escopo

    return escopo.buscar_recurso_escopado(sessao, Notificacao, notificacao_id, usuario)


def marcar_como_lida(usuario, notificacao_id, session=None, ip=None):
    """Marca uma notificação do ``usuario`` como lida (``LIDA`` + ``lida_em``).

    Idempotente: marcar algo já lido não gera novo evento. Retorna a
    notificação ou ``None`` (inexistente/fora do escopo). Registra
    ``NOTIFICACAO_MARCADA_LIDA`` na auditoria (sem segredos).
    """
    with _sessao(session) as s:
        notificacao = escopo_buscar(s, notificacao_id, usuario)
        if notificacao is None:
            return None
        if notificacao.status != STATUS_LIDA:
            notificacao.status = STATUS_LIDA
            notificacao.lida_em = datetime.now()
            s.commit()
            auditoria.registrar_evento(
                acao=ACAO_MARCADA_LIDA,
                alvo=f"notificacao:{notificacao.id}",
                detalhe=f"tipo={notificacao.tipo}",
                usuario_id=notificacao.usuario_id,
                ip=ip,
                session=s,
            )
        return notificacao


def marcar_todas_como_lida(usuario, session=None, ip=None):
    """Marca TODAS as notificações não lidas do ``usuario`` como lidas.

    Opera somente sobre notificações do próprio ``usuario`` (isolamento por
    usuário — nunca toca em notificações de terceiros). Retorna a quantidade
    marcada; ``0`` quando não há pendentes ou ``usuario`` inválido. Idempotente:
    nenhum evento de auditoria é registrado quando nada é alterado. Registra
    ``NOTIFICACOES_MARCADAS_LIDAS`` na auditoria (sem segredos).
    """
    if usuario is None or getattr(usuario, "id", None) is None:
        return 0
    with _sessao(session) as s:
        pendentes = (
            s.query(Notificacao)
            .filter(
                Notificacao.usuario_id == usuario.id,
                Notificacao.status != STATUS_LIDA,
            )
            .all()
        )
        if not pendentes:
            return 0
        agora = datetime.now()
        for notificacao in pendentes:
            notificacao.status = STATUS_LIDA
            notificacao.lida_em = agora
        s.commit()
        auditoria.registrar_evento(
            acao=ACAO_MARCADAS_LIDAS,
            alvo=f"usuario:{usuario.id}",
            detalhe=f"marcadas={len(pendentes)}",
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
        return len(pendentes)


def excluir_notificacao(usuario, notificacao_id, session=None, ip=None):
    """Exclui uma notificação do ``usuario`` aplicando o escopo.

    Retorna ``True``/``False`` (``False`` para inexistente ou de outro usuário).
    Registra ``NOTIFICACAO_EXCLUIDA`` na auditoria.
    """
    with _sessao(session) as s:
        notificacao = escopo_buscar(s, notificacao_id, usuario)
        if notificacao is None:
            return False
        tipo = notificacao.tipo
        s.delete(notificacao)
        s.commit()
        auditoria.registrar_evento(
            acao=ACAO_EXCLUIDA,
            alvo=f"notificacao:{notificacao_id}",
            detalhe=f"tipo={tipo}",
            usuario_id=getattr(usuario, "id", None),
            ip=ip,
            session=s,
        )
        return True
