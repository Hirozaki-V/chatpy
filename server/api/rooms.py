import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
# Optional já importado acima
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from server.database.connection import get_db_api
from server.database.models import User, Room, RoomMember, Message, MessageReaction
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
    # SECURITY: name e description NÃO podem conter < > ' " para evitar
    # stored XSS no painel admin (que renderiza via innerHTML) e em
    # qualquer outro cliente que renderize HTML sem escapar. Antes, o
    # schema aceitava strings livres — bug crítico que permitia account
    # takeover de admin via room name malicioso. Ver auditoria-2026-06.
    name: str = Field(..., min_length=2, max_length=50, pattern=r"^[^<>\"'\\\\]+$")
    is_private: bool = Field(False)
    password: Optional[str] = Field(None)
    description: Optional[str] = Field(None, max_length=255, pattern=r"^[^<>\"'\\\\]*$")


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
    # #7: Guests não podem criar salas PRIVADAS (podem criar públicas).
    # Salas privadas exigem senha e são mais propensas a abuso por contas
    # efêmeras (compartilhamento de conteúdo sem rastreabilidade).
    if getattr(current_user, 'is_guest', False) and req.is_private:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuários convidados não podem criar salas privadas. "
                   "Crie uma conta permanente para acessar este recurso.",
        )

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
    before_id: Optional[uuid.UUID] = Query(None, description="Cursor pagination: retorna mensagens anteriores a este ID"),
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """
    Retorna o histórico paginado de mensagens enviadas para a sala informada.
    O usuário deve ser membro da sala para visualizar o histórico.

    P1-FIX: suporta paginação por cursor via parâmetro `before_id`. Quando
    fornecido, retorna mensagens com ID estritamente menor que before_id,
    ordenadas da mais nova para a mais velha. Isto evita o problema de
    paginação por offset em chats ativos: se novas mensagens chegam enquanto
    o usuário rola o histórico, offset desliza e causa duplicação/skip.
    Cursor pagination é estável independente de inserções concorrentes.

    Mantemos `offset` para backward compatibility, mas `before_id` tem
    precedência quando ambos são fornecidos.
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
        if before_id is not None:
            # P1-FIX: cursor pagination via timestamp.
            # Buscamos a mensagem com ID = before_id para obter seu timestamp,
            # e retornamos mensagens com timestamp estritamente menor (ou
            # igual com ID diferente, para evitar duplicação).
            # Isto é estável mesmo com UUIDs v4 aleatórios — ordenamos por
            # (timestamp DESC, id DESC) e filtramos por timestamp.
            cursor_msg = db.query(Message).filter(Message.id == before_id).first()
            if cursor_msg is None:
                # ID de cursor inválido — retorna vazio (cliente deve resetar)
                messages = []
            else:
                cursor_ts = cursor_msg.timestamp
                messages = (
                    db.query(Message)
                    .filter(
                        Message.room_id == room_id,
                        Message.timestamp < cursor_ts,
                    )
                    .order_by(Message.timestamp.desc(), Message.id.desc())
                    .limit(limit)
                    .all()
                )
        else:
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

    # #7: Guests não podem ser promovidos a admin (contas efêmeras não devem
    # ter poder de moderação — podem abusar e expirar a qualquer momento).
    if req.role == "admin":
        target_user = db.query(User).filter(User.id == user_id).first()
        if target_user and getattr(target_user, 'is_guest', False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuários convidados não podem ser promovidos a administrador.",
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
    # SECURITY: same pattern as CreateRoomRequest.description — rejeita
    # caracteres que poderiam quebrar innerHTML no admin.
    description: Optional[str] = Field(None, max_length=255, pattern=r"^[^<>\"'\\\\]*$")


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


# ---------------------------------------------------------------------------
# Busca de mensagens (Priority 3)
# ---------------------------------------------------------------------------
class SearchMessagesRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200, description="Termo de busca")
    limit: int = Field(20, ge=1, le=100, description="Número máximo de resultados")
    before_id: Optional[str] = Field(None, description="Cursor: retorna resultados anteriores a este ID")


class SearchResultResponse(BaseModel):
    id: str
    room_id: str
    room_name: str
    sender_id: str
    sender_name: str
    content: str
    timestamp: str


@router.post("/search", response_model=List[SearchResultResponse])
def search_messages(
    req: SearchMessagesRequest,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """
    Busca mensagens em todas as salas que o usuário é membro.
    Retorna até `limit` resultados contendo o termo de busca (case-insensitive).
    O usuário só vê mensagens de salas onde é membro ativo.
    """
    # Busca em salas onde o usuário é membro ativo (não banido)
    member_room_ids = [
        rm.room_id for rm in db.query(RoomMember.room_id).filter(
            RoomMember.user_id == current_user.id,
            RoomMember.is_banned == False,
        ).all()
    ]

    if not member_room_ids:
        return []

    # Busca case-insensitive no conteúdo das mensagens
    # SECURITY: escapa wildcards do LIKE (% e _) para prevenir bypass
    # de busca (ex: "%" retorna todas as mensagens)
    _escaped = req.query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    search_term = f"%{_escaped}%"

    # P1-FIX: paginação por cursor — se before_id fornecido, busca o
    # timestamp da mensagem cursor e filtra mensagens anteriores.
    query = (
        db.query(Message, Room)
        .join(Room, Room.id == Message.room_id)
        .filter(
            Message.room_id.in_(member_room_ids),
            Message.content.ilike(search_term, escape="\\"),
        )
    )

    if req.before_id:
        cursor_msg = db.query(Message).filter(Message.id == req.before_id).first()
        if cursor_msg:
            query = query.filter(Message.timestamp < cursor_msg.timestamp)

    messages = (
        query
        .order_by(Message.timestamp.desc())
        .limit(req.limit)
        .all()
    )

    # Pré-carrega senders (evita N+1)
    sender_ids = {m.sender_id for m, _ in messages}
    sender_map = {}
    if sender_ids:
        users = db.query(User).filter(User.id.in_(sender_ids)).all()
        sender_map = {u.id: u.username for u in users}

    return [
        SearchResultResponse(
            id=str(msg.id),
            room_id=str(msg.room_id),
            room_name=room.name,
            sender_id=str(msg.sender_id),
            sender_name=sender_map.get(msg.sender_id, "Desconhecido"),
            content=msg.content,
            timestamp=msg.timestamp.isoformat(),
        )
        for msg, room in messages
    ]


# ---------------------------------------------------------------------------
# Reações em mensagens (Priority 3)
# ---------------------------------------------------------------------------
# SECURITY: allowlist de emojis seguros — previne injeção de sequências
# Unicode perigosas (ZWJ,combinações de modificadores, etc.)
ALLOWED_EMOJIS = {
    # Positivos
    "\U0001f44d", "\U0001f44e", "\U0001f44d\u200d\U0001f3fb",  # 👍 👎 👍🏻
    "\U0001f44e\u200d\U0001f3fb",  # 👎🏻
    "\u2764\ufe0f", "\U0001f494", "\U0001f495", "\U0001f496", "\U0001f497",  # ❤️ 💔 💕 💖 💗
    "\U0001f60a", "\U0001f60d", "\U0001f602", "\U0001f605", "\U0001f606",  # 😊 😍 😂 😅 😆
    "\U0001f60e", "\U0001f61c", "\U0001f61d", "\U0001f609", "\U0001f60f",  # 😎 😜 🤙 😉 😏
    "\U0001f621", "\U0001f620", "\U0001f624", "\U0001f625", "\U0001f629",  # 😡 😠 😤 😥 😩
    "\U0001f62d", "\U0001f631", "\U0001f628", "\U0001f62c", "\U0001f610",  # 😭 😱 😬 😬 😐
    "\U0001f4af", "\U0001f525", "\U0001f44e\u200d\U0001f4a5",  # 💯 🔥 👎💥
    "\U0001f389", "\U0001f38a", "\U0001f381", "\U0001f388",  # 🎉 🎊 🎁 🎈
    "\U0001f44d\u200d\U0001f52c", "\U0001f44d\u200d\U0001f680",  # 👍🔬 👍🚀
    "\U0001f680", "\U0001f4a4", "\U0001f4a3", "\U0001f440",  # 🚀 💤 💣 👀
    "\u2b50", "\U0001f31f", "\U0001f4ab", "\U0001f4a1",  # ⭐ 🌟 💫 💡
    "\U0001f64f", "\U0001f64c", "\U0001f91d", "\U0001f91f",  # 🙏 👏 🤝 🤟
    "\U0001f44b", "\U0001f44a", "\U0001f595", "\U0001f596",  # 👋 👊 🖕 🖖
    "\u2705", "\u274c", "\u26a0\ufe0f", "\u2753", "\u2757",  # ✅ ❌ ⚠️ ❓ ❗
    "\U0001f44d", "\U0001f44e", "\U0001f44f", "\U0001f643",  # 👍 👎 👏 🙃
    "\U0001f914", "\U0001f923", "\U0001f970", "\U0001f973",  # 🤔 🤣 🥰 🥳
    "\U0001f600", "\U0001f603", "\U0001f604", "\U0001f601",  # 😃 😃 😄 😁
}


class ReactionRequest(BaseModel):
    emoji: str = Field(..., min_length=1, max_length=10, description="Emoji da reação")


@router.post("/{room_id}/messages/{message_id}/reactions")
def add_reaction(
    room_id: uuid.UUID,
    message_id: uuid.UUID,
    req: ReactionRequest,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Adiciona uma reação (emoji) a uma mensagem. Toggle: se já existe, remove."""
    # SECURITY: valida emoji contra allowlist — previne injeção de sequências
    # Unicode perigosas (ZWJ, modificadores, etc.)
    if req.emoji not in ALLOWED_EMOJIS:
        raise HTTPException(
            status_code=400,
            detail="Emoji não permitido. Use um dos emojis da lista suportada.",
        )

    # Valida que a mensagem pertence à sala
    msg = db.query(Message).filter(
        Message.id == message_id,
        Message.room_id == room_id,
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada.")

    # Valida que o usuário é membro da sala
    member = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == current_user.id,
        RoomMember.is_banned == False,
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Você não é membro desta sala.")

    # Toggle: se já reagiu com este emoji, remove; senão, adiciona
    existing = db.query(MessageReaction).filter(
        MessageReaction.message_id == message_id,
        MessageReaction.user_id == current_user.id,
        MessageReaction.emoji == req.emoji,
    ).first()

    if existing:
        db.delete(existing)
        db.commit()
        return {"status": "removed", "emoji": req.emoji}
    else:
        reaction = MessageReaction(
            message_id=message_id,
            user_id=current_user.id,
            emoji=req.emoji,
        )
        db.add(reaction)
        db.commit()
        return {"status": "added", "emoji": req.emoji}


@router.get("/{room_id}/messages/{message_id}/reactions")
def get_reactions(
    room_id: uuid.UUID,
    message_id: uuid.UUID,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Retorna todas as reações de uma mensagem agrupadas por emoji."""
    msg = db.query(Message).filter(
        Message.id == message_id,
        Message.room_id == room_id,
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada.")

    reactions = db.query(MessageReaction).filter(
        MessageReaction.message_id == message_id,
    ).all()

    # Pré-carrega usernames em batch (evita N+1 queries)
    user_ids = list({r.user_id for r in reactions})
    users_map = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        users_map = {u.id: u.username for u in users}

    # Agrupa por emoji
    grouped = {}
    for r in reactions:
        if r.emoji not in grouped:
            grouped[r.emoji] = []
        grouped[r.emoji].append({
            "user_id": str(r.user_id),
            "username": users_map.get(r.user_id, "Desconhecido"),
        })

    return {"reactions": grouped}
