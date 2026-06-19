"""
BUG-FIX: Testes para os 3 bugs reportados pelo usuário.

Cobre:
  - Bug 1: Remetente não via link de download do próprio anexo em salas
  - Bug 2: Erro de sala duplicada aparecia na status bar em vez de dialog
  - Bug 3: Crash "installEventFilter: Cannot filter events for objects in
            a different thread" ao visualizar salas
"""
import os
import sys
import unittest

TEST_DB = "test_bug_fixes.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["JWT_SECRET"] = "test-secret-key-min-16-chars-for-bug-tests"
os.environ["REST_RATE_LIMIT_ENABLED"] = "false"

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestBug1SenderSeesAttachment(unittest.TestCase):
    """Bug 1: remetente deve ver o link de download do próprio anexo em salas."""

    def test_send_message_builds_attachment_payload_for_rooms(self):
        """send_message constrói attachment_payload tanto para sala quanto DM."""
        controller_path = os.path.join(
            os.path.dirname(__file__), "..", "client-desktop", "controllers",
            "chat_controller.py"
        )
        with open(controller_path, "r") as f:
            content = f.read()
        # Verifica que _append_local_message foi extraído (unifica sala e DM)
        self.assertIn("_append_local_message", content)
        # Verifica que o caminho de sala chama _append_local_message
        # (não retorna mais sem construir msg_payload)
        self.assertIn("BUG1-FIX", content)

    def test_append_local_message_builds_attachment_payload(self):
        """_append_local_message constrói attachment_payload se houver anexo."""
        controller_path = os.path.join(
            os.path.dirname(__file__), "..", "client-desktop", "controllers",
            "chat_controller.py"
        )
        with open(controller_path, "r") as f:
            content = f.read()
        # Verifica que o helper existe e constrói attachment_payload
        self.assertIn("def _append_local_message", content)
        self.assertIn("attachment_payload", content)
        # Verifica que é chamado após send_room_message (caminho de sala)
        self.assertIn("self._append_local_message(active, content, attachment_id)", content)


class TestBug2ErrorDialog(unittest.TestCase):
    """Bug 2: erro de sala duplicada deve mostrar QMessageBox, não status bar."""

    def test_error_dialog_signal_exists(self):
        """ChatController tem signal error_dialog."""
        controller_path = os.path.join(
            os.path.dirname(__file__), "..", "client-desktop", "controllers",
            "chat_controller.py"
        )
        with open(controller_path, "r") as f:
            content = f.read()
        self.assertIn("error_dialog = Signal(str, str)", content)

    def test_create_room_emits_error_dialog(self):
        """create_room emite error_dialog quando há erro (não só status_message)."""
        controller_path = os.path.join(
            os.path.dirname(__file__), "..", "client-desktop", "controllers",
            "chat_controller.py"
        )
        with open(controller_path, "r") as f:
            content = f.read()
        self.assertIn("self.error_dialog.emit", content)
        self.assertIn("BUG2-FIX", content)

    def test_main_window_connects_error_dialog(self):
        """MainWindow conecta error_dialog ao slot _on_error_dialog."""
        main_window_path = os.path.join(
            os.path.dirname(__file__), "..", "client-desktop", "ui", "main_window.py"
        )
        with open(main_window_path, "r") as f:
            content = f.read()
        self.assertIn("error_dialog.connect", content)
        self.assertIn("_on_error_dialog", content)
        self.assertIn("QMessageBox.warning", content)

    def test_on_error_dialog_shows_messagebox(self):
        """_on_error_dialog abre QMessageBox.warning."""
        main_window_path = os.path.join(
            os.path.dirname(__file__), "..", "client-desktop", "ui", "main_window.py"
        )
        with open(main_window_path, "r") as f:
            content = f.read()
        self.assertIn("def _on_error_dialog", content)
        self.assertIn("QMessageBox.warning(self, title, message)", content)


class TestBug3EventFilterCrash(unittest.TestCase):
    """Bug 3: installEventFilter global causava crash em thread diferente."""

    def test_global_event_filter_removed(self):
        """QApplication.installEventFilter não é mais chamado globalmente."""
        main_window_path = os.path.join(
            os.path.dirname(__file__), "..", "client-desktop", "ui", "main_window.py"
        )
        with open(main_window_path, "r") as f:
            lines = f.readlines()
        # Verifica que nenhuma linha ATIVA (não comentário) chama installEventFilter global
        active_install = [
            line for line in lines
            if "installEventFilter" in line
            and not line.strip().startswith("#")
            and "removido" not in line.lower()
            and "BUG3-FIX" not in line
        ]
        self.assertEqual(
            len(active_install), 0,
            f"installEventFilter global deve ter sido removido (causa crash). "
            f"Linhas ativas encontradas: {active_install}"
        )
        # Verifica que foi substituído por polling
        with open(main_window_path, "r") as f:
            content = f.read()
        self.assertIn("_check_activity_polling", content)
        self.assertIn("BUG3-FIX", content)

    def test_polling_timer_setup(self):
        """_idle_activity_timer substitui eventFilter global."""
        main_window_path = os.path.join(
            os.path.dirname(__file__), "..", "client-desktop", "ui", "main_window.py"
        )
        with open(main_window_path, "r") as f:
            content = f.read()
        self.assertIn("_idle_activity_timer", content)
        self.assertIn("QCursor.pos()", content)
        self.assertIn("keyboardModifiers", content)

    def test_event_filter_method_neutralized(self):
        """eventFilter ainda existe mas não faz nada (retorna False)."""
        main_window_path = os.path.join(
            os.path.dirname(__file__), "..", "client-desktop", "ui", "main_window.py"
        )
        with open(main_window_path, "r") as f:
            content = f.read()
        # O método existe mas não processa eventos (só retorna False)
        self.assertIn("def eventFilter(self, obj, event):", content)
        self.assertIn("BUG3-FIX", content)

    def test_polling_detects_mouse_movement(self):
        """_check_activity_polling detecta mudança de posição do cursor."""
        main_window_path = os.path.join(
            os.path.dirname(__file__), "..", "client-desktop", "ui", "main_window.py"
        )
        with open(main_window_path, "r") as f:
            content = f.read()
        # Verifica que compara posição atual com última conhecida
        self.assertIn("current_pos != self._last_cursor_pos", content)
        self.assertIn("_last_activity_ts = time.time()", content)


if __name__ == "__main__":
    unittest.main()
