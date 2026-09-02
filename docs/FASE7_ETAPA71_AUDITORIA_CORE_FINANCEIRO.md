# Fase 7 — Etapa 7.1: Auditoria do Núcleo Financeiro Atual

> Documento de auditoria (somente análise). NÃO altera código, NÃO cria
> funcionalidades, NÃO migra banco e NÃO avança para a Etapa 7.2.
> Data da auditoria: 2026-08-29 — Commit base: `d8e5255` (árvore de trabalho limpa).

---

## 1. Estado atual

### 1.1 Contexto do repositório
- **Banco principal**: PostgreSQL/Neon via `DATABASE_URL` (`config.obter_database_url()`, `config.py:20-29`). SQLite é usado apenas em dev (`main.py:9-36`).
- **Fonte ativa de dados de mercado**: Google Sheets (abas `BD_FIIs`/`BD_Acoes`). O PostgreSQL é **espelho** (`app.py:47-60`, flag `ESPELHAMENTO_PG_ATIVO`, padrão `false` em `config.py:61`).
- **Suíte de testes**: 907 testes passando, Ruff limpo nos arquivos da Fase 5/6 (legado em `bot/`, `modules/`, `migration_package/`, `services/{dashboard_menus,logo_service,motor_ia,planilhas}.py` acumula 154 erros).

### 1.2 Fluxos de dados existentes

**Fluxo 1 — Garimpo de mercado (Sheets, legado operante):**
`modules/scraper_fiis.py`/`scraper_acoes.py` (Fundamentus + yfinance + StatusInvest) → `app.py` (`executar_auditoria_carteira`) → `batch_update` no Google Sheets → `disparar_alertas` (Telegram) → [opcional, flag] espelhamento 5C → PostgreSQL.

**Fluxo 2 — Dados contábeis estruturados (CVM):**
- `pipeline_dados/coletor_cvm.py` (ITR de ações) → `dados_financeiros_acoes`.
- `pipeline_dados/coletor_fiis.py` (Informes Mensais de FIIs) → `dados_financeiros_fiis`.

**Fluxo 3 — Documentos qualitativos (B3/CVM → Drive):**
`fnet_scraper.py` (B3 FNET, FIIs) + `pipeline_dados/coletor_docs_acoes.py` (CVM IPE, ações) → `documentos_qualitativos` → `atualizador_documentos.py` (download → deduplicação SHA-256 → classificação com IA → upload Google Drive → revisão manual via Telegram).

**Fluxo 4 — Motor de qualidade/alertas (Fase 4):**
`espelhamento_mercado_5c.py` chama `motor_alertas.processar_indicadores_ativo` (FIIs/ACAO) → `indicadores_historico` + `alertas_eventos` → Telegram legado + `services.notificacoes.processar_evento` (notificações individuais da Fase 6) → dispatcher Telegram (`main.py:160-182`).

**Fluxo 5 — Telegram (menus/relatórios legados):**
`bot/*` + `services/dashboard_menus.py` leem o Sheets via cache (`services/planilhas.py`) e o PostgreSQL (`atualizador_documentos.SessionDB`).

### 1.3 Esquema financeiro no PostgreSQL
- Identidade: `ativos` (`ticker` UNIQUE, `cnpj` UNIQUE NOT NULL, `tipo` ENUM ACAO/FII) — `banco_dados.py:30-36`.
- Contábil: `dados_financeiros_acoes` (ITR), `dados_financeiros_fiis` (informe mensal).
- Documentos: `documentos_qualitativos` (+ `hash_sha256` p/ dedup, `id_b3` único).
- Mercado (Bloco 5B): `ativos_perfil` (1:1), `snapshots_fiis`, `snapshots_acoes`, `ativos_inquilinos`.
- Inteligência (Fase 4): `indicadores_historico`, `alertas_eventos`.
- Multiusuário (Fase 5/6): `usuarios`, `sessoes`, `chaves_api`, `auditoria_acesso`, `ativos_acompanhados`, `posicoes_carteira`, `preferencias_usuarios`, `notificacoes`.

