# Fluxo de Mensagens

## Cenário 1: Mensagem em Sala Pública
1. **Ação no Cliente**: O usuário digita na janela GUI (PySide) ou CLI e pressiona Enter.
2. **Envio da Origem**: O serviço do cliente empacota a string num JSON: `{"event": "message.send_room", "payload": {"room_id": "id", "content": "Oi!"}}` e transmite no WebSocket.
3. **Recepção no Servidor**: O roteador de WebSockets captura o evento e delega para o módulo `rooms`.
4. **Validação e Permissões**: O servidor verifica se o remetente associado a este socket tem permissão (membro ativo) para postar na sala em questão.
5. **Persistência**: A mensagem é armazenada no banco na tabela `messages`.
6. **Broadcast (Multiplexing)**: O módulo `websocket/` mapeia todos os sockets ativos atualmente logados que pertencem a esta sala, formatando o payload de envio.
7. **Entrega e Renderização**: O servidor dispara o `message.receive` de volta. Os clientes recebem, extraem a aba correta e renderizam a linha no histórico.

## Cenário 2: Mensagem Privada (DM)
1. **Ação no Cliente**: O usuário decide enviar uma mensagem direta para um amigo.
2. **Envio da Origem**: O cliente dispara o evento correspondente: `{"event": "message.send_private", "payload": {"receiver_id": "id", "content": "Segredo"}}`.
3. **Validação**: O módulo `users/` confere se o alvo existe e (se aplicável na regra de negócios) se a amizade/DM é válida.
4. **Persistência**: A mensagem é salva na tabela `private_messages`.
5. **Direcionamento Específico**: O servidor busca em sua hash local os objetos de socket ligados ao ID do remetente e ao ID do destinatário.
6. **Entrega Segura**: O evento `message.receive` é transmitido unicamente por essas duas vias, garantindo isolamento total de outras conexões ativas do servidor.
