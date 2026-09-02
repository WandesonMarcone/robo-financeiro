"""Motor central de autorização e permissões (Fase 5, Etapa 6).

A autorização é baseada exclusivamente no papel do usuário e em uma matriz
centralizada de permissões (``PAPEL_PERMISSOES``). Nenhuma regra de acesso
deve ser duplicada em outros arquivos: comandos/handlers/camadas futuras devem
consultar ``tem_permissao``/``requer_permissao`` e a política de gestão de
papéis (``pode_alterar_papel``).

Princípios da política:
- ``SUPERADMIN`` possui ``"*"`` (acesso irrestrito) e pode administrar usuários,
  administradores, configurações, dados, alertas e recursos do sistema.
- ``ADMIN`` gerencia usuários e recursos, mas NUNCA assume poderes de
  SUPERADMIN: não promove ninguém a SUPERADMIN e não altera/remove o
  SUPERADMIN protegido (regra explícita de proteção).
- ``USER`` consulta dados/documentos/relatórios/indicadores/histórico/alertas e
  gerencia apenas o próprio escopo (conta/ativos/preferências/notificações).
- ``VISITOR`` acessa somente recursos explicitamente públicos; ``usuario=None``
  (requisição sem autenticação) é tratado como VISITOR.
- Usuário desativado não recebe qualquer autorização.
- A autorização usa apenas ``papel``, ``ativo`` e ``id`` — nunca lê ou registra
  senha, token, chave de API ou qualquer segredo.
- Nenhum vínculo com um usuário específico ou com ``TELEGRAM_CHAT_ID``: qualquer
  instância válida de ``Usuario`` é aceita (preparo para multi-usuário).

Etapas posteriores (não implementadas aqui): sessões, API keys, login web,
endpoints, carteira/acompanhamento/notificações individualizadas.
"""
import logging

from services.usuarios import (
    ADMIN,
    PAPEIS_VALIDOS,
    SUPERADMIN,
    USER,
    VISITOR,
)

logger = logging.getLogger(__name__)

# Permissão que representa acesso irrestrito (exclusiva do SUPERADMIN).
PERMISSAO_TODAS = "*"

# ---------------------------------------------------------------------------
# MATRIZ CENTRAL DE PERMISSÕES POR PAPEL (fonte única de verdade)
# ---------------------------------------------------------------------------
PAPEL_PERMISSOES = {
    SUPERADMIN: frozenset({PERMISSAO_TODAS}),
    ADMIN: frozenset(
        {
            "usuarios.ler",
            "usuarios.criar",
            "usuarios.ativar",
            "usuarios.desativar",
            "usuarios.alterar_papel",
            "dados.consultar",
            "documentos.consultar",
            "relatorios.consultar",
            "indicadores.consultar",
            "historico.consultar",
            "alertas.gerenciar",
            "telegram.administrar",
            "conta.propria",
        }
    ),
    USER: frozenset(
        {
            "dados.consultar",
            "documentos.consultar",
            "relatorios.consultar",
            "indicadores.consultar",
            "historico.consultar",
            "alertas.consultar",
            "notificacoes.consultar",
            "conta.propria",
            "ativos.proprios",
            "preferencias.proprias",
            # Recursos de IA destinados ao usuário serão adicionados quando
            # forem implementados (etapas posteriores).
        }
    ),
    VISITOR: frozenset(
        {
            "publico.consultar",
            "ativos.publicos.consultar",
            "indicadores.publicos.consultar",
        }
    ),
}

# ---------------------------------------------------------------------------
# ISOLAMENTO ENTRE USUÁRIOS (preparo para multi-usuário)
# ---------------------------------------------------------------------------
# Permissões de escopo próprio: só valem para o usuário autenticado. A
# validação de escopo (garantir que o recurso pertence ao usuário) ocorre nas
# etapas de API/site; aqui apenas centralizamos os identificadores.
PERMISSOES_ESCOPO_PROPRIO = frozenset(
    {
        "conta.propria",
        "ativos.proprios",
        "preferencias.proprias",
        "notificacoes.consultar",
    }
)


def eh_permissao_escopo_proprio(permissao):
    """True quando ``permissao`` exige validação de escopo próprio."""
    return permissao in PERMISSOES_ESCOPO_PROPRIO


# ---------------------------------------------------------------------------
# POLÍTICA DE GESTÃO DE PAPÉIS (anti-escalonamento)
# ---------------------------------------------------------------------------
# Papéis que um ADMIN pode atribuir/gerenciar. SUPERADMIN está EXCLUÍDO:
# promover/atribuir SUPERADMIN é poder exclusivo do SUPERADMIN.
PAPEIS_ATRIBUIVEIS_POR_ADMIN = frozenset({USER, VISITOR})

# Papéis atribuíveis por papéis abaixo de ADMIN (nenhum).
PAPEIS_ATRIBUIVEIS_POR_USER = frozenset()
PAPEIS_ATRIBUIVEIS_POR_VISITOR = frozenset()

# ---------------------------------------------------------------------------
# RESOLUÇÃO DO PAPEL EFETIVO
# ---------------------------------------------------------------------------


