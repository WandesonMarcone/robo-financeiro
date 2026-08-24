# 🤖 Robô Financeiro & Data Lake Institucional

Bem-vindo ao repositório do **Robô Financeiro**, um ecossistema avançado de Engenharia de Dados focado no mercado financeiro brasileiro (B3). 

Este sistema abandona o modelo amador de planilhas manuais e implementa uma arquitetura automatizada de coleta de dados, auditoria de FIIs/Ações, raspagem de documentos oficiais (FNET/CVM) e integração com Inteligência Artificial para análise de crédito imobiliário.

---

## 🎯 Objetivos Alcançados (Arquitetura Atual)
- **Data Lake Dinâmico:** Utilização do Google Sheets como banco de dados visual (Dashboard), recebendo cargas contínuas e automatizadas via APIs.
- **Scraping Resiliente:** Sistema de fallback duplo. Se uma API ou site falha (ex: Fundamentus fora do ar), o robô busca os dados no Yahoo Finance ou StatusInvest.
- **Acervo Documental na Nuvem:** Varredura autônoma no sistema FNET da B3 para capturar Fatos Relevantes e Relatórios Gerenciais, organizando-os automaticamente em pastas dinâmicas no Google Drive.
- **Bot de Telegram Operacional:** Interface mobile em tempo real para controle do fluxo, emissão de alertas de oportunidades VIP (quando um ativo entra na margem de desconto) e links diretos para leitura de PDFs oficiais.
- **Banco de Dados Relacional:** Integração com SQLite e SQLAlchemy para evitar processamentos duplicados, registrando o histórico de relatórios baixados.

---

## 📂 Mapeamento de Arquivos e Módulos

### 📱 Interface e Servidor
* `bot_telegram.py`: O "cérebro" da comunicação. Roda 24/7 no Render (via Webhook/Gunicorn), processando menus do usuário e despachando tarefas pesadas (Threads) sem causar *timeout* no servidor.
* `app.py`: O ponto de entrada da aplicação Web que mantém o sistema vivo no ambiente em nuvem.

### 🕵️ Motores de Busca e Auditoria (Scrapers)
* `scraper_fiis.py`: Motor focado em Fundos Imobiliários. Audita P/VP, Dividend Yield, Vacância Física Real e Quantidade de Imóveis fazendo engenharia reversa no HTML do StatusInvest e Fundamentus.
* `scraper_acoes.py`: Caçador de barganhas focado em Ações. Calcula P/L, ROE, Margens e gerencia o tradutor de setores globais para organizar o portfólio.
* `fnet_scraper.py`: Robô especializado na plataforma da B3 (FNET), encarregado de caçar e baixar PDFs institucionais utilizando filtros avançados.

### 📁 Gerenciamento de Nuvem e Banco de Dados
* `atualizador_documentos.py`: A ponte entre a B3, o Banco de Dados e o Google Drive. Faz a checagem de integridade para saber se o FII já está registrado, baixa PDFs inéditos e salva no BD.
* `modules/GoogleDriveManager.py`: Módulo customizado de API do Google. Verifica a existência de diretórios, cria pastas hierárquicas dinâmicas (Ticker > Categoria) e faz o upload de PDFs liberando link público.
* `pipeline_dados/banco_dados.py`: Modelagem ORM (SQLAlchemy) contendo as classes e constraints do sistema (Ativos e DocumentosQualitativos).

### 🛠️ Configurações e Variáveis de Ambiente
* `config.py`: Centralizador de variáveis de ambiente e chaves sensíveis (`GROQ_API_KEY`, Tokens do Telegram e APIs do Google).
* `requirements.txt`: Relação estruturada das dependências do Python para build e deployment.

---

## 🚀 Próximos Passos (No Papel / Em Desenvolvimento)

O sistema está em fase de transição para se tornar um Analista Quantitativo completo. Os próximos desenvolvimentos programados são:

1. **Inteligência Artificial Documental (Groq / Llama 3):**
   - Extração textual de PDFs via `pdfplumber` no momento em que são salvos no Drive.
   - Envio do texto bruto para a API do Groq (LLM) forçando a resposta em formato *JSON Schema*.
   - **Métricas Alvo:** Leitura autônoma de relatórios gerenciais para injetar diretamente na planilha o **WALT** (Prazo médio de contratos), nível de **Alavancagem (Dívida)** e **Lista de Inquilinos**.

2. **Cronjob CVM Total (GitHub Actions):**
   - Transição total da coleta de balanços para bibliotecas institucionais (`brfinance`, `finlogic`), abolindo o *HTML Parsing* em favor do download direto dos demonstrativos financeiros da CVM.

3. **Módulo de Saúde (Alerta Precoce):**
   - Bot do Telegram emitirá alertas proativos não apenas para queda de preços, mas para aumento de vacância real detectado no portfólio do investidor.

---
*Construído com Python, APIs Financeiras e LLMs para automatizar e blindar a tomada de decisão no mercado financeiro.*