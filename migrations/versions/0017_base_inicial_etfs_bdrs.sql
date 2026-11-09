-- Seleção inicial aprovada para acompanhamento. A coleta é executada em etapa
-- própria; este arquivo não cria preços nem apresenta informações como atuais.
INSERT INTO instrumentos_internacionais
  (ticker,tipo,nome,simbolo_yahoo_br,simbolo_exterior,indice_referencia,gestora,fonte_cadastro,ativo)
VALUES
  ('BOVA11','ETF','iShares Ibovespa Fundo de Índice','BOVA11.SA','IBOV','Ibovespa','BlackRock','BASE_INICIAL_SISTEMA',TRUE),
  ('IVVB11','ETF','iShares S&P 500 Fundo de Investimento','IVVB11.SA','IVV','S&P 500','BlackRock','BASE_INICIAL_SISTEMA',TRUE),
  ('SMAL11','ETF','iShares BM&FBovespa Small Cap Fundo de Índice','SMAL11.SA','EWZS','Índice Small Cap (SMLL)','BlackRock','BASE_INICIAL_SISTEMA',TRUE),
  ('XFIX11','ETF','Trend ETF IFIX Fundo de Índice','XFIX11.SA','IFIX','IFIX','XP Asset','BASE_INICIAL_SISTEMA',TRUE),
  ('GOLD11','ETF','Trend ETF LBMA Ouro','GOLD11.SA','GOLD','LBMA Gold Price','XP Asset','BASE_INICIAL_SISTEMA',TRUE),
  ('HMRN31','BDR','Homerun Resources Inc.','HMRN31.SA','HMR',NULL,NULL,'BASE_INICIAL_SISTEMA',TRUE)
ON CONFLICT (ticker) DO UPDATE SET
  tipo=EXCLUDED.tipo, ativo=TRUE,
  nome=COALESCE(instrumentos_internacionais.nome, EXCLUDED.nome),
  simbolo_yahoo_br=COALESCE(instrumentos_internacionais.simbolo_yahoo_br, EXCLUDED.simbolo_yahoo_br),
  simbolo_exterior=COALESCE(instrumentos_internacionais.simbolo_exterior, EXCLUDED.simbolo_exterior),
  indice_referencia=COALESCE(instrumentos_internacionais.indice_referencia, EXCLUDED.indice_referencia),
  gestora=COALESCE(instrumentos_internacionais.gestora, EXCLUDED.gestora),
  atualizado_em=NOW();
