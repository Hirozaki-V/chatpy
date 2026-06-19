import os
import logging
from contextlib import asynccontextmanager

# Carrega variáveis de arquivo .env ANTES de qualquer import que precise delas
try:
    from dotenv import load_dotenv
    # Procura .env no diretório atual e no diretório pai (raiz do projeto)
    for env_path in (os.path.join(os.getcwd(), ".env"), os.path.join(os.path.dirname(__file__), "..", ".env")):
        if os.path.exists(env_path):
            load_dotenv(env_path)
            break
except ImportError:
    # python-dotenv opcional — apenas warning, não quebra o startup
    pass

# P1-10: logging estruturado configurado ANTES de qualquer logger ser usado.
from server.logging_config import configure_logging
configure_logging()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio

from server.database.connection import init_db
from server.api import auth_router, users_router, rooms_router, friends_router, attachments_router
from server.websocket.manager import ConnectionManager
from server.websocket.rate_limit import RateLimiter
from server.websocket.dispatcher import WebSocketDispatcher
from server.api.attachments import cleanup_orphan_attachments

logger = logging.getLogger("chatpy.main")


# ---------------------------------------------------------------------------
# Validação obrigatória de JWT_SECRET em startup (fail-fast)
# ---------------------------------------------------------------------------
def _validate_jwt_secret():
    """
    #1: Valida JWT_SECRET do ambiente. Se não estiver configurado,
    NÃO falha mais — _get_jwt_secret() em security.py auto-gera e
    persiste. Aqui só validamos SE o usuário configurou manualmente
    e a chave é muito curta.
    """
    secret = os.getenv("JWT_SECRET")
    if secret and len(secret) < 16:
        raise RuntimeError("'JWT_SECRET' deve ter no mínimo 16 caracteres.")
    if not secret:
        logger.info(
            "JWT_SECRET não configurado — será auto-gerado automaticamente. "
            "Para produção, defina JWT_SECRET no arquivo .env."
        )