---

## 2. Mapa de componentes

Legenda: 🟢 MANTER · 🔵 EVOLUIR · 🟡 REFATORAR · 🟠 MOVER · 🔴 SUBSTITUIR · ⚫ REMOVER · 🆕 CRIAR

### 2.1 Camada de mercado (Sheets + scrapers)
| Componente | Classificação | Onde | O que faz | Quem utiliza | Entradas | Saídas |
|---|---|---|---|---|---|---|
| `modules/scraper_fiis.py` | 🟡 | `modules/` | Garimpa FIIs (Fundamentus/yfinance/StatusInvest) e grava `BD_FIIs` | `app.py` | planilha, tickers, carimbo | `batch_updates`, mensagem Telegram |
| `modules/scraper_acoes.py` | 🟡 | `modules/` | Garimpa ações e grava `BD_Acoes` | `app.py` | planilha, tickers, carimbo | `batch_updates`, mensagem Telegram |
| `modules/utils.py` (`formatar`/`precisa_atualizar`) | 🟡 | `modules/` | Parsing/atualização legada de valores | scrapers, `disparar_alertas` | valores brutos | floats / decisão de refresh |
| `modules/utils.py` (`conectar_gspread`/`get_request_with_retry`) | 🟢 | `modules/` | Conexão Sheets e HTTP com retry | scrapers, coletores, planilhas | credenciais/URL | cliente gspread / resposta |
| `services/planilhas.py` | 🟢 | `services/` | Cache de 5 min + leitura das abas | espelhamentos, dashboard_menus, bot | nome da aba | matriz de valores |
| `app.py` | 🟢 | raiz | Orquestra scrapers → Sheets → espelhamento → alerta | CLI/agendador | — | Sheets atualizado, relatório |

### 2.2 Espelhamento Sheets → PostgreSQL (Fase 3)
| Componente | Classificação | Onde | O que faz | Quem utiliza | Entradas | Saídas |
|---|---|---|---|---|---|---|
| `pipeline_dados/mapeamento_sheets.py` | 🟢 | `pipeline_dados/` | Documenta/transforma colunas das abas | espelhamentos, testes | matriz | dicts normalizados, lacunas |
| `pipeline_dados/qualidade_dados.py` | 🟢 | `pipeline_dados/` | Validação determinística VALID/WARNING/INVALID | todos os coletores + espelhamentos | registro, contexto | `ResultadoQualidade` |
| `pipeline_dados/normalizacao.py` | 🟢 | `pipeline_dados/` | Normaliza CNPJ/data/texto (offline) | todos os coletores + espelhamentos | valor bruto | valor normalizado |
| `pipeline_dados/espelhamento_sheets.py` | 🟢 | `pipeline_dados/` | Espelha identidade do ativo (ticker/cnpj/tipo) | 5C, testes | matriz | relatório de diagnóstico |
| `pipeline_dados/espelhamento_mercado_5c.py` | 🟢 | `pipeline_dados/` | Espelha snapshots/perfil/inquilinos + dispara Fase 4 | `app.py` (flag) | matriz | relatório 5C |
| `pipeline_dados/migracao_5b.py` | 🟢 | `pipeline_dados/` | Migração versionada das tabelas 5B | ambientes controlados | engine | status de migração |

