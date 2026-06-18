import time
import threading
from typing import Dict, List, Optional

import logging

logger = logging.getLogger("chatpy.rate_limit")


class RateLimiter:
    """
    Controlador de Rate Limiting e detecção de Spam/Flood.
    Bloqueia e silencia temporariamente usuários que excedem a frequência permitida.

    Thread-safe (usado pelo dispatcher async + futuramente por múltiplos workers
    via Redis). Em memória por enquanto.
    """

    def __init__(
        self,
        max_messages: int = 5,
        window_seconds: float = 3.0,
        mute_duration_seconds: float = 15.0,
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