# ---------------------------------------------------------------------------
# Lifespan context manager (substitui @app.on_event("startup") deprecated)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação: startup e shutdown."""
    # === STARTUP ===
    _validate_jwt_secret()
    logger.info("JWT_SECRET validado.")
    init_db()
    logger.info("Banco de dados inicializado.")

    # #5: Primeiro-run detection — se não há usuários, mostra instruções
    try:
        from server.database.connection import get_db
        from server.database.models import User
        with get_db() as db:
            user_count = db.query(User).count()
        if user_count == 0:
            logger.info("=" * 60)
            logger.info("PRIMEIRA EXECUÇÃO DETECTADA — nenhum usuário cadastrado.")
            logger.info("Para criar sua conta:")
            logger.info("  1. Abra http://localhost:5000/admin no navegador")
            logger.info("  2. Ou use o cliente: python client-desktop/main.py")
            logger.info("  3. Clique em 'Não tem conta? Cadastre-se'")
            logger.info("  Ou via API: POST /api/auth/register")
            logger.info("=" * 60)
    except Exception:
        pass

    cleanup_task = asyncio.create_task(_attachment_cleanup_loop())
    logger.info("Tarefa de limpeza de anexos órfãos iniciada (intervalo: 1h).")

    # P2-2: job de limpeza de contas de convidado expiradas
    guest_cleanup_task = asyncio.create_task(_guest_cleanup_loop())
    logger.info("Tarefa de limpeza de convidados expirados iniciada (intervalo: 1h).")

    # #6: job de backup automático do SQLite (se habilitado)
    backup_task = None
    from server.backup import is_backup_enabled, get_backup_interval_seconds
    if is_backup_enabled():
        backup_task = asyncio.create_task(_backup_loop())
        logger.info(
            "Backup automático iniciado (intervalo: %dh)",
            get_backup_interval_seconds() // 3600,
        )
    else:
        logger.info("Backup automático desabilitado (BACKUP_ENABLED=false)")

    # #7: LAN discovery via mDNS — anuncia este servidor na rede local
    from server.lan_discovery import start_announcing, is_lan_discovery_enabled
    if is_lan_discovery_enabled():
        start_announcing()
    else:
        logger.info("LAN discovery desabilitado")

    # P1-FIX: Heartbeat WS para detectar conexões zumbis. O manager é criado
    # depois do lifespan começar (ver seção abaixo), então agendamos o
    # start_heartbeat para rodar após o primeiro yield — mas na verdade o
    # manager é criado em módulo (não dentro do lifespan), então podemos
    # iniciar aqui mesmo. Verificamos se o atributo existe por segurança.
    try:
        # O manager é definido mais abaixo no arquivo (module-level), mas
        # o lifespan roda no startup do uvicorn (depois do module load).
        # Verificamos se está disponível via app.state (setado abaixo).
        manager_ref = getattr(app.state, "manager", None)
        if manager_ref is not None:
            import os as _os_hb
            interval = int(_os_hb.getenv("WS_HEARTBEAT_INTERVAL_SECONDS", "30"))
            timeout = int(_os_hb.getenv("WS_HEARTBEAT_TIMEOUT_SECONDS", "60"))
            manager_ref.start_heartbeat(interval_seconds=interval, timeout_seconds=timeout)
    except Exception as e:
        logger.warning("Falha ao iniciar heartbeat WS: %s", e)

    # Expõe no app.state para shutdown
    app.state._cleanup_task = cleanup_task
    app.state._guest_cleanup_task = guest_cleanup_task
    app.state._backup_task = backup_task

    yield

    # === SHUTDOWN ===
    cleanup_task.cancel()
    guest_cleanup_task.cancel()
    if backup_task is not None:
        backup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    try:
        await guest_cleanup_task
    except asyncio.CancelledError:
        pass
    if backup_task is not None:
        try:
            await backup_task
        except asyncio.CancelledError:
            pass
    # P1-FIX: para o heartbeat WS antes de desligar
    try:
        manager_ref = getattr(app.state, "manager", None)
        if manager_ref is not None:
            await manager_ref.stop_heartbeat()
    except Exception as e:
        logger.warning("Erro ao parar heartbeat WS: %s", e)
    # T3-FIX: fecha o Pub/Sub broker (Redis) antes de desligar
    try:
        from server.pubsub import close_broker
        await close_broker()
    except Exception as e:
        logger.warning("Erro ao fechar Pub/Sub broker: %s", e)
    # #7: para de anunciar via mDNS
    try:
        from server.lan_discovery import stop_announcing
        stop_announcing()
    except Exception:
        pass
    logger.info("Servidor ChatPy desligado com sucesso.")


async def _attachment_cleanup_loop():
    """
    Loop que executa a limpeza de anexos órfãos.

    S4-FIX: intervalo agora configurável via env ATTACHMENT_CLEANUP_INTERVAL_SECONDS
    (default 3600 = 1 hora). Administradores podem ajustar conforme a carga
    do servidor e políticas de retenção.
    """
    interval = int(os.getenv("ATTACHMENT_CLEANUP_INTERVAL_SECONDS", "3600"))
    logger.info("Job de limpeza de anexos iniciado (intervalo: %ds)", interval)
    while True:
        try:
            await asyncio.to_thread(cleanup_orphan_attachments)
        except Exception as e:
            logger.error("Erro no job de limpeza de anexos: %s", e)
        await asyncio.sleep(interval)


async def _guest_cleanup_loop():
    """
    P2-2: Loop que purga contas de convidado expiradas.
    Remove usuários com is_guest=True cujo expires_at < now().
    Cascade delete cuida de sessions, memberships, etc.

    S4-FIX: intervalo agora configurável via env GUEST_CLEANUP_INTERVAL_SECONDS
    (default 3600 = 1 hora).
    """
    interval = int(os.getenv("GUEST_CLEANUP_INTERVAL_SECONDS", "3600"))
    logger.info("Job de limpeza de convidados iniciado (intervalo: %ds)", interval)
    while True:
        try:
            def _do_purge():
                from server.auth.service import purgar_guests_expirados
                from server.database.connection import get_db
                with get_db() as db:
                    count = purgar_guests_expirados(db)
                    if count > 0:
                        logger.info("Limpeza de convidados: %d conta(s) expirada(s) removida(s).", count)
            await asyncio.to_thread(_do_purge)
        except Exception as e:
            logger.error("Erro no job de limpeza de convidados: %s", e)
        await asyncio.sleep(interval)


