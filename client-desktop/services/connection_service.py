import asyncio
import threading
import logging
from typing import Optional, Any
from PySide6.QtCore import QObject, Signal

from shared.client.api import ApiClient
from shared.client.websocket import WebSocketClient
from shared.events import EventType

logger = logging.getLogger(__name__)


class ConnectionSignals(QObject):
    connected = Signal()
    disconnected = Signal()
    authenticated = Signal(bool, str)
    event_received = Signal(str, dict)
    reconnecting = Signal()


class ConnectionService:
    """
    Camada de comunicação: mantém um event loop asyncio dedicado em thread daemon
    e marshalling thread-safe para os signals Qt na Main Thread.
    """

    def __init__(self, api_url: str, ws_url: str):
        self.api_url = api_url
        self.ws_url = ws_url
        self.api = ApiClient(api_url)
        self.ws = WebSocketClient(ws_url)
        self.signals = ConnectionSignals()

        self.token: Optional[str] = None
        self.username: Optional[str] = None

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.loop_thread: Optional[threading.Thread] = None
        self._loop_ready = threading.Event()  # substitui o busy-wait `while self.loop is None: sleep(0.01)`
        self._start_event_loop()

        self.is_connected = False
        self.should_reconnect = True

    def _start_event_loop(self):
        def run_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self._loop_ready.set()  # sinaliza para a thread principal que o loop está pronto
            try:
                self.loop.run_forever()
            finally:
                try:
                    pending = asyncio.all_tasks(self.loop)
                    for task in pending:
                        task.cancel()
                except Exception:
                    pass

        self.loop_thread = threading.Thread(target=run_loop, daemon=True)
        self.loop_thread.start()
        # Espera até o loop estar pronto (com timeout de segurança)
        if not self._loop_ready.wait(timeout=5.0):
            raise RuntimeError("Falha ao iniciar o event loop asyncio em thread dedicada.")

    def run_coroutine(self, coro) -> Any:
        """Roda coroutine e bloqueia até terminar (retorna o resultado)."""
        if self.loop is None or not self.loop.is_running():
            raise RuntimeError("Event loop não está rodando.")
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=30.0)  # timeout de segurança

    def run_coroutine_async(self, coro):
        """Roda coroutine sem bloquear (fire-and-forget)."""
        if self.loop is None or not self.loop.is_running():
            logger.warning("Tentativa de rodar coroutine com loop parado.")
            return
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def connect(self, token: str, username: str):
        self.token = token
        self.username = username
        # SECURITY (auditoria-2026-06): persiste a fila offline do usuário
        # ANTERIOR antes de setar o novo username. Antes, set_username
        # imediatamente carregava a fila do NOVO user — se a fila do user
        # anterior não tivesse sido persistida (ex: crash, kill -9), as
        # mensagens pendentes do user A podiam ser entregues ao user B
        # na mesma máquina (cybercafé, biblioteca). Agora garantimos
        # _persist_queue() antes de trocar de username.
        try:
            self.ws._persist_queue()
        except Exception as e:
            logger.warning(f"Erro ao persistir fila offline antes de trocar user: {e}")
        # P1-FIX: seta o username no WebSocketClient para que a fila offline
        # seja carregada do arquivo correto e persistida para este usuário.
        self.ws.set_username(username)
        self.should_reconnect = True
        self.run_coroutine_async(self._connect_and_auth())

    async def _connect_and_auth(self):
        try:
            logger.info("Tentando conectar ao WebSocket...")
            await self.ws.connect()
            self.is_connected = True
            self.signals.connected.emit()

            await self.ws.authenticate(self.token)

            self.ws.start_listener(
                on_event=self._on_ws_event,
                on_disconnect=self._on_ws_disconnect,
                on_reconnecting=self._on_ws_reconnecting,
            )
        except Exception as e:
            logger.error(f"Erro ao conectar/autenticar: {e}")
            self._on_ws_disconnect()

    def disconnect(self):
        """
        P0-FIX: agora espera o WS fechar de verdade (síncrono) em vez de
        fire-and-forget. Antes, run_coroutine_async(self._disconnect_internal())
        retornava imediatamente, e se o usuário fizesse login novamente em
        seguida, o WS antigo ainda podia estar tentando fechar enquanto o
        novo abria — causava confusão no _auth_token compartilhado.
        """
        self.should_reconnect = False
        self.token = None
        self.username = None
        try:
            # Tenta esperar o disconnect completar (timeout 5s — se falhar,
            # segue em frente para não travar a UI)
            self.run_coroutine(self._disconnect_internal())
        except Exception as e:
            logger.warning(f"Falha ao aguardar disconnect do WS: {e}")
            # Fallback: fire-and-forget — melhor que travar
            try:
                self.run_coroutine_async(self._disconnect_internal())
            except Exception:
                pass

    async def _disconnect_internal(self):
        await self.ws.disconnect()
        self.is_connected = False
        self.signals.disconnected.emit()

    def _on_ws_event(self, event: str, payload: dict):
        logger.debug(f"Evento recebido: {event} -> {payload}")
        if event == EventType.AUTH_SUCCESS.value:
            self.signals.authenticated.emit(True, "Autenticação bem-sucedida.")
        elif event == EventType.ERROR_ALERT.value:
            code = payload.get("code")
            msg = payload.get("message", "")
            # Código 401/1008 — sessão revogada ou token inválido
            if code in (401, 1008, 4001):
                self.signals.authenticated.emit(False, msg)
            self.signals.event_received.emit(event, payload)
        else:
            self.signals.event_received.emit(event, payload)

    def _on_ws_reconnecting(self, attempt: int, delay: float):
        """Dispara sinal para a UI mostrar que está tentando reconectar."""
        self.signals.reconnecting.emit()

    def _on_ws_disconnect(self):
        """Notifica UI da perda momentânea de conexão."""
        if self.is_connected:
            self.is_connected = False
            self.signals.disconnected.emit()

    def send_room_message(self, room_id: str, content: str, attachment_id: Optional[str] = None):
        self.run_coroutine_async(self.ws.send_room_message(room_id, content, attachment_id))

    def send_private_message(self, receiver_id: str, content: str, attachment_id: Optional[str] = None):
        self.run_coroutine_async(self.ws.send_private_message(receiver_id, content, attachment_id))

    def join_room(self, room_name: str, password: Optional[str] = None):
        self.run_coroutine_async(self.ws.join_room(room_name, password))

    def create_room_ws(self, room_name: str, is_private: bool = False, password: Optional[str] = None):
        """Cria sala via WebSocket (evento room.create)."""
        self.run_coroutine_async(self.ws.create_room(room_name, is_private, password))

    def start_dm(self, receiver_id: str):
        """Inicia DM via WebSocket (valida amizade no servidor)."""
        self.run_coroutine_async(self.ws.start_dm(receiver_id))

    def logout(self):
        """Revoga a sessão no servidor REST e desconecta WS."""
        # P1-FIX: persiste fila offline antes de desconectar (caso haja
        # mensagens enfileiradas que precisam sobreviver ao fechamento)
        try:
            self.ws._persist_queue()
        except Exception as e:
            logger.warning(f"Erro ao persistir fila offline: {e}")
        if self.token:
            try:
                self.api.logout(self.token)
            except Exception as e:
                logger.warning(f"Erro ao fazer logout no servidor: {e}")
        self.disconnect()
