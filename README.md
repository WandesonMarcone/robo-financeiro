# Robo Financeiro

Ecossistema de coleta, classificacao e consulta de dados da B3 (FIIs e Acoes).
O sistema raspa documentos oficiais (FNET/B3 e CVM), classifica PDFs com IA
(catalogo fixo, duas checagens), organiza o acervo no Google Drive, grava o
painel no Google Sheets e opera pelo bot do Telegram.

Dois processos independentes:

- `main.py` no Render: Flask + webhook do Telegram + varredura documental diaria.
- `app.py` no GitHub Actions: garimpo de oportunidades (FIIs/Acoes) e alertas.

Nao ha `admin.md` neste repositorio. Detalhes de schema ficam em
`migrations/README.md` e `docs/neon-schema-modelo.md`.

---

## 1. Visao geral

Capacidades ativas:

- Scraping com fallback (Fundamentus, StatusInvest, Yahoo Finance).
- Acervo documental: FNET/B3 e CVM, PDFs no Drive em
  `Documentos / Tipo / Ticker / Ano / Mes`, mais pasta de revisao.
- IA documental (Groq): duas checagens, catalogo fixo, auto-save so com acordo
  e confianca >= 80. Lote `Classificar com IA` identifica, renomeia e move no
  Drive pelo mes de `assunto` (data de busca), sem alterar `data_publicacao`.
- Bot Telegram: menus, consultas, alertas, cadastro, favoritos, Central de
  Controles e Central de Revisoes (hub com Usuarios, Notificacoes e Revisoes).
- PostgreSQL/Neon via SQLAlchemy. Schema de producao nao e alterado no boot.

---

## 2. Arquitetura

```mermaid
graph TD
    subgraph Operacao
        BOT["Bot Telegram bot/"]
        WEB["Flask main.py"]
        SCH["APScheduler seg-sex 08:00"]
        ACT["Cron GitHub Actions 5x/dia"]
    end
    subgraph Pipeline
        ORC["orquestrador.varredura_diaria"]
        GAR["Garimpo app.py"]
        COL["Coletores CVM / FNET / B3"]
        LOTE["Lote IA Classificar"]
    end
    subgraph Fontes
        CVM["CVM"]
        FNET["FNET B3"]
        FUND["Fundamentus"]
        SI["StatusInvest"]
        YF["Yahoo Finance"]
    end
    subgraph Processamento
        PDF["Extracao PDF"]
        IA["Dupla checagem Groq"]
        CAT["Catalogo tipos_documento"]
    end
    subgraph Armazenamento
        DB[("PostgreSQL / Neon")]
        SHEET[("Google Sheets")]
        DRIVE[("Google Drive")]
    end
    BOT --> ORC
    BOT --> LOTE
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
    LOTE --> IA
    IA --> CAT
    CAT --> DRIVE
    CAT --> DB
    PDF --> IA
    ORC --> DB
    GAR --> SHEET
```

### Servidor (`main.py`, Render)

- Flask: webhook do Telegram e rota raiz de status.
- APScheduler: varredura documental segunda a sexta as 08:00 America/Sao_Paulo.
- `create_all` so com `CRIAR_TABELAS=1`. Importar `main` nao agenda jobs nem
  registra webhook, salvo `ROBO_INICIAR_NO_IMPORT=1`.
- Local: `python main.py`.

### Coletor de oportunidades (`app.py`, GitHub Actions)

- Nao e servidor web.
- Garimpo de FIIs e Acoes, gravacao em lote no Sheets e dois pushes de MOVIMENTACAO (1 FII + 1 acao) so para o admin, com botoes `painel_{TICKER}_fii|acao`.
- Fila sem amostra aleatoria ("outras"); carimbo `OK dd/mm HH:MM` ativa o throttle de 2h.
- Canal separado de `alertas_eventos` (hub 🔔). Snapshot EOD no Neon so com `EOD_SNAPSHOTS=1`.
- Cron em `.github/workflows/main.yml`: `0 13,15,17,19,21 * * 1-5` (UTC). Injeta `DATABASE_URL` para a carteira popular.
- Nome da empresa em `BD_Acoes` coluna AH: Yahoo so na primeira captura; PETR3/PETR4 reutilizam o mesmo nome.

### Ordem de registro dos handlers

O `pyTelegramBotAPI` para no primeiro handler que casar. Por isso
`bot.callbacks_menus` (catch-all `func=lambda call: True`) e o ultimo:

