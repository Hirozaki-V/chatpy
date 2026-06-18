import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
from server.database.connection import get_db_api
from server.database.models import User, Room, RoomMember, Message
from server.api.dependencies import get_current_user
from server.rooms.service import (
    criar_sala,
    listar_salas,
    entrar_sala,
    sair_sala,
    obter_historico_sala,
    promover_membro,
    remover_admin,
    expulsar_membro,
    banir_membro,
    listar_membros,
    RoomError,
    RoomNotFoundError,
    AlreadyMemberError,
    NotMemberError,
    RoomAccessDeniedError,
)

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


class CreateRoomRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    is_private: bool = Field(False)
    password: Optional[str] = Field(None)
    description: Optional[str] = Field(None, max_length=255)


class RoomResponse(BaseModel):
    id: str
    name: str
    is_private: bool
    description: Optional[str] = None
    created_at: str


class JoinRoomRequest(BaseModel):
    password: Optional[str] = Field(None)


class MessageResponse(BaseModel):
    id: str
    room_id: str
    sender_id: str
    sender_name: str
    content: str
    timestamp: str


@router.post("", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
def create_new_room(
    req: CreateRoomRequest,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Cria uma nova sala de chat e associa o usuário criador como administrador."""
    try:
        room = criar_sala(db, req.name, req.is_private, req.password, current_user.id, req.description)
        db.commit()
        return RoomResponse(
            id=str(room.id),
            name=room.name,
            is_private=room.is_private,
            description=room.description,
            created_at=room.created_at.isoformat(),
        )
    except RoomError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("", response_model=List[RoomResponse])
def get_rooms_list(db: Session = Depends(get_db_api), current_user: User = Depends(get_current_user)):
    """Retorna a lista de todas as salas de chat disponíveis."""
    rooms = listar_salas(db)
    return [
        RoomResponse(
            id=str(r.id),
            name=r.name,
            is_private=r.is_private,
            description=r.description,
            created_at=r.created_at.isoformat(),
        ) for r in rooms
    ]


@router.post("/{room_id}/join", status_code=status.HTTP_200_OK)
def join_room_endpoint(
    room_id: uuid.UUID,
    req: JoinRoomRequest,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Adiciona o usuário autenticado na sala especificada."""
    try:
        entrar_sala(db, current_user.id, room_id, req.password)
        db.commit()
        return {"status": "success", "message": "Ingressou na sala com sucesso."}
    except RoomNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AlreadyMemberError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RoomAccessDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except RoomError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{room_id}/leave", status_code=status.HTTP_200_OK)
def leave_room_endpoint(
    room_id: uuid.UUID,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Remove o usuário autenticado da sala informada."""
    try:
        sair_sala(db, current_user.id, room_id)
        db.commit()
        return {"status": "success", "message": "Saiu da sala com sucesso."}
    except NotMemberError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RoomError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{room_id}/history", response_model=List[MessageResponse])
def get_room_history(
    room_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """
    Retorna o histórico paginado de mensagens enviadas para a sala informada.
    O usuário deve ser membro da sala para visualizar o histórico.
    """
    # Valida se o usuário é membro da sala
    member = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == current_user.id,
    ).first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você precisa ser membro da sala para visualizar seu histórico de mensagens.",
        )

    try:
        messages = obter_historico_sala(db, room_id, limit, offset)
        # FIX N+1: pré-carrega todos os senders em uma única query e monta um dict
        sender_ids = {m.sender_id for m in messages}
        sender_map: dict = {}
        if sender_ids:
            users = db.query(User).filter(User.id.in_(sender_ids)).all()
            sender_map = {u.id: u.username for u in users}

        return [
            MessageResponse(
                id=str(m.id),
                room_id=str(m.room_id),
                sender_id=str(m.sender_id),
                sender_name=sender_map.get(m.sender_id, "Desconhecido"),
                content=m.content,
                timestamp=m.timestamp.isoformat(),
            ) for m in messages
        ]
    except RoomNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


class MemberResponse(BaseModel):
    user_id: str
    username: str
    role: str
    joined_at: str


@router.get("/{room_id}/members", response_model=List[MemberResponse])
def get_room_members(
    room_id: uuid.UUID,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Retorna a lista de membros ativos da sala com seus respectivos papéis."""
    member = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == current_user.id,
        RoomMember.is_banned == False,
    ).first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você precisa ser membro ativo da sala para listar seus membros.",
        )

    try:
        membros_data = listar_membros(db, room_id)
        return [
            MemberResponse(
                user_id=str(user.id),
                username=user.username,
                role=member_rec.role,
                joined_at=member_rec.joined_at.isoformat(),
            ) for member_rec, user in membros_data
        ]
    except RoomNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


class UpdateRoleRequest(BaseModel):
    role: str = Field(..., description="Papel do usuário (admin ou member)")


@router.put("/{room_id}/members/{user_id}/role", status_code=status.HTTP_200_OK)
def update_member_role(
    room_id: uuid.UUID,
    user_id: uuid.UUID,
    req: UpdateRoleRequest,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Altera o papel de um membro na sala. Apenas o owner da sala pode realizar essa alteração."""
    if req.role not in ("admin", "member"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Papel inválido. Deve ser 'admin' ou 'member'.",
        )

    try:
        if req.role == "admin":
            promover_membro(db, room_id, user_id, current_user.id)
        else:
            remover_admin(db, room_id, user_id, current_user.id)
        db.commit()
        return {"status": "success", "message": f"Papel do usuário atualizado para {req.role}."}
    except RoomNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except NotMemberError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except RoomAccessDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except RoomError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{room_id}/members/{user_id}", status_code=status.HTTP_200_OK)
def remove_room_member(
    room_id: uuid.UUID,
    user_id: uuid.UUID,
    ban: bool = Query(False),
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Expulsa (kick) ou bane um membro da sala. Requer papel 'owner' ou 'admin'."""
    try:
        if ban:
            banir_membro(db, room_id, user_id, current_user.id)
            msg = "Membro banido com sucesso."
        else:
            expulsar_membro(db, room_id, user_id, current_user.id)
            msg = "Membro expulso com sucesso."
        db.commit()
        return {"status": "success", "message": msg}
    except RoomNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except NotMemberError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except RoomAccessDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except RoomError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


class ExploreRoomResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_private: bool
    has_password: bool
    members_count: int
    online_count: int


@router.get("/explore", response_model=List[ExploreRoomResponse])
def explore_rooms_endpoint(
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """
    Retorna a lista de todas as salas públicas e privadas registradas no servidor.
    FIX N+1: usa subqueries agregadas em vez de uma query por sala.
    """
    from sqlalchemy import func, case

    # Query única que retorna rooms + contagens agregadas
    rows = (
        db.query(
            Room.id,
            Room.name,
            Room.description,
            Room.is_private,
            Room.password_hash,
            func.count(
                case(
                    (RoomMember.is_banned == False, RoomMember.user_id),
                )
            ).label("members_count"),
            func.count(
                case(
                    (
                        (RoomMember.is_banned == False) & (User.status != "offline"),
                        RoomMember.user_id,
                    ),
                )
            ).label("online_count"),
        )
        .outerjoin(RoomMember, RoomMember.room_id == Room.id)
        .outerjoin(User, User.id == RoomMember.user_id)
        .group_by(Room.id, Room.name, Room.description, Room.is_private, Room.password_hash)
        .all()
    )

    return [
        ExploreRoomResponse(
            id=str(r.id),
            name=r.name,
            description=r.description,
            is_private=r.is_private,
            has_password=r.password_hash is not None,
            members_count=int(r.members_count or 0),
            online_count=int(r.online_count or 0),
        )
        for r in rows
    ]


class UpdateRoomRequest(BaseModel):
    is_private: Optional[bool] = Field(None, description="Altera privacidade da sala")
    password: Optional[str] = Field(None, description="Nova senha da sala (ou string vazia para remover a senha)")
    description: Optional[str] = Field(None, description="Nova descrição da sala")


@router.put("/{room_id}", response_model=RoomResponse)
def update_room_settings(
    room_id: uuid.UUID,
    req: UpdateRoomRequest,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Atualiza as configurações de uma sala. Apenas owner ou admin pode alterar."""
    from server.auth.security import hash_password

    member = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == current_user.id,
        RoomMember.is_banned == False,
    ).first()

    if not member or member.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores ou proprietários podem alterar as configurações da sala.",
        )

    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sala não encontrada.",
        )

    if req.is_private is not None:
        room.is_private = req.is_private

    if req.password is not None:
        if req.password == "":
            room.password_hash = None
        else:
            # Valida força da senha da sala (mínimo 4 chars, não aplica regras completas)
            if len(req.password) < 4:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Senha da sala deve ter no mínimo 4 caracteres.",
                )
            room.password_hash = hash_password(req.password)

    if req.description is not None:
        room.description = req.description

    db.commit()
    return RoomResponse(
        id=str(room.id),
        name=room.name,
        is_private=room.is_private,
        description=room.description,
        created_at=room.created_at.isoformat(),
    )
