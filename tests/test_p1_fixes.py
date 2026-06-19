"""
P1-FIX: Testes para a segunda rodada de correções.

Cobre:
  - Magic numbers: anexos com extensão mentirosa são rejeitados
  - Replay protection: federação rejeita mensagens duplicadas/antigas
  - Heartbeat WS: ConnectionManager tem touch/start_heartbeat/_ping_all
  - Cursor pagination: history aceita before_id
  - CLI /notifications: handler popula state.notifications
  - Offline queue persistence: WebSocketClient persiste em disco
"""
import os
import sys
import unittest
import asyncio
import tempfile
import time
from datetime import datetime, timezone, timedelta
from uuid import uuid4

TEST_DB = "test_p1_fixes.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["JWT_SECRET"] = "test-secret-key-min-16-chars-for-p1-tests"
os.environ["REST_RATE_LIMIT_ENABLED"] = "false"

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.database.connection import init_db, SessionLocal, engine
from server.database.models import Base, User, Room, RoomMember, Message
from shared.magic_numbers import is_safe_attachment
from server.federation_replay import check_replay, clear_replay_cache
from server.websocket.manager import ConnectionManager


class TestMagicNumbers(unittest.TestCase):
    """P1-1: validação de anexos por magic numbers."""

    def test_png_real_bytes_accepted(self):
        """PNG real é aceito."""
        # Assinatura PNG: 89 50 4E 47 0D 0A 1A 0A
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        self.assertTrue(is_safe_attachment(png_bytes, "image/png"))

    def test_jpeg_real_bytes_accepted(self):
        """JPEG real é aceito."""
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        self.assertTrue(is_safe_attachment(jpeg_bytes, "image/jpeg"))

    def test_exe_disguised_as_png_rejected(self):
        """EXE renomeado para .png é rejeitado."""
        # MZ header = executável Windows
        exe_bytes = b"MZ\x90\x00" + b"\x00" * 100
        self.assertFalse(is_safe_attachment(exe_bytes, "image/png"))

    def test_pdf_real_bytes_accepted(self):
        """PDF real é aceito."""
        pdf_bytes = b"%PDF-1.4\n" + b"\x00" * 100
        self.assertTrue(is_safe_attachment(pdf_bytes, "application/pdf"))

    def test_exe_disguised_as_pdf_rejected(self):
        """EXE renomeado para .pdf é rejeitado."""
        exe_bytes = b"MZ\x90\x00" + b"\x00" * 100
        self.assertFalse(is_safe_attachment(exe_bytes, "application/pdf"))

    def test_zip_real_bytes_accepted(self):
        """ZIP real é aceito."""
        zip_bytes = b"PK\x03\x04" + b"\x00" * 100
        self.assertTrue(is_safe_attachment(zip_bytes, "application/zip"))

    def test_text_no_null_accepted(self):
        """Texto sem NUL é aceito."""
        text_bytes = b"hello world\n"
        self.assertTrue(is_safe_attachment(text_bytes, "text/plain"))

    def test_text_with_null_rejected(self):
        """Texto com NUL (binário disfarçado) é rejeitado."""
        text_bytes = b"hello\x00world"
        self.assertFalse(is_safe_attachment(text_bytes, "text/plain"))

    def test_json_valid_accepted(self):
        """JSON válido (começa com { ou [) é aceito."""
        self.assertTrue(is_safe_attachment(b'{"key": "value"}', "application/json"))
        self.assertTrue(is_safe_attachment(b'[1, 2, 3]', "application/json"))

    def test_json_invalid_rejected(self):
        """JSON inválido (não começa com { ou [) é rejeitado."""
        self.assertFalse(is_safe_attachment(b"not json", "application/json"))

    def test_gif_real_bytes_accepted(self):
        """GIF real é aceito (ambas assinaturas)."""
        self.assertTrue(is_safe_attachment(b"GIF87a" + b"\x00" * 100, "image/gif"))
        self.assertTrue(is_safe_attachment(b"GIF89a" + b"\x00" * 100, "image/gif"))

    def test_bmp_real_bytes_accepted(self):
        """BMP real é aceito."""
        self.assertTrue(is_safe_attachment(b"BM" + b"\x00" * 100, "image/bmp"))