async def _backup_loop():
    """
    #6: Loop que executa backup automático do SQLite.
    Frequência configurável via BACKUP_INTERVAL_HOURS (default 24h).
    """
    from server.backup import perform_backup, get_backup_interval_seconds
    interval = get_backup_interval_seconds()
    # Primeiro backup imediatamente no startup (não espera 24h)
    try:
        await asyncio.to_thread(perform_backup)
    except Exception as e:
        logger.error("Erro no backup inicial: %s", e)
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(perform_backup)
        except Exception as e:
            logger.error("Erro no job de backup: %s", e)


# ---------------------------------------------------------------------------
# Criação da aplicação FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(
    title="ChatPy V2 Server",
    description="Servidor assíncrono modular de chat e mensagens em tempo real.",
    version="2.0.1",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — permite configuração flexível via env (default permite localhost)
# ---------------------------------------------------------------------------
_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost,http://127.0.0.1").split(",")
_cors_origins = [o.strip() for o in _cors_origins if o.strip()]

# CORREÇÃO: default anterior restringia a localhost, o que impedia o cliente
# desktop de se conectar quando o servidor rodava em outra máquina da LAN
# (caso de uso central do projeto — "qualquer um pode hospedar"). Incluímos
# também a origem do próprio host (http://<meu-ip>:5000) por padrão, e
# mantemos a possibilidade de abrir para "*" via CORS_ORIGINS=*.
# P0-FIX: Starlette/Flask-style CORS proíbe allow_origins=["*"] combinado com
# allow_credentials=True — gera ValueError no startup. Detectamos o caso e
# ajustamos: quando o operador pede "*", desligamos credentials (não há como
# o navegador enviar cookies/Authorization para origem "*" mesmo, e o cliente
# ChatPy envia Authorization via header, não cookie — logo, seguro).
if "*" in _cors_origins:
    _cors_origins_resolved = ["*"]
    _cors_allow_credentials = False
    logger.warning(
        "CORS_ORIGINS=* detectado — allow_credentials desligado "
        "(compatível com Starlette). Clientes ChatPy usam header Authorization, "
        "não cookies, então isto é seguro."
    )
else:
    _cors_origins_resolved = list(_cors_origins)
    _cors_allow_credentials = True
    # P0-FIX: usa get_local_ip() do lan_discovery (UDP socket para 8.8.8.8)
    # em vez de socket.gethostbyname(socket.gethostname()), que no Linux
    # frequentemente retorna 127.0.1.1 (entrada padrão em /etc/hosts).
    try:
        from server.lan_discovery import get_local_ip
        local_ip = get_local_ip()
        if local_ip and not local_ip.startswith("127."):
            _cors_origins_resolved.append(f"http://{local_ip}:5000")
            _cors_origins_resolved.append(f"http://{local_ip}")
    except Exception:
        pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins_resolved,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# SECURITY: middleware de security headers (CSP, X-Frame-Options, etc.)
# Camada de defesa em profundidade — mesmo que um XSS escape à sanitização
# server-side, o CSP bloqueia execução de scripts inline não-permitidos.
# Aplicado em TODAS as respostas (incluindo /admin, /docs, /api/*).
# ---------------------------------------------------------------------------
@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    # X-Content-Type-Options: impede MIME sniffing em anexos baixados
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # X-Frame-Options: impede clickjacking via iframe
    response.headers.setdefault("X-Frame-Options", "DENY")
    # Referrer-Policy: não vaza URL completa em headers Referer cross-origin
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # HSTS: força HTTPS em produção (1 ano + preload)
    # Só aplicado se estiver em HTTPS para não quebrar dev local
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains; preload",
        )
    # CSP: default-src 'self' — bloqueia assets de terceiros.
    # /admin tem inline script/style (single-file HTML), então 'unsafe-inline'
    # é necessário para scripts e styles. Endpoints /api/* não servem HTML,
    # então o CSP não os afeta.
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
        "img-src 'self' data:; frame-ancestors 'none';",
    )
    return response


