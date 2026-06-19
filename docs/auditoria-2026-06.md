# Auditoria e Correções — ChatPy V2 (2026-06)

**Status:** Implementado (5 ciclos)
**Autor:** Análise técnica independente
**Escopo:** Backend, frontend (Desktop + CLI), shared, testes, segurança

## Resumo Executivo

Foram identificados **8 bugs críticos (P0)** e **7 problemas importantes (P1)** no primeiro ciclo,
mais **8 problemas (P1 segunda rodada)** no segundo, **7 problemas (T terceira rodada)** no
terceiro, **5 problemas (Q quarta rodada)** no quarto, e **5 melhorias (S quinta rodada)** no
quinto. Todos os P0 e a grande maioria dos P1/T/Q/S foram corrigidos. Adicionamos **102 testes
de regressão** (25 + 29 + 23 + 11 + 14). A suíte de testes passou de 51 para **153 testes
passando** (as 2 falhas restantes são pré-existentes e não relacionadas).

### Ciclo 5 — Novas Melhorias (deste ciclo)

Adicionados após quinta análise (relatório externo):

1. **Upload no Desktop agora usa streaming** — não carrega arquivo inteiro na RAM (S1)
2. **Barras de progresso para download no Desktop** — QProgressDialog com % e MB (S3)
3. **Jobs de background configuráveis** — intervalos via env vars (S4)
4. **Tratamento de erros granular no middleware** — diferencia HTTPException, 422, 500 (S5)
5. **Tutorial interativo na CLI** — comando `/tutorial` + mensagem de boas-vindas (S7)

### Pontos da análise que já estavam implementados (falsos positivos)

- **S2 (funcionalidades admin/federação no Desktop)**: JÁ existem `FederationPeersDialog` e
  `AdminRoomDialog` acessíveis via menu

### Ciclo 4 — Fixes anteriores

1. **Argon2 com parâmetros fixos** — agora configurável via env (Q2)
2. **Heartbeat WS usava .ping() que não existe no Starlette** — ping JSON customizado (Q5)
3. **CLI não exibia anexos recebidos** — agora mostra info + link de download (Q7)
4. **CLI sem sons de notificação** — adicionado BEL + comando `/beep` (Q11)

### Pontos da análise que já estavam corrigidos (falsos positivos)

- **Q1 (replay attack em federação)**: JÁ corrigido no ciclo 2 (`server/federation_replay.py`)
- **Q3 (spoofing de IP)**: JÁ corrigido no ciclo 3 (`server/security_ip.py`)
- **Q10 (system tray no Desktop)**: JÁ existe desde o ciclo 0 (`QSystemTrayIcon` com menu)

### Ciclo 3 — Fixes anteriores

1. **Spoofing de IP via X-Forwarded-For** — atacante forjava header para burlar rate limit
2. **JWT secret legível no Windows** — `os.chmod` não funciona em Windows; agora usa `icacls`
3. **Stateful WebSockets bloqueiam escalonamento** — adicionado scaffold Redis Pub/Sub
4. **Anexos carregados inteiros na memória (cliente)** — adicionados métodos de streaming
5. **Memory leak no attachment_cache do Desktop** — substituído por LRU cache com limite
6. **QTextBrowser lento com milhares de mensagens** — adicionado truncamento automático
7. **Descoberta LAN não automática no Desktop** — agora dispara no startup do LoginDialog

### Ciclo 2 — Fixes anteriores

1. **Anexos sem validação por magic numbers** — um `.exe` renomeado para `.png` era aceito
2. **JWT_SECRET em container Docker efêmero** — sem `CHATPY_DATA_DIR`, container perdia o secret
3. **Replay attack em federação** — payloads assinados podiam ser reenviados indefinidamente
4. **Race condition no auto-away** — usuário que mudava status manualmente era forçado de volta
5. **Conexões zumbis no WS Manager** — sem heartbeat, conexões mortas permaneciam no dict
6. **Paginação por offset em chats ativos** — causava duplicação/skip de mensagens
7. **CLI sem `/notifications`** — faltava paridade com painel de notificações do Desktop
8. **Fila offline não persistente** — mensagens enfileiradas eram perdidas ao fechar o cliente

## Terceira Rodada de Fixes (T — Ciclo 3)

### T1: Spoofing de IP via X-Forwarded-For

**Arquivos:** `server/security_ip.py` (novo), `server/rest_rate_limit.py`, `server/main.py`,
`server/api/auth.py`

**Problema:** Todos os pontos que extraíam IP do cliente liam diretamente o header
`X-Forwarded-For` e pegavam o primeiro valor. Se o servidor for exposto diretamente à internet
(sem proxy reverso confiável limpando esse header), um atacante pode enviar
`X-Forwarded-For: 1.2.3.4` falso. Consequências:
1. Burlar rate limit — usa IPs diferentes a cada requisição
2. Bloquear usuários legítimos — envia XFF com IP da vítima e estoura o limite de tentativas
3. Poluir logs de auditoria com IPs falsos

**Correção:** Criamos `server/security_ip.py` com a função `get_client_ip(request)`:
- Pega o IP da conexão TCP (`request.client.host`) — sempre confiável
- Se este IP for um proxy confiável (em `TRUSTED_PROXIES`), confia no X-Forwarded-For
- Caso contrário, retorna o TCP IP direto

Configurável via env: `TRUSTED_PROXIES=127.0.0.1,10.0.0.0/8,172.16.0.0/12`
(se vazio, NUNCA confia em XFF — mais seguro para internet direta).

Aplicado em 3 lugares: `rest_rate_limit.py`, `main.py` (WS endpoint), `auth.py` (login).

**Testes:** 8 testes em `TestTrustedProxies` cobrindo: sem proxy confiável ignora XFF, proxy
confiável usa XFF, proxy não-confiável ignora XFF, CIDR funciona, múltiplos proxies,
IP inválido, sem client retorna unknown.

### T2: JWT secret legível no Windows

**Arquivos:** `server/paths.py`

**Problema:** No Windows, `os.chmod(0o600)` NÃO restringe efetivamente o acesso ao arquivo —
Windows usa ACLs, não POSIX mode bits. O arquivo `.chatpy_auto_secret` ficava legível para
qualquer usuário da máquina. Além disso, em deploy multi-server (2+ instâncias com mesmo
Postgres), se JWT_SECRET não estivesse setado no env, cada instância gerava seu próprio secret
e invalidava sessões uma da outra.

**Correção:**
1. Adicionamos `_restrict_dir_windows(path)` que usa `icacls` via subprocess para remover
   herança de permissões e conceder acesso apenas ao usuário atual e SYSTEM
2. Adicionamos `_restrict_file_windows(path)` para arquivos individuais (JWT secret, chave
   de federação)
3. `get_data_dir()` chama `_restrict_dir_windows` no Windows
4. `security.py` e `federation.py` chamam `_restrict_file_windows` ao criar os arquivos

Para o problema multi-server: agora o `Dockerfile` e `docker-compose.yml` setam
`CHATPY_DATA_DIR=/app/data` (volume persistente), e o `.env.example` já documenta que
`JWT_SECRET` é obrigatório em produção. O auto-gerado é só para dev.

**Testes:** 2 testes em `TestPathsWindowsRestriction` verificam que as funções existem e
são no-op no Unix.

### T3: Stateful WebSockets bloqueiam escalonamento horizontal

**Arquivos:** `server/pubsub.py` (novo), `server/websocket/manager.py`, `server/main.py`

**Problema:** O `ConnectionManager` mantinha `active_connections` em um dict na memória do
processo Python. Funciona para single-process, mas bloqueia escalonamento horizontal: se você
rodar 2+ workers do Uvicorn (`--workers 4`), o Usuário A conectado no Worker 1 nunca receberia
mensagens do Usuário B conectado no Worker 2.