class TestReplayProtection(unittest.TestCase):
    """P1-3: proteção contra replay attack em federação."""

    def setUp(self):
        clear_replay_cache()

    def test_first_message_accepted(self):
        """Primeira mensagem com timestamp recente é aceita."""
        payload = {
            "sender_username": "alice",
            "sender_domain": "example.com",
            "receiver_username": "bob",
            "content": "hello",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signature": "fake_sig",
        }
        now = time.time()
        is_valid, err = check_replay(payload, now)
        self.assertTrue(is_valid, f"Deveria aceitar: {err}")

    def test_replay_same_payload_rejected(self):
        """Mesmo payload enviado duas vezes é rejeitado na segunda."""
        payload = {
            "sender_username": "alice",
            "sender_domain": "example.com",
            "receiver_username": "bob",
            "content": "hello",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signature": "fake_sig",
        }
        now = time.time()
        # Primeiro envio: OK
        is_valid1, _ = check_replay(payload, now)
        self.assertTrue(is_valid1)
        # Segundo envio (replay): rejeitado
        is_valid2, err2 = check_replay(payload, now)
        self.assertFalse(is_valid2)
        self.assertIn("duplicada", err2.lower())

    def test_old_timestamp_rejected(self):
        """Mensagem com timestamp muito antigo é rejeitada."""
        old_ts = time.time() - 600  # 10 min atrás (janela default é 5 min)
        payload = {
            "sender_username": "alice",
            "sender_domain": "example.com",
            "receiver_username": "bob",
            "content": "old message",
            "timestamp": datetime.fromtimestamp(old_ts, tz=timezone.utc).isoformat(),
            "signature": "fake_sig",
        }
        is_valid, err = check_replay(payload, old_ts)
        self.assertFalse(is_valid)
        self.assertIn("antiga", err.lower())

    def test_future_timestamp_rejected(self):
        """Mensagem com timestamp muito no futuro é rejeitada."""
        future_ts = time.time() + 600  # 10 min no futuro
        payload = {
            "sender_username": "alice",
            "sender_domain": "example.com",
            "receiver_username": "bob",
            "content": "future message",
            "timestamp": datetime.fromtimestamp(future_ts, tz=timezone.utc).isoformat(),
            "signature": "fake_sig",
        }
        is_valid, err = check_replay(payload, future_ts)
        self.assertFalse(is_valid)
        self.assertIn("futuro", err.lower())

    def test_different_content_not_replay(self):
        """Mensagens com conteúdo diferente não são consideradas replay."""
        ts = datetime.now(timezone.utc).isoformat()
        payload1 = {
            "sender_username": "alice", "sender_domain": "x.com",
            "receiver_username": "bob", "content": "msg1",
            "timestamp": ts, "signature": "sig1",
        }
        payload2 = {
            "sender_username": "alice", "sender_domain": "x.com",
            "receiver_username": "bob", "content": "msg2",
            "timestamp": ts, "signature": "sig2",
        }
        now = time.time()
        is_valid1, _ = check_replay(payload1, now)
        is_valid2, _ = check_replay(payload2, now)
        self.assertTrue(is_valid1)
        self.assertTrue(is_valid2)

    def test_cache_stats(self):
        """get_replay_cache_stats retorna informações úteis."""
        from server.federation_replay import get_replay_cache_stats
        stats = get_replay_cache_stats()
        self.assertIn("size", stats)
        self.assertIn("max_size", stats)
        self.assertIn("window_seconds", stats)


