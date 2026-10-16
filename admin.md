# Robô Financeiro — Guia do Administrador

Este documento explica, em linguagem simples, como o sistema está organizado e
como operá-lo. Ele foi escrito para o proprietário do projeto e reflete o estado
real do código. Detalhes técnicos aprofundados ficam no `README.md`, em
`migrations/README.md` e nos comentários dos próprios arquivos.

IMPORTANTE: nenhuma credencial real (tokens, senhas, URLs de banco) deve ser
colocada neste arquivo ou em qualquer arquivo versionado. Elas ficam apenas nas
variáveis de ambiente do Render e nos secrets do GitHub.

---

## 1. O que o sistema faz

O Robô Financeiro automatiza a coleta e a organização de informações de FIIs e
Ações da bolsa brasileira:

- raspa dados e documentos oficiais (FNET/B3, CVM, Fundamentus, StatusInvest,
  Yahoo Finance);
- classifica documentos com Inteligência Artificial (Groq) por nível de
  confiança;
- guarda os PDFs aprovados em pastas organizadas no Google Drive;
- alimenta planilhas do Google Sheets usadas como painel de dados;
- envia avisos e responde a comandos/menus por um bot do Telegram;
- registra o histórico de documentos em um banco relacional (PostgreSQL/Neon em
  produção).

Há dois "empregos" diferentes: um servidor que fica sempre no ar atendendo o
Telegram, e uma tarefa agendada que sai coletando dados.

---

## 2. Como o sistema roda (pontos de entrada)

1. `main.py` — o cérebro que fica no ar.
   - Roda no Render como servidor web (Flask) e recebe as mensagens do Telegram
     por webhook.
   - No boot, registra o webhook e liga um agendador (APScheduler) que dispara a
     varredura diária, de segunda a sexta, às 08:00 (horário de São Paulo).
   - Suba com `python main.py` (ou via gunicorn apontando para `main:app`).

2. `app.py` — o coletor de oportunidades agendado.
   - Não é o servidor web.
   - Roda pelo GitHub Actions (segunda a sexta, de 13h às 21h UTC, 5 vezes ao
     dia) com `python app.py`.
   - Dispara os scrapers de FIIs e Ações, grava os resultados em lote no Google
     Sheets e envia alertas consolidados no Telegram.

Observação: não há `Procfile`/`render.yaml` versionado; a configuração de deploy
do Render é feita no painel do Render.

---

## 3. Estrutura das pastas

- `bot/` — o bot do Telegram (comandos, menus, cadastro de usuários, favoritos,
  permissões e o carregador do bot).
- `modules/` — peças reutilizáveis: scrapers, leitura de PDF, acesso ao Google
  Drive, utilitários e clientes de IA.
- `services/` — serviços de apoio usados pelo bot e pela varredura: orquestrador
  da rotina diária, acesso às planilhas, menus/painéis e logos.
- `pipeline_dados/` — banco de dados: conexão, modelos (tabelas) e repositórios
  de leitura/escrita, além dos coletores CVM/FIIs.
- `migrations/` — scripts SQL manuais e versionados para o banco de produção.
  Nada aqui roda sozinho; a aplicação nunca aplica migração automaticamente.
- `tests/` — testes automatizados (rodam sem rede e sem banco real).
- `.github/workflows/main.yml` — o cron do GitHub Actions que executa `app.py`.

Dentro de `pipeline_dados/`, `atualizador_documentos.py` (na raiz) é a ponte entre
B3, banco, IA e Google Drive.

---

## 4. Principais arquivos e o que fazem

Interface do Telegram (pasta `bot/`):

- `loader.py` — cria a instância única do bot e centraliza o despacho de
  mensagens. Importar os módulos não exige o token; a inicialização real exige.
- `permissoes.py` — decide quem pode fazer o quê, pelo Telegram ID e papel
  (`admin` ou `user`).
- `cadastro.py` — autocadastro (`/start`) e aprovação/rejeição pelo
  administrador.
- `favoritos.py` — lista de ativos favoritos por usuário.
- `comandos.py` — comandos (`/status`, `/relatorios`, `/adicionar`, etc.).
- `handlers.py` — botões de tipo/setor, IA interativa (`/ia`) e raio-x de
  documentos.
- `callbacks_menus.py` — menus e o "catch-all" dos botões (deve ser carregado por
  último).
- `callbacks_revisao.py` — Central de Revisão Humana de documentos.
- `telegram_utils.py` — auxiliares (allowlist de chats, mensagens de falha).

Coleta, IA e armazenamento:

- `atualizador_documentos.py` — baixa PDFs novos, extrai texto, classifica com
  IA e salva no Drive conforme a confiança.
- `modules/GoogleDriveManager.py` — cria pastas no Drive e faz upload/movimentação
  de PDFs.
- `modules/leitor_pdf.py` — extrai texto de PDFs.
- `modules/module_ia.py` — responde às consultas de IA do bot.
- `modules/scraper_fiis.py` / `modules/scraper_acoes.py` — garimpo de
  oportunidades de FIIs e Ações.
- `fnet_scraper.py` — busca e baixa documentos do sistema FNET da B3.
- `pipeline_dados/` — modelos das tabelas (`banco_dados.py`,
  `modelos_usuarios.py`, `modelos_ativos.py`), conexão (`conexao.py`) e
  repositórios de usuários/favoritos; coletores `coletor_cvm.py`,
  `coletor_fiis.py`, `coletor_docs_acoes.py`.

Serviços (`services/`):

- `orquestrador.py` — a `varredura_diaria` (rotina B3/FNET + CVM).
- `planilhas.py` — leitura do Google Sheets com cache de 5 minutos.
- `dashboard_menus.py` — monta os painéis de oportunidades/favoritos do bot.
- `logo_service.py` — busca logos dos ativos (Logo.dev, com plano B no GitHub).

