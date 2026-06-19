"""
P1-FIX: Proteção contra Replay Attack em federação.

ANTES: o endpoint /api/federation/dm validava a assinatura Ed25519 da
mensagem, mas NÃO checava o timestamp nem se a mensagem já tinha sido
processada. Um atacante de rede (man-in-the-middle) poderia capturar o
payload JSON assinado e reenviá-lo repetidas vezes — todas as cópias
passavam a validação de assinatura e eram entregues ao destinatário.

AGORA: mantemos um cache em memória (com TTL) das mensagens federadas
recentemente processadas, identificadas pelo hash do payload assinado.
Também validamos que o timestamp não é muito antigo (default 5 min) nem
no futuro (default 5 min de skew tolerado para diferenças de relógio).

Para produção multi-processo (uvicorn --workers N), este cache é por
processo — uma mensagem reenviada pode passar em outro worker. Para
mitigação completa, migrar para Redis compartilhado entre workers
(futuro P3). Para single-process (default), este cache é suficiente.
"""
import hashlib
import logging
import time
import threading
from collections import OrderedDict
from typing import Optional, Tuple

logger = logging.getLogger("chatpy.federation.replay")

# Configuração via env
import os
_REPLAY_WINDOW_SECONDS = int(os.getenv("FEDERATION_REPLAY_WINDOW_SECONDS", "300"))  # 5 min
_REPLAY_FUTURE_SKEW_SECONDS = int(os.getenv("FEDERATION_FUTURE_SKEW_SECONDS", "300"))  # 5 min
_REPLAY_CACHE_SIZE = int(os.getenv("FEDERATION_REPLAY_CACHE_SIZE", "10000"))  # max 10k msgs


class ReplayCache:
    """
    Cache LRU em memória de hashes de mensagens federadas já processadas.

    Thread-safe (usado por múltiplas threads do Uvicorn).
    Para multi-processo / multi-servidor, migrar para Redis no futuro.
    """

    def __init__(self, max_size: int = _REPLAY_CACHE_SIZE):
        self._cache: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size

    def _make_key(self, signed_payload: dict) -> str:
        """Hash SHA256 do payload assinado (sem signature/signer_domain)."""
        import json
        # Reconstrói o payload como foi assinado (sem campos adicionados)
        clean = {k: v for k, v in signed_payload.items()
                 if k not in ("signature", "signer_domain")}
        payload_str = json.dumps(clean, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

    def check_and_mark(
        self,
        signed_payload: dict,
        timestamp: float,
        now: Optional[float] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Verifica se o payload é um replay. Se não for, marca como processado.

        Args:
            signed_payload: dict do payload federado (incluindo signature opcional)
            timestamp: unix timestamp da mensagem (segundos desde epoch)
            now: timestamp atual para teste (default: time.time())

        Returns:
            (is_valid, error_message). is_valid=False se for replay ou
            timestamp fora da janela. error_message descreve o motivo.
        """
        if now is None:
            now = time.time()

        # 1. Verifica janela de timestamp
        age = now - timestamp
        if age > _REPLAY_WINDOW_SECONDS:
            return False, (
                f"Mensagem federada muito antiga ({int(age)}s > "
                f"{_REPLAY_WINDOW_SECONDS}s de janela) — possível replay attack."
            )
        if age < -_REPLAY_FUTURE_SKEW_SECONDS:
            return False, (
                f"Timestamp da mensagem federada está no futuro "
                f"({int(-age)}s à frente) — possível relógio descalibrado "
                f"ou tentativa de bypass."
            )

        # 2. Verifica cache de replay
        key = self._make_key(signed_payload)
        with self._lock:
            if key in self._cache:
                # Já processamos esta mensagem — replay!
                logger.warning(
                    "Replay detectado: mensagem federada com hash %s já foi processada",
                    key[:16],
                )
                return False, "Mensagem federada duplicada (replay detectado)."

            # Marca como processada
            self._cache[key] = now

            # LRU eviction: remove entradas mais antigas que o tamanho máximo
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

            # Cleanup periódico de entradas expiradas (a cada 100 inserts)
            if len(self._cache) % 100 == 0:
                cutoff = now - _REPLAY_WINDOW_SECONDS
                expired = [k for k, ts in self._cache.items() if ts < cutoff]
                for k in expired:
                    self._cache.pop(k, None)

        return True, None

    def clear(self):
        """Limpa o cache (para testes)."""
        with self._lock:
            self._cache.clear()

    def stats(self) -> dict:
        """Retorna estatísticas para monitoramento."""
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "window_seconds": _REPLAY_WINDOW_SECONDS,
                "future_skew_seconds": _REPLAY_FUTURE_SKEW_SECONDS,
            }


# Instância global
_replay_cache = ReplayCache()


def check_replay(
    signed_payload: dict,
    timestamp: float,
    now: Optional[float] = None,
) -> Tuple[bool, Optional[str]]:
    """Convenience: delega para a instância global."""
    return _replay_cache.check_and_mark(signed_payload, timestamp, now)


def get_replay_cache_stats() -> dict:
    """Convenience: retorna stats da instância global."""
    return _replay_cache.stats()


def clear_replay_cache():
    """Convenience: limpa a instância global (para testes)."""
    _replay_cache.clear()
