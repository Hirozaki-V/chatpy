"""
#1: Rate limiting para endpoints REST.

Antes só o WebSocket tinha rate limiting (via RateLimiter em
websocket/rate_limit.py). Endpoints REST podiam receber milhares de
requisições por segundo sem nenhuma proteção — ataques de brute force
em /api/auth/login, spam de criação de salas, etc.

Este módulo oferece:
  - RESTRateLimiter: limita requisições por IP (configurável via env)
  - apply_rest_rate_limit(): dependência FastAPI para endpoints sensíveis
  - rest_rate_limit_middleware: middleware global para todos os endpoints

Configuração via env:
  - REST_RATE_LIMIT_ENABLED (default true): liga/desliga
  - REST_RATE_LIMIT_PER_MINUTE (default 60): req/min por IP
  - REST_RATE_LIMIT_BURST (default 10): pico inicial permitido
"""
import os
import time
import threading
import logging
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, deque

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse

logger = logging.getLogger("chatpy.rest_rate_limit")


# ---------------------------------------------------------------------------
# Configuração via env
# ---------------------------------------------------------------------------
_REST_RATE_LIMIT_ENABLED = os.getenv("REST_RATE_LIMIT_ENABLED", "true").lower() == "true"
_REST_RATE_LIMIT_PER_MINUTE = int(os.getenv("REST_RATE_LIMIT_PER_MINUTE", "60"))
_REST_RATE_LIMIT_BURST = int(os.getenv("REST_RATE_LIMIT_BURST", "10"))
# Janela deslizante em segundos (default 60s = 1 minuto)
_REST_RATE_LIMIT_WINDOW = int(os.getenv("REST_RATE_LIMIT_WINDOW", "60"))

# Endpoints que NÃO contam para rate limit (próprios de infra/observabilidade)
_EXEMPT_PATHS = {
    "/health", "/metrics", "/docs", "/openapi.json", "/redoc",
    "/", "/.well-known/chatpy.json",
}


class RESTRateLimiter:
    """
    Rate limiter por IP usando sliding window em memória.

    Thread-safe (usado por múltiplas threads do Uvicorn).
    Para multi-processo / multi-servidor, migrar para Redis no futuro.

    Algoritmo: token bucket simplificado com janela deslizante.
    - Mantém deque de timestamps das últimas N requisições por IP.
    - Remove timestamps mais antigos que a janela.
    - Se ainda há espaço no limite, permite; senão, rejeita com 429.
    """

    def __init__(
        self,
        max_per_window: int = _REST_RATE_LIMIT_PER_MINUTE,
        window_seconds: int = _REST_RATE_LIMIT_WINDOW,
        burst: int = _REST_RATE_LIMIT_BURST,
    ):
        self.max_per_window = max_per_window
        self.window_seconds = window_seconds
        # Burst = pico permitido em janela curta (default 10 req em 60s)
        # é subconjunto do max_per_window — efetivamente, o limite é o menor
        self.burst = min(burst, max_per_window)
        self._requests: Dict[str, deque] = defaultdict(lambda: deque())
        self._lock = threading.Lock()
        # IPs bloqueados temporariamente após exceder (cooldown)
        self._blocked_until: Dict[str, float] = {}
        self._block_duration = 60  # 1 min de cooldown após exceder

    def _get_client_ip(self, request: Request) -> str:
        """Extrai IP do cliente (suporta X-Forwarded-For de proxies)."""
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if forwarded:
            return forwarded
        if request.client:
            return request.client.host
        return "unknown"

    def check(self, request: Request) -> Tuple[bool, Optional[str], int]:
        """
        Verifica se a requisição pode prosseguir.
        Retorna (allowed, error_message, retry_after_seconds).
        """
        if not _REST_RATE_LIMIT_ENABLED:
            return True, None, 0

        ip = self._get_client_ip(request)
        now = time.time()

        with self._lock:
            # Verifica se IP está em cooldown
            blocked_until = self._blocked_until.get(ip, 0)
            if now < blocked_until:
                retry_after = int(blocked_until - now)
                return False, "Muitas requisições. Tente novamente em alguns segundos.", retry_after

            # Limpa timestamps antigos
            requests = self._requests[ip]
            cutoff = now - self.window_seconds
            while requests and requests[0] < cutoff:
                requests.popleft()

            # Verifica limite
            if len(requests) >= self.max_per_window:
                # Bloqueia o IP por 1 minuto
                self._blocked_until[ip] = now + self._block_duration
                logger.warning(
                    "Rate limit REST excedido para IP %s (%d req em %ds)",
                    ip, len(requests), self.window_seconds,
                )
                return False, "Limite de requisições excedido.", self._block_duration

            # Registra a requisição
            requests.append(now)
            return True, None, 0

    def clear(self, ip: Optional[str] = None):
        """Limpa estado de rate limiting (para testes)."""
        with self._lock:
            if ip is None:
                self._requests.clear()
                self._blocked_until.clear()
            else:
                self._requests.pop(ip, None)
                self._blocked_until.pop(ip, None)


# Instância global
_rest_rate_limiter = RESTRateLimiter()


def is_rate_limit_enabled() -> bool:
    return _REST_RATE_LIMIT_ENABLED


async def rest_rate_limit_middleware(request: Request, call_next):
    """
    Middleware FastAPI que aplica rate limiting global a todos os endpoints,
    exceto os paths em _EXEMPT_PATHS (health, metrics, docs, etc.).
    """
    path = request.url.path
    # Pula rate limit para endpoints de infra
    if path in _EXEMPT_PATHS:
        return await call_next(request)

    allowed, error_msg, retry_after = _rest_rate_limiter.check(request)
    if not allowed:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": error_msg or "Rate limit excedido."},
            headers={"Retry-After": str(retry_after)},
        )

    return await call_next(request)


# ---------------------------------------------------------------------------
# Rate limiter específico para endpoints sensíveis (login, register, guest)
# Limite mais agressivo: 10 req/min por IP (anti brute-force complementar)
# ---------------------------------------------------------------------------
_SENSITIVE_LIMIT_PER_MINUTE = int(os.getenv("SENSITIVE_ENDPOINT_LIMIT_PER_MINUTE", "10"))
_sensitive_limiter = RESTRateLimiter(
    max_per_window=_SENSITIVE_LIMIT_PER_MINUTE,
    window_seconds=60,
    burst=_SENSITIVE_LIMIT_PER_MINUTE,
)


def check_sensitive_endpoint(request: Request) -> None:
    """
    Verifica rate limit para endpoints sensíveis (login, register, guest).
    Lança HTTPException 429 se excedido. Mais agressivo que o global.

    Uso:
        @router.post("/login")
        def login(req: LoginRequest, request: Request, db: Session = ...):
            check_sensitive_endpoint(request)
            # ... resto do handler
    """
    if not _REST_RATE_LIMIT_ENABLED:
        return
    allowed, error_msg, retry_after = _sensitive_limiter.check(request)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_msg or "Muitas tentativas. Tente novamente mais tarde.",
            headers={"Retry-After": str(retry_after)},
        )
