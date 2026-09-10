# Fase 8 — Etapa 8.7: Auditoria e Estrategia de Fontes de Dados

Documento de auditoria (somente analise). Nao altera codigo, nao cria coletores,
nao adiciona APIs externas, nao altera o banco, nao expande o universo e nao
avanca para implementacao. Data da auditoria: 2026-09-05. Commit base:
`c9c8409` (arvore de trabalho limpa). Fase 8.6 CONCLUIDA (1128 testes, 0 falhas).

Classificacao por campo:

- A = fonte oficial/confiavel disponivel no stack atual
- B = fonte secundaria aceitavel
- C = fonte disponivel mas fragil
- D = sem fonte adequada atualmente

Google Sheets nao e tratado como fonte primaria. E cache operacional e
intermediario do Bloco 5C.

---

## 1. Fontes auditadas (somente as ja presentes no codigo)

### 1.1 CVM (`dados.cvm.gov.br`)

| Atributo | Valor observado no codigo |
|---|---|
| Uso atual | `pipeline_dados/coletor_fiis.py` (INF_MENSAL FII), `pipeline_dados/coletor_cvm.py` (ITR acoes), `pipeline_dados/coletor_docs_acoes.py` (IPE) |
| Oficialidade | Fonte primaria institucional |
| Identidade | CNPJ (`CNPJ_Fundo_Classe` / `CNPJ_Fundo`; acoes via `MAPA_CNPJ_B3` + catalogo 8.3) |
| Formato | ZIP + CSV (`;`, latin1) |
| Frequencia | INF_MENSAL: mensal; ITR: trimestral; IPE: continuo por evento |
| Automacao | Sim (HTTP GET, sem login). INF_MENSAL hoje so roda via `/forcar_fiis` |
| Historico | Sim (pacotes anuais) |
| Producao | Sim para os campos que o CSV realmente traz |

Colunas INF_MENSAL efetivamente mapeadas (8.6): `Patrimonio_Liquido`,
`Valor_Ativo`, `Disponibilidades`, `Total_Numero_Cotistas`,
`Cotas_Emitidas` / `Quantidade_Cotas_Emitidas`. Campo ausente permanece
fora do dict — nunca vira 0.

Campos do schema FII que o CSV **nao** traz: `rendimento_por_cota`,
`vacancia_fisica`, `vacancia_financeira`, `receita_imoveis`,
`resultado_ligado_venda`. `despesas_taxas`: o CSV pode ter percentual de
taxa, nao o valor em R$ do ORM.

### 1.2 B3 / FNET (`fnet.bmfbovespa.com.br`)

| Atributo | Valor observado no codigo |
|---|---|
| Uso atual | `fnet_scraper.py` + `atualizador_documentos.py` — download de PDF, classificacao, Drive |
| Oficialidade | Fonte primaria documental (Relatorio Gerencial, Informe Mensal, Fato Relevante, DFs, Rendimentos) |
| Identidade | Nome do fundo (`descricaoFundo`) + matching 8.3 (CNPJ/ticker/nome); `id_b3` |
| Formato | JSON da pesquisa + PDF binario |
| Frequencia | Evento / mensal (gerencial) / diario na varredura (SLA documentos 60d) |
| Automacao | Parcial: lista e download sim; extracao estruturada de metricas **nao** |
| Historico | Sim, limitado pela janela de varredura |
| Producao | Sim para **documentos**; nao para indicadores numericos |

`config.TIPOS_DOC_FII` ja distingue Relatorio Gerencial, Informe Mensal,
Demonstracoes Financeiras e Rendimentos. Nenhum parser persiste WALT,
alavancagem, vacancia ou inquilinos a partir desses PDFs.

`modules/module_fatos.py` tem prompt Groq para WALT/Alavancagem, mas a lista
de documentos e mock (`LINK_DIRETO_DO_PDF_AQUI`). Nao e pipeline de producao.

### 1.3 Fundamentus (`fundamentus.com.br`)

