# Contribuindo para o ChatPy V2

Obrigado pelo interesse em contribuir! Este guia cobre o básico.

## Setup de desenvolvimento

```bash
# Clone o repositório
git clone https://github.com/your-org/chatpy.git
cd chatpy

# Instale dependências
pip install -r requirements.txt
pip install pytest pytest-asyncio

# Configure ambiente
# JWT_SECRET é auto-gerado se não configurado — mas para dev, defina explicitamente:
export JWT_SECRET="dev-secret-key-min-16-chars"
export DATABASE_URL="sqlite:///dev.db"

# Rode testes
pytest tests/ -v

# Inicie o servidor
uvicorn server.main:app --reload --port 5000

# Em outro terminal, inicie o cliente
python client-desktop/main.py
# ou
python client-cli/main.py
```

## Estrutura do projeto

```
chatpy/
├── server/              # Servidor FastAPI + WebSocket
│   ├── api/             # Endpoints REST (auth, rooms, friends, attachments, federation_admin)
│   ├── auth/            # Autenticação (Argon2, JWT, anti brute-force)
│   ├── database/        # Models SQLAlchemy + connection
│   ├── rooms/           # Lógica de salas
│   ├── users/           # Lógica de usuários e amizades
│   ├── websocket/       # Dispatcher WS, ConnectionManager, RateLimiter
│   ├── federation.py    # Federação entre servidores
│   ├── backup.py        # Backup automático SQLite
│   ├── metrics.py       # Métricas Prometheus
│   ├── rest_rate_limit.py  # Rate limiting REST
│   └── main.py          # App FastAPI + lifespan + endpoints diretos
├── shared/              # Código compartilhado entre server e clientes
│   ├── client/          # ApiClient (HTTP) + WebSocketClient
│   ├── events/          # Enum de eventos do protocolo
│   ├── protocol/        # Schemas Pydantic dos payloads
│   └── allowed_attachments.py  # Allowlist de MIME types
├── client-desktop/      # Cliente PySide6 (Qt)
│   ├── controllers/     # ChatController (coordena state + service)
│   ├── models/          # ClientState (estado local)
│   ├── services/        # ConnectionService (asyncio loop + Qt signals)
│   ├── ui/              # MainWindow + diálogos + helpers + theme
│   │   └── dialogs/     # Diálogos extraídos (join, create, explore, admin, etc.)
│   └── utils/           # async_helper (QThreadPool)
├── client-cli/          # Cliente Typer + Rich
│   ├── main.py          # Lógica principal + comandos
│   └── views/           # Layout Rich (interface.py)
├── tests/               # Testes (pytest)
├── docs/                # Documentação
├── alembic/             # Migrations de schema
└── scripts/             # Scripts (migrate, build)
```

## Como adicionar um novo evento WebSocket

1. **Adicionar EventType** em `shared/events/__init__.py`:
   ```python
   MY_NEW_EVENT = "my.new_event"
   ```

2. **Criar payload Pydantic** em `shared/protocol/client_events.py` (client→server) ou `server_events.py` (server→client):
   ```python
   class MyNewEventPayload(BaseModel):
       field: str = Field(...)
   ```

3. **Registrar no mapa** em `shared/protocol/__init__.py`:
   ```python
   EventType.MY_NEW_EVENT: MyNewEventPayload,
   ```

4. **Handler no dispatcher** em `server/websocket/dispatcher.py`:
   ```python
   elif event == EventType.MY_NEW_EVENT:
       await self._handle_my_event(authenticated_user_id, frame.payload)
   ```

5. **Método no WebSocketClient** em `shared/client/websocket.py`:
   ```python
   async def send_my_event(self, ...):
       await self.send_frame(EventType.MY_NEW_EVENT, {...})
   ```

6. **Handler no controller** (Desktop) ou `handle_ws_event` (CLI).

7. **Teste** em `tests/`.

## Como rodar testes

```bash
# Todos os testes (rate limit desativado para TestClient)
for f in tests/test_*.py; do
  DATABASE_URL="sqlite:///$(basename $f .py).db" \
  JWT_SECRET="test-secret-key-min-16-chars" \
  REST_RATE_LIMIT_ENABLED=false \
  pytest "$f" -v
done

# Teste específico
DATABASE_URL="sqlite:///test.db" JWT_SECRET="test-secret" pytest tests/test_server.py -v
```

## Convenções de código

- **Python 3.10+** — use type hints
- **Português** em docstrings e comentários (projeto é BR)
- **Inglês** em nomes de variáveis/funções
- **Pydantic v2** para schemas (use `model_validate` não `parse_obj`)
- **SQLAlchemy 2.0** com `declarative_base`
- **Signals Qt** para marshalling thread-safe no Desktop
- Nunca use `threading.Thread` direto no Desktop — use `run_in_background` de `utils/async_helper.py`

## CI/CD

Pushes para `main` e PRs disparam o CI em `.github/workflows/ci.yml`:
- Testes do servidor (Python 3.10/3.11/3.12)
- Lint com ruff
- Build do Docker

## Reportando bugs

Abra uma issue com:
1. Versão do servidor e cliente
2. Passos para reproduzir
3. Logs (use `LOG_FORMAT=json` para facilitar)
4. Comportamento esperado vs. atual
