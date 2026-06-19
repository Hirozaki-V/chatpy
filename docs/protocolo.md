# Protocolo de Comunicação ChatPy V2

O ChatPy usa dois canais de comunicação: **REST (HTTP)** para operações stateless e **WebSocket** para eventos em tempo real.

---

## REST (HTTP)

### Autenticação

| Método | Endpoint | Descrição |
|---|---|---|
| POST | `/api/auth/register` | Cadastrar usuário |
| POST | `/api/auth/login` | Login (retorna JWT) |
| POST | `/api/auth/guest` | Criar conta de convidado |
| POST | `/api/auth/logout` | Logout (revoga sessão) |

### Usuários

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/api/users/me` | Perfil do usuário logado |
| GET | `/api/users/online` | Lista de usuários online |
| PUT | `/api/users/status` | Mudar status (online/away/offline) |

### Salas

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/api/rooms` | Listar todas as salas |
| POST | `/api/rooms` | Criar sala |
| POST | `/api/rooms/{id}/join` | Entrar em sala |
| POST | `/api/rooms/{id}/leave` | Sair de sala |
| GET | `/api/rooms/{id}/history` | Histórico de mensagens |
| GET | `/api/rooms/{id}/members` | Membros da sala |
| PUT | `/api/rooms/{id}/members/{uid}/role` | Promover/rebaixar |
| DELETE | `/api/rooms/{id}/members/{uid}` | Expulsar/banir |
| GET | `/api/rooms/explore` | Explorar salas |
| PUT | `/api/rooms/{id}` | Atualizar configurações |

### Amizades

| Método | Endpoint | Descrição |
|---|---|---|
| POST | `/api/friends/request` | Enviar solicitação |
| GET | `/api/friends/requests/pending` | Solicitações pendentes |
| POST | `/api/friends/request/{id}/accept` | Aceitar |
| POST | `/api/friends/request/{id}/reject` | Rejeitar |
| GET | `/api/friends` | Listar amigos |
| DELETE | `/api/friends/{id}` | Remover amigo |
| POST | `/api/friends/{id}/block` | Bloquear |
| POST | `/api/friends/{id}/unblock` | Desbloquear |

### Anexos

| Método | Endpoint | Descrição |
|---|---|---|
| POST | `/api/attachments/upload` | Upload de arquivo |
| GET | `/api/attachments/{id}/download` | Download |

### Federação

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/.well-known/chatpy.json` | Descoberta de servidor |
| POST | `/api/federation/dm` | Receber DM federada |
| POST | `/api/federation/presence` | Receber presença federada |
| GET/POST | `/api/admin/peers` | Gerenciar peers |
| POST | `/api/admin/peers/discover` | Descobrir peer via .well-known |

### E2E (scaffold)

| Método | Endpoint | Descrição |
|---|---|---|
| PUT | `/api/keys/identity` | Publicar Identity Key |
| POST | `/api/keys/prekeys` | Publicar One-Time PreKeys |
| GET | `/api/keys/{username}` | Buscar chaves para X3DH |

### Administração

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/health` | Healthcheck |
| GET | `/metrics` | Métricas Prometheus |
| GET | `/api/version` | Versão do servidor |
| GET | `/admin` | Painel admin web |
| GET/POST | `/api/admin/backups` | Gerenciar backups |

---

## WebSocket

Conexão em `ws://servidor:5000/ws`. Todas as mensagens são JSON no formato:
```json
{"event": "tipo.do.evento", "payload": {...}}
```

### Cliente → Servidor

| Evento | Descrição |
|---|---|
| `auth.authenticate` | Autentica a conexão (envia JWT) |
| `message.send_room` | Envia mensagem para sala |
| `message.send_private` | Envia DM local |
| `message.send_federated` | Envia DM para outro servidor |
| `room.join` | Entra em sala |
| `room.create` | Cria sala |
| `dm.start` | Inicia conversa DM |
| `user.typing` | Indica que está digitando |

### Servidor → Cliente

| Evento | Descrição |
|---|---|
| `auth.success` | Autenticação confirmada |
| `message.receive` | Mensagem recebida (sala, DM, ou federada) |
| `user.presence` | Mudança de presença |
| `user.typing_broadcast` | Alguém está digitando |
| `room.created` | Sala criada com sucesso |
| `room.member_role` | Papel de membro alterado |
| `dm.start_success` | DM iniciada com sucesso |
| `friend.request_received` | Solicitação de amizade recebida |
| `friend.accepted` | Amizade aceita |
| `friend.removed` | Amizade desfeita |
| `error.alert` | Erro |

---

## Federação

Servidores ChatPy podem se federar — trocar DMs entre usuários de servidores diferentes.

### Como funciona

1. **Descoberta**: cada servidor expõe `/.well-known/chatpy.json` com sua chave pública Ed25519
2. **Registro**: administrador cadastra o peer (manualmente ou via descoberta automática)
3. **Envio**: quando Alice (servidor A) manda DM para `@bob@servidor-b.com`:
   - Servidor A identifica o peer pelo domínio
   - Assina a mensagem com Ed25519
   - Envia via HTTP POST para `/api/federation/dm` do servidor B
   - Servidor B valida assinatura, persiste e entrega via WebSocket ao Bob
4. **Presença**: mudanças de status são propagadas para todos os peers

### Usernames federados

Formato: `@usuario@dominio` (estilo Matrix)

Exemplo: `@bob@chatpy.outro-servidor.com`

### Configuração

```env
FEDERATION_ENABLED=true
CHATPY_SERVER_DOMAIN=chatpy.meuserver.com
CHATPY_SERVER_BASE_URL=https://chatpy.meuserver.com
# FEDERATION_OPEN=false  # só aceita de peers registrados (recomendado)
```
