# Robô Financeiro & Data Lake Institucional

Ecossistema de engenharia de dados focado no mercado financeiro brasileiro (B3).
O projeto automatiza a **coleta, auditoria e armazenamento** de dados de FIIs e
Ações: raspagem de documentos oficiais (FNET/B3, CVM), classificação com
Inteligência Artificial, cofre documental no Google Drive, painel em Google
Sheets e operação via **bot do Telegram**.

Para uma explicação simplificada voltada ao proprietário, veja `admin.md`.

---

## 1. Visão geral

O sistema tem dois fluxos independentes:

- **Servidor 24/7** (`main.py`): sobe o Flask, recebe os updates do Telegram por
  webhook e agenda a varredura diária. Roda no Render.
- **Coletor agendado** (`app.py`): dispara o garimpo de oportunidades, grava nas
  planilhas e envia alertas. Roda no cron do GitHub Actions.

Principais capacidades:

- **Scraping resiliente** com fallback (Fundamentus, StatusInvest, Yahoo
  Finance) e retry por requisição.
- **Acervo documental na nuvem**: varredura em FNET/B3 e CVM, com organização
  automática de PDFs em pastas do Google Drive (`Documentos`, `Tipo`, `Ticker`,
  `Ano`, `Mês`, além da pasta de revisão).
- **IA documental**: extração de texto do PDF e classificação pela API Groq com
  nível de confiança; documentos com confiança alta são salvos automaticamente e
  os demais seguem para revisão humana.
- **Bot do Telegram**: menus, consultas financeiras, alertas de oportunidades,
  controle de acesso por papel, autocadastro com aprovação e favoritos por
  usuário.
- **Banco relacional** (PostgreSQL/Neon em produção) via SQLAlchemy, com máquina
  de estados dos documentos.

---

## 2. Arquitetura e fluxos de execução

```mermaid
graph TD
    subgraph Operacao
        BOT["Bot Telegram (bot/)"]
        WEB["Servidor Flask (main.py)"]
        SCH["APScheduler seg-sex 08:00"]
        ACT["Cron GitHub Actions 5x/dia"]
    end
    subgraph Pipeline
        ORC["Orquestrador varredura_diaria"]
        GAR["Garimpo de oportunidades (app.py)"]
        COL["Coletores CVM / FNET / B3"]
    end
    subgraph Fontes
        CVM["CVM"]
        FNET["FNET B3"]
        FUND["Fundamentus"]
        SI["StatusInvest"]
        YF["Yahoo Finance"]
    end
    subgraph Processamento
        PDF["Extracao de texto (leitor_pdf)"]
        IA["Classificacao Groq"]
    end
    subgraph Armazenamento
        DB[("PostgreSQL / Neon")]
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
    IA --> DRIVE
    IA --> DB
    DRIVE --> SHEET
```

### `main.py` — servidor (Render)

- Sobe o Flask e expõe a rota de webhook do Telegram e uma rota raiz de status.
- No boot, configura o webhook e inicia o APScheduler com a varredura diária de
  segunda a sexta às 08:00 (America/Sao_Paulo).
- **Criação de tabelas**: NÃO ocorre por padrão. O `create_all` só roda com
  `CRIAR_TABELAS=1` (uso em desenvolvimento limpo); o banco de produção não é
  alterado no boot.
- Ao apenas **importar** `main`, nenhum job é agendado e nenhum webhook é
  registrado. O boot completo na importação só ocorre com
  `ROBO_INICIAR_NO_IMPORT=1` (compatibilidade com servidores WSGI).
- Execução local: `python main.py`.

### `app.py` — coletor de oportunidades (GitHub Actions)

- Não é o servidor web.
- Executa o garimpo de FIIs e Ações, grava em lote nas abas do Google Sheets e
  envia os alertas consolidados no Telegram.
- Execução: `python app.py`.
- Agendamento: `.github/workflows/main.yml`, cron `0 13,15,17,19,21 * * 1-5`
  (segunda a sexta, 5 vezes ao dia, em UTC).

### Ordem de registro dos handlers do Telegram

O `main.py` importa os módulos nesta ordem:

1. `bot.cadastro`
2. `bot.central_controles`
3. `bot.favoritos`
4. `bot.comandos`
5. `bot.handlers`
6. `bot.callbacks_revisao`
7. `bot.callbacks_menus`

