# Modelo de Banco de Dados

O banco de dados deve ser suportado tanto em SQLite (foco no uso doméstico/Raspberry Pi) quanto PostgreSQL (ambientes escaláveis).

## Entidades e Tabelas Principais

### 1. `users` (Usuários)
- `id`: UUID (PK)
- `username`: String (Unique, Indexed)
- `password_hash`: String (Argon2 hash)
- `status`: String (online, offline, away)
- `created_at`: DateTime

### 2. `rooms` (Salas)
- `id`: UUID (PK)
- `name`: String (Unique, Indexed)
- `is_private`: Boolean (Pública ou Protegida)
- `password_hash`: String (Nullable, para salas protegidas)
- `description`: String (Nullable, descrição breve)
- `created_at`: DateTime

### 3. `room_members` (Membros da Sala)
- `room_id`: UUID (FK -> rooms.id)
- `user_id`: UUID (FK -> users.id)
- `role`: String (owner, admin, member)
- `joined_at`: DateTime
- `is_banned`: Boolean (Default: False)
- *PK: (room_id, user_id)*

### 4. `messages` (Mensagens de Salas)
- `id`: UUID (PK)
- `room_id`: UUID (FK -> rooms.id)
- `sender_id`: UUID (FK -> users.id)
- `content`: Text
- `timestamp`: DateTime

### 5. `private_messages` (Mensagens Diretas - DMs)
- `id`: UUID (PK)
- `sender_id`: UUID (FK -> users.id)
- `receiver_id`: UUID (FK -> users.id)
- `content`: Text
- `timestamp`: DateTime

### 6. `invites` (Convites e Amizades)
- `id`: UUID (PK)
- `sender_id`: UUID (FK -> users.id)
- `receiver_id`: UUID (FK -> users.id)
- `status`: String (pending, accepted, rejected)
- `created_at`: DateTime

### 7. `sessions` (Sessões / Tokens)
- `id`: UUID (PK)
- `user_id`: UUID (FK -> users.id)
- `token`: String (Unique)
- `expires_at`: DateTime
- `created_at`: DateTime

### 8. `friendships` (Amizades e Bloqueios)
- `user_id`: UUID (FK -> users.id, PK)
- `friend_id`: UUID (FK -> users.id, PK)
- `status`: String (pending, accepted, blocked)
- `created_at`: DateTime
- *PK: (user_id, friend_id)*

### 9. `attachments` (Anexos de Mensagens)
- `id`: UUID (PK)
- `uploader_id`: UUID (FK -> users.id)
- `message_id`: UUID (FK -> messages.id, Nullable)
- `private_message_id`: UUID (FK -> private_messages.id, Nullable)
- `filename`: String (Nome original)
- `stored_path`: String (Caminho no servidor)
- `mime_type`: String (Tipo MIME)
- `file_size`: Integer (Tamanho em bytes)
- `uploaded_at`: DateTime

