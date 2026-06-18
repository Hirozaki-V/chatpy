import uuid
from datetime import datetime, timezone
from typing import List, Tuple, Optional
from sqlalchemy.orm import Session
from server.database.models import Room, RoomMember, Message, User
from server.auth.security import hash_password, verify_password

class RoomError(Exception):
    """Classe base para erros relacionados a salas."""
    pass

class RoomNotFoundError(RoomError):
    """Lançada quando a sala não é encontrada."""
    pass

class AlreadyMemberError(RoomError):
    """Lançada quando o usuário já é membro da sala."""
    pass

class NotMemberError(RoomError):
    """Lançada quando o usuário não pertence à sala."""
    pass

class RoomAccessDeniedError(RoomError):
    """Lançada quando o acesso à sala protegida é negado (senha incorreta)."""
    pass

def criar_sala(db: Session, name: str, is_private: bool, password: Optional[str], creator_id: uuid.UUID, description: Optional[str] = None) -> Room:
    """
    Cria uma nova sala e adiciona o criador como proprietário (owner).
    Lança RoomError se o nome da sala já estiver em uso.
    """
    # Garante o prefixo '#' no nome da sala
    if not name.startswith("#"):
        name = f"#{name}"

    existing = db.query(Room).filter(Room.name == name).first()
    if existing:
        raise RoomError("Nome de sala já em uso.")

    pwd_hash = None
    if is_private and password:
        pwd_hash = hash_password(password)

    room = Room(
        id=uuid.uuid4(),
        name=name,
        is_private=is_private,
        password_hash=pwd_hash,
        description=description,
        created_at=datetime.now(timezone.utc)
    )
    db.add(room)
    db.flush()

    # Adiciona criador como proprietário
    member = RoomMember(
        room_id=room.id,
        user_id=creator_id,
        role="owner",
        joined_at=datetime.now(timezone.utc)
    )
    db.add(member)
    db.flush()

    return room

def listar_salas(db: Session) -> List[Room]:
    """
    Retorna a lista de todas as salas registradas no sistema.
    """
    return db.query(Room).all()

def entrar_sala(db: Session, user_id: uuid.UUID, room_id: uuid.UUID, password: Optional[str]) -> RoomMember:
    """
    Adiciona um usuário como membro de uma sala.
    Valida a senha se a sala for protegida.
    Rejeita se o usuário for banido.
    """
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise RoomNotFoundError("Sala não encontrada.")

    # Verifica se já é membro ou está banido
    member = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == user_id
    ).first()
    if member:
        if member.is_banned:
            raise RoomAccessDeniedError("Você foi banido desta sala.")
        raise AlreadyMemberError("Usuário já é membro desta sala.")

    # Verifica senha para salas privadas
    if room.is_private:
        if not room.password_hash or not password:
            raise RoomAccessDeniedError("Esta sala é protegida e exige uma senha.")
        if not verify_password(password, room.password_hash):
            raise RoomAccessDeniedError("Senha de acesso incorreta.")

    member = RoomMember(
        room_id=room_id,
        user_id=user_id,
        role="member",
        joined_at=datetime.now(timezone.utc),
        is_banned=False
    )
    db.add(member)
    db.flush()

    return member

def sair_sala(db: Session, user_id: uuid.UUID, room_id: uuid.UUID):
    """
    Remove o usuário de uma sala.
    """
    member = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == user_id
    ).first()
    if not member:
        raise NotMemberError("Usuário não é membro desta sala.")

    db.delete(member)
    db.flush()

def obter_historico_sala(db: Session, room_id: uuid.UUID, limit: int = 50, offset: int = 0) -> List[Message]:
    """
    Retorna o histórico de mensagens de uma sala de forma paginada, ordenado pelas mensagens mais recentes.
    """
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise RoomNotFoundError("Sala não encontrada.")

    return db.query(Message).filter(Message.room_id == room_id)\
        .order_by(Message.timestamp.desc())\
        .offset(offset)\
        .limit(limit)\
        .all()

