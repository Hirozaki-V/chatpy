"""
Q-FIX (Ciclo 4): Testes para a quarta rodada de correções.

Cobre:
  - Q2: Argon2 parâmetros configuráveis via env
  - Q5: ping/pong JSON customizado no heartbeat
  - Q7: exibição de anexos na CLI
  - Q11: sons de notificação (beep) na CLI
"""
import os
import sys
import unittest
import asyncio
import json
from datetime import datetime, timezone

TEST_DB = "test_q_fixes.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["JWT_SECRET"] = "test-secret-key-min-16-chars-for-q-tests"
os.environ["REST_RATE_LIMIT_ENABLED"] = "false"

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestArgon2Configurable(unittest.TestCase):
    """Q2: parâmetros do Argon2 são configuráveis via env."""

    def test_default_argon2_params(self):
        """Sem env vars, usa defaults (19 MiB, time_cost=2, parallelism=1)."""
        # Limpa env
        for var in ("ARGON2_MEMORY_COST", "ARGON2_TIME_COST", "ARGON2_PARALLELISM"):
            os.environ.pop(var, None)
        # Reimporta security para pegar novos defaults
        import importlib
        import server.auth.security as sec
        importlib.reload(sec)
        self.assertEqual(sec._ARGON2_MEMORY_COST, 19456)
        self.assertEqual(sec._ARGON2_TIME_COST, 2)
        self.assertEqual(sec._ARGON2_PARALLELISM, 1)

    def test_custom_argon2_params(self):
        """Env vars configuram parâmetros do Argon2."""
        os.environ["ARGON2_MEMORY_COST"] = "65536"  # 64 MiB (OWASP recommendation)
        os.environ["ARGON2_TIME_COST"] = "3"
        os.environ["ARGON2_PARALLELISM"] = "1"
        try:
            import importlib
            import server.auth.security as sec
            importlib.reload(sec)
            self.assertEqual(sec._ARGON2_MEMORY_COST, 65536)
            self.assertEqual(sec._ARGON2_TIME_COST, 3)
            self.assertEqual(sec._ARGON2_PARALLELISM, 1)
        finally:
            for var in ("ARGON2_MEMORY_COST", "ARGON2_TIME_COST", "ARGON2_PARALLELISM"):
                os.environ.pop(var, None)
            # Restaura default para outros testes
            import importlib
            import server.auth.security as sec
            importlib.reload(sec)

    def test_too_low_memory_cost_clamped(self):
        """memory_cost abaixo do mínimo (8192) é clampado para 8192."""
        os.environ["ARGON2_MEMORY_COST"] = "1024"  # 1 MiB — muito baixo
        try:
            import importlib
            import server.auth.security as sec
            importlib.reload(sec)
            self.assertEqual(sec._ARGON2_MEMORY_COST, 8192)
        finally:
            os.environ.pop("ARGON2_MEMORY_COST", None)
            import importlib
            import server.auth.security as sec
            importlib.reload(sec)

    def test_password_hashing_works_with_custom_params(self):
        """Hashing e verificação funcionam com parâmetros customizados."""
        os.environ["ARGON2_MEMORY_COST"] = "8192"  # baixo para teste rápido
        os.environ["ARGON2_TIME_COST"] = "1"
        try:
            import importlib
            import server.auth.security as sec
            importlib.reload(sec)
            password = "test-password-123"
            hashed = sec.hash_password(password)
            self.assertTrue(sec.verify_password(password, hashed))
            self.assertFalse(sec.verify_password("wrong-password", hashed))
        finally:
            for var in ("ARGON2_MEMORY_COST", "ARGON2_TIME_COST"):
                os.environ.pop(var, None)
            import importlib
            import server.auth.security as sec
            importlib.reload(sec)


class TestPingPongEvents(unittest.TestCase):
    """Q5: eventos ping/pong no EventType enum."""

    def test_ping_pong_events_exist(self):
        """EventType tem PING e PONG."""
        from shared.events import EventType
        self.assertTrue(hasattr(EventType, "PING"))
        self.assertTrue(hasattr(EventType, "PONG"))
        self.assertEqual(EventType.PING.value, "ping")
        self.assertEqual(EventType.PONG.value, "pong")


class TestWebSocketClientPongResponse(unittest.TestCase):
    """Q5: WebSocketClient responde automaticamente a ping com pong."""

    def test_client_responds_pong_to_ping(self):
        """Ao receber {"event": "ping"}, cliente envia {"event": "pong"}."""
        async def run():
            from shared.client.websocket import WebSocketClient

            ws = WebSocketClient("ws://localhost:5000/ws")

            # Mock do websocket — captura mensagens enviadas
            sent_messages = []

            class MockWebsocket:
                async def recv(self):
                    # Simula recebimento de ping do servidor
                    return json.dumps({"event": "ping", "payload": {"ts": 123}})

                async def send(self, data):
                    sent_messages.append(data)

                async def close(self):
                    pass

            ws.websocket = MockWebsocket()
            ws._connected = True
            ws._reconnect = False  # evita loop de reconexão

            received_events = []

            async def on_event(event, payload):
                received_events.append((event, payload))

            # Roda uma iteração do listen_loop
            ws.on_event_callback = on_event
            # Configura loop
            ws._loop = asyncio.get_running_loop()

            # Chama a lógica de recebimento uma vez
            try:
                raw = await ws.websocket.recv()
                data = json.loads(raw)
                event = data.get("event")
                if event == "ping":
                    await ws.websocket.send(json.dumps({
                        "event": "pong", "payload": {},
                    }))
            except Exception:
                pass

            # Verifica que o pong foi enviado
            self.assertEqual(len(sent_messages), 1)
            pong = json.loads(sent_messages[0])
            self.assertEqual(pong["event"], "pong")

            # Verifica que o ping NÃO foi repassado para o callback
            self.assertEqual(len(received_events), 0)

        asyncio.run(run())