1. `bot.cadastro`
2. `bot.central_controles`
3. `bot.favoritos`
4. `bot.trocas`
5. `bot.menu_principal`
6. `bot.comandos`
7. `bot.handlers`
8. `bot.callbacks_revisao`
9. `bot.callbacks_menus`

Callbacks especificos (`cad_*`, `adm_*`, `favoritos_*`, `favadd_*`, `favnew_*`,
`favrem_*`, `troca_*`, `rev_*`) precisam ser registrados antes do generico.
O handler `rev_*` ignora `acao == 'ia'` para nao engolir `rev_ia_lote`.

---

## 3. Fluxos centrais

### Documentos FII (FNET -> banco -> Drive)

1. `pipeline_dados/coletor_fnet.py` mapeia o tipo e grava `assunto=data_ref`
   (ex.: `15/01/2025`). Essa data de busca nao muda depois.
2. `atualizador_documentos.py` processa a fila: baixa PDF (teto 1.5 MB),
   extrai ate 3 paginas, classifica.
3. Alias conhecido (Ago/Age etc.) mapeia ao catalogo sem IA, mas ainda entra
   na fila para organizar.
4. Auto-save FII: acordo das duas checagens, confianca >= 80 e texto no PDF.
   Senao: `AGUARDANDO_REVISAO`.
5. Identificado: `_confirmar_identificacao` grava o tipo, limpa `resumo_ia`,
   status `SALVO_DRIVE`, move/renomeia no Drive
   (`{tipo}_{assunto}_{id_b3}.pdf`) na pasta do mes de `assunto`. Falha no
   Drive nao desfaz a classificacao no banco.

### Lote `Classificar com IA` (um clique)

- Callback `rev_ia_lote`: responde o webhook na hora e classifica em thread
  (evita SIGKILL/OOM no Gunicorn). Lock anti-reentrada.
- `reclassificar_documentos_genericos_em_lotes` fatia de 3 em 3
  (`LIMITE_RECLASSIFICACAO = 3`, teto `MAX_LOTES_RECLASSIFICACAO = 40`).
- `excluir_ids` evita repetir; `_precisa_reclassificar` pula quem ja tem
  `checagem_1` + `checagem_2` em `resumo_ia`.
- Sem texto: marca `AGUARDANDO_REVISAO` e oferece `IA ler paginas 2 e 3`
  (`rev_ia_pags`, `pagina_inicial=1`, `somente_sem_texto=True`).
- Resumo Telegram: lotes, examinados, identificados, organizados no Drive,
  revisao, sem texto, erros e tipos por fundo.
- Drive injetavel via `drive_manager=` (testes sem rede).

### Hub administrativo

Tres areas, callbacks `adm_*` / `rev_*`, navegacao e autorizacao intactas:

- Usuarios: `adm_usuarios`
- Notificacoes: `adm_notificacoes` (filtro DY na exibicao, fatos persistidos
  em `alertas_eventos` nao sao apagados)
- Central de Revisoes: `adm_revisoes`

Novos Documentos lista so `SALVO_DRIVE`/`SALVO` com tipo do catalogo
(Documento, Ago, Age crus nao entram).

### Entrada por mensagem (alem de `/start`)

Qualquer mensagem privada (texto livre ou midia) funciona como entrada:

- administrador e usuario aprovado recebem o painel;
- conta pendente/rejeitada/suspensa recebe o status atual;
- visitante inicia o autocadastro (nome -> e-mail -> confirmacao).

O gate de `bot.permissoes` continua sendo aplicado pelo `bot.loader` antes do
despacho; durante um formulario ativo o texto e consumido pelo formulario e a
midia recebe um aviso para responder em texto, sem reiniciar o cadastro.

---

## 4. Organizacao das pastas e comentario de cada arquivo

### Raiz

| Arquivo | Comentario |
|---|---|
| `README.md` | Este documento: arquitetura, fluxos e inventario de arquivos. |
| `main.py` | Servidor Flask, webhook Telegram, APScheduler e ordem de import dos handlers. |
| `app.py` | Garimpo de oportunidades (FIIs/Acoes), gravacao no Sheets e 2 digests de MOVIMENTACAO; cron do Actions. |
| `config.py` | Constantes, papeis, favoritos, `TIPOS_DOC_FII` (ids 0-38), `TIPOS_DOC_ACAO`, mapas B3. |
| `atualizador_documentos.py` | Ponte B3/banco/IA/Drive: fila, dupla classificacao, lote IA, helpers de Drive. |
| `fnet_scraper.py` | Download de PDF da FNET com sessao, stream e `max_bytes` (sem /tmp). |
| `requirements.txt` | Dependencias Python (Flask, telebot, SQLAlchemy, Groq, Drive, PDFs). |
| `.gitignore` | Ignora credenciais, `.env`, bancos locais e artefatos. |

