import asyncio
import json
import logging
import time
from typing import Dict, List, Any, Optional
from uuid import UUID

logger = logging.getLogger("chatpy.websocket.manager")


class ConnectionManager:
    """
    Gerenciador central de conexões WebSocket ativas.
    Mapeia os identificadores dos usuários aos seus respectivos sockets de conexão,
    permitindo envio de mensagens diretas e transmissões em grupo (broadcast).

    P1-FIX: agora mantém last_seen_at por user_id e expõe start_heartbeat()
    para pingar conexões periodicamente. Conexões que não respondem ao ping
    em WS_HEARTBEAT_TIMEOUT_SECONDS são consideradas zumbis e removidas —
    evita acúmulo de conexões mortas no dict active_connections quando o
    cliente cai abruptamente (queda de energia, perda de pacote sem FIN).
    """

    def __init__(self):
        # Mapeia user_id (UUID) -> objeto WebSocket da conexão correspondente
        self.active_connections: Dict[UUID, Any] = {}
        # Mapeia user_id (UUID) -> username (str)
        self.user_names: Dict[UUID, str] = {}
        # P1-FIX: timestamp da última atividade recebida por user_id —
        # atualizado a cada mensagem recebida pelo dispatcher. Heartbeat
        # usa isto para detectar conexões zumbis.
        self.last_seen_at: Dict[UUID, float] = {}
        # Task do heartbeat (iniciada por start_heartbeat)
        self._heartbeat_task: Optional[asyncio.Task] = None
        # Set de user_ids em processo de ping — evita double-ping
        self._pending_pings: set = set()
        # T3-FIX: Pub/Sub broker para escalonamento horizontal.
        # Se REDIS_URL estiver configurado, mensagens de broadcast são
        # propagadas para outros workers via Redis. Caso contrário, cai
        # no modo local (in-memory) que mantém comportamento single-worker.
        self._pubsub = None
        self._pubsub_initialized = False

    async def connect(self, user_id: UUID, username: str, websocket: Any):
        """
        Registra uma nova conexão ativa para o usuário autenticado.
        Se o usuário já estiver conectado, derruba a conexão anterior com segurança
        para evitar sockets órfãos e concorrência indesejada.
        """
        if user_id in self.active_connections:
            old_ws = self.active_connections[user_id]
            try:
                # Notifica o cliente antigo sobre a desconexão forçada antes de fechar
                disconnect_frame = {
                    "event": "error.alert",
                    "payload": {
                        "code": 409,
                        "message": "Sessão encerrada: nova conexão detectada em outro dispositivo."
                    }
                }
                if hasattr(old_ws, "send_text"):
                    await old_ws.send_text(json.dumps(disconnect_frame))
                elif hasattr(old_ws, "send_json"):
                    await old_ws.send_json(disconnect_frame)
                else:
                    await old_ws.send(json.dumps(disconnect_frame))
            except Exception:
                pass

            try:
                # Fecha o socket antigo seguindo as especificações do protocolo (Policy Violation)
                if hasattr(old_ws, "close"):
                    await old_ws.close(code=1008)
            except Exception:
                pass

        self.active_connections[user_id] = websocket
        self.user_names[user_id] = username
        self.last_seen_at[user_id] = time.time()

    async def disconnect(self, user_id: UUID):
        """
        Remove o registro da conexão de um usuário.
        """
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_names:
            del self.user_names[user_id]
        if user_id in self.last_seen_at:
            del self.last_seen_at[user_id]
        self._pending_pings.discard(user_id)

    def touch(self, user_id: UUID):
        """
        P1-FIX: marca que houve atividade recente do user_id (chamado pelo
        dispatcher a cada mensagem recebida). Heartbeat usa isto para
        distinguir conexões ativas de zumbis.
        """
        self.last_seen_at[user_id] = time.time()

    async def send_personal_message(self, message: dict, user_id: UUID):
        """
        Envia uma mensagem privada JSON para a conexão de um usuário específico, se conectada.
        """
        websocket = self.active_connections.get(user_id)
        if websocket:
            message_str = json.dumps(message)
            # Suporte a diferentes assinaturas de bibliotecas (websockets, FastAPI)
            if hasattr(websocket, "send_text"):
                await websocket.send_text(message_str)
            elif hasattr(websocket, "send_json"):
                await websocket.send_json(message)
            else:
                await websocket.send(message_str)

    async def broadcast_to_users(self, message: dict, user_ids: List[UUID]):
        """
        Envia uma mensagem JSON para múltiplos usuários conectados.
        As tarefas de envio são disparadas concorrentemente via asyncio.gather,
        evitando que clientes lentos ou travados bloqueiem os demais.
        return_exceptions=True garante que falhas individuais não interrompam o broadcast.

        T3-FIX: se o Pub/Sub broker estiver configurado (Redis), publica a
        mensagem no broker para que outros workers também entreguem aos seus
        usuários conectados. Caso contrário, entrega apenas localmente.

        IMPORTANTE: no modo local (LocalPubSubBroker), o publish entrega
        aos callbacks locais — mas o callback _on_remote_broadcast também
        tenta entregar localmente. Para evitar duplicação, o callback
        ignora mensagens publicadas por este próprio worker (flag
        _local_origin). No modo Redis, não há duplicação porque o publish
        só propaga para outros workers via Redis, e o callback só recebe
        mensagens que voltam pelo canal.
        """
        # T3-FIX: publica no broker para propagação entre workers
        await self._ensure_pubsub_initialized()
        if self._pubsub is not None:
            try:
                from server.pubsub import CHANNEL_BROADCAST, LocalPubSubBroker
                # Serializa user_ids como strings (UUID não é JSON-serializable)
                payload = {
                    "message": message,
                    "user_ids": [str(uid) for uid in user_ids],
                    # Flag para o callback saber que esta mensagem é originada
                    # localmente — no modo LocalPubSubBroker, o callback ignora
                    # para evitar dupla entrega (nós já entregamos abaixo).
                    "_local_origin": isinstance(self._pubsub, LocalPubSubBroker),
                }
                await self._pubsub.publish(CHANNEL_BROADCAST, payload)
            except Exception as e:
                logger.warning("Falha ao publicar broadcast no broker: %s — entregando apenas local", e)

        # Entrega local (sempre — o broker só propaga para OUTROS workers)
        tasks = [self.send_personal_message(message, uid) for uid in user_ids]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _ensure_pubsub_initialized(self):
        """Inicializa broker Pub/Sub na primeira chamada (lazy)."""
        if self._pubsub_initialized:
            return
        self._pubsub_initialized = True
        try:
            from server.pubsub import get_broker, CHANNEL_BROADCAST
            self._pubsub = get_broker()
            # Assina canal de broadcast para receber mensagens de outros workers
            await self._pubsub.subscribe(CHANNEL_BROADCAST, self._on_remote_broadcast)
            logger.info("ConnectionManager assinou canal de broadcast Pub/Sub")
        except Exception as e:
            logger.warning("Falha ao inicializar Pub/Sub broker: %s — modo local", e)
            self._pubsub = None

    async def _on_remote_broadcast(self, payload: dict):
        """
        Callback chamado quando outro worker publica no canal de broadcast.
        Entrega a mensagem aos usuários conectados neste worker.

        T3-FIX: ignora mensagens marcadas com _local_origin=True — estas
        foram publicadas por este próprio worker no modo LocalPubSubBroker,
        e já entregamos localmente no broadcast_to_users. Sem isto, haveria
        dupla entrega no modo local.
        """
        try:
            # T3-FIX: no modo local, ignora mensagens originadas aqui
            if payload.get("_local_origin"):
                return

            message = payload.get("message", {})
            user_ids_str = payload.get("user_ids", [])
            # Converte strings de volta para UUID
            user_ids = []
            for uid_str in user_ids_str:
                try:
                    user_ids.append(UUID(uid_str))
                except ValueError:
                    continue
            # Entrega apenas aos usuários conectados localmente
            local_tasks = [
                self.send_personal_message(message, uid)
                for uid in user_ids
                if uid in self.active_connections
            ]
            if local_tasks:
                await asyncio.gather(*local_tasks, return_exceptions=True)
        except Exception as e:
            logger.error("Erro ao processar broadcast remoto: %s", e)

    def is_user_connected(self, user_id: UUID) -> bool:
        """
        Verifica se um usuário está online no servidor.
        """
        return user_id in self.active_connections

    # -----------------------------------------------------------------------
    # P1-FIX: Heartbeat ping/pong para detectar conexões zumbis
    # -----------------------------------------------------------------------
    def start_heartbeat(self, interval_seconds: int = 30, timeout_seconds: int = 60):
        """
        Inicia task assíncrona que pinga todas as conexões ativas a cada
        `interval_seconds`. Conexões que não respondem (pong ou qualquer
        mensagem) dentro de `timeout_seconds` são consideradas zumbis e
        removidas à força.

        WebSocket protocol define ping/pong frames nativos — o cliente
        responde automaticamente sem precisar de código extra. Mas se a
        conexão TCP cair sem FIN (queda de energia, cabo desconectado),
        o send_text levanta exceção que capturamos aqui.

        Default: ping a cada 30s, timeout de 60s. Configurável via env
        WS_HEARTBEAT_INTERVAL_SECONDS e WS_HEARTBEAT_TIMEOUT_SECONDS.
        """
        if self._heartbeat_task is not None:
            return  # já está rodando

        async def _heartbeat_loop():
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
                    await self._ping_all()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Erro no heartbeat loop: %s", e)

        self._heartbeat_task = asyncio.create_task(_heartbeat_loop())
        logger.info(
            "Heartbeat WS iniciado (intervalo=%ds, timeout=%ds)",
            interval_seconds, timeout_seconds,
        )

    async def stop_heartbeat(self):
        """Para a task de heartbeat (chamado no shutdown do servidor)."""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            self._heartbeat_task = None

    async def _ping_all(self):
        """
        Envia ping para todas as conexões ativas. Conexões que falham ao
        receber ping (TCP caiu) são removidas imediatamente. Conexões que
        não respondem há mais de timeout_seconds também são removidas.

        Q5-FIX: o Starlette WebSocket NÃO expõe o método .ping() nativo
        (verificado: hasattr(ws, 'ping') sempre retorna False). Antes, o
        heartbeat dependia apenas do timeout passivo de inatividade. Agora
        enviamos um frame JSON customizado {"event": "ping"} que o cliente
        deve responder com {"event": "pong"}. Se o send_text falhar (TCP
        caiu), removemos a conexão imediatamente. Se o cliente não responder
        pong dentro do timeout, o last_seen_at não será atualizado e o
        timeout passivo remove na próxima rodada.
        """
        import os as _os
        timeout_seconds = int(_os.getenv("WS_HEARTBEAT_TIMEOUT_SECONDS", "60"))
        now = time.time()

        # Lista de user_ids para checar (cópia para não mutar durante iteração)
        user_ids = list(self.active_connections.keys())

        for user_id in user_ids:
            ws = self.active_connections.get(user_id)
            if ws is None:
                continue

            # 1. Checa timeout de inatividade — se passou do limite, remove
            last_seen = self.last_seen_at.get(user_id, 0)
            if now - last_seen > timeout_seconds:
                logger.info(
                    "Conexão zumbi detectada: user_id=%s (sem atividade há %ds)",
                    user_id, int(now - last_seen),
                )
                await self._force_disconnect(user_id)
                continue

            # 2. Q5-FIX: envia ping JSON customizado (Starlette WS não tem .ping())
            # Se o send_text falhar (TCP caiu sem FIN), a exceção é capturada
            # e a conexão é removida imediatamente.
            try:
                ping_frame = json.dumps({"event": "ping", "payload": {"ts": now}})
                if hasattr(ws, "send_text"):
                    await ws.send_text(ping_frame)
                elif hasattr(ws, "send_json"):
                    await ws.send_json({"event": "ping", "payload": {"ts": now}})
                else:
                    await ws.send(ping_frame)
            except Exception as e:
                logger.info(
                    "Conexão morta detectada no ping JSON: user_id=%s, erro=%s",
                    user_id, e,
                )
                await self._force_disconnect(user_id)

    async def _force_disconnect(self, user_id: UUID):
        """Remove conexão zumbi e marca usuário como offline."""
        ws = self.active_connections.get(user_id)
        if ws is not None:
            try:
                if hasattr(ws, "close"):
                    await ws.close(code=1011)  # Internal Error — servidor detectou problema
            except Exception:
                pass
        await self.disconnect(user_id)

        # Marca usuário como offline no banco (em thread separada para não
        # bloquear o heartbeat loop)
        try:
            def set_offline():
                from server.database.connection import get_db
                from server.database.models import User
                with get_db() as db:
                    user = db.query(User).filter(User.id == user_id).first()
                    if user:
                        user.status = "offline"
                        db.commit()

            await asyncio.to_thread(set_offline)

            # Broadcast de presença offline para os demais
            presence_frame = {
                "event": "user.presence",
                "payload": {
                    "user_id": str(user_id),
                    "status": "offline",
                },
            }
            await self.broadcast_to_users(
                presence_frame, list(self.active_connections.keys())
            )
        except Exception as e:
            logger.error("Erro ao marcar usuário offline após heartbeat: %s", e)