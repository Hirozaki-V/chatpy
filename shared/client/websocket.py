import json
import asyncio
import logging
from typing import Callable, Optional, Any
import websockets
from shared.events import EventType

logger = logging.getLogger(__name__)

_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 60.0
_BACKOFF_FACTOR = 2.0


class WebSocketClient:
    """
    Cliente WebSocket reutilizável para conexão com o servidor ChatPy V2.
    Inclui reconexão automática com backoff exponencial e re-autenticação
    transparente após quedas de conexão.
    """

    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.websocket: Optional[Any] = None
        self.listener_task: Optional[asyncio.Task] = None
        self.on_event_callback: Optional[Callable[[str, dict], Any]] = None
        self.on_disconnect_callback: Optional[Callable[[], Any]] = None
        self.on_reconnecting_callback: Optional[Callable[[int, float], Any]] = None
        self._reconnect: bool = True
        self._connected: bool = False
        self._auth_token: Optional[str] = None  # Para re-autenticação em reconexões
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # capturado no start_listener

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self):
        """Abre a conexão WebSocket com tentativas de reconexão."""
        attempt = 0
        delay = _BACKOFF_BASE
        self._reconnect = True

        while self._reconnect:
            try:
                logger.info("WebSocket: tentando conectar a %s (tentativa %d)…", self.ws_url, attempt + 1)
                self.websocket = await websockets.connect(self.ws_url)
                self._connected = True
                attempt = 0
                delay = _BACKOFF_BASE
                logger.info("WebSocket: conectado com sucesso.")
                return
            except (OSError, websockets.exceptions.WebSocketException) as exc:
                self._connected = False
                attempt += 1
                logger.warning("WebSocket: falha na conexão (%s). Reconectando em %.1fs…", exc, delay)
                await self._invoke(self.on_reconnecting_callback, attempt, delay)
                await asyncio.sleep(delay)
                delay = min(delay * _BACKOFF_FACTOR, _BACKOFF_MAX)

    async def disconnect(self):
        """Fecha a conexão WebSocket e para o listener."""
        self._reconnect = False
        if self.listener_task:
            self.listener_task.cancel()
            try:
                await self.listener_task
            except (asyncio.CancelledError, Exception):
                pass
            self.listener_task = None
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception:
                pass
            self.websocket = None
        self._connected = False

    async def send_frame(self, event: EventType, payload: dict):
        """Envia um frame estruturado para o WebSocket."""
        if not self.websocket:
            raise ConnectionError("WebSocket não conectado.")
        frame = {"event": event.value, "payload": payload}
        await self.websocket.send(json.dumps(frame))

    async def authenticate(self, token: str):
        """Envia o evento de autenticação. Salva o token para re-auth em reconexões."""
        self._auth_token = token
        await self.send_frame(EventType.AUTH_AUTHENTICATE, {"token": token})

    async def send_room_message(self, room_id: str, content: str, attachment_id: Optional[str] = None):
        payload = {"room_id": room_id, "content": content}
        if attachment_id is not None:
            payload["attachment_id"] = attachment_id
        await self.send_frame(EventType.MESSAGE_SEND_ROOM, payload)

    async def send_private_message(self, receiver_id: str, content: str, attachment_id: Optional[str] = None):
        payload = {"receiver_id": receiver_id, "content": content}
        if attachment_id is not None:
            payload["attachment_id"] = attachment_id
        await self.send_frame(EventType.MESSAGE_SEND_PRIVATE, payload)

    async def join_room(self, room_name: str, password: Optional[str] = None):
        await self.send_frame(EventType.ROOM_JOIN, {"room_name": room_name, "password": password})

    async def create_room(self, room_name: str, is_private: bool = False, password: Optional[str] = None):
        await self.send_frame(
            EventType.ROOM_CREATE,
            {"room_name": room_name, "is_private": is_private, "password": password},
        )

    async def start_dm(self, receiver_id: str):
        await self.send_frame(EventType.DM_START, {"receiver_id": receiver_id})

    def start_listener(
        self,
        on_event: Callable[[str, dict], Any],
        on_disconnect: Callable[[], Any],
        on_reconnecting: Optional[Callable[[int, float], Any]] = None,
    ):
        """Inicia a corrotina em background para escutar mensagens recebidas."""
        self.on_event_callback = on_event
        self.on_disconnect_callback = on_disconnect
        self.on_reconnecting_callback = on_reconnecting
        # Captura o loop atual ANTES de iniciar o listener (evita asyncio.get_event_loop() deprecated)
        self._loop = asyncio.get_running_loop()
        self.listener_task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        """Laço principal de escuta de mensagens do WebSocket."""
        loop = self._loop or asyncio.get_running_loop()

        while self._reconnect:
            try:
                while self.websocket:
                    raw_data = await self.websocket.recv()
                    try:
                        data = json.loads(raw_data)
                        event = data.get("event")
                        payload = data.get("payload", {})

                        if event and self.on_event_callback:
                            if asyncio.iscoroutinefunction(self.on_event_callback):
                                asyncio.create_task(self.on_event_callback(event, payload))
                            else:
                                loop.run_in_executor(None, self.on_event_callback, event, payload)
                    except json.JSONDecodeError:
                        logger.debug("WebSocket: frame inválido recebido, ignorando.")

            except asyncio.CancelledError:
                break

            except websockets.exceptions.ConnectionClosed as exc:
                self._connected = False
                logger.warning("WebSocket: conexão encerrada (%s).", exc)

                if not self._reconnect:
                    break

                await self._invoke(self.on_disconnect_callback)

                attempt = 0
                delay = _BACKOFF_BASE
                while self._reconnect:
                    attempt += 1
                    logger.info("WebSocket: reconectando (tentativa %d) em %.1fs…", attempt, delay)
                    await self._invoke(self.on_reconnecting_callback, attempt, delay)
                    await asyncio.sleep(delay)
                    delay = min(delay * _BACKOFF_FACTOR, _BACKOFF_MAX)
                    try:
                        self.websocket = await websockets.connect(self.ws_url)
                        self._connected = True
                        logger.info("WebSocket: reconectado com sucesso após %d tentativa(s).", attempt)

                        # Restabelece a sessão automaticamente (re-auth transparente)
                        if self._auth_token:
                            await self.authenticate(self._auth_token)
                        break
                    except (OSError, websockets.exceptions.WebSocketException) as exc2:
                        logger.warning("WebSocket: falha na tentativa %d (%s).", attempt, exc2)

        if self.on_disconnect_callback:
            await self._invoke(self.on_disconnect_callback)

    async def _invoke(self, callback: Optional[Callable], *args):
        if callback is None:
            return
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(*args)
            else:
                loop = self._loop or asyncio.get_running_loop()
                await loop.run_in_executor(None, callback, *args)
        except Exception:
            logger.exception("WebSocket: erro ao invocar callback %s.", callback)
