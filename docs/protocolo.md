# Especificação do Protocolo WebSocket

A comunicação real-time é guiada por eventos estruturados em JSON. O servidor valida estritamente a assinatura de cada payload baseado nesta especificação.

## Formato Base
Todo frame WebSocket enviado ou recebido segue a estrutura:
```json
{
  "event": "namespace.action",
  "payload": { ... dados ... }
}
```

## Eventos V1 (Client -> Server)

### `auth.authenticate`
Valida a conexão do socket logo após a abertura da conexão.
- **Payload**: `{"token": "jwt_token_here"}`

### `message.send_room`
Envia uma mensagem para uma sala específica.
- **Payload**: `{"room_id": "uuid", "content": "Olá mundo!"}`

### `message.send_private`
Envia uma DM para um usuário.
- **Payload**: `{"receiver_id": "uuid", "content": "Mensagem secreta"}`

### `room.join`
Entra em uma sala pública ou protegida.
- **Payload**: `{"room_name": "#geral", "password": "opcional"}`

### `room.create`
Cria uma nova sala via WebSocket.
- **Payload**: `{"room_name": "#sala-nova", "is_private": false, "password": "opcional"}`

## Eventos V1 (Server -> Client)

### `auth.success`
Confirmando que a autenticação no socket foi validada.
- **Payload**: `{"user_id": "uuid", "username": "nome"}`

### `message.receive`
Uma nova mensagem chegou (sala ou DM).
- **Payload**: `{"id": "uuid", "room_id": "uuid_ou_null", "sender_id": "uuid", "sender_name": "nome", "content": "texto", "timestamp": "iso8601"}`

### `user.presence`
Atualização de status de um usuário (online/offline) e opcionalmente seu papel em uma sala específica.
- **Payload**: `{"user_id": "uuid", "status": "online|offline", "room_id": "uuid_opcional", "role": "owner|admin|member_opcional"}`

### `room.member_role`
Notificação de que o papel de um membro em uma sala foi alterado.
- **Payload**: `{"room_id": "uuid", "user_id": "uuid", "role": "owner|admin|member"}`

### `error.alert`
Mensagem de erro disparada pelo servidor em respostas a eventos incorretos ou confirmação de criação de sala (código 201).
- **Payload**: `{"code": 400, "message": "Senha incorreta para a sala"}`

## Endpoints REST (Exploração)

### `GET /api/rooms/explore`
Retorna a listagem de todas as salas públicas e privadas existentes no servidor com informações sobre contagem de membros e de presença online.
- **Autenticação**: Requer Token JWT de Acesso.
- **Resposta (200 OK)**:
```json
[
  {
    "id": "uuid",
    "name": "#sala-teste",
    "description": "Uma sala para testes de moderação.",
    "is_private": false,
    "has_password": true,
    "members_count": 5,
    "online_count": 2
  }
]
```

## Sistema de Amizades (Endpoints REST)

Todos os endpoints requerem Token JWT de Acesso no cabeçalho `Authorization: Bearer <token>`.

### `POST /api/friends/request`
Envia uma solicitação de amizade.
- **Payload**: `{"receiver_username": "nome_usuario"}`
- **Resposta (201 Created)**: Retorna os dados da relação criada (`FriendshipResponseSchema`).
- **Notificação**: Se o destinatário estiver online, ele receberá o evento WebSocket `friend.request_received`.

### `GET /api/friends/requests/pending`
Lista as solicitações de amizade pendentes recebidas.
- **Resposta (200 OK)**: Lista de usuários solicitantes.

### `POST /api/friends/request/{sender_id}/accept`
Aceita a solicitação de amizade de um remetente.
- **Resposta (200 OK)**: Detalhes da relação atualizada.

### `POST /api/friends/request/{sender_id}/reject`
Rejeita a solicitação de amizade pendente.
- **Resposta (200 OK)**: JSON de confirmação.

