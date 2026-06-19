from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from server.database.connection import get_db_api
from server.database.models import User
from server.api.dependencies import get_current_user, require_admin
from server.users.service import obter_perfil, atualizar_status, listar_usuarios_online

router = APIRouter(prefix="/api/users", tags=["users"])


class UserProfileResponse(BaseModel):
    id: str
    username: str
    status: str
    created_at: str
    is_admin: bool = False
    is_guest: bool = False


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
        is_admin=getattr(current_user, "is_admin", False),
        is_guest=getattr(current_user, "is_guest", False),
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
            is_admin=getattr(u, "is_admin", False),
            is_guest=getattr(u, "is_guest", False),
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
            is_admin=getattr(updated_user, "is_admin", False),
            is_guest=getattr(updated_user, "is_guest", False),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ---------------------------------------------------------------------------
# P0-FIX: Endpoints de administração de usuários (promover/rebaixar admin)
# ---------------------------------------------------------------------------

class PromoteAdminRequest(BaseModel):
    username: str = Field(..., description="Username a promover/rebaixar")


@router.post("/admin/promote", tags=["admin"])
def promote_to_admin(
    req: PromoteAdminRequest,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(require_admin),
):
    """
    P0-FIX: Promove um usuário existente a administrador. Requer admin.

    Caso de uso: o operador criou uma conta no setup.py (que vira admin
    automaticamente) e quer promover outro usuário sem mexer no SQL.

    Não permite promover guests (contas efêmeras não devem ter poder admin).
    """
    target = db.query(User).filter(User.username.ilike(req.username)).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado.")
    if getattr(target, "is_guest", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuários convidados não podem ser promovidos a administrador.",
        )
    target.is_admin = True
    db.commit()
    return {"status": "success", "message": f"Usuário '{target.username}' promovido a administrador."}


@router.post("/admin/demote", tags=["admin"])
def demote_admin(
    req: PromoteAdminRequest,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(require_admin),
):
    """Rebaixa um administrador a usuário comum. Requer admin."""
    target = db.query(User).filter(User.username.ilike(req.username)).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado.")
    if str(target.id) == str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Você não pode rebaixar a si mesmo (evita lock-out acidental).",
        )
    target.is_admin = False
    db.commit()
    return {"status": "success", "message": f"Usuário '{target.username}' rebaixado para usuário comum."}