### `.github/`

| Arquivo | Comentario |
|---|---|
| `.github/workflows/main.yml` | Cron 5x/dia (seg-sex) que instala deps, monta `credenciais.json`, injeta `DATABASE_URL` e roda `app.py`. |

### `bot/` — Telegram

| Arquivo | Comentario |
|---|---|
| `bot/loader.py` | Instancia unica do bot (`BotAutorizado`): token obrigatorio, allowlist de chats, despacho. |
| `bot/permissoes.py` | Fonte unica de papel (`admin`/`user`) e autorizacao de comando/callback pelo Telegram ID. |
| `bot/telegram_utils.py` | Painéis, emojis de botoes, textos de acesso negado e descricao de updates (modulo leve). |
| `bot/sessao_cadastro.py` | Estado em memoria do formulario de autocadastro (sem banco, sem pipeline). |
| `bot/cadastro.py` | `/start`: formulario nome/e-mail, solicitacao pendente e aprovacao/rejeicao admin. |
| `bot/central_controles.py` | Hub `/controles`: Usuarios, Notificacoes filtradas e atalho para Revisoes. |
| `bot/favoritos.py` | Favoritos individuais (`ativos_acompanhados`); teto por tipo; exige conta aprovada. |
| `bot/trocas.py` | Usuario pede troca de favorito; admin decide; persistido em `solicitacoes_troca`. |
| `bot/menu_principal.py` | Painel inicial por usuario: saudacao, favoritos, Novos Documentos e Meus Alertas. |
| `bot/comandos.py` | Comandos (`/menu`, `/revisao`, varreduras forçadas, `/ia`, reset) e relatorio pos-coleta. |
| `bot/handlers.py` | Callbacks de navegacao financeira (tipo/setor FII, setor acao, docs, downloads). |
| `bot/callbacks_revisao.py` | Central de Revisoes: lote IA, paginas 2-3, `rev_typ` (Drive), markup e resumo por fundo. |
| `bot/callbacks_menus.py` | Catch-all de menus/paineis (oportunidades, carteira, dados); registrado por ultimo. |

### `modules/` — scrapers, Drive, PDF, IA pontual

| Arquivo | Comentario |
|---|---|
| `modules/__init__.py` | Pacote; sem logica. |
| `modules/GoogleDriveManager.py` | Pastas hierarquicas, upload organizado, `mover_arquivo_da_revisao_por_id`, logos. |
| `modules/scraper_fiis.py` | Garimpo de FIIs (P/VP, DY, vacancia); fila VIP/popular/oportunidades, sem aleatorio. |
| `modules/scraper_acoes.py` | Indicadores de acoes (P/L, P/VP, ROE, margens, DY); nome da empresa na coluna AH (Yahoo so na 1a vez). |
| `modules/relatorio_mercado.py` | Nomes oficiais (AH), hidratacao PETR3/PETR4, filtro de oportunidades e digest FII/acao. |
| `modules/utils.py` | `conectar_gspread`, conversao numerica, markup `painel_{ticker}_*` e disparo de MOVIMENTACAO. |
| `modules/leitor_pdf.py` | Extracao de texto (PyMuPDF / pdfplumber); uso legado vs lote leve em `atualizador_documentos`. |
| `modules/module_ia.py` | Consultas `/ia` do bot (Groq, com fallbacks de provedor). |
| `modules/eod_snapshots.py` | Monta payloads EOD a partir das abas; persistencia Neon opcional (`EOD_SNAPSHOTS`). |

### `pipeline_dados/` — banco, coletores, repositorios