### 2.3 Coletores CVM / B3 / documentos
| Componente | Classificação | Onde | O que faz | Quem utiliza | Entradas | Saídas |
|---|---|---|---|---|---|---|
| `pipeline_dados/coletor_cvm.py` | 🔵 | `pipeline_dados/` | ITR ações CVM → `dados_financeiros_acoes` | `services/orquestrador.py` | ano, CNPJs do catálogo | registros contábeis |
| `pipeline_dados/coletor_fiis.py` | 🔵 | `pipeline_dados/` | Informe mensal FIIs CVM → `dados_financeiros_fiis` | manual/agendador | ano | registros contábeis |
| `pipeline_dados/coletor_docs_acoes.py` | 🔵 | `pipeline_dados/` | IPE CVM → `documentos_qualitativos` (PENDENTE_ACAO) | `rotina_processar_acoes` | ano | documentos |
| `fnet_scraper.py` | 🟡 | raiz | Download de PDFs da B3 FNET | `atualizador_documentos` | data inicial | lista de docs + PDFs |
| `atualizador_documentos.py` | 🟠 | raiz | Esteira B3/FNET → dedup → IA → Drive → revisão; **também concentra `engine`/`SessionDB`** | `main.py`, `orquestrador`, `dashboard_menus`, `coletor_fiis`, bot | — | documentos no Drive, sessões |
| `pipeline_dados/deduplicacao.py` | 🟢 | `pipeline_dados/` | SHA-256 de conteúdo | atualizador_documentos | bytes | hash/original |

### 2.4 Motor de qualidade/alertas (Fase 4) e integração com notificações
| Componente | Classificação | Onde | O que faz | Quem utiliza | Entradas | Saídas |
|---|---|---|---|---|---|---|
| `pipeline_dados/regras_indicadores.py` | 🟢 | `pipeline_dados/` | Catálogo central de regras por indicador | motor_alertas | tipo_ativo/indicador/valor | classificação + limiares |
| `pipeline_dados/motor_alertas.py` | 🟢 | `pipeline_dados/` | COLETAR→VALIDAR→COMPARAR→DETECTAR→CLASSIFICAR→ALERTAR | 5C, testes | dados do ativo | `indicadores_historico`, `alertas_eventos`, notificações |
| `services/notificacoes.py` | 🟢 | `services/` | Motor individual (elegibilidade, plano, idempotência) | motor_alertas, API | evento | `notificacoes` |
| `services/dispatcher_notificacoes.py` | 🟢 | `services/` | Entrega Telegram das notificações pendentes | `main.py` (scheduler) | pendentes | envio Telegram |

### 2.5 IA / Drive / imagem (qualitativo)
| Componente | Classificação | Onde | O que faz | Quem utiliza | Entradas | Saídas |
|---|---|---|---|---|---|---|
| `modules/GoogleDriveManager.py` | 🟢 | `modules/` | Hierarquia de pastas + upload/movimentação de PDFs e logos | atualizador_documentos, logo_service | arquivo/ticker/mês | link webViewLink |
| `modules/leitor_pdf.py` | 🟢 | `modules/` | Extração de texto de PDF (PyMuPDF/pdfplumber) | services/motor_ia | url PDF | texto |
| `modules/module_fatos.py` | 🔴 | `modules/` | Radar de fatos — **dados mockados** (`LINK_DIRETO_DO_PDF_AQUI`) | legado | — | relatório Telegram |
| `modules/module_ia.py` | 🔵 | `modules/` | Cadeia Groq→OpenRouter→OpenAI (JSON p/ imagem) | legado | prompt | resposta/JSON |
| `modules/llm_manager.py` | 🔴 | `modules/` | `LLMManager` com fila de modelos (duplicado do module_ia) | legado | prompt | resposta |
| `modules/gerador_graficos.py` | 🔵 | `modules/` | Gráfico de dividendos (yfinance) | motor_imagem | ticker | PNG |
| `modules/motor_imagem.py` | 🔵 | `modules/` | Gera imagem de post (exige `template_fii.png`/fontes locais) | legado | JSON | PNG |
| `modules/module_macro.py` | 🟢 | `modules/` | Panorama macro (BCB + AwesomeAPI) | Telegram | — | texto |
| `services/motor_ia.py` | 🔴 | `services/` | IA **com resposta mockada hardcoded** ("Simulação para validação") | orquestrador (placeholder) | url_pdf/ticker | Telegram |
| `services/logo_service.py` | 🟢 | `services/` | Busca/cache de logos (Logo.dev/GitHub→Drive) | dashboard_menus | ticker | URL de imagem |

