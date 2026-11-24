# Inventário de dados para valuation da Carteira Consolidada

> Documento de planejamento. Não cria coletor, workflow, agenda, tabela ou chamada adicional no Robô Financeiro.

## Objetivo e limite deste PR

A Carteira Consolidada deve mostrar análises de valor justo e preço-teto com transparência: cada número exibido precisa informar período, fonte, unidade, abrangência (consolidado/individual) e data de atualização.

O vídeo e as imagens de referência do WARD/Geração Dividendo orientam a experiência desejada — premissas editáveis, cenários, projeções, margem de segurança e comparação com cotação. Eles **não** definem automaticamente a fórmula final nem autorizam copiar interface ou dados de terceiros.

Este PR somente mapeia o estado atual e organiza a próxima conversa técnica. O comportamento atual do robô permanece exatamente igual.

## Dados já disponíveis no Robô

| Classe | Dados atuais para consulta | Série diária disponível |
|---|---|---|
| Ações brasileiras | cotação, DY, P/L, P/VP, ROE, VPA, LPA, setor e subsetor | preço e indicadores de snapshots de fim de dia, quando coletados |
| FIIs | cotação, P/VP, DY, VPA, dividendo mensal, setor/tipo, liquidez e alguns indicadores operacionais | preço e indicadores de snapshots de fim de dia, quando coletados |
| ETFs, BDRs, cripto, moedas, índices e commodities | cotação/referência, DY/PVP/PL/ROE quando aplicável, volatilidade 30d, liquidez 30d e distância da máxima de 52 semanas | observações históricas de instrumentos internacionais, quando coletadas |
| Mercado/macroeconomia | resumo de mercado já exposto pela API | não é, por si só, uma base de valuation |

### Campos já preservados nos snapshots

- **Ações:** preço, DY, P/L, P/VP, P/Ativo, margens, P/EBIT, EV/EBIT, dívida líquida/patrimônio, PSR, indicadores de capital de giro/liquidez, ROE, ROA, ROIC, CAGR de receita, liquidez média, VPA, LPA, PEG e valor de mercado.
- **FIIs:** preço, P/VP, DY, quantidade de imóveis, liquidez, VPA, lucro em 12 meses e dividendo mensal.

A existência do campo não substitui validação por data, origem e consistência. O painel deve mostrar `N/D` quando o dado necessário não estiver disponível ou for incompatível com o período.

## Métodos desejados e cobertura atual

| Método | Situação hoje | Dados que ainda faltam ou precisam de histórico validado |
|---|---|---|
| Graham | Pode funcionar para ações com LPA e VPA numéricos | normalização de LPA/VPA por período; regra para resultados negativos e dados não recorrentes |
| Bazin | Não pronto para cálculo histórico confiável | DPA por evento/período, série de dividendos, ajustes por desdobramentos e política de distribuição |
| Preço-teto por dividendos | FII possui uma estimativa simples baseada no último rendimento mensal | DPA/DY histórico, payout, projeção de lucro e indicação clara de que não é recomendação |
| Lucro projetado / fluxo de lucros descontados | Não pronto | lucro líquido trimestral/anual histórico, crescimento, payout, taxa de desconto, ações totais e em tesouraria, lucro por ação diluído |
| DCF FCFF | Não pronto | EBIT, impostos, D&A, CAPEX, variação de capital de giro, dívida líquida/caixa, WACC, crescimento terminal e número de ações |
| DCF FCFE | Não pronto | fluxo de caixa operacional, CAPEX, captação/amortização de dívida, custo de capital próprio e ações diluídas |
| Gordon / Dividend Discount Model | Não pronto | DPA histórico, payout sustentável, crescimento, taxa de desconto e tratamento de empresas sem dividendos |
| Lucro residual | Não pronto | patrimônio líquido por ação, ROE projetado, custo de capital próprio e reconciliação de patrimônio |
| Peter Lynch / PEG | Parcial: há P/L e PEG pontual em alguns snapshots | crescimento de LPA normalizado em 3–5 anos ou projeção documentada; fórmula e limites devem ser aprovados antes |
| Múltiplos e pares | Parcial: múltiplos isolados | setor comparável, universo de pares, período uniforme, exclusões e estatísticas de mediana/quartis |
| FIIs de renda | Parcial: último dividendo, P/VP e dados de mercado | série mensal de rendimentos, resultado caixa/competência, reservas, inflação/índices e concentração |
| FIIs de tijolo | Não pronto para valuation | vacância física/financeira, WALT, contratos, revisões, área, imóveis, concentração, dívida e despesas recorrentes |
| FIIs de papel/CRI | Não pronto para valuation | carteira por CRI, indexador, prazo, concentração, LTV, inadimplência, pré-pagamentos, garantias e hedge |
| ETFs, BDRs, cripto, moedas, índices e commodities | Não devem herdar fórmulas de ação brasileira | modelo próprio por classe; há preço e série, mas não demonstrações financeiras do ativo subjacente |

