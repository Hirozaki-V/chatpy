# Arquitetura do ChatPy V2

## Visão geral

```
┌─────────────┐     HTTP REST      ┌─────────────┐
│   Cliente   │ ◄────────────────► │             │
│  Desktop    │     WebSocket      │   Servidor  │
│ (PySide6)   │ ◄────────────────► │  (FastAPI)  │
└─────────────┘                    │             │
┌─────────────┐     HTTP REST      │  ┌────────┐ │
│   Cliente   │ ◄────────────────► │  │SQLite/ │ │
│    CLI      │     WebSocket      │  │Postgres│ │
│ (Typer/Rich)│ ◄────────────────► │  └────────┘ │
└─────────────┘                    └──────┬──────┘
                                          │ HTTP (federação)
                                   ┌──────▼──────┐
                                   │  Servidor   │
                                   │   Peer      │
                                   └─────────────┘
```

## Componentes

### Servidor (`server/`)

FastAPI + Uvicorn + SQLAlchemy + WebSocket.

- **API REST**: auth, rooms, friends, attachments, federation, E2E keys, admin
- **WebSocket**: dispatcher roteia eventos por tipo
- **Auth**: Argon2 (senhas), JWT (sessões revogáveis), anti brute-force persistente
- **Rate limiting**: REST (60 req/min) + WebSocket (10 msg/5s)
- **Federação**: DMs e presença cross-server com assinatura Ed25519
- **Jobs em background**: limpeza de anexos, purga de guests, backup SQLite
- **Observabilidade**: Prometheus, logging JSON, healthcheck

### Shared (`shared/`)

Contratos compartilhados entre servidor e clientes.

- `events/`: Enum com todos os eventos do protocolo
- `protocol/`: Schemas Pydantic para cada payload
- `client/api.py`: Cliente HTTP reutilizável
- `client/websocket.py`: Cliente WS com reconexão + fila offline
- `allowed_attachments.py`: Allowlist de MIME types
- `theme_manager.py`: Import/export de temas customizados

### Cliente Desktop (`client-desktop/`)

PySide6 (Qt) — padrão MVC.

- **Model**: `ClientState` — estado local (sessão, salas, mensagens, cache)
- **View**: `ui/main_window.py` + `ui/dialogs/` — 8 diálogos em módulos próprios
- **Controller**: `ChatController` — coordena state + service
- **Service**: `ConnectionService` — event loop asyncio em thread daemon
- **Threading**: `QThreadPool` via `utils/async_helper.py`

### Cliente CLI (`client-cli/`)

Typer + Rich — estilo IRC/WeeChat.

- 35+ comandos (/join, /dm, /create, /block, /fmsg, /upload, /theme, etc.)
- Input assíncrono (prompt_toolkit no Unix, msvcrt no Windows)
- Temas dark/light com import/export

## Banco de dados

Tabelas principais:

| Tabela | Descrição |
|---|---|
| `users` | Usuários (com is_guest, expires_at) |
| `rooms` | Salas (públicas/privadas, com senha) |
| `room_members` | Membros de salas (com role: owner/admin/member) |
| `messages` | Mensagens de sala |
| `private_messages` | DMs |
| `friendships` | Amizades (pending/accepted/blocked) |
| `sessions` | Sessões JWT (revogáveis) |
| `attachments` | Anexos (com validação MIME) |
| `login_attempts` | Tentativas de login (anti brute-force persistente) |
| `server_peers` | Servidores peer federados |
| `user_identity_keys` | Chaves E2E (Signal Protocol scaffold) |
| `one_time_prekeys` | Pool de PreKeys para X3DH |
| `federated_rooms` | Salas federadas (schema para futuro) |

## Segurança (defense in depth)

| Camada | Mecanismo |
|---|---|
| Senhas | Argon2 (19 MiB, time_cost=2) |
| Sessões | JWT HS256 + registro no banco |
| Anti brute-force | Por username (5/5min→10min) + por IP (20/5min→30min) |
| Rate limit REST | 60 req/min (10/min para login/register/guest) |
| Rate limit WS | 10 msg/5s → mute 30s |
| Anexos | Allowlist MIME + extensão, 10MB (1MB para guests) |
| CORS | Configurável, auto-detecção LAN |
| Federação | Assinatura Ed25519, peers registrados |
| Guests | Sem salas privadas, sem admin, anexos limitados |
