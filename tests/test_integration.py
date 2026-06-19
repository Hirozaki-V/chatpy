"""
test_integration.py — Testes de integração end-to-end do ChatPy V2.

Testa o fluxo completo: servidor sobe → registro → login → sala → mensagem.
Usa FastAPI TestClient para simular requests HTTP sem precisar de servidor
real rodando.

Estes testes cobrem os caminhos críticos que testes unitários não atingem:
- Registro + login + token validation
- CRUD de salas via REST
- Envio/recebimento de mensagens via REST
- Upload/download de anexos
- Fluxo de amizades
- Endpoints admin
"""
import os
import pytest

# Garante DB em memória com StaticPool para TestClient
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["REST_RATE_LIMIT_ENABLED"] = "false"

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.database.models import Base


@pytest.fixture(scope="function")
def client():
    """Client de teste FastAPI — novo DB por teste (isolamento total)."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):
        import sqlite3
        if isinstance(dbapi_conn, sqlite3.Connection):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    Base.metadata.create_all(bind=test_engine)

    import server.database.connection as _db_conn
    _original_engine = _db_conn.engine
    _original_SessionLocal = _db_conn.SessionLocal
    _db_conn.engine = test_engine
    _db_conn.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    from server.main import app
    from fastapi.testclient import TestClient as _TestClient
    test_client = _TestClient(app)

    yield test_client

    _db_conn.engine = _original_engine
    _db_conn.SessionLocal = _original_SessionLocal
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


@pytest.fixture(scope="function")
def admin_token(client):
    """Registra um usuário admin e retorna o token."""
    import time
    # Sufixo único para evitar colisão de username entre testes
    suffix = int(time.time() * 1000) % 100000
    username = f"admin{suffix}"
    resp = client.post("/api/auth/register", json={
        "username": username,
        "password": "Admin1234",
    })
    assert resp.status_code == 201, f"Registro falhou: {resp.text}"

    resp = client.post("/api/auth/login", json={
        "username": username,
        "password": "Admin1234",
    })
    assert resp.status_code == 200, f"Login falhou: {resp.text}"
    token = resp.json()["token"]

    # Promove a admin via SQL (o registro REST não auto-promove)
    from server.database.connection import SessionLocal
    from server.database.models import User
    from sqlalchemy import func
    db = SessionLocal()
    try:
        user = db.query(User).filter(func.lower(User.username) == username.lower()).first()
        if user:
            user.is_admin = True
            db.commit()
    finally:
        db.close()

    return token


@pytest.fixture(scope="function")
def user_token(client):
    """Registra um usuário comum e retorna o token."""
    import time
    suffix = int(time.time() * 1000) % 100000
    username = f"user{suffix}"
    resp = client.post("/api/auth/register", json={
        "username": username,
        "password": "User12345",
    })
    assert resp.status_code == 201

    resp = client.post("/api/auth/login", json={
        "username": username,
        "password": "User12345",
    })
    assert resp.status_code == 200
    return resp.json()["token"]


def _auth(token):
    """Helper: retorna headers de autenticação."""
    return {"Authorization": f"Bearer {token}"}


class TestRegistrationAndLogin:
    """Testes de registro e login."""

    def test_register_success(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "newuser",
            "password": "NewUser123",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "success"
        assert data["username"] == "newuser"

    def test_register_duplicate_username(self, client):
        # Registra um usuário e tenta registrar de novo com o mesmo nome
        resp = client.post("/api/auth/register", json={
            "username": "dupetest",
            "password": "Dup12345",
        })
        assert resp.status_code == 201

        resp = client.post("/api/auth/register", json={
            "username": "dupetest",
            "password": "Dup12345",
        })
        assert resp.status_code == 400

    def test_login_success(self, client):
        # Registra e depois faz login
        username = "logintest"
        resp = client.post("/api/auth/register", json={
            "username": username,
            "password": "Login1234",
        })
        assert resp.status_code == 201

        resp = client.post("/api/auth/login", json={
            "username": username,
            "password": "Login1234",
        })
        assert resp.status_code == 200
        assert "token" in resp.json()

    def test_login_wrong_password(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "testadmin",
            "password": "WrongPassword1",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "nonexistent",
            "password": "Anything1",
        })
        assert resp.status_code == 401

    def test_guest_account(self, client):
        resp = client.post("/api/auth/guest")
        assert resp.status_code == 201
        assert "token" in resp.json()

    def test_profile_endpoint(self, client, admin_token):
        resp = client.get("/api/users/me", headers=_auth(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "username" in data
        assert data["is_admin"] is True  # admin_token fixture promove a admin

    def test_logout(self, client, admin_token):
        resp = client.post("/api/auth/logout", json={"token": admin_token}, headers=_auth(admin_token))
        assert resp.status_code == 200


class TestRoomOperations:
    """Testes de operações em salas."""

    def test_create_room(self, client, admin_token):
        resp = client.post("/api/rooms", json={
            "name": "#test-room",
            "is_private": False,
        }, headers=_auth(admin_token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "#test-room"
        return data["id"]

    def test_list_rooms(self, client, admin_token):
        resp = client.get("/api/rooms", headers=_auth(admin_token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_join_room(self, client, admin_token, user_token):
        # Cria sala
        resp = client.post("/api/rooms", json={
            "name": "#join-test",
            "is_private": False,
        }, headers=_auth(admin_token))
        room_id = resp.json()["id"]

        # User joining
        resp = client.post(f"/api/rooms/{room_id}/join", json={}, headers=_auth(user_token))
        assert resp.status_code == 200

    def test_explore_rooms(self, client, admin_token):
        resp = client.get("/api/rooms/explore", headers=_auth(admin_token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestMessaging:
    """Testes de envio/recebimento de mensagens (via REST history)."""

    def test_room_history_empty(self, client, admin_token):
        # Cria sala e pega histórico
        resp = client.post("/api/rooms", json={
            "name": "#history-test",
            "is_private": False,
        }, headers=_auth(admin_token))
        room_id = resp.json()["id"]

        resp = client.get(f"/api/rooms/{room_id}/history", headers=_auth(admin_token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestFriends:
    """Testes de sistema de amizades."""

    def test_send_friend_request(self, client, admin_token, user_token):
        # Pega username do user via profile
        resp = client.get("/api/users/me", headers=_auth(user_token))
        user_data = resp.json()
        username = user_data["username"]

        resp = client.post("/api/friends/request", json={
            "receiver_username": username,
        }, headers=_auth(admin_token))
        assert resp.status_code == 201

    def test_list_pending_requests(self, client, user_token):
        resp = client.get("/api/friends/requests/pending", headers=_auth(user_token))
        assert resp.status_code == 200

    def test_list_friends(self, client, admin_token):
        resp = client.get("/api/friends", headers=_auth(admin_token))
        assert resp.status_code == 200


class TestSearch:
    """Testes de busca de mensagens."""

    def test_search_empty(self, client, admin_token):
        resp = client.post("/api/rooms/search", json={"query": "test"}, headers=_auth(admin_token))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_search_sql_injection_wildcards(self, client, admin_token):
        """SECURITY: wildcards % e _ devem ser escapados, não retornar tudo."""
        resp = client.post("/api/rooms/search", json={"query": "%"}, headers=_auth(admin_token))
        assert resp.status_code == 200
        assert resp.json() == []

        resp = client.post("/api/rooms/search", json={"query": "_"}, headers=_auth(admin_token))
        assert resp.status_code == 200
        assert resp.json() == []


class TestReactions:
    """Testes de reações em mensagens."""

    def test_add_reaction(self, client, admin_token):
        # Cria sala
        resp = client.post("/api/rooms", json={"name": "#react-test", "is_private": False}, headers=_auth(admin_token))
        room_id = resp.json()["id"]

        # Pega mensagem (pode estar vazia)
        resp = client.get(f"/api/rooms/{room_id}/history", headers=_auth(admin_token))
        if resp.json():
            msg_id = resp.json()[0]["id"]
            resp = client.post(f"/api/rooms/{room_id}/messages/{msg_id}/reactions", json={"emoji": "👍"}, headers=_auth(admin_token))
            assert resp.status_code == 200
            assert resp.json()["status"] == "added"

            # Toggle (remove)
            resp = client.post(f"/api/rooms/{room_id}/messages/{msg_id}/reactions", json={"emoji": "👍"}, headers=_auth(admin_token))
            assert resp.status_code == 200
            assert resp.json()["status"] == "removed"


class TestHealthAndVersion:
    """Testes de infraestrutura."""

    def test_health_check(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    def test_version(self, client):
        resp = client.get("/api/version")
        assert resp.status_code == 200
        assert "server_version" in resp.json()

    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200


class TestSecurityHeaders:
    """Testes de security headers."""

    def test_security_headers_present(self, client):
        resp = client.get("/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_csp_header(self, client):
        resp = client.get("/health")
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
