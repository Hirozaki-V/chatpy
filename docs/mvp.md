# Definição do MVP (Mínimo Produto Viável) - V1

O MVP do ChatPy é a prova de conceito do estágio V1, validando as regras inegociáveis de "Zero Electron/PyWebView" e da "Arquitetura API-First". O marco de sucesso do MVP requer os seguintes itens operacionais:

1. **Servidor Backend**
   - Configuração do FastAPI em conjunto com SQLite em modo assíncrono.
   - Um endpoint para criar contas e logar com hashing (Argon2).
   - Um canal WebSocket persistente emitindo eventos estruturados de recebimento/envio.
   - Domínios implementados: Gerenciamento básico de sessões de usuário, salas, e armazenamento das mensagens no banco.

2. **Camada Shared**
   - Pelo menos um modelo Pydantic compartilhado usado com êxito tanto pelo back-end quanto pelas aplicações cliente para validar as comunicações enviadas.

3. **Cliente Desktop (PySide6)**
   - Janela de interface primária (limpa e nativa).
   - Fluxo de autenticação bem sucedido que armazena localmente o token JWT.
   - Capacidade de se juntar a uma sala pública padrão (ex: `#geral`).
   - Apresentação visual da lista de mensagens e capacidade de escrever uma mensagem de volta que se propaga perfeitamente ao redor da rede de WebSockets.

4. **Cliente CLI**
   - Um terminal interativo rudimentar que valida a regra de que *o cliente gráfico não detém privilégio algum*. Se logar via CLI com `Rich`, as mensagens e atualizações devem chegar do mesmo jeito e velocidade que na GUI PySide6.
