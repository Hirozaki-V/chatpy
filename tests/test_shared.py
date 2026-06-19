import unittest
import sys
import os
from uuid import uuid4
from datetime import datetime, timezone
from pydantic import ValidationError

# Adiciona o diretório principal ao path para importar 'shared'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.events import EventType
from shared.protocol import (
    WebSocketFrame, AuthAuthenticatePayload, MessageSendRoomPayload,
    MessageSendPrivatePayload, RoomJoinPayload, AuthSuccessPayload,
    MessageReceivePayload, UserPresencePayload, ErrorAlertPayload,
    parse_payload
)

# P0-10: A classe TestSharedTypes foi removida — testava os modelos Pydantic
# em shared/types/, que eram código morto (nunca usados em produção, só aqui).
# O módulo foi deletado. Mantemos apenas TestSharedProtocol, que testa o
# protocolo WebSocket realmente usado.


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

    def test_allowed_attachments_module(self):
        """
        P0-2: garante que o módulo compartilhado de allowlist de anexos
        está exportando as constantes e funções esperadas.
        """
        from shared.allowed_attachments import (
            ALLOWED_MIME_TYPES,
            ALLOWED_EXTENSIONS,
            DEFAULT_MAX_FILE_SIZE,
            is_allowed_extension,
            is_allowed_mime,
            get_allowed_extensions_display,
        )
        # Sanity: tipos básicos presentes
        self.assertIn("image/png", ALLOWED_MIME_TYPES)
        self.assertIn(".pdf", ALLOWED_EXTENSIONS)
        # Helpers funcionam
        self.assertTrue(is_allowed_extension("foto.png"))
        self.assertFalse(is_allowed_extension("malware.exe"))
        self.assertTrue(is_allowed_mime("image/jpeg"))
        self.assertFalse(is_allowed_mime("application/x-msdownload"))
        self.assertIsInstance(DEFAULT_MAX_FILE_SIZE, int)
        self.assertGreater(DEFAULT_MAX_FILE_SIZE, 0)
        self.assertIsInstance(get_allowed_extensions_display(), str)


if __name__ == "__main__":
    unittest.main()
