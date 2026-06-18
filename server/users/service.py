import uuid
from datetime import datetime, timezone
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from server.database.models import User, PrivateMessage, Friendship

class UserNotFoundError(Exception):
    """Lançada quando o usuário solicitado não existe."""
    pass

class FriendshipError(Exception):
    """Classe base para erros de amizade."""
    pass

class FriendshipAlreadyExistsError(FriendshipError):
    """Lançada quando a amizade ou solicitação já existe."""
    pass

class FriendshipNotFoundError(FriendshipError):
    """Lançada quando a amizade ou solicitação não existe."""
    pass

class UserBlockedError(FriendshipError):
    """Lançada quando a ação é barrada devido a um bloqueio."""
    pass

def obter_perfil(db: Session, user_id: uuid.UUID) -> User:
    """
    Retorna os dados cadastrais do perfil de um usuário.
    Lança UserNotFoundError se não for encontrado.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise UserNotFoundError("Usuário não encontrado.")
    return user

def atualizar_status(db: Session, user_id: uuid.UUID, status: str) -> User:
    """
    Atualiza o status de presença (online, offline, away) do usuário.
    Lança UserNotFoundError se não for encontrado.
    """
    # Validação simples de valores aceitos
    valid_statuses = {"online", "offline", "away"}
    if status not in valid_statuses:
        raise ValueError(f"Status inválido: {status}. Deve ser online, offline ou away.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise UserNotFoundError("Usuário não encontrado.")

    user.status = status
    db.flush()
    return user

def listar_usuarios_online(db: Session) -> List[User]:
    """
    Retorna a lista de todos os usuários que não estão com status offline.
    """
    return db.query(User).filter(User.status != "offline").all()

def salvar_mensagem_privada(db: Session, sender_id: uuid.UUID, receiver_id: uuid.UUID, content: str) -> PrivateMessage:
    """
    Cria e persiste uma mensagem privada (DM) no banco de dados.
    """
    db_pmsg = PrivateMessage(
        id=uuid.uuid4(),
        sender_id=sender_id,
        receiver_id=receiver_id,
        content=content,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(db_pmsg)
    db.flush()
    return db_pmsg

def enviar_solicitacao_amizade(db: Session, sender_id: uuid.UUID, receiver_id: uuid.UUID) -> Friendship:
    """
    Envia uma solicitação de amizade do remetente para o destinatário.
    Auto-aceita se já existir uma solicitação inversa pendente.
    """
    if sender_id == receiver_id:
        raise FriendshipError("Você não pode enviar uma solicitação de amizade para si mesmo.")

    # Verifica se o destinatário existe
    receiver = db.query(User).filter(User.id == receiver_id).first()
    if not receiver:
        raise UserNotFoundError("Usuário destinatário não encontrado.")

    # Busca amizade/solicitação existente em qualquer direção
    f = db.query(Friendship).filter(
        or_(
            and_(Friendship.user_id == sender_id, Friendship.friend_id == receiver_id),
            and_(Friendship.user_id == receiver_id, Friendship.friend_id == sender_id)
        )
    ).first()

    if f:
        if f.status == "accepted":
            raise FriendshipAlreadyExistsError("Vocês já são amigos.")
        elif f.status == "pending":
            if f.user_id == sender_id:
                raise FriendshipAlreadyExistsError("Já existe uma solicitação de amizade pendente enviada por você.")
            else:
                # O destinatário já tinha enviado uma solicitação ao remetente: auto-aceita
                f.status = "accepted"
                db.flush()
                return f
        elif f.status == "blocked":
            if f.user_id == sender_id:
                raise FriendshipError("Você bloqueou este usuário. Desbloqueie-o primeiro.")
            else:
                raise UserBlockedError("Você foi bloqueado por este usuário.")

    friendship = Friendship(
        user_id=sender_id,
        friend_id=receiver_id,
        status="pending",
        created_at=datetime.now(timezone.utc)
    )
    db.add(friendship)
    db.flush()
    return friendship

def aceitar_solicitacao_amizade(db: Session, receiver_id: uuid.UUID, sender_id: uuid.UUID) -> Friendship:
    """
    Aceita uma solicitação de amizade recebida.
    """
    f = db.query(Friendship).filter(
        Friendship.user_id == sender_id,
        Friendship.friend_id == receiver_id,
        Friendship.status == "pending"
    ).first()

    if not f:
        raise FriendshipNotFoundError("Solicitação de amizade pendente não encontrada.")

    f.status = "accepted"
    db.flush()
    return f

def rejeitar_solicitacao_amizade(db: Session, receiver_id: uuid.UUID, sender_id: uuid.UUID) -> None:
    """
    Rejeita uma solicitação de amizade recebida (exclui a linha pendente).
    """
    f = db.query(Friendship).filter(
        Friendship.user_id == sender_id,
        Friendship.friend_id == receiver_id,
        Friendship.status == "pending"
    ).first()

    if not f:
        raise FriendshipNotFoundError("Solicitação de amizade pendente não encontrada.")

    db.delete(f)
    db.flush()

def remover_amigo(db: Session, user_id: uuid.UUID, friend_id: uuid.UUID) -> None:
    """
    Remove uma amizade ativa existente.
    Deleta todas as linhas que correspondem ao par (user_id, friend_id) em
    qualquer combinação direcional, garantindo que nenhuma entrada órfã
    permaneça visível para nenhuma das partes.
    """
    rows = db.query(Friendship).filter(
        or_(
            and_(Friendship.user_id == user_id, Friendship.friend_id == friend_id),
            and_(Friendship.user_id == friend_id, Friendship.friend_id == user_id)
        ),
        Friendship.status == "accepted"
    ).all()

    if not rows:
        raise FriendshipNotFoundError("Amizade ativa não encontrada.")

    for row in rows:
        db.delete(row)
    db.flush()

def listar_amigos(db: Session, user_id: uuid.UUID) -> List[User]:
    """
    Retorna a lista de amigos do usuário.
    """
    fs = db.query(Friendship).filter(
        or_(Friendship.user_id == user_id, Friendship.friend_id == user_id),
        Friendship.status == "accepted"
    ).all()

    friends = []
    for f in fs:
        if f.user_id == user_id:
            friends.append(f.friend)
        else:
            friends.append(f.user)
    return friends

def listar_solicitacoes_pendentes(db: Session, user_id: uuid.UUID) -> List[User]:
    """
    Retorna a lista de usuários que enviaram solicitação pendente para o usuário informado.
    """
    fs = db.query(Friendship).filter(
        Friendship.friend_id == user_id,
        Friendship.status == "pending"
    ).all()
    return [f.user for f in fs]

def bloquear_usuario(db: Session, user_id: uuid.UUID, target_id: uuid.UUID) -> Friendship:
    """
    Bloqueia um usuário (desfaz amizades/solicitações pendentes e cria o bloqueio).
    """
    if user_id == target_id:
        raise FriendshipError("Você não pode bloquear a si mesmo.")

    target = db.query(User).filter(User.id == target_id).first()
    if not target:
        raise UserNotFoundError("Usuário alvo não encontrado.")

    f = db.query(Friendship).filter(
        or_(
            and_(Friendship.user_id == user_id, Friendship.friend_id == target_id),
            and_(Friendship.user_id == target_id, Friendship.friend_id == user_id)
        )
    ).first()

    if f:
        f.user_id = user_id
        f.friend_id = target_id
        f.status = "blocked"
    else:
        f = Friendship(
            user_id=user_id,
            friend_id=target_id,
            status="blocked",
            created_at=datetime.now(timezone.utc)
        )
        db.add(f)

    db.flush()
    return f

def desbloquear_usuario(db: Session, user_id: uuid.UUID, target_id: uuid.UUID) -> None:
    """
    Desbloqueia um usuário previamente bloqueado por este usuário.
    """
    f = db.query(Friendship).filter(
        Friendship.user_id == user_id,
        Friendship.friend_id == target_id,
        Friendship.status == "blocked"
    ).first()

    if not f:
        raise FriendshipNotFoundError("Bloqueio ativo não encontrado.")

    db.delete(f)
    db.flush()

