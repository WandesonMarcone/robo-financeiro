# Fase 7 — Etapa 7.3: Dados de Mercado Persistidos Utilizáveis em Produção

> Documento de relatório da Etapa 7.3. Data: 2026-08-31.
> Suíte de testes: 957 passando (era 931 antes da etapa). Ruff limpo nos
> arquivos alterados/criados. Nenhuma migração de banco foi necessária.

---

## 1. O que já existia (reutilizado, não recriado)

- **Produtor de persistência (Bloco 5C)**: `pipeline_dados/espelhamento_mercado_5c.py`
  já gravava `snapshots_fiis`, `snapshots_acoes`, `ativos_perfil`,
  `ativos_inquilinos` e disparava `motor_alertas.processar_indicadores_ativo`
  (`indicadores_historico`, `alertas_eventos`), de forma idempotente por
  `(ativo_id, data_referencia)`, usando `qualidade_dados` (erro nunca vira
  `0.0`) e `mapeamento_sheets` (transformação das linhas do Sheets).
- **Dados contábeis (CVM)**: `pipeline_dados/coletor_cvm.py` (ITR → 
  `dados_financeiros_acoes`) e `pipeline_dados/coletor_fiis.py` (informe mensal →
  `dados_financeiros_fiis`), já adaptados na 7.2 para usar
  `obter_tickers_com_fallback`.
- **Identidade declarativa (Etapa 7.2)**: `pipeline_dados/catalogo_ativos.py`
  e a tabela `ativos_catalogo` (seed idempotente a partir de `config`).
- **ORM completo**: `SnapshotFii`/`SnapshotAcao` com `UniqueConstraint`
  (`uix_snapshots_fiis`/`uix_snapshots_acoes` em `ativo_id+data_referencia`) e
  `DadosFinanceirosAcoes`/`DadosFinanceirosFiis` com unicidade equivalente.

## 2. O que faltava (lacunas atacadas nesta etapa)

- **Nenhum leitor de produção consumia `snapshots_*` nem `dados_financeiros_*`**
  (verificado: `api/`, `services/`, `bot/`, `app.py` não referenciam as tabelas —
  mesmo diagnóstico da auditoria da Etapa 7.1, item 5.1). Todo o valor persistido
  ficava órfão.
- **A identidade do ativo no espelhamento não usava o catálogo da Etapa 7.2**:
  `espelhar_ativo` resolvia o CNPJ direto nos mapas de `config.py`
  (`mapeamento_sheets.resolver_cnpj`), e não no catálogo PostgreSQL.

## 3. O que foi alterado

- `pipeline_dados/espelhamento_sheets.py` — `espelhar_ativo` passou a resolver o
  CNPJ **via catálogo da Etapa 7.2** (`catalogo_ativos.resolver_cnpj`:
  PostgreSQL primeiro, `config` como fallback) e só usa o placeholder
  `PENDENTE-{ticker}` quando o CNPJ é desconhecido (exigido pela constraint
  `NOT NULL` de `ativos.cnpj`). O parâmetro `cnpj` explícito continua tendo
  precedência. Comportamento observável preservado para o universo config.
- `api/blueprint.py` — registro do novo Blueprint `api_mercado` sob `/mercado`.
- `api/serializadores.py` — serializers explícitos de snapshots e dados
  financeiros (FII/ação), com dispatch por tipo; campos ausentes permanecem
  `None`; `Decimal` normalizado para JSON.

## 4. Arquivos criados

- `services/mercado.py` — camada de leitura de produção dos dados de mercado
  persistidos (o leitor do Financial Intelligence Core). Somente leitura;
  filtros seguros (ticker/ativo_id/tipo/tipo_doc/data_referencia); limite com
  teto (500); ordenação decrescente por `data_referencia`.
- `api/routes/mercado.py` — endpoints HTTP somente leitura sob
  `/api/v1/mercado/*` (permissão `dados.consultar`).
- `tests/test_mercado_service.py` — 23 testes do serviço, serialização e API.

## 5. Fluxo final (fonte → consulta)

```
Google Sheets (fonte ativa)
  -> transformar_linha_fii/acao (normalização)
  -> validar_registro (validação VALID/WARNING/INVALID)
  -> espelhar_ativo (identidade via catálogo 7.2)
  -> gravar_snapshot_fii/acao + ativos_perfil + inquilinos + motor_alertas
  -> PostgreSQL: snapshots_fiis/snapshots_acoes (+ dados_financeiros_* via CVM)
  -> services.mercado.obter_snapshots/obter_dados_financeiros (consulta do core)
  -> api/routes/mercado.py -> GET /api/v1/mercado/snapshots e /dados-financeiros
```

