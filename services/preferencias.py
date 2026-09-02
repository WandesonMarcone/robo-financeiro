"""Serviço central de preferências individuais do usuário (Fase 6, Etapa 5).

Gerencia ``PreferenciasUsuario`` reutilizando exclusivamente:
- ``services/autorizacao.py`` — matriz central (nenhuma regra paralela; a
  permissão ``preferencias.proprias`` já existe na matriz e é a única exigida);
- ``services/auditoria.py`` — trilha de eventos sem segredos;
- padrão de sessão do projeto (``services.usuarios._sessao``).

Isolamento: as preferências são 1:1 com o ``usuario`` autenticado e não existe
nenhum id de recurso vindo do cliente — a chave é o próprio ``usuario.id`` do
contexto autenticado. Portanto não há acesso cruzado por id (o princípio de
``services/escopo.py`` é satisfeito pela inexistência de id externo) e nenhuma
função aceita ``usuario_id`` arbitrário. Um usuário nunca lê/altera preferências
de outro porque toda consulta é filtrada pelo usuário autenticado.

Segredos: nenhuma senha, token, API Key ou hash é lido, persistido ou
registrado aqui.
"""
import logging

from pipeline_dados.banco_dados import PreferenciasUsuario
from services import auditoria, autorizacao
from services.usuarios import _sessao

logger = logging.getLogger(__name__)

ACAO_CRIADAS = "PREFERENCIAS_CRIADAS"
ACAO_ATUALIZADAS = "PREFERENCIAS_ATUALIZADAS"
ACAO_RESTAURADAS = "PREFERENCIAS_RESTAURADAS"

# Valores controlados das frequências (nunca aceitar valores arbitrários).
FREQUENCIAS_NOTIFICACOES = ("imediata", "diaria", "semanal", "desativada")
FREQUENCIAS_RELATORIOS = ("diaria", "semanal", "mensal", "desativada")

# Campos booleanos (validação de tipo estrita: somente ``bool``).
CAMPOS_BOOLEANOS = frozenset(
    {
        "notificacoes_ativas",
        "notificacoes_preco",
        "notificacoes_dividendos",
        "notificacoes_resultados",
        "notificacoes_documentos",
        "notificacoes_alertas",
        "telegram_ativo",
        "web_ativo",
        "relatorios_ativos",
        "mercado_acoes",
        "mercado_fiis",
    }
)

# Campos com enumeração controlada (nome -> valores permitidos).
CAMPOS_FREQUENCIA = {
    "frequencia_notificacoes": FREQUENCIAS_NOTIFICACOES,
    "frequencia_relatorios": FREQUENCIAS_RELATORIOS,
}

# Campos que o cliente pode atualizar.
CAMPOS_ATUALIZAVEIS = frozenset(CAMPOS_BOOLEANOS) | frozenset(CAMPOS_FREQUENCIA)

# Campos que o cliente NUNCA pode alterar (rejeitados com erro).
CAMPOS_PROIBIDOS = frozenset({"id", "usuario_id", "criado_em", "atualizado_em"})


def preferencias_padrao():
    """Dicionário com os defaults seguros (fonte única, espelha o modelo).

    ``telegram_ativo=True`` é apenas a preferência declarada; a disponibilidade
    real depende de um vínculo Telegram válido e será verificada pelo futuro
    serviço de notificações — nenhum envio ocorre nesta etapa.
    """
    return {
        "notificacoes_ativas": True,
        "notificacoes_preco": True,
        "notificacoes_dividendos": True,
        "notificacoes_resultados": True,
        "notificacoes_documentos": True,
        "notificacoes_alertas": True,
        "frequencia_notificacoes": "imediata",
        "telegram_ativo": True,
        "web_ativo": True,
        "relatorios_ativos": True,
        "frequencia_relatorios": "semanal",
        "mercado_acoes": True,
        "mercado_fiis": True,
    }


def _alvo(usuario):
    """Rótulo de alvo para auditoria (email quando disponível, senão o id)."""
    if usuario is None:
        return None
    email = getattr(usuario, "email", None)
    return email if email else f"usuario:{usuario.id}"


def _garantir_permissao(usuario):
    """Exige a permissão central ``preferencias.proprias``.

    Levanta ``PermissaoNegadaError`` para usuário inválido, desativado ou sem a
    permissão na matriz (ex.: VISITOR, ADMIN, usuário inexistente). A decisão
    é SEMPRE da matriz central — nenhuma regra paralela por papel.
    """
    if not autorizacao.tem_permissao(usuario, "preferencias.proprias"):
        raise autorizacao.PermissaoNegadaError(
            permissao="preferencias.proprias",
            papel=autorizacao.papel_de(usuario),
            usuario_id=getattr(usuario, "id", None),
        )


def _validar_booleano(valor, nome):
    """Valida tipo booleano estrito (``bool``) — rejeita 0/1/"true"/None."""
    if not isinstance(valor, bool):
        raise ValueError(f"O campo '{nome}' deve ser um booleano.")
    return valor


def _validar_frequencia(valor, nome, permitidos):
    """Valida a enumeração controlada da frequência (normaliza para minúsculas)."""
    if not isinstance(valor, str):
        raise ValueError(
            f"O campo '{nome}' deve ser uma das opções: {', '.join(permitidos)}."
        )
    normalizado = str(valor).strip().lower()
    if normalizado not in permitidos:
        raise ValueError(
            f"Valor inválido para '{nome}'. Opções: {', '.join(permitidos)}."
        )
    return normalizado


