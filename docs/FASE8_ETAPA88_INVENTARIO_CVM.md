# Fase 8 — Etapa 8.8: Inventario de Fontes Oficiais CVM

Documento de auditoria (somente analise). Nao altera codigo, nao cria coletores,
nao cria parser FNET, nao altera banco, API, Telegram, website, alertas nem
universo. Data: 2026-09-05. Commit base: `c9c8409`. Etapas 8.6 e 8.7 CONCLUIDAS.

Classificacao:

- A = fonte oficial estruturada adequada
- B = fonte oficial, mas exige tratamento/documento
- C = fonte oficial parcial/limitada
- D = nao existe fonte CVM adequada identificada

Ausencia permanece ausencia. Campo CVM que nao equivale semanticamente ao ORM
nao e promovido a A.

Evidencia: dicionarios oficiais CVM
(`meta_inf_mensal_fii.zip`, `meta_inf_trimestral_fii.zip`,
`meta_inf_anual_fii.zip`, `meta_dfin_fii.txt`) e listagem do ZIP
`inf_trimestral_fii_2026.zip` em 2026-09-05. Codigo atual:
`pipeline_dados/coletor_fiis.py`, `coletor_cvm.py`, `coletor_docs_acoes.py`.

---

## 1. FONTES CVM ENCONTRADAS

Repositorio: `https://dados.cvm.gov.br/dados/`. Identidade FII e sempre
`CNPJ_Fundo_Classe` (alias legado `CNPJ_Fundo`). Ticker nao vem da CVM;
o projeto resolve via catalogo 8.3. Formato: ZIP/CSV `;` latin1, HTTP GET
sem login, atualizacao semanal no portal, historico anual.

### 1.1 FII — ja no codigo (uso parcial)

**INF_MENSAL** — `https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip`

Anexo 39-I ICVM 571/2015. Tres CSVs no ZIP: `geral`, `complemento`,
`ativo_passivo`. O coletor le todos os CSVs, mas so persiste cinco metricas.

Usado hoje: `Patrimonio_Liquido`, `Valor_Ativo`, `Disponibilidades`,
`Total_Numero_Cotistas`, `Cotas_Emitidas` / `Quantidade_Cotas_Emitidas`.

Presente no mesmo ZIP e nao mapeado: `Valor_Patrimonial_Cotas`,
`Percentual_Dividend_Yield_Mes`, `Percentual_Despesas_Taxa_Administracao`,
`Percentual_Despesas_Agente_Custodiante`, `Taxa_Administracao_Pagar`,
`Taxa_Performance_Pagar`, `Rendimentos_Distribuir`, `Segmento_Atuacao`,
`Codigo_ISIN`, `Total_Passivo`, `Obrigacoes_Aquisicao_Imoveis`,
`Contas_Receber_Aluguel`, composicao de imoveis/CRI/LCI.

Periodicidade: mensal. Automacao: sim (hoje so `/forcar_fiis`).

### 1.2 FII — no portal, ausente do codigo

**INF_TRIMESTRAL** — `https://dados.cvm.gov.br/dados/FII/DOC/INF_TRIMESTRAL/DADOS/inf_trimestral_fii_{ano}.zip`

Anexo 39-II. 16 CSVs estruturados (2026 verificado). Principal candidato
a cobrir lacunas 8.6/8.7 sem PDF.

Arquivos relevantes:

- `imovel`: `Percentual_Vacancia`, `Percentual_Locado`, `Percentual_Inadimplencia`, `Percentual_Receitas_FII` (por imovel)
- `resultado_contabil_financeiro`: receitas de aluguel, taxas adm/performance em R$, vendas, rendimentos declarados (versoes Contabil e Financeiro)
- `complemento`: faixas de vencimento da receita (`Percentual_Vencimento_Receita_FII_Faixa_*`) — nao e WALT
- `imovel_renda_acabado_inquilino`: concentracao por imovel/setor, sem nome do inquilino
- `geral`: `Quantidade_Cotas_Emitidas`, `Segmento_Atuacao`, `Codigo_ISIN`

Periodicidade: trimestral. Identidade: CNPJ. Automacao: sim (mesmo padrao do mensal). Nao integrado.

