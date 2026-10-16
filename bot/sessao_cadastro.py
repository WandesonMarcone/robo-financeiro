"""Estado (em memória) do formulário conversacional de autocadastro.

Este módulo é deliberadamente leve: depende apenas da biblioteca padrão. Ele é
importado tanto pelo fluxo de cadastro (``bot.cadastro``) quanto pela camada de
autorização (``bot.permissoes`` / ``bot.loader``), que precisa reconhecer um
chat que está preenchendo o formulário antes de existir qualquer registro no
banco. Importá-lo não cria o bot nem toca no banco.

Limitação conhecida (documentada, não "inventada"): o estado vive na memória do
processo. Se a aplicação reiniciar ou rodar com múltiplos workers, um formulário
em andamento pode ser perdido; nesse caso o usuário simplesmente reinicia com
``/start``. Nenhuma coluna nova é criada no banco para evitar alterar o schema.
"""

import threading
import time

# Tempo de validade de um formulário em andamento (30 minutos).
TTL_SEGUNDOS = 30 * 60

# Etapas do formulário.
ETAPA_NOME = "nome"
ETAPA_EMAIL = "email"
ETAPA_CONFIRMACAO = "confirmacao"

_lock = threading.RLock()
_sessoes = {}


class SessaoCadastro:
    """Formulário em andamento de um usuário do Telegram."""

    __slots__ = ("usuario_id", "chat_id", "etapa", "nome", "email", "atualizado_em")

    def __init__(self, usuario_id, chat_id):
        self.usuario_id = usuario_id
        self.chat_id = chat_id
        self.etapa = ETAPA_NOME
        self.nome = None
        self.email = None
        self.atualizado_em = time.monotonic()


def _chave(usuario_id):
    if usuario_id is None:
        return None
    return str(usuario_id).strip() or None


def _expirada(sessao):
    return (time.monotonic() - sessao.atualizado_em) > TTL_SEGUNDOS


def _descartar(chave):
    _sessoes.pop(chave, None)


def iniciar(usuario_id, chat_id):
    """Cria/reinicia o formulário, voltando à etapa de nome."""
    chave = _chave(usuario_id)
    if chave is None:
        return None
    with _lock:
        sessao = SessaoCadastro(usuario_id, chat_id)
        _sessoes[chave] = sessao
        return sessao


def obter(usuario_id):
    """Retorna o formulário ativo (ou ``None``), descartando os expirados."""
    chave = _chave(usuario_id)
    if chave is None:
        return None
    with _lock:
        sessao = _sessoes.get(chave)
        if sessao is None:
            return None
        if _expirada(sessao):
            _descartar(chave)
            return None
        return sessao


def tem_sessao_ativa(usuario_id):
    """True se existe um formulário válido em andamento para o usuário."""
    return obter(usuario_id) is not None


def atualizar(usuario_id, **campos):
    chave = _chave(usuario_id)
    if chave is None:
        return None
    with _lock:
        sessao = _sessoes.get(chave)
        if sessao is None or _expirada(sessao):
            _descartar(chave)
            return None
        for nome, valor in campos.items():
            if nome in SessaoCadastro.__slots__:
                setattr(sessao, nome, valor)
        sessao.atualizado_em = time.monotonic()
        return sessao


def cancelar(usuario_id):
    """Encerra o formulário. Retorna True se havia algo para cancelar."""
    chave = _chave(usuario_id)
    if chave is None:
        return False
    with _lock:
        return _sessoes.pop(chave, None) is not None


def limpar(usuario_id):
    """Remove o formulário (após conclusão ou recusa)."""
    cancelar(usuario_id)


def limpar_tudo():
    """Limpa todo o estado em memória (uso em testes)."""
    with _lock:
        _sessoes.clear()