def _validar_dados(dados):
    """Valida e normaliza um dicionário parcial de preferências.

    Rejeita campos proibidos (``id``, ``usuario_id``, timestamps), campos
    desconhecidos, tipos inválidos e valores nulos. Retorna apenas os campos
    válidos normalizados.
    """
    if dados is None or not isinstance(dados, dict):
        raise ValueError("Dados de preferências inválidos.")
    for campo in dados:
        if campo in CAMPOS_PROIBIDOS:
            raise ValueError(f"O campo '{campo}' não pode ser alterado.")
        if campo not in CAMPOS_ATUALIZAVEIS:
            raise ValueError(f"Campo desconhecido: '{campo}'.")
    resultado = {}
    for campo, valor in dados.items():
        if campo in CAMPOS_BOOLEANOS:
            resultado[campo] = _validar_booleano(valor, campo)
        else:
            resultado[campo] = _validar_frequencia(
                valor, campo, CAMPOS_FREQUENCIA[campo]
            )
    return resultado


def _buscar_linha(sessao, usuario):
    """Busca a linha de preferências do ``usuario`` (ou ``None``)."""
    return (
        sessao.query(PreferenciasUsuario)
        .filter(PreferenciasUsuario.usuario_id == usuario.id)
        .first()
    )


# ==========================================
# CONSULTA
# ==========================================


def buscar_preferencias(usuario, session=None):
    """Busca as preferências do ``usuario`` (1:1), ou ``None`` quando ausentes."""
    if usuario is None or getattr(usuario, "id", None) is None:
        return None
    with _sessao(session) as s:
        return _buscar_linha(s, usuario)


def obter_ou_criar_preferencias(usuario, session=None):
    """Retorna as preferências de ``usuario``, criando com defaults se ausente.

    Não cria usuário: exige um ``Usuario`` existente com permissão na matriz
    central. A linha é criada somente para o ``usuario.id`` do contexto
    autenticado — ``usuario_id`` arbitrário nunca é aceito. A criação
    registra ``PREFERENCIAS_CRIADAS`` na auditoria (sem segredos).
    """
    _garantir_permissao(usuario)
    if usuario is None or getattr(usuario, "id", None) is None:
        raise ValueError("Usuário inválido.")
    with _sessao(session) as s:
        preferencias = _buscar_linha(s, usuario)
        if preferencias is not None:
            return preferencias
        preferencias = PreferenciasUsuario(usuario_id=usuario.id)
        s.add(preferencias)
        s.commit()
        auditoria.registrar_evento(
            acao=ACAO_CRIADAS,
            alvo=_alvo(usuario),
            usuario_id=usuario.id,
            session=s,
        )
        return preferencias


# ==========================================
# ATUALIZAÇÃO E RESTAURAÇÃO
# ==========================================


def atualizar_preferencias(usuario, dados, session=None, ip=None):
    """Atualiza as preferências do ``usuario`` autenticado.

    Valida rigorosamente tipos, enums, campos proibidos e desconhecidos e
    valores nulos; aplica somente campos válidos. O proprietário é sempre
    ``usuario.id`` — ``usuario_id`` no payload é rejeitado. Registra
    ``PREFERENCIAS_ATUALIZADAS`` na auditoria com apenas os nomes dos campos
    alterados (nunca segredos, tokens, senhas ou API Keys).
    """
    _garantir_permissao(usuario)
    if usuario is None or getattr(usuario, "id", None) is None:
        raise ValueError("Usuário inválido.")
    dados_validos = _validar_dados(dados)
    if not dados_validos:
        raise ValueError("Nenhum campo válido para atualizar.")

    with _sessao(session) as s:
        preferencias = _buscar_linha(s, usuario)
        if preferencias is None:
            preferencias = PreferenciasUsuario(usuario_id=usuario.id)
            s.add(preferencias)
        for campo, valor in dados_validos.items():
            setattr(preferencias, campo, valor)
        s.commit()
        auditoria.registrar_evento(
            acao=ACAO_ATUALIZADAS,
            alvo=_alvo(usuario),
            detalhe=f"campos={','.join(sorted(dados_validos))}",
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
        return preferencias


def restaurar_preferencias_padrao(usuario, session=None, ip=None):
    """Restaura os defaults seguros das preferências de ``usuario``.

    Usado pelo endpoint ``POST /api/v1/preferencias/restaurar``. Não apaga a
    linha: reescreve todos os campos com ``preferencias_padrao()``. Registra
    ``PREFERENCIAS_RESTAURADAS`` na auditoria (sem segredos).
    """
    _garantir_permissao(usuario)
    if usuario is None or getattr(usuario, "id", None) is None:
        raise ValueError("Usuário inválido.")
    with _sessao(session) as s:
        preferencias = _buscar_linha(s, usuario)
        if preferencias is None:
            preferencias = PreferenciasUsuario(usuario_id=usuario.id)
            s.add(preferencias)
        for campo, valor in preferencias_padrao().items():
            setattr(preferencias, campo, valor)
        s.commit()
        auditoria.registrar_evento(
            acao=ACAO_RESTAURADAS,
            alvo=_alvo(usuario),
            usuario_id=usuario.id,
            ip=ip,
            session=s,
        )
        return preferencias
