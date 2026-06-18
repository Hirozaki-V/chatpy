# Guia: Migrar ChatPy de SQLite para PostgreSQL

O ChatPy usa SQLite por padrão (zero configuração, ideal para Raspberry Pi).
Para cenários de maior escala (100+ usuários, alta concorrência), PostgreSQL
oferece melhor performance e concorrência.

## 1. Subir PostgreSQL via Docker

```bash
# Subir servidor + Postgres juntos
docker compose --profile database up -d
```

Ou manualmente:

```bash
docker run -d \
  --name chatpy-db \
  -e POSTGRES_USER=chatpy_user \
  -e POSTGRES_PASSWORD=chatpy_pass \
  -e POSTGRES_DB=chatpy \
  -p 5432:5432 \
  postgres:15-alpine
```

## 2. Configurar DATABASE_URL

No arquivo `.env`:

```env
DATABASE_URL=postgresql://chatpy_user:chatpy_pass@chatpy-db:5432/chatpy
```

Para servidores Heroku/Render que usam `postgres://`:

```env
DATABASE_URL=postgres://...  # o ChatPy converte automaticamente
```

## 3. Aplicar migrations

```bash
# Instalar alembic se ainda não tiver
pip install alembic

# Aplicar todas as migrations
alembic upgrade head
```

Ou sem Alembic (cria todas as tabelas de uma vez):

```bash
python -c "from server.database.connection import init_db; init_db()"
```

## 4. Migrar dados existentes do SQLite (opcional)

Se você já tem dados no SQLite e quer migrar para Postgres:

```bash
# Export do SQLite
sqlite3 chatpy.db .dump > dump.sql

# Ajusta sintaxe SQLite → PostgreSQL (PRAGMAs, etc.)
# Remove linhas PRAGMA e ajusta AUTOINCREMENT → SERIAL
grep -v "PRAGMA" dump.sql | sed 's/AUTOINCREMENT/SERIAL/g' > dump_pg.sql

# Import no Postgres
psql -h localhost -U chatpy_user -d chatpy < dump_pg.sql
```

## 5. Verificar

```bash
# Healthcheck deve mostrar database: ok
curl http://localhost:5000/health

# Verificar tabelas criadas
psql -h localhost -U chatpy_user -d chatpy -c "\dt"
```

## Diferenças de comportamento

| Aspecto | SQLite | PostgreSQL |
|---|---|---|
| Concorrência | 1 writer por vez (WAL mode) | Múltiplos writers concorrentes |
| Tipo UUID | CHAR(36) | UUID nativo |
| Timestamps | Naive datetime (sem tz) | Timezone-aware |
| Pool de conexões | `check_same_thread=False` | `pool_pre_ping=True` |
| Backup | `VACUUM INTO` (cópia consistente) | `pg_dump` (já recomendado) |

## Notas

- O ChatPy detecta automaticamente o tipo de banco via `DATABASE_URL`
- O tipo `GUID` no SQLAlchemy usa `UUID` nativo no Postgres e `CHAR(36)` no SQLite
- PRAGMAs de otimização SQLite (WAL, busy_timeout) são aplicados apenas quando SQLite
- O backup automático (`server/backup.py`) só funciona com SQLite — para Postgres, use `pg_dump` via cron