## Melhor fonte e forma de busca

1. **Ações brasileiras — base oficial estruturada primeiro.** Usar DFP anual e ITR trimestral da CVM para fatos contábeis; ambos são conjuntos oficiais de demonstrações periódicas. A CVM disponibiliza ITR dos últimos cinco anos. Formulário de Referência, IPE e Relações com Investidores complementam ações, tesouraria, dividendos e eventos corporativos.
2. **FIIs — dados estruturados e documentos oficiais.** Usar informes estruturados/arquivos da CVM e FNET para fatos mensuráveis; os relatórios gerenciais já coletados devem ser prova complementar, não única fonte numérica. O informe trimestral estruturado foi padronizado pela CVM.
3. **Cotações e métricas de mercado.** Manter os provedores atuais para preço e liquidez, com data da cotação. Eles não devem ser a única origem de demonstrações auditadas.
4. **Instrumentos internacionais.** Para ETFs, BDRs, cripto, moedas, índices e commodities, separar o modelo por classe. Não tentar preencher lacunas fundamentais com dados de uma ação brasileira.

## Arquitetura proposta para implementação posterior

### Camada 1 — fatos brutos normalizados

Criar uma base de fatos fundamentais com, no mínimo:

- identificador do emissor/fundo e ticker;
- período de referência e data de publicação;
- escopo consolidado/individual;
- unidade e moeda;
- item contábil canônico;
- valor, fonte, URL/identificador do documento, data de coleta e nível de confiança.

Dados brutos não devem ser sobrescritos por cálculo do painel.

### Camada 2 — indicadores derivados

Calcular LPA, VPA, payout, crescimento, fluxo de caixa e métricas de FII a partir da camada bruta, guardando a regra e a versão do cálculo.

### Camada 3 — valuation por premissas

Salvar resultados em cache por:

`ativo + método + cenário + versão das premissas + período dos dados`.

A interface pode permitir cenário conservador, base e otimista, mas deve destacar premissas editadas pelo usuário e não confundi-las com fato observado.

## Proteção contra sobrecarga

- Não baixar todo o histórico de todos os ativos de uma vez.
- Atualizar somente quando surgir nova competência publicada, usando `CNPJ + período + versão` como chave de idempotência.
- Fazer carga inicial limitada aos favoritos/carteira e, depois, lotes pequenos com fila, pausa e limite de tempo já adotados pelo robô.
- Separar a coleta de fundamentos do fluxo noturno de preços; falha de uma não pode bloquear a outra.
- Reutilizar documentos já arquivados quando houver identificador e período compatíveis.
- Registrar contagem, ativos, período, origem e erro resumido no histórico operacional; não enviar mensagens longas ao Telegram para cada linha.

## Ordem segura para a próxima conversa do Robô Financeiro

1. Aprovar fórmulas, premissas padrão, unidades e regras de indisponibilidade para cada método.
2. Implementar somente a base estruturada de ações (DFP/ITR) e testar com poucos ativos representativos.
3. Validar reconciliação entre números brutos, LPA/VPA, ações diluídas e tela.
4. Liberar Graham, Bazin, lucro projetado e DCF para ações quando a cobertura estiver completa.
5. Criar a camada específica de FIIs, começando por rendimentos históricos e depois tijolo/papel.
6. Tratar ETFs, BDRs, cripto, moedas, índices, commodities e Tesouro por modelos próprios.

## Contrato futuro de API

Somente após a coleta validada, expor endpoints de leitura como:

- `GET /api/v1/assets/{ticker}/fundamentals`
- `GET /api/v1/assets/{ticker}/valuations?method=graham&scenario=base`
- `GET /api/v1/assets/{ticker}/coverage`

Cada resposta deve informar campos ausentes, período mais recente, fonte e data de atualização. A Carteira nunca deve inventar série histórica ou valor justo.

## Critérios de aceite

- Cada número do valuation possui fonte, período e unidade visíveis.
- Método incompleto fica marcado como indisponível, e não como valor calculado.
- Cenários têm premissas explícitas e persistidas.
- Há testes com empresas lucrativas, prejuízo, banco, empresa cíclica, FII de tijolo e FII de papel.
- Nenhum coletor novo é acionado pelo acesso normal ao site.
- O produto exibe aviso educacional: análise informativa, não recomendação de investimento.

## Referências

- Vídeo de referência enviado pelo usuário: https://youtu.be/7wOGP2bklNc
- Dados abertos CVM — DFP: https://dados.cvm.gov.br/dataset/cia_aberta-doc-dfp
- Dados abertos CVM — ITR: https://dados.cvm.gov.br/dataset/cia_aberta-doc-itr