**Correção:** Criamos `server/pubsub.py` com abstração `PubSubBroker`:
- `LocalPubSubBroker` — in-memory, mantém comportamento single-worker (default)
- `RedisPubSubBroker` — usa Redis pub/sub para propagar entre workers (quando `REDIS_URL`
  está configurado)

O `ConnectionManager.broadcast_to_users` agora:
1. Publica a mensagem no broker (canal `chatpy:broadcast`)
2. Entrega localmente (sempre)
3. O callback `_on_remote_broadcast` recebe mensagens de outros workers via broker e entrega
   aos usuários conectados localmente

Flag `_local_origin` evita dupla entrega no modo local (quando o broker é LocalPubSubBroker,
o callback ignora mensagens que nós mesmos publicamos).

`get_broker()` é singleton — cria RedisPubSubBroker se `REDIS_URL` está setado, senão
LocalPubSubBroker. `close_broker()` é chamado no shutdown.

**Limitação:** `send_personal_message` ainda só funciona localmente (precisa saber em qual
worker o destinatário está). Solução completa exigiria tracking de `user_id -> worker_id`
em Redis (futuro P3-2). Por enquanto, `broadcast_to_users` propaga para todos os workers.

**Testes:** 5 testes em `TestPubSubBroker` cobrindo: publish entrega aos assinantes,
múltiplos assinantes, sem assinante não erro, close limpa, get_broker retorna local sem Redis.

### T4: Anexos carregados inteiros na memória (cliente)

**Arquivos:** `shared/client/api.py`, `client-cli/main.py`

**Problema:** O servidor já fazia streaming no upload (chunks de 1MB), mas o cliente não.
Tanto `upload_attachment` quanto `download_attachment` liam o arquivo inteiro na RAM
(`file_bytes = f.read()`). Para 50 usuários enviando imagens de 10MB simultaneamente, consumia
500MB de RAM só no cliente.

**Correção:** Adicionamos dois métodos em `ApiClient`:
1. `upload_attachment_streaming(token, file_path, filename=None, mime_type=None)` — abre o
   arquivo como file-like object e passa para httpx, que faz streaming automático sem carregar
   tudo na RAM
2. `download_attachment_streaming(token, attachment_id, save_path, chunk_size=1MB)` — usa
   `httpx.stream()` para receber em chunks e escrever direto no disco

Atualizamos a CLI (`/upload` e `/download`) para usar os métodos de streaming. Os métodos
antigos (`upload_attachment` com `bytes` e `download_attachment` retornando `bytes`) são
mantidos para backward compatibility (Desktop ainda usa para preview de imagens inline).

**Testes:** 2 testes em `TestStreamingMethodsExist` verificam que os métodos existem e são
chamáveis.

### T5: Memory leak no attachment_cache do Desktop

**Arquivo:** `client-desktop/models/state.py`

**Problema:** `attachment_cache` era um dict simples que crescia indefinidamente. Cada imagem
baixada ficava na RAM para sempre. Se o usuário ficasse num chat com muito envio de
memes/imagens, o cliente Desktop consumia centenas de MB de RAM até travar a máquina (OOM).

**Correção:** Criamos a classe `LRUAttachmentCache` (Least Recently Used) com limite duplo:
- `max_bytes` (default 100 MB) — remove entradas antigas quando atinge o limite de bytes
- `max_entries` (default 50) — evita que muitas imagens pequenas encham o cache

Acessar uma entrada (`cache[key]`) move ela para o final (mais recente). Inserir nova entrada
quando o cache está cheio remove a mais antiga. Configurável via env:
`ATTACHMENT_CACHE_MAX_BYTES` e `ATTACHMENT_CACHE_MAX_ENTRIES`.

`ClientState.attachment_cache` agora é `LRUAttachmentCache()` em vez de `{}`.

**Testes:** 6 testes em `TestLRUAttachmentCache` cobrindo: respeita max_entries, respeita
max_bytes, LRU order on access, clear, stats, get com default.

### T6: QTextBrowser lento com milhares de mensagens

**Arquivo:** `client-desktop/ui/main_window.py`

**Problema:** O `_on_message_added` fazia `browser.append(html_msg)` que acumula HTML
indefinidamente. Com milhares de mensagens, o QTextBrowser ficava lento (re-parse de HTML
inteiro a cada append) e consumia muita RAM.

**Correção:** Adicionamos um contador de mensagens por aba. Quando passa de
`DESKTOP_MAX_RENDERED_MESSAGES` (default 500), trunca as mais antigas:
- A cada `max_msgs * 2`, pega o texto do document, mantém apenas as últimas ~5000 chars
  (~200 mensagens), e reescreve
- Adiciona marcador `…[histórico truncado]…` no início

Isto mantém o contexto visual sem estourar RAM.

### T7: Descoberta LAN não automática no Desktop

**Arquivo:** `client-desktop/ui/login_dialog.py`

**Problema:** A análise terceira afirmou que o Desktop não tinha descoberta LAN. Na verdade,
JÁ tinha o botão 📡, mas a descoberta só rodava quando o usuário clicava — a CLI faz
automaticamente no startup. Falta de paridade.

**Correção:**
1. `LoginDialog.__init__` agora dispara `_discover_servers()` automaticamente 500ms após abrir
   (via `QTimer.singleShot`)
2. `_on_discover_result` melhorado:
   - Se 1 servidor encontrado: seleciona automaticamente no campo de servidor
   - Se múltiplos: mostra indicação visual "📡 N servidores encontrados! Clique em 📡"
3. `_show_servers_menu` extraído para método próprio — se já há servidores em cache, clicar
   no 📡 mostra o menu direto sem fazer nova busca

Agora o Desktop tem paridade total com a CLI na descoberta LAN.

## Quarta Rodada de Fixes (Q — Ciclo 4)

### Q2: Argon2 com parâmetros configuráveis

**Arquivo:** `server/auth/security.py`

**Problema:** `memory_cost=19456` (19 MiB) era fixo no código. OWASP 2024 recomenda
≥64 MiB para servidores modernos. O trade-off era consciente (Raspberry Pi), mas não
era configurável sem editar código.

**Correção:** Parâmetros agora lidos de env vars:
- `ARGON2_MEMORY_COST` (default 19456 = 19 MiB)
- `ARGON2_TIME_COST` (default 2)
- `ARGON2_PARALLELISM` (default 1)

Validação: se `memory_cost < 8192` (8 MiB), clampa para 8192 com warning.

Mudar parâmetros NÃO invalida senhas existentes — Argon2 armazena parâmetros no hash,
e `verify()` usa os parâmetros do hash (não os atuais). Apenas novas senhas usam os
parâmetros novos.

**Testes:** 4 testes em `TestArgon2Configurable`.

### Q5: Heartbeat WS com ping JSON customizado

**Arquivos:** `server/websocket/manager.py`, `server/websocket/dispatcher.py`,
`shared/events/__init__.py`, `shared/client/websocket.py`

**Problema:** O heartbeat fazia `if hasattr(ws, "ping"): await ws.ping()`. Mas o
Starlette WebSocket **NÃO tem método `.ping()`** (verificado:
`hasattr(WebSocket, 'ping')` retorna `False`). O heartbeat dependia apenas do
timeout passivo de inatividade — conexões mortas que ainda recebiam keepalive TCP
não eram detectadas.

**Correção:**
1. Adicionados `EventType.PING` e `EventType.PONG` no enum
2. `_ping_all()` agora envia `{"event": "ping", "payload": {"ts": now}}` via
   `send_text` — se falhar (TCP caiu), remove a conexão imediatamente
