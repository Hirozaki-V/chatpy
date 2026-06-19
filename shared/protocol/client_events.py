from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

class AuthAuthenticatePayload(BaseModel):
    """
    Payload para o evento 'auth.authenticate'.
    
    Este evento é enviado pelo cliente imediatamente após a abertura da conexão
    WebSocket para autenticar a sessão do usuário associando o canal à sua identidade.
    
    Campos:
        token (str): Token JWT de acesso válido obtido no login REST API.
    """
    token: str = Field(..., description="Token JWT de acesso da sessão do usuário")

class MessageSendRoomPayload(BaseModel):
    """
    Payload para o evento 'message.send_room'.
    
    Enviado pelo cliente para transmitir uma mensagem pública ou protegida em uma
    sala de chat na qual ele já ingressou.
    
    Campos:
        room_id (UUID): Identificador único da sala destinatária.
        content (str): Texto da mensagem digitada pelo usuário.
        attachment_id (Optional[UUID]): UUID do anexo associado (opcional).
    """
    room_id: UUID = Field(..., description="UUID da sala destinatária")
    content: str = Field(..., max_length=5000, description="Conteúdo textual da mensagem")
    attachment_id: Optional[UUID] = Field(None, description="UUID do anexo associado")

class MessageSendPrivatePayload(BaseModel):
    """
    Payload para o evento 'message.send_private'.
    
    Enviado pelo cliente para mandar uma mensagem direta/privada (DM) a outro usuário.
    
    Campos:
        receiver_id (UUID): Identificador único do usuário destinatário.
        content (str): Conteúdo de texto confidencial/privado da mensagem.
        attachment_id (Optional[UUID]): UUID do anexo associado (opcional).
    """
    receiver_id: UUID = Field(..., description="UUID do usuário destinatário")
    content: str = Field(..., max_length=5000, description="Conteúdo textual da mensagem privada")
    attachment_id: Optional[UUID] = Field(None, description="UUID do anexo associado")

class RoomJoinPayload(BaseModel):
    """
    Payload para o evento 'room.join'.
    
    Enviado pelo cliente quando ele deseja se juntar a uma sala (pública ou protegida por senha).
    
    Campos:
        room_name (str): Nome identificador da sala (normalmente prefixada com #, ex: '#geral').
        password (Optional[str]): Senha da sala (opcional, exigida apenas para salas protegidas).
    """
    room_name: str = Field(..., max_length=50, description="Nome da sala na qual deseja ingressar")
    password: Optional[str] = Field(None, max_length=128, description="Senha de acesso caso seja uma sala protegida")

class RoomCreatePayload(BaseModel):
    """
    Payload para o evento 'room.create'.
    
    Enviado pelo cliente para criar uma nova sala via WebSocket.
    """
    room_name: str = Field(..., min_length=2, max_length=50, description="Nome da sala a ser criada")
    is_private: bool = Field(False, description="Se a sala é privada/protegida por senha")
    password: Optional[str] = Field(None, max_length=128, description="Senha da sala se for privada")

class DmStartPayload(BaseModel):
    """
    Payload para o evento 'dm.start'.

    Enviado pelo cliente para iniciar um chat privado (DM) diretamente com um usuário.
    """
    receiver_id: UUID = Field(..., description="UUID do usuário destinatário")


class UserTypingPayload(BaseModel):
    """
    P1-3: Payload para o evento 'user.typing' (client → server).

    Enviado pelo cliente quando o usuário está digitando numa sala ou DM.
    O servidor retransmite como 'user.typing_broadcast' para os outros
    participantes, que mostram "X está digitando..." por alguns segundos.

    Campos:
        room_id (Optional[UUID]): UUID da sala, ou None se for DM.
        receiver_id (Optional[UUID]): UUID do destinatário da DM (se for DM).
    """
    room_id: Optional[UUID] = Field(None, description="UUID da sala (ou None para DM)")
    receiver_id: Optional[UUID] = Field(None, description="UUID do destinatário da DM")


class MessageSendFederatedPayload(BaseModel):
    """
    P2-1.2d: Payload para o evento 'message.send_federated' (client → server).

    Enviado pelo cliente para mandar uma DM para um usuário em outro
    servidor (ex: @user@outro-servidor.com). O servidor local identifica
    o peer pelo domínio e encaminha via HTTP.

    Campos:
        receiver_username (str): Username federado completo (ex: @bob@outro.com)
        content (str): Conteúdo da mensagem
    """
    receiver_username: str = Field(..., description="Username federado: @user@dominio")
    content: str = Field(..., description="Conteúdo da mensagem")


class MessageReactionPayload(BaseModel):
    """
    Priority 3: Payload para o evento 'message.reaction' (client → server).

    Enviado pelo cliente para reagir (ou remover reação) a uma mensagem.
    O servidor valida e retransmite para todos os membros da sala.

    Campos:
        room_id (UUID): UUID da sala onde está a mensagem
        message_id (UUID): UUID da mensagem a reagir
        emoji (str): Emoji da reação (ex: "👍", "❤️")
    """
    room_id: UUID = Field(..., description="UUID da sala")
    message_id: UUID = Field(..., description="UUID da mensagem")
    emoji: str = Field(..., min_length=1, max_length=10, description="Emoji da reação")
