"""Testes da camada central de acesso a LLM (Fase 7, Etapa 7.6).

Cobrem ``services.llm`` — a camada única que absorve ``module_ia``,
``llm_manager`` e ``atualizador_documentos.classificar_documento_com_ia``
(auditoria 7.1, item 4.1/§3). Garantias centrais:

- configuração centralizada (mesmas variáveis do legado, sem variável nova);
- retorno normal preservado ``(conteudo, None)``;
- erro de provedor com fallback para o próximo da fila;
- erro sanitizado: nenhum segredo (chave/token) vaza em logs ou no motivo;
- compatibilidade dos consumidores migrados (mesmos textos de erro legados);
- mocks pré-existentes (``motor_ia``, ``module_fatos``) permanecem intactos.
"""

import services.llm as llm

# ==========================================
# FAKES (cliente compatível com chat.completions.create)
# ==========================================

def _resposta_com_conteudo(conteudo):
    mensagem = type("Mensagem", (), {"content": conteudo})()
    choice = type("Choice", (), {"message": mensagem})()
    return type("Resposta", (), {"choices": [choice]})()


class ClienteFake:
    """Cliente OpenAI/Groq fake que registra os parâmetros recebidos."""

    def __init__(self, conteudo="ok"):
        self.resposta = _resposta_com_conteudo(conteudo)
        self.erro = None
        self.chamadas = []
        self._completions = _Completions(self)

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self._completions


class _Completions:
    def __init__(self, fake):
        self._fake = fake

    def create(self, **params):
        self._fake.chamadas.append(params)
        if self._fake.erro is not None:
            raise self._fake.erro
        return self._fake.resposta


def _usar_provedor(monkeypatch, provedor, cliente):
    monkeypatch.setitem(llm._CLIENTES, provedor, lambda: cliente)


def _nenhum_provedor_configurado(monkeypatch):
    for provedor in list(llm._CLIENTES):
        monkeypatch.setitem(llm._CLIENTES, provedor, lambda: None)


# ==========================================
# CONFIGURAÇÃO CENTRALIZADA
# ==========================================

def test_fila_padrao_reutiliza_envs_existentes():
    # A fila padrão usa GROQ_MODEL (ou o default) e os provedores do legado.
    assert llm.FILA_PADRAO[0][0] == "groq"
    assert llm.FILA_PADRAO[0][1] == (llm.GROQ_MODEL or llm.MODELO_GROQ_PADRAO)
    assert llm.FILA_PADRAO[1] == ("openrouter", "meta-llama/llama-3.3-70b-instruct")
    assert llm.FILA_PADRAO[2] == ("openai", "gpt-4o-mini")


def test_modelo_groq_tem_default_legado():
    # Default idêntico ao usado por module_ia/llm_manager/classificar.
    assert llm.MODELO_GROQ_PADRAO == "llama-3.3-70b-versatile"


