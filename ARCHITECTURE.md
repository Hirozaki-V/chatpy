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

**FastAPI + Uvicorn + SQLAlchemy + WebSocket**

- **API REST**: auth, rooms, friends, attachments, federation admin, version, metrics
- **WebSocket**: dispatcher roteia eventos por tipo (auth, message, room, typing, federated)
- **Auth**: Argon2 (password hashing), JWT (sessões), anti brute-force persistente (SQLite)
- **Rate limiting**: REST (middleware global, 60 req/min) + WebSocket (10 msg/5s)
- **Federação**: DMs cross-server via HTTP com assinatura Ed25519
- **Background jobs**: limpeza de anexos órfãos, purga de guests, backup SQLite
- **Observabilidade**: métricas Prometheus, logging JSON estruturado, healthcheck multi-componente

### Shared (`shared/`)

**Contratos compartilhados entre servidor e clientes (DRY)**

- `events/`: Enum `EventType` com todos os eventos do protocolo
- `protocol/`: Schemas Pydantic para cada payload (validação automática)
- `client/api.py`: `ApiClient` — cliente HTTP reutilizável
- `client/websocket.py`: `WebSocketClient` — cliente WS com reconexão automática
- `allowed_attachments.py`: Allowlist de MIME types (servidor + desktop usam a mesma)

### Cliente Desktop (`client-desktop/`)

**PySide6 (Qt) — padrão MVC**

- **Model**: `ClientState` — estado local (sessão, salas, mensagens, amigos, cache)
- **View**: `ui/main_window.py` + `ui/dialogs/` — 8 diálogos extraídos em módulos próprios
- **Controller**: `ChatController` — coordena state + service, emite signals Qt
- **Service**: `ConnectionService` — mantém event loop asyncio em thread daemon
- **Threading**: `QThreadPool` via `utils/async_helper.py` — todas operações em background

### Cliente CLI (`client-cli/`)

**Typer + Rich — estilo IRC/WeeChat**

- `main.py`: lógica principal, 30+ comandos (/join, /dm, /create, /fmsg, /upload, etc.)
- `views/interface.py`: layout Rich com painéis, temas dark/light
- Input assíncrono via `prompt_toolkit` (Unix) ou `msvcrt` (Windows)

## Protocolo de comunicação

### REST (HTTP)

| Método | Endpoint | Descrição |
|---|---|---|
| POST | /api/auth/register | Cadastro |
| POST | /api/auth/login | Login |
| POST | /api/auth/guest | Conta de convidado |
| POST | /api/auth/logout | Logout (revoga sessão) |
| GET | /api/users/me | Perfil |
| GET | /api/users/online | Usuários online |
| PUT | /api/users/status | Mudar status |
| GET/POST | /api/rooms | Listar/criar salas |
| POST | /api/rooms/{id}/join | Entrar em sala |
| GET | /api/rooms/{id}/history | Histórico |
| GET/POST/PUT/DELETE | /api/friends/* | Amizades |
| POST/GET | /api/attachments/* | Anexos |
| GET/POST/DELETE | /api/admin/peers/* | Federação |
| GET | /api/version | Versão (auto-update) |
| GET | /metrics | Métricas Prometheus |
| GET | /health | Healthcheck |
| GET | /.well-known/chatpy.json | Descoberta de federação |

### WebSocket

Eventos client→server:
- `auth.authenticate` — autentica conexão WS
- `message.send_room` — envia mensagem para sala
- `message.send_private` — envia DM local
- `message.send_federated` — envia DM para outro servidor
- `room.join` / `room.create` — gerencia salas
- `dm.start` — inicia conversa DM
- `user.typing` — indicador de digitação

Eventos server→client:
- `auth.success` — autenticação confirmada
- `message.receive` — mensagem recebida (sala, DM, ou federada)
- `user.presence` — mudança de presença
- `user.typing_broadcast` — alguém está digitando
- `room.created` — sala criada com sucesso
- `friend.request_received/accepted/removed` — eventos de amizade
- `error.alert` — erro

## Segurança

| Camada | Mecanismo |
|---|---|
| Senhas | Argon2 (19 MiB memory, time_cost=2) |
| Sessões | JWT HS256 + registro no banco (revogação imediata) |
| Anti brute-force | Por username (5 tentativas/5min → 10min lock) + por IP (20/5min → 30min lock) |
| Rate limit REST | 60 req/min por IP (10 req/min para endpoints sensíveis) |
| Rate limit WS | 10 msg/5s → mute 30s |
| Anexos | Allowlist MIME + extensão, 10MB (1MB para guests) |
| CORS | Configurável, auto-detecção de IP LAN |
| Federação | Assinatura Ed25519, peers registrados ou open_federation |
| Guests | Não criam salas privadas, não são admin, anexos limitados |
| Logging | JSON estruturado (production), text (dev) |

## Decisões de design

1. **SQLite default**: zero configuração, ideal para Raspberry Pi. Postgres como upgrade.
2. **shared/ como pacote separado**: DRY real — servidor e clientes usam os mesmos schemas.
3. **Event loop dedicado no Desktop**: Qt roda na main thread, asyncio numa thread daemon, marshalling via signals.
4. **Federação via HTTP não WS**: mais simples, mais resiliente (retry natural), não exige conexão persistente entre servidores.
5. **Mode convidado**: alinha com promessa de anonimato — "entrar e falar" sem cadastro.
6. **Rate limiting em camadas**: REST (global + sensível), WS (flood), auth (brute-force) — defense in depth.
