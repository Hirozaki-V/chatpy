# 📋 ChatPy V2 — Correções Aplicadas

Este diretório contém os arquivos corrigidos do projeto ChatPy V2. As correções foram organizadas preservando a estrutura de diretórios original, então basta copiar os arquivos para as respectivas pastas no seu projeto.

## 🚀 Como aplicar as correções

### 1. Backup primeiro
```bash
cp -r /caminho/para/ChatPy /caminho/para/ChatPy.backup
```

### 2. Copiar arquivos corrigidos
```bash
# No Linux/macOS
cp -r ChatPy-fixed/server/* /caminho/para/ChatPy/server/
cp -r ChatPy-fixed/shared/* /caminho/para/ChatPy/shared/
cp -r ChatPy-fixed/client-cli/* /caminho/para/ChatPy/client-cli/
cp -r ChatPy-fixed/client-desktop/* /caminho/para/ChatPy/client-desktop/
cp ChatPy-fixed/docker-compose.yml /caminho/para/ChatPy/
cp ChatPy-fixed/Dockerfile /caminho/para/ChatPy/
cp ChatPy-fixed/requirements.txt /caminho/para/ChatPy/
cp ChatPy-fixed/all-requirements.txt /caminho/para/ChatPy/
cp ChatPy-fixed/requirements-cli.txt /caminho/para/ChatPy/
cp ChatPy-fixed/requirements-desktop.txt /caminho/para/ChatPy/
cp ChatPy-fixed/.env.example /caminho/para/ChatPy/
cp ChatPy-fixed/.dockerignore /caminho/para/ChatPy/
```