| Arquivo | Comentario |
|---|---|
| `pipeline_dados/__init__.py` | Pacote; sem logica. |
| `pipeline_dados/conexao.py` | Normaliza `DATABASE_URL`, cria engine e session factory preguicosa. |
| `pipeline_dados/banco_dados.py` | ORM de `Ativo`, `DadosFinanceirosAcoes/Fiis`, `DocumentosQualitativos`. |
| `pipeline_dados/modelos_usuarios.py` | Mapeia `usuarios` (nao cria tabela). |
| `pipeline_dados/modelos_ativos.py` | Mapeia `ativos_acompanhados` (favoritos). |
| `pipeline_dados/modelos_trocas.py` | Mapeia `solicitacoes_troca` (tabela nova via migracao 0002). |
| `pipeline_dados/modelos_alertas.py` | Mapeia `alertas_eventos` (somente leitura pelo bot). |
| `pipeline_dados/modelos_snapshots.py` | Mapeia `snapshots_acoes` e `snapshots_fiis`. |
| `pipeline_dados/modelos_catalogo.py` | Empresas, setores, vinculos ticker-empresa, sugestoes e cache de logos. |
| `pipeline_dados/repositorio_usuarios.py` | Cadastro, status e listagens; session injetavel nos testes. |
| `pipeline_dados/repositorio_favoritos.py` | Vinculo usuario-ativo; nunca aceita `usuario_id` vindo do cliente. |
| `pipeline_dados/repositorio_trocas.py` | Cria/decide solicitacoes de troca com historico. |
| `pipeline_dados/repositorio_alertas.py` | Consulta alertas pelos favoritos; nao grava. |
| `pipeline_dados/repositorio_snapshots.py` | Upsert EOD idempotente `(ativo_id, data_referencia)`. |
| `pipeline_dados/repositorio_catalogo.py` | Upserts do catalogo, vigencia setorial e fila de revisao. |
| `pipeline_dados/repositorio_logos.py` | Cache persistente do `file_id` do Telegram. |
| `pipeline_dados/tipos_documento.py` | Catalogo oficial FII/acao e aliases FNET (Ago/Age/ITR etc.); sem inventar nomes. |
| `pipeline_dados/filtro_alertas.py` | Esconde ruido DY (% vs fracao) e duplicatas do mesmo dia; nao apaga fatos. |
| `pipeline_dados/taxonomia_catalogo.py` | Aliases e validacao da taxonomia B3 usada pela IA de catalogo. |
| `pipeline_dados/identidade_visual.py` | Grupos de logo por empresa (PETR3/PETR4); nao une dados financeiros. |
| `pipeline_dados/coletor_fnet.py` | Varredura FNET: associa ticker FII, grava `assunto=data_ref`, nao cria PENDENTE. |
| `pipeline_dados/coletor_cvm.py` | ITR de acoes da CVM (ZIP/CSV) associado por CNPJ. |
| `pipeline_dados/coletor_docs_acoes.py` | Documentos IPE de acoes (grava URL, nao baixa PDF nesta etapa). |
| `pipeline_dados/coletor_fiis.py` | Informes mensais de FIIs da CVM associados por CNPJ. |
| `pipeline_dados/coletor_catalogo_cvm.py` | Importa FCA oficial e associa tickers a empresas. |

### `services/` — orquestracao e paineis

| Arquivo | Comentario |
|---|---|
| `services/__init__.py` | Pacote; sem logica. |
| `services/orquestrador.py` | `varredura_diaria`: FNET/B3 + CVM; avisos so ao admin; docs nao em broadcast. |
| `services/planilhas.py` | Leitura do Google Sheets com cache de 5 min. |
| `services/dashboard_menus.py` | Paineis de oportunidades, favoritos e raio-x do ativo. |
| `services/logo_service.py` | Drive (Icones B3) -> Brand API/CDN (`/ticker/{TICKER}.SA`) -> texto; grava no Drive e envia bytes ao Telegram. |
| `services/catalogo_empresas.py` | Aplica `MAPA_SETORES_B3` e monta resumo da empresa. |
| `services/catalogo_ia.py` | Novidades de catalogo assistidas por IA; ambiguos vao para sugestoes. |
| `services/motor_ia.py` | Leitura de relatorios com IA; importado mas chamada inativa (nao e fluxo ativo). |

### `migrations/` e `docs/`

| Arquivo | Comentario |
|---|---|
| `migrations/README.md` | Como aplicar/reverter; nenhuma migracao roda no boot. |
| `migrations/versions/0001_add_status_cadastro_usuarios.sql` | Coluna `usuarios.status_cadastro`. |
| `migrations/versions/0002_add_solicitacoes_troca.sql` | Tabela `solicitacoes_troca`. |
| `migrations/versions/0003_fix_solicitacoes_troca_unique.sql` | Indice unico parcial de pendentes. |
| `migrations/versions/0004_add_favoritos_pendentes_usuarios.sql` | Coluna `usuarios.favoritos_pendentes`. |
| `migrations/versions/0005_catalogo_empresas.sql` | Tabelas do catalogo central. |
| `migrations/versions/0006_cache_logos_telegram.sql` | Tabela `cache_logos_telegram`. |
| `migrations/versions/0007_empresa_ativo_unico.sql` | Unicidade `empresa_ativos.ativo_id`. |
| `docs/neon-schema-modelo.md` | Auditoria do schema Neon (somente referencia; nao executar). |

