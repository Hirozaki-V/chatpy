# Estrutura de Diretórios

```
chatpy/
├── server/                  # Servidor FastAPI + WebSocket
│   ├── api/                 # Endpoints REST (8 módulos)
│   ├── auth/                # Autenticação (Argon2, JWT, brute-force)
│   ├── database/            # Models SQLAlchemy + connection
│   ├── rooms/               # Lógica de salas
│   ├── users/               # Lógica de usuários e amizades
│   ├── websocket/           # Dispatcher, manager, rate limiter
│   ├── static/              # Painel admin HTML
│   ├── federation.py        # Federação entre servidores
│   ├── backup.py            # Backup automático
│   ├── bots.py              # Framework de bots
│   ├── metrics.py           # Métricas Prometheus
│   ├── rest_rate_limit.py   # Rate limiting REST
│   ├── lan_discovery.py     # Descoberta mDNS
│   ├── logging_config.py    # Logging JSON estruturado
│   └── main.py              # App principal
│
├── shared/                  # Código compartilhado
│   ├── events/              # EventType enum
│   ├── protocol/            # Schemas Pydantic
│   ├── client/              # ApiClient + WebSocketClient
│   ├── allowed_attachments.py
│   └── theme_manager.py
│
├── client-desktop/          # Cliente PySide6
│   ├── controllers/
│   ├── models/
│   ├── services/
│   ├── ui/
│   │   └── dialogs/         # 8 diálogos modulares
│   ├── utils/
│   └── main.py
│
├── client-cli/              # Cliente terminal
│   ├── views/
│   └── main.py
│
├── tests/                   # 54 testes pytest
├── alembic/                 # Migrations
├── docs/                    # Documentação
├── scripts/                 # Scripts utilitários
├── legacy/                  # Código V1 (referência)
├── .github/workflows/       # CI/CD
├── Dockerfile
├── docker-compose.yml
└── requirements*.txt
```

Convenções:
- **server/**: código que roda no servidor (nunca no cliente)
- **shared/**: código usado por servidor E clientes (DRY)
- **client-*/**: código específico de cada cliente
- **tests/**: um arquivo por área (test_server, test_friendship, etc.)
- **docs/**: um arquivo por tópico
