import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from server.database.connection import get_db_api
from server.database.models import User, Friendship
from server.api.dependencies import get_current_user
from server.users.service import (
    enviar_solicitacao_amizade,
    aceitar_solicitacao_amizade,
    rejeitar_solicitacao_amizade,
    remover_amigo,
    listar_amigos,
    listar_solicitacoes_pendentes,
    bloquear_usuario,
    desbloquear_usuario,
    UserNotFoundError,
    FriendshipError,
    FriendshipAlreadyExistsError,
    FriendshipNotFoundError,
    UserBlockedError
)
from shared.events import EventType

router = APIRouter(prefix="/api/friends", tags=["friends"])

class FriendRequestSchema(BaseModel):
    receiver_username: str = Field(..., description="Nome do usuário destinatário")

class FriendResponseSchema(BaseModel):
    id: str
    username: str
    status: str

class FriendshipResponseSchema(BaseModel):
    user_id: str
    friend_id: str
    status: str
    created_at: str

@router.post("/request", response_model=FriendshipResponseSchema, status_code=status.HTTP_201_CREATED)
async def send_friend_request(
    req: FriendRequestSchema,
    request: Request,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user)
):
    """
    Envia uma solicitação de amizade a outro usuário.
    Se o destinatário estiver online, envia uma notificação WebSocket em tempo real.
    """
    receiver = db.query(User).filter(User.username == req.receiver_username).first()
    if not receiver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário destinatário não encontrado."
        )

    try:
        friendship = enviar_solicitacao_amizade(db, current_user.id, receiver.id)
        db.commit()

        # Envia notificação em tempo real via WebSocket se o manager estiver ativo e o destinatário online
        manager = getattr(request.app.state, "manager", None)
        if manager and friendship.status == "pending":
            ws_notification = {
                "event": EventType.FRIEND_REQUEST_RECEIVED.value,
                "payload": {
                    "sender_id": str(current_user.id),
                    "sender_name": current_user.username
                }
            }
            await manager.send_personal_message(ws_notification, receiver.id)

        return FriendshipResponseSchema(
            user_id=str(friendship.user_id),
            friend_id=str(friendship.friend_id),
            status=friendship.status,
            created_at=friendship.created_at.isoformat()
        )

    except FriendshipAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except UserBlockedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except FriendshipError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except UserNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.get("/requests/pending", response_model=List[FriendResponseSchema])
def get_pending_requests(
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user)
):
    """
    Retorna a lista de solicitações de amizade pendentes recebidas.
    """
    senders = listar_solicitacoes_pendentes(db, current_user.id)
    return [
        FriendResponseSchema(
            id=str(u.id),
            username=u.username,
            status=u.status
        ) for u in senders
    ]

@router.post("/request/{sender_id}/accept", response_model=FriendshipResponseSchema)
async def accept_friend_request(
    sender_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user)
):
    """
    Aceita a solicitação de amizade pendente enviada por sender_id.
    """
    try:
        friendship = aceitar_solicitacao_amizade(db, current_user.id, sender_id)
        db.commit()

        # Notifica o remetente em tempo real via WebSocket se estiver online
        manager = getattr(request.app.state, "manager", None)
        if manager:
            ws_notification = {
                "event": EventType.FRIEND_ACCEPTED.value,
                "payload": {
                    "user_id": str(current_user.id),
                    "username": current_user.username
                }
            }
            await manager.send_personal_message(ws_notification, sender_id)

        return FriendshipResponseSchema(
            user_id=str(friendship.user_id),
            friend_id=str(friendship.friend_id),
            status=friendship.status,
            created_at=friendship.created_at.isoformat()
        )
    except FriendshipNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FriendshipError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/request/{sender_id}/reject")
def reject_friend_request(
    sender_id: uuid.UUID,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user)
):
    """
    Rejeita a solicitação de amizade pendente enviada por sender_id.
    """
    try:
        rejeitar_solicitacao_amizade(db, current_user.id, sender_id)
        db.commit()
        return {"status": "success", "message": "Solicitação de amizade rejeitada."}
    except FriendshipNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FriendshipError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.get("", response_model=List[FriendResponseSchema])
def get_friends_list(
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user)
):
    """
    Retorna a lista de todos os amigos ativos (aceitos).
    """
    friends = listar_amigos(db, current_user.id)
    return [
        FriendResponseSchema(
            id=str(u.id),
            username=u.username,
            status=u.status
        ) for u in friends
    ]

@router.delete("/{friend_id}")
async def delete_friend(
    friend_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user)
):
    """
    Desfaz a amizade ativa com friend_id e notifica ambos os usuários via WebSocket
    para que as listas de amigos sejam atualizadas de forma reativa em tempo real.
    """
    # Carrega o objeto do amigo antes de deletar para montar os payloads WS
    friend = db.query(User).filter(User.id == friend_id).first()
    if not friend:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado."
        )

    try:
        remover_amigo(db, current_user.id, friend_id)
        db.commit()

        # Propaga o evento FRIEND_REMOVED para ambas as partes simultaneamente
        manager = getattr(request.app.state, "manager", None)
        if manager:
            import asyncio
            notify_initiator = {
                "event": EventType.FRIEND_REMOVED.value,
                "payload": {
                    "user_id": str(friend_id),
                    "username": friend.username
                }
            }
            notify_removed = {
                "event": EventType.FRIEND_REMOVED.value,
                "payload": {
                    "user_id": str(current_user.id),
                    "username": current_user.username
                }
            }
            await asyncio.gather(
                manager.send_personal_message(notify_initiator, current_user.id),
                manager.send_personal_message(notify_removed, friend_id),
                return_exceptions=True
            )

        return {"status": "success", "message": "Amizade desfeita com sucesso."}
    except FriendshipNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FriendshipError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/{user_id}/block", response_model=FriendshipResponseSchema)
def block_user_endpoint(
    user_id: uuid.UUID,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user)
):
    """
    Bloqueia o usuário correspondente a user_id.
    """
    try:
        friendship = bloquear_usuario(db, current_user.id, user_id)
        db.commit()
        return FriendshipResponseSchema(
            user_id=str(friendship.user_id),
            friend_id=str(friendship.friend_id),
            status=friendship.status,
            created_at=friendship.created_at.isoformat()
        )
    except UserNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FriendshipError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/{user_id}/unblock")
def unblock_user_endpoint(
    user_id: uuid.UUID,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user)
):
    """
    Desbloqueia o usuário correspondente a user_id.
    """
    try:
        desbloquear_usuario(db, current_user.id, user_id)
        db.commit()
        return {"status": "success", "message": "Usuário desbloqueado com sucesso."}
    except FriendshipNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FriendshipError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