3. Dispatcher processa `PONG` (silencioso — só atualiza `last_seen_at` via `touch()`)
   e responde a `PING` com `PONG` (para clientes que enviam ping)
4. `WebSocketClient._listen_loop` responde automaticamente a `ping` do servidor
   com `pong`, sem repassar para o callback (evento interno do protocolo)

**Testes:** 2 testes (`TestPingPongEvents`, `TestWebSocketClientPongResponse`).

### Q7: CLI exibe anexos recebidos

**Arquivo:** `client-cli/main.py`

**Problema:** O handler de `MESSAGE_RECEIVE` montava
`formatted_msg = f"[{t}] <{sender_name}> {content}"` mas ignorava o campo
`attachment` do payload. Mensagens com só anexo (content vazio) apareciam como
`[HH:MM] <user> ` sem indicação de que havia um arquivo para baixar.

**Correção:** Agora verifica `payload.get("attachment")` e, se presente, adiciona
linha com:
- Emoji por tipo (🖼️ imagem, 🎵 áudio, 🎬 vídeo, 📕 PDF, 📦 zip)
- Nome do arquivo e tamanho formatado (B/KB/MB)
- Comando de download: `use /download {att_id} para baixar`

**Testes:** 1 teste em `TestCLIAttachmentDisplay`.

### Q11: Sons de notificação na CLI (BEL)

**Arquivo:** `client-cli/main.py`

**Problema:** Quando a CLI estava em background (outra aba/janela do terminal), o
usuário não tinha como saber que chegou DM sem olhar a tela.

**Correção:**
1. Adicionada flag `state.beep_enabled` (default True)
2. Função `_beep()` escreve caractere BEL (`\x07`) no stderr — faz o terminal
   apitar (se som habilitado) OU piscar ícone na taskbar
3. Chamada quando DM chega em aba não ativa
4. Novo comando `/beep [on|off]` para ligar/desligar (com teste imediato ao ligar)

**Testes:** 3 testes em `TestCLIBeepFunction`.

## Quinta Rodada de Melhorias (S — Ciclo 5)

### S1: Upload streaming no Desktop

**Arquivo:** `client-desktop/ui/main_window.py`

**Problema:** O `_upload_attachment` fazia `with open(file_path, "rb") as f: file_bytes = f.read()`
— carregava o arquivo inteiro na RAM antes de enviar. Para 50 usuários enviando imagens de 10MB
simultaneamente, consumia 500MB de RAM só no cliente.

**Correção:** Agora usa `api.upload_attachment_streaming(token, file_path, filename, mime_type)`
(criado no ciclo 3 T4 mas não usado no Desktop). O httpx recebe o file-like object e faz streaming
automático. Só carrega no cache de preview se for imagem (PDFs, zips, etc não precisam ficar na RAM).

### S3: Barras de progresso para download

**Arquivos:** `shared/client/api.py`, `client-desktop/ui/main_window.py`

**Problema:** Downloads mostravam apenas "Baixando..." na status bar, sem indicação de progresso.
Para arquivos grandes, o usuário não sabia se travou ou estava progredindo.

**Correção:**
1. `download_attachment_streaming` agora aceita `progress_callback(downloaded, total)` chamado
   a cada chunk. `total` vem do header `Content-Length`.
2. `_download_attachment_to_file` no Desktop cria `QProgressDialog` modal com:
   - Barra de progresso 0-100%
   - Label "Baixando {filename}... {size_mb}/{total_mb} MB"
   - Botão Cancelar
   - Só aparece se demorar > 500ms (`setMinimumDuration`)
3. Thread-safe via `_ProgressBridge` (QObject com signal `update` conectado ao dialog)

### S4: Jobs de background configuráveis

**Arquivo:** `server/main.py`

**Problema:** `_attachment_cleanup_loop` e `_guest_cleanup_loop` tinham `asyncio.sleep(3600)`
fixo no código. Administradores não podiam ajustar a frequência sem editar código.

**Correção:** Intervalos agora lidos de env vars:
- `ATTACHMENT_CLEANUP_INTERVAL_SECONDS` (default 3600 = 1 hora)
- `GUEST_CLEANUP_INTERVAL_SECONDS` (default 3600 = 1 hora)

Defaults mantêm comportamento anterior. Log info no startup mostra o intervalo configurado.

### S5: Tratamento de erros granular no middleware

**Arquivo:** `server/main.py`

**Problema:** O `_error_logger` capturava todas as exceções e retornava 500 genérico
"Erro interno do servidor". Não diferenciava HTTPException (que tem status e detail próprios)
de erros inesperados.

**Correção:** Agora diferencia 3 tipos:
1. **HTTPException** — repassa `status_code` e `detail` originais, loga como WARNING
2. **RequestValidationError (422)** — repassa com lista de erros, loga como INFO (erro de cliente)
3. **Outras exceções** — 500 genérico + log completo no servidor

Em modo debug (`LOG_LEVEL=DEBUG`), o 500 inclui `type(e).__name__` e mensagem truncada para
ajudar o desenvolvedor. Em produção, mensagem genérica para não expor detalhes internos.

### S7: Tutorial interativo na CLI

**Arquivo:** `client-cli/main.py`

**Problema:** A CLI tem 35+ comandos mas nova usuários podiam se sentir perdidos sem um guia.

**Correção:**
1. Novo comando `/tutorial` mostra guia didático em 7 seções:
   - Navegação (Enter, TAB, /switch)
   - Salas (/rooms, /join, /create, /leave, /members)
   - DMs (/dm, /query, /invite, /accept, /friends)
   - Arquivos (/upload, /download)
   - Perfil (/whoami, /status, /notifications)
   - Personalização (/theme, /typing, /beep)
   - Ajuda (/help, /tutorial, /quit)
2. Mensagem de boas-vindas mostrada automaticamente no primeiro login (quando não há cache
   de histórico): "👋 Bem-vindo ao ChatPy! Digite /tutorial para ver um guia rápido"
3. `/help` agora lista `/tutorial`

## Próximos Passos Recomendados (não implementados)

Os itens abaixo foram identificados na auditoria mas **não** implementados neste ciclo:

## Bugs Críticos Corrigidos (P0)

### P0-1: CORS `*` + `allow_credentials=True` quebrava o startup

**Arquivo:** `server/main.py`

**Problema:** Starlette/Flask-style CORS proíbe `allow_origins=["*"]` combinado com
`allow_credentials=True` — gera `ValueError` no startup. Se o operador configurasse
`CORS_ORIGINS=*` (caso de uso legítimo do projeto: "qualquer um pode hospedar"), o
servidor nem iniciava.

**Correção:** Detectamos `*` em `_cors_origins` e desligamos `allow_credentials` neste caso.
Clientes ChatPy usam header `Authorization`, não cookies — então isto é seguro.

```python
if "*" in _cors_origins:
    _cors_origins_resolved = ["*"]
    _cors_allow_credentials = False
    logger.warning("CORS_ORIGINS=* detectado — allow_credentials desligado ...")
else:
    _cors_origins_resolved = list(_cors_origins)
    _cors_allow_credentials = True
    # ... auto-detecção LAN
```

### P0-2: JWT_SECRET salvo em `os.getcwd()` invalidava sessões

**Arquivos:** `server/auth/security.py`, `server/paths.py` (novo)

**Problema:** O arquivo `.chatpy_auto_secret` era salvo em `os.getcwd()`. Se o operador
rodasse o servidor a partir de diretórios diferentes em momentos diferentes (ex: `python
server/main.py` um dia, `cd .. && python chatpy/server/main.py` no outro), o arquivo não
era encontrado. O servidor gerava um novo secret e **invalidava TODAS as sessões JWT em uso**.

