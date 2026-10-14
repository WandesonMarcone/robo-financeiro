# 🤖 Robô Financeiro & Data Lake Institucional

 

Bem-vindo ao repositório do **Robô Financeiro**, um ecossistema de Engenharia de Dados focado no mercado financeiro brasileiro (B3).

 

Este sistema abandona o modelo amador de planilhas manuais e implementa uma arquitetura automatizada de **coleta, auditoria e armazenamento** de FIIs e Ações: raspagem de documentos oficiais (FNET/CVM/B3), classificação com Inteligência Artificial, cofre documental no Google Drive, dashboard em Google Sheets e operação em tempo real via **bot do Telegram**.

 

---

 

## 🎯 Objetivos Alcançados (Arquitetura Atual)

 

- **Data Lake Dinâmico:** Utilização do Google Sheets como banco de dados visual (Dashboard), recebendo cargas contínuas e automatizadas via APIs (`batch_update` em abas `BD_FIIs`, `BD_Acoes`, `BD_Logs`).

- **Scraping Resiliente:** Sistema de fallback duplo. Se uma fonte falha (ex.: Fundamentus fora do ar), o robô busca os dados no **Yahoo Finance** (yfinance) ou **StatusInvest** — inclusive com retry automático em cada requisição.

- **Acervo Documental na Nuvem:** Varredura autônoma no sistema **FNET da B3** e na **CVM** para capturar Fatos Relevantes, Relatórios Gerenciais, formulários e informes, organizando-os automaticamente em pastas dinâmicas no Google Drive (`Documentos → Tipo → Ticker → Ano → Mês`).

- **Inteligência Artificial Documental:** Todo PDF baixado passa por **extração de texto** (PyPDF2/PyMuPDF/pdfplumber) e **classificação pela API Groq (LLM)**, que devolve um JSON com tipo de documento e nível de **confiança** — documentos com confiança ≥ 80 são salvos automaticamente; os demais seguem para **revisão humana**.

- **Bot de Telegram Operacional:** Interface mobile em tempo real para controle do fluxo, emissão de alertas de oportunidades (quando um ativo entra na margem de desconto) e links diretos para leitura de PDFs oficiais.

- **Banco de Dados Relacional:** Integração com **SQLite (padrão) ou PostgreSQL (produção)** via SQLAlchemy para evitar processamentos duplicados, registrando o histórico de relatórios baixados com máquina de estados (`SALVO_DRIVE`, `AGUARDANDO_REVISAO`, `ERRO_DOWNLOAD`, `ERRO_DRIVE`, `REJEITADO_MANUAL`).

 

---

 

## 🏗️ Arquitetura Geral

 

```mermaid

graph TD

    subgraph "Operação"

        BOT["Bot Telegram bot/"]

        WEB["Servidor Flask main.py"]

        SCH["Agendador APScheduler seg-sex 08:00"]

        ACT["Cron GitHub Actions 5x/dia"]

    end

    subgraph "Pipeline"

        ORC["Orquestrador varredura_diaria"]

        GAR["Garimpo de oportunidades app.py"]

        COL["Coletores CVM/FNET/B3"]

    end

    subgraph "Fontes Externas"

        CVM["CVM"]

        FNET["FNET B3"]

        FUND["Fundamentus"]

        SI["StatusInvest"]

        YF["Yahoo Finance"]

    end

    subgraph "Processamento e IA"

        PDF["Extração de texto leitor_pdf"]

        IA["Classificação Groq confiança"]

    end

    subgraph "Armazenamento"

        DB[("SQLite/PostgreSQL")]

        SHEET[("Google Sheets")]

        DRIVE[("Google Drive")]

    end

    BOT --> ORC

    WEB --> ORC

    SCH --> ORC

    ACT --> GAR

    ORC --> COL

    GAR --> FUND

    GAR --> SI

    GAR --> YF

    COL --> CVM

    COL --> FNET

    COL --> PDF

    PDF --> IA

    ORC --> DB

    GAR --> SHEET

    IA --> DRIVE

    IA --> DB

    DRIVE --> SHEET

```

 

---

 

## 📂 Mapeamento de Arquivos e Módulos

 

### 📱 Interface e Servidor

- `main.py`: O **"cérebro" da comunicação** e o verdadeiro ponto de entrada web. Roda 24/7 no Render (via Webhook/Gunicorn), sobe o Flask, registra o webhook do Telegram, cria as tabelas do banco e agenda a varredura diária com o APScheduler.

