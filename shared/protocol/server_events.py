from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class AuthSuccessPayload(BaseModel):
    """Payload para o evento 'auth.success'."""

    user_id: UUID = Field(..., description="UUID do usuário autenticado")
    username: str = Field(..., description="Nome de usuário do usuário autenticado")


class AttachmentResponsePayload(BaseModel):
    """Payload contendo os detalhes de um anexo associado a uma mensagem."""

    id: UUID = Field(..., description="UUID do anexo")
    url: str = Field(..., description="URL para download do anexo")
    filename: str = Field(..., description="Nome original do arquivo")
    file_size: int = Field(..., description="Tamanho do arquivo em bytes")
    mime_type: str = Field(..., description="Tipo MIME do arquivo")


class MessageReceivePayload(BaseModel):
    """Payload para o evento 'message.receive'."""

    id: UUID = Field(..., description="UUID gerado para a mensagem")
    room_id: Optional[UUID] = Field(None, description="UUID da sala, ou None se for uma DM")
    sender_id: UUID = Field(..., description="UUID do usuário remetente")
    sender_name: str = Field(..., description="Nome do usuário remetente")
    content: str = Field(..., description="Conteúdo textual da mensagem")
    timestamp: datetime = Field(..., description="Carimbo de data/hora no padrão ISO 8601")
    attachment: Optional[AttachmentResponsePayload] = Field(None, description="Dados do anexo caso exista")


class UserPresencePayload(BaseModel):
    """Payload para o evento 'user.presence'."""

    user_id: UUID = Field(..., description="UUID do usuário cuja presença mudou")
    status: str = Field(..., description="Status de presença ('online' ou 'offline')")
    room_id: Optional[UUID] = Field(None, description="UUID da sala (opcional)")
    role: Optional[str] = Field(None, description="Papel do usuário na sala (opcional)")


class ErrorAlertPayload(BaseModel):
    """Payload para o evento 'error.alert'."""

    code: int = Field(..., description="Código numérico representativo do erro")
    message: str = Field(..., description="Mensagem descritiva explicando o erro")


class RoomMemberRolePayload(BaseModel):
    """Payload para o evento 'room.member_role'."""

    room_id: UUID = Field(..., description="UUID da sala")
    user_id: UUID = Field(..., description="UUID do usuário afetado")
    role: str = Field(..., description="Novo papel do usuário (owner, admin, member)")


class DmStartSuccessPayload(BaseModel):
    """Payload para o evento 'dm.start_success'."""

    receiver_id: UUID = Field(..., description="UUID do destinatário")
    receiver_name: str = Field(..., description="Nome de usuário do destinatário")


class RoomCreatedPayload(BaseModel):
    """Payload para o evento 'room.created' — confirma criação de sala via WS."""

    room_id: UUID = Field(..., description="UUID da sala criada")
    room_name: str = Field(..., description="Nome da sala criada")
    message: Optional[str] = Field(None, description="Mensagem opcional de confirmação")


class FriendRequestReceivedPayload(BaseModel):
    """Payload para o evento 'friend.request_received'."""

    sender_id: UUID = Field(..., description="UUID do solicitante")
    sender_name: str = Field(..., description="Nome de usuário do solicitante")


class FriendAcceptedPayload(BaseModel):
    """Payload para o evento 'friend.accepted'."""

    user_id: UUID = Field(..., description="UUID do usuário que aceitou a amizade")
    username: str = Field(..., description="Nome de usuário de quem aceitou a amizade")


class FriendRemovedPayload(BaseModel):
    """Payload para o evento 'friend.removed'."""

    user_id: UUID = Field(..., description="UUID do usuário que foi removido da lista de amigos")
    username: str = Field(..., description="Nome de usuário do amigo removido")


class UserTypingBroadcastPayload(BaseModel):
    """
    P1-3: Payload para o evento 'user.typing_broadcast' (server → client).

    Servidor retransmite para os outros participantes quando um usuário
    está digitando. O cliente mostra "X está digitando..." por alguns segundos.

    Campos:
        user_id (UUID): UUID de quem está digitando.
        username (str): Nome de quem está digitando.
        room_id (Optional[UUID]): Sala onde está digitando, ou None se for DM.
        receiver_id (Optional[UUID]): Para DMs, UUID do destinatário.
    """
    user_id: UUID = Field(..., description="UUID de quem está digitando")
    username: str = Field(..., description="Nome de quem está digitando")
    room_id: Optional[UUID] = Field(None, description="Sala (ou None para DM)")
    receiver_id: Optional[UUID] = Field(None, description="Destinatário da DM")
