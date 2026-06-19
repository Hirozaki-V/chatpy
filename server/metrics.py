"""
P2-7: Métricas Prometheus para o servidor ChatPy.

Expostas em GET /metrics no formato text/plain compatível com Prometheus.
Inclui contadores e gauges para:
  - Conexões WebSocket ativas
  - Mensagens enviadas (por tipo: room, dm)
  - Logins (sucesso, falha, guest)
  - Sessões ativas
  - Uploads de anexos
  - Amizades (pendentes, aceitas, bloqueadas)
  - Salas (total, privadas, públicas)
  - Latência de endpoints HTTP (histograma)

Uso:
  - Prometheus scrape: add target http://chatpy-server:5000/metrics
  - Grafana: importar dashboard ou construir queries PromQL
"""

try:
    from prometheus_client import (
        Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # Stubs para permitir import mesmo sem prometheus_client instalado
    def generate_latest():
        return b"# prometheus_client not installed\n"
    CONTENT_TYPE_LATEST = "text/plain; charset=utf-8"


if PROMETHEUS_AVAILABLE:
    # Usa registry default — permite que outras libs (ex: uvicorn) também
    # exponham métricas no mesmo endpoint.

    # ── WebSocket ──────────────────────────────────────────────────────
    ws_connections_active = Gauge(
        "chatpy_ws_connections_active",
        "Número de conexões WebSocket ativas no momento",
    )
    ws_messages_received_total = Counter(
        "chatpy_ws_messages_received_total",
        "Total de mensagens WebSocket recebidas",
        ["event_type"],
    )
    ws_messages_sent_total = Counter(
        "chatpy_ws_messages_sent_total",
        "Total de mensagens WebSocket enviadas",
        ["event_type"],
    )
    ws_rate_limit_mutes_total = Counter(
        "chatpy_ws_rate_limit_mutes_total",
        "Total de vezes que usuários foram mutados por flood",
    )

    # ── Auth ───────────────────────────────────────────────────────────
    auth_logins_total = Counter(
        "chatpy_auth_logins_total",
        "Total de tentativas de login",
        ["result"],  # success, invalid_credentials, too_many_attempts
    )
    auth_registrations_total = Counter(
        "chatpy_auth_registrations_total",
        "Total de registros de novos usuários",
        ["user_type"],  # normal, guest
    )
    auth_sessions_active = Gauge(
        "chatpy_auth_sessions_active",
        "Número de sessões ativas no banco",
    )

    # ── Mensagens ──────────────────────────────────────────────────────
    messages_sent_total = Counter(
        "chatpy_messages_sent_total",
        "Total de mensagens persistidas",
        ["type"],  # room, private
    )

    # ── Anexos ─────────────────────────────────────────────────────────
    attachments_uploads_total = Counter(
        "chatpy_attachments_uploads_total",
        "Total de uploads de anexos",
        ["mime_type"],
    )
    attachments_uploads_bytes_total = Counter(
        "chatpy_attachments_uploads_bytes_total",
        "Total de bytes enviados em uploads de anexos",
    )
    attachments_rejected_total = Counter(
        "chatpy_attachments_rejected_total",
        "Total de uploads rejeitados (validação)",
        ["reason"],  # extension, mime_type, size, empty
    )

    # ── Salas e Amizades ───────────────────────────────────────────────
    rooms_total = Gauge(
        "chatpy_rooms_total",
        "Número total de salas",
        ["is_private"],  # true, false
    )
    friendships_total = Gauge(
        "chatpy_friendships_total",
        "Número de relações de amizade",
        ["status"],  # pending, accepted, blocked
    )

    # ── HTTP ───────────────────────────────────────────────────────────
    http_requests_total = Counter(
        "chatpy_http_requests_total",
        "Total de requisições HTTP",
        ["method", "endpoint", "status"],
    )
    http_request_duration_seconds = Histogram(
        "chatpy_http_request_duration_seconds",
        "Latência de requisições HTTP em segundos",
        ["method", "endpoint"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )

    # ── DB ─────────────────────────────────────────────────────────────
    db_pool_size = Gauge(
        "chatpy_db_pool_size",
        "Tamanho do pool de conexões do SQLAlchemy",
    )


def get_metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST


def get_metrics_bytes() -> bytes:
    """
    Retorna as métricas no formato Prometheus text.
    Se prometheus_client não estiver instalado, retorna comentário explicativo.
    """
    if not PROMETHEUS_AVAILABLE:
        return b"# prometheus_client not installed. Install with: pip install prometheus_client\n"
    return generate_latest()


def is_metrics_enabled() -> bool:
    """Verifica se prometheus_client está disponível."""
    return PROMETHEUS_AVAILABLE


# ── Helpers para instrumentação fácil ──────────────────────────────────

def record_ws_message_received(event_type: str):
    """Incrementa contador de mensagem WS recebida."""
    if PROMETHEUS_AVAILABLE:
        ws_messages_received_total.labels(event_type=event_type).inc()


def record_ws_message_sent(event_type: str):
    """Incrementa contador de mensagem WS enviada."""
    if PROMETHEUS_AVAILABLE:
        ws_messages_sent_total.labels(event_type=event_type).inc()


def record_ws_rate_limit_mute():
    """Incrementa contador de mute por flood."""
    if PROMETHEUS_AVAILABLE:
        ws_rate_limit_mutes_total.inc()


def record_login_attempt(result: str):
    """result: 'success' | 'invalid_credentials' | 'too_many_attempts'"""
    if PROMETHEUS_AVAILABLE:
        auth_logins_total.labels(result=result).inc()


def record_registration(user_type: str):
    """user_type: 'normal' | 'guest'"""
    if PROMETHEUS_AVAILABLE:
        auth_registrations_total.labels(user_type=user_type).inc()


def record_message_sent(msg_type: str):
    """msg_type: 'room' | 'private'"""
    if PROMETHEUS_AVAILABLE:
        messages_sent_total.labels(type=msg_type).inc()


def record_attachment_upload(mime_type: str, file_size: int):
    if PROMETHEUS_AVAILABLE:
        attachments_uploads_total.labels(mime_type=mime_type).inc()
        attachments_uploads_bytes_total.inc(file_size)


def record_attachment_rejection(reason: str):
    if PROMETHEUS_AVAILABLE:
        attachments_rejected_total.labels(reason=reason).inc()


def update_ws_connections_active(count: int):
    if PROMETHEUS_AVAILABLE:
        ws_connections_active.set(count)


def update_rooms_total(public_count: int, private_count: int):
    if PROMETHEUS_AVAILABLE:
        rooms_total.labels(is_private="false").set(public_count)
        rooms_total.labels(is_private="true").set(private_count)


def update_friendships_total(pending: int, accepted: int, blocked: int):
    if PROMETHEUS_AVAILABLE:
        friendships_total.labels(status="pending").set(pending)
        friendships_total.labels(status="accepted").set(accepted)
        friendships_total.labels(status="blocked").set(blocked)


def update_sessions_active(count: int):
    if PROMETHEUS_AVAILABLE:
        auth_sessions_active.set(count)


def record_http_request(method: str, endpoint: str, status: int, duration_seconds: float):
    if PROMETHEUS_AVAILABLE:
        http_requests_total.labels(method=method, endpoint=endpoint, status=str(status)).inc()
        http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration_seconds)