| Atributo | Valor observado no codigo |
|---|---|
| Uso atual | `modules/scraper_fiis.py` (`/fii_resultado.php`), `modules/scraper_acoes.py` (`/resultado.php`) |
| Oficialidade | Agregador terciario (HTML) |
| Identidade | Ticker (`Papel`) |
| Formato | Tabela HTML (`pd.read_html`, decimal BR) |
| Frequencia | Intradia (ciclo do scraper ~2h em dias uteis) |
| Automacao | Sim, fragil (HTML, User-Agent, layout) |
| Historico | Nao no projeto (snapshot do dia) |
| Producao | Aceitavel como secundaria de mercado; nao substitui CVM |

Campos FII lidos: Cotacao, P/VP, Dividend Yield, Liquidez, Vacancia Media,
Valor de Mercado, Qtd de imoveis, Segmento.

### 1.4 StatusInvest (`statusinvest.com.br`)

| Atributo | Valor observado no codigo |
|---|---|
| Uso atual | `buscar_dados_profundos_fii`: JSON de segmento + HTML de vacancia/imoveis/inquilinos |
| Oficialidade | Agregador terciario |
| Identidade | Ticker na URL |
| Formato | JSON (`/fii/portfolio-segment-chart`) e HTML (`/fii/{ticker}`) |
| Frequencia | Intradia no ciclo do scraper |
| Automacao | Sim, muito fragil (CSS `.info`, tabelas, titulos em PT) |
| Historico | Nao |
| Producao | So como enriquecimento fragil; 0 de Papel e valido |

### 1.5 Yahoo Finance / yfinance

| Atributo | Valor observado no codigo |
|---|---|
| Uso atual | `yf.Ticker("{ticker}.SA").info` — preco FII; preco/ROA/VPA/LPA/PEG/marketCap acoes |
| Oficialidade | Agregador de mercado (nao CVM/B3) |
| Identidade | Ticker B3 + sufixo `.SA` |
| Formato | JSON via biblioteca |
| Frequencia | Pregao |
| Automacao | Sim |
| Historico | Disponivel na lib; o projeto so usa snapshot `.info` |
| Producao | Sim para cotacao; nao para dados gerenciais de FII |

### 1.6 Google Sheets (BD_FIIs / BD_Acoes)

| Atributo | Valor observado no codigo |
|---|---|
| Uso atual | Destino do scraper; origem do espelhamento 5C; cache de 5 min (`services/planilhas.py`) |
| Oficialidade | Nenhuma. Intermediario operacional |
| Identidade | Ticker; sem coluna de CNPJ; carimbo sem ano |
| Formato | Planilha (18 colunas FII / 33 acoes) |
| Frequencia | Mesmo ciclo do scraper |
| Automacao | Sim (gspread) |
| Historico | Sobrescreve a linha do ticker; nao e serie oficial |
| Producao | Cache/dashboard. Nunca fonte primaria |

WALT e alavancagem no Sheets continuam `"Pendente de IA"` (`montar_linha_fii`).
O 5C nao persiste placeholder (`_texto_real_fii` -> None).

### 1.7 Demais fontes ja presentes

| Fonte | Papel no codigo | Adequacao como fonte de indicador |
|---|---|---|
| Catalogo (`ativos_catalogo` / `config.MAPA_*`) | Identidade ticker/CNPJ/nome (8.3) | Identidade, nao metrica |
| Groq / `services.llm` | Classificacao de PDF FNET; prompt WALT em `module_fatos` (mock) | Nao e fonte; e extrator nao integrado |
| Google Drive | Arquivo dos PDFs FNET | Armazenamento, nao metrica |
| GitHub Actions | Agenda scraper 5x/dia util | Orquestracao |

Nenhuma API de provedor pago, Funds Explorer, Clube FII, BTG, XP ou CVM
XML complementar alem do INF_MENSAL CSV esta no codigo. Nao serao
integradas nesta etapa.