**INF_ANUAL** — `https://dados.cvm.gov.br/dados/FII/DOC/INF_ANUAL/DADOS/inf_anual_fii_{ano}.zip`

Anexo 39-V. Cadastro, prestadores, processos, distribuicao de cotistas.
`Percentual_Patrimonio_Valor_Mercado` e % do patrimonio a valor de mercado
(ativo), nao market cap da cota. Nao cobre as lacunas prioritarias.

**DFIN** — `https://dados.cvm.gov.br/dados/FII/DOC/DFIN/DADOS/dfin_fii_{ano}.csv`

Demonstracoes Financeiras. Colunas: CNPJ, datas, `Link_Download`, parecer.
E indice documental (PDF), nao metricas. Equivale a FNET DFs, nao substitui
parser. Tipo: documental.

**FIE Medidas / ADM_FII cadastro**: PL/cotistas agregados ou cadastro de
administrador. Redundante ou fora do ativo.

Nao existe no portal CVM aberto: WALT, alavancagem nominada, vacancia fisica
e financeira como campos distintos, preco de mercado, valor de mercado da cota.

### 1.3 Acoes — ja no codigo

**ITR** — `https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{ano}.zip`

Usado: BPA/BPP/DRE/DFC_MI **consolidado** (`*_con_*`). Contas via
`config.MAPA_CONTAS_CVM` (subconjunto). Identidade: CNPJ + `MAPA_CNPJ_B3`.
Trimestral. Integrado em `AcoesCVMReader`.

**IPE** — `https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip`

Indice de documentos (Fato Relevante, DFs, FRE...). Link para PDF.
Integrado em `coletor_docs_acoes.py`. Nao e metrica.

### 1.4 Acoes — no portal, ausente ou subutilizado

**DFP** — `https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/`

Mesma estrutura de contas do ITR, exercicio anual. Nao ha URL/coleta no codigo.
O bot ja rotula dezembro como DFP, mas o coletor so grava `tipo_doc='ITR'`.

Nao lidos no ITR: arquivos individuais (`*_ind_*`) e outras pecas do ZIP
(DVA, DMPL etc.). FRE, FCA, CGVN, VLMO, cadastro de cias: cadastrais/governanca,
nao preenchem lacunas FII.

---

## 2. MATRIZ

