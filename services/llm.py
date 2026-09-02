"""Camada central de acesso a modelos de IA — Fase 7, Etapa 7.6.

Ponto único de integração com provedores de LLM (Groq / OpenRouter / OpenAI e
qualquer servidor compatível com a API da OpenAI). Absorve as implementações
concorrentes apontadas pela auditoria 7.1 (``modules/module_ia.py``,
``modules/llm_manager.py`` e ``atualizador_documentos.classificar_documento_com_ia``),
centralizando:

- configuração: reutiliza as mesmas variáveis de ambiente já usadas pelo legado
  (``GROQ_API_KEY``/``GROQ_MODEL``, ``OPENAI_API_KEY``, ``OPENROUTER_API_KEY``,
  ``OPENAI_BASE_URL``) — nenhuma variável nova foi criada;
- chamada: fila ordenada de ``(provedor, modelo)`` com fallback automático;
- tratamento de erros: a falha é registrada em log sem prompt, sem chaves e sem
  o texto bruto da exceção (que pode embutir a API key); o motivo devolvido ao
  chamador é igualmente sanitizado;
- retorno compatível: ``(conteudo, None)`` em sucesso ou ``(None, motivo)`` quando
  nenhum provedor responde — o chamador preserva o seu texto/tratamento de erro.

Trocar de provedor no futuro exige apenas ajustar a fila padrão e/ou a
configuração neste módulo, sem espalhar alterações pelo sistema.
"""
import logging
import os

from groq import Groq
from openai import OpenAI

logger = logging.getLogger(__name__)

# ==========================================
# CONFIGURAÇÃO CENTRALIZADA (mesmas envs do legado)
# ==========================================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL")

URL_OPENROUTER = "https://openrouter.ai/api/v1"
MODELO_GROQ_PADRAO = "llama-3.3-70b-versatile"
MODELO_OPENROUTER_PADRAO = "meta-llama/llama-3.3-70b-instruct"
MODELO_OPENAI_PADRAO = "gpt-4o-mini"

FILA_PADRAO = (
    ("groq", GROQ_MODEL or MODELO_GROQ_PADRAO),
    ("openrouter", MODELO_OPENROUTER_PADRAO),
    ("openai", MODELO_OPENAI_PADRAO),
)

_MSG_SEM_PROVEDOR = "Nenhum provedor LLM configurado/disponível."


# ==========================================
# CLIENTES (construídos sob demanda; nada de segredo em logs)
# ==========================================

def _cliente_groq() -> Groq | None:
    if not GROQ_API_KEY:
        return None
    return Groq(api_key=GROQ_API_KEY)


def _cliente_openai() -> OpenAI | None:
    if not OPENAI_API_KEY and not OPENAI_BASE_URL:
        return None
    return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL or None)


def _cliente_openrouter() -> OpenAI | None:
    if not OPENROUTER_API_KEY:
        return None
    return OpenAI(api_key=OPENROUTER_API_KEY, base_url=URL_OPENROUTER)


_CLIENTES = {
    "groq": _cliente_groq,
    "openai": _cliente_openai,
    "openrouter": _cliente_openrouter,
}


# ==========================================
# CHAMADA ÚNICA
# ==========================================

def completar_chat(
    mensagens,
    fila_modelos=None,
    *,
    temperature=None,
    response_format=None,
) -> tuple[str | None, str | None]:
    """Envia ``mensagens`` pela fila de ``(provedor, modelo)`` até obter sucesso.

    Parâmetros compatíveis com os consumidores legados: ``mensagens`` (lista de
    dicts ``{"role", "content"}``), ``fila_modelos`` (lista de ``(provedor,
    modelo)``; padrão é ``FILA_PADRAO``), ``temperature`` e ``response_format``
    (repassados ao provedor apenas quando fornecidos).

    Retorna ``(conteudo, None)`` quando um provedor responde (``conteudo`` pode
    ser ``None`` em resposta vazia, como no legado) ou ``(None, motivo)`` quando
    todos os provedores falham ou nenhum está configurado. O ``motivo`` nunca
    contém o texto da exceção, prompts ou chaves.
    """
    fila = list(fila_modelos) if fila_modelos else list(FILA_PADRAO)
    ultimo_motivo = ""

    for provedor, modelo in fila:
        construtor = _CLIENTES.get(provedor)
        if construtor is None:
            continue

        params = {"messages": mensagens, "model": modelo}
        if temperature is not None:
            params["temperature"] = temperature
        if response_format is not None:
            params["response_format"] = response_format

        try:
            cliente = construtor()
            if cliente is None:
                continue
            resposta = cliente.chat.completions.create(**params)
        except Exception as exc:
            ultimo_motivo = f"Provedor '{provedor}' com modelo '{modelo}' falhou."
            logger.warning("LLM indisponível: %s", ultimo_motivo)
            logger.debug("LLM falha em %s/%s: %s", provedor, modelo, type(exc).__name__)
            continue

        return resposta.choices[0].message.content, None

    if not ultimo_motivo:
        ultimo_motivo = _MSG_SEM_PROVEDOR
    return None, ultimo_motivo
