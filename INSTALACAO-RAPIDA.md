# 🚀 ChatPy V2 — Instalação Rápida (Windows)

Este zip contém o projeto **COMPLETO** com todas as correções já aplicadas.
Siga os passos abaixo para rodar.

---

## ⚡ Passo a passo (5 minutos)

### 1. Backup do projeto atual (recomendado)

```powershell
# No PowerShell
cd C:\Projetos
Rename-Item ChatPy ChatPy.old
```

### 2. Descompactar o zip no destino final

```powershell
# Descompacte o conteúdo de ChatPy-final.zip diretamente em:
# C:\Projetos\ChatPy

# A pasta final deve conter: server/, shared/, client-cli/, client-desktop/,
# docker-compose.yml, Dockerfile, .env.example, etc.
```

### 3. Criar o arquivo `.env` com JWT_SECRET

```powershell
cd C:\Projetos\ChatPy

# Copia o template
Copy-Item .env.example .env

# Gera uma chave JWT aleatória
python -c "import secrets; print(secrets.token_urlsafe(48))"

# Abre o .env no bloco de notas e cola a chave gerada na linha JWT_SECRET=...
notepad .env
```

O `.env` deve ficar assim (com sua chave real):
```
JWT_SECRET=sua-chave-aleatoria-gerada-acima
DATABASE_URL=sqlite:////app/data/chatpy.db
CORS_ORIGINS=http://localhost,http://127.0.0.1
LOG_LEVEL=INFO
UPLOAD_DIR=/app/uploads
```

### 4. Instalar dependências Python

```powershell
# Dependências do servidor
pip install -r requirements.txt

# Dependências do cliente Desktop (PySide6)
pip install -r requirements-desktop.txt

# OU instale tudo de uma vez:
pip install -r all-requirements.txt
```

### 5. Subir o servidor

#### Opção A: Via Docker (recomendado)

```powershell
docker compose up -d --build

# Verificar que está rodando:
curl http://localhost:5000/health
# Esperado: {"status":"healthy","database":"ok","version":"2.0.1"}
```

#### Opção B: Direto com uvicorn (sem Docker)

```powershell
# Em um terminal separado, na pasta do projeto
$env:JWT_SECRET = "sua-chave-aleatoria"
$env:DATABASE_URL = "sqlite:///chatpy.db"
uvicorn server.main:app --host 0.0.0.0 --port 5000
```

### 6. Rodar o cliente Desktop

```powershell
# Em OUTRO terminal, na pasta do projeto
python client-desktop/main.py
```

### 7. Primeiro acesso (banco está vazio)

Na tela de login, clique em **CADASTRAR**:
- Username: `usuario` (mínimo 3 chars, sem espaços)
- Senha: uma senha forte (mínimo 8 chars, com letra e número)
  - Ex: `SenhaSegura123`

Depois faça login normalmente.

---

## 🧪 Como verificar que está tudo funcionando

```powershell
# 1. Healthcheck
curl http://localhost:5000/health

# 2. Registro com senha fraca (deve ser rejeitado)
curl -X POST http://localhost:5000/api/auth/register `
  -H "Content-Type: application/json" `
  -d '{\"username\":\"teste\",\"password\":\"123\"}'
# Esperado: 422 ou 400

# 3. Login com senha curta NÃO deve retornar 422 (apenas 401)
curl -X POST http://localhost:5000/api/auth/login `
  -H "Content-Type: application/json" `
  -d '{\"username\":\"naoexiste\",\"password\":\"123\"}'
# Esperado: 401 "Usuário ou senha incorretos."
```

---

## 📁 Estrutura do projeto

```
ChatPy/
├── server/                  # Backend FastAPI (CORRIGIDO)
│   ├── api/                 # Endpoints REST (auth, users, rooms, friends, attachments)
│   ├── auth/                # Argon2 + JWT + anti brute-force
│   ├── database/            # SQLAlchemy + SQLite WAL
│   ├── websocket/           # Dispatcher + Manager + RateLimiter thread-safe
│   ├── main.py              # FastAPI app com lifespan, CORS, /health
│   └── ...
├── shared/                  # Camada compartilhada server + clients
│   ├── client/              # ApiClient + WebSocketClient (com reconexão + re-auth)
│   ├── events/              # EventType (inclui ROOM_CREATED, FRIEND_REMOVED)
│   ├── protocol/            # Pydantic schemas para eventos WS
│   └── types/               # Modelos compartilhados
├── client-cli/              # CLI Typer + Rich
│   └── main.py              # USA shared/client/* (não duplica mais)
├── client-desktop/          # GUI PySide6
│   ├── controllers/         # ChatController com sanitização HTML
│   ├── services/            # ConnectionService sem busy-wait
│   ├── ui/                  # MainWindow, LoginDialog, theme
│   └── models/              # ClientState
├── docs/                    # 13 markdowns de documentação
├── tests/                   # Testes pytest
├── legacy/                  # Código V1 antigo (referência histórica)
├── scripts/                 # Scripts de migração
├── Dockerfile               # Multi-stage build + healthcheck
├── docker-compose.yml       # JWT_SECRET obrigatório + healthcheck em todos serviços
├── .env.example             # Template de variáveis de ambiente
├── .dockerignore            # Reduz tamanho da imagem Docker
├── requirements.txt         # Servidor (inclui python-dotenv)
├── requirements-cli.txt     # Cliente CLI
├── requirements-desktop.txt # Cliente Desktop
├── all-requirements.txt     # Tudo + pytest
├── README.md                # Documentação principal
└── LEIA-ME-CORRECOES.md     # Lista detalhada de todas as correções
```