# ---------------------------------------------------------------------------
# #1: Middleware de rate limiting global para REST.
# Limite padrão: 60 req/min por IP (configurável via env).
# Endpoints de infra (/health, /metrics, /docs) são isentos.
# Aplicado ANTES do middleware de erro para que 429 não vire 500.
# ---------------------------------------------------------------------------
from server.rest_rate_limit import rest_rate_limit_middleware, is_rate_limit_enabled
if is_rate_limit_enabled():
    app.middleware("http")(rest_rate_limit_middleware)
    logger.info(
        "Rate limit REST ativado: %s req/%s por IP",
        os.getenv("REST_RATE_LIMIT_PER_MINUTE", "60"),
        os.getenv("REST_RATE_LIMIT_WINDOW", "60"),
    )


# ---------------------------------------------------------------------------
# Middleware de logging de erros não tratados
# ---------------------------------------------------------------------------
@app.middleware("http")
async def _error_logger(request: Request, call_next):
    """
    S5-FIX: tratamento de erros mais granular.

    Antes: qualquer exceção não tratada virava 500 genérico "Erro interno
    do servidor". Agora diferenciamos tipos comuns de erro para dar feedback
    mais útil ao cliente sem expor detalhes internos:
      - HTTPException: repassa status e detail originais (FastAPI já faz isto,
        mas capturamos aqui para logar)
      - RequestValidationError (422): repassa sem logar como erro (é erro de
        cliente, não de servidor)
      - Outras exceções: 500 genérico + log completo no servidor
    """
    # P2-7: instrumenta latência e contagem de requisições HTTP.
    # Ignora /metrics para não criar loop de auto-incremento.
    import time as _time
    start = _time.perf_counter()
    response = None
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        # S5-FIX: tratamento granular por tipo de exceção
        from fastapi import HTTPException as _FastAPIHTTPException
        from fastapi.exceptions import RequestValidationError as _RVE

        if isinstance(e, _FastAPIHTTPException):
            # HTTPException já tem status_code e detail — repassa
            logger.warning(
                "HTTPException em %s %s: %d %s",
                request.method, request.url.path,
                e.status_code, e.detail,
            )
            return JSONResponse(
                status_code=e.status_code,
                content={"detail": e.detail},
                headers=getattr(e, "headers", None),
            )
        elif isinstance(e, _RVE):
            # Erro de validação 422 — é erro do cliente, não loga como ERROR
            logger.info(
                "Validação falhou em %s %s: %s",
                request.method, request.url.path, str(e)[:200],
            )
            return JSONResponse(
                status_code=422,
                content={"detail": "Dados de entrada inválidos.", "errors": e.errors()},
            )
        else:
            # Erro inesperado — loga completo no servidor, mensagem genérica ao cliente
            logger.error(
                "Erro não tratado em %s %s: %s",
                request.method,
                request.url.path,
                e,
                exc_info=True,
            )
            # S5-FIX: em modo debug (LOG_LEVEL=DEBUG), inclui a mensagem da
            # exceção para ajudar o desenvolvedor. Em produção, mensagem genérica.
            log_level = os.getenv("LOG_LEVEL", "INFO").upper()
            if log_level == "DEBUG":
                detail = f"Erro interno: {type(e).__name__}: {str(e)[:200]}"
            else:
                detail = "Erro interno do servidor. Verifique os logs do servidor para detalhes."
            return JSONResponse(
                status_code=500,
                content={"detail": detail},
            )
    finally:
        # P2-7: registra métrica de requisição HTTP (não conta /metrics
        # nem /docs para não inflar artificialmente).
        path = request.url.path
        if path not in ("/metrics", "/docs", "/openapi.json", "/redoc"):
            try:
                from server.metrics import record_http_request
                duration = _time.perf_counter() - start
                status_code = response.status_code if response is not None else 500
                record_http_request(request.method, path, status_code, duration)
            except Exception:
                # Métricas são best-effort — nunca quebrar a requisição por causa delas
                pass


