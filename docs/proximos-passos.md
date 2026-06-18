# Próximos Passos: Ordem Sugerida de Implementação

Com a definição mestra documentada através dos arquivos markdown desta pasta, encerra-se a fase de Arquitetura. A implementação oficial (desenvolvimento de código) deve obedecer o pipeline lógico de dependências descritas abaixo:

### Passo 1: Construção Básica da Árvore
- Criar a estrutura base de diretórios (`server/`, `client-desktop/`, `client-cli/`, `shared/`).
- Instalar dependências bases virtuais e criar o boilerplate do `shared/` com modelos Pydantic e enums básicos.

### Passo 2: O Banco de Dados e Autenticação (`server/`)
- Levantar o ORM assíncrono conectado com SQLite na camada `server/database/`.
- Construir a mecânica da API REST de autenticação (`server/auth/`) com `Argon2` e emissão de `JWT`.
- Validação: Testar esses endpoints via requests puros (ex: curl).

### Passo 3: Coração do WebSocket (`server/websocket/`)
- Mapear o servidor WebSocket.
- Integrar a validação de token aos novos WebSockets recebidos.
- Implementar o padrão "Echo" inicial ou chat em sala genérica para testar conectividade bidirecional base.

### Passo 4: O Cliente CLI de Validação Rápida (`client-cli/`)
- Criar a interface de terminal usando `Rich/Typer`.
- Essa escolha prioriza testar o ciclo completo do JSON WebSocket e autenticação antes de se comprometer com componentes densos de GUI.

### Passo 5: Escalando Regras de Negócio de Salas (`server/rooms/`)
- Escrever os controladores lógicos reais de gerenciar múltiplos canais, salas protegidas, listas de membros e o isolamento de eventos de broadcasting de maneira correta no server.

### Passo 6: O Cliente GUI Definitivo (`client-desktop/`)
- Levantar o ciclo de vida do `PySide6`.
- Mapear a UX e as sub-rotinas (Signal/Slots) integradas com a thread de chamadas WebSocket não-bloqueantes.
- Polimento estético, inserção de temas Dark/Light nativos.

### Passo 7: Empacotamento
- Redigir os `Dockerfiles` nativos do backend.
- Lançar os testes oficiais focados na resiliência das conexões concorrentes.
