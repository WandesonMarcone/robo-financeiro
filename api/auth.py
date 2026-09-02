"""Autenticação e autorização da API HTTP (Fase 5, Etapa 10).

Responsabilidades:
- extrair ``X-API-Key`` (e opcionalmente ``X-Session-Token``) da requisição;
- validar a API Key exclusivamente via ``services/chaves_api.py`` (que já
  gerencia o hash SHA-256 e o ciclo de vida da chave — nenhuma lógica de hash
  é duplicada aqui);
- validar sessão (quando informada) via ``services/sessoes.py``;
- identificar o usuário autenticado ou negar acesso (401) quando inválido;
- autorizar via ``services/autorizacao.py`` (matriz central) ou negar (403).

Precedência quando ``X-Session-Token`` e ``X-API-Key`` são enviados
simultaneamente:
- ``X-API-Key`` tem prioridade: quando presente e válida, autentica por ela;
- somente na ausência da API Key (ou quando ela é inválida) o
  ``X-Session-Token`` é considerado.
Essa precedência preserva o comportamento das integrações por API Key
existentes e é a regra única de desempate — não há terceira forma de
autenticação.

Não cria outro sistema de autenticação e não revela, na resposta, se a API Key
não existe, está expirada ou foi revogada.
"""
from functools import wraps

from flask import g, request

from api import dependencias
from api.respostas import resposta_erro
from services import auditoria, autorizacao, chaves_api, sessoes


def _extrair_credenciais():
    """Retorna ``(api_key, token_sessao)`` limpos dos cabeçalhos."""
    api_key = (request.headers.get("X-API-Key") or "").strip() or None
    token_sessao = (request.headers.get("X-Session-Token") or "").strip() or None
    return api_key, token_sessao


def autenticar_usuario(sessao):
    """Autentica a requisição atual e retorna o ``Usuario``, ou ``None``.

    Prioriza a API Key; na ausência (ou invalidez) dela, aceita o token de
    sessão já existente. Qualquer falha retorna ``None`` sem distinguir motivo.
    """
    api_key, token_sessao = _extrair_credenciais()
    if api_key:
        usuario = chaves_api.validar_chave_api(api_key, session=sessao)
        if usuario is not None:
            return usuario
    if token_sessao:
        return sessoes.validar_sessao(token_sessao, session=sessao)
    return None


def rota_protegida(permissao):
    """Decorator que exige autenticação e a ``permissao`` da matriz central.

    - sem credencial válida -> ``401 Unauthorized``;
    - autenticado sem permissão -> ``403 Forbidden``;
    - autorizado -> expõe ``g.usuario`` e ``g.sessao`` à rota.
    """

    def decorator(funcao):
        @wraps(funcao)
        def wrapper(*args, **kwargs):
            sessao = dependencias.obter_sessao()
            try:
                usuario = autenticar_usuario(sessao)
                if usuario is None:
                    return resposta_erro("Não autenticado.", 401)
                if not autorizacao.tem_permissao(usuario, permissao):
                    auditoria.registrar_evento(
                        acao="API_ACESSO_NEGADO",
                        alvo=(
                            usuario.email
                            if usuario.email
                            else f"usuario:{usuario.id}"
                        ),
                        detalhe=f"permissao={permissao}",
                        usuario_id=usuario.id,
                        ip=request.remote_addr,
                        sucesso=False,
                        session=sessao,
                    )
                    return resposta_erro("Acesso negado.", 403)
                g.usuario = usuario
                g.sessao = sessao
                return funcao(*args, **kwargs)
            finally:
                sessao.close()

        return wrapper

    return decorator