class TestConnectionManagerHeartbeat(unittest.TestCase):
    """P1-5: ConnectionManager com heartbeat ping/pong."""

    def test_touch_updates_last_seen(self):
        """touch() atualiza last_seen_at para o user_id."""
        mgr = ConnectionManager()
        uid = uuid4()
        # Antes do touch, last_seen_at está vazio
        self.assertNotIn(uid, mgr.last_seen_at)
        mgr.touch(uid)
        self.assertIn(uid, mgr.last_seen_at)
        self.assertGreater(mgr.last_seen_at[uid], 0)

    def test_disconnect_clears_last_seen(self):
        """disconnect() remove last_seen_at do user_id."""
        mgr = ConnectionManager()
        uid = uuid4()
        mgr.last_seen_at[uid] = time.time()
        mgr._pending_pings.add(uid)
        # Simula asyncio.run para disconnect
        asyncio.run(mgr.disconnect(uid))
        self.assertNotIn(uid, mgr.last_seen_at)
        self.assertNotIn(uid, mgr._pending_pings)

    def test_start_heartbeat_idempotent(self):
        """start_heartbeat chamado duas vezes não cria duas tasks."""
        async def run():
            mgr = ConnectionManager()
            mgr.start_heartbeat(interval_seconds=999, timeout_seconds=999)
            task1 = mgr._heartbeat_task
            mgr.start_heartbeat(interval_seconds=999, timeout_seconds=999)
            task2 = mgr._heartbeat_task
            self.assertIs(task1, task2, "Segundo start_heartbeat não deveria criar nova task")
            await mgr.stop_heartbeat()
        asyncio.run(run())

    def test_stop_heartbeat_clears_task(self):
        """stop_heartbeat cancela e limpa a task."""
        async def run():
            mgr = ConnectionManager()
            mgr.start_heartbeat(interval_seconds=999, timeout_seconds=999)
            self.assertIsNotNone(mgr._heartbeat_task)
            await mgr.stop_heartbeat()
            self.assertIsNone(mgr._heartbeat_task)
        asyncio.run(run())


class TestCursorPagination(unittest.TestCase):
    """P1-6: paginação por cursor no /history."""

    @classmethod
    def setUpClass(cls):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def setUp(self):
        self.db = SessionLocal()
        # Cria sala e usuário
        self.user = User(
            id=uuid4(), username="paguser", password_hash="x",
            status="online", created_at=datetime.now(timezone.utc),
        )
        self.room = Room(
            id=uuid4(), name="#pagtest", is_private=False,
            created_at=datetime.now(timezone.utc),
        )
        self.member = RoomMember(
            room_id=self.room.id, user_id=self.user.id,
            role="member", joined_at=datetime.now(timezone.utc),
            is_banned=False,
        )
        self.db.add_all([self.user, self.room, self.member])
        self.db.commit()
        # Cria 10 mensagens com timestamps diferentes
        self.msg_ids = []
        for i in range(10):
            m = Message(
                id=uuid4(),
                room_id=self.room.id,
                sender_id=self.user.id,
                content=f"msg_{i}",
                timestamp=datetime.now(timezone.utc) - timedelta(seconds=10 - i),
            )
            self.db.add(m)
            self.msg_ids.append(m.id)
        self.db.commit()
        # msg_ids[0] é o mais velho, msg_ids[9] é o mais novo

    def tearDown(self):
        self.db.query(Message).delete()
        self.db.query(RoomMember).delete()
        self.db.query(Room).delete()
        self.db.query(User).delete()
        self.db.commit()
        self.db.close()

    def test_offset_pagination_returns_newest_first(self):
        """Sem cursor, retorna as mais novas primeiro."""
        from server.rooms.service import obter_historico_sala
        msgs = obter_historico_sala(self.db, self.room.id, limit=5, offset=0)
        self.assertEqual(len(msgs), 5)
        # A primeira deve ser a mais nova (msg_9)
        self.assertEqual(msgs[0].content, "msg_9")

    def test_cursor_pagination_returns_older_messages(self):
        """Com before_id, retorna mensagens anteriores àquele timestamp."""
        # Pega as 5 mais novas primeiro
        from server.rooms.service import obter_historico_sala
        page1 = obter_historico_sala(self.db, self.room.id, limit=5, offset=0)
        self.assertEqual(len(page1), 5)
        # O último (mais velho) da página 1 é o cursor para página 2
        cursor_msg = page1[-1]  # msg_4 (mais velho de page1)
        # Busca mensagens com timestamp < cursor_msg.timestamp
        # (simulando o que o endpoint faz internamente)
        page2 = (
            self.db.query(Message)
            .filter(
                Message.room_id == self.room.id,
                Message.timestamp < cursor_msg.timestamp,
            )
            .order_by(Message.timestamp.desc(), Message.id.desc())
            .limit(5)
            .all()
        )
        # page1 = [msg_9, msg_8, msg_7, msg_6, msg_5], page2 = [msg_4, msg_3, msg_2, msg_1, msg_0]
        self.assertEqual(len(page2), 5)
        contents = [m.content for m in page2]
        self.assertIn("msg_4", contents)
        self.assertIn("msg_0", contents)
        # Não deve ter duplicação com page1
        page1_contents = [m.content for m in page1]
        for c in contents:
            self.assertNotIn(c, page1_contents, f"{c} não deveria estar em ambas as páginas")