### 2.6 Serviços Telegram legados (consomem o núcleo financeiro)
| Componente | Classificação | Onde | O que faz | Quem utiliza | Entradas | Saídas |
|---|---|---|---|---|---|---|
| `services/dashboard_menus.py` | 🟡 | `services/` | Menus/painéis do bot lendo Sheets + DB | `bot/callbacks_menus.py` | ticker/tipo | mensagens/teclados |
| `services/orquestrador.py` | 🟢 | `services/` | `varredura_diaria` (B3 + CVM + placeholder IA) | `main.py` (scheduler) | — | Telegram |
| `bot/*` (handlers/callbacks/comandos) | 🟡 | `bot/` | Interface Telegram | webhook `main.py` | updates | respostas |

### 2.7 Banco/modelagem
| Componente | Classificação | Onde | O que faz | Quem utiliza | Entradas | Saídas |
|---|---|---|---|---|---|---|
| `pipeline_dados/banco_dados.py` | 🟢 (com 🔵) | `pipeline_dados/` | Modelos ORM + `garantir_coluna_plano` | todo o sistema | — | schema |

---

## 3. Reutilização

**Bases sólidas e amplamente reutilizadas (manter):**
- `pipeline_dados.qualidade_dados` — usado por CVM (`coletor_cvm.py:148`, `coletor_fiis.py:123`, `coletor_docs_acoes.py:79`), FNET/B3 (`atualizador_documentos.py:173`) e por todo o espelhamento (`espelhamento_mercado_5c.py:310,536`).
- `pipeline_dados.normalizacao` — `normalizar_cnpj`/`normalizar_data`/`normalizar_texto`/`formatar_cnpj` reutilizados por todos os coletores.
- `pipeline_dados.mapeamento_sheets` — único lugar que conhece o layout do Sheets; espelhamentos e testes dependem dele.
- `pipeline_dados.regras_indicadores` + `motor_alertas` — arquitetura genérica `tipo_ativo + ativo + indicador + valor + histórico + regra + severidade`, extensível a novos indicadores/tipos.
- `modules.utils.conectar_gspread` — ponto único de conexão Sheets (com validação clara de config).

**Duplicações de lógica (problema de reutilização):**
- **Parsing de número**: `modules.utils.formatar()` (erro → `0.0`, `utils.py:28-37`) **concorre** com `qualidade_dados.parsear_numero()` (erro → `None`). O código novo (5C) já rejeita o legado ("NUNCA usa `modules.utils.formatar()`", `espelhamento_mercado_5c.py:17-19`), mas os scrapers ainda o usam.
- **Conexão gspread**: `modules/utils.conectar_gspread` é usada diretamente por coletores (`coletor_cvm.py:45`) e indiretamente via `services/planilhas.py` — dois caminhos.
- **LLM**: três implementações concorrentes — `modules/module_ia.py`, `modules/llm_manager.py` e `atualizador_documentos.classificar_documento_com_ia` (Groq direto) — sem camada única.
- **Conexão ao banco**: `atualizador_documentos.SessionDB` (engine com pool, `atualizador_documentos.py:39-46`) vs `espelhamento_sheets._criar_sessao()` (parâmetros equivalentes, `espelhamento_sheets.py:61-76`).
- **Conversão de valores no Telegram**: `services/dashboard_menus.converter_numero` (erro → `0.0`) e `services/planilhas.safe_get` duplicam parsing de colunas do Sheets por índice numérico.

**Código morto/enganoso (não reutilizável):**
- `services/motor_ia.py:36-41` — resposta de IA simulada/hardcoded.
- `modules/module_fatos.py:63-65` — fonte de documentos com link fictício.
- `services/orquestrador.py:37-44` — etapa "IA" do agendador é placeholder comentado.