**Correção:** Criamos o módulo `server/paths.py` que resolve caminhos persistentes em um
diretório base único, com precedência:
1. `CHATPY_DATA_DIR` env var (se definida)
2. Diretório do projeto (parent de `server/`) — útil em dev
3. `~/.chatpy/` — fallback universal

O `auto_secret_path()` agora retorna um `Path` absoluto, garantindo consistência entre
execuções a partir de cwd diferentes. Também criamos `federation_key_path()` para a chave
Ed25519 da federação (P0-5) e `cli_history_cache_path()` para o cache de histórico da CLI.

### P0-3: Endpoints admin de federação e backup não validavam role admin

**Arquivos:** `server/database/models.py`, `server/api/dependencies.py`, `server/api/federation_admin.py`,
`server/main.py`, `server/api/users.py`, `setup.py`

**Problema:** Todos os endpoints `/api/admin/*` (listar/cadastrar/deletar peers federados,
forçar backup, etc) aceitavam `Depends(get_current_user)` — ou seja, **qualquer usuário
autenticado** podia:
- Cadastrar um peer federado malicioso apontando para servidor próprio → interceptar DMs federadas
- Deletar todos os peers legítimos → quebrar federação
- Forçar backup a cada segundo → encher o disco (DoS)

**Correção:**
1. Adicionamos `is_admin = Column(Boolean, default=False, nullable=False, index=True)` em `User`
2. Criamos a dependência `require_admin` em `server/api/dependencies.py` que valida
   `current_user.is_admin` e retorna 403 se não for admin
3. Aplicamos `require_admin` em todos os endpoints `/api/admin/*`:
   - `federation_admin.py`: list_peers, register_peer, discover_peer, toggle_peer_active, delete_peer
   - `main.py`: list_backups_endpoint, trigger_backup_now_endpoint
4. Adicionamos endpoints novos `/api/users/admin/promote` e `/api/users/admin/demote`
   (também protegidos por `require_admin`) para permitir promoção via REST sem mexer em SQL
5. `setup.py` agora marca o primeiro usuário criado como admin automaticamente
   (caso de uso: setup interativo na primeira execução)
6. `/api/users/me` e `/api/users/online` agora retornam `is_admin` e `is_guest` para que
   clientes possam mostrar badges e habilitar/desabilitar ações administrativas

### P0-4: DM federada persistia com `sender_id = receiver.id` (corrupção de dados)

**Arquivos:** `server/database/models.py`, `server/federation.py`, `server/main.py`

**Problema:** Em `receive_federated_dm`, a mensagem federada era persistida com:
```python
sender_id=receiver.id,  # Placeholder — sender federado não é User local
receiver_id=receiver.id,
```
Isso:
- Aparece errado em qualquer query de "DMs que recebi"
- Viola a foreign key semanticamente (sender_id deveria apontar para quem enviou)
- Quebra o payload WebSocket enviado ao destinatário: `"sender_id": str(receiver.id)` —
  o cliente acha que a mensagem é dele mesmo

**Correção:**
1. Adicionamos a coluna `federated_sender = Column(String(255), nullable=True, index=True)`
   em `PrivateMessage` para guardar o remetente federado real (ex: `@bob@outro.com`)
2. `sender_id` continua sendo o `receiver.id` apenas como placeholder (para satisfazer a
   NOT NULL FK) — clientes devem checar `federated_sender` para identificar o remetente
3. O payload WS agora inclui `federated_sender` explicitamente
4. O conteúdo da mensagem fica limpo (não mais prefixado com `[Federado] <@bob@...>`) —
   clientes usam `sender_name` e `federated_sender` para montar a UI

**Bônus:** Aproveitamos para tornar `receive_federated_dm` e `receive_federated_presence`
async (P1-14) — antes usavam `asyncio.ensure_future` + `asyncio.get_event_loop()`
(deprecated em Python 3.12+ quando há running loop) que nunca esperava a entrega.

### P0-5: Chave Ed25519 da federação era regenerada a cada restart

**Arquivo:** `server/federation.py`

**Problema:** Em import-time:
```python
_PRIVATE_KEY = Ed25519PrivateKey.generate()
```
Toda vez que o servidor reiniciava, uma nova chave era gerada. Todos os peers que tinham
cadastrado este servidor com a chave pública anterior rejeitavam todas as DMs federadas
("Assinatura criptográfica inválida") após o primeiro restart. A federação quebrava
silenciosamente. O comentário admitia: *"Em produção, esta chave deve ser persistida"*.

**Correção:** Criamos a função `_load_or_create_federation_key()` que:
1. Tenta carregar a chave de `.chatpy_federation_key.pem` (resolvido via
   `server.paths.federation_key_path()`)
2. Se o arquivo não existe, gera nova chave, salva em formato PKCS8 PEM com permissões
   `0600` no Unix
3. Log warning explícito quando uma nova chave é gerada, alertando que peers federados
   precisam re-discover este servidor

### P0-6: Indicador de digitação na CLI poluía o histórico

**Arquivos:** `client-cli/main.py`, `client-cli/views/interface.py`

**Problema:** Quando o servidor retransmitia `user.typing_broadcast`, o handler na CLI fazia:
```python
state.messages[state.active_tab].append(f"  ... {username} está digitando ...")
```
O comentário dizia que o `live_chat_loop` sobrescreveria, mas o `live.update(layout,
refresh=True)` só faz refresh do layout Rich — **não limpa a lista `state.messages`**.
O `messages[-100:]` em `interface.py` mostrava os últimos 100 — então **cada evento de
digitação virava uma linha permanente no histórico**.

**Correção:**
1. Adicionamos `typing_indicators: dict = {}` em `ClientState` (formato:
   `{tab_name: {username: timestamp}}`)
2. O handler agora registra o indicador neste dict em vez de fazer append em `messages`
3. `create_chat_layout` aceita `typing_indicators` e `typing_ttl_s` e renderiza "X está
   digitando..." apenas para usuários ativos nos últimos 4 segundos
4. `live_chat_loop` limpa indicadores expirados a cada frame
5. Adicionamos comando `/typing [on|off]` para o usuário poder desativar (útil em
   terminais lentos)

### P0-7: `_apply_room_history` no Desktop sobrescrevia histórico local

**Arquivo:** `client-desktop/controllers/chat_controller.py`

**Problema:** Quando salas fixadas/favoritadas eram reabertas após login, este método
substituía o histórico local pelo do servidor:
```python
self.state.messages[room_name] = history
```
Em salas que tinham mensagens próprias em cache local (enviadas offline e enfileiradas
via `_offline_queue` do `WebSocketClient`), as mensagens locais eram perdidas visualmente
— o usuário pensava que o envio falhou mesmo tendo sido entregue ao servidor.

**Correção:** Agora faz merge por chave `(sender, content, timestamp_truncated_to_seconds)`:
- Histórico do servidor é a fonte autoritativa
- Mensagens locais que NÃO estão no servidor (ainda em fila offline) são mantidas
- Limite de 200 mensagens por aba para não estourar memória

### P0-8: `socket.gethostbyname(socket.gethostname())` retornava `127.0.1.1` no Linux

**Arquivo:** `server/main.py`

**Problema:** No Debian/Ubuntu, `/etc/hosts` costuma ter `127.0.1.1 hostname` — o filtro
`not startswith("127.")` NÃO pega `127.0.1.1`. Como resultado, a origem
`http://127.0.1.1:5000` era adicionada ao CORS mas não funcionava para clientes externos.

**Correção:** Substituímos por `get_local_ip()` de `lan_discovery.py` que faz a coisa certa
(socket UDP para 8.8.8.8 — não envia pacotes, só resolve o IP da interface de saída).

