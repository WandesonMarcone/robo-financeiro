# Coleta automática de fundamentos de ações

O workflow existente passa a executar a fila a cada 4 horas, além do acionamento individual.
Universo: união da coluna A da BD_Acoes com o catálogo e cadastro SQL. Um ticker sem CNPJ válido fica em falha explícita, sem inventar CNPJ. A fila guarda tentativas e próxima execução; os novos ativos têm prioridade. Cada execução seleciona até quatro ativos, com orçamento de 15 minutos entre inícios de ativos e timeout externo de 35 minutos. Um ativo com erro não bloqueia os outros. O cache de ZIPs é temporário por execução.

Busca cinco DFP anuais completos e cinco anos de ITR, proventos e desdobramentos complementares. Atualização semanal (dois dias quando houver falha parcial da fonte, um dia em falha total). Não confundir atualização do coletor com publicação oficial de novos balanços.

Limitações explícitas: conciliação oficial de eventos/proventos, classificação por espécie de ação, normalização contábil setorial, CAPEX completo, ações em circulação, múltiplos setoriais e premissas ainda precisam de desenvolvimento e validação. A fila não garante que todas as empresas publiquem todos os dados. Não usa valores sintéticos para preencher lacunas. A base anterior de indicadores pode conservar registros de fórmulas antigas; consumidores devem considerar cobertura e origem até a revisão de versionamento. Não inicia FIIs automaticamente.

Teste: python -m unittest discover -s tests -p 'test_*.py' -v.
