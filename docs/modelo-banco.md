# Modelo do Banco de Dados

O ChatPy usa SQLAlchemy com suporte a SQLite (default) e PostgreSQL.

## Tabelas

### users
Usuários do sistema.

| Campo | Tipo | Descrição |
|---|---|---|
| id | UUID | Chave primária |
| username | String(50) | Único, case-insensitive |
| password_hash | String(255) | Argon2 |
| status | String(20) | online/offline/away |
| created_at | DateTime | |
| is_guest | Boolean | True para contas efêmeras |
| expires_at | DateTime | TTL para guests (NULL para normais) |

### rooms
Salas de chat.

| Campo | Tipo | Descrição |
|---|---|---|
| id | UUID | |
| name | String(50) | Único, com prefixo # |
| is_private | Boolean | True se tem senha |
| password_hash | String(255) | Argon2 (NULL se pública) |
| description | String(255) | |
| created_at | DateTime | |

### room_members
Associação usuário ↔ sala.

| Campo | Tipo | Descrição |
|---|---|---|
| room_id | UUID | FK → rooms |
| user_id | UUID | FK → users |
| role | String(20) | owner/admin/member |
| joined_at | DateTime | |
| is_banned | Boolean | |

### messages
Mensagens de sala.

| Campo | Tipo | Descrição |
|---|---|---|
| id | UUID | |
| room_id | UUID | FK → rooms |
| sender_id | UUID | FK → users |
| content | Text | Máximo 5000 chars |
| timestamp | DateTime | |

### private_messages
DMs.

| Campo | Tipo | Descrição |
|---|---|---|
| id | UUID | |
| sender_id | UUID | |
| receiver_id | UUID | |
| content | Text | |
| timestamp | DateTime | |

### friendships
Relações de amizade.

| Campo | Tipo | Descrição |
|---|---|---|
| user_id | UUID | Quem enviou/bloqueou |
| friend_id | UUID | Destinatário |
| status | String(20) | pending/accepted/blocked |
| created_at | DateTime | |

### sessions
Sessões JWT (revogáveis).

| Campo | Tipo | Descrição |
|---|---|---|
| id | UUID | |
| user_id | UUID | |
| token | String(500) | JWT completo |
| expires_at | DateTime | |
| created_at | DateTime | |

### attachments
Anexos de mensagens.

| Campo | Tipo | Descrição |
|---|---|---|
| id | UUID | |
| uploader_id | UUID | |
| message_id | UUID | FK (nullable) |
| private_message_id | UUID | FK (nullable) |
| filename | String(255) | Sanitizado |
| stored_path | String(500) | Caminho no disco |
| mime_type | String(100) | |
| file_size | Integer | Bytes |

### login_attempts
Tentativas de login falhas (anti brute-force).

| Campo | Tipo | Descrição |
|---|---|---|
| id | UUID | |
| username | String(50) | |
| attempted_at | DateTime | |
| ip_address | String(45) | Para limite por IP |

### server_peers
Servidores federados.

| Campo | Tipo | Descrição |
|---|---|---|
| id | UUID | |
| domain | String(255) | Domínio do peer |
| base_url | String(500) | URL base |
| public_key | Text | Ed25519 PEM |
| trust_level | String(20) | trusted/verified/blocked |
| is_active | Boolean | |

### user_identity_keys
Chaves E2E (Signal Protocol).

| Campo | Tipo | Descrição |
|---|---|---|
| user_id | UUID | FK → users |
| public_key_pem | Text | Identity Key Ed25519 |
| signed_prekey_pem | Text | Signed PreKey atual |
| signed_prekey_signature | Text | Assinatura |

### one_time_prekeys
Pool de PreKeys para X3DH.

| Campo | Tipo | Descrição |
|---|---|---|
| id | UUID | |
| user_id | UUID | |
| key_id | Integer | Sequencial |
| public_key_pem | Text | Efêmera |
| used | Boolean | True após consumo |

### federated_rooms
Salas federadas (schema para futuro).

| Campo | Tipo | Descrição |
|---|---|---|
| id | UUID | |
| origin_room_id | UUID | UUID no servidor de origem |
| origin_server_domain | String(255) | |
| name | String(50) | |
| participating_servers | Text | JSON array de domains |