---

## 2. Matriz de campos FII

Legenda TIPO: bruto | derivado | documental | inexistente.

CAMPO | FONTE ATUAL | MELHOR FONTE | TIPO | CONFIABILIDADE | ATUALIZACAO | IDENTIDADE | AUTOMACAO | STATUS
---|---|---|---|---|---|---|---|---
preco | yfinance (pri) / Fundamentus | B3 via yfinance; Fundamentus B | bruto | alta (mercado) | pregão / 2h | ticker | sim | B
pvp | Fundamentus | Fundamentus B; derivado preco/VPA CVM | bruto | media | 2h | ticker | sim (HTML) | B
dy | Fundamentus | Fundamentus B; FNET Rendimentos A se parseado | bruto | media | 2h | ticker | sim (HTML) | B
liquidez | Fundamentus | Fundamentus / B3 | bruto | media | 2h | ticker | sim (HTML) | B
vpa | derivado preco/pvp no scraper | CVM PL / cotas_emitidas | derivado | media (hoje); alta se CVM | 2h / mensal | ticker / CNPJ | sim | B
lucro_12m | derivado valor_mercado*dy | derivado de fontes B | derivado | baixa | 2h | ticker | sim | C
dividendo_mensal | derivado preco*dy/12 | FNET Aviso de Rendimentos | derivado | baixa | 2h | ticker | sim | C
qtd_imoveis | StatusInvest HTML / Fundamentus | Relatorio Gerencial FNET | bruto | baixa | 2h | ticker | HTML fragil | C
walt | placeholder Sheets (nao persistido) | Relatorio Gerencial FNET (PDF) | documental | n/a | mensal se gerencial | nome/CNPJ no PDF | nao (nao parseado) | D
alavancagem | placeholder Sheets (nao persistido) | Relatorio Gerencial / DFs FNET | documental | n/a | mensal/trimestral | nome/CNPJ no PDF | nao | D
patrimonio_liquido | CVM INF_MENSAL | CVM INF_MENSAL | bruto | alta | mensal | CNPJ | sim | A
ativo_total | CVM INF_MENSAL Valor_Ativo | CVM INF_MENSAL | bruto | alta | mensal | CNPJ | sim | A
disponibilidades_caixa | CVM INF_MENSAL Disponibilidades | CVM INF_MENSAL | bruto | alta | mensal | CNPJ | sim | A
cotistas | CVM INF_MENSAL Total_Numero_Cotistas | CVM INF_MENSAL | bruto | alta | mensal | CNPJ | sim | A
cotas_emitidas | CVM INF_MENSAL Cotas_Emitidas | CVM INF_MENSAL | bruto | alta | mensal | CNPJ | sim | A
rendimento_por_cota | schema vazio | FNET Informe/Rendimentos (nao parseado) | inexistente | n/a | mensal | CNPJ no FNET | nao | D
vacancia_fisica | schema vazio; HTML mistura | Relatorio Gerencial FNET | inexistente | n/a | mensal | PDF | nao | D
vacancia_financeira | schema vazio | Relatorio Gerencial FNET | inexistente | n/a | mensal | PDF | nao | D
receita_imoveis | schema vazio | DFs / gerencial FNET | inexistente | n/a | trimestral | PDF | nao | D
resultado_ligado_venda | schema vazio | DFs / gerencial FNET | inexistente | n/a | trimestral | PDF | nao | D
despesas_taxas | schema vazio (CSV tem % taxa, nao R$) | CVM percentual (parcial) / DFs | inexistente no ORM | baixa | mensal | CNPJ | parcial | D
setor | StatusInvest JSON/HTML | StatusInvest (nao ha CVM de segmento) | bruto | media | 2h | ticker | JSON razoavel | B
tipo_fii | derivado do setor | derivado | derivado | media | 2h | ticker | sim | B
inquilinos | StatusInvest HTML top-3 | Relatorio Gerencial FNET | bruto | baixa | 2h | ticker | HTML fragil | C
documentos | FNET/B3 | FNET/B3 | documental | alta (arquivo) | diario/evento | nome + 8.3 | sim (arquivo) | A
vacancia (Sheets) | StatusInvest/Fundamentus misturada | nenhuma fiel no ORM | bruto ambiguo | baixa | 2h | ticker | HTML | C (nao mapeada)
numero_cotas (Sheets) | derivado valor_mercado/preco | CVM cotas_emitidas (ja A noutro campo) | derivado erroneo | baixa | 2h | ticker | sim | D
valor_mercado (Sheets) | Fundamentus rotulado PL Total | derivado preco * cotas_emitidas CVM | bruto mal rotulado | media | 2h | ticker | sim | B (como market cap; nunca como PL)
preco acao | yfinance / Fundamentus | yfinance B | bruto | alta | 2h | ticker | sim | B
indicadores acao (P/L, ROE, margens) | Fundamentus | Fundamentus B; CVM ITR para contas | bruto | media | 2h | ticker | HTML | B
contabil acao (PL, receita, divida) | CVM ITR | CVM ITR/DFP | bruto | alta | trimestral | CNPJ | sim | A
div_liq_ebit | Sheets duplica Div.Liq/Patrim; 5C NULL | Fundamentus se coluna distinta | inexistente util | n/a | — | ticker | — | D
roa acao | yfinance | yfinance B | bruto | media | 2h | ticker | sim | B