def salvar_mensagem(db: Session, room_id: uuid.UUID, sender_id: uuid.UUID, content: str) -> Message:
    """
    Cria e persiste uma mensagem de sala no banco de dados.
    """
    db_msg = Message(
        id=uuid.uuid4(),
        room_id=room_id,
        sender_id=sender_id,
        content=content,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(db_msg)
    db.flush()
    return db_msg

def promover_membro(db: Session, room_id: uuid.UUID, target_user_id: uuid.UUID, current_user_id: uuid.UUID) -> RoomMember:
    """
    Promove um membro comum a 'admin/moderador'. Apenas o 'owner' pode realizar esta ação.
    """
    requester = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == current_user_id,
        RoomMember.is_banned == False
    ).first()
    if not requester or requester.role != "owner":
        raise RoomAccessDeniedError("Apenas o proprietário da sala pode promover membros.")

    target = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == target_user_id,
        RoomMember.is_banned == False
    ).first()
    if not target:
        raise NotMemberError("Usuário alvo não é membro ativo desta sala.")

    if target.role == "owner":
        raise RoomError("Não é possível alterar o papel do proprietário.")

    target.role = "admin"
    db.flush()
    return target

def remover_admin(db: Session, room_id: uuid.UUID, target_user_id: uuid.UUID, current_user_id: uuid.UUID) -> RoomMember:
    """
    Rebaixa um admin/moderador para membro comum. Apenas o 'owner' pode realizar esta ação.
    """
    requester = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == current_user_id,
        RoomMember.is_banned == False
    ).first()
    if not requester or requester.role != "owner":
        raise RoomAccessDeniedError("Apenas o proprietário da sala pode remover administradores.")

    target = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == target_user_id,
        RoomMember.is_banned == False
    ).first()
    if not target:
        raise NotMemberError("Usuário alvo não é membro ativo desta sala.")

    if target.role == "owner":
        raise RoomError("Não é possível alterar o papel do proprietário.")

    target.role = "member"
    db.flush()
    return target

def expulsar_membro(db: Session, room_id: uuid.UUID, target_user_id: uuid.UUID, current_user_id: uuid.UUID):
    """
    Expulsa um membro da sala. Requer papel 'owner' ou 'admin'.
    """
    requester = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == current_user_id,
        RoomMember.is_banned == False
    ).first()
    if not requester or requester.role not in ("owner", "admin"):
        raise RoomAccessDeniedError("Permissão de moderação negada.")

    target = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == target_user_id,
        RoomMember.is_banned == False
    ).first()
    if not target:
        raise NotMemberError("Usuário alvo não é membro ativo desta sala.")

    # Valida hierarquia
    if target.role == "owner":
        raise RoomAccessDeniedError("Não é possível expulsar o proprietário da sala.")
    if requester.role == "admin" and target.role == "admin":
        raise RoomAccessDeniedError("Administradores não podem expulsar outros administradores.")

    db.delete(target)
    db.flush()

def banir_membro(db: Session, room_id: uuid.UUID, target_user_id: uuid.UUID, current_user_id: uuid.UUID) -> RoomMember:
    """
    Bane um membro da sala. Requer papel 'owner' ou 'admin'.
    """
    requester = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == current_user_id,
        RoomMember.is_banned == False
    ).first()
    if not requester or requester.role not in ("owner", "admin"):
        raise RoomAccessDeniedError("Permissão de moderação negada.")

    target = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == target_user_id
    ).first()

    # Valida hierarquia
    if target:
        if target.role == "owner":
            raise RoomAccessDeniedError("Não é possível banir o proprietário da sala.")
        if requester.role == "admin" and target.role == "admin":
            raise RoomAccessDeniedError("Administradores não podem banir outros administradores.")

        target.is_banned = True
        target.role = "member"
        db.flush()
        return target
    else:
        # Se não for membro atual, cria o registro como banido
        new_ban = RoomMember(
            room_id=room_id,
            user_id=target_user_id,
            role="member",
            joined_at=datetime.now(timezone.utc),
            is_banned=True
        )
        db.add(new_ban)
        db.flush()
        return new_ban

def listar_membros(db: Session, room_id: uuid.UUID) -> List[Tuple[RoomMember, User]]:
    """
    Retorna a lista de membros ativos (não banidos) e seus papéis na sala.
    """
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise RoomNotFoundError("Sala não encontrada.")

    return db.query(RoomMember, User).join(User, User.id == RoomMember.user_id).filter(
        RoomMember.room_id == room_id,
        RoomMember.is_banned == False
    ).all()
