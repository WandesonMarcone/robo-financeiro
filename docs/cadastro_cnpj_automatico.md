# Cadastro automático de CNPJ por ação

O workflow Mercado unificado consulta o FCA da CVM uma vez antes das oportunidades e da atualização noturna (inclusive despacho manual). Não roda no modo exclusivamente cripto ou correção de FIIs. O passo tem teto de quatro minutos e não impede as etapas de mercado se falhar.

A tabela cadastro_cnpj_acoes é criada no primeiro sucesso. Ticker é chave, CNPJ não é único: ações ON e PN da mesma companhia podem compartilhar emissor. O código verifica dígitos, vínculo, negociação encerrada e conflitos no FCA, registra fonte e horário e prioriza nova coleta fundamentalista quando muda o CNPJ. Não inventa vínculos. O universo é a união BD_Acoes e cadastros SQL. A ausência no FCA aparece nos logs e não apaga dados oficiais previamente validados.

Fundamentos, consulta de nome por CNPJ e coletores legados de ITR/IPE consultam o registro oficial antes do legado. O mapa config deixa de ser consultado para nomes, mas permanece no arquivo para migração e compatibilidade com eventuais outros consumidores. Tabelas antigas mantêm suas restrições e seus CNPJs originais; não representam a fonte oficial. Coletores legados de ITR/IPE ainda escolhem um ativo por emissor; a distribuição dos mesmos documentos/dados entre múltiplas classes exige evolução separada. A sincronização não baixa balanços nem proventos. PR #82 (notificações e consulta FCA no fluxo de fundamentos) é independente.

Validação: python -m unittest discover -s tests -p 'test_*.py' -v. Após implantação, verificar tabela e logs; nenhum acesso à produção é necessário nos testes.