O `pyTelegramBotAPI` avalia os handlers na ordem de registro e para no primeiro
que corresponder. Por isso `bot.callbacks_menus`, que registra um
`callback_query_handler(func=lambda call: True)` (catch-all), é importado por
último. Os módulos com callbacks específicos (`cad_*`, `adm_*`, `favoritos_*`,
`favadd_*`, `favnew_*`, `favrem_*`, `rev_*`) são registrados antes, para não serem
capturados pelo genérico (sem isso a Central de Controles responderia "botão
inválido"; há teste cobrindo a ordem em `main.py`).

---

## 3. Estrutura das pastas

- `bot/` — bot do Telegram (comandos, menus, cadastro, favoritos, permissões,
  loader e utilitários).
- `modules/` — scrapers, leitura de PDF, Google Drive, utilitários e clientes de
  IA.
- `services/` — orquestrador da rotina diária, planilhas, menus/painéis, logos,
  catálogo de empresas e motor de IA (inativo).
- `pipeline_dados/` — conexão, modelos ORM, repositórios e coletores CVM/FIIs.
- `migrations/` — migrações SQL manuais e versionadas para o banco de produção.
- `tests/` — testes automatizados (sem rede e sem banco real).
- `.github/workflows/main.yml` — cron do GitHub Actions que executa `app.py`.

Arquivos de topo: `main.py`, `app.py`, `config.py`, `atualizador_documentos.py`
(ponte entre B3, banco, IA e Drive), `fnet_scraper.py`, `requirements.txt`.

---

## 4. Funcionalidades e integrações

### Funcionalidades ativas

| Área | Descrição |
|---|---|
| Servidor Flask + webhook | `main.py`, no Render |
| Agendador diário | APScheduler, seg-sex 08:00 America/Sao_Paulo |
| Varredura orquestrada | `services/orquestrador.py::varredura_diaria` (B3/FNET + CVM) |
| IA documental | Extração de PDF + classificação Groq com confiança, em `atualizador_documentos.py` |
| Coleta CVM | `pipeline_dados/coletor_cvm.py` |
| Coleta FNET/B3 | `fnet_scraper.py` + `atualizador_documentos.py` |
| Google Drive | `modules/GoogleDriveManager.py` (pastas hierárquicas + revisão) |
| Google Sheets | `services/planilhas.py` (cache de 5 min) |
| Garimpo de oportunidades | `app.py` via GitHub Actions |
| Bot do Telegram | Comandos, menus, `/ia`, raio-x, favoritos e revisão |
| Controle de acesso | Papéis `admin`/`user` e allowlist de chats |
| Cadastro e aprovação | Autocadastro por `/start` com aprovação administrativa |
| Central de Controles | `/controles` (admin): gestão de acessos pelo Telegram (`bot/central_controles.py`) |
| Revisão humana | `bot/callbacks_revisao.py` (`/revisao` e callbacks `rev_*`) |
| Logos dos ativos | Catálogo GitHub (pasta plana `icones/`), cache de `file_id` do Telegram e fallback textual |
| Painel administrativo | Visão própria do admin: Central de Controles, indicadores, carteira e documentos |
| Testes automatizados | 359 testes (execução local; 7 exigem PostgreSQL local) |

### Integrações externas

- **Telegram** (bot e alertas).
- **Neon / PostgreSQL** (banco de produção) e SQLite apenas se definido
  explicitamente.
- **Google Sheets** (painel de dados) e **Google Drive** (PDFs e logos).
- **Groq** (classificação e consultas de IA); **OpenAI/OpenRouter** como
  alternativas opcionais.
- **Fontes de mercado**: FNET/B3, CVM, Fundamentus, StatusInvest, Yahoo Finance.
- **Render** (servidor) e **GitHub Actions** (cron). São ambientes distintos:
  o Render hospeda `main.py`; o GitHub Actions só executa `app.py`.

### Detalhes por módulo

- `modules/scraper_fiis.py`: auditores de FIIs (P/VP, Dividend Yield, vacância
  física, imóveis e inquilinos) com fallback entre fontes.
- `modules/scraper_acoes.py`: indicadores de Ações (P/L, P/VP, ROE, margens, DY)
  organizados por setor.
- `atualizador_documentos.py`: verifica duplicidade, baixa PDFs inéditos, extrai
  texto, classifica com Groq e salva no Drive quando a confiança é alta.
- `modules/leitor_pdf.py`: extração de texto de PDFs (PyMuPDF + pdfplumber).
- `modules/module_ia.py`: consultas de IA do bot (`/ia`).
- `services/dashboard_menus.py`: painéis de oportunidades/favoritos do bot.
- `services/logo_service.py`: logos dos ativos. Fonte principal é o catálogo
  público `WandesonMarcone/icones-bolsabr` (pasta plana `icones/`, mais de 3 mil
  PNGs), consultado por URL `raw.githubusercontent.com` para **não consumir a
  API de listagem do GitHub**. PETR3 e PETR4 compartilham a identidade visual da
  Petrobras (`PETR4.png`), sem unir os dados financeiros. Logo.dev (`LOGO_DEV_TOKEN`)
  é apenas alternativa quando o catálogo não tem a imagem. O `file_id` devolvido
  pelo Telegram é persistido em `cache_logos_telegram` (ver
  `pipeline_dados/repositorio_logos.py`), reutilizável após reinícios do bot,
  associado à empresa para que tickers irmãos compartilhem a mesma logo. Falhas
  são registradas com expiração (cache negativo). Sem logo, o painel/mensagem
  degrada para texto sem interromper o bot.
- `pipeline_dados/modelos_catalogo.py`: catálogo central (`empresas`,
  `setores`, `subsetores`, `atividades_economicas`, `empresa_ativos`,
  `empresa_segmentos`, `empresa_atividades`, `sugestoes_catalogo`,
  `cache_logos_telegram`). Uma empresa pode ter vários tickers, mas os dados
  financeiros continuam por ticker em `ativos`/`dados_financeiros_*`.
- `pipeline_dados/repositorio_catalogo.py`: upserts, classificação setorial com
  histórico (vigência), fila de revisão e resumo da empresa.
- `pipeline_dados/repositorio_logos.py`: cache persistente do `file_id` do
  Telegram com TTL para falhas e vínculo opcional à empresa.
- `pipeline_dados/coletor_catalogo_cvm.py`: importa o FCA oficial da CVM
  (`dados.cvm.gov.br`), cria empresas e associa tickers oficiais.
- `services/catalogo_empresas.py`: aplica `config.MAPA_SETORES_B3` e monta o
  resumo consolidado da empresa.
- `services/catalogo_ia.py`: detecção assistida por IA com validação
  (confiança, fonte oficial, evidência); casos ambíguos vão para
  `sugestoes_catalogo` em vez de criar registros.
- `pipeline_dados/banco_dados.py`: modelos ORM (`Ativo`, `DadosFinanceirosAcoes`,
  `DadosFinanceirosFiis`, `DocumentosQualitativos`).
- `pipeline_dados/coletor_cvm.py`, `coletor_fiis.py`, `coletor_docs_acoes.py`:
  coletores de CVM, informes de FIIs e relatórios de ações.

---

## 5. Configuração das variáveis de ambiente

Nunca versionar valores reais de tokens, senhas ou URLs de conexão.

### Render (servidor `main.py`)

Obrigatórias:

- `TELEGRAM_BOT_TOKEN` — token do bot. Sem ele, o bot não inicializa.
- `DATABASE_URL` — conexão com o banco. A URL é normalizada
  (`postgres://` para `postgresql://`). Sem ela, a criação do engine falha com erro
  controlado (não há fallback silencioso para SQLite).

Permissões e acesso:

- `TELEGRAM_ADMIN_ID` (padrão no código: `8867098987`).
- `TELEGRAM_USUARIOS_LIMITADOS` (padrão no código: `5336458734`; lista separada
  por vírgulas).
- `TELEGRAM_CHATS_AUTORIZADOS` (opcional; complementa a allowlist de chats).

Operação e funcionalidades opcionais:

- `WEBHOOK_BASE_URL` (opcional; padrão no código).
- `PORT` (injetada pelo Render; padrão interno `10000`).
- `GROQ_API_KEY` (IA; sem ela, apenas as operações de IA falham de forma
  controlada).
- `LOGO_DEV_TOKEN` (alternativa opcional; GitHub é a fonte principal),
  `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_BASE_URL`.
- `LOGO_GITHUB_REPO`, `LOGO_GITHUB_BRANCH`, `LOGO_GITHUB_DIR` (opcionais; padrão
  `WandesonMarcone/icones-bolsabr`, `main`, `icones`).
- `CLIENT_ID`, `CLIENT_SECRET`, `REFRESH_TOKEN`, `DRIVE_ROOT_FOLDER_ID`,
  `GOOGLE_CREDS` (Google Drive/Sheets).

Flags de manutenção:

- `CRIAR_TABELAS=1` — habilita `create_all` (apenas em desenvolvimento limpo).
- `ROBO_INICIAR_NO_IMPORT=1` — executa o boot completo ao importar `main`.

### GitHub Actions (coletor `app.py`)

Definidas como secrets em `.github/workflows/main.yml`:

- `GOOGLE_CREDENTIALS` (gera `credenciais.json` em tempo de execução),
  `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`, `LOGO_DEV_TOKEN`, `CLIENT_ID`,
  `CLIENT_SECRET`, `REFRESH_TOKEN`, `DRIVE_ROOT_FOLDER_ID`.

Mapeada mas **sem uso confirmado no código**: `GEMINI_API_KEY`.

---

## 6. Execução local e testes

```bash
# Clonar e preparar ambiente
git clone <url-do-repositorio>
cd robo-financeiro
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Variáveis de ambiente essenciais (exemplo; use valores reais locais)
export TELEGRAM_BOT_TOKEN="seu_token_do_bot"
export DATABASE_URL="sua_url_de_conexao"
export GROQ_API_KEY="sua_chave_groq"

# Servidor (webhook + agendador + banco)
python main.py

# Garimpo manual de oportunidades
python app.py

# Testes automatizados (não acessam serviços reais)
python -m unittest discover -s tests
```

Observações:

- A suíte atual tem **359 testes** distribuídos em `tests/`:
  `test_acesso_ativos.py` (9), `test_bot_boot.py` (9), `test_cadastro.py` (47),
  `test_callbacks_revisao.py` (4), `test_catalogo_correcoes.py` (14),
  `test_catalogo_empresas.py` (18), `test_catalogo_postgres.py` (7),
  `test_central_controles.py` (56), `test_dashboard_logos.py` (10),
  `test_documentos_notificacoes.py` (6), `test_favoritos.py` (38),
  `test_inicializacao.py` (21), `test_logo_service.py` (13),
  `test_menu_principal.py` (39), `test_permissoes.py` (22),
  `test_scraper_fiis.py` (12), `test_telegram_stability.py` (14) e
  `test_trocas.py` (20).
- Os testes rodam sem `TELEGRAM_BOT_TOKEN`; quando um token é necessário,
  usam apenas um valor fictício. Não há conexão com o banco real.
- Os 7 testes de `test_catalogo_postgres.py` exercitam as migrações 0005/0006/
  0007 em um PostgreSQL local descartável e são ignorados sem
  `TEST_DATABASE_URL`; o módulo recusa hosts remotos (incluindo o Neon):

  ```bash
  TEST_DATABASE_URL="postgresql+psycopg://usuario:senha@127.0.0.1:5432/robo_test" \
      python3 -m unittest tests.test_catalogo_postgres -v
  ```
- O import de `main.py` e dos módulos do bot não exige token; apenas a
  inicialização efetiva (boot do servidor) exige `TELEGRAM_BOT_TOKEN` e falha
  com mensagem clara se ele estiver ausente.
- A IA é opcional no boot: sem `GROQ_API_KEY`, o bot inicia e apenas as
  operações de IA falham de forma controlada (`IAIndisponivelError`).

---

## 7. Banco de dados e migrações

- Acesso via SQLAlchemy. A conexão é criada de forma preguiçosa por
  `pipeline_dados/conexao.py`, usando a `DATABASE_URL` normalizada.
- Modelos:
  - `pipeline_dados/banco_dados.py` — `Ativo`, `DadosFinanceirosAcoes`,
    `DadosFinanceirosFiis`, `DocumentosQualitativos` (máquina de estados:
    `SALVO`, `SALVO_DRIVE`, `AGUARDANDO_REVISAO`, `ERRO_DOWNLOAD`, `ERRO_DRIVE`,
    `REJEITADO_MANUAL`).
  - `pipeline_dados/modelos_usuarios.py` — tabela `usuarios` existente no Neon
    (somente mapeamento; o projeto não a cria nem recria).
  - `pipeline_dados/modelos_ativos.py` — associação de favoritos.
- A aplicação **não executa migrações automaticamente** e não altera o schema no
  boot.
- Migrações versionadas (execução **manual**, pelo administrador, com backup
  antes; instruções e estado real em `migrations/README.md`):
  - `0001_add_status_cadastro_usuarios.sql` — coluna `status_cadastro`;
  - `0002_add_solicitacoes_troca.sql` — tabela `solicitacoes_troca`;
  - `0003_fix_solicitacoes_troca_unique.sql` — índice único parcial de pendentes;
  - `0004_add_favoritos_pendentes_usuarios.sql` — coluna `favoritos_pendentes`;
  - `0005_catalogo_empresas.sql` — tabelas do catálogo central e fila de revisão;
  - `0006_cache_logos_telegram.sql` — cache persistente de `file_id` de logos;
  - `0007_empresa_ativo_unico.sql` — unicidade de `empresa_ativos.ativo_id`.
  As sete migrações **existem no repositório**, mas **nenhuma foi executada ou
  verificada no Neon nesta revisão**. O estado real é desconhecido até uma
  verificação somente leitura feita pelo administrador; nada é aplicado no boot.
- Criação de tabelas apenas de forma opt-in (`CRIAR_TABELAS=1`), destinada a
  ambientes de desenvolvimento limpos.

---

## 8. Funcionalidades inativas ou pendentes

Código presente no repositório que **não participa do fluxo ativo**. Não remova
sem antes decidir o destino:

- `services/motor_ia.py` — leitura de relatórios com IA. É importado pelo
  orquestrador, mas a chamada está comentada e a resposta de IA é simulada (não
  usa API real). **Não é uma funcionalidade ativa.**
- `modules/module_fatos.py` — resumo de fatos via Groq; não é importado por
  nenhum fluxo.
- `modules/module_macro.py` — dados macroeconômicos; não é importado.
- `modules/llm_manager.py` — gerenciador de múltiplos LLMs; não é importado.
- `modules/motor_imagem.py` e `modules/gerador_graficos.py` — imagem e gráfico;
  exigem `Pillow`/`matplotlib`, que não estão em `requirements.txt`.
- `modules/leitor_pdf.py::extrair_texto_do_pdf` — função sem chamadas (a usada é
  `extrair_texto_com_paginas`, acionada apenas pelo `services/motor_ia.py`
  inativo).
- `GEMINI_API_KEY` — mapeada no workflow, sem uso no código.

Outras pendências de manutenção (ver roadmap abaixo): rotacionar o token do bot
caso ele tenha sido exposto em histórico, confirmar `/resetar_docs`, corrigir o
coletor de FIIs por CNPJ, revisar o filtro de ROE do garimpo de ações e sanitizar
a entrada do `/adicionar`.

---

## 9. Controle de usuários e permissões

O acesso é restrito a usuários autorizados. Atualizações de chats fora da
allowlist são descartadas antes de qualquer handler executar; não há liberação
automática para quem inicia uma conversa.

### Papéis

| Papel | Telegram ID (padrão no código) | Descrição |
|---|---|---|
| `admin` | `8867098987` | Acesso administrativo total e todas as funcionalidades de `user`. |
| `user` | `5336458734` | Somente funcionalidades financeiras e de consulta autorizadas. |

### Permissões

Comandos liberados para `user`: `/menu`, `/start`, `/relatorios`, `/docs`,
`/help`.

Comandos exclusivos do `admin`: `/status`, `/adicionar`, `/forcar_varredura`,
`/forcar_docs_acoes`, `/processar_acoes_ia`, `/forcar_cvm`, `/forcar_fiis`,
`/alimentar_ia`, `/mapear_nomes`, `/resetar_docs`, `/revisao`, `/controles`.

Callbacks de `user` incluem navegação e consulta (`menu_*`, `macro_fii_*`,
`macro_ac_*`, `subsetor_fii_*`, `sub_ac_*`, `tipo_fii_*`, `setor_fii_*`,
`setor_acao_*`, `painel_*`, `dados_*`, `ano_*`, `mes_*`, `docs_*`, `dnav_*`,
`dl_*`, `ia_*`, `ajuda_*`, `ajuda_cvm_*`, `voltar_menu`, `favoritos_*`,
`oportunidades_*`) e favoritos (`favadd_*`, `favnew_*`, `favrem_*`).

Callbacks exclusivos do `admin`: `rev_*`, `cad_*`, `adm_*`, `ver_raiox_docs`,
`confirmar_reset`, `cancelar_reset`, `iniciar_revisao_pendencias`.

Operações não reconhecidas (comandos/callbacks desconhecidos) são tratadas como
administrativas por padrão (falha segura): não recebem autorização automática.

### Como a autenticação funciona

1. `bot/loader.py` — `BotAutorizado.process_new_updates` é o ponto único de
   despacho.
2. O chat é validado contra `config.CHATS_AUTORIZADOS`.
3. `bot/permissoes.py` identifica o autor pelo Telegram ID (`from_user.id`, com
   fallback para o `chat.id`), resolve o papel (`config.USUARIOS_AUTORIZADOS` e,
   para contas aprovadas no autocadastro, o banco), classifica a operação
   (comando ou callback) e decide se ela pode ser executada.
4. Operações negadas recebem uma mensagem genérica e são registradas em log; uma
   tentativa negada nunca interrompe o bot.

O papel é sempre derivado do Telegram ID fornecido pela plataforma; ele não pode
ser alterado por texto de comando, parâmetros nem por dados de callback.

### Cadastro e favoritos

- `bot/cadastro.py`: `/start` cria uma solicitação `pendente` (sem duplicar
  contas) e o administrador aprova/rejeita por botões. Usuários já autorizados
  por config entram direto no menu. Decisões administrativas são revalidadas no
  servidor (permissão do autor e estado atual da solicitação) e registradas em
  trilha de auditoria (`robo.auditoria`, logs estruturados). Como a tabela
  `usuarios` não tem colunas para username/nome de exibição do Telegram, esses
  dados e o status anterior da solicitação são anexados ao registro de auditoria
  (sem alterar o schema).
- `bot/favoritos.py`: favoritos individuais por usuário. Exigem conta
  persistente; usuários comuns precisam de cadastro aprovado e conta ativa. O
  administrador autorizado por config pode usá-los mesmo com status pendente,
  desde que exista registro correspondente em `usuarios`.

### Painel administrativo

O administrador autenticado recebe um painel próprio, distinto do fluxo dos
usuários comuns: Central de Controles, consulta de indicadores, Minha carteira e
Novos documentos. O fluxo de seleção de favoritos do cadastro (FIIs/Ações antes
da aprovação) **não** é apresentado ao administrador; se houver uma sessão
antiga em memória, ela é descartada e o painel administrativo assume.

### Central de Controles (`/controles`)

Painel administrativo para gerenciar acessos pelo Telegram, sem mexer no banco.
Abre por `/controles` ou pelo botão "⚙️ Central de Controles" do menu, que só
aparece para o administrador autorizado (`bot/central_controles.py`).

- **Áreas:** solicitações pendentes, usuários aprovados, rejeitados e suspensos,
  paginadas de 8 em 8. Ao tocar numa pessoa são exibidos nome completo, e-mail,
  Telegram User ID, username, data de cadastro e situação atual.
- **Ações por situação:** pendente → aprovar/rejeitar; aprovado → suspender;
  suspenso → reativar; rejeitado → aprovar (reconsiderar).
  Rejeitar, suspender, reativar e reconsiderar exigem confirmação.
- **Revalidação:** a cada callback o servidor confere o papel do autor (pelo
  Telegram ID do update, nunca pelo `callback_data`) e o estado atual do
  usuário; a transição é conferida de novo na gravação
  (`definir_status(..., origens_permitidas=...)`). Botões antigos não
  sobrescrevem um estado que mudou. O cartão `cad_*` de solicitação também só
  decide solicitações pendentes.
- **Contas somente leitura:** contas definidas em `config.USUARIOS_AUTORIZADOS`
  (por precedência de `bot.permissoes`, mudar o banco não revogaria o acesso) e
  a própria conta do autor aparecem com 🔒 e sem botões de ação.
- **Notificação:** o usuário afetado recebe as mensagens de `bot/cadastro.py`
  (aprovado, rejeitado, suspenso, reativado), sem identificar o administrador.
- **Auditoria:** `robo.auditoria` (`acao=central_<ação>`, `resultado`,
  `status_anterior`), o mesmo mecanismo do cadastro. A tabela `auditoria_acesso`
  não tem esquema declarado no repositório, então nenhuma coluna é presumida.
- **Sem exclusão:** não há remoção de usuários; o acesso é revogado por
  rejeição/suspensão, preservando histórico, documentos e auditoria. Nenhuma
  tabela ou migração foi criada.

Limitações conhecidas:

- O username não é persistido (não há coluna); é consultado ao Telegram na hora
  e aparece como "não disponível" se o usuário nunca conversou com o bot ou o
  bloqueou.
- Depois de aplicar a migração `0001` sem backfill, todas as linhas antigas têm
  `status_cadastro = 'pendente'` e aparecem em "Solicitações pendentes".
- Suspender um administrador definido só no banco é permitido a outro
  administrador; administradores definidos em `config` só mudam por configuração.

### Como adicionar outro usuário

Adicione o Telegram ID em `TELEGRAM_USUARIOS_LIMITADOS` (lista separada por
vírgulas) e reinicie o serviço. O administrador é definido por
`TELEGRAM_ADMIN_ID`. Chats de leitura podem ir em `TELEGRAM_CHATS_AUTORIZADOS`,
mas continuam sujeitos ao bloqueio de operações administrativas.

---

## 10. Segurança

- **Sem credenciais em texto puro na árvore atual**: `.gitignore` cobre
  `credenciais.json`, `.env`, chaves locais e bancos SQLite.
- **Sem SQL Injection**: consultas via SQLAlchemy (ORM parametrizado).
- **Controle de acesso por papel** e **allowlist de chats** (ver seção 9).
- **Token do bot**: se o token já tiver sido exposto no histórico do Git,
  rotacione-o e purgue o histórico. O código atual lê o token apenas de variável
  de ambiente.
- **Melhorias recomendadas**: confirmar `/resetar_docs` e sanitizar entradas que
  vão para o Google Sheets.

---

## 11. Roadmap

### P0 — correções críticas

1. Rotacionar o token do bot, se houver exposição em histórico.
2. Proteger o `/resetar_docs` com confirmação/autorização.
3. Corrigir o coletor de FIIs (busca por CNPJ).
4. Corrigir o filtro de ROE no garimpo de ações.
5. Sanitizar a entrada do `/adicionar` (formula injection no Google Sheets).

### P1 — robustez e manutenibilidade

1. Ampliar a cobertura de testes (coletores, orquestrador, banco) e executá-los
   no CI.
2. Popular o `hash_sha256` dos documentos para deduplicação real.
3. Decidir o destino do motor de IA do orquestrador (`services/motor_ia.py`):
   ativar ou remover.
4. Adicionar `Pillow` e `matplotlib` caso imagem/gráficos sejam ativados.

### P2 — qualidade de dados e observabilidade

1. Usar a data de publicação real dos documentos.
2. Tornar documentos `ERRO_DOWNLOAD`/`ERRO_DRIVE` reprocessáveis.
3. Padronizar logs (substituir `print` por `logging`) e expor métricas.

### P3 — escala e evolução

1. Fila de processamento (ex.: Redis + Celery) para lotes grandes.
2. Paralelizar downloads com limite de concorrência.
3. Extrair catálogos fixos de `config.py` para arquivos/tabelas externas.
4. Deploy reprodutível (Dockerfile + `render.yaml`/Procfile).

---

## 12. Tecnologias

- **Linguagem:** Python 3.x
- **Servidor/Agendamento:** Flask, Gunicorn, APScheduler, pytz
- **Bot:** pyTelegramBotAPI (webhook)
- **Dados/Scraping:** pandas, requests, yfinance, BeautifulSoup4, lxml, html5lib
- **Google:** gspread (Sheets), google-api-python-client (Drive),
  google-auth-oauthlib
- **IA:** Groq (classificação), OpenAI SDK (provedor alternativo)
- **PDFs:** PyPDF2, PyMuPDF, pdfplumber
- **Banco:** SQLAlchemy, PostgreSQL (Neon); SQLite apenas se definido
  explicitamente
- **Infra:** Render (servidor), GitHub Actions (cron)

---

## 13. Documentação do administrador

Para uma explicação simplificada do sistema (estrutura, funcionamento,
integrações, o que está ativo e o que ainda não está), consulte `admin.md`. Os
detalhes de migrações ficam em `migrations/README.md`.

---

*Construído com Python, APIs financeiras e LLMs para automatizar e blindar a
tomada de decisão no mercado financeiro.*