- `bot/loader.py`: Cria a **instância única** do bot (telebot).

- `bot/comandos.py`, `bot/handlers.py`, `bot/callbacks_menus.py`, `bot/callbacks_revisao.py`: Menus, comandos, navegação por setor/tipo e o fluxo de **revisão humana** de documentos.

- `app.py`: **Garimpo de oportunidades** — não é o servidor web. Roda no cron do GitHub Actions, dispara os scrapers de FIIs/Ações, grava em lote nas planilhas e envia alertas consolidados.

 

### 🔌 Ordem de registro dos handlers do Telegram

O `main.py` importa os módulos que registram handlers nesta ordem:

1. `bot.comandos` — comandos (`/...`).
2. `bot.handlers` — callbacks específicos de tipo/setor.
3. `bot.callbacks_revisao` — fluxo de revisão humana.
4. `bot.callbacks_menus` — menus e o **callback catch-all**.

O `pyTelegramBotAPI` avalia os handlers na ordem em que foram registrados e **para no primeiro que corresponder**. Por isso `bot.callbacks_menus`, que registra `@bot.callback_query_handler(func=lambda call: True)` (catch-all), deve ser importado **por último**: se fosse importado antes, capturaria todos os callbacks e impediria os handlers específicos de `bot.handlers` e `bot.callbacks_revisao` de executar.

 

### 🕵️ Motores de Busca e Auditoria (Scrapers)

- `modules/scraper_fiis.py`: Motor focado em Fundos Imobiliários. Audita P/VP, Dividend Yield, **vacância física real**, quantidade de imóveis e inquilinos via StatusInvest (JSON + HTML), com preço do Fundamentus e fallback no Yahoo Finance.

- `modules/scraper_acoes.py`: Caçador de barganhas focado em Ações. Calcula P/L, P/VP, ROE, Margens e Dividend Yield (Fundamentus + fallback Yahoo Finance) e organiza o portfólio por setores.

- `fnet_scraper.py`: Robô especializado na plataforma da **B3 (FNET)**, encarregado de caçar e baixar PDFs institucionais.

- `pipeline_dados/coletor_cvm.py`: Leitura institucional dos documentos da **CVM** (relatórios e formulários por ano/ativo).

- `pipeline_dados/coletor_docs_acoes.py` e `pipeline_dados/coletor_fiis.py`: Coletores específicos de ações e informes de FIIs.

 

### 📁 Gerenciamento de Nuvem, IA e Banco de Dados

- `atualizador_documentos.py`: A ponte entre a B3, o Banco de Dados, a IA e o Google Drive. Verifica se o documento já está registrado, baixa PDFs inéditos, **extrai o texto, classifica com Groq e salva** no Drive quando a confiança é alta.

- `modules/GoogleDriveManager.py`: Módulo customizado de API do Google. Verifica a existência de diretórios, cria pastas hierárquicas dinâmicas (`Documentos → Tipo → Ticker → Ano → Mês`, além da pasta de revisão `⚠️ REVISÃO`) e faz o upload dos PDFs liberando link público.

- `modules/leitor_pdf.py`: Extração de texto de PDFs (PyMuPDF + pdfplumber).

- `modules/module_ia.py`: Consultas interativas de fatos relevantes dos ativos via LLM (Groq/OpenAI).

- `pipeline_dados/banco_dados.py`: Modelagem ORM (SQLAlchemy) com as classes e constraints do sistema (`Ativos`, `DadosFinanceirosAcoes`, `DadosFinanceirosFiis`, `DocumentosQualitativos`).

- `services/orquestrador.py`: **Ponto de entrada do pipeline** — a `varredura_diaria` que roda a rotina B3/FNET, a coleta CVM e dispara os alertas.

- `services/planilhas.py` e `services/dashboard_menus.py`: Leitura de Sheets com cache (TTL 5 min) e geração dos painéis de oportunidades/favoritos exibidos no bot.

- `services/logo_service.py`: Fornece os links de logos dos ativos nos menus.

 

### 🛠️ Configurações e Variáveis de Ambiente

- `config.py`: Centralizador de variáveis de ambiente, catálogos (mapas de tickers, setores, CNPJs e contas CVM), filtros de garimpo e tipos de documento.

