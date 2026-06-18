"""
#15: Configuração do Alembic.

Lê DATABASE_URL do ambiente (mesma variável usada pelo SQLAlchemy).
Importa todos os models de server.database.models para que o
autogenerate detecte mudanças.
"""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Carrega .env se disponível
try:
    from dotenv import load_dotenv
    for env_path in (".env", "../.env"):
        if os.path.exists(env_path):
            load_dotenv(env_path)
            break
except ImportError:
    pass

# Importa os models para que o autogenerate os detecte
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.database.models import Base
# Importa todas as classes para garantir que estão registradas no Base.metadata
from server.database.models import (
    User, Room, RoomMember, Message, PrivateMessage, Friendship,
    Session, Attachment, LoginAttempt, ServerPeer,
)

# Configuração do Alembic
config = context.config

# Sobrescreve sqlalchemy.url com DATABASE_URL do ambiente
database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
if database_url:
    # Correção para PostgreSQL (Heroku/Render usam postgres://)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    config.set_main_option("sqlalchemy.url", database_url)

# Configura logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata para autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Roda migrations em modo offline — gera SQL sem conectar ao banco.
    Útil para revisar o que será executado antes de aplicar.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # detecta mudanças de tipo
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Roda migrations em modo online — conecta ao banco e aplica.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