---

## ✅ Correções aplicadas (resumo)

### 🔴 P0 — Críticas
1. `docker-compose.yml` agora injeta `JWT_SECRET` (obrigatório) + healthcheck
2. `.env` carregado automaticamente via `python-dotenv`
3. **WebSocket valida sessão no BD** (token revogado = invalidado imediatamente)
4. Endpoint `POST /api/auth/logout` que revoga sessão
5. **Anti brute-force**: 5 tentativas → 10 min de lockout (429)
6. **Força de senha no registro**: mínimo 8 chars + letra + número
7. **Login permissivo**: aceita qualquer senha (deixa o BD decidir) — não bloqueia usuários antigos
8. **Upload com ALLOWLIST de MIME types** + sanitização de filename
9. CLI usa `shared/client/*` (DRY), porta default `5000`, sanitiza ANSI
10. **Desktop sanitiza conteúdo via `html.escape`** (previne XSS visual)
11. `FRIEND_REMOVED` mapeado no protocolo
12. **Bug do `get_db()` corrigido**: commit sempre que há transação ativa

### 🟡 P1 — Importantes
13. Evento `room.created` dedicado (sem abuso de `error.alert`)
14. **N+1 queries corrigidas** em `/rooms/history` e `/rooms/explore`
15. Migração para `lifespan` context manager (sem `@app.on_event` deprecated)
16. CORS configurável via `CORS_ORIGINS`
17. Endpoint `/health` para Docker
18. RateLimiter thread-safe
19. SQLite PRAGMAs: WAL mode + busy_timeout + foreign_keys
20. `asyncio.get_event_loop()` deprecated → `get_running_loop()`
21. `ConnectionService` sem busy-wait (usa `threading.Event`)
22. Reconexão WS faz `await listener_task` (sem tasks órfãs)
23. Validação de conteúdo (vazio, máximo 5000 chars, sem DM para si)
24. Sessões expiradas auto-limpadas
25. `httpx` com timeouts explícitos

### 🟢 P2 — Desejáveis
26. Dockerfile multi-stage + `tini` + `curl` para healthcheck
27. `.dockerignore` (imagem menor)
28. Logging estruturado com `LOG_LEVEL` via env
29. `requirements-*.txt` organizados (servidor / CLI / desktop / tudo)
30. Desktop trata novos eventos (`room.created`, `dm.start_success`, `friend.removed`)

---

## 🗑️ Arquivos removidos deste zip (lixo do projeto original)

- `temp_req.txt`, `temp_req2.txt`, `temp_requests.txt` — rascunhos de prompt
- `requirements-fixed.txt` — versão antiga confusa
- `client-cli/services/api_client.py` — CLI agora usa `shared/client/api.py`
- `client-cli/services/websocket_client.py` — CLI agora usa `shared/client/websocket.py`
- `chatpy.db`, `test_advanced_rooms.db` — bancos de teste antigos
- `uploads/` — será criada automaticamente
- `__pycache__/` — cache Python, recriado automaticamente
- `.git/` — histórico de versionamento (mantenha o seu próprio controle de versão)

---

## ❓ Problemas comuns

### "docker compose up falha com 'JWT_SECRET é obrigatório'"

Você não criou o arquivo `.env` ou ele está vazio. Volte ao Passo 3.

### "Login retorna 422 mesmo com senha correta"

Você está rodando o servidor com código antigo. Pare o servidor e rode novamente:
```powershell
docker compose down
docker compose up -d --build   # o --build é OBRIGATÓRIO
```

### "Cliente Desktop não conecta ao WebSocket"

1. Verifique que o servidor está rodando: `curl http://localhost:5000/health`
2. Verifique que não há firewall bloqueando a porta 5000
3. Verifique os logs do servidor para ver se há erros

### "Erro ao salvar anexo no banco"

Você está rodando sem Docker e o diretório `uploads/` não existe. Crie manualmente:
```powershell
mkdir uploads
```

---

## 📞 Próximos passos recomendados (não implementados ainda)

1. **Migrar para SQLAlchemy Async** (`create_async_engine` + `aiosqlite`) — elimina `asyncio.to_thread`
2. **Rate limiting via Redis** (com fallback em memória) — necessário para multi-worker
3. **Quebrar `main_window.py` (1741 linhas)** em `ui/dialogs/*.py` e `ui/widgets/*.py`
4. **Adicionar Alembic** para migrações de schema
5. **E2EE para DMs** (Fase V2 do roadmap)
6. **Adicionar CI/CD** (GitHub Actions rodando `pytest`)
7. **Atualizar `docs/protocolo.md`** — ainda referencia `/api/invites/*` removidos
8. **Corrigir `tests/test_endpoints.py`** — ainda testa `/api/invites`

Consulte `LEIA-ME-CORRECOES.md` para a lista completa detalhada.

---

**Dúvidas?** Consulte `LEIA-ME-CORRECOES.md` para o changelog completo ou o `README.md` original para a documentação geral do projeto.
