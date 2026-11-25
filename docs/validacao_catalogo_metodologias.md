# Auditoria de cobertura e integração — 25/11/2026

Base auditada: 135 ações na fila, 5 com fatos, 7 com falhas, 123 pendentes. União SQL: 134 ações/35 FIIs; 20 ETFs, 16 BDRs, 15 cripto ativos. 79 ações/34 FIIs possuem snapshots. Não representa toda B3 nem carteira pessoal. O GET não realiza scraping, Drive nem Sheets; o cache em memória de 5 min limita consultas. Falta conciliar a ação presente apenas na planilha e o universo de FIIs; validar cadastro oficial/atividade.

## Qualidade antes de valuation
- ABEV3 VPA 5684,67 por provável escala de mil ações; RI informa 15,618 bilhões em circulação em 2025. Corrigir pela unidade de origem e cruzar com lucro/LPA, não aplicar fator mil indiscriminado.
- AZUL4 VPA negativo: Graham convencional não aplicável. Exigir LPA e VPA positivos no período escolhido.
- Crescimento de 5 pontos anuais significa 4 intervalos; registrar horizonte real ou coletar ponto inicial adicional.
- Lynch/PEG precisa cotação/P-L na mesma referência e crescimento positivo ajustado por eventos.
- Bazin, teto por proventos e Gordon: B3/avisos CVM para proventos oficiais por classe, data-ex, valor bruto, JCP e eventos; ausência não é zero.
- DCF: CAPEX total, captação e amortização, capital de giro operacional, dívida líquida, ações por espécie, fluxo de caixa e premissas. Bancos requerem modelo próprio/IF.Data e capital regulatório. Não usar automaticamente FCFF industrial.
- Múltiplos: preço histórico B3, ações em circulação e market cap por espécie, grupos comparáveis oficiais, P/L, P/VP, EV/EBITDA e P/FCF coerentes no tempo. Sem dupla contagem de emissor.
- FIIs: nenhuma base histórica de fundamentos da nova camada; informes mensais, distribuição oficial, cota, PL, NOI/vacância/WALT quando tijolo e carteira CRI, indexadores, LTV, inadimplência quando papel.
- Premissas de crescimento, desconto, margem e cenários pertencem à Carteira, não são fatos históricos.
- Último erro cadastral FCA_sem_vinculos_validos; validar layout e filtros reais, antes de chamar toda a fila de completa.

## Logos
Cache explicitamente aprovado em Neon com WebP reduzido, máximo 64KiB por imagem. Drive primeiro; fallback Logo.dev apenas stock com cadastro oficial. PETR3/PETR4 compartilham chave por CNPJ confirmado. Não usar token, URL arbitrária ou ID Drive no frontend. Ativar somente com PORTFOLIO_PUBLIC_LOGOS_ENABLED=true e PORTFOLIO_PUBLIC_MEDIA_ORIGIN=https://host-aprovado. CLI manual limitado a 10 tickers, com confirmação de direito de publicação. ETF/BDR/cripto não recebem logo até validação individual. Sem logo retorna null. Não foi feita publicação de imagens nem alteração de produção.

## Validação pendente
Testes offline, comparação SQL com planilha, execução autenticada ponta a ponta na Carteira, latência, revisão de direitos/termos, configuração Render e publicação. Nenhuma metodologia deve ser liberada como confiável somente pelo status de cobertura atual.