## 6. Identificação e armazenamento de snapshots

- **Identidade**: o ativo é identificado por `ativo_id` (FK para `ativos`), com
  o CNPJ resolvido agora pelo catálogo da Etapa 7.2 (PostgreSQL primeiro).
- **Chave temporal**: `(ativo_id, data_referencia)` — `data_referencia` é a
  data da coleta em São Paulo (`_data_referencia_sp()`), preservando a série
  histórica: cada coleta em dia diferente cria uma nova linha.
- **Rastreabilidade**: `fonte` (ex.: `"Google Sheets"`), `data_coleta` e
  `url_origem` (NULL quando a origem não transporta URL — não se inventa).

## 7. Prevenção de duplicação

- Constraints `UniqueConstraint('ativo_id', 'data_referencia')` em
  `snapshots_fiis` e `snapshots_acoes` (e equivalentes em `dados_financeiros_*`).
- A escrita 5C é idempotente por `(ativo_id, data_referencia)`: segunda execução
  do mesmo dia atualiza o registro em vez de duplicar; data diferente cria nova
  linha da série. O leitor `services/mercado` respeita essas chaves — nunca
  cria, altera ou apaga dados.

## 8. Testes

- **Novos** (26): `tests/test_mercado_service.py` (23) + identidade via catálogo
  em `tests/test_espelhamento_sheets.py` (3).
  Cobertura: persistência via produtor 5C e leitura pelo serviço; identificação
  por ticker/tipo/ativo_id; isolamento entre ativos; histórico temporal
  ordenado; idempotência; `data_referencia` diferente cria série; dados ausentes
  permanecem `None`; INVALID não persiste (erro nunca vira `0.0`); dados
  financeiros por tipo/tipo_doc; tipos inválidos rejeitados; limite/teto;
  serialização explícita; endpoints HTTP (autenticação 401, filtros, 404, 400,
  dados financeiros). Compatibilidade com fluxos existentes: as suítes de
  espelhamento (Bloco 4/5C) permanecem verdes.
- **Suíte completa**: **957 passed** (era 931) em 8m34s; único warning é a
  deprecação pré-existente do PyPDF2.

## 9. Ruff

- Limpo em todos os arquivos alterados/criados:
  `pipeline_dados/espelhamento_sheets.py`, `services/mercado.py`,
  `api/serializadores.py`, `api/routes/mercado.py`, `api/blueprint.py`,
  `tests/test_mercado_service.py`, `tests/test_espelhamento_sheets.py`.

## 10. Conclusão da Etapa 7.3

- A camada de dados de mercado **persistida agora é utilizável em produção**:
  existe leitor de produção (`services/mercado`) e exposição HTTP
  (`/api/v1/mercado/*`) para `snapshots_*` e `dados_financeiros_*`.
- A **identidade do ativo passou a fluir pelo catálogo da Etapa 7.2**
  (PostgreSQL primeiro, `config` como fallback), sem voltar a ticker hardcoded
  nem ao Sheets como fonte primária de identidade.
- Nenhuma estrutura equivalente foi criada: os modelos/produtores do Bloco
  5B/5C e CVM foram reutilizados; nenhuma migração de banco foi necessária.
- Escopo respeitado: nada de valuation, preço-teto, scoring, IA, frontend,
  Content Engine, coletores ETF/CRIPTO, nova arquitetura de banco ou
  refatoração geral. A Etapa 7.4 **não** foi iniciada.

## 11. Pendências (não bloqueiam; candidatas a etapas futuras)

- `ESPELHAMENTO_PG_ATIVO` (padrão `false`) continua opt-in em produção — ligá-lo
  efetiva a escrita dos snapshots 5C na rotina diária (o Sheets segue fonte
  ativa até a decisão de inversão de papel da Etapa 7.1, item 7.1).
- Os coletores ETF/CRIPTO e o desacoplamento do motor de alertas da flag de
  espelhamento permanecem fora desta etapa (alinhado ao escopo).
- A leitura por `tipo` do catálogo no `espelhar_ativo` considera apenas os
  tipos com dados de mercado persistidos (ACAO/FII); novos tipos exigirão
  coletores próprios (fora de escopo nesta etapa).
