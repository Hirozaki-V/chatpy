import os
import logging
from datetime import datetime, timezone
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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
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
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


# ---------------------------------------------------------------------------
# Validação obrigatória de JWT_SECRET em startup (fail-fast)
# ---------------------------------------------------------------------------
def _validate_jwt_secret():
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError(
            "A variável de ambiente 'JWT_SECRET' é obrigatória. "
            "Crie um arquivo .env com JWT_SECRET=<chave-aleatória-longa> ou "
            "export JWT_SECRET=... antes de iniciar o servidor."
        )
    if len(secret) < 16:
        raise RuntimeError("'JWT_SECRET' deve ter no mínimo 16 caracteres.")


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

    cleanup_task = asyncio.create_task(_attachment_cleanup_loop())
    logger.info("Tarefa de limpeza de anexos órfãos iniciada (intervalo: 1h).")

    # Expõe no app.state para shutdown
    app.state._cleanup_task = cleanup_task

    yield

    # === SHUTDOWN ===
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("Servidor ChatPy desligado com sucesso.")


async def _attachment_cleanup_loop():
    """Loop que executa a limpeza de anexos órfãos a cada 1 hora."""
    while True:
        try:
            await asyncio.to_thread(cleanup_orphan_attachments)
        except Exception as e:
            logger.error("Erro no job de limpeza de anexos: %s", e)
        await asyncio.sleep(3600)


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
if "*" in _cors_origins:
    _cors_origins_resolved = ["*"]
else:
    _cors_origins_resolved = list(_cors_origins)
    # Adiciona origens comuns para servidores LAN (apenas se não estiver usando *)
    try:
        import socket
        local_ip = socket.gethostbyname(socket.gethostname())
        if local_ip and not local_ip.startswith("127."):
            _cors_origins_resolved.append(f"http://{local_ip}:5000")
            _cors_origins_resolved.append(f"http://{local_ip}")
    except Exception:
        pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins_resolved,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Middleware de logging de erros não tratados
# ---------------------------------------------------------------------------
@app.middleware("http")
async def _error_logger(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logger.error(
            "Erro não tratado em %s %s: %s",
            request.method,
            request.url.path,
            e,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Erro interno do servidor."},
        )


# ---------------------------------------------------------------------------
# Healthcheck endpoint
# ---------------------------------------------------------------------------
@app.get("/health", tags=["health"])
async def health_check():
    """
    Healthcheck para Docker e load balancers.
    Verifica conexão com o banco de dados.
    """
    try:
        from server.database.connection import get_db
        from server.database.models import User
        with get_db() as db:
            db.query(User).first()
        return {"status": "healthy", "database": "ok", "version": "2.0.1"}
    except Exception as e:
        logger.error("Healthcheck falhou: %s", e)
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "error", "detail": str(e)},
        )


@app.get("/", tags=["root"])
async def root():
    """Endpoint raiz — redireciona para /docs."""
    return {"name": "ChatPy V2 Server", "docs": "/docs", "health": "/health"}


# ---------------------------------------------------------------------------
# Registro das rotas REST
# ---------------------------------------------------------------------------
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(rooms_router)
app.include_router(friends_router)
app.include_router(attachments_router)


# ---------------------------------------------------------------------------
# WebSocket — instância global de manager/rate_limiter/dispatcher
# ---------------------------------------------------------------------------
manager = ConnectionManager()
app.state.manager = manager
rate_limiter = RateLimiter()
dispatcher = WebSocketDispatcher(manager, rate_limiter)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Rota WebSocket principal para comunicação real-time baseada em eventos.
    Lida com o ciclo de vida completo da conexão, autenticação, dispatching
    e atualização reativa de presença de usuários offline na desconexão.
    """
    await websocket.accept()
    authenticated_user_id = None

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