- `requirements.txt`: Relação estruturada das dependências do Python para build e deployment.

- `.github/workflows/main.yml`: Cron de execução do garimpo no GitHub Actions (segunda a sexta, 13h–21h UTC).

 

---

## Controle de Usuarios e Permissoes (Fase 2)

O acesso ao bot e restrito a usuarios previamente autorizados. Nao ha liberacao
automatica para quem inicia uma conversa: atualizacoes de chats fora da
allowlist sao descartadas antes de qualquer handler executar.

### Papeis

| Papel | Telegram ID (padrao) | Descricao |
|---|---|---|
| `admin` | 8867098987 | Acesso administrativo total e tambem todas as funcionalidades do usuario comum. |
| `user` | 5336458734 | Somente funcionalidades financeiras e de consulta autorizadas. |

### Permissoes

Comandos liberados para `user` (consulta/financeiro): `/menu`, `/start`,
`/relatorios`, `/docs`.

Comandos exclusivos do `admin` (operacao/configuracao/manutencao/destrutivos):
`/status`, `/adicionar`, `/forcar_varredura`, `/forcar_docs_acoes`,
`/processar_acoes_ia`, `/forcar_cvm`, `/forcar_fiis`, `/alimentar_ia`,
`/mapear_nomes`, `/resetar_docs`, `/revisao`.

Callbacks liberados para `user`: navegacao e consulta (`menu_*`, `macro_*`,
`subsetor_*`, `sub_ac_*`, `painel_*`, `dados_*`, `ano_*`, `mes_*`, `docs_*`,
`dnav_*`, `dl_*`, `tipo_fii_*`, `setor_*`, `favoritos_*`, `oportunidades_*`,
`ia_*`, `ajuda_*`, `ajuda_cvm_*`, `voltar_menu`).

Callbacks exclusivos do `admin`: `rev_*` (Central de Revisao), `ver_raiox_docs`,
`confirmar_reset`, `cancelar_reset`, `iniciar_revisao_pendencias`.

Operacoes nao reconhecidas (comandos/callbacks desconhecidos) sao tratadas como
administrativas por padrao (falha segura): nao recebem autorizacao automatica.

### Como a autenticacao funciona

1. `bot/loader.py` — `BotAutorizado.process_new_updates` e o ponto unico de
   despacho.
2. O chat e validado contra `config.CHATS_AUTORIZADOS`.
3. `bot/permissoes.py` identifica o autor pelo Telegram ID (`from_user.id`, com
   fallback para o `chat.id`), resolve o papel em `config.USUARIOS_AUTORIZADOS`,
   classifica a operacao (comando ou callback) e decide se ela pode ser
   executada.
4. Operacoes negadas sao respondidas com uma mensagem generica (sem detalhes
   internos) e registradas em log. Uma tentativa negada nunca interrompe o bot.

O papel e sempre derivado do Telegram ID fornecido pela plataforma; ele nao pode
ser alterado por texto de comando, parametros nem por dados de callback.

### Como adicionar outro usuario autorizado

Adicione o Telegram ID em `TELEGRAM_USUARIOS_LIMITADOS` (lista separada por
virgulas) e reinicie o servico. Para definir o administrador, use
`TELEGRAM_ADMIN_ID` (um unico ID). Chats que so precisam de leitura podem ser
incluidos em `TELEGRAM_CHATS_AUTORIZADOS`, mas continuam sujeitos ao bloqueio de
operacoes administrativas.

Variaveis de ambiente relacionadas (nunca versione IDs, tokens ou credenciais
reais):

- `TELEGRAM_ADMIN_ID` (padrao `8867098987`)
- `TELEGRAM_USUARIOS_LIMITADOS` (padrao `5336458734`)
- `TELEGRAM_CHATS_AUTORIZADOS` (opcional; complementa a allowlist)

### Funcionalidades exclusivas do administrador

Coleta e processamento (CVM/FNET/FIIs/IA), manutencao e diagnostico
(`/status`, `/mapear_nomes`, `ver_raiox_docs`), alteracao de dados
(`/adicionar`), reset de documentos (`/resetar_docs`) e a Central de Revisao
Humana (`/revisao` e callbacks `rev_*`).

---

## 🚀 Progresso do Sistema

 

### ✅ Implementado e em produção

 

| Módulo | Status |

|---|---|

| Bot do Telegram (webhook, comandos, menus, revisão) | ✅ Ativo |