# ---------------------------------------------------------------------------
# Healthcheck endpoint
# ---------------------------------------------------------------------------
@app.get("/health", tags=["health"])
async def health_check():
    """
    Healthcheck para Docker e load balancers.

    #4: Agora verifica 3 componentes além do banco:
      - Database: conexão + query simples
      - WebSocket: ConnectionManager inicializado e aceitando conexões
      - Rate limiter: instâncias ativas (não travadas)

    Retorna 200 se tudo OK, 503 se algum componente falhar.
    """
    components = {}
    overall_healthy = True

    # 1. Database
    try:
        from server.database.connection import get_db
        from server.database.models import User
        with get_db() as db:
            db.query(User).first()
        components["database"] = "ok"
    except Exception as e:
        logger.error("Healthcheck DB falhou: %s", e)
        components["database"] = f"error: {str(e)[:100]}"
        overall_healthy = False

    # 2. #4: WebSocket — verifica se o ConnectionManager existe e tem
    # estrutura interna consistente. Não abre conexão real (seria caro
    # a cada healthcheck) — só valida que o manager está inicializado.
    try:
        manager = getattr(app.state, "manager", None)
        if manager is None:
            components["websocket"] = "error: manager not initialized"
            overall_healthy = False
        elif not hasattr(manager, "active_connections"):
            components["websocket"] = "error: manager missing active_connections"
            overall_healthy = False
        else:
            # Conta conexões ativas — se negativo ou NaN, algo está errado
            active_count = len(manager.active_connections)
            if active_count < 0:
                components["websocket"] = "error: negative active count"
                overall_healthy = False
            else:
                components["websocket"] = f"ok ({active_count} active)"
    except Exception as e:
        logger.error("Healthcheck WS falhou: %s", e)
        components["websocket"] = f"error: {str(e)[:100]}"
        overall_healthy = False

    # 3. #4: Rate limiter — verifica se a instância existe (não travou em lock)
    try:
        rate_limiter = getattr(app.state, "rate_limiter", None)
        if rate_limiter is None:
            components["rate_limiter"] = "error: not initialized"
            overall_healthy = False
        else:
            components["rate_limiter"] = "ok"
    except Exception as e:
        components["rate_limiter"] = f"error: {str(e)[:100]}"
        overall_healthy = False

    # 4. #4: Federação (se habilitada) — verifica que o módulo carregou
    try:
        from server.federation import is_federation_enabled
        components["federation"] = "enabled" if is_federation_enabled() else "disabled"
    except Exception as e:
        components["federation"] = f"error: {str(e)[:100]}"
        # Federação com erro não derruba o healthcheck (é opcional)

    status_code = 200 if overall_healthy else 503
    response = {
        "status": "healthy" if overall_healthy else "unhealthy",
        "version": "2.0.1",
        "components": components,
    }
    if not overall_healthy:
        return JSONResponse(status_code=status_code, content=response)
    return response


@app.get("/", tags=["root"])
async def root():
    """Endpoint raiz — redireciona para /docs."""
    return {"name": "ChatPy V2 Server", "docs": "/docs", "health": "/health"}


@app.get("/api/version", tags=["version"])
async def get_version():
    """
    #9: Retorna versão do servidor + versão mínima do cliente compatível.
    Clientes usam isso para notificar usuário de updates disponíveis.
    """
    return {
        "server_version": "2.0.1",
        "min_client_version": "2.0.0",
        "latest_client_version": "2.0.1",
        "download_url": "https://github.com/your-org/chatpy/releases/latest",
        "changelog": "https://github.com/your-org/chatpy/blob/main/CHANGELOG.md",
    }


