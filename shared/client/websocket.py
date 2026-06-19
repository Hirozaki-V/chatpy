import json
import asyncio
import logging
import os
from typing import Callable, Optional, Any
import websockets
from shared.events import EventType

logger = logging.getLogger(__name__)

_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 60.0
_BACKOFF_FACTOR = 2.0

# P1-FIX: arquivo para persistir fila offline entre sessões. Se o cliente
# fechar enquanto offline, mensagens enfileiradas seriam perdidas. Agora
# persistimos em disco e recarregamos no startup.
# Caminho resolvido via paths.py (cliente importa shared que pode importar
# server.paths — mas para evitar dependência circular, usamos abordagem
# standalone aqui).
def _get_offline_queue_path(username: Optional[str]) -> Optional[str]:
    """Retorna caminho do arquivo de fila offline para o usuário."""
    if not username:
        return None
    # Tenta usar server.paths se disponível (servidor); senão usa fallback
    try:
        import sys
        # Procura server.paths no path
        for p in sys.path:
            if not p:
                continue
            candidate = os.path.join(p, "server", "paths.py")
            if os.path.exists(candidate):
                from server.paths import get_data_dir
                import re
                safe = re.sub(r"[^A-Za-z0-9_-]", "", username) or "default"
                return str(get_data_dir() / f"offline_queue_{safe}.json")
    except Exception:
        pass
    # Fallback: ~/.chatpy/ no Unix, %USERPROFILE%\.chatpy\ no Windows
    home = os.path.expanduser("~")
    chatpy_dir = os.path.join(home, ".chatpy")
    try:
        os.makedirs(chatpy_dir, exist_ok=True)
    except Exception:
        return None
    import re
    safe = re.sub(r"[^A-Za-z0-9_-]", "", username) or "default"
    return os.path.join(chatpy_dir, f"offline_queue_{safe}.json")