def papel_de(usuario):
    """Papel efetivo usado pela autorização.

    Retorna ``VISITOR`` para ``usuario=None`` (requisição sem autenticação) e
    ``None`` para usuário desativado, papel inválido ou objeto que não seja uma
    instância válida de ``Usuario`` (acesso negado).
    """
    if usuario is None:
        return VISITOR
    try:
        papel = getattr(usuario, "papel", None)
        ativo = getattr(usuario, "ativo", False)
    except Exception:
        return None
    if ativo is not True:
        return None
    if papel not in PAPEIS_VALIDOS:
        return None
    return papel


# ---------------------------------------------------------------------------
# CHECAGEM DE PERMISSÃO
# ---------------------------------------------------------------------------


def tem_permissao(usuario, permissao):
    """True se ``usuario`` possui ``permissao`` segundo a matriz central.

    ``SUPERADMIN`` possui ``"*"`` e, portanto, qualquer permissão. Um usuário
    desativado ou um objeto inválido nunca possui permissão. ``usuario=None``
    é avaliado como VISITOR (somente permissões públicas).
    """
    papel = papel_de(usuario)
    if papel is None:
        return False
    permissoes = PAPEL_PERMISSOES.get(papel, frozenset())
    if PERMISSAO_TODAS in permissoes:
        return True
    return permissao in permissoes


class PermissaoNegadaError(Exception):
    """Levantada por ``requer_permissao`` quando o acesso deve ser negado.

    Carrega apenas ``permissao``, ``papel`` e ``usuario_id`` — nunca senha,
    token ou qualquer segredo.
    """

    def __init__(self, permissao=None, papel=None, usuario_id=None):
        self.permissao = permissao
        self.papel = papel
        self.usuario_id = usuario_id
        super().__init__(f"Acesso negado: permissão '{permissao}' requerida.")


def requer_permissao(usuario, permissao):
    """Garante que ``usuario`` possui ``permissao``.

    Retorna ``True`` quando autorizado; caso contrário levanta
    ``PermissaoNegadaError`` (sem expor segredos). É o mecanismo padrão de
    negação de acesso para as camadas de comando/API/site.
    """
    if tem_permissao(usuario, permissao):
        return True
    raise PermissaoNegadaError(
        permissao=permissao,
        papel=papel_de(usuario),
        usuario_id=getattr(usuario, "id", None) if usuario is not None else None,
    )


# ---------------------------------------------------------------------------
# IDENTIFICAÇÃO DE PAPEL (funções auxiliares)
# ---------------------------------------------------------------------------


def eh_superadmin(usuario):
    """True apenas para um SUPERADMIN ativo."""
    return papel_de(usuario) == SUPERADMIN


def eh_admin(usuario):
    """True apenas para um ADMIN ativo."""
    return papel_de(usuario) == ADMIN


def eh_user(usuario):
    """True apenas para um USER ativo."""
    return papel_de(usuario) == USER


def eh_visitor(usuario):
    """True para ``usuario=None`` (sem autenticação) ou um VISITOR ativo."""
    return papel_de(usuario) == VISITOR


# ---------------------------------------------------------------------------
# POLÍTICA DE GESTÃO DE USUÁRIOS (anti-escalonamento e proteção)
# ---------------------------------------------------------------------------


def papeis_atribuiveis_por(autor):
    """Papéis que ``autor`` pode atribuir/promover.

    SUPERADMIN atribui qualquer papel; ADMIN atribui apenas
    ``PAPEIS_ATRIBUIVEIS_POR_ADMIN`` (nunca SUPERADMIN); USER/VISITOR nenhum.
    """
    papel = papel_de(autor)
    if papel == SUPERADMIN:
        return frozenset(PAPEIS_VALIDOS)
    if papel == ADMIN:
        return PAPEIS_ATRIBUIVEIS_POR_ADMIN
    if papel == USER:
        return PAPEIS_ATRIBUIVEIS_POR_USER
    if papel == VISITOR:
        return PAPEIS_ATRIBUIVEIS_POR_VISITOR
    return frozenset()


def usuario_protegido(usuario):
    """True para usuários que exigem SUPERADMIN para ter o papel alterado.

    Regra explícita de proteção: um usuário SUPERADMIN (incluindo o SUPERADMIN
    inicial criado pelo seed) só pode ser alterado/removido por outro
    SUPERADMIN — nunca por ADMIN.
    """
    return papel_de(usuario) == SUPERADMIN


def pode_alterar_papel(autor, alvo, novo_papel):
    """True se ``autor`` pode alterar o papel de ``alvo`` para ``novo_papel``.

    Barra escalonamento de privilégio:
    - ``novo_papel`` precisa estar entre os papéis atribuíveis por ``autor``;
    - usuário protegido (SUPERADMIN) só pode ser alterado por SUPERADMIN.
    """
    if novo_papel not in papeis_atribuiveis_por(autor):
        return False
    if usuario_protegido(alvo) and not eh_superadmin(autor):
        return False
    return True


def pode_criar_usuario_com_papel(autor, papel):
    """True se ``autor`` pode criar um usuário com ``papel``.

    Combina a permissão ``usuarios.criar`` com a política de papéis, impedindo
    que ADMIN (ou inferior) crie/promova SUPERADMIN.
    """
    if not tem_permissao(autor, "usuarios.criar"):
        return False
    return papel in papeis_atribuiveis_por(autor)