---

## 5. Integrações e serviços externos

- Telegram (bot e envio de alertas).
- Neon / PostgreSQL (banco de produção) via SQLAlchemy.
- Google Sheets (painel de dados) e Google Drive (cofre de PDFs e logos).
- Groq (classificação e consultas de IA); OpenAI/OpenRouter como alternativas.
- Fontes de mercado: FNET/B3, CVM, Fundamentus, StatusInvest, Yahoo Finance.
- Render (hospedagem do servidor) e GitHub Actions (cron do coletor).

---

## 6. Configurações importantes

Nunca versionar valores reais. Os nomes das variáveis mais relevantes:

Render (servidor `main.py`):

- Obrigatórias: `TELEGRAM_BOT_TOKEN`, `DATABASE_URL`.
- Permissões: `TELEGRAM_ADMIN_ID`, `TELEGRAM_USUARIOS_LIMITADOS`,
  `TELEGRAM_CHATS_AUTORIZADOS`.
- Opcionais: `WEBHOOK_BASE_URL`, `PORT`, `GROQ_API_KEY`, `LOGO_DEV_TOKEN`,
  `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_BASE_URL`, `CLIENT_ID`,
  `CLIENT_SECRET`, `REFRESH_TOKEN`, `DRIVE_ROOT_FOLDER_ID`, `GOOGLE_CREDS`.
- Flags de manutenção: `CRIAR_TABELAS` (criação de tabelas, apenas em
  desenvolvimento) e `ROBO_INICIAR_NO_IMPORT` (boot completo ao importar).

GitHub Actions (coletor `app.py`), via secrets:

- `GOOGLE_CREDENTIALS`, `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`, `LOGO_DEV_TOKEN`,
  `CLIENT_ID`, `CLIENT_SECRET`, `REFRESH_TOKEN`, `DRIVE_ROOT_FOLDER_ID`.
- `GEMINI_API_KEY` está mapeada no workflow, mas nenhum código atual a usa.

Regras de acesso (resumo):

- `admin` acessa tudo; `user` acessa apenas consultas/financeiro.
- Usuários novos entram por autocadastro (`/start`) e ficam pendentes até a
  aprovação do administrador.
- Comandos/callbacks desconhecidos são tratados como administrativos (negação
  segura).
- O administrador é reconhecido pela configuração (Telegram ID), não por um
  papel gravado no banco.

---

## 7. O que está ativo hoje

- Servidor Flask + webhook do Telegram no Render.
- Agendador diário (seg-sex, 08:00 America/Sao_Paulo) e varredura orquestrada.
- Bot: comandos, menus, permissões (`admin`/`user`), autocadastro com aprovação,
  favoritos individuais e Central de Revisão Humana.
- Coleta B3/FNET, CVM e garimpo de oportunidades (Ações e FIIs) via GitHub
  Actions.
- IA documental (extração de PDF + classificação com confiança) e consultas de
  IA pelo bot.
- Google Drive (pastas hierárquicas + revisão) e Google Sheets.
- Banco de dados com máquina de estados dos documentos.
- Testes automatizados do bot (executados manualmente; hoje passam 115 testes).

---

## 8. O que existe no código mas ainda não está ativo/confirmado

Estes arquivos existem, mas não participam do fluxo atual. Não remova sem antes
confirmar que ninguém pretende ativá-los:

- `services/motor_ia.py` — leitura de relatórios com IA; é importado pelo
  orquestrador, mas a chamada está comentada e a resposta de IA é simulada (não
  usa API real).
- `modules/module_macro.py` — dados macroeconômicos; não é usado por nenhum
  fluxo.
- `modules/llm_manager.py` — gerenciador de vários LLMs; não é importado.
- `modules/motor_imagem.py` e `modules/gerador_graficos.py` — imagem e gráfico;
  exigem `Pillow`/`matplotlib`, que não estão nas dependências.
- `modules/module_fatos.py` — resumo de fatos via Groq; não é importado.
- Dentro de `modules/leitor_pdf.py`, a função `extrair_texto_do_pdf` não é usada
  (a usada é `extrair_texto_com_paginas`).

---

## 9. Estado das migrações do banco

- Existe uma migração versionada em
  `migrations/versions/0001_add_status_cadastro_usuarios.sql` que adiciona a
  coluna de status de cadastro à tabela `usuarios`.
- A aplicação NÃO aplica migrações automaticamente. A execução é manual e
  documentada em `migrations/README.md`.
- Antes de qualquer execução manual: faça backup e leia o `migrations/README.md`.
- Pendências conhecidas de correção de dados ficam no roadmap do `README.md`
  (ex.: token do bot, coletor de FIIs por CNPJ, filtro de ROE, sanitização do
  `/adicionar`).

---

## 10. Onde procurar os detalhes técnicos

- Arquitetura, fluxos e roadmap: `README.md`.
- Como aplicar e reverter migrações: `migrations/README.md`.
- Regras de permissão e papel: comentários em `bot/permissoes.py` e
  `bot/cadastro.py`.
- Como rodar os testes: seção "Configuração Rápida" do `README.md`.

---

## 11. Verificações rápidas de saúde

- Testes (não acessam serviços reais): rode
  `python -m unittest discover -s tests` na raiz do projeto.
- Logs: o bot registra autorizações, negações e falhas de handler; o cadastro
  registra as decisões administrativas.
- Segurança: nunca exibir tokens, senhas nem a URL de conexão; se um segredo
  vazar, rotacione-o e purgue o histórico do Git.