---

## 4. Refatoração (o que deve mudar, sem avançar para 7.2)

1. **Unificar parsing numérico**: eliminar `formatar()`/`converter_numero` em favor de `parsear_numero` (erro nunca vira 0.0). Impacta `modules/utils.py`, `modules/scraper_*`, `services/dashboard_menus.py`.
2. **Centralizar `SessionDB`/engine** em um módulo de banco dedicado (ex.: `services/db.py`), removendo a dependência de `atualizador_documentos` nos coletores (`coletor_fiis.py:9`, `services/dashboard_menus.py:8`, `services/orquestrador.py:4`).
3. **Centralizar o cliente LLM** em uma única camada com fallback (Groq→OpenRouter→OpenAI), absorvendo `module_ia`/`llm_manager`/`classificar_documento_com_ia`; remover mocks (`motor_ia`, `module_fatos`).
4. **Desacoplar o motor de alertas (Fase 4) do espelhamento 5C**: hoje `processar_indicadores_ativo` só roda dentro de `espelhamento_mercado_5c` (que por padrão está desligado). A detecção de mudanças/alertas deveria rodar com os dados do Sheets independentemente da flag de espelhamento.
5. **Eliminar índices mágicos de colunas** no bot (`dashboard_menus.py`, `services/planilhas.buscar_ativo_na_planilha`): usar o mapeamento declarativo de `mapeamento_sheets` em vez de índices numéricos espalhados.
6. **Substituir strings livres de `status_processamento`** por enum/validação (`PENDENTE`, `PENDENTE_ACAO`, `AGUARDANDO_REVISAO`, `SALVO_DRIVE`, `ERRO_DOWNLOAD`, `ERRO_DRIVE`, `DUPLICADO`).
7. **Padronizar tipo numérico**: `dados_financeiros_acoes`/`dados_financeiros_fiis` usam `Float` enquanto `snapshots_*` usam `Numeric` — unificar em `Numeric` para séries contábeis.

---

## 5. Problemas arquiteturais

1. **Sheets é a fonte ativa; PostgreSQL é espelho sem leitores de produção.** Os dados de mercado (`snapshots_*`, `ativos_perfil`, `ativos_inquilinos`) são gravados apenas com `ESPELHAMENTO_PG_ATIVO=true` (padrão `false`) e **nenhum leitor de produção os consome** (verificado: `api/`, `bot/`, `services/`, `app.py` não referenciam essas tabelas). A API/relatórios consomem `indicadores_historico`/`alertas_eventos` (Fase 4). Há risco de divergência entre Sheets e PostgreSQL e todo o "novo" valor fica órfão.
2. **Catálogo de identidade hardcoded em `config.py`**: `MAPA_CNPJ_B3`, `MAPA_ISCAS_MASTER`, `MAPA_SETORES_B3`, `MAPA_CONTAS_CVM` são dicts no código. Adicionar um ativo exige editar código; a resolução de CNPJ é pontual (Sheets não tem coluna de CNPJ; FIIs sem catálogo usam placeholder `PENDENTE-{ticker}`).
3. **Modelagem `Ativo`:** `cnpj` é UNIQUE **NOT NULL** (`banco_dados.py:35`), forçando placeholders para FIIs. `TipoAtivo` é `enum.Enum` fechado (ACAO/FII) — novo tipo (ETF, cripto) exige migração de enum.
4. **A cadeia de alertas (Fase 4) está desligada em produção por padrão** e acoplada ao espelhamento 5C (ver item 4.4). Logo, `indicadores_historico`, `alertas_eventos` e as notificações de alerta da Fase 6 só se alimentam quando a flag é ligada.
5. **Scrapers frágeis e mascaradores de erro**: Fundamentus/StatusInvest/yfinance com parsing ad-hoc, `print`/emojis, filas aleatórias (`random.sample`) e carimbo `d/m %H:%M` sem ano para `precisa_atualizar` (`utils.py:82-105`).
6. **Três implementações de IA** e duas com resposta mockada (ver §3). Risco de decisão baseada em "IA" que na verdade é JSON fixo.
7. **Indicadores duplicados na origem**: `BD_Acoes` coluna N (`div_liq_ebit`) é preenchida com Dív.Líq/Patrimônio (duplicação da origem, documentada em `mapeamento_sheets.py:176-177` e tratada em `espelhamento_mercado_5c.py:529-534`). `vacancia` e `numero_cotas`/`qtd_acoes` do Sheets são ambíguos (física vs financeira; estimativa).
8. **Datas**: carimbo do Sheets sem ano (`mapeamento_sheets.py:25,135-137`); `data_referencia` dos snapshots = data da coleta em SP, não data de mercado; FNET guarda a data de referência no campo `assunto` (`atualizador_documentos.py:204`), gerando dupla interpretação com `data_publicacao`.
9. **Ferramentas de "post/imagem"** (`motor_imagem`, `gerador_graficos`) dependem de arquivos locais não versionados (`template_fii.png`, fontes) — não reproduzíveis.