---

## 3. Melhores fontes por indicador (lacunas 8.6)

### 3.1 Ja resolvidos com fonte A (manter, nao reimplementar)

- patrimonio_liquido, ativo_total, disponibilidades_caixa, cotistas, cotas_emitidas: CVM INF_MENSAL.
- documentos FII: FNET/B3 (arquivo, nao metrica).
- contabil acao: CVM ITR.

### 3.2 Mercado: secundaria B, sem fonte B3 estruturada no codigo

- preco: yfinance (melhor do stack); Fundamentus fallback.
- pvp, dy, liquidez: Fundamentus.
- vpa: hoje derivado preco/pvp; melhor futuro = PL CVM / cotas_emitidas (ainda nao implementado).
- valor_mercado: Fundamentus ou derivado preco * cotas_emitidas CVM. Nunca usar a coluna Sheets "PL Total" como patrimonio.

### 3.3 Fragis C (existem no HTML, nao oficiais)

- qtd_imoveis: StatusInvest/Fundamentus; 0 de FII de Papel e valido.
- inquilinos: StatusInvest top-3; sentinela nao gera registro.
- vacancia (coluna Sheets): mistura fisica/financeira; sem destino ORM.
- setor/tipo_fii: StatusInvest + heuristica `classificar_fii_e_emoji`.

### 3.4 Sem fonte adequada D

Nenhuma fonte **estruturada e ja integrada** preenche:

- WALT
- alavancagem
- vacancia_fisica
- vacancia_financeira
- rendimento_por_cota
- receita_imoveis
- resultado_ligado_venda
- despesas_taxas (valor R$ do schema)
- numero_cotas da planilha (estimativa; o oficial e cotas_emitidas CVM)

A fonte documental candidata e o Relatorio Gerencial / DFs no FNET. Isso
nao a torna adequada: o projeto so baixa o PDF. Extração por LLM
(`module_fatos`) nao esta ligada a persistencia e usa documento mock.

---

## 4. Campos sem fonte adequada (D)

1. walt — placeholder de IA; gerencial FNET nao parseado.
2. alavancagem — idem.
3. vacancia_fisica — INF_MENSAL CSV nao traz; HTML do StatusInvest nao distingue.
4. vacancia_financeira — idem.
5. rendimento_por_cota — schema oco.
6. receita_imoveis — schema oco.
7. resultado_ligado_venda — schema oco.
8. despesas_taxas em R$ — percentual CVM nao equivale ao ORM.
9. numero_cotas (Sheets) — nao equivale a cotas_emitidas.
10. div_liq_ebit (acoes) — coluna Sheets duplicada; 5C persiste NULL.

