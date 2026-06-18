from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from server.database.connection import get_db_api
from server.database.models import User
from server.api.dependencies import get_current_user
from server.users.service import obter_perfil, atualizar_status, listar_usuarios_online

router = APIRouter(prefix="/api/users", tags=["users"])


class UserProfileResponse(BaseModel):
    id: str
    username: str
    status: str
    created_at: str


class UpdateStatusRequest(BaseModel):
    status: str = Field(..., description="Novo status do usuário: online, offline, away")


@router.get("/me", response_model=UserProfileResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Retorna os detalhes do perfil do usuário autenticado atual."""
    return UserProfileResponse(
        id=str(current_user.id),
        username=current_user.username,
        status=current_user.status,
        created_at=current_user.created_at.isoformat(),
    )


@router.get("/online", response_model=List[UserProfileResponse])
def get_online_users(db: Session = Depends(get_db_api), current_user: User = Depends(get_current_user)):
    """Retorna a lista de todos os usuários que estão com status de presença ativo (diferente de offline)."""
    online_users = listar_usuarios_online(db)
    return [
        UserProfileResponse(
            id=str(u.id),
            username=u.username,
            status=u.status,
            created_at=u.created_at.isoformat(),
        ) for u in online_users
    ]


@router.put("/status", response_model=UserProfileResponse)
def update_my_status(
    req: UpdateStatusRequest,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Permite ao usuário autenticado atualizar seu próprio status de presença."""
    try:
        updated_user = atualizar_status(db, current_user.id, req.status)
        db.commit()
        return UserProfileResponse(
            id=str(updated_user.id),
            username=updated_user.username,
            status=updated_user.status,
            created_at=updated_user.created_at.isoformat(),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
