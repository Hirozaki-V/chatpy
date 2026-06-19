from uuid import UUID
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session as DBSession
from server.database.connection import get_db_api
from server.database.models import User, Session
from server.auth.security import decode_access_token

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: DBSession = Depends(get_db_api),
) -> User:
    """
    Dependência FastAPI que extrai o token JWT, valida a sua assinatura
    e verifica na base de dados se a sessão permanece ativa e não expirada.
    """
    token = credentials.credentials
    claims = decode_access_token(token)
    if not claims or "sub" not in claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de acesso inválido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(claims["sub"])
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identificador de usuário inválido no token.",
        )

    # Validação da sessão ativa no banco de dados (permite revogação imediata)
    db_session = db.query(Session).filter(
        Session.token == token,
        Session.user_id == user_id,
    ).first()

    if not db_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão revogada ou inexistente na base de dados.",
        )

    # Compatibilidade de timezone (SQLite armazena naive datetime)
    expires_at = db_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < datetime.now(timezone.utc):
        # Limpa sessões expiradas automaticamente
        db.delete(db_session)
        db.flush()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A sessão expirou.",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário associado ao token não encontrado.",
        )

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    P0-FIX: Dependência que exige que o usuário autenticado seja admin.

    Usada para proteger endpoints /api/admin/* (peers federados, backups,
    futuras ações administrativas). Antes, qualquer usuário autenticado
    podia cadastrar peers maliciosos, deletar todos os peers, ou forçar
    backups — risco grave de segurança e DoS.

    Para tornar um usuário admin:
      - Via setup.py: o primeiro usuário criado é marcado como admin
      - Via SQL: UPDATE users SET is_admin = 1 WHERE username = 'admin'
      - Via CLI futura: chatpy-admin promote <username>
    """
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado. Esta operação requer privilégios de administrador.",
        )
    return current_user