### `GET /api/friends`
Retorna a lista de amigos ativos (amizades aceitas).
- **Resposta (200 OK)**: Lista de usuários amigos.

### `DELETE /api/friends/{friend_id}`
Remove um amigo da lista (desfaz amizade).
- **Resposta (200 OK)**: JSON de confirmação.

### `POST /api/friends/{user_id}/block`
Bloqueia um usuário (desfaz amizades/solicitações pendentes e cria o bloqueio).
- **Resposta (200 OK)**: Detalhes do bloqueio.

### `POST /api/friends/{user_id}/unblock`
Desbloqueia um usuário.
- **Resposta (200 OK)**: JSON de confirmação.


## Eventos Adicionais de WebSocket (Amizades & DMs)

### `dm.start` (Client -> Server)
Inicia uma sessão de DM direta com um usuário, validando a inexistência de bloqueio mútuo.
- **Payload**: `{"receiver_id": "uuid"}`

### `dm.start_success` (Server -> Client)
Confirmação enviada de volta ao remetente autorizando o início da DM.
- **Payload**: `{"receiver_id": "uuid", "receiver_name": "nome_usuario"}`

### `friend.request_received` (Server -> Client)
Disparado em tempo real para o destinatário de uma nova solicitação de amizade (se online).
- **Payload**: `{"sender_id": "uuid", "sender_name": "nome_usuario"}`

### `friend.accepted` (Server -> Client)
Disparado em tempo real para o remetente original de um convite ou solicitação de amizade quando este é aceito pelo destinatário.
- **Payload**: `{"user_id": "uuid", "username": "nome_usuario"}`


## Sistema de Convites (Ajustes de Notificações)

### `GET /api/invites/pending/count`
Retorna a contagem de convites pendentes recebidos pelo usuário autenticado.
- **Resposta (200 OK)**:
```json
{
  "pending_count": 3
}
```

### `GET /api/invites/pending/detail`
Retorna os convites pendentes recebidos detalhadamente.
- **Resposta (200 OK)**: Lista de convites (`List[InviteResponse]`).

### `invite.received` (Server -> Client)
Disparado em tempo real via WebSocket para o destinatário de um novo convite (se online).
- **Payload**: `{"invite_id": "uuid", "sender_id": "uuid", "sender_name": "nome_usuario"}`


## Suporte a Envio de Anexos (Endpoints REST)

### `POST /api/attachments/upload`
Faz o upload de um arquivo para o servidor. Limite máximo: 10 MB. Tipos de arquivos executáveis são bloqueados.
- **Form-data**: `file` (UploadFile)
- **Resposta (201 Created)**:
```json
{
  "id": "uuid",
  "filename": "documento.pdf",
  "file_size": 24567,
  "mime_type": "application/pdf",
  "url": "/api/attachments/uuid/download"
}
```

### `GET /api/attachments/{attachment_id}/download`
Faz o download do anexo correspondente. A permissão é verificada:
- Se não estiver associado a nenhuma mensagem, apenas o próprio uploader pode baixar.
- Se associado a sala, o usuário autenticado deve ser membro da sala.
- Se associado a DM, o usuário deve ser o remetente ou o destinatário.


## Ajuste em Mensagens (WebSocket)

Tanto `message.send_room` (Client -> Server) quanto `message.send_private` (Client -> Server) suportam um campo opcional de anexo:
- **Payload**: `{"room_id/receiver_id": "uuid", "content": "texto", "attachment_id": "uuid_opcional"}`

Ao receber uma mensagem com anexo, o payload `message.receive` (Server -> Client) conterá o bloco `attachment`:
- **Payload**:
```json
{
  "id": "uuid",
  "room_id": "uuid_ou_null",
  "sender_id": "uuid",
  "sender_name": "nome",
  "content": "texto",
  "timestamp": "iso8601",
  "attachment": {
    "id": "uuid",
    "url": "/api/attachments/uuid/download",
    "filename": "documento.pdf",
    "file_size": 24567,
    "mime_type": "application/pdf"
  }
}
```

