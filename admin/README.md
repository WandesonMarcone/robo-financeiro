# Central de Controle — Estratégia Fardada

Interface administrativa estática publicada pelo GitHub Pages. Ela não contém
nem armazena credenciais de Neon, Telegram, Google Drive ou GitHub.

## Publicação

1. Em **Settings → Pages** do repositório, selecione **GitHub Actions** como
   fonte de publicação.
2. Após o workflow `Publicar Central de Controle` concluir, o painel ficará em
   `https://wandesonmarcone.github.io/robo-financeiro/`.
3. No Render, configure as variáveis abaixo no serviço do robô:

```text
ADMIN_DASHBOARD_TOKEN=<token longo, aleatório e exclusivo>
ADMIN_DASHBOARD_ORIGINS=https://wandesonmarcone.github.io
```

4. Abra o painel e informe o endereço do Render e o token. O token permanece
   somente na sessão atual do navegador.

## API administrativa

As rotas ficam no mesmo serviço Flask do robô e exigem o header:

```text
Authorization: Bearer <ADMIN_DASHBOARD_TOKEN>
```

- `GET /api/admin/status`: saúde básica e tarefas iniciadas pelo painel.
- `POST /api/admin/commands`: inicia operações administrativas já existentes.

O painel permite atualizar ativo isolado, buscar documentos por ativo, executar
as coletas FNET/CVM/FIIs, processamento por IA, resumos, auditoria do Drive e
diagnóstico de fontes. Operações irreversíveis, como resetar documentos, não
foram expostas pela interface.