class WebSocketClient:
    """
    Cliente WebSocket reutilizável para conexão com o servidor ChatPy V2.
    Inclui reconexão automática com backoff exponencial e re-autenticação
    transparente após quedas de conexão.

    P1-FIX: a fila offline agora é persistida em disco. Se o cliente fechar
    enquanto offline (com mensagens enfileiradas), elas são recarregadas na
    próxima sessão. Isto aumenta significativamente a resiliência — o usuário
    pode fechar o app no meio de uma mensagem e ela será entregue quando
    reconectar.
    """

    def __init__(self, ws_url: str, username: Optional[str] = None):
        self.ws_url = ws_url
        self.username = username
        self.websocket: Optional[Any] = None
        self.listener_task: Optional[asyncio.Task] = None
        self.on_event_callback: Optional[Callable[[str, dict], Any]] = None
        self.on_disconnect_callback: Optional[Callable[[], Any]] = None
        self.on_reconnecting_callback: Optional[Callable[[int, float], Any]] = None
        self._reconnect: bool = True
        self._connected: bool = False
        self._auth_token: Optional[str] = None  # Para re-autenticação em reconexões
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # capturado no start_listener
        # #12: fila de mensagens enviadas enquanto offline — re-enviadas ao reconectar
        self._offline_queue: list = []
        # P1-FIX: carrega fila persistida do disco se houver
        self._load_persisted_queue()

    def set_username(self, username: str):
        """Define o username para persistência da fila offline (chamado após login)."""
        self.username = username
        self._load_persisted_queue()

    def _load_persisted_queue(self):
        """Carrega fila offline persistida em disco (se houver)."""
        path = _get_offline_queue_path(self.username)
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                # Converte dicts de volta para tuplas (EventType, payload)
                for item in data:
                    if isinstance(item, dict) and "event" in item and "payload" in item:
                        try:
                            evt = EventType(item["event"])
                            self._offline_queue.append((evt, item["payload"]))
                        except ValueError:
                            pass  # evento desconhecido — descarta
                if self._offline_queue:
                    logger.info(
                        "Fila offline carregada do disco: %d mensagem(ns) pendente(s)",
                        len(self._offline_queue),
                    )
        except Exception as e:
            logger.warning("Falha ao carregar fila offline persistida: %s", e)

    def _persist_queue(self):
        """Persiste fila offline atual em disco."""
        path = _get_offline_queue_path(self.username)
        if not path:
            return
        try:
            data = [
                {"event": evt.value, "payload": payload}
                for evt, payload in self._offline_queue
            ]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Falha ao persistir fila offline: %s", e)

    def _clear_persisted_queue(self):
        """Remove arquivo de fila persistida (após flush bem-sucedido)."""
        path = _get_offline_queue_path(self.username)
        if not path or not os.path.exists(path):
            return
        try:
            os.remove(path)
        except Exception:
            pass

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
        """
        Envia um frame estruturado para o WebSocket.

        #12: Se offline, enfileira a mensagem para re-envio quando reconectar.
        P1-FIX: a fila também é persistida em disco — se o cliente fechar
        enquanto offline, as mensagens são recarregadas na próxima sessão.
        """
        if not self.websocket or not self._connected:
            # #12: enfileira para envio posterior
            self._offline_queue.append((event, payload))
            # P1-FIX: persiste em disco para sobreviver a restart do cliente
            self._persist_queue()
            logger.info("Mensagem enfileirada (offline): %s (fila: %d)", event.value, len(self._offline_queue))
            return
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

    async def send_typing_room(self, room_id: str):
        """
        P1-3: Notifica que o usuário está digitando numa sala.
        O servidor retransmite para os outros membros.
        """
        await self.send_frame(EventType.USER_TYPING, {"room_id": room_id})

    async def send_typing_dm(self, receiver_id: str):
        """
        P1-3: Notifica que o usuário está digitando numa DM.
        O servidor retransmite apenas para o destinatário.
        """
        await self.send_frame(EventType.USER_TYPING, {"receiver_id": receiver_id})

    async def send_federated_message(self, receiver_username: str, content: str):
        """
        P2-1.2d: Envia DM federada para usuário em outro servidor.
        receiver_username deve ser @user@dominio.
        """
        await self.send_frame(
            EventType.MESSAGE_SEND_FEDERATED,
            {"receiver_username": receiver_username, "content": content},
        )

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

                        # Q5-FIX: responde automaticamente a ping do servidor
                        # com pong. O heartbeat do servidor envia {"event": "ping"}
                        # a cada 30s; se não respondermos, o servidor considera a
                        # conexão zumbi e a remove. Não repassamos ping/pong para
                        # o callback do cliente (são eventos internos do protocolo).
                        if event == "ping":
                            try:
                                await self.websocket.send(json.dumps({
                                    "event": "pong", "payload": {},
                                }))
                            except Exception as e:
                                logger.debug("Erro ao responder pong: %s", e)
                            continue  # não repassa para callback

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
                            # #12: re-envia mensagens que foram enfileiradas enquanto offline
                            await self._flush_offline_queue()
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

    async def _flush_offline_queue(self):
        """
        #12: Re-envia todas as mensagens que foram enfileiradas enquanto
        o cliente estava offline. Chamado após reconexão + re-auth.

        P1-FIX: se todas as mensagens são enviadas com sucesso, limpa o
        arquivo de fila persistida. Se alguma falha, re-enfileira e
        re-persiste para próxima reconexão.
        """
        if not self._offline_queue:
            # Fila vazia — garante que arquivo persistido também está limpo
            self._clear_persisted_queue()
            return
        queue = self._offline_queue.copy()
        self._offline_queue.clear()
        logger.info("Re-enviando %d mensagem(ns) da fila offline...", len(queue))
        failed = []
        for event, payload in queue:
            try:
                frame = {"event": event.value, "payload": payload}
                await self.websocket.send(json.dumps(frame))
            except Exception as e:
                logger.warning("Erro ao re-enviar mensagem da fila: %s", e)
                failed.append((event, payload))
        if failed:
            # Re-enfileira as que falharam
            self._offline_queue.extend(failed)
            self._persist_queue()
            logger.info("Fila offline parcialmente esvaziada: %d falha(s) re-enfileirada(s).", len(failed))
        else:
            # Sucesso total — limpa arquivo persistido
            self._clear_persisted_queue()
            logger.info("Fila offline esvaziada com sucesso.")