---

## 6. Acoplamentos

- **Sheets como hub**: escrito pelos scrapers (`app.py`), lido pelo espelhamento 5C, pelos menus do bot (`dashboard_menus`, `bot/callbacks_menus`, `bot/handlers`) e **pelos coletores contábeis** (`coletor_cvm._obter_tickers` lê `BD_Acoes`, `coletor_cvm.py:42-51`; `atualizador_documentos.obter_tickers_da_planilha` lê `BD_FIIs`, `atualizador_documentos.py:48-55`). O pipeline contábil depende de um artefato operacional (planilha) para saber *quais* CNPJs coletar.
- **`atualizador_documentos.SessionDB` é o ponto central de banco**: dependido por `main.py`, `services/orquestrador.py`, `services/dashboard_menus.py`, `pipeline_dados/coletor_fiis.py`, `bot/*`. Refatorar esse ponto (item 4.2) é de alto impacto.
- **Fase 4 → Fase 6 (ponte real)**: `motor_alertas.notificar_individual` → `services.notificacoes.processar_evento` (`motor_alertas.py:324-377`) → `notificacoes` → `dispatcher_notificacoes` → `bot.loader.enviar_mensagem`. É a única integração viva entre o pipeline financeiro e o motor individualizado.
- **`app.py` encadeia scraper → Sheets → espelhamento 5C → motor_alertas**: o motor de alertas herda a disponibilidade do Sheets e da flag.
- **Drive acoplado ao fluxo de documentos**: `atualizador_documentos` → `GoogleDriveManager` (upload/movimentação) e `dashboard_menus`/`logo_service` → `GoogleDriveManager` (logos). Falha de Drive não derruba o fluxo (tratado por status `ERRO_DRIVE`/`AGUARDANDO_REVISAO`).
- **IA acoplada via rede (Groq) no `classificar_documento_com_ia`**: sem `GROQ_API_KEY` cai em fallback (nome original, confiança 0) — tolerante, mas a classificação fica de baixa qualidade silenciosamente.

---

## 7. Arquitetura recomendada (direção, sem implementar agora)