## Problemas Importantes Corrigidos (P1)

### P1-9: Sanitização ANSI incompleta na CLI

**Arquivo:** `client-cli/main.py`

**Problema:** A regex `r"\x1b\[[0-9;]*[A-Za-z]"` só removia sequências CSI. Deixava passar:
- OSC (`ESC ] ... BEL/ST`) — pode mudar título da janela e, em alguns terminais, ler clipboard
- DCS/PM/APC — escape strings que alguns terminais interpretam
- Single-char ESC (`ESC =`, `ESC >`, `ESC M`...) — mudam modo do terminal
- Caracteres de controle C0 (BEL, BS, VT, FF, ...) e DEL

Um peer federado malicioso poderia enviar DMs com estes escapes para manipular o terminal.

**Correção:** 5 regexes consecutivos cobrem todos os casos, mantendo apenas `\t`, `\n`, `\r`:
```python
text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", text)  # OSC
text = re.sub(r"\x1b[P^_][^\x1b]*\x1b\\", "", text)             # DCS/PM/APC
text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)              # CSI
text = re.sub(r"\x1b[^[]", "", text)                            # single-char ESC
text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)    # C0 + DEL
```

### P1-10: Confirmação Y/n em comandos destrutivos da CLI

**Arquivo:** `client-cli/main.py`

**Problema:** Comandos como `/kick`, `/ban`, `/leave`, `/unfriend`, `/block` executavam
imediatamente sem confirmação. Um typo (`/ban alce` em vez de `/ban alice`) → ação
irreversível.

**Correção:** Criamos `_confirm_destructive(action_desc)` que pede `[y/N]` (default N) em
thread não-bloqueante. Aplicado em:
- `/leave`
- `/unfriend`
- `/block`
- `/kick`
- `/ban`
- `/demote_admin` (comando novo)

### P1-11: Race condition no consumo de One-Time PreKey

**Arquivo:** `server/api/e2e_keys.py`

**Problema:** O código fazia SELECT + UPDATE em duas queries separadas:
```python
otpk = db.query(OneTimePreKey).filter(...).first()
if otpk:
    otpk.used = True
    db.commit()
```
Dois clientes fazendo X3DH simultâneo podiam receber a **mesma** One-Time PreKey (race window
entre SELECT e UPDATE). Em SQLite com WAL o isolamento padrão é READ COMMITTED — a race é real.

**Correção:** Substituímos por `UPDATE ... RETURNING` atômico (suportado em SQLite 3.35+ e
PostgreSQL). Se não disponível, fallback para SELECT + re-checa `used` antes de marcar.

### P1-12: Rate limit de conexões WS não-autenticadas por IP

**Arquivos:** `server/websocket/rate_limit.py`, `server/main.py`

**Problema:** O timeout de 30s para autenticação WS era generoso. Um atacante podia abrir
milhares de conexões por segundo e esperar o timeout sem enviar nada — cada conexão consome
um socket + uma task asyncio. Sem limites, isto é DoS trivial.

**Correção:** Criamos a classe `UnauthConnectionGuard` em `server/websocket/rate_limit.py`:
- `try_acquire(ip)`: chamado ANTES do `accept()` no endpoint WS. Retorna False se excedeu
- `release(ip)`: chamado APÓS auth success OU desconexão
- Limites configuráveis: `WS_MAX_UNAUTH_PER_IP` (default 10), `WS_MAX_UNAUTH_GLOBAL`
  (default 1000)
- Se excedeu, fecha com 1008 (Policy Violation) **antes** do accept — consome menos recursos

### P1-13: Bot `sender_id` usava UUID de quem invocou

**Arquivos:** `server/bots.py`, `server/websocket/dispatcher.py`

**Problema:** Quando um bot respondia a um comando `!echo`, o dispatcher setava:
```python
"sender_id": str(user_id),  # placeholder — deveria ser um ID de bot
```
O `sender_id` do bot era o UUID do usuário que invocou. Cliente Desktop ia exibir a mensagem
como se fosse do usuário (com badge não-lida na aba, etc).

**Correção:**
1. Cada bot agora tem `uuid` determinístico derivado do nome (UUID v5 com namespace fixo)
2. `process_bots` retorna `List[tuple]` em vez de `List[str]` — cada tupla é `(bot, response)`
3. O dispatcher usa `bot.uuid` como `sender_id` e `f"🤖 {bot.name}"` como `sender_name`
4. Payload inclui flag `is_bot: True` para clientes identificarem facilmente

### P1-14: `asyncio.get_event_loop()` + `run_until_complete` em contexto async

**Arquivo:** `server/federation.py`

**Problema:** `receive_federated_dm` (chamada de endpoint FastAPI async) usava:
```python
loop = asyncio.get_event_loop()
if loop.is_running():
    asyncio.ensure_future(..., loop=loop)  # não espera entrega
else:
    loop.run_until_complete(...)  # nunca executa em contexto async
```
- `asyncio.get_event_loop()` deprecated em Python 3.12+ quando há running loop
- `ensure_future` não espera a entrega completar — o endpoint retornava 200 antes do
  WebSocket receber a DM
- O fallback `run_until_complete` lançaria `RuntimeError: This event loop is already running`

**Correção:** Tornamos `receive_federated_dm` e `receive_federated_presence` async e
usamos `await` direto no `_connection_manager.send_personal_message(...)` /
`broadcast_to_users(...)`. Os endpoints que os chamam também foram atualizados para `await`.

### P1-15: Logout no Desktop não esperava WS fechar

**Arquivo:** `client-desktop/services/connection_service.py`

**Problema:** `disconnect()` fazia fire-and-forget:
```python
self.run_coroutine_async(self._disconnect_internal())
```
Se o usuário fizesse login novamente em seguida (no mesmo processo), o WS antigo ainda
podia estar tentando fechar enquanto o novo abria — confusão no `_auth_token` compartilhado.

**Correção:** Agora usa `run_coroutine` (síncrono, com timeout de 30s) em vez de
`run_coroutine_async`. Se falhar (timeout), cai no fire-and-forget como fallback.

## Melhorias Adicionais

### CLI — novos comandos e features

| Comando | Descrição |
|---|---|
| `/whoami` | Mostra perfil do usuário logado (username, status, is_admin, is_guest) |
| `/history more` | Paginação — carrega mais 20 mensagens antigas da sala ativa |
| `/peers` | Lista peers federados (requer admin) |
| `/promote_admin <user>` | Promove usuário a admin (requer admin) |
| `/demote_admin <user>` | Rebaixa admin a usuário (requer admin, com confirmação Y/n) |
| `/typing [on\|off]` | Liga/desliga indicador de digitação dos outros |

### CLI — login guest

Opção 3 no menu inicial: "Entrar como Convidado (anônimo, expira em 24h)". Cria conta
guest via `/api/auth/guest` sem pedir username/senha. Paridade com o Desktop (que também
ganhou o botão "Entrar como Convidado").

### CLI — cache de histórico offline

Adicionamos `_load_cli_history_cache()` e `_save_cli_history_cache()` em `main.py` que
persistem `state.messages` em `cli_history_cache_<user>.json` (resolvido via
`server.paths.cli_history_cache_path()`). Carregado ANTES de `fetch_initial_data` para
mostrar mensagens recentes mesmo se o servidor estiver lento. Paridade com o Desktop
que já tem `history_cache_<user>.json`.

### CLI — tab-completion com prompt_toolkit

`input_poller_fallback` agora habilita TAB-completion quando `prompt_toolkit` está
disponível. Completa:
- Comandos `/` (todos os 35+ comandos)
- Salas `#` (apenas salas já ingressadas)
- Usuários `@` (apenas usuários online)

