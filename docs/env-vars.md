# Variáveis de Ambiente

Todas as variáveis que o ChatPy aceita, organizadas por categoria.

## Segurança (obrigatórias)

| Variável | Default | Descrição |
|---|---|---|
| `JWT_SECRET` | (obrigatório) | Chave para assinar JWT. Mínimo 16 caracteres. |

## Banco de dados

| Variável | Default | Descrição |
|---|---|---|
| `DATABASE_URL` | `sqlite:///chatpy.db` | URL do banco. SQLite ou PostgreSQL. |
| `POSTGRES_URL` | (alternativa) | Mesmo que DATABASE_URL (compatibilidade). |

## Servidor

| Variável | Default | Descrição |
|---|---|---|
| `CORS_ORIGINS` | `http://localhost,http://127.0.0.1` | Origens permitidas, separadas por vírgula. Use `*` para permitir todas. |
| `LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING, ERROR. |
| `LOG_FORMAT` | `text` | `text` (legível) ou `json` (estruturado para produção). |
| `UPLOAD_DIR` | `uploads` | Diretório para salvar anexos. |

## Rate limiting

| Variável | Default | Descrição |
|---|---|---|
| `REST_RATE_LIMIT_ENABLED` | `true` | Liga/desliga rate limit REST. |
| `REST_RATE_LIMIT_PER_MINUTE` | `60` | Requisições por minuto por IP. |
| `REST_RATE_LIMIT_BURST` | `10` | Pico inicial permitido. |
| `REST_RATE_LIMIT_WINDOW` | `60` | Janela em segundos. |
| `SENSITIVE_ENDPOINT_LIMIT_PER_MINUTE` | `10` | Limite para login/register/guest. |
| `RATE_LIMIT_MAX_MESSAGES` | `10` | Mensagens WebSocket por janela. |
| `RATE_LIMIT_WINDOW_SECONDS` | `5.0` | Janela do rate limit WS em segundos. |
| `RATE_LIMIT_MUTE_DURATION` | `30.0` | Duração do mute por flood (segundos). |

## Anti brute-force

| Variável | Default | Descrição |
|---|---|---|
| `LOGIN_MAX_ATTEMPTS` | `5` | Tentativas falhas por username antes do lockout. |
| `LOGIN_WINDOW_SECONDS` | `300` | Janela de tempo das tentativas (5 min). |
| `LOGIN_LOCK_SECONDS` | `600` | Duração do lockout por username (10 min). |
| `LOGIN_MAX_ATTEMPTS_PER_IP` | `20` | Tentativas falhas por IP antes do lockout. |
| `LOGIN_IP_LOCK_SECONDS` | `1800` | Duração do lockout por IP (30 min). |

## Anexos

| Variável | Default | Descrição |
|---|---|---|
| `MAX_FILE_SIZE` | `10485760` | Tamanho máximo de anexo em bytes (10 MB). |
| `GUEST_MAX_FILE_SIZE` | `1048576` | Tamanho máximo para guests (1 MB). |

## Modo convidado

| Variável | Default | Descrição |
|---|---|---|
| `GUEST_TTL_HOURS` | `24` | Tempo de vida de contas guest em horas. |
| `GUEST_USERNAME_PREFIX` | `guest_` | Prefixo dos usernames de guest. |
| `GUEST_USERNAME_LEN` | `8` | Comprimento do sufixo aleatório. |

## Backup

| Variável | Default | Descrição |
|---|---|---|
| `BACKUP_ENABLED` | `false` | Habilita backup automático SQLite. |
| `BACKUP_INTERVAL_HOURS` | `24` | Frequência do backup em horas. |
| `BACKUP_KEEP_COUNT` | `7` | Quantos backups manter. |
| `BACKUP_DIR` | `/app/data/backups` | Diretório dos backups. |

## Federação

| Variável | Default | Descrição |
|---|---|---|
| `FEDERATION_ENABLED` | `false` | Habilita federação entre servidores. |
| `FEDERATION_OPEN` | `false` | Aceita DMs de qualquer servidor (true) ou só de peers registrados (false). |
| `CHATPY_SERVER_DOMAIN` | (vazio) | Domínio deste servidor para federação. |
| `CHATPY_SERVER_BASE_URL` | (vazio) | URL base pública para federação. |

## LAN discovery

| Variável | Default | Descrição |
|---|---|---|
| `LAN_DISCOVERY_ENABLED` | `true` | Habilita descoberta via mDNS. |
| `LAN_DISCOVERY_PORT` | `5000` | Porta anunciada via mDNS. |

## Bots

| Variável | Default | Descrição |
|---|---|---|
| `BOT_ECHO_ENABLED` | `true` | Habilita bot de teste (EchoBot). |

## Cliente (auto-away)

| Variável | Default | Descrição |
|---|---|---|
| `IDLE_TIMEOUT_SECONDS` | `300` | Segundos de inatividade antes de auto-away (5 min). |

## Cliente Desktop (URLs)

| Variável | Default | Descrição |
|---|---|---|
| `CHATPY_HOST` | `127.0.0.1` | Host padrão do servidor. |
| `CHATPY_PORT` | `5000` | Porta padrão. |
| `CHATPY_API_URL` | `http://{host}:{port}` | URL da API. |
| `CHATPY_WS_URL` | `ws://{host}:{port}/ws` | URL do WebSocket. |
