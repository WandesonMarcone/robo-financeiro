# Especificação de integração — catálogo e logos da Carteira Consolidada

**Status:** proposta para implementação; não representa endpoints implantados.
**Dependência:** [Carteira Consolidada PR #1](https://github.com/WandesonMarcone/carteira-consolidada/pull/1) e [contrato do consumidor](https://github.com/WandesonMarcone/carteira-consolidada/blob/feat/painel-investidor-metodologias/docs/contrato_catalogo.md).
**Escopo:** navegação Mercado → classe → setor → ativo → ficha → adicionar à carteira ou abrir metodologias. Pesquisa por ticker/nome é opcional. A Carteira não lê Neon, Drive ou segredos diretamente.

## 1. Diagnóstico no código atual

- `services/portfolio_api.py` tem detalhe, history, income, corporate-events, performance, fundamentals, coverage e market/overview, mas não possui GET /api/v1/assets (coleção). Detalhe não fornece name nem logo_url; classification já fornece setor/subsetor conforme a classe.
- `services/planilhas.py`: buscar_dados_planilha_com_cache e buscar_ativo_na_planilha já usam BD_Acoes e BD_FIIs. Não chamar buscar_ativo_na_planilha individualmente para cada linha.
- `pipeline_dados/repositorio_catalogo.py` e `services/catalogo_empresas.py`: vínculo empresa/ticker e taxonomia oficial CVM/B3 existente. Utilizar nomes comerciais/oficiais e classificação validada, sem inferir CNPJ ou setor.
- `services/coletor_etfs_bdrs.py`: listar_instrumentos_menu aceita ETF/BDR e consulta instrumentos_internacionais e última observação; detalhe_instrumento_menu já consulta nome, índice, gestora e referência. Reutilizar a base também para CRIPTO. MOEDA/INDICE/COMMODITY pertencem à visão de mercado e não devem ser apresentadas como posições negociáveis sem suporte do consumidor.
- `services/logo_service.py`: Drive Ícones B3 primeiro, fallback Logo.dev quando não FII, grava no Drive e usa cache positivo/negativo. obter_media_logo_rapida pode retornar file_id Telegram; não é URL web. `pipeline_dados/repositorio_logos.py` persiste file_id do Telegram, não imagem web.
- `fixed_income` é opção da Carteira, mas não há classe equivalente de catálogo genérico no contrato atual. Tesouro/indicadores existentes não equivalem a catálogo completo de renda fixa.

## 2. Contrato compatível com o frontend

`GET /api/v1/assets?asset_type=stock|fii|etf|bdr|crypto|fixed_income&page=1&page_size=24&q=&sector=`

- Bearer Supabase usando requires_portfolio_user e CORS existente. Não aceitar token em query string.
- Classe obrigatória; paginação estável por ticker (desempate determinístico), page >= 1, page_size 1..100 (default 24); parâmetros inválidos retornam 400. q opcional (nome/ticker, sem distinguir maiúsculas; tolerância a acento quando possível), limitar tamanho a 100; sector opcional, valores oficiais. Parâmetro futuro subsector opcional, sem alterar os atuais.
- Resposta 200: data é array, total inteiro do conjunto filtrado antes da paginação, has_more booleano, sectors array de strings do catálogo da classe (independente da página e da busca), page e page_size opcionais. Página vazia é 200 com data=[]; erro de fonte é 503, não lista vazia silenciosa. Classe reconhecida mas ainda não suportada (fixed_income) retorna 501 com mensagem clara até contrato próprio.
- Chave única (asset_type,ticker), excluir inativos/duplicatas comprovadas; sem misturar FIIs com ETFs/BDRs pelo sufixo do ticker. Sem inventar nomes, preços, classificação ou imagens. Campos ausentes são null. Cotação deve ser a última observação disponível, com referência explícita; não confundir horário de consulta com data de cotação.
- O detalhe GET /api/v1/assets/{ticker}?asset_type=... recebe os mesmos campos de identidade e logo, preservando formato data, indicators, classification, histórico e demais endpoints existentes.

Exemplo meramente estrutural (não é cotação real):
```json
{
  "data": [
    {
      "ticker": "BBAS3",
      "asset_type": "stock",
      "name": "Banco do Brasil",
      "sector": "Financeiro",
      "subsector": "Bancos",
      "price": null,
      "logo_url": null,
      "updated_at": null,
      "source": "robo_financeiro"
    }
  ],
  "total": 1,
  "has_more": false,
  "sectors": ["Financeiro"],
  "page": 1,
  "page_size": 24
}
```

## 3. Fonte e eficiência

Construir serviço de leitura do catálogo, separado do coletor e Telegram. Ações: catálogo oficial vinculado a ativos + snapshots/cache da planilha; FIIs: base consolidada e classificação própria; ETF/BDR/cripto: instrumentos_internacionais ativos + última observação. Resolver divergências documentando precedência de fonte e sem sobrescrever cadastro oficial. Consultar preços/nomes/logos em lote, evitar N+1 de SQL, Drive ou Sheets. Cache curto por classe ou consulta com TTL configurável (proposta 5–15 min), limite de memória, invalidação após atualização consolidada. Consultas SQL parametrizadas, índices por classe/ticker/status/referência conforme EXPLAIN. Não executar coleta externa, IA, download de documentos ou aquecimento de logos no GET. Não criar workflow obrigatório adicional nem interferir nas janelas noturnas/oportunidades.

## 4. Logos web

- Manter Drive como origem preferencial (Ícones B3/Ações e FIIs); fallback Logo.dev no servidor para empresas elegíveis, respeitando a regra existente de não usar o fallback para FII. ETFs, BDRs e cripto somente quando existir identidade validada; não atribuir logo de empresa errada ou da gestora como se fosse o fundo.
- PETR3/PETR4 compartilham identidade canônica; preços continuam independentes. FII tem identidade própria. Chave de cache web deve separar classe e identidade, com versão/hash.
- Não devolver file_id Telegram, caminho interno do Drive, token Logo.dev ou URL com credencial. A imagem precisa ser consumível pelo img src sem Authorization (frontend atual); opção preferida: URL HTTPS de mídia pública estritamente limitada a logos previamente aprovadas/cacheadas, servida pelo próprio Robô ou armazenamento dedicado. Não publicar pastas/documentos do Drive. Alternativa assinada de curta duração exige revisão do contrato e expiração suficiente; não transportar JWT Supabase no URL.
- Endpoint de mídia, se usado: GET /api/v1/media/logos/{asset_type}/{logo_key}/{version}. Aceitar somente chaves registradas, nenhuma URL arbitrária/path traversal, sem proxy aberto e sem busca de rede sob demanda. Servir bytes cacheados com MIME validado, limite de tamanho (proposta 512 KiB), ETag/Cache-Control, X-Content-Type-Options nosniff; PNG/JPEG/WebP raster. Requisições 404 para ausente, sem token em logs. Aplicar limites e observar cache; usar HTTPS origin aprovado.
- Catalogar URLs em lote a partir de índice de logos prontas; não emitir 24 chamadas Drive/Logo.dev por página. Aquecer cache em lotes limitados em rotina isolada/manual ou mecanismo já existente, preservar TTL negativo e backoff. Imagem ausente: logo_url:null → fallback com iniciais na Carteira. Falha de imagem nunca bloqueia listagem/detalhe. Não alterar comportamento Telegram.
- Verificar licenças/termos de uso das marcas e provedor antes de publicar mídia.

## 5. Testes de aceite (antes de mesclar a implementação)

1. Autenticação ausente/inválida 401; configuração indisponível 503; sessão válida 200; preflight CORS da origem GitHub Pages configurada.
2. Paginação sem duplicação ou omissão em base estável, total/has_more corretos e setores independentes da página. Busca sem ticker obrigatório, por nome, ticker parcial, acentos, setor e classe; entradas inválidas, página vazia, SQL injection.
3. Ações, FIIs, ETFs, BDRs e cripto retornam exclusivamente sua classe e dados reais. fixed_income 501 enquanto não suportado. Comparar contagem com cadastro consolidado, registrar divergências; não prometer cobertura de toda B3 se não existir.
4. Validar BBAS3, PETR3/PETR4, MXRF11, KNCR11, BOVA11, BDR existente e cripto existente contra base real; selecionar sem digitar ticker. Conferir tipo papel/tijolo quando fonte validada. Logo PETR3/PETR4 igual e cotações independentes; FII sem logo retorna null; erro do Drive não quebra catálogo.
5. Testar URL HTTPS no navegador sem JWT; MIME e cache, nenhuma credencial/ID privado, sem proxy arbitrário. Medir número de consultas e chamadas externas por página (zero chamadas externas no GET de catálogo com cache aquecido); medir p50/p95 e propor orçamento de latência antes de publicar.
6. Testar detalhe/histórico (30,120,365,730 dias), proventos, eventos, fundamentos e coverage, sem regressão; manter autorização existente. Não converter ausência em zero.
7. Validar ponta a ponta na Carteira: Mercado em segundo botão, escolher classe/setor/ativo, ver logo/nome/indicadores, adicionar com ticker/classe já preenchidos e abrir metodologias; sem acesso direto ao Neon/Drive. Verificar resposta no navegador com conta de teste autorizada.
8. Monitorar logs sanitizados, falhas por classe, cobertura de logos e cache hit/miss; incluir rollback por versão de deploy. Não alterar deploy, banco ou usuários nesta proposta.

## 6. Entregas sugeridas para PR de implementação

- [ ] Serviço de catálogo paginado e contrato de resposta.
- [ ] Endpoint autenticado de listagem e extensão compatível de detalhe.
- [ ] Índice/cache web de logos e entrega HTTPS segura; reutilizar Drive e fallback elegível.
- [ ] Testes unitários e de integração em tests/test_portfolio_api.py e testes específicos de catálogo/logo.
- [ ] Validar em staging/ambiente controlado e registrar contagens, amostras e latência.
- [ ] Atualizar contrato oficial, publicar no Render após revisão e validar integração com Carteira PR #1.
- [ ] Renda fixa: especificação independente se desejada; não bloquear lançamento das cinco classes disponíveis.

Este PR é exclusivamente documental; não implementa endpoints nem publica mudanças de produção.