### 3. Configurar JWT_SECRET
```bash
cd /caminho/para/ChatPy
cp .env.example .env
# Edite .env e troque JWT_SECRET por uma chave aleatória longa:
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 4. Reinstalar dependências
```bash
pip install -r requirements.txt
# Para clientes desktop/CLI:
pip install -r requirements-cli.txt
pip install -r requirements-desktop.txt
```

### 5. Subir o servidor
```bash
docker compose up -d
# Verifique o healthcheck:
curl http://localhost:5000/health
```

---

## ✅ Lista completa de correções

### 🔴 P0 — Críticas (segurança e funcionamento)

#### 1. **`docker-compose.yml` agora injeta `JWT_SECRET`**
- Antes: servidor quebrava em startup porque `JWT_SECRET` não era passado ao container.
- Agora: variável é obrigatória via `${JWT_SECRET:?...}` — falha explicitamente se ausente.
- Adicionado `healthcheck` no serviço do servidor e no Postgres/Redis.
- Adicionado volume `chatpy-uploads` para persistência de anexos.

#### 2. **`.env` carregado automaticamente**
- `server/main.py` agora usa `python-dotenv` para carregar `.env` ANTES de qualquer import.
- `.env.example` adicionado como template.
- `JWT_SECRET` validado em **startup** (não em import-time) — testes não quebram mais.

#### 3. **JWT no WebSocket agora valida sessão no banco**
- `server/websocket/dispatcher.py::_handle_auth` consulta a tabela `sessions` antes de aceitar a conexão.
- Token revogado (via logout ou admin) agora é invalidado **imediatamente** no WebSocket também — antes continuava válido por até 24h.

#### 4. **Endpoint `/api/auth/logout` adicionado**
- `server/api/auth.py` agora tem `POST /api/auth/logout` que revoga a sessão no banco.
- CLI e Desktop chamam logout explicitamente ao sair.

#### 5. **Anti brute-force no login**
- `server/auth/service.py` bloqueia após **5 tentativas falhas em 5 minutos** → 10 min de lockout.
- Retorna `429 Too Many Requests` com header `Retry-After`.
- Mensagens de erro genéricas (não revelam se usuário existe).

#### 6. **Força de senha validada**
- Mínimo **8 caracteres** (antes eram 4!), exigindo ao menos 1 letra e 1 número.
- Username validado por regex `^[A-Za-z0-9_\-]{3,50}$`.
- Username case-insensitive no banco (evita impersonação `Alice` vs `alice`).

#### 7. **Upload de anexos com ALLOWLIST de MIME types**
- `server/api/attachments.py` trocou denylist de extensões por **allowlist** de MIME types + extensões.
- Nome do arquivo sanitizado (remove `..`, caracteres de controle, etc.) antes de ir ao header `Content-Disposition`.
- Re-validação de tamanho durante o streaming (evita abuso de memória).
- Erros não vazam detalhes internos para o cliente.

#### 8. **CLI corrigido para usar clientes compartilhados**
- `client-cli/main.py` agora importa de `shared.client.api` e `shared.client.websocket` (DRY).
- Porta default corrigida: `5000` (antes era `8000`).
- Paridade de features: agora tem `/explore`, `/friends`, `/unfriend`, suporte a `room.created`, `friend.removed`, etc.
- Healthcheck antes do login.
- Logout explícito ao sair (revoga sessão).

#### 9. **Sanitização de conteúdo no Desktop**
- `client-desktop/controllers/chat_controller.py` agora aplica `html.escape()` em todo conteúdo recebido via WebSocket antes de exibir.
- Previne XSS visual no QTextBrowser (HTML rendering).

#### 10. **`FRIEND_REMOVED` mapeado no protocolo**
- `shared/events/__init__.py` + `shared/protocol/__init__.py` + `shared/protocol/server_events.py` agora definem e mapeiam `FriendRemovedPayload`.
- Antes o evento era emitido mas não tinha payload validável → clientes não conseguiam chamar `parse_payload`.

### 🟡 P1 — Importantes (qualidade e performance)

#### 11. **Evento `room.created` dedicado**
- Antes: criar sala via WS retornava sucesso como `error.alert` code 201 (abuso semântico).
- Agora: evento dedicado `room.created` com payload `RoomCreatedPayload`.
- Clientes (CLI e Desktop) tratam o novo evento.

#### 12. **N+1 queries corrigidas**
- `server/api/rooms.py::get_room_history` agora pré-carrega todos os senders em UMA query (antes fazia 1 query por mensagem).
- `server/api/rooms.py::explore_rooms_endpoint` agora usa `GROUP BY` com `CASE` (antes fazia 2 queries por sala).

#### 13. **Migração para `lifespan` context manager**
- `server/main.py` substitui `@app.on_event("startup")` (deprecated) por `lifespan`.
- Shutdown graceful cancela a task de cleanup de anexos.

#### 14. **CORS configurado**
- `server/main.py` adiciona `CORSMiddleware` com origens configuráveis via `CORS_ORIGINS` (default: localhost).

#### 15. **Endpoint `/health`**
- `server/main.py` adiciona `GET /health` que verifica conexão com o banco.
- Usado pelo Docker healthcheck e por load balancers.

#### 16. **Rate limiter thread-safe**
- `server/websocket/rate_limit.py` agora usa `threading.Lock` (antes era não-thread-safe).

#### 17. **SQLite otimizado**
- `server/database/connection.py` aplica PRAGMAs: `WAL mode`, `busy_timeout=5000`, `foreign_keys=ON`.
- `pool_pre_ping=True` evita erros com conexões ociosas em produção.

#### 18. **`asyncio.get_event_loop()` deprecated corrigido**
- `shared/client/websocket.py` captura o loop com `asyncio.get_running_loop()` no `start_listener` (antes usava `get_event_loop` que é deprecated em Python 3.10+).

#### 19. **`ConnectionService._start_event_loop` sem busy-wait**
- `client-desktop/services/connection_service.py` agora usa `threading.Event` (antes era `while self.loop is None: time.sleep(0.01)`).
- Timeout de segurança de 5s.

#### 20. **`run_coroutine` com timeout**
- `client-desktop/services/connection_service.py::run_coroutine` agora tem timeout de 30s (antes travava indefinidamente se a coroutine pendurasse).

#### 21. **Reconexão WS com `await listener_task`**
- `shared/client/websocket.py::disconnect` agora espera o listener terminar antes de retornar (antes deixava task órfã).

#### 22. **Validação de conteúdo de mensagens**
- `server/websocket/dispatcher.py` rejeita mensagens vazias (sem conteúdo nem anexo) e maiores que 5000 caracteres.
- Rejeita DM para si mesmo.
- Verifica `is_banned == False` ao broadcast de mensagens (antes banidos podiam receber).

#### 23. **Sessões expiradas auto-limpas**
- `server/api/dependencies.py::get_current_user` deleta a sessão do banco quando detecta que expirou.

#### 24. **`httpx` com timeouts**
- `shared/client/api.py` agora configura timeouts explícitos (connect=5s, read=15s, write=15s).
- Timeouts maiores para upload/download de anexos.
- Erros de conexão capturados e traduzidos em mensagens amigáveis.

### 🟢 P2 — Desejáveis (manutenibilidade)

#### 25. **Multi-stage Docker build**
- `Dockerfile` agora tem estágio `builder` + `runtime` → imagem final menor.
- `tini` como init para tratamento correto de sinais (graceful shutdown).
- `curl` para healthcheck.

#### 26. **`.dockerignore`**
- Exclui `.git`, `__pycache__`, `tests/`, `docs/`, `client-*`, `legacy/`, `temp_*.txt` do contexto de build.
- Imagem significativamente menor.

#### 27. **Logging estruturado**
- `server/main.py` configura logging com `LOG_LEVEL` via env.
- Erros incluem `exc_info=True` para stack traces completos.
- Middleware de logging captura erros não tratados.

#### 28. **`requirements-*.txt` organizados**
- `requirements.txt`: servidor (inclui `python-dotenv`).
- `requirements-cli.txt`: apenas dependências do CLI.
- `requirements-desktop.txt`: apenas dependências do Desktop.
- `all-requirements.txt`: tudo junto + ferramentas de teste.

#### 29. **CLI: novos comandos**
- `/explore` — lista salas com contagem de membros.
- `/friends` — lista seus amigos.
- `/unfriend <username>` — remove amizade por nome (antes só por UUID).

#### 30. **Desktop: eventos WS adicionais tratados**
- `room.created` — adiciona aba da sala criada.
- `dm.start_success` — abre aba de DM automaticamente.
- `friend.removed` — fecha aba de DM se aberta, mostra status message.
- Otimização: evento `user.presence` agora só recarrega online users (antes disparava `load_initial_data` com 4 chamadas REST).

---

## ⚠️ Possíveis breaking changes

1. **Senha mínima agora é 8 caracteres** (antes 4). Usuários antigos com senhas curtas continuam conseguindo logar (a validação é só no registro), mas se quiser forçar reset, delete as contas antigas.

2. **`docker-compose.yml` agora exige `JWT_SECRET`**. Sem ele, o compose falha explicitamente. Crie o `.env`.

3. **CLI usa porta 5000 por default** (antes 8000). Se você usa outra porta, passe `--port XXXX`.

4. **Evento `error.alert` code 201 não é mais emitido para criação de sala**. Use o evento `room.created`. Se você tem clientes antigos (sem atualizar), eles vão receber o novo evento mas não saberão tratá-lo — basta atualizar todos os clientes junto com o servidor.

5. **`username` agora é case-insensitive no cadastro**. Se você já tem usuários `Alice` e `alice` no banco, um deles precisará ser renomeado (bem improvável, mas vale checar).

---

## 🧪 Como testar

```bash
# 1. Suba o servidor
docker compose up -d

