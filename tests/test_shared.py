import unittest
import sys
import os
from uuid import uuid4, UUID
from datetime import datetime, timezone
from pydantic import ValidationError

# Adiciona o diretório principal ao path para importar 'shared'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.events import EventType
from shared.types import (
    User, UserStatus, Room, RoomMember, RoomRole, Message, PrivateMessage, Invite, InviteStatus, Session
)
from shared.protocol import (
    WebSocketFrame, AuthAuthenticatePayload, MessageSendRoomPayload,
    MessageSendPrivatePayload, RoomJoinPayload, AuthSuccessPayload,
    MessageReceivePayload, UserPresencePayload, ErrorAlertPayload,
    parse_payload
)

class TestSharedTypes(unittest.TestCase):
    def test_user_validation(self):
        user_id = uuid4()
        now = datetime.now(timezone.utc)
        
        # Dados válidos
        user = User(
            id=user_id,
            username="testuser",
            status=UserStatus.ONLINE,
            created_at=now
        )
        self.assertEqual(user.id, user_id)
        self.assertEqual(user.username, "testuser")
        self.assertEqual(user.status, "online")

        # Dados inválidos - status incorreto
        with self.assertRaises(ValidationError):
            User(
                id=user_id,
                username="testuser",
                status="not_a_valid_status", # type: ignore
                created_at=now
            )

    def test_room_validation(self):
        room_id = uuid4()
        now = datetime.now(timezone.utc)
        
        room = Room(
            id=room_id,
            name="#geral",
            is_private=False,
            created_at=now
        )
        self.assertEqual(room.name, "#geral")
        self.assertFalse(room.is_private)

        # Dados inválidos - id não é UUID
        with self.assertRaises(ValidationError):
            Room(
                id="not-a-uuid", # type: ignore
                name="#geral",
                is_private=False,
                created_at=now
            )

    def test_room_member_validation(self):
        room_id = uuid4()
        user_id = uuid4()
        now = datetime.now(timezone.utc)
        
        member = RoomMember(
            room_id=room_id,
            user_id=user_id,
            role=RoomRole.ADMIN,
            joined_at=now
        )
        self.assertEqual(member.role, RoomRole.ADMIN)

    def test_message_and_private_message_validation(self):
        msg_id = uuid4()
        room_id = uuid4()
        sender_id = uuid4()
        receiver_id = uuid4()
        now = datetime.now(timezone.utc)
        
        # Mensagem normal
        msg = Message(
            id=msg_id,
            room_id=room_id,
            sender_id=sender_id,
            content="Hello room!",
            timestamp=now
        )
        self.assertEqual(msg.content, "Hello room!")

        # DM / Mensagem privada
        pmsg = PrivateMessage(
            id=msg_id,
            sender_id=sender_id,
            receiver_id=receiver_id,
            content="Hello secret!",
            timestamp=now
        )
        self.assertEqual(pmsg.content, "Hello secret!")

    def test_invite_validation(self):
        invite_id = uuid4()
        sender_id = uuid4()
        receiver_id = uuid4()
        now = datetime.now(timezone.utc)
        
        invite = Invite(
            id=invite_id,
            sender_id=sender_id,
            receiver_id=receiver_id,
            status=InviteStatus.PENDING,
            created_at=now
        )
        self.assertEqual(invite.status, InviteStatus.PENDING)

    def test_session_validation(self):
        session_id = uuid4()
        user_id = uuid4()
        now = datetime.now(timezone.utc)
        
        session = Session(
            id=session_id,
            user_id=user_id,
            token="secret_token_value",
            expires_at=now,
            created_at=now
        )
        self.assertEqual(session.token, "secret_token_value")


class TestSharedProtocol(unittest.TestCase):
    def test_websocket_frame_validation(self):
        # Valida frame básico
        frame_data = {
            "event": "auth.authenticate",
            "payload": {"token": "my_jwt_token"}
        }
        frame = WebSocketFrame.model_validate(frame_data)
        self.assertEqual(frame.event, EventType.AUTH_AUTHENTICATE)
        self.assertEqual(frame.payload["token"], "my_jwt_token")

        # Evento desconhecido gera erro no Enum do event
        with self.assertRaises(ValidationError):
            WebSocketFrame.model_validate({
                "event": "invalid.event.name",
                "payload": {}
            })

    def test_parse_payload_client_events(self):
        # Teste auth.authenticate
        payload = parse_payload("auth.authenticate", {"token": "token123"})
        self.assertIsInstance(payload, AuthAuthenticatePayload)
        self.assertEqual(payload.token, "token123") # type: ignore

        # Teste message.send_room
        room_uuid = str(uuid4())
        payload = parse_payload("message.send_room", {"room_id": room_uuid, "content": "Olá"})
        self.assertIsInstance(payload, MessageSendRoomPayload)
        self.assertEqual(str(payload.room_id), room_uuid) # type: ignore

        # Teste message.send_private
        receiver_uuid = str(uuid4())
        payload = parse_payload("message.send_private", {"receiver_id": receiver_uuid, "content": "Privado"})
        self.assertIsInstance(payload, MessageSendPrivatePayload)
        self.assertEqual(str(payload.receiver_id), receiver_uuid) # type: ignore

        # Teste room.join
        payload = parse_payload("room.join", {"room_name": "#geral", "password": "123"})
        self.assertIsInstance(payload, RoomJoinPayload)
        self.assertEqual(payload.room_name, "#geral") # type: ignore
        self.assertEqual(payload.password, "123") # type: ignore

    def test_parse_payload_server_events(self):
        # Teste auth.success
        user_uuid = str(uuid4())
        payload = parse_payload("auth.success", {"user_id": user_uuid, "username": "alice"})
        self.assertIsInstance(payload, AuthSuccessPayload)
        self.assertEqual(str(payload.user_id), user_uuid) # type: ignore
        self.assertEqual(payload.username, "alice") # type: ignore

        # Teste message.receive
        msg_uuid = str(uuid4())
        room_uuid = str(uuid4())
        sender_uuid = str(uuid4())
        now_str = datetime.now(timezone.utc).isoformat()
        
        payload = parse_payload("message.receive", {
            "id": msg_uuid,
            "room_id": room_uuid,
            "sender_id": sender_uuid,
            "sender_name": "bob",
            "content": "oi sala",
            "timestamp": now_str
        })
        self.assertIsInstance(payload, MessageReceivePayload)
        self.assertEqual(str(payload.id), msg_uuid) # type: ignore
        self.assertEqual(str(payload.room_id), room_uuid) # type: ignore

        # Teste user.presence
        payload = parse_payload("user.presence", {"user_id": sender_uuid, "status": "online"})
        self.assertIsInstance(payload, UserPresencePayload)
        self.assertEqual(str(payload.user_id), sender_uuid) # type: ignore

        # Teste error.alert
        payload = parse_payload("error.alert", {"code": 403, "message": "Proibido"})
        self.assertIsInstance(payload, ErrorAlertPayload)
        self.assertEqual(payload.code, 403) # type: ignore

    def test_parse_payload_errors(self):
        # Evento inválido
        with self.assertRaises(ValueError):
            parse_payload("not.a.real.event", {})

        # Payload faltando campo obrigatório
        with self.assertRaises(ValidationError):
            parse_payload("auth.authenticate", {})

        # Payload com campo de tipo incorreto
        with self.assertRaises(ValidationError):
            parse_payload("message.send_room", {"room_id": "not-a-uuid", "content": "Olá"})

if __name__ == "__main__":
    unittest.main()