### `tests/` — sem rede, Drive injetavel, SQLite em memoria

| Arquivo | Comentario |
|---|---|
| `tests/test_acesso_ativos.py` | Limite de consulta do user comum aos favoritos e filtro de Novos Documentos. |
| `tests/test_alertas.py` | Leitura de `alertas_eventos` e texto de Meus Alertas. |
| `tests/test_bot_boot.py` | Import sem token; boot exige `TELEGRAM_BOT_TOKEN`. |
| `tests/test_cadastro.py` | Autocadastro e aprovacao via bot fake + SQLite. |
| `tests/test_callbacks_revisao.py` | Hub revisao, lote IA, resumo por fundo, `rev_ia_pags`, Drive no texto. |
| `tests/test_catalogo_correcoes.py` | Regressao do catalogo (repositorio/servico em SQLite). |
| `tests/test_catalogo_empresas.py` | Catalogo, taxonomia, importador CVM e IA (tudo fake). |
| `tests/test_catalogo_postgres.py` | Constraints reais; exige `TEST_DATABASE_URL` local (nunca Neon). |
| `tests/test_central_controles.py` | Hub Usuarios/Notificacoes/Revisoes e transicoes de status. |
| `tests/test_coletor_cvm.py` | ITR CVM com ZIP/HTTP fabricados. |
| `tests/test_coletor_docs_acoes.py` | Varredura IPE simulada. |
| `tests/test_coletor_fiis.py` | Informes mensais CVM simulados. |
| `tests/test_coletor_fnet.py` | FNET: tipo, `assunto=data_ref`, sem Drive real. |
| `tests/test_conversao.py` | Zero legitimo vs ausencia em `converter_numero`. |
| `tests/test_dashboard_logos.py` | Logos nos paineis (bytes do Drive fake / fallback texto). |
| `tests/test_documentos_notificacoes.py` | Docs so para seguidores do ativo (nunca broadcast). |
| `tests/test_eod_snapshots.py` | Writer EOD Sheets->Neon isolado. |
| `tests/test_favoritos.py` | Repositorio e UI de favoritos. |
| `tests/test_inicializacao.py` | URL do banco, boot sem Groq, Drive preguicoso no import. |
| `tests/test_logo_service.py` | Ordem Drive/Logo.dev/texto, PETR3/PETR4, cache. |
| `tests/test_menu_principal.py` | Painel inicial, Novos Documentos e Meus Alertas. |
| `tests/test_permissoes.py` | Papeis, allowlist e bloqueio de callbacks admin. |
| `tests/test_processamento_fila.py` | Fila, lote IA 3 em 3, Drive mock (mes de assunto, nome, data intacta). |
| `tests/test_relatorio_mercado.py` | Filtro de oportunidades, nomes Petrobras/AH e heranca PETR3/PETR4. |
| `tests/test_scraper_acoes.py` | Ausencia nao vira zero; coluna AH e heranca PETR3/PETR4 sem reconsultar Yahoo. |
| `tests/test_scraper_fiis.py` | SSL Fundamentus, conversao e protecao de indicadores. |
| `tests/test_telegram_stability.py` | Estabilidade de comandos com bot fake. |
| `tests/test_trocas.py` | Solicitacao e decisao de troca de favorito. |

---

## 5. Maquina de estados dos documentos

`DocumentosQualitativos.status_processamento`:

- `PENDENTE` / `PENDENTE_ACAO` — na fila de processamento.
- `SALVO` / `SALVO_DRIVE` — classificado; Drive organizado quando houver `file_id`.
- `AGUARDANDO_REVISAO` — sem acordo IA, sem texto, ou alias ainda na mesa.
- `ERRO_DOWNLOAD` / `ERRO_DRIVE` — falha operacional.
- `REJEITADO_MANUAL` — recusado na Central de Revisoes.

Constantes do lote IA (em `atualizador_documentos.py`):

- `LIMITE_RECLASSIFICACAO = 3`
- `MAX_LOTES_RECLASSIFICACAO = 40`
- `TAMANHO_MAX_PDF_CLASSIFICACAO = 1_500_000`
- `TEXTO_MAX_CLASSIFICACAO = 1500`
- `PAGINAS_MAX_CLASSIFICACAO = 3`

