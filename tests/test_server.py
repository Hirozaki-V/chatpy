import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

# Configura banco de dados temporário para testes isolados antes de importar a conexão
TEST_DB_FILE = "test_chatpy.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE}"
os.environ["JWT_SECRET"] = "test-jwt-secret-key-for-unit-tests-1234"
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.database.connection import init_db, SessionLocal
from server.database.models import User, Room, RoomMember, Session as DbSession
from server.auth.security import hash_password, verify_password, create_access_token, decode_access_token
from server.auth.service import registrar_usuario, autenticar_usuario, UsernameTakenError, InvalidCredentialsError
from server.websocket.rate_limit import RateLimiter
from server.websocket.manager import ConnectionManager
from server.websocket.dispatcher import WebSocketDispatcher

class MockWebSocket:
    def __init__(self):
        self.sent_messages = []

    async def send_text(self, text: str):
        self.sent_messages.append(text)

    async def send_json(self, data: dict):
        import json
        self.sent_messages.append(json.dumps(data))

    async def send(self, data: str):
        self.sent_messages.append(data)


class TestDatabaseAndModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    @classmethod
    def tearDownClass(cls):
        # Remove arquivo de teste após o término do grupo
        if os.path.exists(TEST_DB_FILE):
            try:
                os.remove(TEST_DB_FILE)
            except OSError:
                pass

    def setUp(self):
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_database_persistence(self):
        # Cria usuário
        user = User(
            id=uuid4(),
            username="db_test_user",
            password_hash="somehash",
            status="offline",
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(user)
        self.db.commit()

        # Busca do banco
        db_user = self.db.query(User).filter(User.username == "db_test_user").first()
        self.assertIsNotNone(db_user)
        self.assertEqual(db_user.password_hash, "somehash")


class TestAuthAndSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_password_hashing(self):
        password = "my-secret-password-123"
        hashed = hash_password(password)
        self.assertTrue(verify_password(password, hashed))
        self.assertFalse(verify_password("wrong-password", hashed))

    def test_jwt_tokens(self):
        data = {"sub": str(uuid4()), "username": "token_user"}
        token = create_access_token(data, expires_delta=timedelta(minutes=5))
        
        claims = decode_access_token(token)
        self.assertIsNotNone(claims)
        self.assertEqual(claims["username"], "token_user") # type: ignore

        # Validação de token expirado
        expired_token = create_access_token(data, expires_delta=timedelta(minutes=-5))
        self.assertIsNone(decode_access_token(expired_token))

    def test_auth_services(self):
        username = "service_user"
        password = "password123"

        # Registro
        user = registrar_usuario(self.db, username, password)
        self.db.commit()
        self.assertEqual(user.username, username)

        # Registro de username duplicado
        with self.assertRaises(UsernameTakenError):
            registrar_usuario(self.db, username, password)

        # Login bem sucedido
        token = autenticar_usuario(self.db, username, password)
        self.assertIsNotNone(token)

        # Verifica se sessão foi persistida no BD
        session_rec = self.db.query(DbSession).filter(DbSession.user_id == user.id).first()
        self.assertIsNotNone(session_rec)
        self.assertEqual(session_rec.token, token)

        # Login falhando (senha errada)
        with self.assertRaises(InvalidCredentialsError):
            autenticar_usuario(self.db, username, "wrongpassword")

        # Login falhando (usuário inexistente)
        with self.assertRaises(InvalidCredentialsError):
            autenticar_usuario(self.db, "not_exist", password)


class TestRateLimiter(unittest.TestCase):
    def test_rate_limiting_triggers_and_mutes(self):
        limiter = RateLimiter(max_messages=2, window_seconds=1.0, mute_duration_seconds=2.0)
        user = "spammer"

        # Primeira mensagem: OK
        self.assertFalse(limiter.record_message_and_check_flood(user))
        self.assertFalse(limiter.is_muted(user))

        # Segunda mensagem: OK (limite = 2)
        self.assertFalse(limiter.record_message_and_check_flood(user))
        self.assertFalse(limiter.is_muted(user))

        # Terceira mensagem: Flood detectado (muta)
        self.assertTrue(limiter.record_message_and_check_flood(user))
        self.assertTrue(limiter.is_muted(user))
        self.assertGreater(limiter.get_remaining_mute_time(user), 0)


class TestWebSocketManager(unittest.IsolatedAsyncioTestCase):
    async def test_connection_management(self):
        manager = ConnectionManager()
        user_id = uuid4()
        ws = MockWebSocket()

        await manager.connect(user_id, "chat_user", ws)
        self.assertTrue(manager.is_user_connected(user_id))
        self.assertEqual(manager.user_names[user_id], "chat_user")

        # Envia mensagem pessoal
        test_msg = {"hello": "world"}
        await manager.send_personal_message(test_msg, user_id)
        self.assertEqual(len(ws.sent_messages), 1)

        # Desconecta
        await manager.disconnect(user_id)
        self.assertFalse(manager.is_user_connected(user_id))


class TestWebSocketDispatcher(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from server.database.connection import engine
        from server.database.models import Base
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        
        self.db = SessionLocal()
        self.manager = ConnectionManager()
        self.rate_limiter = RateLimiter()
        self.dispatcher = WebSocketDispatcher(self.manager, self.rate_limiter)
        
        # Cria usuário no BD de teste
        self.test_user_id = uuid4()
        self.test_username = "dispatcher_user"
        pwd_hash = hash_password("mypassword")
        user = User(id=self.test_user_id, username=self.test_username, password_hash=pwd_hash)
        self.db.add(user)
        self.db.commit()

        # Gera token para autenticar
        self.token = create_access_token({"sub": str(self.test_user_id), "username": self.test_username})

        # CORREÇÃO: o dispatcher agora valida se a sessão existe na tabela
        # 'sessions' (consistência com REST). Sem este registro, a autenticação
        # WS falha com "Sessão revogada ou usuário inexistente." — comportamento
        # correto do servidor. O teste precisa persistir a sessão.
        from datetime import datetime, timezone, timedelta
        session_rec = DbSession(
            id=uuid4(),
            user_id=self.test_user_id,
            token=self.token,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(session_rec)
        self.db.commit()

    async def asyncTearDown(self):
        self.db.close()

    async def test_dispatch_unauthenticated_blocked(self):
        ws = MockWebSocket()
        raw_msg = '{"event": "message.send_room", "payload": {"room_id": "8aa181a9-d652-4467-bc0c-df27c9f8df59", "content": "olá"}}'
        auth_id = await self.dispatcher.dispatch(ws, None, raw_msg)
        self.assertIsNone(auth_id)
        self.assertEqual(len(ws.sent_messages), 1)
        self.assertIn("autenticado", ws.sent_messages[0])

    async def test_dispatch_authentication_lifecycle(self):
        ws = MockWebSocket()
        raw_auth_msg = f'{{"event": "auth.authenticate", "payload": {{"token": "{self.token}"}}}}'
        
        # Faz autenticação
        auth_id = await self.dispatcher.dispatch(ws, None, raw_auth_msg)
        if auth_id is None:
            print("AUTH FAILED. Sent messages:", ws.sent_messages)
        self.assertEqual(auth_id, self.test_user_id)
        self.assertTrue(self.manager.is_user_connected(self.test_user_id))

        # Verifica mensagem de sucesso de auth enviada de volta
        self.assertEqual(len(ws.sent_messages), 1)
        self.assertIn("auth.success", ws.sent_messages[0])

        # Cria uma sala no BD
        room_id = uuid4()
        room = Room(id=room_id, name="#general", is_private=False)
        self.db.add(room)
        # Adiciona o usuário como membro da sala
        member = RoomMember(room_id=room_id, user_id=self.test_user_id, role="member")
        self.db.add(member)
        self.db.commit()

        # Envia mensagem para a sala
        ws_room = MockWebSocket()
        await self.manager.connect(self.test_user_id, self.test_username, ws_room)
        
        raw_room_msg = f'{{"event": "message.send_room", "payload": {{"room_id": "{room_id}", "content": "Test Room Message"}}}}'
        await self.dispatcher.dispatch(ws_room, self.test_user_id, raw_room_msg)

        # Verifica se o broadcast foi recebido pelo socket do usuário
        receive_msgs = [m for m in ws_room.sent_messages if "message.receive" in m]
        self.assertEqual(len(receive_msgs), 1)
        self.assertIn("Test Room Message", receive_msgs[0])


if __name__ == "__main__":
    unittest.main()