def test_config_nao_cria_variavel_nova():
    # Só lê as envs que o legado já usava.
    for attr in ("GROQ_API_KEY", "GROQ_MODEL", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_BASE_URL"):
        assert hasattr(llm, attr)


# ==========================================
# RETORNO NORMAL
# ==========================================

def test_retorno_normal(monkeypatch):
    cliente = ClienteFake(conteudo="RESPOSTA DA IA")
    _usar_provedor(monkeypatch, "groq", cliente)

    conteudo, erro = llm.completar_chat(
        [{"role": "user", "content": "prompt"}], temperature=0.1
    )
    assert conteudo == "RESPOSTA DA IA"
    assert erro is None
    chamada = cliente.chamadas[0]
    assert chamada["messages"] == [{"role": "user", "content": "prompt"}]
    assert chamada["temperature"] == 0.1


def test_conteudo_vazio_eh_preservado(monkeypatch):
    # Resposta vazia (content None) não é tratada como erro — como no legado.
    cliente = ClienteFake(conteudo=None)
    _usar_provedor(monkeypatch, "groq", cliente)
    assert llm.completar_chat([{"role": "user", "content": "x"}]) == (None, None)


def test_response_format_repassado(monkeypatch):
    cliente = ClienteFake(conteudo='{"tipo": "x"}')
    _usar_provedor(monkeypatch, "groq", cliente)
    llm.completar_chat(
        [{"role": "user", "content": "x"}],
        fila_modelos=[("groq", "llama-3.3-70b-versatile")],
        response_format={"type": "json_object"},
    )
    assert cliente.chamadas[0]["response_format"] == {"type": "json_object"}


def test_temperature_none_nao_e_repassado(monkeypatch):
    cliente = ClienteFake()
    _usar_provedor(monkeypatch, "groq", cliente)
    llm.completar_chat([{"role": "user", "content": "x"}])
    assert "temperature" not in cliente.chamadas[0]


# ==========================================
# ERRO DE PROVEDOR E FALLBACK
# ==========================================

def test_erro_do_provedor_faz_fallback(monkeypatch):
    groq_falho = ClienteFake()
    groq_falho.erro = RuntimeError("boom groq")
    openai_ok = ClienteFake(conteudo="RESPOSTA OPENAI")
    _usar_provedor(monkeypatch, "groq", groq_falho)
    _usar_provedor(monkeypatch, "openai", openai_ok)

    conteudo, erro = llm.completar_chat([{"role": "user", "content": "x"}])
    assert conteudo == "RESPOSTA OPENAI"
    assert erro is None


def test_todos_provedores_falham_retorna_motivo(monkeypatch):
    groq_falho = ClienteFake()
    groq_falho.erro = RuntimeError("erro groq")
    openai_falho = ClienteFake()
    openai_falho.erro = RuntimeError("erro openai")
    _usar_provedor(monkeypatch, "groq", groq_falho)
    _usar_provedor(monkeypatch, "openai", openai_falho)

    conteudo, erro = llm.completar_chat([{"role": "user", "content": "x"}])
    assert conteudo is None
    assert erro == "Provedor 'openai' com modelo 'gpt-4o-mini' falhou."


def test_sem_credencial_retorna_motivo(monkeypatch):
    _nenhum_provedor_configurado(monkeypatch)
    conteudo, erro = llm.completar_chat([{"role": "user", "content": "x"}])
    assert conteudo is None
    assert erro == "Nenhum provedor LLM configurado/disponível."


# ==========================================
# SEGURANÇA: NENHUM SEGREDO EM LOGS OU NO MOTIVO
# ==========================================

def test_erro_nao_vaza_segredo_na_resposta(monkeypatch):
    cliente = ClienteFake()
    cliente.erro = RuntimeError("Unauthorized: api_key sk-SUPER-SECRETA-123 inválida")
    _usar_provedor(monkeypatch, "groq", cliente)

    _, erro = llm.completar_chat([{"role": "user", "content": "x"}])
    assert "sk-SUPER-SECRETA-123" not in erro


def test_erro_nao_vaza_segredo_no_log(monkeypatch, caplog):
    cliente = ClienteFake()
    cliente.erro = RuntimeError("token sk-SUPER-SECRETA-123 vazado")
    _usar_provedor(monkeypatch, "groq", cliente)

    with caplog.at_level("DEBUG"):
        llm.completar_chat([{"role": "user", "content": "x"}])

    assert "sk-SUPER-SECRETA-123" not in caplog.text


# ==========================================
# COMPATIBILIDADE DOS CONSUMIDORES MIGRADOS
# ==========================================

def _stub_completar_chat(conteudo, erro):
    def _stub(mensagens, fila_modelos=None, *, temperature=None, response_format=None):
        return conteudo, erro
    return _stub


def test_module_ia_analisar_fatos_sucesso(monkeypatch):
    from modules import module_ia
    monkeypatch.setattr(llm, "completar_chat", _stub_completar_chat("TEXTO-IA", None))
    assert module_ia.analisar_fatos_com_ia("prompt") == "TEXTO-IA"


def test_module_ia_erro_mantem_texto_legado(monkeypatch):
    from modules import module_ia
    monkeypatch.setattr(llm, "completar_chat", _stub_completar_chat(None, "Provedor 'groq' com modelo 'llama-3.3-70b-versatile' falhou."))
    resultado = module_ia.analisar_fatos_com_ia("prompt")
    assert resultado == "❌ Erro crítico na IA. Último erro: Provedor 'groq' com modelo 'llama-3.3-70b-versatile' falhou."


def test_module_ia_conteudo_vazio_retorna_none(monkeypatch):
    from modules import module_ia
    # Resposta vazia não vira texto de erro (comportamento legado).
    monkeypatch.setattr(llm, "completar_chat", _stub_completar_chat(None, None))
    assert module_ia.analisar_fatos_com_ia("prompt") is None


def test_llm_manager_sucesso(monkeypatch):
    from modules.llm_manager import LLMManager
    monkeypatch.setattr(llm, "completar_chat", _stub_completar_chat("X", None))
    assert LLMManager().analisar("p") == "X"


def test_llm_manager_erro_mantem_texto_legado(monkeypatch):
    from modules.llm_manager import LLMManager
    monkeypatch.setattr(llm, "completar_chat", _stub_completar_chat(None, "motivo"))
    resultado = LLMManager().analisar("p")
    assert resultado == "❌ Erro crítico: Todos os modelos e provedores falharam. Último erro: motivo"


def test_classificar_documento_com_ia_sucesso(monkeypatch):
    from atualizador_documentos import classificar_documento_com_ia
    monkeypatch.setattr(llm, "GROQ_API_KEY", "presente")
    resposta = '{"tipo": "Demonstracoes Financeiras", "confianca": 92}'
    monkeypatch.setattr(llm, "completar_chat", _stub_completar_chat(resposta, None))

    tipo, confianca = classificar_documento_com_ia("Nome Original", "texto do pdf")
    assert tipo == "Demonstracoes Financeiras"
    assert confianca == 92


def test_classificar_sem_credencial_cai_no_fallback(monkeypatch):
    from atualizador_documentos import classificar_documento_com_ia
    monkeypatch.setattr(llm, "GROQ_API_KEY", None)
    assert classificar_documento_com_ia("Nome Original", "texto do pdf") == ("Nome Original", 0)


def test_classificar_erro_do_provedor_cai_no_fallback(monkeypatch):
    from atualizador_documentos import classificar_documento_com_ia
    monkeypatch.setattr(llm, "GROQ_API_KEY", "presente")
    monkeypatch.setattr(llm, "completar_chat", _stub_completar_chat(None, "Provedor 'groq' com modelo 'llama-3.3-70b-versatile' falhou."))
    assert classificar_documento_com_ia("Nome Original", "texto do pdf") == ("Nome Original", 0)


def test_classificar_tipo_invalido_zera_confianca(monkeypatch):
    from atualizador_documentos import classificar_documento_com_ia
    monkeypatch.setattr(llm, "GROQ_API_KEY", "presente")
    resposta = '{"tipo": "Palavra Inventada", "confianca": 99}'
    monkeypatch.setattr(llm, "completar_chat", _stub_completar_chat(resposta, None))
    assert classificar_documento_com_ia("Nome Original", "texto do pdf") == ("Nome Original", 0)


def test_classificar_json_invalido_cai_no_fallback(monkeypatch):
    from atualizador_documentos import classificar_documento_com_ia
    monkeypatch.setattr(llm, "GROQ_API_KEY", "presente")
    monkeypatch.setattr(llm, "completar_chat", _stub_completar_chat("isso não é json", None))
    assert classificar_documento_com_ia("Nome Original", "texto do pdf") == ("Nome Original", 0)


def test_classificar_sem_texto_cai_no_fallback():
    from atualizador_documentos import classificar_documento_com_ia
    assert classificar_documento_com_ia("Nome Original", "") == ("Nome Original", 0)
    assert classificar_documento_com_ia("Nome Original", "   ") == ("Nome Original", 0)


# ==========================================
# MOCKS PRÉ-EXISTENTES PRESERVADOS
# ==========================================

def test_motor_ia_mock_preservado():
    # services/motor_ia.py permanece com a simulação hardcoded (não removida).
    import inspect

    import services.motor_ia as motor_ia
    assert callable(motor_ia.processar_relatorio_com_ia)
    fonte = inspect.getsource(motor_ia)
    assert "Simulação para validação do teste" in fonte


def test_module_fatos_mock_preservado():
    # module_fatos.py permanece com a fonte de documentos fictícia.
    import inspect

    import modules.module_fatos as module_fatos
    assert callable(module_fatos.buscar_fatos_relevantes)
    assert "LINK_DIRETO_DO_PDF_AQUI" in inspect.getsource(module_fatos)


def test_orquestrador_ia_placeholder_preservado():
    # orquestrador.py mantém a etapa IA como placeholder (sem chamada real).
    import services.orquestrador as orquestrador
    assert callable(orquestrador.varredura_diaria)