CAMPO | FONTE CVM | ARQUIVO/ENDPOINT | TIPO | PERIODICIDADE | IDENTIDADE | AUTOMACAO | CONFIABILIDADE | STATUS
---|---|---|---|---|---|---|---|---
patrimonio_liquido | INF_MENSAL (ja integrado) | inf_mensal_fii_{ano}.zip complemento Patrimonio_Liquido | estruturado | mensal | CNPJ | sim | alta | A
ativo_total | INF_MENSAL (ja integrado) | Valor_Ativo | estruturado | mensal | CNPJ | sim | alta | A
disponibilidades_caixa | INF_MENSAL (ja integrado) | ativo_passivo Disponibilidades | estruturado | mensal | CNPJ | sim | alta | A
cotistas | INF_MENSAL (ja integrado) | Total_Numero_Cotistas | estruturado | mensal | CNPJ | sim | alta | A
cotas_emitidas / numero_cotas oficial | INF_MENSAL (ja integrado); tambem INF_TRIM/ANUAL geral | Cotas_Emitidas / Quantidade_Cotas_Emitidas | estruturado | mensal | CNPJ | sim | alta | A
vpa | INF_MENSAL nao mapeado | complemento Valor_Patrimonial_Cotas | estruturado | mensal | CNPJ | sim | alta | A
rendimento_por_cota | INF_MENSAL DY% / Rendimentos_Distribuir; INF_TRIM Rendimentos_Declarados | complemento + resultado_contabil_financeiro | estruturado parcial | mensal/trimestral | CNPJ | sim | media | C
despesas_taxas (R$ do ORM) | INF_TRIM Taxa_Administracao_Contabil/Financeiro | resultado_contabil_financeiro | estruturado | trimestral | CNPJ | sim | alta | A
despesas_taxas (% PL) | INF_MENSAL nao mapeado | Percentual_Despesas_Taxa_Administracao | estruturado (unidade distinta do ORM) | mensal | CNPJ | sim | alta como % | C
receita_imoveis | INF_TRIM Receita_Aluguel_Investimento_Contabil ou Financeiro | resultado_contabil_financeiro | estruturado | trimestral | CNPJ | sim | alta | A
resultado_ligado_venda | INF_TRIM Receita_Venda_* / Resultado_Liquido_Estoque_* / Resultado_Venda_TVM_* | resultado_contabil_financeiro | estruturado (multiplas contas) | trimestral | CNPJ | sim | alta apos mapeamento | B
vacancia (generica por imovel) | INF_TRIM Percentual_Vacancia | imovel.csv | estruturado por imovel | trimestral | CNPJ | sim | media (sem tipo fisico/financeiro) | C
vacancia_fisica | nenhuma coluna com esse nome | — | — | — | — | — | — | D
vacancia_financeira | nenhuma coluna com esse nome | — | — | — | — | — | — | D
walt | nenhuma; so faixas de vencimento de receita | INF_TRIM complemento Percentual_Vencimento_Receita_FII_Faixa_* | estruturado (nao e WALT) | trimestral | CNPJ | sim | n/a como WALT | D
alavancagem | nenhuma razao nomeada; passivo existe | INF_MENSAL Total_Passivo / Obrigacoes_Aquisicao_Imoveis | estruturado (nao e o indicador gerencial) | mensal | CNPJ | sim | n/a como alavancagem | D
valor_mercado (market cap) | nao existe | INF_ANUAL Percentual_Patrimonio_Valor_Mercado e outro conceito | — | — | — | — | — | D
setor / Segmento_Atuacao | INF_MENSAL/TRIM/ANUAL geral | Segmento_Atuacao | estruturado | mensal | CNPJ | sim | alta | A
inquilinos (nome) | INF_TRIM inquilino sem nome de locatario | imovel_renda_acabado_inquilino | estruturado parcial | trimestral | CNPJ | sim | baixa p/ nome | C
preco | nao e CVM | — | — | — | — | — | — | D
contabil acao (PL, receita, divida, etc.) | ITR consolidado (ja integrado) | itr_cia_aberta_{ano}.zip BPA/BPP/DRE/DFC_MI_con | estruturado | trimestral | CNPJ | sim | alta | A
contabil acao anual | DFP (nao integrado) | CIA_ABERTA/DOC/DFP | estruturado | anual | CNPJ | sim | alta | A
documentos acao | IPE (ja integrado) | ipe_cia_aberta_{ano}.zip | documental | evento | CNPJ | sim | alta (arquivo) | B
DFs FII | DFIN Link_Download | dfin_fii_{ano}.csv | documental | periodico | CNPJ | sim (download) | alta (arquivo, nao metrica) | B

---

## 3. CAMPOS QUE PODEM SER COBERTOS PELA CVM

Sem PDF/LLM, com CSV oficial (integracao futura, nao nesta etapa):

Ja cobertos e integrados (manter):

- patrimonio_liquido, ativo_total, disponibilidades_caixa, cotistas, cotas_emitidas
- contabil de acoes via ITR consolidado

Cobertura nova possivel (fonte A/B, ainda sem coletor):

1. **vpa** = `Valor_Patrimonial_Cotas` (INF_MENSAL complemento) — ja no ZIP lido hoje.
2. **despesas_taxas** em R$ = `Taxa_Administracao_Contabil` ou `Taxa_Administracao_Financeiro` (INF_TRIMESTRAL). Escolher uma visao e nao misturar.
3. **receita_imoveis** = `Receita_Aluguel_Investimento_Contabil` ou `_Financeiro` (INF_TRIMESTRAL).
4. **resultado_ligado_venda** = contas de venda de estoque/investimento/TVM no mesmo CSV, apos mapa 1:1 (B).
5. **numero_cotas** oficial = `cotas_emitidas` CVM (ja A). A coluna Sheets permanece estimativa e nao deve ser preenchida pela CVM com outro significado.
6. **setor** = `Segmento_Atuacao` (substitui StatusInvest se houver integracao).
7. **DFP acoes** = mesmo mapa de contas do ITR, `tipo_doc='DFP'`.

