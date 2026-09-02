"""Camada central de escopo e isolamento por usuário (Fase 6, Etapa 3).

Centraliza TODAS as regras de "a quem pertence um recurso" e "quem pode acessar
um recurso", para que as rotas NUNCA repitam condições de propriedade. A
autorização por papel continua exclusivamente em ``services/autorizacao.py``;
esta camada decide apenas o ESCOPO (público / próprio / administrativo).

Contrato mínimo de um recurso com dono:
- ``usuario_id``: id do usuário dono. ``None`` indica recurso público
  (dado de plataforma, sem dono).
- ``publico`` (opcional): ``True`` força o recurso como público mesmo quando
  ``usuario_id`` está preenchido.

Política de escopo (sem herança implícita de permissões):
- ``PUBLICO``: recurso sem dono -> acessível por qualquer usuário (a permissão
  de domínio da matriz central continua decidindo cada rota).
- ``PROPRIO``: ``recurso.usuario_id == usuario.id`` -> o dono acessa e altera.
- ``ADMINISTRATIVO``: recurso de terceiros -> somente com ``permissao_administrativa``
  explícita na matriz central OU SUPERADMIN (wildcard ``"*"``). ADMIN não recebe
  acesso privado implícito aos recursos dos usuários.

Garantias:
- ``None`` (usuário inexistente) e usuário desativado nunca acessam recurso
  privado.
- ``buscar_recurso_escopado`` retorna ``None`` tanto para recurso inexistente
  quanto para recurso sem permissão de escopo: a resposta é indistinguível,
  prevenindo enumeração e IDOR/BOLA.
- Nenhuma senha, token, API Key ou segredo é lido, exposto ou registrado aqui.
- O contrato (``usuario_id``/``publico``) prepara as etapas futuras (carteira,
  ativos acompanhados, notificações, preferências, relatórios personalizados)
  sem criar nenhuma dessas tabelas.
"""
from services import autorizacao


class EscopoError(Exception):
    """Erro base da camada de escopo."""


class AcessoRecursoNegadoError(EscopoError):
    """Levantada quando o usuário não possui acesso de escopo a um recurso.

    Mensagem genérica, sem segredos e sem revelar o conteúdo do recurso;
    carrega apenas metadados opcionais para auditoria (tipo do recurso e
    permissão exigida).
    """

    def __init__(self, recurso_tipo=None, permissao=None):
        self.recurso_tipo = recurso_tipo
        self.permissao = permissao
        super().__init__("Acesso negado ao recurso.")


# ==========================================
# PROPRIEDADE
# ==========================================


def dono_do_recurso(recurso):
    """Id do usuário dono do ``recurso``, ou ``None`` (recurso público).

    Recursos sem atributo ``usuario_id`` (dados de plataforma) são tratados
    como públicos. ``publico=True`` força o recurso como público.
    """
    if recurso is None:
        return None
    if getattr(recurso, "publico", False):
        return None
    return getattr(recurso, "usuario_id", None)


def recurso_eh_publico(recurso):
    """True quando o ``recurso`` não possui dono (público, de plataforma)."""
    return dono_do_recurso(recurso) is None


def recurso_pertence_a(recurso, usuario):
    """True quando ``recurso.usuario_id`` é igual a ``usuario.id``."""
    if recurso is None or usuario is None:
        return False
    dono_id = dono_do_recurso(recurso)
    if dono_id is None:
        return False
    id_usuario = getattr(usuario, "id", None)
    return id_usuario is not None and dono_id == id_usuario


# ==========================================
# POLÍTICA DE ESCOPO
# ==========================================


def usuario_pode_administrar(usuario, permissao_administrativa=None):
    """True quando ``usuario`` pode administrar recursos de terceiros.

    SUPERADMIN (wildcard ``"*"``) sempre pode. Os demais exigem a
    ``permissao_administrativa`` explícita na matriz central — ADMIN não recebe
    acesso privado implícito aos recursos dos usuários.
    """
    if autorizacao.eh_superadmin(usuario):
        return True
    if permissao_administrativa is None:
        return False
    return autorizacao.tem_permissao(usuario, permissao_administrativa)


def usuario_pode_acessar(usuario, recurso, permissao_administrativa=None):
    """True quando ``usuario`` pode LER ``recurso`` (escopo de acesso).

    Política (sem herança implícita):
    1. usuário nulo/desativado nunca acessa recurso (papel efetivo inválido);
    2. recurso público -> True;
    3. recurso do próprio usuário -> True;
    4. permissão administrativa explícita (ou SUPERADMIN) -> True;
    5. caso contrário (recurso privado de terceiros) -> False.
    """
    if autorizacao.papel_de(usuario) is None:
        return False
    if recurso is None:
        return False
    if recurso_eh_publico(recurso):
        return True
    if recurso_pertence_a(recurso, usuario):
        return True
    return usuario_pode_administrar(usuario, permissao_administrativa)


def usuario_pode_alterar(usuario, recurso, permissao_administrativa=None):
    """True quando ``usuario`` pode ALTERAR/EXCLUIR ``recurso``.

    Mais restritivo que a leitura: recurso público NÃO pode ser alterado por
    qualquer usuário — apenas pelo dono (quando tem dono) ou por quem possui
    permissão administrativa explícita (ou SUPERADMIN). Abrange update e delete.
    """
    if autorizacao.papel_de(usuario) is None:
        return False
    if recurso is None:
        return False
    if recurso_pertence_a(recurso, usuario):
        return True
    return usuario_pode_administrar(usuario, permissao_administrativa)


def requer_recurso_acessivel(
    usuario, recurso, permissao_administrativa=None, recurso_tipo=None
):
    """Garante acesso de leitura; levanta ``AcessoRecursoNegadoError`` se negado."""
    if not usuario_pode_acessar(usuario, recurso, permissao_administrativa):
        raise AcessoRecursoNegadoError(
            recurso_tipo=recurso_tipo, permissao=permissao_administrativa
        )
    return True


def requer_pode_alterar(
    usuario, recurso, permissao_administrativa=None, recurso_tipo=None
):
    """Garante permissão de alteração/exclusão; levanta ``AcessoRecursoNegadoError`` se negado."""
    if not usuario_pode_alterar(usuario, recurso, permissao_administrativa):
        raise AcessoRecursoNegadoError(
            recurso_tipo=recurso_tipo, permissao=permissao_administrativa
        )
    return True


# ==========================================
# PADRÃO DE BUSCA ESCOPADA (ANTI-IDOR/BOLA)
# ==========================================


def buscar_recurso_escopado(
    sessao, modelo, recurso_id, usuario, permissao_administrativa=None
):
    """Busca um recurso pelo id aplicando o escopo, sem revelar existência.

    Retorna o objeto apenas quando ``usuario`` pode acessá-lo; ``None`` em
    qualquer outro caso (recurso inexistente OU sem permissão de escopo). A
    resposta é idêntica nos dois cenários, prevenindo enumeração de recursos
    privados e IDOR/BOLA.

    Padrão a ser usado pelas rotas de recursos privados nas próximas etapas:
    NUNCA retornar um recurso buscado pelo id do cliente sem validar o
    proprietário. Exemplo de uso futuro::

        recurso = escopo.buscar_recurso_escopado(
            g.sessao, Carteira, recurso_id, g.usuario,
            permissao_administrativa="carteira.administrar",
        )
        if recurso is None:
            return resposta_erro("Recurso não encontrado.", 404)
    """
    recurso = sessao.get(modelo, recurso_id)
    if recurso is None:
        return None
    if not usuario_pode_acessar(usuario, recurso, permissao_administrativa):
        return None
    return recurso
