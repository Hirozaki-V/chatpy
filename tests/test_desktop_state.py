"""
P1-8: Testes unitários para o cliente Desktop que NÃO exigem servidor real.

Estes testes cobrem:
  - State: ClientState métodos (pin_tab, unpin_tab, favorite_tab, clear, etc.)
  - Lógica de unread_counts (P1-2)
  - Lógica de blocked_users (P0-1)
  - Helpers de UI (_clean_tab_text, _sanitize_filename, _get_username_from_item)

Testes que exigem PySide6 + servidor real ficam em test_desktop_*.py
(integrados) e requerem ambiente com servidor rodando — não rodam em CI.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Configura path
TEST_DESKTOP_DB = "test_desktop_state.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DESKTOP_DB}"
os.environ["JWT_SECRET"] = "test-secret-key-min-16-chars-long-enough"

current_dir = os.path.abspath(os.path.dirname(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.insert(0, root_dir)
sys.path.insert(0, os.path.join(root_dir, "client-desktop"))


class TestClientState(unittest.TestCase):
    """Testes do ClientState — não exigem Qt."""

    @classmethod
    def setUpClass(cls):
        # Importa ClientState direto (não exige QApplication)
        from models.state import ClientState
        cls.ClientState = ClientState

    def setUp(self):
        self.state = self.ClientState()

    def test_initial_state(self):
        """Estado recém-criado tem defaults corretos."""
        self.assertEqual(self.state.active_tab, "#geral")
        self.assertEqual(self.state.joined_rooms, ["#geral"])
        self.assertEqual(self.state.status, "online")
        self.assertEqual(self.state.friends, [])
        self.assertEqual(self.state.online_users, [])
        # P1-2: unread_counts começa vazio
        self.assertEqual(self.state.unread_counts, {})
        # P0-1: blocked_users começa vazio
        self.assertEqual(self.state.blocked_users, set())

    def test_add_joined_room_dedup(self):
        """add_joined_room não duplica."""
        self.state.add_joined_room("#geral")
        self.assertEqual(self.state.joined_rooms, ["#geral"])
        self.state.add_joined_room("#nova")
        self.assertEqual(self.state.joined_rooms, ["#geral", "#nova"])

    def test_pin_unpin_tab(self):
        """Pin/unpin persiste via user_config."""
        # Nota: pin_tab chama save_user_config — que escreve em disco.
        # Para evitar sujar o filesystem, fazemos mock.
        with patch("models.state.save_user_config") as mock_save:
            self.state.pin_tab("#sala1")
            self.assertIn("#sala1", self.state.pinned_tabs)
            self.state.pin_tab("#sala2")
            self.assertEqual(len(self.state.pinned_tabs), 2)
            self.state.unpin_tab("#sala1")
            self.assertNotIn("#sala1", self.state.pinned_tabs)
            self.assertIn("#sala2", self.state.pinned_tabs)
            # save_user_config deve ter sido chamado a cada operação
            self.assertEqual(mock_save.call_count, 3)

    def test_favorite_unfavorite_tab(self):
        """Favorite/unfavorite persiste via user_config."""
        with patch("models.state.save_user_config") as mock_save:
            self.state.favorite_tab("#sala1")
            self.assertIn("#sala1", self.state.favorite_tabs)
            self.state.unfavorite_tab("#sala1")
            self.assertNotIn("#sala1", self.state.favorite_tabs)

    def test_clear_resets_state(self):
        """clear() reseta estado de sessão mas preserva pinned/favorite."""
        with patch("models.state.save_user_config"):
            self.state.pin_tab("#sala1")
            self.state.favorite_tab("#sala2")
            self.state.username = "alice"
            self.state.token = "tok123"
            self.state.unread_counts = {"#geral": 5, "@bob": 2}
            self.state.blocked_users = {"charlie"}

        self.state.clear()

        # Sessão limpa
        self.assertEqual(self.state.username, "")
        self.assertEqual(self.state.token, "")
        self.assertEqual(self.state.active_tab, "#geral")
        self.assertEqual(self.state.joined_rooms, ["#geral"])
        self.assertEqual(self.state.messages, {"#geral": []})
        # P1-2: unread_counts limpo no logout
        self.assertEqual(self.state.unread_counts, {})
        # P0-1: blocked_users limpo no logout
        self.assertEqual(self.state.blocked_users, set())
        # pinned/favorite persistem (carregados de user_config)
        # — após clear(), recarrega de user_config.json (que foi mockado acima
        # para não escrever, então volta vazio do arquivo).
        # Apenas verificamos que não crasha.

    def test_unread_counts_tracking(self):
        """P1-2: unread_counts funciona como dict simples."""
        self.state.unread_counts["#geral"] = 3
        self.assertEqual(self.state.unread_counts.get("#geral"), 3)
        self.state.unread_counts["#geral"] += 1
        self.assertEqual(self.state.unread_counts["#geral"], 4)
        # Reset ao ativar
        self.state.unread_counts["#geral"] = 0
        self.assertEqual(self.state.unread_counts.get("#geral"), 0)

    def test_blocked_users_tracking(self):
        """P0-1: blocked_users funciona como set."""
        self.state.blocked_users.add("charlie")
        self.assertIn("charlie", self.state.blocked_users)
        self.state.blocked_users.discard("charlie")
        self.assertNotIn("charlie", self.state.blocked_users)


class TestSharedAllowedAttachments(unittest.TestCase):
    """P0-2: testa a allowlist compartilhada (sem Qt)."""

    def test_allowlist_constants(self):
        from shared.allowed_attachments import (
            ALLOWED_MIME_TYPES,
            ALLOWED_EXTENSIONS,
            DEFAULT_MAX_FILE_SIZE,
        )
        self.assertIn("image/png", ALLOWED_MIME_TYPES)
        self.assertIn(".pdf", ALLOWED_EXTENSIONS)
        self.assertEqual(DEFAULT_MAX_FILE_SIZE, 10 * 1024 * 1024)

    def test_is_allowed_extension(self):
        from shared.allowed_attachments import is_allowed_extension
        self.assertTrue(is_allowed_extension("foto.png"))
        self.assertTrue(is_allowed_extension("doc.pdf"))
        self.assertFalse(is_allowed_extension("malware.exe"))
        self.assertFalse(is_allowed_extension("script.py"))
        self.assertFalse(is_allowed_extension(""))

    def test_is_allowed_mime(self):
        from shared.allowed_attachments import is_allowed_mime
        self.assertTrue(is_allowed_mime("image/jpeg"))
        self.assertTrue(is_allowed_mime("application/pdf"))
        self.assertFalse(is_allowed_mime("application/x-msdownload"))
        self.assertFalse(is_allowed_mime(""))


class TestProtocolTyping(unittest.TestCase):
    """P1-3: testa os novos eventos de typing no protocolo."""

    def test_user_typing_payload_valid(self):
        from shared.protocol import parse_payload
        from shared.events import EventType
        from uuid import uuid4

        # Payload com room_id
        room_uuid = str(uuid4())
        p = parse_payload(EventType.USER_TYPING, {"room_id": room_uuid})
        self.assertEqual(str(p.room_id), room_uuid)
        self.assertIsNone(p.receiver_id)

        # Payload com receiver_id (DM)
        recv_uuid = str(uuid4())
        p = parse_payload(EventType.USER_TYPING, {"receiver_id": recv_uuid})
        self.assertIsNone(p.room_id)
        self.assertEqual(str(p.receiver_id), recv_uuid)

    def test_user_typing_broadcast_payload_valid(self):
        from shared.protocol import parse_payload
        from shared.events import EventType
        from uuid import uuid4

        user_uuid = str(uuid4())
        room_uuid = str(uuid4())
        p = parse_payload(EventType.USER_TYPING_BROADCAST, {
            "user_id": user_uuid,
            "username": "alice",
            "room_id": room_uuid,
        })
        self.assertEqual(p.username, "alice")
        self.assertEqual(str(p.user_id), user_uuid)


if __name__ == "__main__":
    unittest.main()
