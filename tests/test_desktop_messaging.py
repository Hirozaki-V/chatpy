import os
import sys
import unittest
import uuid
from fastapi.testclient import TestClient

TEST_MSG_DB = "test_messaging.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_MSG_DB}"
os.environ["JWT_SECRET"] = "test-jwt-secret-key-for-messaging-tests-1234"
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.main import app
from server.database.connection import init_db, SessionLocal
from server.database.models import Base, User, Room, RoomMember, Session as DbSession, Friendship
from server.auth.security import create_access_token, hash_password
from shared.events import EventType

class TestWebSocketMessaging(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from server.database.connection import engine
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        
        # Garante a existência da sala #geral
        init_db()
        
        cls.db = SessionLocal()
        
        # Cadastra usuários de teste
        cls.user_a_id = uuid.uuid4()
        cls.user_b_id = uuid.uuid4()
        
        user_a = User(
            id=cls.user_a_id,
            username="user_a",
            password_hash=hash_password("password_a"),
            status="offline"
        )
        user_b = User(
            id=cls.user_b_id,
            username="user_b",
            password_hash=hash_password("password_b"),
            status="offline"
        )
        cls.db.add(user_a)
        cls.db.add(user_b)
        cls.db.commit()

        # Cria amizade A <-> B (necessário para o teste de DM — o servidor
        # rejeita DMs entre não-amigos com error.alert 403 "Acesso negado".
        # bug pré-existente no teste: o teste assumia que DM funcionava sem
        # amizade, mas a feature de friend-gate foi adicionada depois.)
        from datetime import datetime, timezone
        cls.db.add(Friendship(
            user_id=cls.user_a_id,
            friend_id=cls.user_b_id,
            status="accepted",
            created_at=datetime.now(timezone.utc),
        ))
        cls.db.commit()

        cls.token_a = create_access_token({"sub": str(cls.user_a_id), "username": "user_a"})
        cls.token_b = create_access_token({"sub": str(cls.user_b_id), "username": "user_b"})
        # O WebSocket valida que o token tem uma sessão ativa no banco
        # (is_session_valid em dispatcher._handle_auth). Sem isto, o WS
        # rejeita com error.alert 401 "Sessão revogada ou usuário inexistente."
        # — bug introduzido quando a feature de revogação imediata foi
        # adicionada. Criamos as DbSessions correspondentes aos tokens.
        from datetime import datetime, timezone, timedelta
        for token, user_id in (
            (cls.token_a, cls.user_a_id),
            (cls.token_b, cls.user_b_id),
        ):
            cls.db.add(DbSession(
                id=uuid.uuid4(),
                user_id=user_id,
                token=token,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                created_at=datetime.now(timezone.utc),
            ))
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        if os.path.exists(TEST_MSG_DB):
            try:
                os.remove(TEST_MSG_DB)
            except OSError:
                pass

    def test_room_messaging_and_dm_ws(self):
        client = TestClient(app)
        
        # Conecta o usuário A
        with client.websocket_connect("/ws") as ws_a:
            # Autentica usuário A
            ws_a.send_json({
                "event": EventType.AUTH_AUTHENTICATE.value,
                "payload": {"token": self.token_a}
            })
            resp_a = ws_a.receive_json()
            self.assertEqual(resp_a["event"], EventType.AUTH_SUCCESS.value)
            
            # Conecta o usuário B
            with client.websocket_connect("/ws") as ws_b:
                # Autentica usuário B
                ws_b.send_json({
                    "event": EventType.AUTH_AUTHENTICATE.value,
                    "payload": {"token": self.token_b}
                })
                resp_b = ws_b.receive_json()
                self.assertEqual(resp_b["event"], EventType.AUTH_SUCCESS.value)
                
                # Consome evento de presença enviado para A (B ficou online)
                pres_a = ws_a.receive_json()
                self.assertEqual(pres_a["event"], EventType.USER_PRESENCE.value)
                self.assertEqual(pres_a["payload"]["user_id"], str(self.user_b_id))
                self.assertEqual(pres_a["payload"]["status"], "online")
                
                # 1. Testar mensagem em sala pública (#geral já é criada automaticamente em init_db())
                room = self.db.query(Room).filter(Room.name == "#geral").first()
                self.assertIsNotNone(room)
                
                # Garante que ambos são membros no banco
                member_a = self.db.query(RoomMember).filter(
                    RoomMember.room_id == room.id, RoomMember.user_id == self.user_a_id
                ).first()
                if not member_a:
                    self.db.add(RoomMember(room_id=room.id, user_id=self.user_a_id, role="member"))
                member_b = self.db.query(RoomMember).filter(
                    RoomMember.room_id == room.id, RoomMember.user_id == self.user_b_id
                ).first()
                if not member_b:
                    self.db.add(RoomMember(room_id=room.id, user_id=self.user_b_id, role="member"))
                self.db.commit()
                
                # Envia mensagem na sala geral por A
                ws_a.send_json({
                    "event": EventType.MESSAGE_SEND_ROOM.value,
                    "payload": {
                        "room_id": str(room.id),
                        "content": "Olá a todos na sala!"
                    }
                })
                
                # Verifica se A recebe o eco da própria mensagem
                msg_a = ws_a.receive_json()
                self.assertEqual(msg_a["event"], EventType.MESSAGE_RECEIVE.value)
                self.assertEqual(msg_a["payload"]["content"], "Olá a todos na sala!")
                self.assertEqual(msg_a["payload"]["sender_name"], "user_a")
                self.assertEqual(msg_a["payload"]["room_id"], str(room.id))
                
                # Verifica se B recebe a mensagem da sala
                msg_b = ws_b.receive_json()
                self.assertEqual(msg_b["event"], EventType.MESSAGE_RECEIVE.value)
                self.assertEqual(msg_b["payload"]["content"], "Olá a todos na sala!")
                self.assertEqual(msg_b["payload"]["sender_name"], "user_a")
                self.assertEqual(msg_b["payload"]["room_id"], str(room.id))
                
                # 2. Testar DM (mensagem direta/privada) de B para A
                ws_b.send_json({
                    "event": EventType.MESSAGE_SEND_PRIVATE.value,
                    "payload": {
                        "receiver_id": str(self.user_a_id),
                        "content": "Oi User A, esta é uma DM secreta!"
                    }
                })
                
                # B recebe o eco da própria DM
                dm_eco_b = ws_b.receive_json()
                self.assertEqual(dm_eco_b["event"], EventType.MESSAGE_RECEIVE.value)
                self.assertEqual(dm_eco_b["payload"]["content"], "Oi User A, esta é uma DM secreta!")
                self.assertEqual(dm_eco_b["payload"]["room_id"], None)
                self.assertEqual(dm_eco_b["payload"]["sender_name"], "user_b")
                
                # A recebe a DM
                dm_a = ws_a.receive_json()
                self.assertEqual(dm_a["event"], EventType.MESSAGE_RECEIVE.value)
                self.assertEqual(dm_a["payload"]["content"], "Oi User A, esta é uma DM secreta!")
                self.assertEqual(dm_a["payload"]["room_id"], None)
                self.assertEqual(dm_a["payload"]["sender_name"], "user_b")

if __name__ == "__main__":
    unittest.main()