Cobertura apenas parcial (C), nao promove o campo do schema:

- rendimento_por_cota: DY mensal (%) ou total a distribuir / cotas — nao e o campo R$/cota sem regra explicita.
- vacancia: `Percentual_Vacancia` por imovel exige agregacao ponderada; nao distingue fisica/financeira (8.5).
- despesas_taxas mensal: so percentual sobre PL.

---

## 4. CAMPOS QUE CONTINUAM SEM FONTE ADEQUADA

Continuam D na CVM (FNET/gerencial ou mercado, nao inventar):

1. **walt** — faixas de vencimento nao sao prazo medio de contratos.
2. **alavancagem** — nao ha razao divida/PL gerencial; passivo contabil e outro indicador.
3. **vacancia_fisica** — coluna unica `Percentual_Vacancia`, sem rotulo fisico.
4. **vacancia_financeira** — inexistente.
5. **valor_mercado** (market cap da cota) — preco * cotas e mercado/B3, nao CVM.
6. **preco** — nao e dado CVM.
7. **inquilinos nominais** — CSV trimestral nao traz o nome do locatario.

DFIN/IPE/FNET continuam documentais. Nao preenchem WALT/alavancagem/vacancias
distintas sem parser de PDF.

---

## 5. FONTES CVM EXISTENTES NO CODIGO MAS SUBUTILIZADAS

1. **INF_MENSAL ZIP inteiro** — `coletor_fiis.py` itera todos os CSVs e descarta
   `Valor_Patrimonial_Cotas`, DY%, taxas %, passivo, segmento, ISIN.
2. **INF_MENSAL so via `/forcar_fiis`** — nao entra no ciclo; SLA 45d pode STALE.
3. **ITR so consolidado** — `*_ind_*` e pecas extra do ZIP ignoradas.
4. **MAPA_CONTAS_CVM restrito** — contas CVM extras no ITR nao mapeadas.
5. **tipo_doc DFP** — schema e UI preveem DFP; coletor nunca baixa
   `CIA_ABERTA/DOC/DFP`.

Nao subutilizadas: estao **ausentes** do codigo (nao ha coletor):

- INF_TRIMESTRAL (maior lacuna estruturada)
- INF_ANUAL
- DFIN (indice de PDF)

Nao tratar IPE/FNET como fonte estruturada subutilizada: ja cumprem papel
documental.

---

## 6. RECOMENDACAO DA PROXIMA ETAPA

Nao implementar agora.

Ordem, se houver etapa seguinte de coleta CVM (antes de parser FNET):

1. Inventariar/mapear **INF_TRIMESTRAL** `resultado_contabil_financeiro` e
   `imovel` campo a campo contra o ORM (sem persistir).
2. Ampliar o mapa do **INF_MENSAL** ja baixado: `Valor_Patrimonial_Cotas`
   como VPA bruto CVM (nao derivado preco/pvp).
3. So depois: coletor INF_TRIMESTRAL para receita_imoveis, despesas_taxas R$,
   resultado de venda — com escolha explicita Contabil vs Financeiro e
   regras 8.2/8.5 (zero=zero, ausencia=NULL).
4. Nao mapear `Percentual_Vacancia` em `vacancia_fisica` nem
   `vacancia_financeira`.
5. Nao derivar WALT das faixas de vencimento nem alavancagem de Total_Passivo.
6. valor_mercado permanece mercado (preco * cotas_emitidas), marcado DERIVADO.
7. DFP acoes e opcional e independente das lacunas FII.
8. Parser FNET so para o que continuar D apos o mapear CVM: WALT,
   alavancagem gerencial, vacancias distintas, nomes de inquilinos.

Fora de escopo permanente desta fase: ETF, cripto, Telegram, website,
alertas novos, expansao de universo, agregadores, LLM como primaria.

---

## 7. Validacao de escopo

Unico artefato: este documento. Nenhuma alteracao funcional.

8.8 CONCLUIDA
