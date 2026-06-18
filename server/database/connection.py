import os
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from .models import Base

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or "sqlite:///chatpy.db"

# Correção amigável para drivers PostgreSQL (Heroku/Render usam postgres://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    # check_same_thread é necessário para testes e laços assíncronos que usam sqlite3
    connect_args["check_same_thread"] = False

# Pool pre-ping evita erros com conexões ociosas expiradas em produção
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Otimizações SQLite para alta concorrência
# ---------------------------------------------------------------------------
@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_conn, _record):
    """
    Aplica PRAGMAs de concorrência e performance quando o banco é SQLite.
    - WAL mode: permite múltiplos leitores + 1 escritor concorrente.
    - busy_timeout: espera até 5s em locks antes de falhar.
    - foreign_keys: aplica integridade referencial.
    """
    if not DATABASE_URL.startswith("sqlite"):
        return
    import sqlite3
    if isinstance(dbapi_conn, sqlite3.Connection):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def init_db():
    """
    Inicializa o banco de dados criando todas as tabelas se estas não existirem.
    Garante a existência da sala padrão #geral.
    Usa o mesmo context manager get_db — consistência de pattern.
    """
    Base.metadata.create_all(bind=engine)

    # Garante a existência da sala padrão #geral usando SessionLocal
    from .models import Room
    import uuid
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        geral = db.query(Room).filter(Room.name == "#geral").first()
        if not geral:
            geral = Room(
                id=uuid.uuid4(),
                name="#geral",
                is_private=False,
                created_at=datetime.now(timezone.utc),
            )
            db.add(geral)
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_db():
    """
    Context manager para fornecer uma sessão do banco de dados com commit/rollback
    automáticos e fechamento seguro de conexões.
    """
    db = SessionLocal()
    try:
        yield db
        # Commita sempre que houver transação ativa (mesmo após flush).
        # Antes a checagem `if db.new or db.dirty or db.deleted` falhava em
        # endpoints que já tinham chamado flush() — os objetos saíam do
        # estado 'new' mas a transação não era commitada.
        if db.in_transaction():
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_api():
    """Gerador de sessão do banco de dados compatível com dependências do FastAPI."""
    with get_db() as db:
        yield db
