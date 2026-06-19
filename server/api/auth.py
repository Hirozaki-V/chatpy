from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from server.database.connection import get_db_api
from server.database.models import User, Session as DbSessionModel
from server.api.dependencies import get_current_user
from server.auth.service import (
    registrar_usuario,
    registrar_usuario_guest,
    autenticar_usuario,
    revogar_sessao,
    UsernameTakenError,
    InvalidCredentialsError,
    ValidationError,
    TooManyAttemptsError,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# Schema PERMISSIVO para login — aceita qualquer senha e deixa o banco decidir.
# Isso é importante para não bloquear usuários antigos que tenham senhas curtas
# criadas antes da validação de força ser adicionada.
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


# Schema RIGOROSO para registro — aplica validação de força de senha.
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)


class AuthSuccessResponse(BaseModel):
    status: str
    token: str


class RegisterSuccessResponse(BaseModel):
    status: str
    user_id: str
    username: str


class LogoutResponse(BaseModel):
    status: str
    message: str


@router.post("/register", response_model=RegisterSuccessResponse, status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db_api)):
    """
    Endpoint para cadastrar um novo usuário no ChatPy.
    Aplica validação de username e força de senha (mínimo 8 chars, com letra e número).
    """
    # #1: Rate limit agressivo para endpoints sensíveis (10 req/min por IP).
    from server.rest_rate_limit import check_sensitive_endpoint
    check_sensitive_endpoint(request)

    try:
        user = registrar_usuario(db, req.username, req.password)
        db.commit()
        return RegisterSuccessResponse(
            status="success",
            user_id=str(user.id),
            username=user.username,
        )
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except UsernameTakenError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/guest", response_model=AuthSuccessResponse, status_code=status.HTTP_201_CREATED)
def create_guest_account(request: Request, db: Session = Depends(get_db_api)):
    """
    P2-2: Cria uma conta de CONVIDADO efêmera — sem senha, sem email, sem
    dados pessoais. Username é gerado aleatoriamente (ex: guest_a7b3x9q2).
    Expira após GUEST_TTL_HOURS (default 24h).

    Caso de uso: "entrar e falar" sem cadastro — alinha com o objetivo do
    projeto de ser anônimo. O cliente recebe um token JWT imediatamente e
    pode usar todas as features públicas (entrar em #geral, mandar DM para
    amigos que aceitarem solicitação, etc.).

    #1: Rate limit agressivo (10 req/min por IP) — evita abuso de criação
    massiva de contas guest.

    Limitações para guests (implementado em #7):
      - Não podem criar salas privadas
      - Não podem ser admin/owner de salas
      - Não podem enviar anexos > 1 MB
      - Conta some após GUEST_TTL_HOURS
    """
    # #1: Rate limit agressivo para endpoints sensíveis
    from server.rest_rate_limit import check_sensitive_endpoint
    check_sensitive_endpoint(request)

    try:
        user, token = registrar_usuario_guest(db)
        db.commit()
        return AuthSuccessResponse(status="success", token=token)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao criar conta de convidado: {e}",
        )


@router.post("/login", response_model=AuthSuccessResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db_api)):
    """
    Endpoint para autenticar um usuário e receber um JWT de acesso.

    Não aplica validação de força de senha aqui — apenas verifica contra o hash
    Argon2 armazenado no banco. Isso permite que usuários existentes com senhas
    criadas antes da validação rigorosa continuem conseguindo logar.

    Inclui proteção anti brute-force PERSISTENTE (P0-8): limite/janela/lockout
    configuráveis via env (LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS,
    LOGIN_LOCK_SECONDS). O contador sobrevive a restarts (SQLite).
    """
    # T1-FIX: captura IP para auditoria de forma segura.
    # Antes confiávamos cegamente em X-Forwarded-For, permitindo spoofing.
    # Agora só confiamos no header se veio de proxy confiável (TRUSTED_PROXIES).
    from server.security_ip import get_client_ip
    ip_address = get_client_ip(request)
    if ip_address == "unknown":
        ip_address = None

    # #1: Rate limit agressivo para login (10 req/min por IP) — complementa
    # o anti brute-force por username (P0-8). Atacante que tenta 100 usernames
    # do mesmo IP é bloqueado aqui antes de testar o anti brute-force por user.
    from server.rest_rate_limit import check_sensitive_endpoint
    check_sensitive_endpoint(request)

    try:
        token = autenticar_usuario(db, req.username, req.password, ip_address=ip_address)
        db.commit()
        return AuthSuccessResponse(status="success", token=token)
    except TooManyAttemptsError as e:
        # Persiste qualquer tentativa registrada antes do raise
        try:
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e),
            headers={"Retry-After": "600"},
        )
    except InvalidCredentialsError as e:
        # P0-8: COMITA explicitamente para persistir a tentativa falha no banco.
        # Sem isto, o get_db() via rollback() descartaria o INSERT feito em
        # _record_failed_login, e o anti brute-force não funcionaria.
        try:
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except ValidationError as e:
        # Não deveria acontecer no login, mas por segurança
        try:
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


class LogoutRequest(BaseModel):
    token: str = Field(..., description="Token JWT a ser revogado")


@router.post("/logout", response_model=LogoutResponse)
def logout(
    req: LogoutRequest,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """
    Endpoint para logout: revoga a sessão atual no banco de dados.
    Recebe o token JWT no body JSON. Idempotente — retorna sucesso mesmo se já revogado.

    CORREÇÃO DE SEGURANÇA: agora exige autenticação via `current_user`. Antes,
    o endpoint era público, permitindo que qualquer cliente enviasse tokens
    arbitrários e forçasse logout de sessões alheias (ataque de negação de
    serviço). A dependência `get_current_user` valida assinatura JWT + sessão
    ativa no banco, e a revogação abaixo só remove o token enviado no body
    se ele pertencer ao mesmo usuário autenticado.
    """
    # Remove prefixo "Bearer " caso presente
    clean_token = req.token.removeprefix("Bearer ").strip()

    # Valida que o token enviado no body pertence ao usuário autenticado
    # (evita que um cliente autenticado revogue sessões de outros usuários)
    db_session = db.query(DbSessionModel).filter(
        DbSessionModel.token == clean_token,
        DbSessionModel.user_id == current_user.id,
    ).first()
    if not db_session:
        # Não revela se o token existe ou não — apenas retorna idempotente
        return LogoutResponse(status="success", message="Sessão revogada com sucesso.")

    try:
        revogar_sessao(db, clean_token)
        db.commit()
    except Exception:
        db.rollback()
    return LogoutResponse(status="success", message="Sessão revogada com sucesso.")
