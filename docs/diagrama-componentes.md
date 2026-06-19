# Diagrama de Componentes

```
chatpy/
├── server/                      # Servidor (FastAPI)
│   ├── api/                     # Endpoints REST
│   │   ├── auth.py              # Login, registro, guest, logout
│   │   ├── users.py             # Perfil, status, online
│   │   ├── rooms.py             # Salas CRUD, join/leave, members
│   │   ├── friends.py           # Amizades, bloqueios
│   │   ├── attachments.py       # Upload/download de anexos
│   │   ├── federation_admin.py  # Admin de peers federados
│   │   ├── e2e_keys.py          # Chaves E2E (Signal Protocol)
│   │   └── dependencies.py      # get_current_user (JWT + sessão)
│   ├── auth/                    # Lógica de autenticação
│   │   ├── security.py          # Argon2, JWT, validação
│   │   └── service.py           # registrar, autenticar, brute-force
│   ├── database/                # SQLAlchemy
│   │   ├── connection.py        # Engine, sessionmaker, get_db
│   │   └── models.py            # 12 modelos (User, Room, etc.)
│   ├── rooms/                   # Lógica de salas
│   ├── users/                   # Lógica de usuários e amizades
│   ├── websocket/               # WebSocket
│   │   ├── dispatcher.py        # Roteamento de eventos WS
│   │   ├── manager.py           # ConnectionManager
│   │   └── rate_limit.py        # Rate limiter anti-flood
│   ├── federation.py            # Federação entre servidores
│   ├── backup.py                # Backup automático SQLite
│   ├── bots.py                  # Framework de bots
│   ├── metrics.py               # Métricas Prometheus
│   ├── rest_rate_limit.py       # Rate limiting REST
│   ├── lan_discovery.py         # Descoberta mDNS
│   ├── logging_config.py        # Logging JSON
│   ├── static/admin.html        # Painel admin web
│   └── main.py                  # App FastAPI + lifespan + endpoints
│
├── shared/                      # Compartilhado (servidor + clientes)
│   ├── events/__init__.py       # Enum EventType
│   ├── protocol/                # Schemas Pydantic
│   ├── client/                  # ApiClient + WebSocketClient
│   ├── allowed_attachments.py   # Allowlist MIME
│   └── theme_manager.py         # Import/export temas
│
├── client-desktop/              # Cliente Desktop (PySide6)
│   ├── controllers/             # ChatController
│   ├── models/                  # ClientState
│   ├── services/                # ConnectionService
│   ├── ui/                      # Interface
│   │   ├── main_window.py       # Janela principal
│   │   ├── helpers.py           # Helpers compartilhados
│   │   ├── theme.py             # Temas dark/light
│   │   └── dialogs/             # 8 diálogos extraídos
│   ├── utils/                   # async_helper (QThreadPool)
│   └── main.py                  # Entry point
│
├── client-cli/                  # Cliente CLI (Typer + Rich)
│   ├── main.py                  # Lógica + 35+ comandos
│   └── views/interface.py       # Layout Rich + temas
│
├── tests/                       # 54 testes (pytest)
├── alembic/                     # Migrations de schema
├── docs/                        # Documentação
├── scripts/                     # Scripts (build, migrate)
├── .github/workflows/ci.yml     # CI/CD
├── Dockerfile                   # Multi-stage build
├── docker-compose.yml           # SQLite default + Postgres/Redis opcional
├── requirements.txt             # Dependências servidor
├── requirements-cli.txt         # Dependências CLI
├── CONTRIBUTING.md              # Guia de contribuição
├── ARCHITECTURE.md              # Arquitetura detalhada
└── README.md                    # Este arquivo
```
