import time
import threading
import os
from typing import Dict, List, Optional

import logging

logger = logging.getLogger("chatpy.rate_limit")


# ---------------------------------------------------------------------------
# P0-9: Rate limit configurável via env vars.
# Defaults mais permissivos que antes (5msg/3s era agressivo demais — usuário
# legítimo digitando rápido era mutado). Agora: 10 msg em 5s, mute de 30s.
# Operador pode ajustar via env sem mexer no código.
# ---------------------------------------------------------------------------
_DEFAULT_MAX_MESSAGES = int(os.getenv("RATE_LIMIT_MAX_MESSAGES", "10"))
_DEFAULT_WINDOW_SECONDS = float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "5.0"))
_DEFAULT_MUTE_DURATION = float(os.getenv("RATE_LIMIT_MUTE_DURATION", "30.0"))


class RateLimiter:
    """
    Controlador de Rate Limiting e detecção de Spam/Flood.
    Bloqueia e silencia temporariamente usuários que excedem a frequência permitida.

    Thread-safe (usado pelo dispatcher async + futuramente por múltiplos workers
    via Redis). Em memória por enquanto.

    P0-9: limites configuráveis via env vars (RATE_LIMIT_MAX_MESSAGES,
    RATE_LIMIT_WINDOW_SECONDS, RATE_LIMIT_MUTE_DURATION).
    """

    def __init__(
        self,
        max_messages: int = _DEFAULT_MAX_MESSAGES,
        window_seconds: float = _DEFAULT_WINDOW_SECONDS,
        mute_duration_seconds: float = _DEFAULT_MUTE_DURATION,
    ):
        self.max_messages = max_messages
        self.window_seconds = window_seconds
        self.mute_duration_seconds = mute_duration_seconds

        self.user_message_timestamps: Dict[str, List[float]] = {}
        self.user_mute_until: Dict[str, float] = {}
        self._lock = threading.Lock()

    def is_muted(self, username: str) -> bool:
        """Verifica se o usuário está mutado por flood neste momento."""
        now = time.time()
        with self._lock:
            mute_until = self.user_mute_until.get(username, 0.0)
            return now < mute_until

    def get_remaining_mute_time(self, username: str) -> int:
        """Retorna a quantidade de segundos restantes de silêncio."""
        now = time.time()
        with self._lock:
            mute_until = self.user_mute_until.get(username, 0.0)
            return max(0, int(mute_until - now))

    def record_message_and_check_flood(self, username: str) -> bool:
        """
        Registra uma nova tentativa de envio e avalia se o usuário excedeu o limite.
        Retorna True caso o usuário esteja mutado (ou tenha sido mutado agora).
        """
        now = time.time()
        with self._lock:
            # Se já estiver sob punição, descarta diretamente
            mute_until = self.user_mute_until.get(username, 0.0)
            if now < mute_until:
                return True

            # Mantém apenas os registros dentro da janela de tempo
            timestamps = self.user_message_timestamps.get(username, [])
            timestamps = [ts for ts in timestamps if now - ts < self.window_seconds]
            timestamps.append(now)
            self.user_message_timestamps[username] = timestamps

            # Se ultrapassou o limite de requisições, muta o usuário
            if len(timestamps) > self.max_messages:
                self.user_mute_until[username] = now + self.mute_duration_seconds
                logger.info(
                    "Usuário '%s' mutado por flood (%d mensagens em %.1fs).",
                    username,
                    len(timestamps),
                    self.window_seconds,
                )
                return True

            # Periodic cleanup: a cada 100 mensagens, limpa entradas expiradas
            # para evitar vazamento de memória em servidores de longa duração
            self._cleanup_count = getattr(self, "_cleanup_count", 0) + 1
            if self._cleanup_count >= 100:
                self._cleanup_count = 0
                cutoff = now - self.mute_duration_seconds * 2
                expired_users = [
                    u for u, ts_list in self.user_message_timestamps.items()
                    if not ts_list or max(ts_list) < cutoff
                ]
                for u in expired_users:
                    del self.user_message_timestamps[u]
                expired_mutes = [
                    u for u, mute_ts in self.user_mute_until.items()
                    if mute_ts < now
                ]
                for u in expired_mutes:
                    del self.user_mute_until[u]

            return False

    def clear(self, username: Optional[str] = None):
        """Limpa o estado de rate limiting de um usuário (ou todos)."""
        with self._lock:
            if username is None:
                self.user_message_timestamps.clear()
                self.user_mute_until.clear()
            else:
                self.user_message_timestamps.pop(username, None)
                self.user_mute_until.pop(username, None)


