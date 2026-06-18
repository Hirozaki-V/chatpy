from fastapi import APIRouter, Depends, HTTPException, status, Body
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from server.database.connection import get_db_api
from server.database.models import User, Session as DbSessionModel
from server.api.dependencies import get_current_user
from server.auth.service import (
    registrar_usuario,
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
def register(req: RegisterRequest, db: Session = Depends(get_db_api)):
    """
    Endpoint para cadastrar um novo usuário no ChatPy.
    Aplica validação de username e força de senha (mínimo 8 chars, com letra e número).
    """
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


@router.post("/login", response_model=AuthSuccessResponse)
def login(req: LoginRequest, db: Session = Depends(get_db_api)):
    """
    Endpoint para autenticar um usuário e receber um JWT de acesso.

    Não aplica validação de força de senha aqui — apenas verifica contra o hash
    Argon2 armazenado no banco. Isso permite que usuários existentes com senhas
    criadas antes da validação rigorosa continuem conseguindo logar.

    Inclui proteção anti brute-force: 5 tentativas / 5 min, depois 10 min de lockout.
    """
    try:
        token = autenticar_usuario(db, req.username, req.password)
        db.commit()
        return AuthSuccessResponse(status="success", token=token)
    except TooManyAttemptsError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e),
            headers={"Retry-After": "600"},
        )
    except InvalidCredentialsError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except ValidationError as e:
        # Não deveria acontecer no login, mas por segurança
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
