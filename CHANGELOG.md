# CHANGELOG

## v2.0.1 (2026-06-18)

### Adicionado
- Federação entre servidores (DMs cross-server com assinatura Ed25519)
- Modo convidado (contas efêmeras, TTL 24h)
- Sync de presença federada entre peers
- Framework de bots (`!comandos` em salas)
- Painel admin web (`/admin`)
- Métricas Prometheus (`/metrics`) + dashboard Grafana
- Backup automático SQLite
- LAN discovery via mDNS (zeroconf)
- Rate limiting REST (middleware global)
- Anti brute-force por IP (além de username)
- Auto-update (endpoint `/api/version` + check no cliente)
- Offline sync queue (fila de mensagens no WebSocketClient)
- Tab-completion de @nick e #sala no Desktop
- Indicador "digitando..." em tempo real (Desktop + CLI)
- Badges de não-lidas por aba
- Auto-away por ociosidade (Desktop + CLI)
- Marketplace de temas (import/export .chatpy-theme)
- Anexos na CLI (`/upload`, `/download`)
- DMs federadas na CLI (`/fmsg @user@dominio`)
- Tema light na CLI
- Schema migration com Alembic
- E2E scaffold (Identity Keys + OneTime PreKeys + endpoints)
- Schema para salas federadas
- CI/CD com GitHub Actions
- Logging estruturado JSON
- Healthcheck multi-componente (DB + WebSocket + rate limiter + federação)
- CORS com auto-detecção de IP LAN
- Limites para usuários guest (sem salas privadas, sem admin, anexos 1MB)
- Persistência de histórico local entre sessões (Desktop)
- Persistência de geometria da janela (Desktop, QSettings)
- Tray icon com menu de contexto (Desktop)
- Atalhos de teclado (Ctrl+Tab, Ctrl+W, Ctrl+Q, F1, Ctrl+K)
- Diálogo de ajuda (F1)
- Confirmações para ações destrutivas (kick, ban, fechar DM)
- Admin de peers federados (REST + UI Desktop)
- PyInstaller spec para empacotamento Desktop
- prompt_toolkit para input assíncrono na CLI (Unix)
- Documentação: CONTRIBUTING, ARCHITECTURE, guia Postgres, design docs E2E e Web

### Corrigido
- docker-compose.yml: removido depends_on de chatpy-cache (opcional)
- Endpoint /logout agora exige autenticação
- XSS via filename de anexo no Desktop
- Path traversal em nome de arquivo de anexo
- Memory leak: removeTab sem deleteLater
- Segfault em re-login: closeEvent não desconectava sinais
- Double-escape HTML no controller vs view
- setHtml() resetando scroll ao inserir imagem
- time.sleep(1.5) vulnerável a race com logout
- HTTP síncrono congelando UI em _handle_my_rooms e context menu
- Storm de chamadas em _load_room_members_async
- Testes quebrados (Invite removido, /api/invites renomeado, senhas fracas)
- 8 arquivos de teste corrigidos (sessions não persistidas)

### Refatorado
- main_window.py: 2700 → 1900 linhas (7 diálogos extraídos para ui/dialogs/)
- Helpers compartilhados movidos para ui/helpers.py
- threading.Thread migrado para QThreadPool via async_helper
- EmojiSelectorDialog com instância cacheada
- Diálogos redimensionáveis (setFixedSize → setMinimumSize)
- _get_selected_username usando Qt.UserRole (não mais text.split)
- shared/types/ removido (código morto)
- Allowlist de anexos extraída para shared/allowed_attachments.py (DRY)

## v2.0.0

- Reconstrução completa do zero
- Arquitetura API-First com FastAPI + WebSocket
- Dois clientes oficiais (Desktop PySide6 + CLI Typer/Rich)
- Protocolo versionado com Pydantic
- Argon2 + JWT + sessões revogáveis
- Salas públicas e privadas com roles
- DMs entre amigos
- Anexos com allowlist
- Docker multi-stage