# ---------------------------------------------------------------------------
# P0-FIX: Rate limit de conexões WS NÃO-AUTENTICADAS por IP.
#
# Antes, um atacante podia abrir milhares de conexões WS por segundo e
# esperar o timeout de 30s do dispatcher (que pede autenticação após o
# accept) sem enviar nada. Cada conexão consome um socket + uma task
# asyncio; sem limite, isto é DoS trivial.
#
# Este guard mantém um contador por IP de conexões PENDENTES de auth.
# Acima do limite, a conexão é recusada com 1008 antes mesmo de accept.
# ---------------------------------------------------------------------------
import asyncio
from collections import defaultdict


class UnauthConnectionGuard:
    """
    Limita conexões WS não-autenticadas por IP.

    Funcionamento:
      - try_acquire(ip): chamado ANTES do accept no endpoint WS.
        Retorna True se o IP ainda tem slot, False se excedeu.
      - release(ip): chamado APÓS auth success OU desconexão.
        Decrementa o contador para liberar o slot.

    Limite configurável via env WS_MAX_UNAUTH_PER_IP (default 10).
    Limite global de conexões não-autenticadas: WS_MAX_UNAUTH_GLOBAL
    (default 1000) — protege contra botnets que usam muitos IPs.
    """

    def __init__(
        self,
        max_per_ip: int = None,
        max_global: int = None,
    ):
        import os
        self.max_per_ip = max_per_ip or int(os.getenv("WS_MAX_UNAUTH_PER_IP", "10"))
        self.max_global = max_global or int(os.getenv("WS_MAX_UNAUTH_GLOBAL", "1000"))
        self._per_ip: dict = defaultdict(int)
        self._global: int = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self, ip: str) -> bool:
        """Tenta reservar um slot de conexão não-autenticada. Retorna False se excedeu."""
        async with self._lock:
            if self._global >= self.max_global:
                return False
            if self._per_ip[ip] >= self.max_per_ip:
                return False
            self._per_ip[ip] += 1
            self._global += 1
            return True

    async def release(self, ip: str):
        """Libera um slot (após auth success ou disconnect)."""
        async with self._lock:
            if self._per_ip[ip] > 0:
                self._per_ip[ip] -= 1
                if self._per_ip[ip] == 0:
                    del self._per_ip[ip]
            if self._global > 0:
                self._global -= 1

    async def get_stats(self) -> dict:
        """Retorna estatísticas para monitoramento."""
        async with self._lock:
            return {
                "max_per_ip": self.max_per_ip,
                "max_global": self.max_global,
                "current_global": self._global,
                "current_ips": len(self._per_ip),
            }


# ---------------------------------------------------------------------------
# SECURITY (auditoria-2026-06): Rate limit de MENSAGENS WS por IP.
#
# Antes, o RateLimiter só contava por username. Cada guest recebe username
# único, então cada guest tinha seu próprio contador. Atacante criando 10
# guests/IP/min tinha 10 contadores separados = 10x a quota de mensagens.
# Com 10 IPs de proxy rotativo, 100x. Sem limite por IP, DoS trivial.
#
# Esta classe é complementar ao RateLimiter por username: ela muta o IP
# inteiro se o agregado de todos os usernames daquele IP exceder o limite.
# ---------------------------------------------------------------------------