@app.get("/admin", tags=["admin"])
async def admin_panel():
    """
    #8: Painel admin web — dashboard com métricas, usuários, salas, peers,
    backups e saúde do servidor. Requer login (token JWT) na própria página.

    Acessível em http://servidor:5000/admin — não precisa de instalação.
    """
    from fastapi import Response
    from pathlib import Path
    admin_html = Path(__file__).parent / "static" / "admin.html"
    if admin_html.exists():
        return Response(content=admin_html.read_text(encoding="utf-8"), media_type="text/html")
    return {"error": "admin.html não encontrado"}


@app.get("/metrics", tags=["metrics"])
async def metrics():
    """
    P2-7: Endpoint de métricas no formato Prometheus text.

    Requer `pip install prometheus_client`. Se não estiver instalado,
    retorna um comentário explicativo (não quebra o servidor).

    Recomendação de scrape: a cada 15s.
    Exemplo de configuração Prometheus:
        - job_name: 'chatpy'
          scrape_interval: 15s
          static_configs:
            - targets: ['chatpy-server:5000']
    """
    from server.metrics import get_metrics_bytes, get_metrics_content_type
    from fastapi import Response
    return Response(
        content=get_metrics_bytes(),
        media_type=get_metrics_content_type(),
    )


# ---------------------------------------------------------------------------
# P2-1: Federação — endpoints de descoberta e recebimento de DMs
# ---------------------------------------------------------------------------
@app.get("/.well-known/chatpy.json", tags=["federation"])
async def well_known_chatpy():
    """
    Descoberta de federação — outros servidores ChatPy podem fazer GET
    neste endpoint para descobrir a URL base, chave pública e capacidades
    deste servidor. Estilo .well-known/matrix/client.
    """
    from server.federation import get_well_known_info
    return get_well_known_info()


@app.post("/api/federation/dm", tags=["federation"])
async def receive_federated_dm_endpoint(req: Request):
    """
    Recebe uma DM federada de outro servidor ChatPy.

    O servidor de origem envia um JSON com:
      - sender_username, sender_domain
      - receiver_username (local)
      - content, timestamp
      - signature (base64 Ed25519), signer_domain

    Valida permissões (peer registrado ou open_federation) e entrega
    ao destinatário local (persiste + notifica via WebSocket se online).
    """
    from server.federation import receive_federated_dm, is_federation_enabled
    from server.database.connection import get_db
    from datetime import datetime, timezone

    if not is_federation_enabled():
        return JSONResponse(
            status_code=403,
            content={"detail": "Federação desabilitada neste servidor"},
        )

    try:
        payload = await req.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "JSON inválido"})

    required = ["sender_username", "sender_domain", "receiver_username", "content", "timestamp"]
    for field in required:
        if not payload.get(field):
            return JSONResponse(
                status_code=400,
                content={"detail": f"Campo obrigatório ausente: {field}"},
            )

    try:
        ts = datetime.fromisoformat(payload["timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:
        ts = datetime.now(timezone.utc)

    with get_db() as db:
        # P0-FIX: receive_federated_dm agora é async — usa await direto
        success, msg = await receive_federated_dm(
            db=db,
            sender_username=payload["sender_username"],
            sender_domain=payload["sender_domain"],
            receiver_username=payload["receiver_username"],
            content=payload["content"],
            timestamp=ts,
            signature=payload.get("signature"),
            signer_domain=payload.get("signer_domain") or payload.get("sender_domain"),
        )

    if success:
        return {"status": "ok", "message": msg}
    else:
        return JSONResponse(status_code=400, content={"detail": msg})


@app.post("/api/federation/presence", tags=["federation"])
async def receive_federated_presence_endpoint(req: Request):
    """
    #5: Recebe notificação de presença de um servidor peer.
    """
    from server.federation import receive_federated_presence, is_federation_enabled
    from server.database.connection import get_db

    if not is_federation_enabled():
        return JSONResponse(status_code=403, content={"detail": "Federação desabilitada"})

    try:
        payload = await req.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "JSON inválido"})

    with get_db() as db:
        # P0-FIX: receive_federated_presence agora é async
        success, msg = await receive_federated_presence(
            db=db,
            username=payload.get("username", ""),
            domain=payload.get("domain", ""),
            status=payload.get("status", ""),
            signature=payload.get("signature"),
            signer_domain=payload.get("signer_domain") or payload.get("domain"),
        )

    if success:
        return {"status": "ok"}
    return JSONResponse(status_code=400, content={"detail": msg})