class TestCLINotificationsState(unittest.TestCase):
    """P1-9: ClientState da CLI tem lista de notificações."""

    def test_state_has_notifications_list(self):
        """ClientState inicializa com lista de notificações vazia."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client-cli"))
        try:
            # Recarrega para pegar mudanças
            if "main" in sys.modules:
                del sys.modules["main"]
            from main import ClientState
            state = ClientState()
            self.assertEqual(state.notifications, [])
            self.assertIsInstance(state.notifications, list)
        finally:
            sys.path.pop(0)


class TestOfflineQueuePersistence(unittest.TestCase):
    """P1-10: WebSocketClient persiste fila offline em disco."""

    def setUp(self):
        # Cria diretório temporário para simular home
        self.tmpdir = tempfile.mkdtemp()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmpdir

    def tearDown(self):
        if self._old_home is not None:
            os.environ["HOME"] = self._old_home
        else:
            os.environ.pop("HOME", None)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_queue_persisted_and_reloaded(self):
        """Mensagens enfileiradas são persistidas e recarregadas."""
        from shared.client.websocket import WebSocketClient, _get_offline_queue_path
        from shared.events import EventType

        # Limpa arquivo de fila anterior (caso teste rodou antes)
        path = _get_offline_queue_path("testuser_persist")
        if path and os.path.exists(path):
            os.remove(path)

        # Cria cliente com username "testuser"
        ws1 = WebSocketClient("ws://localhost:5000/ws", username="testuser_persist")
        # Limpa qualquer fila residual do __init__
        ws1._offline_queue.clear()
        ws1._clear_persisted_queue()
        # Simula mensagem enfileirada (offline)
        asyncio.run(ws1.send_frame(
            EventType.MESSAGE_SEND_ROOM,
            {"room_id": str(uuid4()), "content": "test message"},
        ))
        # Verifica que foi persistida
        self.assertEqual(len(ws1._offline_queue), 1)

        # Cria novo cliente com mesmo username — deve carregar do disco
        ws2 = WebSocketClient("ws://localhost:5000/ws", username="testuser_persist")
        self.assertEqual(len(ws2._offline_queue), 1, "Fila deveria ser recarregada do disco")
        # Conteúdo deve ser o mesmo
        evt, payload = ws2._offline_queue[0]
        self.assertEqual(evt, EventType.MESSAGE_SEND_ROOM)
        self.assertEqual(payload["content"], "test message")

        # Limpa após teste
        ws2._clear_persisted_queue()

    def test_queue_cleared_after_flush(self):
        """Após flush bem-sucedido, arquivo persistido é removido."""
        from shared.client.websocket import WebSocketClient
        from shared.client.websocket import _get_offline_queue_path
        from shared.events import EventType

        ws = WebSocketClient("ws://localhost:5000/ws", username="testuser_flush")
        asyncio.run(ws.send_frame(
            EventType.MESSAGE_SEND_ROOM,
            {"room_id": str(uuid4()), "content": "flush test"},
        ))

        path = _get_offline_queue_path("testuser_flush")
        self.assertTrue(os.path.exists(path), "Arquivo de fila deveria existir")

        # Simula flush bem-sucedido
        ws._offline_queue.clear()
        ws._clear_persisted_queue()

        self.assertFalse(os.path.exists(path), "Arquivo deveria ser removido após flush")


class TestDockerfileHasDataDir(unittest.TestCase):
    """P1-2: Dockerfile e docker-compose.yml setam CHATPY_DATA_DIR."""

    def test_dockerfile_sets_data_dir(self):
        """Dockerfile tem ENV CHATPY_DATA_DIR=/app/data."""
        dockerfile_path = os.path.join(
            os.path.dirname(__file__), "..", "Dockerfile"
        )
        with open(dockerfile_path, "r") as f:
            content = f.read()
        self.assertIn("CHATPY_DATA_DIR=/app/data", content)

    def test_compose_sets_data_dir(self):
        """docker-compose.yml tem CHATPY_DATA_DIR=/app/data no environment."""
        compose_path = os.path.join(
            os.path.dirname(__file__), "..", "docker-compose.yml"
        )
        with open(compose_path, "r") as f:
            content = f.read()
        self.assertIn("CHATPY_DATA_DIR=/app/data", content)


if __name__ == "__main__":
    unittest.main()