### Desktop — login guest

Adicionamos botão "Entrar como Convidado (anônimo)" no `LoginDialog`. Cria conta guest
em thread background, busca o username gerado pelo servidor via `/api/users/me`, e
conecta automaticamente.

### Desktop — persistir preferência de status

`user_config.json` agora inclui `preferred_status` (default: `"online"`). Quando o
usuário muda status para "away", a preferência é persistida. No próximo login,
`_on_initial_connect` usa `preferred_status` em vez de forçar "online".

### Shared — novos métodos na ApiClient

- `create_guest_account()` → cria conta guest, retorna token
- `get_me(token)` → retorna perfil do usuário logado (incluindo is_admin, is_guest)
- `promote_to_admin(token, username)` → promove usuário a admin
- `demote_admin(token, username)` → rebaixa admin

## Testes Adicionados

Criamos `tests/test_p0_fixes.py` com **25 testes de regressão** cobrindo cada fix do ciclo 1:
- `TestPathsAndSecretPersistence` (6 testes): paths centralizados, JWT_SECRET persistente
- `TestFederationKeyPersistence` (2 testes): chave Ed25519 persistida entre loads
- `TestIsAdminAndRequireAdmin` (3 testes): is_admin em User + require_admin funciona
- `TestFederatedDMPersistence` (1 teste): DM federada com federated_sender
- `TestOneTimePreKeyAtomicConsumption` (1 teste): prekeys marcadas como used após consumo
- `TestBotUUIDDeterministic` (3 testes): UUID v5 por nome é estável
- `TestUnauthConnectionGuard` (4 testes): limites por IP e global, release funciona
- `TestCLISanitization` (4 testes): CSI, OSC, control chars, DEL removidos
- `TestCORSMiddlewareConfig` (1 teste): CORS com `*` não quebra o startup

Criamos `tests/test_p1_fixes.py` com **29 testes de regressão** cobrindo os fixes do ciclo 2:
- `TestMagicNumbers` (11 testes): PNG/JPEG/PDF/ZIP/GIF/BMP aceitos, EXE disfarçado rejeitado
- `TestReplayProtection` (6 testes): primeira mensagem OK, replay rejeitado, timestamp antigo/futuro rejeitado
- `TestConnectionManagerHeartbeat` (4 testes): touch, disconnect, start/stop heartbeat
- `TestCursorPagination` (2 testes): offset retorna mais novas, cursor retorna mais velhas sem duplicação
- `TestCLINotificationsState` (1 teste): ClientState tem lista de notificações
- `TestOfflineQueuePersistence` (2 testes): fila persistida e recarregada, limpa após flush
- `TestDockerfileHasDataDir` (2 testes): Dockerfile e compose setam CHATPY_DATA_DIR

Criamos `tests/test_t_fixes.py` com **23 testes de regressão** cobrindo os fixes do ciclo 3:
- `TestTrustedProxies` (8 testes): sem proxy ignora XFF, proxy confiável usa XFF, CIDR, múltiplos
- `TestPubSubBroker` (5 testes): publish entrega, múltiplos assinantes, close limpa, get_broker local
- `TestLRUAttachmentCache` (6 testes): max_entries, max_bytes, LRU order, clear, stats, get default
- `TestStreamingMethodsExist` (2 testes): upload/download streaming existem e são chamáveis
- `TestPathsWindowsRestriction` (2 testes): funções Windows existem e são no-op no Unix

Criamos `tests/test_q_fixes.py` com **11 testes de regressão** cobrindo os fixes do ciclo 4:
- `TestArgon2Configurable` (4 testes): defaults, custom params, clamp mínimo, hashing funciona
- `TestPingPongEvents` (1 teste): EventType tem PING e PONG
- `TestWebSocketClientPongResponse` (1 teste): cliente responde pong a ping automaticamente
- `TestCLIAttachmentDisplay` (1 teste): anexo recebido gera info de download na mensagem
- `TestCLIBeepFunction` (3 testes): _beep existe, respeita flag, state tem beep_enabled
- `TestSystemTrayExists` (1 teste): confirma que Desktop já tem system tray (Q10 falso positivo)

Criamos `tests/test_s_fixes.py` com **14 testes de regressão** cobrindo as melhorias do ciclo 5:
- `TestDesktopUploadStreaming` (1 teste): Desktop usa upload_attachment_streaming
- `TestDownloadProgressCallback` (2 testes): progress_callback existe e é chamável
- `TestBackgroundJobsConfigurable` (3 testes): env vars existem, default é 3600
- `TestErrorMiddlewareGranular` (2 testes): middleware diferencia tipos, debug mode
- `TestCLITutorial` (3 testes): /tutorial existe, está no help, mensagem de boas-vindas
- `TestDesktopHasFederationDialog` (3 testes): confirma que Desktop JÁ tem federation/admin (S2 falso positivo)

**Resultado:** 153 testes passando (antes: 51), mesmas 2 falhas pré-existentes
(`test_federation` com variáveis de ambiente avaliadas em import-time — bug pré-existente
não relacionado aos fixes).

## Ambiente e Configuração

### Novas env vars

| Variável | Default | Descrição |
|---|---|---|
| `CHATPY_DATA_DIR` | (vazio) | Diretório base para arquivos persistentes (override) |
| `WS_MAX_UNAUTH_PER_IP` | `10` | Máximo de conexões WS não-autenticadas por IP |
| `WS_MAX_UNAUTH_GLOBAL` | `1000` | Máximo global de conexões WS não-autenticadas |
| `WS_HEARTBEAT_INTERVAL_SECONDS` | `30` | Intervalo entre pings do heartbeat WS |
| `WS_HEARTBEAT_TIMEOUT_SECONDS` | `60` | Timeout de inatividade antes de remover conexão zumbi |
| `FEDERATION_REPLAY_WINDOW_SECONDS` | `300` | Janela de timestamp aceita em DMs federadas (5 min) |
| `FEDERATION_FUTURE_SKEW_SECONDS` | `300` | Tolerância de skew de relógio para timestamps no futuro |
| `FEDERATION_REPLAY_CACHE_SIZE` | `10000` | Tamanho máximo do cache de replay (LRU) |
| `TRUSTED_PROXIES` | (vazio) | Lista de IPs/CIDRs de proxies confiáveis para X-Forwarded-For (T1) |
| `REDIS_URL` | (vazio) | URL do Redis para Pub/Sub entre workers (T3 — escalonamento horizontal) |
| `ATTACHMENT_CACHE_MAX_BYTES` | `104857600` | Tamanho máximo do cache de anexos no Desktop (100 MB) (T5) |
| `ATTACHMENT_CACHE_MAX_ENTRIES` | `50` | Número máximo de entradas no cache de anexos (T5) |
| `DESKTOP_MAX_RENDERED_MESSAGES` | `500` | Limite de mensagens renderizadas no QTextBrowser (T6) |
| `ARGON2_MEMORY_COST` | `19456` | Memory cost do Argon2 em KiB (19 MiB default; OWASP recomenda 65536) (Q2) |
| `ARGON2_TIME_COST` | `2` | Time cost do Argon2 (iterações; OWASP recomenda 3) (Q2) |
| `ARGON2_PARALLELISM` | `1` | Paralelismo do Argon2 (default 1) (Q2) |
| `ATTACHMENT_CLEANUP_INTERVAL_SECONDS` | `3600` | Intervalo do job de limpeza de anexos órfãos (S4) |
| `GUEST_CLEANUP_INTERVAL_SECONDS` | `3600` | Intervalo do job de purga de convidados expirados (S4) |

### Novos endpoints REST