# ---------------------------------------------------------------------------
# #6: Endpoint de administração de backups
# ---------------------------------------------------------------------------
# Importa a dependência de autenticação para proteger endpoints admin.
# P0-FIX: endpoints /api/admin/* agora exigem require_admin (is_admin=True no User)
from server.api.dependencies import require_admin as _require_admin


@app.get("/api/admin/backups", tags=["admin"])
async def list_backups_endpoint(current_user=Depends(_require_admin)):
    """
    Lista backups existentes do SQLite. Requer privilégios de administrador.

    P0-FIX: antes, qualquer usuário autenticado podia ver backups (e até
    forçar criação). Agora exige is_admin=True.
    """
    from server.backup import list_backups, is_backup_enabled
    return {
        "enabled": is_backup_enabled(),
        "backups": list_backups(),
    }


@app.post("/api/admin/backups/now", tags=["admin"])
async def trigger_backup_now_endpoint(current_user=Depends(_require_admin)):
    """
    Força um backup imediato (além do agendamento). Requer admin.

    P0-FIX: antes este endpoint era aberto a qualquer usuário autenticado,
    permitindo DoS de disco (chamar N vezes/segundo). Agora exige is_admin.
    """
    from server.backup import perform_backup, is_backup_enabled
    if not is_backup_enabled():
        return JSONResponse(
            status_code=400,
            content={"detail": "Backup desabilitado. Set BACKUP_ENABLED=true para usar."},
        )
    success = perform_backup()
    if success:
        return {"status": "ok", "message": "Backup criado com sucesso."}
    return JSONResponse(
        status_code=500,
        content={"detail": "Falha ao criar backup. Verifique os logs do servidor."},
    )


# ---------------------------------------------------------------------------
# Registro das rotas REST
# ---------------------------------------------------------------------------
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(rooms_router)
app.include_router(friends_router)
app.include_router(attachments_router)

# #9: Router de administração de peers federados
from server.api.federation_admin import router as federation_admin_router
app.include_router(federation_admin_router)

# #2: Router de chaves E2E (Signal Protocol scaffold)
from server.api.e2e_keys import router as e2e_keys_router
app.include_router(e2e_keys_router)


# ---------------------------------------------------------------------------
# WebSocket — instância global de manager/rate_limiter/dispatcher
# ---------------------------------------------------------------------------
manager = ConnectionManager()
app.state.manager = manager
rate_limiter = RateLimiter()
app.state.rate_limiter = rate_limiter  # #4: expõe para healthcheck
dispatcher = WebSocketDispatcher(manager, rate_limiter)

# P0-FIX: guard de conexões não-autenticadas por IP — previne DoS via
# milhares de conexões penduradas no timeout de auth (30s)
from server.websocket.rate_limit import (
    UnauthConnectionGuard,
    AuthenticatedConnectionGuard,
    IpRateLimiter,
)
unauth_guard = UnauthConnectionGuard()
app.state.unauth_guard = unauth_guard

# SECURITY (auditoria-2026-06): guard de conexões autenticadas por IP —
# previne DoS via 10 guests/IP/min = 600 conexões autenticadas em 1h.
auth_guard = AuthenticatedConnectionGuard()
app.state.auth_guard = auth_guard

# SECURITY: rate limiter de mensagens WS por IP (complementar ao por-user).
# Muta o IP inteiro se o agregado de todos usernames daquele IP exceder.
ip_rate_limiter = IpRateLimiter()
app.state.ip_rate_limiter = ip_rate_limiter

# Passa o IP rate limiter para o dispatcher usar
dispatcher.ip_rate_limiter = ip_rate_limiter

# P2-1.2a: Registra o ConnectionManager no módulo de federação para que
# DMs federadas recebidas sejam entregues via WebSocket ao destinatário.
from server.federation import set_connection_manager
set_connection_manager(manager)


