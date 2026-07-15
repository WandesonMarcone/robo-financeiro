# Robô Financeiro Institucional
Automação completa de monitoramento de ações e FIIs, com análise quantitativa, garimpo de oportunidades e interface via Telegram.

## Estrutura do Sistema
- `app.py`: Orquestrador das tarefas de atualização.
- `bot_telegram.py`: Servidor 24/7 para interface de usuário e consulta de documentos.
- `modules/`: Lógica de garimpo e integração com CVM.

## Mapeamento de Colunas (BD_Acoes)
- **Coluna A:** Ticker
- **Colunas B-AG:** Dados financeiros (Preço, P/L, P/VP, ROE, etc.)
- **Coluna AG:** Carimbo de tempo da última atualização

## Como rodar
Este repositório é configurado para rodar via GitHub Actions (para automação de planilha) e Render (para o bot Telegram).

IDDescrição do Documento
14Relatório Gerencial (O que você usa hoje)
10Relatório Trimestral
15Fato Relevante
12Informe Mensal
3Demonstrações Financeiras (ITR/DFP)
17Carta ao Cotista
23Aviso aos Cotistas