| Servidor Flask + webhook no Render | ✅ Ativo |

| Agendador diário (APScheduler, seg-sex 08:00 America/Sao_Paulo) | ✅ Ativo |

| Varredura diária orquestrada | ✅ Ativo |

| **IA Documental (Groq)** — extração de PDF + classificação JSON + confiança ≥ 80 | ✅ Ativo em `atualizador_documentos.py` |

| Coleta **CVM** (ações e relatórios) | ✅ Ativo |

| Coleta **FNET/B3** (informes e relatórios) | ✅ Ativo |

| Upload automático ao Google Drive (pastas hierárquicas + revisão) | ✅ Ativo |

| Planilhas Google Sheets (BD_FIIs, BD_Acoes, BD_Logs) | ✅ Ativo |

| Garimpo de oportunidades (Ações + FIIs) via GitHub Actions | ✅ Ativo |

| Banco SQLite/PostgreSQL com máquina de estados documental | ✅ Ativo |

| Revisão humana de documentos de baixa confiança | ✅ Ativo |

| IA de fatos (`/ia`) e dashboard de oportunidades | ✅ Ativo |

| Allowlist de chats autorizados (`CHATS_AUTORIZADOS`) | ✅ Ativo em `bot/telegram_utils.py` + `bot/loader.py` |

| Papéis de usuário (`admin`/`user`) e IDs autorizados | ✅ Ativo em `config.py` + `bot/permissoes.py` |

| Controle centralizado de permissões em comandos e callbacks | ✅ Ativo em `bot/loader.py` + `bot/permissoes.py` |

| Estabilização de handlers/callbacks (falhas visíveis + callback desconhecido) | ✅ Ativo em `bot/telegram_utils.py` |

| Testes automatizados do bot (`tests/test_bot_boot.py`, `tests/test_telegram_stability.py`, `tests/test_permissoes.py`) | ✅ 41 testes passando |

| Boot protegido sem `TELEGRAM_BOT_TOKEN` (falha clara, sem segredo) | ✅ Ativo em `bot/loader.py` |

 

### 🧪 Em desenvolvimento / código existente ainda não integrado

 

- `services/motor_ia.py` — leitura de relatórios com IA: a chamada está **comentada** no orquestrador, pronta para ser ativada.

- `modules/module_macro.py` — dados macroeconômicos: não é importado por nenhum fluxo.

- `modules/llm_manager.py` — gerenciador de múltiplos LLMs: não é importado.

- `modules/motor_imagem.py` e `modules/gerador_graficos.py` — imagens e gráficos: exigem `Pillow`/`matplotlib`, que ainda não estão no `requirements.txt`.

 

---

 

## 🔜 Próximos Passos (Roadmap)

 

### P0 — Correções críticas (segurança e funcionamento)

1. **Rotacionar o token do bot** do Telegram (credencial exposta no histórico do git) e purgar o histórico com `git filter-repo`/BFG.

2. **Proteger o `/resetar_docs`** com confirmação/autorização.

3. **Corrigir o coletor de FIIs** — a busca do ativo pelo CNPJ nunca encontra correspondência, então informes de FIIs não são salvos.

4. **Corrigir o filtro de ROE** no garimpo de ações (`ROE >= 8.0` é sempre falso após a conversão decimal; deveria ser `0.08`).

5. **Sanitizar entrada** do `/adicionar` (risco de formula injection no Google Sheets).

 

### P1 — Robustez e manutenibilidade

1. **Ampliar a suíte de testes** — hoje há cobertura apenas do bot (`tests/test_telegram_stability.py`); faltam testes para coletores, orquestrador e banco, além de executá-los no CI do GitHub Actions.

2. **Proteger o boot** — não quebrar o import de `atualizador_documentos.py` quando `GROQ_API_KEY`/`DATABASE_URL` não existirem.

3. **Popular o `hash_sha256`** dos documentos para deduplicação real (o campo existe no banco, mas nunca é preenchido).

4. **Ativar o motor de IA** do orquestrador (ou removê-lo como código morto).

5. Adicionar `Pillow` e `matplotlib` ao `requirements.txt` caso imagem/gráficos sejam ativados.

 

### P2 — Qualidade de dados e observabilidade

1. Usar a **data de publicação real** dos documentos em vez da data de captura como referência.