def _extract_client_ip(websocket: WebSocket) -> str:
    """
    Extrai IP do cliente WebSocket de forma segura.

    T1-FIX: antes confiávamos cegamente em X-Forwarded-For, permitindo
    spoofing. Agora só confiamos no header se veio de proxy confiável.
    """
    from server.security_ip import get_client_ip
    return get_client_ip(websocket)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Rota WebSocket principal para comunicação real-time baseada em eventos.
    Lida com o ciclo de vida completo da conexão, autenticação, dispatching
    e atualização reativa de presença de usuários offline na desconexão.

    P0-FIX: aplica UnauthConnectionGuard ANTES do accept — se o IP excedeu
    o limite de conexões não-autenticadas, recusa com 1008 sem sequer
    aceitar o socket (consome menos recursos).
    """
    client_ip = _extract_client_ip(websocket)

    # P0-FIX: rate limit de conexões não-autenticadas por IP
    acquired = await unauth_guard.try_acquire(client_ip)
    if not acquired:
        logger.warning(
            "WS rejeitada por limite de conexões não-autenticadas: IP=%s", client_ip,
        )
        # Fecha ANTES do accept com código 1008 (Policy Violation)
        await websocket.close(code=1008, reason="Muitas conexões pendentes. Tente novamente.")
        return

    await websocket.accept()
    authenticated_user_id = None
    auth_guard_acquired = False

    try:
        # Timeout de proteção na etapa de autenticação (30 segundos)
        try:
            data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            authenticated_user_id = await dispatcher.dispatch(websocket, None, data)
            if authenticated_user_id is None:
                return
        except asyncio.TimeoutError:
            logger.warning("Conexão barrada: Timeout aguardando payload de autenticação.")
            try:
                await websocket.close(code=1008, reason="Timeout na autenticação.")
            except Exception:
                pass
            return

        # SECURITY (auditoria-2026-06): após auth success, aplica o
        # AuthenticatedConnectionGuard para limitar conexões autenticadas
        # por IP. Se excedeu, recusa com 1008 e desconecta.
        if not await auth_guard.try_acquire(client_ip):
            logger.warning(
                "WS rejeitada pós-auth por limite de conexões autenticadas: IP=%s",
                client_ip,
            )
            try:
                await websocket.close(
                    code=1008,
                    reason="Muitas conexões autenticadas para este IP.",
                )
            except Exception:
                pass
            return
        auth_guard_acquired = True

        # Loop principal (Conexão normal)
        while True:
            data = await websocket.receive_text()
            new_user_id = await dispatcher.dispatch(websocket, authenticated_user_id, data)

            if new_user_id is None:
                break

            authenticated_user_id = new_user_id

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(
            "Erro inesperado no WebSocket (user_id=%s): %s",
            authenticated_user_id,
            e,
            exc_info=True,
        )
    finally:
        # P0-FIX: libera o slot do guard de conexões não-autenticadas
        await unauth_guard.release(client_ip)
        # SECURITY: libera o slot do guard de conexões autenticadas
        if auth_guard_acquired:
            await auth_guard.release(client_ip)

        # Limpeza na desconexão do socket
        if authenticated_user_id:
            await manager.disconnect(authenticated_user_id)

            def set_offline():
                from server.database.connection import get_db
                from server.database.models import User
                with get_db() as db:
                    user = db.query(User).filter(User.id == authenticated_user_id).first()
                    if user:
                        user.status = "offline"
                        db.commit()

            try:
                await asyncio.to_thread(set_offline)
            except Exception as e:
                logger.error("Erro ao marcar usuário offline: %s", e)

            # Broadcast da atualização de presença offline
            presence_frame = {
                "event": "user.presence",
                "payload": {
                    "user_id": str(authenticated_user_id),
                    "status": "offline",
                },
            }
            try:
                await manager.broadcast_to_users(
                    presence_frame, list(manager.active_connections.keys())
                )
            except Exception as e:
                logger.error("Erro ao broadcast de presença offline: %s", e)