class IpRateLimiter:
    """
    Rate limiter de mensagens por IP (complementar ao por-username).

    Funcionamento similar ao RateLimiter mas usando IP como chave. Mútua
    independente — mesmo se o user mudar de username (criar novo guest),
    o IP continua mutado.
    """

    def __init__(
        self,
        max_messages: int = None,
        window_seconds: float = 60.0,
        mute_duration_seconds: float = 120.0,
    ):
        self.max_messages = max_messages or int(os.getenv("WS_RATE_LIMIT_MAX_PER_IP", "100"))
        self.window_seconds = window_seconds
        self.mute_duration_seconds = mute_duration_seconds
        self._ip_timestamps: Dict[str, List[float]] = {}
        self._ip_mute_until: Dict[str, float] = {}
        self._lock = threading.Lock()

    def is_muted(self, ip: str) -> bool:
        now = time.time()
        with self._lock:
            return now < self._ip_mute_until.get(ip, 0.0)

    def record_and_check(self, ip: str) -> bool:
        """Retorna True se o IP deve ser mutado."""
        now = time.time()
        with self._lock:
            if now < self._ip_mute_until.get(ip, 0.0):
                return True
            timestamps = [ts for ts in self._ip_timestamps.get(ip, []) if now - ts < self.window_seconds]
            timestamps.append(now)
            self._ip_timestamps[ip] = timestamps
            if len(timestamps) > self.max_messages:
                self._ip_mute_until[ip] = now + self.mute_duration_seconds
                logger.warning(
                    "IP '%s' mutado por flood WS (%d mensagens em %.1fs).",
                    ip, len(timestamps), self.window_seconds,
                )
                return True

            # Periodic cleanup: a cada 100 checks, limpa entradas expiradas
            self._cleanup_count = getattr(self, "_cleanup_count", 0) + 1
            if self._cleanup_count >= 100:
                self._cleanup_count = 0
                cutoff = now - self.mute_duration_seconds * 2
                expired_ips = [
                    i for i, ts_list in self._ip_timestamps.items()
                    if not ts_list or max(ts_list) < cutoff
                ]
                for i in expired_ips:
                    del self._ip_timestamps[i]
                expired_mutes = [
                    i for i, mute_ts in self._ip_mute_until.items()
                    if mute_ts < now
                ]
                for i in expired_mutes:
                    del self._ip_mute_until[i]

            return False

    def clear(self, ip: Optional[str] = None):
        with self._lock:
            if ip is None:
                self._ip_timestamps.clear()
                self._ip_mute_until.clear()
            else:
                self._ip_timestamps.pop(ip, None)
                self._ip_mute_until.pop(ip, None)


# ---------------------------------------------------------------------------
# SECURITY (auditoria-2026-06): Limite de conexões WS AUTENTICADAS por IP.
#
# Antes, só havia UnauthConnectionGuard (para pendentes de auth). Uma vez
# autenticado, o slot era liberado e não havia limite — atacante podia
# criar 10 guests/IP/min = 600 conexões autenticadas após 1h. Cada conexão
# consome socket FD + memória. Com 10 IPs, 6000 conexões = ~300MB RAM só
# em sockets. Esta classe aplica o mesmo padrão do UnauthConnectionGuard
# mas para conexões JÁ autenticadas.
# ---------------------------------------------------------------------------

class AuthenticatedConnectionGuard:
    """
    Limita conexões WS autenticadas por IP e globalmente.

    Funcionamento:
      - try_acquire(ip): chamado APÓS auth success no endpoint WS.
        Retorna True se o IP ainda tem slot, False se excedeu.
      - release(ip): chamado APÓS disconnect.

    Limite configurável via env WS_MAX_AUTH_PER_IP (default 50) e
    WS_MAX_AUTH_GLOBAL (default 5000).
    """

    def __init__(
        self,
        max_per_ip: int = None,
        max_global: int = None,
    ):
        self.max_per_ip = max_per_ip or int(os.getenv("WS_MAX_AUTH_PER_IP", "50"))
        self.max_global = max_global or int(os.getenv("WS_MAX_AUTH_GLOBAL", "5000"))
        self._per_ip: dict = defaultdict(int)
        self._global: int = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self, ip: str) -> bool:
        async with self._lock:
            if self._global >= self.max_global:
                return False
            if self._per_ip[ip] >= self.max_per_ip:
                return False
            self._per_ip[ip] += 1
            self._global += 1
            return True

    async def release(self, ip: str):
        async with self._lock:
            if self._per_ip[ip] > 0:
                self._per_ip[ip] -= 1
                if self._per_ip[ip] == 0:
                    del self._per_ip[ip]
            if self._global > 0:
                self._global -= 1

    async def get_stats(self) -> dict:
        async with self._lock:
            return {
                "max_per_ip": self.max_per_ip,
                "max_global": self.max_global,
                "current_global": self._global,
                "current_ips": len(self._per_ip),
            }
