"""
T3-FIX: Camada de Pub/Sub para escalonamento horizontal do WebSocket.

ANTES: o ConnectionManager mantinha active_connections em um dict na memória
do processo Python. Isto funcionava para single-process, mas bloqueava
escalonamento horizontal: se você rodar 2+ workers do Uvicorn
(`--workers 4`), o Usuário A conectado no Worker 1 nunca receberia mensagens
do Usuário B conectado no Worker 2 — broadcast_to_users só alcança conexões
do worker local.

AGORA: este módulo fornece uma abstração PubSubBroker que:
  - Se REDIS_URL estiver configurado, usa Redis pub/sub para propagar
    mensagens entre todos os workers
  - Caso contrário, cai no modo "local" (in-memory) que mantém o
    comportamento single-worker atual

O ConnectionManager usa o broker para publicar mensagens de broadcast.
Cada worker assina o canal e recebe as mensagens publicadas por outros
workers, entregando às conexões locais.

Configuração:
  REDIS_URL — URL do Redis (ex: redis://localhost:6379/0). Se vazio,
    usa modo local (sem escalonamento horizontal).

Uso típico:
  broker = get_broker()
  await broker.publish("chatpy.user_presence", {"user_id": ..., "status": ...})
  await broker.subscribe("chatpy.user_presence", handler_func)

Limitações:
  - send_personal_message ainda precisa saber em qual worker o destinatário
    está conectado. Solução completa exigiria tracking de user_id -> worker_id
    em Redis (futuro P3-2).
  - Por enquanto, broadcast_to_users propaga para TODOS os workers, que
    tentam entregar localmente (se o usuário está conectado aqui, entrega;
    senão, ignora). Isto é correto mas ineficiente para grandes clusters.
"""
import os
import json
import asyncio
import logging
from typing import Callable, Any, Optional

logger = logging.getLogger("chatpy.pubsub")


class LocalPubSubBroker:
    """
    Broker in-memory para single-process. Mantém o comportamento atual.

    Útil como fallback quando Redis não está configurado. Não propaga
    mensagens entre workers (mas também não quebra nada).
    """

    def __init__(self):
        self._subscribers: dict = {}  # {channel: [callback, ...]}
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, message: dict):
        """Publica mensagem no canal — entrega apenas localmente."""
        callbacks = self._subscribers.get(channel, [])
        for cb in callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(message)
                else:
                    cb(message)
            except Exception as e:
                logger.error("Erro em callback local do canal %s: %s", channel, e)

    async def subscribe(self, channel: str, callback: Callable[[dict], Any]):
        """Assina canal localmente."""
        async with self._lock:
            if channel not in self._subscribers:
                self._subscribers[channel] = []
            self._subscribers[channel].append(callback)

    async def close(self):
        """Limpa assinaturas."""
        async with self._lock:
            self._subscribers.clear()


class RedisPubSubBroker:
    """
    Broker Redis para escalonamento horizontal.

    Publica mensagens em canais Redis que todos os workers assinam.
    Cada worker entrega a mensagem às conexões WebSocket locais.
    """

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._redis = None
        self._pubsub = None
        self._subscribers: dict = {}  # {channel: [callback, ...]}
        self._listener_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._connected = False

    async def _connect(self):
        """Conecta ao Redis (lazy)."""
        if self._connected:
            return
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5.0,
                socket_keepalive=True,
                health_check_interval=30,
            )
            # Testa conexão
            await self._redis.ping()
            self._connected = True
            logger.info("Conectado ao Redis para pub/sub: %s", self.redis_url)
        except ImportError:
            logger.warning(
                "redis não instalado — pub/sub cai no modo local. "
                "Instale com: pip install redis"
            )
            raise
        except Exception as e:
            logger.error("Falha ao conectar ao Redis %s: %s", self.redis_url, e)
            raise

    async def publish(self, channel: str, message: dict):
        """Publica mensagem no canal Redis (todos os workers recebem)."""
        if not self._connected:
            await self._connect()
        try:
            await self._redis.publish(channel, json.dumps(message))
        except Exception as e:
            logger.error("Erro ao publicar no Redis canal %s: %s", channel, e)
            # Fallback: entrega localmente
            await self._local_deliver(channel, message)

    async def subscribe(self, channel: str, callback: Callable[[dict], Any]):
        """Assina canal Redis."""
        async with self._lock:
            if channel not in self._subscribers:
                self._subscribers[channel] = []
                # Primeiro assinante deste canal — registra no Redis
                if not self._connected:
                    await self._connect()
                if self._pubsub is None:
                    self._pubsub = self._redis.pubsub()
                await self._pubsub.subscribe(channel)
                # Inicia listener se ainda não rodando
                if self._listener_task is None:
                    self._listener_task = asyncio.create_task(self._listener_loop())
                logger.info("Assinando canal Redis: %s", channel)
            self._subscribers[channel].append(callback)

    async def _listener_loop(self):
        """Loop que recebe mensagens do Redis e despacha para callbacks."""
        while True:
            try:
                async for message in self._pubsub.listen():
                    if message["type"] != "message":
                        continue
                    channel = message["channel"]
                    try:
                        data = json.loads(message["data"])
                    except json.JSONDecodeError:
                        continue
                    await self._local_deliver(channel, data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Erro no listener Redis: %s — reconectando em 1s", e)
                await asyncio.sleep(1.0)

    async def _local_deliver(self, channel: str, message: dict):
        """Despacha mensagem para callbacks locais assinantes do canal."""
        callbacks = self._subscribers.get(channel, [])
        for cb in callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(message)
                else:
                    cb(message)
            except Exception as e:
                logger.error("Erro em callback Redis do canal %s: %s", channel, e)

    async def close(self):
        """Fecha conexão com Redis."""
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except (asyncio.CancelledError, Exception):
                pass
            self._listener_task = None
        if self._pubsub is not None:
            try:
                await self._pubsub.close()
            except Exception:
                pass
            self._pubsub = None
        if self._redis is not None:
            try:
                await self._redis.close()
            except Exception:
                pass
            self._redis = None
        self._connected = False
        async with self._lock:
            self._subscribers.clear()


# Singleton global
_broker: Optional[Any] = None


def get_broker() -> Any:
    """
    Retorna o broker singleton. Cria RedisPubSubBroker se REDIS_URL estiver
    configurado, senão LocalPubSubBroker.
    """
    global _broker
    if _broker is not None:
        return _broker

    redis_url = os.getenv("REDIS_URL", "").strip()
    if redis_url:
        try:
            _broker = RedisPubSubBroker(redis_url)
            logger.info("Pub/Sub broker: Redis (%s)", redis_url)
        except Exception as e:
            logger.warning(
                "Falha ao criar RedisPubSubBroker: %s — caindo para local. "
                "Escalonamento horizontal não funcionará.", e,
            )
            _broker = LocalPubSubBroker()
    else:
        _broker = LocalPubSubBroker()
        logger.info("Pub/Sub broker: local (sem Redis configurado)")

    return _broker


async def close_broker():
    """Fecha o broker (chamado no shutdown do servidor)."""
    global _broker
    if _broker is not None:
        await _broker.close()
        _broker = None


# Canais padrão
CHANNEL_USER_PRESENCE = "chatpy:user_presence"
CHANNEL_BROADCAST = "chatpy:broadcast"
CHANNEL_DM = "chatpy:dm"