| Método | Path | Descrição | Auth |
|---|---|---|---|
| `POST` | `/api/users/admin/promote` | Promove usuário a admin | admin |
| `POST` | `/api/users/admin/demote` | Rebaixa admin a usuário comum | admin |

### Schema changes

- `users.is_admin` (Boolean, default False, indexado) — flag de admin (ciclo 1)
- `private_messages.federated_sender` (String(255), nullable, indexado) — remetente federado (ciclo 1)

### Novos módulos (ciclo 2)

- `shared/magic_numbers.py` — validação de anexos por assinatura de bytes
- `server/federation_replay.py` — cache LRU + validação de timestamp para replay protection

### Novos módulos (ciclo 3)

- `server/security_ip.py` — extração segura de IP com trusted proxies
- `server/pubsub.py` — abstração Pub/Sub broker (local + Redis) para escalonamento horizontal

**Atenção:** Se você tem um banco SQLite existente, precisa recriar as tabelas (ou rodar
`alembic revision --autogenerate && alembic upgrade head` quando a migration estiver
disponível). Em dev, `Base.metadata.create_all(bind=engine)` cuida disso automaticamente.

## Migração

### Para operadores existentes

1. **Faça backup do banco SQLite** antes de aplicar os fixes (caso algo dê errado)
2. Após aplicar, o servidor vai criar as novas colunas automaticamente em dev. Em produção,
   gere uma migration Alembic: `alembic revision --autogenerate -m "add is_admin and federated_sender"`
3. Para promover um usuário existente a admin:
   ```bash
   sqlite3 chatpy.db "UPDATE users SET is_admin = 1 WHERE username = 'seu_admin'"
   ```
   Ou via API: faça login como o primeiro admin (via setup.py se for nova instância), e use
   `POST /api/users/admin/promote` com o username desejado.

### Para desenvolvedores

1. Rode `pip install -r all-requirements.txt` para incluir `prompt_toolkit`
2. Rode `python -m pytest tests/` — deve passar 76 testes (2 falhas pré-existentes ok)
3. Se tinha `.chatpy_auto_secret` no cwd, ele será ignorado (o novo path é
   `~/.chatpy/.chatpy_auto_secret` ou `CHATPY_DATA_DIR`). Copie o arquivo antigo para o
   novo path SE quiser manter as sessões ativas, OU peça para usuários fazerem login
   novamente.

## Segunda Rodada de Fixes (P1 — Ciclo 2)

### P1-C2-1: Validação de anexos por Magic Numbers

**Arquivos:** `shared/magic_numbers.py` (novo), `server/api/attachments.py`

**Problema:** O backend confiava apenas na extensão do filename e no MIME type declarado
pelo cliente. Um atacante podia renomear `malicious.exe` para `cute.png` e o servidor
aceitava — o navegador de outro usuário até mostrava o ícone de imagem, mas o conteúdo
era um executável.

**Correção:** Criamos o módulo `shared/magic_numbers.py` com tabela de assinaturas
conhecidas para todos os formatos da allowlist (PNG, JPEG, GIF, WebP, BMP, ICO, PDF,
ZIP, GZIP, TAR, MP3, OGG, WAV, MP4, WebM, DOC, DOCX, XLS, XLSX, PPT, PPTX, ODT, ODS).
Para texto/JSON/XML, validação heurística (sem bytes NUL, começa com `{`/`[`/`<`).

O fluxo de upload agora lê os primeiros 512 bytes e chama `is_safe_attachment(prefix,
declared_mime)`. Se não bater, rejeita com 400 e log warning com flag
`magic_number_mismatch` para métricas Prometheus.

**Testes:** 11 testes em `TestMagicNumbers` cobrindo PNG, JPEG, PDF, ZIP, GIF, BMP
reais aceitos; EXE disfarçado de PNG/PDF rejeitado; texto com NUL rejeitado; JSON
válido/inválido.

### P1-C2-2: JWT_SECRET em container Docker efêmero

**Arquivos:** `Dockerfile`, `docker-compose.yml`

**Problema:** O `server/paths.py` (criado no ciclo 1) prefere `CHATPY_DATA_DIR` >
diretório do projeto > `~/.chatpy/`. Em container Docker, o diretório do projeto
(`/app`) é gravável mas é destruído quando o container é recriado. Sem `CHATPY_DATA_DIR`
setado, o `.chatpy_auto_secret` ia para `/app/.chatpy_auto_secret` — perdido a cada
`docker compose down && docker compose up`, invalidando todas as sessões JWT.

**Correção:**
1. `Dockerfile` agora seta `ENV CHATPY_DATA_DIR=/app/data` (que já é o volume mapeado)
2. `docker-compose.yml` adiciona `CHATPY_DATA_DIR=/app/data` no environment do serviço
   `chatpy-server`

Agora o secret vai para `/app/data/.chatpy_auto_secret` que sobrevive a restarts do
container (desde que o volume `chatpy-data` esteja mapeado, o que já é o padrão).

**Testes:** 2 testes em `TestDockerfileHasDataDir` verificam que ambos arquivos
contêm `CHATPY_DATA_DIR=/app/data`.

### P1-C2-3: Proteção contra Replay Attack em federação

**Arquivos:** `server/federation_replay.py` (novo), `server/federation.py`

**Problema:** O endpoint `/api/federation/dm` validava a assinatura Ed25519 da mensagem,
mas NÃO checava o timestamp nem se a mensagem já tinha sido processada. Um atacante de
rede (man-in-the-middle) poderia capturar o payload JSON assinado e reenviá-lo
repetidas vezes — todas as cópias passavam a validação de assinatura e eram entregues
ao destinatário.

**Correção:** Criamos `server/federation_replay.py` com a classe `ReplayCache`:
- Cache LRU em memória (max 10k entries) de hashes SHA256 dos payloads processados
- Validação de janela de timestamp: rejeita se `age > 300s` ou `age < -300s` (skew
  de relógio tolerado)
- Thread-safe (usado por múltiplas threads do Uvicorn)
- Cleanup periódico de entradas expiradas

Integrado em `receive_federated_dm`: após validação de assinatura, chama
`check_replay(payload, timestamp)` que retorna `(is_valid, error_message)`. Se inválido,
rejeita com a mensagem apropriada.

**Limitação:** Para multi-processo (uvicorn `--workers N`), o cache é por processo —
uma mensagem reenviada pode passar em outro worker. Para mitigação completa, migrar
para Redis compartilhado entre workers (futuro P3).

**Testes:** 6 testes em `TestReplayProtection` cobrindo primeira mensagem aceita,
replay rejeitado, timestamp antigo rejeitado, timestamp futuro rejeitado, conteúdo
diferente não é replay, stats retornam info útil.

### P1-C2-4: Race condition no auto-away (Desktop)

**Arquivo:** `client-desktop/ui/main_window.py`

**Problema:** Se o usuário mudava manualmente para "online" via ComboBox e o
`_idle_check_timer` (10s) disparava antes do próximo evento de mouse/teclado, ele era
forçado de volta para "away" mesmo tendo acabado de mudar manualmente. O
`_last_activity_ts` não era resetado na mudança manual.

**Correção:** `_handle_status_change` agora:
1. Reseta `_last_activity_ts = time.time()` — o check idle vai contar a partir daqui
2. Seta `_auto_away_active = False` — garante que o `eventFilter` saiba que o status
   atual é intencional (não auto)

Isto resolve o race: se o usuário acabou de mudar para "online", o check idle só vai
disparar auto-away depois de `IDLE_TIMEOUT_SECONDS` (default 300s) sem atividade.

### P1-C2-5: Conexões zumbis no WS Manager (heartbeat ping/pong)