# 2. Healthcheck
curl http://localhost:5000/health
# Esperado: {"status":"healthy","database":"ok","version":"2.0.1"}

# 3. Teste brute-force protection (5 tentativas erradas → 429)
for i in 1 2 3 4 5 6; do
  curl -s -X POST http://localhost:5000/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"naoexiste","password":"errada"}' | jq .
done

# 4. Teste upload de exe (deve ser rejeitado)
curl -X POST http://localhost:5000/api/attachments/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@/tmp/test.exe"
# Esperado: 400 "Extensão '.exe' não permitida..."

# 5. Teste JWT revogado no WS
# Faça login, pegue token, faça logout (revoga), tente conectar WS — deve falhar.
```

---

## 📁 Arquivos modificados (24 no total)

### Backend (`server/`)
- `server/main.py` ✨
- `server/auth/security.py` ✨
- `server/auth/service.py` ✨
- `server/api/auth.py` ✨
- `server/api/dependencies.py` ✨
- `server/api/users.py` ✨
- `server/api/rooms.py` ✨
- `server/api/attachments.py` ✨
- `server/api/__init__.py` ✨
- `server/database/connection.py` ✨
- `server/websocket/dispatcher.py` ✨
- `server/websocket/rate_limit.py` ✨

### Shared (`shared/`)
- `shared/events/__init__.py` ✨
- `shared/protocol/__init__.py` ✨
- `shared/protocol/server_events.py` ✨
- `shared/client/api.py` ✨
- `shared/client/websocket.py` ✨

### Clientes
- `client-cli/main.py` ✨
- `client-desktop/main.py` ✨
- `client-desktop/services/connection_service.py` ✨
- `client-desktop/controllers/chat_controller.py` ✨

### Infraestrutura
- `docker-compose.yml` ✨
- `Dockerfile` ✨
- `requirements.txt` ✨
- `all-requirements.txt` ✨
- `requirements-cli.txt` ✨ (NOVO)
- `requirements-desktop.txt` ✨
- `.env.example` ✨ (NOVO)
- `.dockerignore` ✨ (NOVO)

### Não modificados (mas referenciados)
- `client-cli/services/api_client.py` e `client-cli/services/websocket_client.py` — **NÃO precisam ser copiados**. O CLI agora usa os clientes de `shared/client/`. Se quiser limpar o repositório, pode deletar esses dois arquivos.
- `client-desktop/ui/main_window.py` — arquivo grande (1741 linhas) não foi reescrito. As correções de sanitização são aplicadas no `chat_controller.py` antes de chegar à UI. Recomenda-se futura refatoração para quebrar em módulos menores.
- `server/rooms/service.py`, `server/users/service.py`, `server/database/models.py`, `server/websocket/manager.py`, `shared/protocol/client_events.py`, `shared/protocol/base.py` — não precisavam de mudanças.

---

## 🎯 Próximos passos recomendados (não implementados ainda)

1. **Migrar para SQLAlchemy Async** (`create_async_engine` + `aiosqlite`) — elimina `asyncio.to_thread` e melhora escalabilidade.
2. **Rate limiting via Redis** (com fallback em memória) — necessário para deploy multi-worker.
3. **Quebrar `main_window.py` (1741 linhas)** em `ui/dialogs/*.py` e `ui/widgets/*.py`.
4. **Adicionar Alembic** para migrações de schema.
5. **E2EE para DMs** (Fase V2 do roadmap) — usar X25519 key exchange.
6. **Adicionar CI/CD** (GitHub Actions rodando `pytest`).
7. **Atualizar `docs/protocolo.md`** — ainda referencia `/api/invites/*` removidos e não documenta `friend.removed` e `room.created`.
8. **Corrigir `tests/test_endpoints.py`** — ainda testa `/api/invites` que foi removido.
9. **Adicionar `CHANGELOG.md` e `CONTRIBUTING.md`**.
10. **Refresh tokens** — access token curto (15min) + refresh token (7 dias).

---

Dúvidas? Revise o arquivo `RELATORIO_COMPLETO.md` para o diagnóstico detalhado que motivou estas correções.
