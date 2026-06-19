"""
conftest.py — fixtures e configuração global para os testes do ChatPy.

PROBLEMA RESOLVIDO (auditoria-2026-06):
- 12 testes falhavam porque o rate limiter REST global derrubava requisições
  em série com 429 Too Many Requests.
- Cada teste tinha que setar `os.environ["REST_RATE_LIMIT_ENABLED"] = "false"`
  individualmente — quem esquecesse, falhava.
- Agora o conftest seta isto globalmente ANTES de qualquer import de
  server.main, garantindo comportamento consistente em todos os testes.

OUTRAS CONFIGS:
- DATABASE_URL em memória por default (cada teste pode override).
- JWT_SECRET fixo (mínimo 16 chars para passar validação).
- QT_QPA_PLATFORM=offscreen para testes PySide6 em headless.
"""
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuração de env vars GLOBAIS para testes — DEVE acontecer antes de
# qualquer import de server.* ou shared.*
# ---------------------------------------------------------------------------
os.environ.setdefault("REST_RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-pytest-global-32-chars")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("FEDERATION_ENABLED", "false")
os.environ.setdefault("CHATPY_SERVER_DOMAIN", "test.local")
os.environ.setdefault("CHATPY_SERVER_BASE_URL", "http://test.local")
# PySide6 headless
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ---------------------------------------------------------------------------
# Garante que diretórios do projeto estão no sys.path para imports relativos
# funcionarem tanto em `pytest` quanto em `pytest tests/test_xxx.py`
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "client-desktop"), str(_ROOT / "client-cli")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Fixtures compartilhadas (estendidas por testes conforme necessário)
# ---------------------------------------------------------------------------
import pytest  # noqa: E402


@pytest.fixture(scope="function")
def db_session():
    """Fixture que fornece uma session SQLAlchemy com rollback automático.

    Usa o engine global do server.database.connection — cada teste chama
    Base.metadata.create_all() no setUp, e a session é fechada no teardown.
    """
    from server.database.connection import SessionLocal
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def reset_db():
    """Reseta o banco de dados entre testes (drop + create)."""
    from server.database.connection import engine
    from server.database.models import Base
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