**Arquivo:** `server/websocket/manager.py`, `server/main.py`, `server/websocket/dispatcher.py`

**Problema:** Se a conexão WebSocket caísse de forma abrupta (queda de energia, perda
de pacote sem FIN), o servidor demorava a perceber e mantinha o `user_id` no dict
`active_connections`. Isto podia impedir novos logins (já que `connect()` derruba a
conexão antiga) e manter o usuário falsamente "online".

**Correção:**
1. `ConnectionManager` agora mantém `last_seen_at: Dict[UUID, float]` atualizado por
   `touch(user_id)` (chamado pelo dispatcher a cada mensagem recebida)
2. Novo método `start_heartbeat(interval, timeout)` inicia task assíncrona que:
   - A cada `interval` (default 30s), itera sobre conexões ativas
   - Se `now - last_seen > timeout` (default 60s), marca como zumbi e remove
   - Tenta enviar ping nativo WebSocket — se falhar (TCP caiu), remove imediatamente
3. `_force_disconnect(user_id)` fecha o socket, remove do dict, marca usuário offline
   no banco, e broadcast de presença offline para os demais
4. `stop_heartbeat()` cancela a task no shutdown do servidor
5. Integrado no `lifespan` do FastAPI — heartbeat inicia no startup e para no shutdown

**Configurável via env:** `WS_HEARTBEAT_INTERVAL_SECONDS` (default 30),
`WS_HEARTBEAT_TIMEOUT_SECONDS` (default 60).

**Testes:** 4 testes em `TestConnectionManagerHeartbeat` cobrindo `touch` atualiza
`last_seen_at`, `disconnect` limpa `last_seen_at`, `start_heartbeat` é idempotente,
`stop_heartbeat` limpa a task.

### P1-C2-6: Paginação por cursor no `/history more`

**Arquivos:** `server/api/rooms.py`, `shared/client/api.py`, `client-cli/main.py`

**Problema:** A paginação usava `offset`. Em bancos de dados de chat (onde mensagens são
inseridas constantemente), se novas mensagens chegassem enquanto o usuário rola o
histórico para cima, o offset deslizava — o usuário via mensagens duplicadas ou pulava
mensagens.

**Correção:**
1. Endpoint `GET /api/rooms/{room_id}/history` agora aceita parâmetro `before_id`
   (UUID). Quando fornecido, busca a mensagem com aquele ID, pega seu timestamp, e
   retorna mensagens com `timestamp < cursor_ts` ordenadas por `(timestamp DESC, id DESC)`.
   Isto é estável mesmo com UUIDs v4 aleatórios.
2. `ApiClient.get_room_history` aceita `before_id` parameter
3. Comando `/history more` da CLI agora usa cursor: guarda o ID da mensagem mais velha
   vista em `state.history_offsets[tab_name]`, e passa como `before_id` na próxima
   chamada

Mantemos `offset` para backward compatibility, mas `before_id` tem precedência quando
ambos são fornecidos.

**Testes:** 2 testes em `TestCursorPagination` verificam que offset retorna mais novas
primeiro, e cursor retorna mensagens mais velhas sem duplicação.

### P1-C2-7: Comando `/notifications` na CLI (paridade com Desktop)

**Arquivo:** `client-cli/main.py`

**Problema:** A CLI não tinha um comando equivalente ao painel de notificações do
Desktop. DMs recebidas apareciam nas abas, mas não havia como ver um histórico de
notificações (amizades aceitas, solicitações pendentes, DMs recebidas enquanto offline).

**Correção:**
1. `ClientState` agora tem `notifications: list` (cada item é um dict com
   `type`, `sender`, `content`, `timestamp`, `read`)
2. Handlers de evento WS (`MESSAGE_RECEIVE` para DMs, `FRIEND_REQUEST_RECEIVED`,
   `FRIEND_ACCEPTED`) agora populam `state.notifications`
3. Novo comando `/notifications` mostra as últimas 20 notificações (mais novas
   primeiro), com indicador de lida/não-lida (✓/●), tipo (💬 DM, 🤝 Amizade aceita,
   📨 Solicitação), remetente, timestamp e preview do conteúdo
4. `/notifications clear` marca todas como lidas

### P1-C2-8: Fila offline persistente em disco

**Arquivo:** `shared/client/websocket.py`, `client-cli/main.py`,
`client-desktop/services/connection_service.py`

**Problema:** O `WebSocketClient` já tinha fila offline (`_offline_queue`) que
enfileirava mensagens quando o WS caía e re-enviava ao reconectar. Mas a fila era só em
memória — se o cliente fechasse enquanto offline, as mensagens eram perdidas.

**Correção:**
1. `WebSocketClient.__init__` agora aceita `username` parameter
2. `_get_offline_queue_path(username)` resolve caminho do arquivo de fila (prefere
   `server.paths.get_data_dir()` se disponível, senão `~/.chatpy/`)
3. `_load_persisted_queue()` carrega fila do disco no `__init__` e em `set_username()`
4. `_persist_queue()` salva fila em disco após cada `send_frame` enquanto offline
5. `_clear_persisted_queue()` remove arquivo após flush bem-sucedido
6. `_flush_offline_queue()` agora re-persiste se algumas mensagens falharem
7. CLI e Desktop chamam `ws.set_username(username)` após login
8. CLI e Desktop chamam `ws._persist_queue()` antes de fechar/logout

**Resultado:** Se o usuário escreve uma mensagem enquanto offline e fecha o app, a
mensagem é entregue quando ele reabrir o app e reconectar.

**Testes:** 2 testes em `TestOfflineQueuePersistence` verificam que fila é persistida
e recarregada, e que arquivo é removido após flush bem-sucedido.

## Próximos Passos Recomendados (não implementados)

Os itens abaixo foram identificados na auditoria mas **não** implementados neste ciclo:

1. **Migrar CLI para Textual** — substituir Typer/Rich+Live por Textual (TUI real com
   painéis, scroll nativo, input async sem gambiarras). Vale MUITO a pena.
2. **Implementar E2E nos clientes** — o scaffold já está pronto (X3DH, Double Ratchet,
   endpoints REST). Falta integrar a biblioteca `python-axolotl` nos clientes CLI e Desktop.
3. **Cliente Web (PWA)** — maximiza alcance da promessa "qualquer um conversa com qualquer um"
4. **Multi-linha no input da CLI** — Ctrl+J para newline, Enter para enviar
5. **Markdown rendering na CLI** — Rich suporta via `rich.markdown`
6. **Toast/inline errors no admin HTML** — substituir `alert()` por toasts
7. **WebSocket compression** (permessage-deflate) — banda em mobile
8. **Request ID propagation** para tracing distribuído
9. **Retry queue para DMs federadas** quando peer está offline (com TTL)
10. **Plugin system para bots** — carregar de `~/.chatpy/bots/`
11. **Salas federadas** — schema já existe em `federated_rooms`, falta implementar sync
12. **Multi-device support para E2E** — cada dispositivo com sua Identity Key
13. **Key Backup Service para E2E** — recuperação de dispositivo perdido
14. **Safety Numbers / fingerprint verification UX** — verificação out-of-band
15. **mDNS peer discovery para federação local** — servidores peers na mesma LAN
16. **Bridge para Matrix/IRC** — interop com redes existentes

## Nota Final

A fundação do projeto continua **excelente** — arquitetura modular, escolha de tecnologias,
observabilidade, docs. Os bugs corrigidos aqui eram todos problemas de produção que
impediam deploy confiável. Com os P0 corrigidos, o projeto está pronto para uso real em
LAN e, com E2E implementado, poderá competir com Signal/Matrix no nicho de chat
descentralizado, leve e anônimo.