---

## 5. Riscos

1. Tratar Sheets como primaria mascara CVM/FNET e inventa identidade (sem CNPJ, carimbo sem ano).
2. HTML Fundamentus/StatusInvest quebra com layout; risco de parsing alto.
3. Vacancia Media do Fundamentus nao e fisica nem financeira; persistir seria semantica falsa (8.5).
4. numero_cotas = market cap / preco nao e cotas_emitidas CVM.
5. "PL Total" do Sheets e valor de mercado; PL real e CVM.
6. WALT/alavancagem via LLM em PDF: alucinacao, N/D vs ausencia, sem unidade canonica.
7. Matching FNET por nome (ultimo recurso 8.3) pode associar documento ao fundo errado da mesma familia.
8. INF_MENSAL so roda sob comando; SLA contabil FII 45d pode ir a STALE sem `/forcar_fiis`.
9. Derivados (vpa, lucro_12m, dividendo_mensal) herdam erro das bases B/C.
10. Integrar agregador novo (Funds Explorer etc.) violaria o escopo e repetiria fragilidade C.

---

## 6. Recomendacoes (nao implementar agora)

1. Manter CVM INF_MENSAL como unica primaria dos campos A.
2. Manter yfinance+Fundamentus como B de mercado; Sheets so como cache.
3. Nao criar fonte de WALT/alavancagem/vacancia a partir de HTML de agregador.
4. Se no futuro houver preenchimento das lacunas D, a ordem e: (1) inventariar XML/CSV CVM alem do INF_MENSAL ja lido; (2) so entao parse estruturado de Relatorio Gerencial FNET; (3) LLM so com validacao 8.2/8.5 (zero/NULL/N/A/INVALID) e nunca como primaria.
5. Distinguir cotas_emitidas (CVM, A) de numero_cotas (Sheets, D).
6. Distinguir patrimonio_liquido (CVM, A) de valor_mercado (Fundamentus/derivado, B).
7. Vacancia so entra no ORM quando a fonte separar fisica e financeira.
8. qtd_imoveis e inquilinos podem permanecer C, explicitamente frageis na cobertura 8.6.
9. Nao expandir universo, ETF/cripto, Telegram, website, alertas ou Content Engine para "resolver" lacuna de fonte.

---

## 7. O que deve ser implementado depois (fora desta etapa)

Esta etapa nao implementa nada abaixo.

1. Inventario pontual de outros arquivos CVM FII (se existirem no mesmo portal) antes de scraper novo.
2. Pipeline documental FNET: tipo Relatorio Gerencial -> extracao controlada, nao placeholder.
3. Reativar coleta INF_MENSAL no ciclo (hoje so `/forcar_fiis`) para freshness 8.4.
4. VPA oficial = patrimonio_liquido / cotas_emitidas, marcado DERIVADO.
5. valor_mercado persistido so como derivado preco * cotas, nunca como PL.
6. Politica explicita: campo D permanece NULL/FONTE_INEXISTENTE ate existir fonte A ou B.

Fora de escopo permanente desta fase: ETF, cripto, Telegram novo, website,
novos alertas, Content Engine, provedores externos nao presentes no codigo.

---

## 8. Validacao de escopo

Nao feito nesta etapa:

- coletores novos
- scrapers novos
- APIs externas novas
- alteracao de banco
- Telegram / website / alertas
- expansao de universo
- ETF/cripto
- fontes novas de WALT/alavancagem
- implementacao das recomendacoes

Preservado: cobertura FII 8.6, INF_MENSAL 8.6, zero/NULL/N/A/INVALID 8.2 e 8.5,
identidade/CNPJ 8.3, freshness 8.4, Sheets como intermediario.

Unico artefato: este documento.

---

## 9. Veredito

8.7 CONCLUIDA