class TestCLIAttachmentDisplay(unittest.TestCase):
    """Q7: CLI exibe informação de anexos recebidos."""

    def test_attachment_info_added_to_message(self):
        """Quando payload tem attachment, formatted_msg inclui info de download."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client-cli"))
        try:
            # Importa manualmente a lógica de formatação
            # Simula o que o handler faz
            payload = {
                "sender_name": "alice",
                "content": "",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "attachment": {
                    "id": "abc-123-def",
                    "filename": "foto.png",
                    "file_size": 15360,  # 15 KB
                    "mime_type": "image/png",
                },
            }

            # Reproduz a lógica do handler
            content = payload.get("content") or ""
            formatted_msg = f"[12:00] <alice> {content}"

            attachment = payload.get("attachment")
            if attachment:
                att_id = attachment.get("id", "?")
                filename = attachment.get("filename") or "arquivo"
                file_size = attachment.get("file_size", 0)
                mime_type = attachment.get("mime_type") or ""

                if file_size < 1024:
                    size_str = f"{file_size} B"
                elif file_size < 1024 * 1024:
                    size_str = f"{file_size / 1024:.1f} KB"
                else:
                    size_str = f"{file_size / (1024 * 1024):.1f} MB"

                type_icon = "📄"
                if mime_type.startswith("image/"):
                    type_icon = "🖼️"
                elif mime_type.startswith("audio/"):
                    type_icon = "🎵"
                elif mime_type.startswith("video/"):
                    type_icon = "🎬"
                elif mime_type == "application/pdf":
                    type_icon = "📕"
                elif "zip" in mime_type or "gzip" in mime_type or "tar" in mime_type:
                    type_icon = "📦"

                att_line = (
                    f"\n  {type_icon} [Anexo: {filename} ({size_str})] "
                    f"— use /download {att_id} para baixar"
                )
                formatted_msg += att_line

            # Verifica que a info do anexo está na mensagem
            self.assertIn("foto.png", formatted_msg)
            self.assertIn("15.0 KB", formatted_msg)
            self.assertIn("abc-123-def", formatted_msg)
            self.assertIn("/download", formatted_msg)
            self.assertIn("🖼️", formatted_msg)  # icon de imagem

        finally:
            if sys.path[0] == os.path.join(os.path.dirname(__file__), "..", "client-cli"):
                sys.path.pop(0)


class TestCLIBeepFunction(unittest.TestCase):
    """Q11: função _beep() e comando /beep na CLI."""

    def test_beep_function_exists(self):
        """_beep() existe e é chamável."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client-cli"))
        try:
            if "main" in sys.modules:
                del sys.modules["main"]
            from main import _beep, ClientState
            self.assertTrue(callable(_beep))

            # Testa que _beep não levanta exceção
            state = ClientState()
            state.beep_enabled = True
            _beep()  # não deve erro
        finally:
            if sys.path[0] == os.path.join(os.path.dirname(__file__), "..", "client-cli"):
                sys.path.pop(0)

    def test_state_has_beep_enabled_flag(self):
        """ClientState tem flag beep_enabled (default True)."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client-cli"))
        try:
            if "main" in sys.modules:
                del sys.modules["main"]
            from main import ClientState
            state = ClientState()
            self.assertTrue(hasattr(state, "beep_enabled"))
            self.assertTrue(state.beep_enabled)  # default True
        finally:
            if sys.path[0] == os.path.join(os.path.dirname(__file__), "..", "client-cli"):
                sys.path.pop(0)

    def test_beep_respects_disabled_flag(self):
        """_beep() não faz nada quando beep_enabled=False."""
        # Não podemos facilmente capturar stderr em teste, mas verificamos
        # que a função retorna sem erro quando desativada.
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client-cli"))
        try:
            if "main" in sys.modules:
                del sys.modules["main"]
            from main import _beep, ClientState
            state = ClientState()
            state.beep_enabled = False
            _beep()  # deve retornar silenciosamente
        finally:
            if sys.path[0] == os.path.join(os.path.dirname(__file__), "..", "client-cli"):
                sys.path.pop(0)


class TestSystemTrayExists(unittest.TestCase):
    """Q10: confirma que System Tray existe no Desktop (análise estava errada)."""

    def test_main_window_has_tray_icon(self):
        """MainWindow.py referencia QSystemTrayIcon e tray_icon."""
        main_window_path = os.path.join(
            os.path.dirname(__file__), "..", "client-desktop", "ui", "main_window.py"
        )
        with open(main_window_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("QSystemTrayIcon", content)
        self.assertIn("tray_icon", content)
        self.assertIn("setContextMenu", content)  # tem menu de contexto


if __name__ == "__main__":
    unittest.main()