1. **Inverter o papel de fonte**: tornar o PostgreSQL a fonte ativa dos dados de mercado (coletores escrevem direto nas tabelas), mantendo o Sheets apenas como export/legado para o Telegram V1 — ou como fonte de *seed* controlada. Elimina a dupla escrita e destrava leitores novos.
2. **Catálogo de ativos no banco** (🆕): tabela de identidade com tickers, CNPJ, tipo e setor, alimentada por uma rotina de catálogo; `MAPA_*` de `config.py` migram para seed/seed de catálogo.
3. **Camada única de leitura de mercado (fetch)** (🆕): abstrai Fundamentus/yfinance/StatusInvest sob um contrato comum, retornando valores normalizados (`parsear_numero`) e alimentando `snapshots_*` diretamente.
4. **Motor de alertas desacoplado**: `processar_indicadores_ativo` passa a ser alimentado por um gatilho independente (agendador/evento), não pela rotina de espelhamento.
5. **Camada LLM única com fallback e sem mocks** (🆕/🔴): substitui `module_ia`/`llm_manager`/`motor_ia`/`module_fatos`; classificação de documentos e resumos passam por ela.
6. **Catálogo de regras estendido a preço justo/teto** (ver §9) e `TipoAtivo` extensível (string + validação) para novos tipos de ativo.
7. **Banco centralizado** (`services/db.py`) e **status processamento com enum**, unificando convenções atuais.

---

## 8. Próximas etapas (aguardando análise; NÃO executar agora)

- Decidir, com base nesta auditoria, o escopo da **Etapa 7.2** (refatoração do núcleo financeiro), priorizando: (a) catálogo de ativos, (b) unificação de parsing, (c) desacoplamento do motor de alertas, (d) camada LLM única.
- Definir se o PostgreSQL passa a ser fonte ativa de mercado (e como o Sheets/Telegram legado é preservado).
- Nenhuma alteração de código foi feita nesta etapa; a árvore de trabalho permanece limpa no commit `d8e5255`.

---

## 9. Verificação de capacidade arquitetural para preço-teto/valuation (NÃO implementar agora)

**Objetivo**: confirmar apenas se a arquitetura atual *permite* o futuro encadeamento
`valuation → preço justo → preço-teto → margem de segurança → score`.

**Insumos já disponíveis no banco:**
- `snapshots_acoes` / `snapshots_fiis`: preço, P/L, P/VP, VPA, LPA, DY, margens, ROE/ROA/ROIC, EV/EBIT, valor de mercado — base de múltiplos para `preço justo`.
- `dados_financeiros_acoes` (CVM ITR/DFP): lucro líquido, PL, receita, EBITDA, caixa, dívidas — base de valuation (DCF/múltiplos).
- `dados_financeiros_fiis` (CVM informe): PL, ativo total, rendimento por cota — base de valuation de FII.
- `regras_indicadores` + `motor_alertas`: infraestrutura genérica de faixa/classificação por indicador — padrão reutilizável para "faixas de preço justo" e "margem de segurança".
- `IndicadorHistorico`/`AlertaEvento`: série temporal e eventos — base de comparação/score.

**Avaliação**: a arquitetura atual **permite** a adição futura do encadeamento sem ruptura. Novos indicadores derivados (preço justo, preço-teto, margem de segurança, score) podem entrar como indicadores monitorados em `regras_indicadores` e persistidos em tabelas/séries no padrão existente (`tipo_ativo + ativo + indicador + valor + regra + data_referencia`). A infraestrutura de qualidade/alertas já cobre a detecção de violação de faixas.

**Limitações a considerar antes da Etapa 7.2 (não bloqueiam, mas condicionam a qualidade):**
- Preço vem do Sheets (espelho desligado por padrão): o `preco` confiável para valuation depende de ativar/persistir `snapshots_*`.
- Identidade de ativos parcial (`cnpj` placeholder para FIIs; catálogo manual) — um `score` por ativo herdará essa imprecisão de identidade.
- `TipoAtivo` fechado (ACAO/FII) — novos tipos precisam de evolução do enum.
- Motores de IA atuais são mockados/duplicados — análises "qualitativas" usadas num score futuro precisam da camada LLM única.

**Conclusão**: viável (com os insumos já modelados), desde que (1) os `snapshots_*` passem a ser persistidos e lidos de produção e (2) a identidade/catálogo seja resolvida. Nada foi implementado nesta etapa.