Pasta do Drive usa mes de `assunto` (`_mes_ref_do_doc` aceita `DD-MM-YYYY` e
`YYYY-MM-DD`). Sem `file_id` em `url_pdf` ou ticker `?`, o Drive e pulado.

---

## 6. Variaveis de ambiente

Nunca versionar tokens, senhas ou URLs reais.

### Render (`main.py`)

Obrigatorias: `TELEGRAM_BOT_TOKEN`, `DATABASE_URL` (normalizada para
`postgresql+psycopg://`; sem fallback silencioso para SQLite).

Acesso: `TELEGRAM_ADMIN_ID`, `TELEGRAM_USUARIOS_LIMITADOS`,
`TELEGRAM_CHATS_AUTORIZADOS`.

Opcionais: `WEBHOOK_BASE_URL`, `PORT`, `GROQ_API_KEY`, `LOGO_DEV_TOKEN` (pk_ da CDN),
`LOGO_DEV_SECRET_KEY` (sk_ da Brand API, para gravar no Drive),
`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_BASE_URL`, `CLIENT_ID`,
`CLIENT_SECRET`, `REFRESH_TOKEN`, `DRIVE_ROOT_FOLDER_ID`,
`DRIVE_LOGOS_FOLDER_ID`, `GOOGLE_CREDS`, `EOD_SNAPSHOTS`.

Flags: `CRIAR_TABELAS=1`, `ROBO_INICIAR_NO_IMPORT=1`.

### GitHub Actions (`app.py`)

Secrets: `GOOGLE_CREDENTIALS`, `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`,
`LOGO_DEV_TOKEN` (pk_), `LOGO_DEV_SECRET_KEY` (sk_, opcional para self-host),
`CLIENT_ID`, `CLIENT_SECRET`, `REFRESH_TOKEN`,
`DRIVE_ROOT_FOLDER_ID`. `GEMINI_API_KEY` esta no workflow sem uso no codigo.

---

## 7. Execucao local e testes

```bash
# Preparar ambiente
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Variaveis minimas
export TELEGRAM_BOT_TOKEN="seu_token_do_bot"
export DATABASE_URL="sua_url_de_conexao"
export GROQ_API_KEY="sua_chave_groq"

# Servidor
python main.py

# Garimpo manual
python app.py

# Testes (sem rede, sem Neon, Drive mockado)
python -m unittest discover -s tests
```

- Sem `GROQ_API_KEY` o bot sobe; so operacoes de IA falham (`IAIndisponivelError`).
- `tests/test_catalogo_postgres.py` e ignorado sem `TEST_DATABASE_URL` local.

```bash
TEST_DATABASE_URL="postgresql+psycopg://usuario:senha@127.0.0.1:5432/robo_test"
python3 -m unittest tests.test_catalogo_postgres -v
```

---

## 8. Permissoes

Chats fora de `CHATS_AUTORIZADOS` sao descartados em `bot/loader.py` antes de
qualquer handler. O papel vem so do Telegram ID.

| Papel | Escopo |
|---|---|
| `admin` | Tudo do user + varreduras, revisao, controles, cadastro, reset. |
| `user` | `/menu`, `/start`, `/relatorios`, `/docs`, `/help`, favoritos e consultas. |

Callbacks admin: `rev_*`, `cad_*`, `adm_*`, `ver_raiox_docs`, `confirmar_reset`,
`cancelar_reset`, `iniciar_revisao_pendencias`. Operacao desconhecida e tratada
como administrativa (falha segura).

---

## 9. Banco e migracoes

Acesso preguicoso em `pipeline_dados/conexao.py`. A aplicacao nao migra sozinha.
Aplicar `migrations/versions/*.sql` manualmente, com backup, na ordem 0001-0007.
Estado no Neon: ver `migrations/README.md` (nao presumir aplicacao).

---

## 10. Codigo presente mas inativo

- `services/motor_ia.py` — importado pelo orquestrador; chamada comentada.
- `GEMINI_API_KEY` — secret do workflow, sem referencia no Python.

---

## 11. Tecnologias

Python 3.x; Flask, Gunicorn, APScheduler; pyTelegramBotAPI; pandas, requests,
yfinance, BeautifulSoup4; gspread e google-api-python-client; Groq; PyPDF2 /
PyMuPDF / pdfplumber; SQLAlchemy + PostgreSQL (Neon); Render + GitHub Actions.
