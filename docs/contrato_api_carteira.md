# Contrato Robô Financeiro → Carteira Consolidada

Este contrato permite que a Carteira consuma dados de mercado sem acessar o
Neon, o Google Drive ou credenciais do Robô diretamente. Todos os endpoints são
somente leitura e exigem o token Supabase do usuário da Carteira em
`Authorization: Bearer <token>`.

## Endpoints

- `GET /api/v1/assets/{ticker}?asset_type=stock|fii|etf|bdr|crypto|currency`
- `GET /api/v1/assets/{ticker}/history?asset_type=...&days=30`
- `GET /api/v1/assets/{ticker}/income?asset_type=...&days=30`
- `GET /api/v1/assets/{ticker}/corporate-events?asset_type=...&days=30`
- `GET /api/v1/assets/{ticker}/performance?asset_type=...&days=30`
- `GET /api/v1/market/overview`

O período aceito vai de 7 a 730 dias. A Carteira pode usar 30, 120 ou outro
valor sem alterar o Robô. Ausência de dado é retornada como ausência, nunca
como zero inventado.

## Gráficos recomendados na Carteira

1. Gráfico de patrimônio: quantidade diária × preço retornado por `history`.
2. Aportes e retiradas: usar exclusivamente as transações da própria Carteira.
3. Proventos: quantidade elegível na data-ex × `amount_per_unit` de `income`.
4. Eventos: ajustar quantidades históricas pelo `factor` após confirmação da
   natureza do evento.
5. Rentabilidade simples do ativo: pode exibir diretamente `performance`.
6. Rentabilidade da carteira: calcular na Carteira por TWR e XIRR, pois apenas
   ela conhece datas de compras, vendas, aportes, retiradas, custos e impostos.

`simple_total_return_percent` representa uma unidade mantida no período, sem
reinvestimento, impostos ou corretagem. Não deve ser apresentado como retorno
personalizado do investidor.

## Qualidade e origem

Cada provento e evento traz `source` e `source_quality`. A primeira versão usa
Yahoo Finance como fonte complementar e a classificação conservadora
`DISTRIBUICAO`, pois essa fonte não separa de forma fiscalmente confiável JCP,
dividendo e rendimento de FII. Uma fonte oficial pode refinar os registros no
futuro sem quebrar o formato da API.

## Persistência

O Robô grava primeiro nas abas `BD_Proventos` e
`BD_Eventos_Corporativos`; somente depois confirma a mesma informação no Neon.
A coleta usa lote rotativo e janela curta sobreposta, sem carregar anos de
histórico.