2. Tornar os documentos `ERRO_DOWNLOAD`/`ERRO_DRIVE` re-processáveis.

3. Padronizar logs (substituir `print` por `logging`) e expor métricas de execução.

 

### P3 — Escala e evolução

1. **Fila de processamento** (ex.: Redis + Celery) para lotes grandes sem bloquear a varredura.

2. **Paralelizar downloads** com limite de concorrência.

3. Extrair catálogos fixos de `config.py` para tabelas/arquivos externos.

4. Deploy reprodutível (Dockerfile + `render.yaml`/Procfile).

 

---

 

## 🛠️ Tecnologias Utilizadas

 

- **Linguagem:** Python 3.x

- **Servidor/Agendamento:** Flask, Gunicorn, APScheduler, pytz

- **Bot:** pyTelegramBotAPI (webhook)

- **Dados/Scraping:** pandas, requests, yfinance, BeautifulSoup4, lxml, html5lib

- **Google:** gspread (Sheets), google-api-python-client (Drive), google-auth-oauthlib

- **IA:** Groq (classificação documental), OpenAI SDK (provedor alternativo)

- **PDFs:** PyPDF2, PyMuPDF, pdfplumber

- **Banco:** SQLAlchemy, SQLite (local), psycopg2/PostgreSQL (produção)

- **Infra:** Render (servidor web), GitHub Actions (cron)

 

---

 

## 🔑 Configuração Rápida

 

```bash

# Clonar e instalar

git clone https://github.com/WandesonMarcone/robo-financeiro.git

cd robo-financeiro

python -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt

 

# Variáveis de ambiente essenciais

export TELEGRAM_BOT_TOKEN="seu_token_do_bot"

export TELEGRAM_CHATS_AUTORIZADOS="8867098987"

export TELEGRAM_ADMIN_ID="8867098987"

export TELEGRAM_USUARIOS_LIMITADOS="5336458734"

export GROQ_API_KEY="sua_chave_groq"

export CLIENT_ID="..."

export CLIENT_SECRET="..."

export REFRESH_TOKEN="..."

export DRIVE_ROOT_FOLDER_ID="..."

 

# Servidor (webhook + agendador + banco)

python main.py

 

# Garimpo manual

python app.py

# Testes do bot (nao acessam servicos reais)

python tests/test_telegram_stability.py

python tests/test_bot_boot.py

python tests/test_permissoes.py

```

 

> 💡 Sem `DATABASE_URL` o sistema usa SQLite local (`pipeline_dados/banco_institucional.db`). Demais configurações e catálogos ficam em `config.py`.

 

> ⚠️ O bot **não inicia** se `TELEGRAM_BOT_TOKEN` estiver ausente ou vazio: `bot/loader.py` falha com uma mensagem clara e **não** fornece token padrão. Os usuários definidos em `USUARIOS_AUTORIZADOS` (via `TELEGRAM_ADMIN_ID` e `TELEGRAM_USUARIOS_LIMITADOS`) são sempre autorizados; `TELEGRAM_CHATS_AUTORIZADOS` é opcional e complementa a allowlist de chats.

 

---

 

## ⚠️ Segurança

 

- **Credencial exposta no histórico** — versões antigas de `config.py` continham o token do bot em texto puro. O código atual lê de variável de ambiente, mas o valor persiste no git e **deve ser rotacionado e purgado**.

- **Sem SQL Injection** — SQLAlchemy (ORM parametrizado) protege as consultas.

- **Sem credenciais em texto puro** na árvore atual (`.gitignore` cobre `credenciais.json`, `.env`, chaves locais e o banco SQLite).

- **Controle de acesso por papel** — o acesso é restrito a `USUARIOS_AUTORIZADOS`. Cada update é classificado por `bot/permissoes.py` e operações administrativas (comandos e callbacks) são bloqueadas para o papel `user` antes de qualquer efeito; tentativas negadas são registradas em log sem expor credenciais (ver `bot/loader.py`).

- **Allowlist de chats** — apenas os `chat_id` listados em `CHATS_AUTORIZADOS` são processados; demais atualizações são descartadas e registradas em log (ver `bot/loader.py`).

- **Melhorias necessárias** — confirmação no `/resetar_docs` e sanitização de entradas que vão para o Google Sheets.

 

---

 

*Construído com Python, APIs Financeiras e LLMs para automatizar e blindar a tomada de decisão no mercado financeiro.*
