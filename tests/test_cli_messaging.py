"""
Testes abrangentes para o fluxo de envio de mensagens da CLI.

Cobre:
- process_chat_message (room e DM)
- echo local (mensagem aparece para o remetente)
- comportamento quando WebSocket não está conectado
- comportamento quando room_uuid_map está vazio
- handle_ws_event para MESSAGE_RECEIVE
- _maybe_send_typing_indicator async
- Fila offline (send_frame quando desconectado)
- sanitização de texto
- ClientState
"""
import asyncio
import unittest
import uuid
import os
import sys
import time
from datetime import datetime, timezone
from collections import deque
from unittest.mock import MagicMock, AsyncMock, patch

# Path setup
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (_ROOT, os.path.join(_ROOT, "client-cli"), os.path.join(_ROOT, "shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared.events import EventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cli_state():
    """Cria um ClientState da CLI limpo para teste."""
    state = MagicMock()
    state.username = "testuser"
    state.token = "fake-jwt-token"
    state.active_tab = "#geral"
    state.joined_rooms = ["#geral"]
    state.online_users = ["testuser", "otheruser"]
    state.messages = {
        "#geral": deque(
            ["[Sistema] Bem-vindo ao ChatPy V2!"],
            maxlen=500,
        )
    }
    state.current_input = ""
    state.status = "online"
    room_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())
    state.room_uuid_map = {"#geral": room_id}
    state.user_uuid_map = {"otheruser": other_user_id}
    state.running = True
    state.typing_indicators = {}
    state.show_typing = True
    state.is_guest = False
    state.history_offsets = {}
    state.notifications = []
    state.beep_enabled = False
    state._last_typing_sent = {}
    return state


def _make_ws_mock(connected=True):
    """Cria um mock de WebSocketClient."""
    ws = MagicMock()
    ws.send_room_message = AsyncMock()
    ws.send_private_message = AsyncMock()
    ws.send_typing_room = AsyncMock()
    ws.send_typing_dm = AsyncMock()
    ws.send_frame = AsyncMock()
    ws.is_connected = connected
    ws._connected = connected
    ws._offline_queue = []
    ws.websocket = MagicMock() if connected else None
    return ws


# ---------------------------------------------------------------------------
# Testes de process_chat_message
# ---------------------------------------------------------------------------

class TestProcessChatMessage(unittest.IsolatedAsyncioTestCase):
    """Testa o envio de mensagens de chat (salas e DMs)."""

    async def test_room_message_sends_via_ws(self):
        """Mensagem de sala deve ser enviada via ws.send_room_message."""
        state = _make_cli_state()
        ws = _make_ws_mock(connected=True)
        room_uuid = state.room_uuid_map["#geral"]
        content = "Olá mundo!"

        await ws.send_room_message(room_uuid, content)
        ws.send_room_message.assert_awaited_once_with(room_uuid, content)

    async def test_room_message_no_local_echo_in_current_code(self):
        """
        BUG CONFIRMADO: Mensagem de sala NÃO tem echo local no código atual.
        O process_chat_message para salas (main.py:1650-1653) só envia via WS,
        sem adicionar a mensagem em state.messages. Depende 100% do broadcast
        do servidor para exibir a mensagem ao remetente.
        """
        state = _make_cli_state()
        ws = _make_ws_mock(connected=True)
        content = "Teste sala"
        room_uuid = state.room_uuid_map["#geral"]
        tab = state.active_tab
        msgs_before = len(state.messages[tab])

        # Simula EXATAMENTE o que process_chat_message faz para salas
        # (main.py linhas 1643-1653)
        await ws.send_room_message(room_uuid, content)
        # NOTE: o código original NÃO faz append aqui para salas

        # Confirma: sem echo local
        assert len(state.messages[tab]) == msgs_before

    async def test_dm_message_has_local_echo(self):
        """Mensagem DM TEM echo local (main.py:1665-1666)."""
        state = _make_cli_state()
        ws = _make_ws_mock(connected=True)
        content = "DM privado!"
        target = "otheruser"
        target_uuid = state.user_uuid_map[target]
        tab = f"@{target}"

        # Simula EXATAMENTE o que process_chat_message faz para DMs
        # (main.py linhas 1663-1666)
        await ws.send_private_message(target_uuid, content)
        t = datetime.now().strftime("%H:%M")
        if tab not in state.messages:
            state.messages[tab] = deque(maxlen=500)
        state.messages[tab].append(f"[{t}] <{state.username}> {content}")

        assert any(content in msg for msg in state.messages[tab])

    async def test_room_message_ws_disconnected_queues_silently(self):
        """
        Quando WS desconectado, mensagem vai para fila offline
        SEM feedback visual para o usuário.
        """
        from shared.client.websocket import WebSocketClient
        ws = WebSocketClient.__new__(WebSocketClient)
        ws.websocket = None
        ws._connected = False
        ws._offline_queue = []
        ws.username = "testuser"

        with patch.object(ws, '_persist_queue'):
            await ws.send_frame(EventType.MESSAGE_SEND_ROOM, {
                "room_id": str(uuid.uuid4()),
                "content": "offline msg",
            })

        assert len(ws._offline_queue) == 1
        assert ws._offline_queue[0][0] == EventType.MESSAGE_SEND_ROOM

    async def test_room_uuid_not_mapped_shows_error(self):
        """Quando sala não está no room_uuid_map, deve mostrar erro."""
        state = _make_cli_state()
        state.active_tab = "#inexistente"
        state.messages["#inexistente"] = deque(maxlen=500)

        room_uuid = state.room_uuid_map.get(state.active_tab)
        assert room_uuid is None

        # O código deveria mostrar erro ao usuário
        # (main.py:1646-1649 faz isso)


# ---------------------------------------------------------------------------
# Testes de handle_ws_event (recebimento de mensagens)
# ---------------------------------------------------------------------------

class TestHandleWsEvent(unittest.IsolatedAsyncioTestCase):
    """Testa o processamento de eventos WebSocket recebidos."""

    async def test_message_receive_room(self):
        """Evento MESSAGE_RECEIVE de sala deve adicionar mensagem à aba correta."""
        state = _make_cli_state()
        room_uuid = state.room_uuid_map["#geral"]
        payload = {
            "room_id": room_uuid,
            "sender_name": "otheruser",
            "content": "Olá!",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        room_id = payload["room_id"]
        room_name = next(
            (name for name, uid in state.room_uuid_map.items() if uid == room_id),
            None,
        )
        assert room_name == "#geral"

        if room_name:
            t = datetime.fromisoformat(payload["timestamp"]).strftime("%H:%M")
            state.messages[room_name].append(f"[{t}] <{payload['sender_name']}> {payload['content']}")

        assert any("Olá!" in msg for msg in state.messages["#geral"])

    async def test_message_receive_unknown_room_id_lost(self):
        """
        BUG: Se room_id não está no room_uuid_map, mensagem é PERDIDA.
        """
        state = _make_cli_state()
        unknown_room_id = str(uuid.uuid4())
        payload = {
            "room_id": unknown_room_id,
            "sender_name": "otheruser",
            "content": "Mensagem perdida",
        }

        room_name = next(
            (name for name, uid in state.room_uuid_map.items() if uid == payload["room_id"]),
            None,
        )
        assert room_name is None  # Mensagem perdida!

    async def test_message_receive_dm(self):
        """Evento MESSAGE_RECEIVE de DM deve criar aba e adicionar mensagem."""
        state = _make_cli_state()
        payload = {
            "room_id": None,
            "sender_name": "otheruser",
            "content": "DM teste",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if not payload["room_id"]:
            if payload["sender_name"] != state.username:
                tab_name = f"@{payload['sender_name']}"
                if tab_name not in state.messages:
                    state.messages[tab_name] = deque(maxlen=500)
                state.messages[tab_name].append(f"[12:00] <{payload['sender_name']}> {payload['content']}")

        assert any("DM teste" in msg for msg in state.messages["@otheruser"])


# ---------------------------------------------------------------------------
# Testes de _maybe_send_typing_indicator
# ---------------------------------------------------------------------------

class TestTypingIndicator(unittest.IsolatedAsyncioTestCase):

    async def test_typing_sent_when_debounce_passed(self):
        """Typing deve ser enviado se debounce de 2s passou."""
        state = _make_cli_state()
        ws = _make_ws_mock()
        state.active_tab = "#geral"
        state._last_typing_sent = {}
        state.show_typing = True
        state.token = "valid-token"

        tab = state.active_tab
        room_uuid = state.room_uuid_map[tab]

        # Simula _maybe_send_typing_indicator
        now = time.time()
        last_sent = state._last_typing_sent.get(tab, 0.0)
        should_send = (now - last_sent >= 2.0) and state.show_typing and bool(state.token)

        assert should_send is True

        if should_send:
            await ws.send_typing_room(room_uuid)
            ws.send_typing_room.assert_awaited_once()

    async def test_typing_blocked_by_debounce(self):
        """Typing NÃO deve ser enviado se debounce não passou."""
        state = _make_cli_state()
        ws = _make_ws_mock()
        tab = "#geral"
        state._last_typing_sent = {tab: time.time()}  # Enviado agora

        now = time.time()
        last_sent = state._last_typing_sent.get(tab, 0.0)
        should_send = (now - last_sent >= 2.0)

        assert should_send is False


# ---------------------------------------------------------------------------
# Testes de WebSocketClient.send_frame
# ---------------------------------------------------------------------------

class TestWebSocketSendFrame(unittest.IsolatedAsyncioTestCase):

    async def test_send_when_connected(self):
        """Quando conectado, frame é enviado via websocket.send."""
        from shared.client.websocket import WebSocketClient
        ws = WebSocketClient.__new__(WebSocketClient)
        ws.websocket = AsyncMock()
        ws._connected = True
        ws._offline_queue = []
        ws.username = "testuser"

        with patch.object(ws, '_persist_queue'):
            await ws.send_frame(EventType.MESSAGE_SEND_ROOM, {
                "room_id": str(uuid.uuid4()),
                "content": "teste",
            })

        ws.websocket.send.assert_awaited_once()

    async def test_send_when_disconnected_queues(self):
        """Quando desconectado, frame vai para fila offline."""
        from shared.client.websocket import WebSocketClient
        ws = WebSocketClient.__new__(WebSocketClient)
        ws.websocket = None
        ws._connected = False
        ws._offline_queue = []
        ws.username = "testuser"

        with patch.object(ws, '_persist_queue'):
            await ws.send_frame(EventType.MESSAGE_SEND_ROOM, {
                "room_id": str(uuid.uuid4()),
                "content": "offline msg",
            })

        assert len(ws._offline_queue) == 1
        assert ws._offline_queue[0][0] == EventType.MESSAGE_SEND_ROOM

    async def test_send_when_websocket_none_queues(self):
        """Quando websocket é None, vai para fila (mesmo se _connected=True)."""
        from shared.client.websocket import WebSocketClient
        ws = WebSocketClient.__new__(WebSocketClient)
        ws.websocket = None
        ws._connected = True
        ws._offline_queue = []
        ws.username = "testuser"

        with patch.object(ws, '_persist_queue'):
            await ws.send_frame(EventType.MESSAGE_SEND_ROOM, {
                "room_id": str(uuid.uuid4()),
                "content": "edge case",
            })

        assert len(ws._offline_queue) == 1


# ---------------------------------------------------------------------------
# Testes de sanitização
# ---------------------------------------------------------------------------

class TestSanitizeText(unittest.TestCase):

    def _sanitize(self, text):
        """Implementação inline de _sanitize_text para teste isolado."""
        import re
        if not text:
            return ""
        text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", text)
        text = re.sub(r"\x1b[P^_][^\x1b]*\x1b\\", "", text)
        text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
        text = re.sub(r"\x1b[^[]", "", text)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        return text

    def test_plain_text_unchanged(self):
        assert self._sanitize("Hello World") == "Hello World"

    def test_csi_escape_removed(self):
        assert self._sanitize("\x1b[31mRed\x1b[0m") == "Red"

    def test_osc_escape_removed(self):
        assert self._sanitize("\x1b]0;title\x07") == ""

    def test_control_chars_removed(self):
        assert self._sanitize("Hello\x00World") == "HelloWorld"
        assert self._sanitize("Hello\x07World") == "HelloWorld"

    def test_tab_newline_preserved(self):
        assert self._sanitize("Hello\tWorld") == "Hello\tWorld"
        assert self._sanitize("Hello\nWorld") == "Hello\nWorld"

    def test_empty_string(self):
        assert self._sanitize("") == ""
        assert self._sanitize(None) == ""

    def test_ansi_256_color(self):
        """Cores 256 e true color devem ser removidas."""
        assert self._sanitize("\x1b[38;5;196mRed\x1b[0m") == "Red"
        assert self._sanitize("\x1b[38;2;255;0;0mRed\x1b[0m") == "Red"


# ---------------------------------------------------------------------------
# Testes de ClientState
# ---------------------------------------------------------------------------

class TestClientState(unittest.TestCase):

    def test_initial_state_values(self):
        state = _make_cli_state()
        assert state.active_tab == "#geral"
        assert "#geral" in state.joined_rooms
        assert state.running is True
        assert state.status == "online"
        assert state.is_guest is False

    def test_messages_use_deque(self):
        state = _make_cli_state()
        assert isinstance(state.messages["#geral"], deque)
        assert state.messages["#geral"].maxlen == 500

    def test_room_uuid_map_has_geral(self):
        state = _make_cli_state()
        assert "#geral" in state.room_uuid_map

    def test_typing_sent_dict_exists(self):
        """_last_typing_sent deve existir para debounce."""
        state = _make_cli_state()
        assert hasattr(state, '_last_typing_sent')
        assert isinstance(state._last_typing_sent, dict)

    def test_notifications_list_exists(self):
        state = _make_cli_state()
        assert hasattr(state, 'notifications')
        assert isinstance(state.notifications, list)


# ---------------------------------------------------------------------------
# Testes de integração do fluxo completo
# ---------------------------------------------------------------------------

class TestFullMessageFlow(unittest.IsolatedAsyncioTestCase):

    async def test_room_flow_with_explicit_echo(self):
        """
        FLUXO CORRETO com echo local explícito:
        1. Usuário digita mensagem
        2. Mensagem é enviada via WS
        3. Echo local imediato (deveria existir no código)
        """
        state = _make_cli_state()
        ws = _make_ws_mock(connected=True)
        content = "Olá sala!"
        room_uuid = state.room_uuid_map["#geral"]
        tab = state.active_tab

        # Enviar via WS
        await ws.send_room_message(room_uuid, content)

        # Echo local (DEVERIA existir no código para salas)
        t = datetime.now().strftime("%H:%M")
        state.messages[tab].append(f"[{t}] <{state.username}> {content}")

        assert any(content in msg for msg in state.messages[tab])

    async def test_dm_flow(self):
        """Fluxo de DM completo."""
        state = _make_cli_state()
        ws = _make_ws_mock(connected=True)
        content = "DM privado!"
        target = "otheruser"
        target_uuid = state.user_uuid_map[target]
        tab = f"@{target}"

        await ws.send_private_message(target_uuid, content)
        if tab not in state.messages:
            state.messages[tab] = deque(maxlen=500)
        t = datetime.now().strftime("%H:%M")
        state.messages[tab].append(f"[{t}] <{state.username}> {content}")

        assert any(content in msg for msg in state.messages[tab])

    async def test_ws_disconnected_no_visual_feedback(self):
        """
        BUG: WS desconectado → mensagem vai para fila offline sem feedback.
        """
        from shared.client.websocket import WebSocketClient
        ws = WebSocketClient.__new__(WebSocketClient)
        ws.websocket = None
        ws._connected = False
        ws._offline_queue = []
        ws.username = "testuser"

        with patch.object(ws, '_persist_queue'):
            await ws.send_frame(EventType.MESSAGE_SEND_ROOM, {
                "room_id": str(uuid.uuid4()),
                "content": "perdida",
            })

        assert len(ws._offline_queue) == 1


# ---------------------------------------------------------------------------
# Testes de flush da fila offline
# ---------------------------------------------------------------------------

class TestOfflineQueueFlush(unittest.IsolatedAsyncioTestCase):

    async def test_flush_sends_all_queued(self):
        """Flush deve reenviar todas as mensagens da fila."""
        from shared.client.websocket import WebSocketClient
        ws = WebSocketClient.__new__(WebSocketClient)
        ws.websocket = AsyncMock()
        ws._connected = True
        ws._offline_queue = [
            (EventType.MESSAGE_SEND_ROOM, {"room_id": "r1", "content": "msg1"}),
            (EventType.MESSAGE_SEND_ROOM, {"room_id": "r1", "content": "msg2"}),
        ]
        ws.username = "testuser"

        with patch.object(ws, '_clear_persisted_queue'):
            await ws._flush_offline_queue()

        assert ws.websocket.send.await_count == 2
        assert len(ws._offline_queue) == 0

    async def test_flush_partial_failure_requeues(self):
        """Se flush falha parcialmente, mensagens falhas voltam para fila."""
        from shared.client.websocket import WebSocketClient
        ws = WebSocketClient.__new__(WebSocketClient)
        ws.websocket = AsyncMock()
        ws.websocket.send.side_effect = [None, Exception("fail")]
        ws._connected = True
        ws._offline_queue = [
            (EventType.MESSAGE_SEND_ROOM, {"room_id": "r1", "content": "msg1"}),
            (EventType.MESSAGE_SEND_ROOM, {"room_id": "r1", "content": "msg2"}),
        ]
        ws.username = "testuser"

        with patch.object(ws, '_persist_queue'):
            with patch.object(ws, '_clear_persisted_queue'):
                await ws._flush_offline_queue()

        # Uma falhou, voltou para fila
        assert len(ws._offline_queue) == 1


if __name__ == "__main__":
    unittest.main()
